from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.core import security
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.api_access_token import APIAccessToken
from app.models.user import User
from app.schemas.user import TokenPayload


@dataclass(frozen=True)
class APIAccessTokenPrincipal:
    """Authenticated user plus the Personal API Token used for a request."""

    user: User
    api_token: APIAccessToken

    def __getattr__(self, name: str):
        return getattr(self.user, name)


def _should_update_last_used(last_used_at: datetime | None, now: datetime) -> bool:
    if last_used_at is None:
        return True
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)
    return (now - last_used_at).total_seconds() >= settings.API_TOKEN_LAST_USED_UPDATE_SECONDS

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

def get_db() -> Generator:
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()


def _get_api_access_token(db: Session, token: str) -> Optional[APIAccessToken]:
    hashed_token = security.hash_api_access_token(token)
    api_token = (
        db.query(APIAccessToken)
        .filter(APIAccessToken.hashed_token == hashed_token)
        .first()
    )
    if not api_token:
        return None
    if api_token.revoked_at is not None:
        return None
    if api_token.expires_at is not None:
        now = datetime.now(timezone.utc) if api_token.expires_at.tzinfo is not None else datetime.utcnow()
        if api_token.expires_at <= now:
            return None

    now = datetime.now(timezone.utc)
    if _should_update_last_used(api_token.last_used_at, now):
        api_token.last_used_at = now
        db.add(api_token)
        db.commit()

    return api_token


def _get_user_from_api_access_token(db: Session, token: str) -> Optional[User]:
    api_token = _get_api_access_token(db, token)
    if not api_token:
        return None
    if api_token.mcp_access_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This token is restricted to the MCP endpoint",
        )
    return db.query(User).filter(User.id == api_token.user_id).first()


def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(reusable_oauth2)
) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        user = db.query(User).filter(User.id == token_data.sub).first()
    except (jwt.JWTError, ValidationError):
        user = _get_user_from_api_access_token(db, token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    return user

def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def get_current_active_api_token_principal(
    db: Session = Depends(get_db), token: str = Depends(reusable_oauth2)
) -> APIAccessTokenPrincipal:
    """Authenticate MCP requests with a Personal API Token, not a web JWT."""
    api_token = _get_api_access_token(db, token)
    if not api_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MCP requires a valid Personal API Token",
        )
    user = db.query(User).filter(User.id == api_token.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials")
    return APIAccessTokenPrincipal(user=user, api_token=api_token)

def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return current_user


def get_current_active_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Require an active system administrator for platform configuration."""
    if not (current_user.is_superuser or _normalize_role(current_user.role) == "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user


def get_current_active_admin_or_manager(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Require an active admin or manager (documents_admin) for user/group management."""
    if not (
        current_user.is_superuser
        or _normalize_role(current_user.role) in {"admin", "manager"}
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user


def _normalize_role(role: str | None) -> str:
    """Normalize role for permission checks."""
    if not role:
        return "user"
    return "manager" if role == "documents_admin" else role
