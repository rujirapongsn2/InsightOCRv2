from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.user import User
from sqlalchemy.orm import Session
from app.api import deps
from app.models.job import Job
from app.schemas.job import Job as JobSchema
from app.schemas.job import JobCreate

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
    if current_user.is_superuser:
        jobs = db.query(Job).offset(skip).limit(limit).all()
    else:
        jobs = db.query(Job).filter(Job.user_id == current_user.id).offset(skip).limit(limit).all()
    return jobs

@router.post("/", response_model=JobSchema)
def create_job(
    *,
    db: Session = Depends(deps.get_db),
    job_in: JobCreate,
    current_user = Depends(deps.get_current_user),
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
    if not current_user.is_superuser and job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
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
