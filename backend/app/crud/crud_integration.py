"""CRUD operations for Integration model."""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.integration import Integration
from app.schemas.integration import IntegrationCreate, IntegrationUpdate


class CRUDIntegration:
    """CRUD operations for Integration."""

    def get(self, db: Session, integration_id: UUID) -> Optional[Integration]:
        """Get integration by ID."""
        return db.query(Integration).filter(Integration.id == integration_id).first()

    def get_by_user(
        self,
        db: Session,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None
    ) -> List[Integration]:
        """Get all integrations for a user."""
        query = db.query(Integration).filter(Integration.user_id == user_id)

        if status:
            query = query.filter(Integration.status == status)

        return query.offset(skip).limit(limit).all()

    def get_active_by_user(self, db: Session, user_id: UUID) -> List[Integration]:
        """Get all active integrations for a user."""
        return db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.status == "active"
        ).all()

    def create(self, db: Session, integration: IntegrationCreate, user_id: UUID) -> Integration:
        """Create new integration."""
        db_integration = Integration(
            user_id=user_id,
            name=integration.name,
            type=integration.type,
            description=integration.description,
            status=integration.status,
            config=integration.config
        )
        db.add(db_integration)
        db.commit()
        db.refresh(db_integration)
        return db_integration

    def update(
        self,
        db: Session,
        integration_id: UUID,
        integration: IntegrationUpdate
    ) -> Optional[Integration]:
        """Update integration."""
        db_integration = self.get(db, integration_id)
        if not db_integration:
            return None

        update_data = integration.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_integration, field, value)

        db.commit()
        db.refresh(db_integration)
        return db_integration

    def delete(self, db: Session, integration_id: UUID) -> bool:
        """Delete integration."""
        db_integration = self.get(db, integration_id)
        if not db_integration:
            return False

        db.delete(db_integration)
        db.commit()
        return True

    def count_by_user(self, db: Session, user_id: UUID) -> int:
        """Count integrations for a user."""
        return db.query(Integration).filter(Integration.user_id == user_id).count()


integration = CRUDIntegration()
