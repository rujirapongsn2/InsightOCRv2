"""
Activity Logger Utility
Provides helper functions for logging user activities.
"""
from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.activity_log import ActivityLog


def log_activity(
    db: Session,
    user_id: UUID,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[UUID] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> ActivityLog:
    """
    Log a user activity.
    
    Args:
        db: Database session
        user_id: ID of the user performing the action
        action: Action type (e.g., 'login', 'logout', 'upload_document')
        resource_type: Type of resource (e.g., 'document', 'job', 'schema')
        resource_id: ID of the affected resource
        details: Additional details as dict
        ip_address: Client IP address
        user_agent: Client user agent string
    
    Returns:
        Created ActivityLog instance
    """
    activity = ActivityLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


# Action type constants for consistency
class Actions:
    # Access logs
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"

    # Document actions (CRUD)
    UPLOAD_DOCUMENT = "upload_document"  # CREATE
    VIEW_DOCUMENT = "view_document"      # READ
    PROCESS_DOCUMENT = "process_document"
    REVIEW_DOCUMENT = "review_document"   # UPDATE
    UPDATE_DOCUMENT = "update_document"   # UPDATE
    DELETE_DOCUMENT = "delete_document"   # DELETE

    # Job actions (CRUD)
    CREATE_JOB = "create_job"
    VIEW_JOB = "view_job"
    UPDATE_JOB = "update_job"
    DELETE_JOB = "delete_job"

    # Schema actions (CRUD)
    CREATE_SCHEMA = "create_schema"
    VIEW_SCHEMA = "view_schema"
    UPDATE_SCHEMA = "update_schema"
    DELETE_SCHEMA = "delete_schema"

    # Integration actions (CRUD)
    CREATE_INTEGRATION = "create_integration"
    VIEW_INTEGRATION = "view_integration"
    UPDATE_INTEGRATION = "update_integration"
    DELETE_INTEGRATION = "delete_integration"
    SEND_TO_INTEGRATION = "send_to_integration"

    # User actions (admin only - CRUD)
    CREATE_USER = "create_user"
    VIEW_USER = "view_user"
    UPDATE_USER = "update_user"
    DELETE_USER = "delete_user"
    CHANGE_PASSWORD = "change_password"
    CREATE_API_TOKEN = "create_api_token"
    REVOKE_API_TOKEN = "revoke_api_token"

    # Settings actions
    VIEW_SETTINGS = "view_settings"
    UPDATE_SETTINGS = "update_settings"

    # Chat actions
    CHAT_CREATE_CONVERSATION = "chat_create_conversation"
    CHAT_SEND_MESSAGE = "chat_send_message"
    CHAT_DELETE_CONVERSATION = "chat_delete_conversation"

    # Other actions
    EXPORT_DATA = "export_data"
