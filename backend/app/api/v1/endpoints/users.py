from typing import Any, List
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic.networks import EmailStr
from sqlalchemy.orm import Session
from app.api import deps
from app.core.config import settings
from app.core import security
from app.models.user import User
from app.services.agent_skill_pack import SKILL_PACK_NAME, build_skill_pack_archive
from app.schemas.user import User as UserSchema, UserCreate, UserUpdate, UserSelfUpdate
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()


def _build_api_urls(request: Request) -> tuple[str, str, bool]:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")

    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    origin = f"{scheme}://{host}"
    api_base_url = f"{origin}{settings.API_V1_STR}"
    external_base_url = f"{api_base_url}/external"

    host_only = host.split(":", 1)[0]
    curl_insecure = host_only in {"127.0.0.1", "localhost"}
    return api_base_url, external_base_url, curl_insecure

@router.get("/", response_model=List[UserSchema])
def read_users(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Retrieve users.
    """
    users = db.query(User).offset(skip).limit(limit).all()
    return users

@router.post("/", response_model=UserSchema)
def create_user(
    *,
    db: Session = Depends(deps.get_db),
    user_in: UserCreate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Create new user.
    """
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    
    db_user = User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role,
        is_superuser=user_in.is_superuser,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_USER,
        resource_type="user",
        resource_id=db_user.id,
        details={
            "email": db_user.email,
            "full_name": db_user.full_name,
            "role": db_user.role
        }
    )

    return db_user

@router.get("/me", response_model=UserSchema)
def read_user_me(
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get current user.
    """
    return current_user


@router.get("/me/agent-skill-pack")
def download_agent_skill_pack(
    request: Request,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
) -> Response:
    api_base_url, external_base_url, curl_insecure = _build_api_urls(request)
    archive_bytes = build_skill_pack_archive(
        api_base_url=api_base_url,
        external_base_url=external_base_url,
        curl_insecure=curl_insecure,
    )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.EXPORT_DATA,
        resource_type="agent_skill_pack",
        details={"package_name": SKILL_PACK_NAME},
        ip_address=client_ip,
        user_agent=user_agent,
    )

    headers = {
        "Content-Disposition": f'attachment; filename="{SKILL_PACK_NAME}.zip"',
        "Content-Type": "application/zip",
    }
    return Response(content=archive_bytes, media_type="application/zip", headers=headers)

@router.get("/{user_id}", response_model=UserSchema)
def read_user_by_id(
    user_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
) -> Any:
    """
    Get a specific user by id.
    """
    # Allow current user to fetch self by id to avoid UUID parsing errors when using "me" path
    if user_id == "me":
        return current_user

    user = db.query(User).filter(User.id == user_id).first()
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return user

@router.put("/me", response_model=UserSchema)
def update_user_me(
    *,
    request: Request,
    db: Session = Depends(deps.get_db),
    user_in: UserSelfUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update current user's profile (name/password).
    """
    # Get client info for logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    update_data = user_in.dict(exclude_unset=True)
    password_changed = False

    if "password" in update_data and update_data["password"]:
        hashed_password = security.get_password_hash(update_data["password"])
        del update_data["password"]
        update_data["hashed_password"] = hashed_password
        password_changed = True

    if "full_name" in update_data:
        current_user.full_name = update_data["full_name"]
    if "hashed_password" in update_data:
        current_user.hashed_password = update_data["hashed_password"]

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    # Log password change activity
    if password_changed:
        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.CHANGE_PASSWORD,
            resource_type="user",
            resource_id=current_user.id,
            details={"email": current_user.email},
            ip_address=client_ip,
            user_agent=user_agent
        )

    return current_user

@router.put("/{user_id}", response_model=UserSchema)
def update_user(
    *,
    request: Request,
    db: Session = Depends(deps.get_db),
    user_id: str,
    user_in: UserUpdate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Update a user.
    """
    # Get client info for logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system",
        )

    update_data = user_in.dict(exclude_unset=True)
    password_changed = False

    if "password" in update_data and update_data["password"]:
        hashed_password = security.get_password_hash(update_data["password"])
        del update_data["password"]
        update_data["hashed_password"] = hashed_password
        password_changed = True

    for field, value in update_data.items():
        setattr(user, field, value)

    db.add(user)
    db.commit()
    db.refresh(user)

    # Log password change activity if password was changed
    if password_changed:
        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.CHANGE_PASSWORD,
            resource_type="user",
            resource_id=user.id,
            details={
                "email": user.email,
                "changed_by_admin": True
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

    # Log general user update activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_USER,
        resource_type="user",
        resource_id=user.id,
        details={
            "email": user.email,
            "updated_fields": [f for f in list(update_data.keys()) if f != "hashed_password"]
        },
        ip_address=client_ip,
        user_agent=user_agent
    )

    return user

@router.delete("/{user_id}", response_model=UserSchema)
def delete_user(
    *,
    db: Session = Depends(deps.get_db),
    user_id: str,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Delete a user (admin only). Cannot delete yourself.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own account.",
        )

    # Log activity before deletion
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.DELETE_USER,
        resource_type="user",
        resource_id=user.id,
        details={
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    )

    db.delete(user)
    db.commit()
    return user
