from datetime import datetime, timedelta, timezone
from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core import security
from app.models.api_access_token import APIAccessToken
from app.models.user import User
from app.schemas.api_token import (
    APIAccessTokenCreate,
    APIAccessTokenCreateResponse,
    APIAccessTokenResponse,
)
from app.utils.activity_logger import Actions, log_activity

router = APIRouter()


@router.get("/", response_model=List[APIAccessTokenResponse])
def list_api_tokens(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    tokens = (
        db.query(APIAccessToken)
        .filter(APIAccessToken.user_id == current_user.id)
        .order_by(APIAccessToken.created_at.desc())
        .all()
    )
    return tokens


@router.post("/", response_model=APIAccessTokenCreateResponse, status_code=status.HTTP_201_CREATED)
def create_api_token(
    *,
    request: Request,
    db: Session = Depends(deps.get_db),
    payload: APIAccessTokenCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    plain_token = security.generate_api_access_token()
    expires_at = None
    if payload.expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)

    db_token = APIAccessToken(
        user_id=current_user.id,
        name=payload.name.strip(),
        token_prefix=security.get_api_access_token_prefix(plain_token),
        hashed_token=security.hash_api_access_token(plain_token),
        expires_at=expires_at,
    )
    db.add(db_token)
    db.commit()
    db.refresh(db_token)

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_API_TOKEN,
        resource_type="api_token",
        resource_id=db_token.id,
        details={"name": db_token.name, "expires_at": db_token.expires_at.isoformat() if db_token.expires_at else None},
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return APIAccessTokenCreateResponse(
        token=plain_token,
        token_info=db_token,
    )


@router.delete("/{token_id}", status_code=status.HTTP_200_OK)
def revoke_api_token(
    *,
    token_id: UUID,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    db_token = (
        db.query(APIAccessToken)
        .filter(APIAccessToken.id == token_id, APIAccessToken.user_id == current_user.id)
        .first()
    )
    if not db_token:
        raise HTTPException(status_code=404, detail="API token not found")
    if db_token.revoked_at is None:
        db_token.revoked_at = datetime.now(timezone.utc)
        db.add(db_token)
        db.commit()

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.REVOKE_API_TOKEN,
        resource_type="api_token",
        resource_id=db_token.id,
        details={"name": db_token.name},
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return {"message": "API token revoked"}
