import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Literal
from uuid import UUID, uuid4
from time import perf_counter
import time
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, HttpUrl
import requests
from sqlalchemy.orm import Session
from app.api import deps
from app.core.config import settings
from app.models.user import User
from app.models.setting import Setting
from app.schemas.setting import (
    GoogleOAuthConfigResponse,
    GoogleOAuthConfigUpdate,
    MicrosoftOAuthConfigResponse,
    MicrosoftOAuthConfigUpdate,
    Setting as SettingSchema,
    SettingUpdate,
)
from app.services.tls import warn_ssl_verification_disabled
from app.services.ocr_fallback import fallback_configuration_error, resolve_fallback_api_key
from app.services.ocr_configuration_test import run_ocr_configuration_test
from app.services.typesafe import typesafe_config_source
from app.utils.activity_logger import log_activity, Actions
from app.utils.redact import is_masked, mask_secret
from app.utils.secret_store import SecretStoreError, encrypt_secret

router = APIRouter()
logger = logging.getLogger(__name__)
BUILD_INFO_PATH = Path(__file__).resolve().parents[4] / ".build-info.json"


class MappingPolicy(BaseModel):
    engine: Literal["auto", "softnix", "llm", "fixed", "jev"] = "auto"
    fallback_provider_id: UUID | None = None
    fallback_enabled: bool = True


@router.get("/mapping/config")
def read_mapping_policy(db: Session = Depends(deps.get_db),
                        current_user: User = Depends(deps.get_current_active_superuser)):
    setting = db.query(Setting).first()
    return {"engine": getattr(setting, "mapping_engine", "auto"),
            "fallback_provider_id": getattr(setting, "mapping_fallback_provider_id", None),
            "fallback_enabled": getattr(setting, "mapping_fallback_enabled", True)}


@router.put("/mapping/config")
def save_mapping_policy(payload: MappingPolicy, db: Session = Depends(deps.get_db),
                        current_user: User = Depends(deps.get_current_active_superuser)):
    from app.models.ai_settings import AISettings
    if payload.fallback_provider_id:
        provider = db.query(AISettings).filter(AISettings.id == payload.fallback_provider_id,
            AISettings.is_active.is_(True), AISettings.provider_type == "openai_compatible").first()
        if provider is None:
            raise HTTPException(422, "Choose an active OpenAI-compatible mapping provider")
    setting = db.query(Setting).first()
    if setting is None:
        raise HTTPException(422, "Save OCR configuration first")
    before = (setting.mapping_engine, str(setting.mapping_fallback_provider_id or ""), bool(setting.mapping_fallback_enabled))
    setting.mapping_engine = payload.engine
    setting.mapping_fallback_provider_id = str(payload.fallback_provider_id) if payload.fallback_provider_id else None
    setting.mapping_fallback_enabled = payload.fallback_enabled
    db.commit()
    if before != (setting.mapping_engine, str(setting.mapping_fallback_provider_id or ""), bool(setting.mapping_fallback_enabled)):
        _queue_engine_change_tests(db)
    return payload


def _queue_engine_change_tests(db: Session) -> None:
    """Re-run stored test sets so schema owners can see how the new engine performs.

    One message is published here; the worker finds the schemas and queues
    their runs, so a Redis or broker outage cannot stall saving the policy.
    """
    from app.tasks.schema_studio_tasks import queue_engine_change_tests_task

    if not settings.SCHEMA_TEST_AUTO_RUN:
        return
    try:
        queue_engine_change_tests_task.apply_async(retry=False)
    except Exception:  # noqa: BLE001 — the policy is saved; only the automatic re-test is missed
        logger.warning("Could not queue test runs after the mapping engine changed", exc_info=True)


@router.post("/mapping/test", status_code=202)
def start_mapping_test(current_user: User = Depends(deps.get_current_active_superuser)):
    import redis
    from app.tasks.document_tasks import test_mapping_providers_task
    run_id = str(uuid4())
    key = f"mapping_test:{current_user.id}:{run_id}"
    client = redis.from_url(settings.REDIS_URL)
    try:
        client.set(key, json.dumps({"status": "queued"}), ex=1800)
        test_mapping_providers_task.delay(str(current_user.id), run_id)
    except Exception:
        raise HTTPException(503, "Mapping test queue unavailable")
    finally:
        client.close()
    return {"run_id": run_id}


@router.get("/mapping/test/{run_id}")
def read_mapping_test(run_id: UUID, current_user: User = Depends(deps.get_current_active_superuser)):
    import redis
    client = redis.from_url(settings.REDIS_URL)
    try:
        result = client.get(f"mapping_test:{current_user.id}:{run_id}")
    finally:
        client.close()
    if result is None:
        raise HTTPException(404, "Mapping test expired or not found")
    return json.loads(result)


def _setting_response(setting: Setting) -> SettingSchema:
    """Serialize a Setting without echoing the plaintext api_token."""
    data = SettingSchema.model_validate(setting)
    if data.api_token:
        data.api_token = mask_secret(data.api_token)
    if data.ocr_fallback_api_key:
        data.ocr_fallback_api_key = mask_secret(data.ocr_fallback_api_key)
    if data.typesafe_api_key:
        data.typesafe_api_key = mask_secret(data.typesafe_api_key)
    return data


def _set_fallback_metadata(setting: Setting) -> None:
    key, source = resolve_fallback_api_key(setting)
    setattr(setting, "ocr_fallback_configured", bool(key))
    setattr(setting, "ocr_fallback_source", source)
    setattr(setting, "typesafe_source", typesafe_config_source(setting))


def get_app_commit_sha() -> str | None:
    try:
        if not BUILD_INFO_PATH.exists():
            return None
        data = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
        sha = data.get("short_commit_sha") or data.get("commit_sha")
        if isinstance(sha, str) and sha.strip():
            return sha.strip()[:7]
    except Exception:
        return None
    return None


class EndpointTestRequest(BaseModel):
    url: HttpUrl
    token: Optional[str] = None


def _microsoft_oauth_payload(db: Session, request: Request) -> MicrosoftOAuthConfigResponse:
    from app.services.cloud_oauth import (
        DEFAULT_MICROSOFT_OAUTH_SCOPE,
        get_microsoft_oauth_config,
        resolve_public_app_url,
    )

    config = get_microsoft_oauth_config(db)
    public_app_url = resolve_public_app_url(request)
    local_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    redirect_uri = config["redirect_uri"] or (
        f"{public_app_url.rstrip('/')}{settings.API_V1_STR}/integrations/oauth/microsoft/callback"
    )
    if config["redirect_uri"]:
        parsed = urlparse(config["redirect_uri"])
        public_hostname = urlparse(public_app_url).hostname
        if parsed.hostname in local_hosts and public_hostname not in local_hosts:
            redirect_uri = f"{public_app_url.rstrip('/')}{settings.API_V1_STR}/integrations/oauth/microsoft/callback"
    secret = config["client_secret"]
    return MicrosoftOAuthConfigResponse(
        client_id=config["client_id"],
        client_secret=mask_secret(secret) if secret else None,
        tenant=config["tenant"] or "common",
        redirect_uri=redirect_uri,
        scope=config["scope"] or DEFAULT_MICROSOFT_OAUTH_SCOPE,
        configured=bool(config["client_id"] and secret and config["scope"]),
    )


def _validate_microsoft_oauth_input(payload: MicrosoftOAuthConfigUpdate) -> tuple[str, str | None, str, str | None, str]:
    tenant = payload.tenant.strip()
    if "/" in tenant or " " in tenant:
        raise HTTPException(status_code=422, detail="Tenant ต้องเป็น common, organizations, tenant ID หรือโดเมนที่ไม่มีช่องว่าง")

    redirect_uri = payload.redirect_uri.strip() if payload.redirect_uri else None
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Redirect URI ต้องเป็น URL แบบ http หรือ https")

    scope = " ".join(payload.scope.split())
    if not scope:
        raise HTTPException(status_code=422, detail="ต้องระบุ Microsoft OAuth scope")
    return payload.client_id.strip(), payload.client_secret, tenant, redirect_uri, scope


def _google_oauth_payload(db: Session, request: Request) -> GoogleOAuthConfigResponse:
    from app.services.cloud_oauth import DEFAULT_GOOGLE_OAUTH_SCOPE, get_google_oauth_config, resolve_public_app_url

    config = get_google_oauth_config(db)
    public_app_url = resolve_public_app_url(request)
    local_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    redirect_uri = config["redirect_uri"] or (
        f"{public_app_url.rstrip('/')}{settings.API_V1_STR}/integrations/oauth/google/callback"
    )
    if config["redirect_uri"]:
        parsed = urlparse(config["redirect_uri"])
        public_hostname = urlparse(public_app_url).hostname
        if parsed.hostname in local_hosts and public_hostname not in local_hosts:
            redirect_uri = f"{public_app_url.rstrip('/')}{settings.API_V1_STR}/integrations/oauth/google/callback"
    secret = config["client_secret"]
    return GoogleOAuthConfigResponse(
        client_id=config["client_id"],
        client_secret=mask_secret(secret) if secret else None,
        redirect_uri=redirect_uri,
        scope=config["scope"] or DEFAULT_GOOGLE_OAUTH_SCOPE,
        configured=bool(config["client_id"] and secret and config["scope"]),
    )


def _validate_google_oauth_input(payload: GoogleOAuthConfigUpdate) -> tuple[str, str | None, str | None, str]:
    redirect_uri = payload.redirect_uri.strip() if payload.redirect_uri else None
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Redirect URI ต้องเป็น URL แบบ http หรือ https")
    scope = " ".join(payload.scope.split())
    if not scope:
        raise HTTPException(status_code=422, detail="ต้องระบุ Google OAuth scope")
    return payload.client_id.strip(), payload.client_secret, redirect_uri, scope


@router.get("/google-oauth", response_model=GoogleOAuthConfigResponse)
def get_google_oauth_settings(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
) -> GoogleOAuthConfigResponse:
    """Return masked Google OAuth configuration for system admins only."""
    return _google_oauth_payload(db, request)


@router.put("/google-oauth", response_model=GoogleOAuthConfigResponse)
def update_google_oauth_settings(
    payload: GoogleOAuthConfigUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
) -> GoogleOAuthConfigResponse:
    """Save delegated Google OAuth configuration without exposing its secret."""
    client_id, client_secret, redirect_uri, scope = _validate_google_oauth_input(payload)
    setting = db.query(Setting).first()
    if not setting:
        setting = Setting()
        db.add(setting)
        db.flush()

    setting.google_oauth_client_id = client_id
    setting.google_oauth_redirect_uri = redirect_uri
    setting.google_oauth_scope = scope
    if client_secret and not is_masked(client_secret):
        try:
            setting.google_oauth_client_secret_encrypted = encrypt_secret(client_secret)
        except SecretStoreError as exc:
            raise HTTPException(status_code=422, detail="Google OAuth Client Secret ไม่ถูกต้อง") from exc

    db.add(setting)
    db.commit()
    db.refresh(setting)
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_SETTINGS,
        resource_type="settings",
        resource_id=setting.id,
        details={"google_oauth_configured": True},
    )
    return _google_oauth_payload(db, request)


@router.get("/microsoft-oauth", response_model=MicrosoftOAuthConfigResponse)
def get_microsoft_oauth_settings(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
) -> MicrosoftOAuthConfigResponse:
    """Return masked Microsoft OAuth configuration for system admins only."""
    return _microsoft_oauth_payload(db, request)


@router.put("/microsoft-oauth", response_model=MicrosoftOAuthConfigResponse)
def update_microsoft_oauth_settings(
    payload: MicrosoftOAuthConfigUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
) -> MicrosoftOAuthConfigResponse:
    """Save delegated Microsoft OAuth configuration without exposing its secret."""
    client_id, client_secret, tenant, redirect_uri, scope = _validate_microsoft_oauth_input(payload)
    setting = db.query(Setting).first()
    if not setting:
        setting = Setting()
        db.add(setting)
        db.flush()

    setting.microsoft_oauth_client_id = client_id
    setting.microsoft_oauth_tenant = tenant
    setting.microsoft_oauth_redirect_uri = redirect_uri
    setting.microsoft_oauth_scope = scope
    # An empty or masked value means “keep the existing encrypted secret”.
    if client_secret and not is_masked(client_secret):
        try:
            setting.microsoft_oauth_client_secret_encrypted = encrypt_secret(client_secret)
        except SecretStoreError as exc:
            raise HTTPException(status_code=422, detail="Microsoft OAuth Client Secret ไม่ถูกต้อง") from exc

    db.add(setting)
    db.commit()
    db.refresh(setting)
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_SETTINGS,
        resource_type="settings",
        resource_id=setting.id,
        details={"microsoft_oauth_configured": True, "microsoft_oauth_tenant": tenant},
    )
    return _microsoft_oauth_payload(db, request)


@router.get("/config", response_model=SettingSchema)
def get_settings(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    setting = db.query(Setting).first()
    if not setting:
        setting = Setting()
        db.add(setting)
        db.commit()
        db.refresh(setting)
    setattr(setting, "app_commit_sha", get_app_commit_sha())

    # Migrate legacy api_endpoint to new fields if needed
    if setting.api_endpoint and (not setting.ocr_endpoint or not setting.test_endpoint):
        # If api_endpoint exists but new fields don't, migrate
        if not setting.ocr_endpoint:
            setting.ocr_endpoint = setting.api_endpoint
        if not setting.test_endpoint:
            # Assume test endpoint is /me on same base URL
            setting.test_endpoint = "https://111.223.37.41:9001/me"
        db.add(setting)
        db.commit()
        db.refresh(setting)

    # Backfill defaults if missing
    if not setting.ocr_endpoint:
        setting.ocr_endpoint = "https://111.223.37.41:9001/v3/ai-process-file"
        db.add(setting)
        db.commit()
        db.refresh(setting)
    if not setting.structured_output_endpoint:
        setting.structured_output_endpoint = "https://111.223.37.41:9001/structured-output"
        db.add(setting)
        db.commit()
        db.refresh(setting)
    if not setting.schema_suggestion_endpoint:
        setting.schema_suggestion_endpoint = "https://111.223.37.41:9001/suggest-schema"
        db.add(setting)
        db.commit()
        db.refresh(setting)
    if not setting.test_endpoint:
        setting.test_endpoint = "https://111.223.37.41:9001/me"
        db.add(setting)
        db.commit()
        db.refresh(setting)

    setattr(setting, "app_commit_sha", get_app_commit_sha())
    _set_fallback_metadata(setting)
    return _setting_response(setting)


def _apply_typesafe_update(setting: Setting, payload: BaseModel) -> None:
    # Blank/masked key keeps the stored key only while the endpoint stays the
    # same — a stored key is never re-pointed at a different host. A new key
    # with a blank endpoint uses the default endpoint. Clearing the endpoint
    # without a new key drops the UI config; TYPESAFE_* env vars, if set, then
    # take over (reported back as typesafe_source="env").
    from app.services.typesafe import DEFAULT_TYPESAFE_ENDPOINT

    raw_key = (payload.typesafe_api_key or "").strip()
    new_key = raw_key if raw_key and not is_masked(raw_key) else None
    old_endpoint = (setting.typesafe_endpoint or "").strip().rstrip("/") or None
    endpoint = old_endpoint
    if "typesafe_endpoint" in payload.model_fields_set:
        endpoint = (payload.typesafe_endpoint or "").strip().rstrip("/") or None
    if endpoint is None and new_key:
        endpoint = DEFAULT_TYPESAFE_ENDPOINT
    if endpoint is None:
        setting.typesafe_endpoint = None
        setting.typesafe_api_key = None
        return
    setting.typesafe_endpoint = endpoint
    if new_key:
        setting.typesafe_api_key = new_key
    elif endpoint != old_endpoint:
        setting.typesafe_api_key = None


class TypeSafeConfigUpdate(BaseModel):
    typesafe_endpoint: Optional[str] = None
    typesafe_api_key: Optional[str] = None


@router.put("/typesafe", response_model=SettingSchema)
def update_typesafe_settings(
    *,
    db: Session = Depends(deps.get_db),
    payload: TypeSafeConfigUpdate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Save only the TypeSafe card, leaving OCR/fallback settings untouched."""
    setting = db.query(Setting).first()
    if not setting:
        setting = Setting()
        db.add(setting)
    _apply_typesafe_update(setting, payload)
    db.add(setting)
    db.commit()
    db.refresh(setting)
    setattr(setting, "app_commit_sha", get_app_commit_sha())
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_SETTINGS,
        resource_type="settings",
        resource_id=setting.id,
        details={"typesafe_endpoint": setting.typesafe_endpoint},
    )
    _set_fallback_metadata(setting)
    return _setting_response(setting)


@router.put("/config", response_model=SettingSchema)
def update_settings(
    *,
    db: Session = Depends(deps.get_db),
    payload: SettingUpdate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    setting = db.query(Setting).first()
    if not setting:
        setting = Setting()
        db.add(setting)

    # Update all fields
    setting.ocr_engine = payload.ocr_engine
    setting.model = payload.model
    setting.ocr_endpoint = payload.ocr_endpoint
    setting.structured_output_endpoint = payload.structured_output_endpoint
    setting.schema_suggestion_endpoint = payload.schema_suggestion_endpoint
    setting.test_endpoint = payload.test_endpoint
    # A masked token means the client echoed back the redacted GET response
    # without changing it — keep the stored token.
    if not is_masked(payload.api_token):
        setting.api_token = payload.api_token
    if "ocr_fallback_api_key" in payload.model_fields_set and not is_masked(payload.ocr_fallback_api_key):
        setting.ocr_fallback_api_key = payload.ocr_fallback_api_key or None
    setting.verify_ssl = payload.verify_ssl
    _apply_typesafe_update(setting, payload)

    if payload.ocr_fallback_enabled:
        fallback_error = fallback_configuration_error(setting, enabled=True)
        if fallback_error:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot enable OCR fallback: {fallback_error}. Configure a UI key or MISTRAL_API_KEY first.",
            )
    setting.ocr_fallback_enabled = payload.ocr_fallback_enabled

    # Keep legacy api_endpoint in sync with ocr_endpoint for backward compatibility
    if payload.ocr_endpoint:
        setting.api_endpoint = payload.ocr_endpoint

    db.add(setting)
    db.commit()
    db.refresh(setting)
    setattr(setting, "app_commit_sha", get_app_commit_sha())

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_SETTINGS,
        resource_type="settings",
        resource_id=setting.id,
        details={
            "ocr_engine": payload.ocr_engine,
            "model": payload.model,
            "ocr_endpoint": payload.ocr_endpoint,
            "structured_output_endpoint": payload.structured_output_endpoint,
            "schema_suggestion_endpoint": payload.schema_suggestion_endpoint,
            "test_endpoint": payload.test_endpoint,
            "ocr_fallback_enabled": payload.ocr_fallback_enabled,
        }
    )

    _set_fallback_metadata(setting)
    return _setting_response(setting)


class OCRFallbackTestRequest(BaseModel):
    api_key: Optional[str] = None


class OCRConfigurationTestRequest(BaseModel):
    ocr_endpoint: Optional[str] = None
    api_token: Optional[str] = None
    ocr_engine: Optional[str] = None
    model: Optional[str] = None
    ocr_fallback_enabled: Optional[bool] = None
    ocr_fallback_api_key: Optional[str] = None


@router.post("/ocr/test")
def test_complete_ocr_configuration(
    *,
    payload: OCRConfigurationTestRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Run file-based checks against the same OCR adapters used by Jobs."""
    saved = db.query(Setting).first()

    def selected(value: Any, saved_value: Any = None) -> Any:
        if value is None or is_masked(value):
            return saved_value
        return value

    effective = SimpleNamespace(
        ocr_endpoint=selected(payload.ocr_endpoint, getattr(saved, "ocr_endpoint", None)),
        api_endpoint=getattr(saved, "api_endpoint", None),
        api_token=selected(payload.api_token, getattr(saved, "api_token", None)),
        ocr_engine=selected(payload.ocr_engine, getattr(saved, "ocr_engine", "default")),
        model=selected(payload.model, getattr(saved, "model", "default")),
        verify_ssl=bool(getattr(saved, "verify_ssl", False)),
        ocr_fallback_enabled=(
            payload.ocr_fallback_enabled
            if payload.ocr_fallback_enabled is not None
            else bool(getattr(saved, "ocr_fallback_enabled", False))
        ),
        ocr_fallback_api_key=selected(
            payload.ocr_fallback_api_key,
            getattr(saved, "ocr_fallback_api_key", None),
        ),
    )
    return run_ocr_configuration_test(effective)


@router.post("/ocr-fallback/test")
def test_ocr_fallback(
    *,
    payload: OCRFallbackTestRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Verify the UI key, or the currently selected fallback credential."""
    setting = db.query(Setting).first()
    requested_key = payload.api_key
    if is_masked(requested_key):
        requested_key = None
    key = (requested_key or "").strip() or resolve_fallback_api_key(setting)[0]
    if not key:
        raise HTTPException(status_code=400, detail="Fallback API key is not configured")

    try:
        response = requests.get(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=15,
            verify=True,
        )
        response.raise_for_status()
        return {"ok": True, "status_code": response.status_code}
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail="Fallback API key was rejected") from exc


@router.post("/test")
def test_endpoint(
    *,
    payload: EndpointTestRequest,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Admin-only: test an external API endpoint with optional bearer token.
    """
    headers = {"accept": "application/json"}
    if payload.token:
        headers["Authorization"] = f"Bearer {payload.token}"

    try:
        warn_ssl_verification_disabled("settings endpoint test request")
        resp = requests.get(str(payload.url), headers=headers, timeout=10, verify=False)
        return {
            "status_code": resp.status_code,
            "body": resp.text,
            "headers": dict(resp.headers),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class TypeSafeTestRequest(BaseModel):
    endpoint: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/typesafe/test")
def test_typesafe_configuration(
    *,
    payload: TypeSafeTestRequest,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Verify the TypeSafe (Jev) endpoint and key with one real minimal call.

    Accepts overrides so the admin can test unsaved form values. A blank or
    masked key means "use the stored key" — and the stored key is only ever
    sent to the stored endpoint, never to a caller-supplied URL.
    """
    from app.db.session import SessionLocal
    from app.services.typesafe import TypeSafeConfigurationError, resolve_typesafe_config

    db = SessionLocal()
    try:
        setting = db.query(Setting).first()
    finally:
        db.close()
    try:
        stored = resolve_typesafe_config(setting)
    except TypeSafeConfigurationError:
        stored = None
    requested_endpoint = (payload.endpoint or "").strip().rstrip("/")
    requested_key = (payload.api_key or "").strip()
    if requested_key and not is_masked(requested_key):
        endpoint = requested_endpoint or (stored.endpoint if stored else "")
        api_key = requested_key
    elif stored and (not requested_endpoint or requested_endpoint == stored.endpoint):
        endpoint, api_key = stored.endpoint, stored.api_key
    elif stored:
        return {
            "status": "failed",
            "message": "Endpoint ถูกเปลี่ยน — กรุณากรอก API Key ใหม่เพื่อทดสอบกับ Endpoint นี้ (หรือบันทึกก่อนแล้วค่อยทดสอบ)",
            "latency_ms": None,
        }
    else:
        endpoint, api_key = requested_endpoint, ""
    if not endpoint or not api_key:
        return {
            "status": "failed",
            "message": "กรุณาระบุ TypeSafe Endpoint และ API Key ก่อนทดสอบ",
            "latency_ms": None,
        }

    started = time.perf_counter()
    try:
        resp = requests.post(
            endpoint.rstrip("/") + "/v1/systemone",
            json={
                "model": "jev-latest",
                "state": {"ping": "insightdoc-connection-test"},
                "questions": {
                    "reachable": {
                        "type": "noul",
                        "instructions": "Is this a working TypeSafe API connection test?",
                    }
                },
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            timeout=15,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code == 200:
            return {
                "status": "connected",
                "message": f"เชื่อมต่อ TypeSafe สำเร็จ ({resp.headers.get('x-typesafe-model', 'jev')})",
                "latency_ms": latency_ms,
            }
        if resp.status_code in (401, 403):
            return {"status": "failed", "message": "API Key ไม่ถูกต้องหรือไม่มีสิทธิ์", "latency_ms": latency_ms}
        return {
            "status": "failed",
            "message": f"Endpoint ตอบกลับ HTTP {resp.status_code}: {resp.text[:200]}",
            "latency_ms": latency_ms,
        }
    except requests.RequestException as exc:
        return {
            "status": "failed",
            "message": f"เชื่อมต่อไม่สำเร็จ: {exc}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
