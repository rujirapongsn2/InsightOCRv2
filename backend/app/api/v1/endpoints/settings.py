from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
import requests
from sqlalchemy.orm import Session
from app.api import deps
from app.models.user import User
from app.models.setting import Setting
from app.schemas.setting import Setting as SettingSchema, SettingUpdate

router = APIRouter()


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
    # Backfill defaults if missing
    if not setting.api_endpoint:
        setting.api_endpoint = "https://111.223.37.41:9001/ai-process-file"
        db.add(setting)
        db.commit()
        db.refresh(setting)
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
    setting.ocr_engine = payload.ocr_engine
    setting.model = payload.model
    setting.api_endpoint = payload.api_endpoint
    setting.api_token = payload.api_token
    setting.verify_ssl = payload.verify_ssl
    db.add(setting)
    db.commit()
    db.refresh(setting)
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
