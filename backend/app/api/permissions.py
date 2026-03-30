from fastapi import HTTPException, status

from app.models.document import Document
from app.models.job import Job
from app.models.user import User


def normalize_role(role: str | None) -> str:
    if not role:
        return "user"
    return "manager" if role == "documents_admin" else role


def is_admin_user(user: User) -> bool:
    return bool(user.is_superuser or normalize_role(user.role) == "admin")


def can_access_job(user: User, job: Job) -> bool:
    if is_admin_user(user):
        return True
    return bool(job.user_id == user.id)


def ensure_job_access(user: User, job: Job, detail: str = "Not enough permissions") -> Job:
    if not can_access_job(user, job):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return job


def can_access_document(user: User, document: Document) -> bool:
    if is_admin_user(user):
        return True
    if document.job is None:
        return False
    return bool(document.job.user_id == user.id)


def ensure_document_access(
    user: User, document: Document, detail: str = "Not enough permissions"
) -> Document:
    if not can_access_document(user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return document
