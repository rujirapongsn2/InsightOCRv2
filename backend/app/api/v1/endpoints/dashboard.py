from typing import Any, List, Dict
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.api import deps
from app.models.job import Job
from app.models.document import Document
from app.models.schema import DocumentSchema

router = APIRouter()

@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(deps.get_db),
    current_user: Any = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get dashboard statistics:
    - Daily usage (last 7 days)
    - Schema usage (top schemas)
    - Recent jobs (last 5)
    """
    
    # 1. Daily Usage (Last 7 Days)
    today = datetime.utcnow().date()
    seven_days_ago = today - timedelta(days=6)
    
    # Query for job counts per day
    # Note: This assumes created_at is a DateTime. We cast to Date for grouping.
    daily_stats = (
        db.query(
            func.date(Job.created_at).label("day"),
            func.count(Job.id).label("count")
        )
        .filter(Job.created_at >= seven_days_ago)
        .group_by(func.date(Job.created_at))
        .all()
    )
    
    # Format daily usage to ensure all 7 days are present
    daily_usage_map = {str(stat.day): stat.count for stat in daily_stats}
    daily_usage = []
    for i in range(7):
        date = seven_days_ago + timedelta(days=i)
        date_str = str(date)
        daily_usage.append({
            "day": date_str,
            "count": daily_usage_map.get(date_str, 0)
        })

    # 2. Schema Usage (count documents per schema)
    schema_stats = (
        db.query(
            DocumentSchema.name,
            func.count(Document.id).label("count")
        )
        .join(Document, Document.schema_id == DocumentSchema.id)
        .group_by(DocumentSchema.name)
        .order_by(desc("count"))
        .limit(10) # Top 10 schemas
        .all()
    )
    
    schema_usage = [{"name": stat.name, "count": stat.count} for stat in schema_stats]

    # 3. Recent Jobs
    recent_jobs_query = (
        db.query(Job)
        .order_by(desc(Job.created_at))
        .limit(5)
        .all()
    )
    # Serialize jobs to plain dicts to avoid JSON encoding errors with SQLAlchemy objects
    recent_jobs = [
        {
            "id": str(job.id),
            "name": job.name,
            "status": job.status,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "schema_id": str(job.schema_id) if job.schema_id else None,
        }
        for job in recent_jobs_query
    ]

    return {
        "daily_usage": daily_usage,
        "schema_usage": schema_usage,
        "recent_jobs": recent_jobs
    }
