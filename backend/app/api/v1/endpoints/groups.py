from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.api import deps
from app.models.group import Group
from app.models.user import User
from app.schemas.group import GroupCreate, GroupOut
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()


def _to_out(group: Group) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        created_at=group.created_at,
        member_count=len(group.users) if group.users else 0,
    )


@router.get("/", response_model=List[GroupOut])
def list_groups(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """List all groups (any active user, used for the autolist picker)."""
    groups = db.query(Group).options(selectinload(Group.users)).order_by(Group.name).all()
    return [_to_out(g) for g in groups]


@router.post("/", response_model=GroupOut)
def create_group(
    *,
    db: Session = Depends(deps.get_db),
    group_in: GroupCreate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    """Create a new group (admin only)."""
    name = group_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    existing = db.query(Group).filter(func.lower(Group.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Group with this name already exists")

    group = Group(name=name, creator_id=current_user.id)
    db.add(group)
    db.commit()
    db.refresh(group)

    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_GROUP,
        resource_type="group",
        resource_id=group.id,
        details={"name": group.name},
    )
    return _to_out(group)


@router.delete("/{group_id}", response_model=dict)
def delete_group(
    *,
    db: Session = Depends(deps.get_db),
    group_id: UUID,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    """Delete a group (admin only)."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    name = group.name
    db.delete(group)
    db.commit()

    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.DELETE_GROUP,
        resource_type="group",
        resource_id=group_id,
        details={"name": name},
    )
    return {"ok": True}
