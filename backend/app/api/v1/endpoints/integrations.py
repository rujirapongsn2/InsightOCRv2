from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Literal
from urllib.parse import urlencode, urlsplit
from uuid import UUID
from openai import AsyncOpenAI, OpenAI


def _build_llm_input(
    doc_filename: str,
    doc_input: str,
    user_prompt: Optional[str] = None,
    output_format_prompt: Optional[str] = None,
) -> str:
    """Compose the input string: [userPrompt] + OCR data + [outputFormatPrompt]."""
    parts: list[str] = []
    if user_prompt and user_prompt.strip():
        parts.append(user_prompt.strip())
    parts.append(f"Document: {doc_filename}\n\nData:\n{doc_input}")
    if output_format_prompt and output_format_prompt.strip():
        parts.append(output_format_prompt.strip())
    return "\n\n".join(parts)


def _build_combined_llm_input(
    documents: List[tuple],
    user_prompt: Optional[str] = None,
    output_format_prompt: Optional[str] = None,
) -> str:
    """Compose input with ALL documents combined into one block for cross-document validation."""
    import json as _json
    parts: list[str] = []
    if user_prompt and user_prompt.strip():
        parts.append(user_prompt.strip())
    doc_blocks = []
    for filename, data in documents:
        doc_json = _json.dumps(data, ensure_ascii=False, indent=2) if data is not None else "No data"
        doc_blocks.append(f"## Document: {filename}\n\n```json\n{doc_json}\n```")
    parts.append("\n\n---\n\n".join(doc_blocks))
    if output_format_prompt and output_format_prompt.strip():
        parts.append(output_format_prompt.strip())
    return "\n\n".join(parts)


def _supports_reasoning(model: str) -> bool:
    """Return True only for o-series OpenAI models that support reasoning.effort."""
    if not model:
        return False
    m = model.lower()
    return m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


LLMMode = Literal["responses", "chat"]
SOFTNIX_GENAI_BASE_URL = "https://genai.softnix.ai/external/openai"


def _normalize_llm_base_url(base_url: Optional[str]) -> tuple[Optional[str], Optional[LLMMode]]:
    """Accept either an OpenAI-compatible base URL or a full endpoint URL."""
    if not base_url or not base_url.strip():
        return None, None

    normalized = base_url.strip().rstrip("/")
    lower = normalized.lower()

    if lower.endswith("/chat/completions"):
        return normalized[: -len("/chat/completions")], "chat"
    if lower.endswith("/responses"):
        return normalized[: -len("/responses")], "responses"

    return normalized, None


LLM_INTEGRATION_TYPES = ("llm", "softnix_genai")


def _integration_type_value(integration: Any) -> str:
    value = getattr(integration, "type", integration)
    return value.value if hasattr(value, "value") else str(value)


def _is_llm_integration(integration: Any) -> bool:
    return _integration_type_value(integration) in LLM_INTEGRATION_TYPES


def _is_softnix_genai_integration(integration: Any) -> bool:
    return _integration_type_value(integration) == "softnix_genai"


def _llm_base_url_for_integration(integration: Any) -> Optional[str]:
    """Return the configured provider URL, with a default for Softnix GenAI."""
    config = getattr(integration, "config", None) or {}
    if _is_softnix_genai_integration(integration):
        return config.get("baseUrl") or SOFTNIX_GENAI_BASE_URL
    return config.get("baseUrl")


def _integration_api_key(integration: Any) -> Optional[str]:
    """Read an integration key, supporting encrypted and legacy values."""
    config = getattr(integration, "config", None) or {}
    encrypted = config.get("apiKeyEncrypted")
    if encrypted:
        try:
            return decrypt_secret(encrypted)
        except SecretStoreError:
            return None
    return config.get("apiKey")


def _normalize_softnix_config(integration_type: Any, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize and validate settings for Softnix GenAI."""
    normalized = dict(config or {})
    type_value = integration_type.value if hasattr(integration_type, "value") else str(integration_type)
    if type_value != "softnix_genai":
        return normalized
    api_key = str(normalized.get("apiKey") or "").strip()
    encrypted_key = normalized.get("apiKeyEncrypted")
    if api_key and not is_masked(api_key):
        normalized["apiKeyEncrypted"] = encrypt_secret(api_key)
        normalized.pop("apiKey", None)
    elif encrypted_key:
        try:
            decrypt_secret(str(encrypted_key))
        except SecretStoreError as exc:
            raise HTTPException(status_code=400, detail="API Key is invalid or cannot be decrypted") from exc
    else:
        raise HTTPException(status_code=400, detail="API Key is required for Softnix GenAI")
    model = str(normalized.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model is required for Softnix GenAI")
    normalized["model"] = model
    endpoint = str(normalized.get("baseUrl") or SOFTNIX_GENAI_BASE_URL).strip().rstrip("/")
    parsed_endpoint = urlsplit(endpoint)
    if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
        raise HTTPException(status_code=400, detail="Softnix GenAI endpoint must be a valid HTTP(S) URL")
    normalized["baseUrl"] = endpoint
    return normalized


def _build_openai_client(api_key: str, base_url: Optional[str]) -> OpenAI:
    client_kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs)


def _is_not_found_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    return status_code == 404 or "404" in str(error)


def _call_responses_api(
    client: OpenAI,
    model: str,
    input_text: str,
    instructions: Optional[str] = None,
    reasoning_effort: str = "low",
) -> str:
    create_params: Dict[str, Any] = {
        "model": model,
        "input": input_text,
    }
    if instructions and instructions.strip():
        create_params["instructions"] = instructions.strip()
    if _supports_reasoning(model):
        create_params["reasoning"] = {"effort": reasoning_effort}

    response = client.responses.create(**create_params)
    return response.output_text if hasattr(response, "output_text") else str(response)


def _call_chat_completions_api(
    client: OpenAI,
    model: str,
    input_text: str,
    instructions: Optional[str] = None,
) -> str:
    messages: List[Dict[str, str]] = []
    if instructions and instructions.strip():
        messages.append({"role": "system", "content": instructions.strip()})
    messages.append({"role": "user", "content": input_text})

    response = client.chat.completions.create(model=model, messages=messages)
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


def _call_llm_text(
    api_key: str,
    base_url: Optional[str],
    model: str,
    input_text: str,
    instructions: Optional[str] = None,
    reasoning_effort: str = "low",
    request_mode: Optional[LLMMode] = None,
) -> tuple[str, LLMMode]:
    normalized_base_url, detected_mode = _normalize_llm_base_url(base_url)
    preferred_mode = request_mode or detected_mode
    client = _build_openai_client(api_key, normalized_base_url)

    if preferred_mode == "chat":
        return _call_chat_completions_api(client, model, input_text, instructions), "chat"

    try:
        return (
            _call_responses_api(client, model, input_text, instructions, reasoning_effort),
            "responses",
        )
    except Exception as responses_error:
        if preferred_mode == "responses" or not _is_not_found_error(responses_error):
            raise

        return _call_chat_completions_api(client, model, input_text, instructions), "chat"
from sqlalchemy.orm import Session
import httpx
import json
from app.api import deps
from app.api.permissions import ensure_job_access, is_admin_user, normalize_role, can_manage_group_resource
from app.models.job import Job
from app.models.user import User
from app.models.integration import Integration, IntegrationType, IntegrationStatus
from app.core.config import settings
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationUpdate,
    IntegrationResponse,
    IntegrationListResponse
)
from app.crud.crud_integration import integration as crud_integration
from app.crud.crud_integration_result import integration_result as crud_integration_result
from app.utils.activity_logger import log_activity, Actions
from app.utils.redact import is_masked, mask_secret, redact_secrets, restore_masked_secrets
from app.utils.secret_store import SecretStoreError, decrypt_secret, encrypt_secret

router = APIRouter()

CloudProvider = Literal["google", "microsoft"]


def _cloud_redirect_url(request: Request, **params: str) -> str:
    from app.services.cloud_oauth import resolve_public_app_url

    query = urlencode(params)
    return f"{resolve_public_app_url(request).rstrip('/')}/integrations?{query}"


def _can_manage_cloud(current_user: User, integration: Integration) -> bool:
    return bool(
        current_user.is_superuser
        or current_user.role in ("admin", "manager", "documents_admin")
        or integration.user_id == current_user.id
    )


class CloudDestinationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    folder_id: str
    folder_name: str = ""


class DriveFolderResponse(BaseModel):
    id: str
    name: str
    is_folder: bool
    mimeType: Optional[str] = None
    size: Optional[int] = None


@router.get("/oauth/{provider}/start")
async def start_cloud_oauth(
    provider: CloudProvider,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Return an OAuth authorization URL for a user-owned cloud connection."""
    from app.services.cloud_oauth import authorization_url, CloudOAuthError

    try:
        from app.services.cloud_oauth import resolve_public_app_url

        return {
            "provider": provider,
            "authorization_url": authorization_url(
                provider,
                str(current_user.id),
                db=db,
                public_app_url=resolve_public_app_url(request),
            ),
        }
    except CloudOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/oauth/{provider}/callback")
async def complete_cloud_oauth(
    provider: CloudProvider,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: Session = Depends(deps.get_db),
):
    """Exchange the provider callback and create/update the user's connection."""
    from app.services.cloud_oauth import complete_authorization, consume_state, get_microsoft_oauth_config, CloudOAuthError

    if error:
        if state:
            try:
                consume_state(state, provider)
            except CloudOAuthError:
                pass
        message = error_description or error
        return RedirectResponse(_cloud_redirect_url(request, oauth="error", provider=provider, message=message[:240]))
    if not code or not state:
        return RedirectResponse(_cloud_redirect_url(request, oauth="error", provider=provider, message="OAuth callback ไม่สมบูรณ์"))

    try:
        user_id = UUID(consume_state(state, provider))
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if not user:
            raise CloudOAuthError("ไม่พบผู้ใช้สำหรับ OAuth session นี้")
        from app.services.cloud_oauth import resolve_public_app_url

        oauth_data = complete_authorization(
            provider,
            code,
            db=db,
            public_app_url=resolve_public_app_url(request),
        )
    except (ValueError, CloudOAuthError) as exc:
        return RedirectResponse(_cloud_redirect_url(request, oauth="error", provider=provider, message=str(exc)[:240]))

    integration_type = IntegrationType.GDRIVE if provider == "google" else IntegrationType.ONEDRIVE
    provider_label = "Google Drive" if provider == "google" else "OneDrive"
    config: Dict[str, Any] = {
        "auth_mode": "oauth",
        "provider": provider,
        "account_id": oauth_data.get("account_id"),
        "account_email": oauth_data.get("account_email"),
        "account_name": oauth_data.get("account_name"),
        "refresh_token_encrypted": oauth_data["refresh_token_encrypted"],
        "access_token_expires_at": oauth_data.get("access_token_expires_at"),
        "folder_id": "root",
        "folder_name": "My Drive" if provider == "google" else "OneDrive",
    }
    if provider == "microsoft":
        config.update({
            "tenant_id": get_microsoft_oauth_config(db)["tenant"],
            "drive_id": oauth_data.get("drive_id"),
            "drive_name": oauth_data.get("drive_name"),
            "drive_type": oauth_data.get("drive_type"),
        })

    existing = next(
        (
            item for item in db.query(Integration).filter(
                Integration.user_id == user.id,
                Integration.type == integration_type,
            ).all()
            if (item.config or {}).get("auth_mode") == "oauth"
            and (item.config or {}).get("provider") == provider
            and (item.config or {}).get("account_id") == config.get("account_id")
        ),
        None,
    )
    if existing:
        config["folder_id"] = (existing.config or {}).get("folder_id") or config["folder_id"]
        config["folder_name"] = (existing.config or {}).get("folder_name") or config["folder_name"]
        existing.name = f"{provider_label} · {config.get('account_email') or config.get('account_name') or 'Connected account'}"
        existing.status = IntegrationStatus.ACTIVE
        existing.config = {**(existing.config or {}), **config}
        integration_id = existing.id
    else:
        existing = Integration(
            user_id=user.id,
            name=f"{provider_label} · {config.get('account_email') or config.get('account_name') or 'Connected account'}",
            type=integration_type,
            description="เชื่อมต่อผ่านบัญชีผู้ใช้",
            status=IntegrationStatus.ACTIVE,
            config=config,
        )
        db.add(existing)
        db.flush()
        integration_id = existing.id
    db.commit()
    return RedirectResponse(
        _cloud_redirect_url(request, oauth="success", provider=provider, integration_id=str(integration_id))
    )


def _masked_response(integration) -> IntegrationResponse:
    """Serialize an integration without echoing stored credentials."""
    data = IntegrationResponse.model_validate(integration)
    config = redact_secrets(data.config or {})
    if _is_softnix_genai_integration(integration) and (integration.config or {}).get("apiKeyEncrypted"):
        try:
            config["apiKey"] = mask_secret(decrypt_secret(integration.config["apiKeyEncrypted"]))
        except SecretStoreError:
            config["apiKey"] = "****"
        config.pop("apiKeyEncrypted", None)
    data.config = config
    return data


# ============================================================================
# Integration CRUD Endpoints
# ============================================================================

@router.get("/", response_model=IntegrationListResponse)
async def get_integrations(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Get all integrations (all users can view all integrations).

    Query parameters:
    - skip: Number of integrations to skip (pagination)
    - limit: Maximum number of integrations to return
    - status: Filter by status (active/paused)
    """
    integrations = crud_integration.get_all(
        db=db,
        skip=skip,
        limit=limit,
        status=status
    )
    total = crud_integration.count_all(db=db)

    return IntegrationListResponse(
        integrations=[_masked_response(i) for i in integrations],
        total=total
    )


@router.get("/active", response_model=List[IntegrationResponse])
async def get_active_integrations(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get all active integrations (all users can view all integrations)."""
    integrations = crud_integration.get_all_active(db=db)
    return [_masked_response(i) for i in integrations]


@router.get("/results")
async def get_integration_results_by_job(
    job_id: UUID,
    limit: int = 50,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Get all integration results for a job, newest first."""
    results = crud_integration_result.get_by_job(db, job_id=job_id, limit=limit)
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "integration_id": str(r.integration_id) if r.integration_id else None,
            "integration_type": r.integration_type,
            "integration_name": r.integration_name,
            "status": r.status,
            "model_used": r.model_used,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ]


@router.get("/results/{result_id}")
async def get_integration_result(
    result_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Get a single integration result with full output."""
    result = crud_integration_result.get(db, result_id=result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return {
        "id": str(result.id),
        "job_id": str(result.job_id),
        "integration_id": str(result.integration_id) if result.integration_id else None,
        "integration_type": result.integration_type,
        "integration_name": result.integration_name,
        "status": result.status,
        "output": result.output,
        "error_message": result.error_message,
        "model_used": result.model_used,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


@router.get("/{integration_id}/folders", response_model=List[DriveFolderResponse])
async def list_cloud_folders(
    integration_id: UUID,
    parent_id: str = "root",
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """List files/folders for the OAuth connection's folder picker."""
    integration = crud_integration.get(db=db, integration_id=integration_id)
    if not integration or integration.type not in (IntegrationType.GDRIVE, IntegrationType.ONEDRIVE):
        raise HTTPException(status_code=404, detail="Cloud integration not found")
    if not _can_manage_cloud(current_user, integration):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์จัดการ integration นี้")
    if (integration.config or {}).get("auth_mode") != "oauth":
        raise HTTPException(status_code=400, detail="Folder picker ใช้ได้กับ OAuth connection เท่านั้น")

    from app.services.cloud_drive import get_drive_client, CloudDriveError
    try:
        client = get_drive_client(integration, db=db)
        return client.list_children(parent_id)
    except CloudDriveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{integration_id}/cloud-destination", response_model=IntegrationResponse)
async def update_cloud_destination(
    integration_id: UUID,
    payload: CloudDestinationUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Save a selected folder without exposing OAuth secrets to the browser."""
    integration = crud_integration.get(db=db, integration_id=integration_id)
    if not integration or integration.type not in (IntegrationType.GDRIVE, IntegrationType.ONEDRIVE):
        raise HTTPException(status_code=404, detail="Cloud integration not found")
    if not _can_manage_cloud(current_user, integration):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์จัดการ integration นี้")
    if (integration.config or {}).get("auth_mode") != "oauth":
        raise HTTPException(status_code=400, detail="Destination wizard ใช้ได้กับ OAuth connection เท่านั้น")

    config = {
        **(integration.config or {}),
        "folder_id": payload.folder_id or "root",
        "folder_name": payload.folder_name or "Root",
    }
    integration.config = config
    if payload.name and payload.name.strip():
        integration.name = payload.name.strip()
    if payload.description is not None:
        integration.description = payload.description.strip() or None
    if payload.status in ("active", "paused"):
        integration.status = payload.status
    db.commit()
    db.refresh(integration)
    return _masked_response(integration)


class DriveTestRequest(BaseModel):
    folder_id: Optional[str] = None


@router.post("/{integration_id}/test-drive")
async def test_drive_integration(
    integration_id: UUID,
    payload: Optional[DriveTestRequest] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Verify a Google Drive / OneDrive credential (issue token, reach the API)."""
    integration = crud_integration.get(db=db, integration_id=integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if integration.type not in ("gdrive", "onedrive"):
        raise HTTPException(status_code=400, detail="Integration นี้ไม่ใช่ Google Drive / OneDrive")
    if not _can_manage_cloud(current_user, integration):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ทดสอบ integration นี้")
    if (integration.config or {}).get("auth_mode") == "oauth" and payload and payload.folder_id:
        selected_folder = (integration.config or {}).get("folder_id") or "root"
        if payload.folder_id != selected_folder:
            raise HTTPException(status_code=400, detail="ทดสอบได้เฉพาะโฟลเดอร์ปลายทางที่บันทึกไว้")

    from app.services.cloud_drive import get_drive_client, CloudDriveError
    try:
        client = get_drive_client(integration, db=db)
        result = client.check()
        if payload and payload.folder_id:
            children = client.list_children(payload.folder_id)
            result["folder_id"] = payload.folder_id
            result["children_count"] = len(children)
        return {"ok": True, "detail": result}
    except CloudDriveError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"เชื่อมต่อไม่สำเร็จ: {e}")


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get a specific integration by ID (all users can view all integrations for LLM usage)."""
    integration = crud_integration.get(db=db, integration_id=integration_id)

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    return _masked_response(integration)


@router.post("/", response_model=IntegrationResponse, status_code=201)
async def create_integration(
    integration_data: IntegrationCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Create a new integration (only managers and admins can create)."""
    role_value = str(current_user.role) if current_user.role else None
    normalized = deps._normalize_role(role_value)
    is_admin = current_user.is_superuser or normalized == "admin"

    if normalized != "manager" and not is_admin:
        raise HTTPException(status_code=403, detail="Only managers and admins can create integrations")

    integration_data.config = _normalize_softnix_config(
        integration_data.type,
        integration_data.config,
    )

    integration = crud_integration.create(
        db=db,
        integration=integration_data,
        user_id=current_user.id
    )

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_INTEGRATION,
        resource_type="integration",
        resource_id=str(integration.id),
        details={
            "name": integration.name,
            "type": integration.type,
            "status": integration.status
        }
    )

    return _masked_response(integration)


@router.put("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: UUID,
    integration_data: IntegrationUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Update an existing integration (only managers and admins can update their own integrations)."""
    role_value = str(current_user.role) if current_user.role else None
    normalized = deps._normalize_role(role_value)
    is_admin = current_user.is_superuser or normalized == "admin"

    # Check if integration exists
    existing = crud_integration.get(db=db, integration_id=integration_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Check permissions: admin can update any, managers can update their own or same-group
    if not is_admin and existing.user_id != current_user.id and not can_manage_group_resource(current_user, existing.user):
        raise HTTPException(status_code=403, detail="You can only update your own integrations")

    # A masked credential in the payload means the client echoed back the
    # redacted GET response unchanged — restore the stored value.
    if integration_data.config is not None:
        if (
            _integration_type_value(existing) == "softnix_genai"
            and is_masked(integration_data.config.get("apiKey"))
            and (existing.config or {}).get("apiKeyEncrypted")
        ):
            integration_data.config = {
                **integration_data.config,
                "apiKeyEncrypted": existing.config["apiKeyEncrypted"],
            }
            integration_data.config.pop("apiKey", None)
        integration_data.config = restore_masked_secrets(
            integration_data.config, existing.config or {}
        )

    effective_type = integration_data.type or _integration_type_value(existing)
    if integration_data.config is None and effective_type == "softnix_genai":
        integration_data.config = dict(existing.config or {})
    if integration_data.config is not None:
        integration_data.config = _normalize_softnix_config(
            effective_type,
            integration_data.config,
        )

    # Update integration
    updated_integration = crud_integration.update(
        db=db,
        integration_id=integration_id,
        integration=integration_data
    )

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_INTEGRATION,
        resource_type="integration",
        resource_id=str(integration_id),
        details={
            "name": updated_integration.name,
            "type": updated_integration.type,
            "status": updated_integration.status
        }
    )

    return _masked_response(updated_integration)


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Delete an integration (only managers and admins can delete their own integrations)."""
    role_value = str(current_user.role) if current_user.role else None
    normalized = deps._normalize_role(role_value)
    is_admin = current_user.is_superuser or normalized == "admin"

    # Check if integration exists
    existing = crud_integration.get(db=db, integration_id=integration_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Check permissions: admin can delete any, managers can delete their own or same-group
    if not is_admin and existing.user_id != current_user.id and not can_manage_group_resource(current_user, existing.user):
        raise HTTPException(status_code=403, detail="You can only delete your own integrations")

    # Delete integration
    success = crud_integration.delete(db=db, integration_id=integration_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete integration")

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.DELETE_INTEGRATION,
        resource_type="integration",
        resource_id=str(integration_id),
        details={
            "name": existing.name,
            "type": existing.type
        }
    )

    return None


# ============================================================================
# LLM Integration Endpoints
# ============================================================================

class TestLLMRequest(BaseModel):
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    model: str
    reasoningEffort: str = "low"
    instructions: str = ""
    userPrompt: Optional[str] = None
    outputFormatPrompt: Optional[str] = None
    testInput: str = ""
    providerType: Optional[str] = None
    integrationId: Optional[UUID] = None


class TestLLMResponse(BaseModel):
    output: str


from typing import Optional, List, Dict, Any, Union

class DocumentInput(BaseModel):
    id: str
    filename: str
    data: Optional[Union[Dict[str, Any], List[Any], Any]] = None


class SendLLMRequest(BaseModel):
    apiKey: str
    baseUrl: Optional[str] = None
    model: str
    reasoningEffort: str = "low"
    instructions: str
    userPrompt: Optional[str] = None
    outputFormatPrompt: Optional[str] = None
    documents: List[DocumentInput]
    providerType: Optional[str] = None


class DocumentResult(BaseModel):
    id: str
    filename: str
    output: str
    success: bool
    error: Optional[str] = None


class SendLLMResponse(BaseModel):
    results: List[DocumentResult]


class SendToIntegrationRequest(BaseModel):
    integration_id: Optional[UUID] = None
    integration_name: Optional[str] = None
    job_id: Optional[UUID] = None
    job_name: str
    documents: List[DocumentInput]


class SendToIntegrationResponse(BaseModel):
    success: bool
    message: str
    results: Optional[List[DocumentResult]] = None


def _resolve_send_target_integration(db: Session, request: SendToIntegrationRequest):
    if request.integration_id is not None:
        integration = crud_integration.get(db=db, integration_id=request.integration_id)
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")
        return integration

    if not request.integration_name or not request.integration_name.strip():
        raise HTTPException(status_code=400, detail="integration_id or integration_name is required")

    normalized_name = request.integration_name.strip().lower()
    matches = [
        integration
        for integration in crud_integration.get_all_active(db=db)
        if integration.name and integration.name.strip().lower() == normalized_name
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Integration not found")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Multiple integrations share this name; use integration_id instead")
    return matches[0]


def _authorize_send_target(
    db: Session,
    current_user: User,
    integration: Integration,
    job_id: Optional[UUID],
) -> None:
    """Authorize the job and destination before any external call is made."""
    if integration.status != IntegrationStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Integration is not active")

    if job_id:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        ensure_job_access(current_user, job)

    # LLM providers are intentionally shared for document processing. Other
    # destinations can send data outside the platform and require ownership or
    # an elevated role.
    if _is_llm_integration(integration):
        return
    if is_admin_user(current_user) or normalize_role(current_user.role) == "manager":
        return
    if integration.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You cannot use this integration")


@router.post("/test-llm", response_model=TestLLMResponse)
async def test_llm(
    request: TestLLMRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Test LLM connectivity with Responses API and Chat Completions fallback.
    """
    try:
        api_key = request.apiKey
        base_url = request.baseUrl
        provider_type = request.providerType
        if request.integrationId:
            integration = crud_integration.get(db=db, integration_id=request.integrationId)
            if not integration:
                raise HTTPException(status_code=404, detail="Integration not found")
            _authorize_send_target(db, current_user, integration, None)
            if not _is_llm_integration(integration):
                raise HTTPException(status_code=400, detail="Integration is not an LLM type")
            api_key = _integration_api_key(integration)
            base_url = _llm_base_url_for_integration(integration)
            provider_type = _integration_type_value(integration)
        if not api_key:
            raise HTTPException(status_code=400, detail="API Key is required")

        output_text, mode = _call_llm_text(
            api_key=api_key,
            base_url=base_url or (SOFTNIX_GENAI_BASE_URL if provider_type == "softnix_genai" else None),
            model=request.model,
            input_text=request.testInput.strip() or "hello",
            instructions=request.instructions or "Reply briefly to confirm connectivity.",
            reasoning_effort=request.reasoningEffort,
            request_mode="chat" if provider_type == "softnix_genai" else None,
        )

        return TestLLMResponse(output=f"Success via {mode}: {output_text}")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"LLM test failed: {str(e)}"
        )


@router.post("/send-llm", response_model=SendLLMResponse)
async def send_to_llm(
    http_request: Request,
    request: SendLLMRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Process multiple documents with LLM using configured instructions
    """
    results = []

    # Get client info for logging
    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    try:
        for doc in request.documents:
            try:
                # Convert document data to string input
                doc_input = json.dumps(doc.data, ensure_ascii=False, indent=2) if doc.data else "No data"

                # Compose input: userPrompt + OCR data + outputFormatPrompt
                composed_input = _build_llm_input(
                    doc_filename=doc.filename,
                    doc_input=doc_input,
                    user_prompt=request.userPrompt,
                    output_format_prompt=request.outputFormatPrompt,
                )

                output_text, _mode = _call_llm_text(
                    api_key=request.apiKey,
                    base_url=request.baseUrl or (SOFTNIX_GENAI_BASE_URL if request.providerType == "softnix_genai" else None),
                    model=request.model,
                    input_text=composed_input,
                    instructions=request.instructions,
                    reasoning_effort=request.reasoningEffort,
                    request_mode="chat" if request.providerType == "softnix_genai" else None,
                )

                results.append(DocumentResult(
                    id=doc.id,
                    filename=doc.filename,
                    output=output_text,
                    success=True
                ))
            except Exception as e:
                results.append(DocumentResult(
                    id=doc.id,
                    filename=doc.filename,
                    output="",
                    success=False,
                    error=str(e)
                ))

        # Log activity for successful integration send
        successful_count = sum(1 for r in results if r.success)
        failed_count = len(results) - successful_count

        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.SEND_TO_INTEGRATION,
            resource_type="integration",
            resource_id=None,
            details={
                "name": "LLM Integration",
                "type": "llm",
                "result": "success" if failed_count == 0 else "failed"
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

        return SendLLMResponse(results=results)

    except Exception as e:
        # Log failed integration attempt
        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.SEND_TO_INTEGRATION,
            resource_type="integration",
            resource_id=None,
            details={
                "name": "LLM Integration",
                "type": "llm",
                "result": "failed"
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

        raise HTTPException(
            status_code=400,
            detail=f"LLM processing failed: {str(e)}"
        )


@router.post("/send-stream")
async def send_to_integration_stream(
    request: SendToIntegrationRequest,
    http_request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Stream LLM output as SSE events.
    Events:
      data: {"type":"delta","text":"..."}
      data: {"type":"done","full_output":"...","filename":"..."}
      data: {"type":"error","message":"..."}
    """
    import uuid as _uuid

    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    integration = _resolve_send_target_integration(db, request)
    _authorize_send_target(db, current_user, integration, request.job_id)

    if not _is_llm_integration(integration):
        raise HTTPException(status_code=400, detail="Streaming is only supported for LLM integrations")

    llm_api_key = _integration_api_key(integration)
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="API Key is required for LLM integration")

    llm_model = integration.config.get("model", "gpt-4o")
    llm_base_url = _llm_base_url_for_integration(integration)
    llm_instructions = integration.config.get("instructions", "")
    llm_user_prompt = integration.config.get("userPrompt")
    llm_output_format = integration.config.get("outputFormatPrompt")
    llm_reasoning_effort = integration.config.get("reasoningEffort", "low")

    doc_tuples = [(doc.filename, doc.data) for doc in request.documents]
    composed_input = _build_combined_llm_input(
        documents=doc_tuples,
        user_prompt=llm_user_prompt,
        output_format_prompt=llm_output_format,
    )

    report_filename = f"{request.job_name} — Validation Report"

    async def _event_generator():
        full_output = ""
        try:
            normalized_base_url, detected_mode = _normalize_llm_base_url(llm_base_url)
            preferred_mode = "chat" if _is_softnix_genai_integration(integration) else detected_mode
            client_kwargs: Dict[str, Any] = {
                "api_key": llm_api_key,
                "timeout": 120.0,
                "max_retries": 0,
            }
            if normalized_base_url:
                client_kwargs["base_url"] = normalized_base_url

            async with AsyncOpenAI(**client_kwargs) as client:
                async def chat_stream():
                    messages: List[Dict[str, str]] = []
                    if llm_instructions and llm_instructions.strip():
                        messages.append({"role": "system", "content": llm_instructions.strip()})
                    messages.append({"role": "user", "content": composed_input})
                    return await client.chat.completions.create(
                        model=llm_model,
                        messages=messages,
                        stream=True,
                    )

                if preferred_mode == "chat":
                    stream = await chat_stream()
                    async for chunk in stream:
                        if chunk.choices:
                            delta = chunk.choices[0].delta.content or ""
                            if delta:
                                full_output += delta
                                payload = json.dumps({"type": "delta", "text": delta}, ensure_ascii=False)
                                yield f"data: {payload}\n\n"
                else:
                    create_params: Dict[str, Any] = {
                        "model": llm_model,
                        "instructions": llm_instructions,
                        "input": composed_input,
                        "stream": True,
                    }
                    if _supports_reasoning(llm_model):
                        create_params["reasoning"] = {"effort": llm_reasoning_effort}

                    try:
                        stream = await client.responses.create(**create_params)
                    except Exception as responses_error:
                        if preferred_mode == "responses" or not _is_not_found_error(responses_error):
                            raise
                        stream = await chat_stream()
                        async for chunk in stream:
                            if chunk.choices:
                                delta = chunk.choices[0].delta.content or ""
                                if delta:
                                    full_output += delta
                                    payload = json.dumps({"type": "delta", "text": delta}, ensure_ascii=False)
                                    yield f"data: {payload}\n\n"
                    else:
                        async for event in stream:
                            if hasattr(event, "type"):
                                if event.type == "response.output_text.delta":
                                    delta = event.delta if hasattr(event, "delta") else ""
                                    if delta:
                                        full_output += delta
                                        payload = json.dumps({"type": "delta", "text": delta}, ensure_ascii=False)
                                        yield f"data: {payload}\n\n"
                                elif event.type == "response.completed":
                                    if hasattr(event, "response") and hasattr(event.response, "output_text"):
                                        full_output = event.response.output_text
                                elif event.type == "response.output_text.done":
                                    if hasattr(event, "text"):
                                        full_output = event.text

            # Save result to DB
            saved_result_id = None
            if request.job_id:
                try:
                    saved = crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type=_integration_type_value(integration),
                        integration_name=integration.name,
                        status="success",
                        output=full_output,
                        model_used=llm_model,
                    )
                    saved_result_id = str(saved.id)
                except Exception:
                    pass

            done_payload: Dict[str, Any] = {
                "type": "done",
                "full_output": full_output,
                "filename": report_filename,
            }
            if saved_result_id:
                done_payload["result_id"] = saved_result_id
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

            # Log activity after stream completes
            try:
                log_activity(
                    db=db,
                    user_id=current_user.id,
                    action=Actions.SEND_TO_INTEGRATION,
                    resource_type="integration",
                    resource_id=integration.id,
                    details={
                        "job_name": request.job_name,
                        "name": integration.name,
                        "type": integration.type,
                        "result": "success",
                        "stream": True,
                    },
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
            except Exception:
                pass

        except Exception as e:
            # Save error result to DB
            if request.job_id:
                try:
                    crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type=_integration_type_value(integration),
                        integration_name=integration.name,
                        status="error",
                        error_message=str(e),
                        model_used=llm_model,
                    )
                except Exception:
                    pass

            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            try:
                log_activity(
                    db=db,
                    user_id=current_user.id,
                    action=Actions.SEND_TO_INTEGRATION,
                    resource_type="integration",
                    resource_id=integration.id,
                    details={
                        "job_name": request.job_name,
                        "name": integration.name,
                        "type": integration.type,
                        "result": "failed",
                        "stream": True,
                    },
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
            except Exception:
                pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/send", response_model=SendToIntegrationResponse)
async def send_to_integration(
    request: SendToIntegrationRequest,
    http_request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Send documents to integration endpoint (supports all integration types: llm, workflow, api)
    """
    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    integration = None

    try:
        integration = _resolve_send_target_integration(db, request)
        _authorize_send_target(db, current_user, integration, request.job_id)

        results = []
        success = False
        message = ""

        if _is_llm_integration(integration):
            llm_api_key = _integration_api_key(integration)
            if not llm_api_key:
                raise HTTPException(status_code=400, detail="API Key is required for LLM integration")

            llm_model = integration.config.get("model", "gpt-4o")
            llm_base_url = _llm_base_url_for_integration(integration)
            llm_instructions = integration.config.get("instructions", "")
            llm_user_prompt = integration.config.get("userPrompt")
            llm_output_format = integration.config.get("outputFormatPrompt")
            llm_reasoning_effort = integration.config.get("reasoningEffort", "low")

            # Combine all documents into ONE LLM call so cross-document validation works
            try:
                doc_tuples = [(doc.filename, doc.data) for doc in request.documents]
                composed_input = _build_combined_llm_input(
                    documents=doc_tuples,
                    user_prompt=llm_user_prompt,
                    output_format_prompt=llm_output_format,
                )

                output_text, _mode = _call_llm_text(
                    api_key=llm_api_key,
                    base_url=llm_base_url,
                    model=llm_model,
                    input_text=composed_input,
                    instructions=llm_instructions,
                    reasoning_effort=llm_reasoning_effort,
                    request_mode="chat" if _is_softnix_genai_integration(integration) else None,
                )

                results.append(DocumentResult(
                    id="combined",
                    filename=f"{request.job_name} — Validation Report",
                    output=output_text,
                    success=True
                ))
            except Exception as e:
                results.append(DocumentResult(
                    id="combined",
                    filename=request.job_name,
                    output="",
                    success=False,
                    error=str(e)
                ))

            successful_count = sum(1 for r in results if r.success)
            failed_count = len(results) - successful_count
            success = failed_count == 0
            message = "Sent successfully" if success else f"Partial success: {successful_count} succeeded, {failed_count} failed"

        elif integration.type == "workflow":
            webhook_url = integration.config.get("webhookUrl")
            if not webhook_url:
                raise HTTPException(status_code=400, detail="Webhook URL is required for workflow integration")

            payload = {
                "documents": [{"id": d.id, "filename": d.filename, "data": d.data} for d in request.documents]
            }

            async with httpx.AsyncClient() as client:
                res = await client.post(webhook_url, json=payload, timeout=30.0)
                if res.status_code >= 400:
                    raise HTTPException(status_code=res.status_code, detail=f"Webhook responded {res.status_code}: {res.text}")

            success = True
            message = "Sent successfully to workflow"

        elif integration.type == "api":
            endpoint = integration.config.get("endpoint")
            if not endpoint:
                raise HTTPException(status_code=400, detail="Endpoint URL is required for API integration")

            payload = {
                "documents": [{"id": d.id, "filename": d.filename, "data": d.data} for d in request.documents]
            }

            headers: Dict[str, str] = {"Content-Type": "application/json"}
            auth_header = integration.config.get("authHeader")
            if auth_header:
                for line in auth_header.split("\n"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        headers[parts[0].strip()] = parts[1].strip()

            headers_json = integration.config.get("headersJson")
            if headers_json:
                try:
                    parsed = json.loads(headers_json)
                    headers.update(parsed)
                except:
                    pass

            method = integration.config.get("method", "POST")

            async with httpx.AsyncClient() as client:
                res = await client.request(method, endpoint, json=payload, headers=headers, timeout=30.0)
                if res.status_code >= 400:
                    raise HTTPException(status_code=res.status_code, detail=f"API responded {res.status_code}: {res.text}")

            success = True
            message = "Sent successfully to API endpoint"

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported integration type: {integration.type}")

        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.SEND_TO_INTEGRATION,
            resource_type="integration",
            resource_id=integration.id,
            details={
                "job_name": request.job_name,
                "name": integration.name,
                "type": integration.type,
                "result": "success" if success else "failed"
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

        # Save integration result for history
        if request.job_id:
            try:
                crud_integration_result.create(
                    db,
                    job_id=request.job_id,
                    integration_id=integration.id,
                    user_id=current_user.id,
                    integration_type=integration.type.value if hasattr(integration.type, "value") else str(integration.type),
                    integration_name=integration.name,
                    status="success" if success else "error",
                    output=results[0].output if results and _is_llm_integration(integration) else None,
                    error_message=results[0].error if results and not success else None,
                    model_used=integration.config.get("model") if _is_llm_integration(integration) else None,
                )
            except Exception:
                pass

        return SendToIntegrationResponse(
            success=success,
            message=message,
            results=results if _is_llm_integration(integration) else None
        )

    except HTTPException as he:
        if integration:
            log_activity(
                db=db,
                user_id=current_user.id,
                action=Actions.SEND_TO_INTEGRATION,
                resource_type="integration",
                resource_id=integration.id,
                details={
                    "name": integration.name,
                    "type": integration.type,
                    "result": "failed"
                },
                ip_address=client_ip,
                user_agent=user_agent
            )
            if request.job_id:
                try:
                    crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type=integration.type.value if hasattr(integration.type, "value") else str(integration.type),
                        integration_name=integration.name,
                        status="error",
                        error_message=str(he.detail),
                    )
                except Exception:
                    pass
        raise

    except Exception as e:
        import traceback
        traceback.print_exc()

        if integration:
            log_activity(
                db=db,
                user_id=current_user.id,
                action=Actions.SEND_TO_INTEGRATION,
                resource_type="integration",
                resource_id=integration.id,
                details={
                    "name": integration.name,
                    "type": integration.type,
                    "result": "failed"
                },
                ip_address=client_ip,
                user_agent=user_agent
            )
            if request.job_id:
                try:
                    crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type=integration.type.value if hasattr(integration.type, "value") else str(integration.type),
                        integration_name=integration.name,
                        status="error",
                        error_message=str(e),
                    )
                except Exception:
                    pass

        raise HTTPException(
            status_code=400,
            detail=f"Integration send failed: {str(e)}"
        )
