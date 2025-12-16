from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.api import deps
from app.models.template import SchemaTemplate
from app.models.schema import DocumentSchema
from app.schemas.template import (
    SchemaTemplate as SchemaTemplateSchema,
    SchemaTemplateCreate,
    SchemaTemplateUpdate,
    SchemaTemplateList
)
from app.models.user import User

router = APIRouter()


def _normalize_role(role: str | None) -> str:
    """Normalize role for permission checks"""
    if not role:
        return "user"
    return "manager" if role == "documents_admin" else role


@router.get("/", response_model=List[SchemaTemplateSchema])
def list_templates(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    category: str | None = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve templates.
    All authenticated users can read templates.
    """
    query = db.query(SchemaTemplate).filter(SchemaTemplate.is_active == True)

    # Filter by category if provided
    if category and category != "all":
        query = query.filter(SchemaTemplate.category == category)

    # Order by usage_count (most popular first), then by name
    query = query.order_by(SchemaTemplate.usage_count.desc(), SchemaTemplate.name)

    templates = query.offset(skip).limit(limit).all()

    # Populate creator info
    for template in templates:
        if template.creator:
            template.created_by_email = template.creator.email
            template.created_by_name = template.creator.full_name

    return templates


@router.get("/categories", response_model=List[str])
def list_categories(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get list of all template categories.
    """
    categories = db.query(SchemaTemplate.category).filter(
        SchemaTemplate.is_active == True
    ).distinct().all()

    return [cat[0] for cat in categories if cat[0]]


@router.get("/{template_id}", response_model=SchemaTemplateSchema)
def get_template(
    template_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get template by ID.
    All authenticated users can read templates.
    """
    template = db.query(SchemaTemplate).filter(
        SchemaTemplate.id == template_id,
        SchemaTemplate.is_active == True
    ).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    # Populate creator info
    if template.creator:
        template.created_by_email = template.creator.email
        template.created_by_name = template.creator.full_name

    return template


@router.post("/", response_model=SchemaTemplateSchema)
def create_template(
    *,
    db: Session = Depends(deps.get_db),
    template_in: SchemaTemplateCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new template.
    Only Admins and Managers can create templates.
    """
    normalized = _normalize_role(current_user.role)
    if not (current_user.is_superuser or normalized in ["admin", "manager"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create template."
        )

    # Only admins can create system templates
    if template_in.is_system_template and not (current_user.is_superuser or normalized == "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create system templates."
        )

    db_template = SchemaTemplate(
        name=template_in.name,
        description=template_in.description,
        document_type=template_in.document_type,
        category=template_in.category,
        thumbnail_url=template_in.thumbnail_url,
        fields=[field.dict() for field in template_in.fields],
        is_system_template=template_in.is_system_template,
        created_by=None if template_in.is_system_template else current_user.id,
        usage_count=0,
        is_active=True,
    )

    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template


@router.put("/{template_id}", response_model=SchemaTemplateSchema)
def update_template(
    *,
    template_id: str,
    db: Session = Depends(deps.get_db),
    template_in: SchemaTemplateUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update template.
    - Admins can update any template
    - Managers can only update templates they created (non-system)
    """
    template = db.query(SchemaTemplate).filter(SchemaTemplate.id == template_id).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    normalized = _normalize_role(current_user.role)
    is_admin = current_user.is_superuser or normalized == "admin"

    # Permission check
    if not is_admin:
        # Managers can only edit templates they created (non-system)
        if normalized == "manager":
            if template.is_system_template:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot edit system templates."
                )
            if template.created_by != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Can only edit templates you created."
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to update template."
            )

    # Update fields
    update_data = template_in.dict(exclude_unset=True)

    if "fields" in update_data and update_data["fields"]:
        update_data["fields"] = [field.dict() for field in update_data["fields"]]

    for field, value in update_data.items():
        setattr(template, field, value)

    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", response_model=SchemaTemplateSchema)
def delete_template(
    *,
    template_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete (soft delete) template.
    - Admins can delete any template
    - Managers can only delete templates they created (non-system)
    """
    template = db.query(SchemaTemplate).filter(SchemaTemplate.id == template_id).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    normalized = _normalize_role(current_user.role)
    is_admin = current_user.is_superuser or normalized == "admin"

    # Permission check
    if not is_admin:
        # Managers can only delete templates they created (non-system)
        if normalized == "manager":
            if template.is_system_template:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot delete system templates."
                )
            if template.created_by != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Can only delete templates you created."
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to delete template."
            )

    # Soft delete
    template.is_active = False
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/use", response_model=dict)
def use_template(
    *,
    template_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Increment usage count for a template.
    Called when a user starts creating a schema from this template.
    """
    template = db.query(SchemaTemplate).filter(
        SchemaTemplate.id == template_id,
        SchemaTemplate.is_active == True
    ).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    # Increment usage count
    template.usage_count += 1
    db.add(template)
    db.commit()

    return {"message": "Template usage recorded", "usage_count": template.usage_count}
