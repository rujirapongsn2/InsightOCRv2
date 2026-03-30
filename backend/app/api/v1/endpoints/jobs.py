from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.user import User
from sqlalchemy.orm import Session
from app.api import deps
from app.api.permissions import ensure_job_access, is_admin_user
from app.models.job import Job
from app.models.document import Document
from app.schemas.job import Job as JobSchema
from app.schemas.job import JobCreate
from app.services.storage import get_storage_service
from app.utils.activity_logger import log_activity, Actions
from app.utils.job_logger import get_job_logger
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/", response_model=List[JobSchema])
def read_jobs(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve jobs.
    """
    is_admin = is_admin_user(current_user)
    if is_admin:
        jobs = db.query(Job).offset(skip).limit(limit).all()
    else:
        jobs = db.query(Job).filter(Job.user_id == current_user.id).offset(skip).limit(limit).all()
    return jobs

@router.post("/", response_model=JobSchema)
def create_job(
    *,
    db: Session = Depends(deps.get_db),
    job_in: JobCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new job.
    """
    db_job = Job(
        name=job_in.name,
        description=job_in.description,
        schema_id=job_in.schema_id,
        status="draft",
        user_id=current_user.id
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_JOB,
        resource_type="job",
        resource_id=db_job.id,
        details={"job_name": db_job.name}
    )

    # Job-specific log
    job_logger = get_job_logger(str(db_job.id))
    job_logger.info(f"Job created by user {current_user.email} (ID: {current_user.id}). Name: {db_job.name}")

    return db_job

@router.get("/{job_id}", response_model=JobSchema)
def read_job(
    *,
    db: Session = Depends(deps.get_db),
    job_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get job by ID.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_job_access(current_user, job)

    # Convert to dict and add user_name
    job_dict = {
        "id": job.id,
        "name": job.name,
        "description": job.description,
        "schema_id": job.schema_id,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "user_id": job.user_id,
        "user_name": job.user.email if job.user else None
    }
    return job_dict

@router.delete("/{job_id}")
def delete_job(
    *,
    db: Session = Depends(deps.get_db),
    job_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete a job and all its associated documents.
    Owner, admin, or superuser can delete.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check permissions: superuser, admin role, or job owner
    is_admin = is_admin_user(current_user)
    is_owner = job.user_id == current_user.id
    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    try:
        job_logger = get_job_logger(str(job.id))
        job_logger.info(f"Job deletion requested by user {current_user.email} (ID: {current_user.id}). Deleting storage files for {len(job.documents)} documents.")
        
        # Cleanup storage files for all associated documents
        storage = get_storage_service()
        documents = db.query(Document).filter(Document.job_id == job.id).all()
        for doc in documents:
            try:
                storage.delete_file(doc.file_path)
            except Exception as e:
                logger.warning(f"Failed to delete storage file {doc.file_path}: {e}")

        # Log activity before deletion
        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.DELETE_JOB,
            resource_type="job",
            resource_id=job.id,
            details={
                "job_name": job.name,
                "status": job.status,
                "documents_deleted": len(documents),
            }
        )

        db.delete(job)
        db.commit()
        
        job_logger.info(f"Job logically deleted from database successfully.")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete job {job_id}: {e}")
        try:
            job_logger.error(f"Failed to delete job: {e}", exc_info=True)
        except:
            pass
        raise HTTPException(status_code=500, detail="Failed to delete job")

    return {"message": "Job deleted successfully", "id": job_id}
