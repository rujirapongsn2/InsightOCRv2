"""
Activity Logs API endpoint.
Provides access to user activity logs with role-based filtering.
"""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from uuid import UUID

from app.api import deps
from app.models import ActivityLog, User

router = APIRouter()


class ActivityLogResponse(BaseModel):
    id: str
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ActivityLogListResponse(BaseModel):
    items: List[ActivityLogResponse]
    total: int
    skip: int
    limit: int


@router.get("/", response_model=ActivityLogListResponse)
def get_activity_logs(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action: Optional[str] = Query(None, description="Filter by action type"),
    user_id: Optional[str] = Query(None, description="Filter by user ID (Admin only)"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
):
    """
    Get activity logs with role-based access control.
    
    - Admin: Can see all logs, can filter by user_id
    - Manager/User: Can only see their own logs
    """
    query = db.query(ActivityLog)
    
    # Role-based filtering
    if current_user.role == "admin":
        # Admin can see all logs and filter by user_id
        if user_id:
            query = query.filter(ActivityLog.user_id == user_id)
    else:
        # Manager and User can only see their own logs
        query = query.filter(ActivityLog.user_id == current_user.id)
    
    # Apply optional filters
    if action:
        query = query.filter(ActivityLog.action == action)
    
    if start_date:
        query = query.filter(ActivityLog.created_at >= start_date)
    
    if end_date:
        query = query.filter(ActivityLog.created_at <= end_date)
    
    # Get total count before pagination
    total = query.count()
    
    # Apply pagination and ordering
    logs = query.order_by(desc(ActivityLog.created_at)).offset(skip).limit(limit).all()
    
    # Build response with user info
    items = []
    for log in logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        items.append(ActivityLogResponse(
            id=str(log.id),
            user_id=str(log.user_id),
            user_email=user.email if user else None,
            user_name=user.full_name if user else None,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=str(log.resource_id) if log.resource_id else None,
            details=log.details,
            ip_address=log.ip_address,
            created_at=log.created_at
        ))
    
    return ActivityLogListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/actions", response_model=List[str])
def get_action_types(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Get list of available action types for filtering.
    """
    query = db.query(ActivityLog.action).distinct()
    
    # Non-admin users only see their own action types
    if current_user.role != "admin":
        query = query.filter(ActivityLog.user_id == current_user.id)
    
    actions = [row[0] for row in query.all()]
    return sorted(set(actions))
