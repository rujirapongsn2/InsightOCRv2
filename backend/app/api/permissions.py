from fastapi import HTTPException, status

from app.models.document import Document
from app.models.job import Job
from app.models.user import User


def normalize_role(role: str | None) -> str:
    if not role:
        return "user"
    return "manager" if role == "documents_admin" else role


def is_manager_user(user: User) -> bool:
    return normalize_role(user.role) == "manager"


def can_manage_group_resource(user: User, owner: User | None) -> bool:
    """A Manager may manage resources owned by any user who shares at least one
    group with the manager.

    Group membership is only meaningful when the manager belongs to at least
    one group and the owner is in the same group.
    """
    if not is_manager_user(user):
        return False
    user_group_ids = {g.id for g in (user.groups or [])}
    if not user_group_ids:
        return False
    if not owner:
        return False
    owner_group_ids = {g.id for g in (owner.groups or [])}
    return bool(user_group_ids & owner_group_ids)


def is_admin_user(user: User) -> bool:
    return bool(user.is_superuser or normalize_role(user.role) == "admin")


def can_access_job(user: User, job: Job) -> bool:
    if is_admin_user(user):
        return True
    if job.user_id == user.id:
        return True
    return can_manage_group_resource(user, job.user)


def ensure_job_access(user: User, job: Job, detail: str = "Not enough permissions") -> Job:
    if not can_access_job(user, job):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return job


def can_access_document(user: User, document: Document) -> bool:
    if is_admin_user(user):
        return True
    if document.job is None:
        return False
    if document.job.user_id == user.id:
        return True
    return can_manage_group_resource(user, document.job.user)


def ensure_document_access(
    user: User, document: Document, detail: str = "Not enough permissions"
) -> Document:
    if not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return document
