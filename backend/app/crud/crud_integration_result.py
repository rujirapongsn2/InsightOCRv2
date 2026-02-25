"""CRUD operations for IntegrationResult model."""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.integration_result import IntegrationResult


class CRUDIntegrationResult:
    """CRUD operations for IntegrationResult."""

    def create(
        self,
        db: Session,
        *,
        job_id: UUID,
        integration_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        integration_type: Optional[str] = None,
        integration_name: Optional[str] = None,
        status: str = "success",
        output: Optional[str] = None,
        error_message: Optional[str] = None,
        model_used: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> IntegrationResult:
        """Create a new integration result record."""
        db_obj = IntegrationResult(
            job_id=job_id,
            integration_id=integration_id,
            user_id=user_id,
            integration_type=integration_type,
            integration_name=integration_name,
            status=status,
            output=output,
            error_message=error_message,
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def get(self, db: Session, result_id: UUID) -> Optional[IntegrationResult]:
        """Get a single result by ID."""
        return db.query(IntegrationResult).filter(IntegrationResult.id == result_id).first()

    def get_by_job(
        self,
        db: Session,
        job_id: UUID,
        limit: int = 50,
    ) -> List[IntegrationResult]:
        """Get all results for a job, newest first."""
        return (
            db.query(IntegrationResult)
            .filter(IntegrationResult.job_id == job_id)
            .order_by(IntegrationResult.created_at.desc())
            .limit(limit)
            .all()
        )


integration_result = CRUDIntegrationResult()
