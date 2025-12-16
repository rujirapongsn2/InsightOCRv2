from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.api import deps
from app.core import security
from app.core.config import settings
from app.models.user import User
from app.schemas.user import Token, User as UserSchema
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()

@router.post("/login/access-token", response_model=Token)
def login_access_token(
    request: Request,
    db: Session = Depends(deps.get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    # Get client info for logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        # Log failed login attempt (we don't have user_id, so skip logging here)
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    # Log successful login
    log_activity(
        db=db,
        user_id=user.id,
        action=Actions.LOGIN,
        details={"email": user.email},
        ip_address=client_ip,
        user_agent=user_agent
    )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

@router.post("/login/test-token", response_model=UserSchema)
def test_token(current_user: User = Depends(deps.get_current_user)) -> Any:
    """
    Test access token
    """
    return current_user

@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Logout endpoint - logs user logout activity
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.LOGOUT,
        details={"email": current_user.email},
        ip_address=client_ip,
        user_agent=user_agent
    )
    
    return {"message": "Logged out successfully"}
