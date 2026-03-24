import json
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
import requests
from sqlalchemy.orm import Session
from app.api import deps
from app.models.user import User
from app.models.setting import Setting
from app.schemas.setting import Setting as SettingSchema, SettingUpdate
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()
BUILD_INFO_PATH = Path(__file__).resolve().parents[4] / ".build-info.json"


def get_app_commit_sha() -> str | None:
    try:
        if not BUILD_INFO_PATH.exists():
            return None
        data = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
        sha = data.get("short_commit_sha") or data.get("commit_sha")
        if isinstance(sha, str) and sha.strip():
            return sha.strip()
    except Exception:
        return None
    return None


class EndpointTestRequest(BaseModel):
    url: HttpUrl
    token: Optional[str] = None


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
    return setting


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
    setting.api_token = payload.api_token
    setting.verify_ssl = payload.verify_ssl

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
            "test_endpoint": payload.test_endpoint
        }
    )

    return setting


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
        resp = requests.get(str(payload.url), headers=headers, timeout=10, verify=False)
        return {
            "status_code": resp.status_code,
            "body": resp.text,
            "headers": dict(resp.headers),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
