from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api import deps
from app.models.schema import DocumentSchema
from app.schemas.schema import DocumentSchema as DocumentSchemaSchema
from app.schemas.schema import DocumentSchemaCreate, DocumentSchemaUpdate
from app.models.user import User
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()

def _normalize_role(role: str | None) -> str:
    if not role:
        return "user"
    return "manager" if role == "documents_admin" else role

def _ensure_can_manage(schema: DocumentSchema, current_user: User) -> None:
    normalized = _normalize_role(current_user.role)
    is_admin = current_user.is_superuser or normalized == "admin"
    if is_admin:
        return
    if normalized == "manager" and schema.created_by == current_user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions to manage this schema.",
    )

@router.get("/", response_model=List[DocumentSchemaSchema])
def read_schemas(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve schemas.
    Admin: all schemas
    Manager: read all, manage own
    User: read-only access to all schemas (no write actions allowed)
    """
    normalized = _normalize_role(current_user.role)
    is_admin = current_user.is_superuser or normalized == "admin"

    query = db.query(DocumentSchema)

    schemas = query.offset(skip).limit(limit).all()

    for schema in schemas:
        if schema.creator:
            schema.created_by_email = schema.creator.email
            schema.created_by_name = schema.creator.full_name

    return schemas

@router.post("/", response_model=DocumentSchemaSchema)
def create_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_in: DocumentSchemaCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new schema.
    Only Admins and Managers (documents_admin) can create schemas.
    """
    normalized = _normalize_role(current_user.role)
    if not (current_user.is_superuser or normalized in ["admin", "manager"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to create schema.")

    db_schema = DocumentSchema(
        name=schema_in.name,
        description=schema_in.description,
        document_type=schema_in.document_type,
        ocr_engine=schema_in.ocr_engine,
        fields=[field.dict() for field in schema_in.fields], # Store as JSON
        created_by=current_user.id,
    )
    db.add(db_schema)
    db.commit()
    db.refresh(db_schema)

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_SCHEMA,
        resource_type="schema",
        resource_id=db_schema.id,
        details={"schema_name": db_schema.name, "document_type": db_schema.document_type}
    )

    return db_schema

@router.get("/{schema_id}", response_model=DocumentSchemaSchema)
def read_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get schema by ID (read-only for all authenticated users).
    """
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")

    if schema.creator:
        schema.created_by_email = schema.creator.email
        schema.created_by_name = schema.creator.full_name

    return schema

@router.put("/{schema_id}", response_model=DocumentSchemaSchema)
def update_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    schema_in: DocumentSchemaUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update schema.
    Admin: any schema
    Manager: only schemas created by self
    """
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")

    _ensure_can_manage(schema, current_user)

    for field, value in schema_in.dict(exclude_unset=True).items():
        if field == "fields":
            normalized_fields = []
            for f in value or []:
                if hasattr(f, "dict"):
                    normalized_fields.append(f.dict())
                else:
                    normalized_fields.append(f)
            setattr(schema, field, normalized_fields)
        else:
            setattr(schema, field, value)

    db.add(schema)
    db.commit()
    db.refresh(schema)

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_SCHEMA,
        resource_type="schema",
        resource_id=schema.id,
        details={"schema_name": schema.name}
    )

    return schema

@router.delete("/{schema_id}", response_model=DocumentSchemaSchema)
def delete_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete schema.
    Admin: any schema
    Manager: only schemas created by self
    """
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")

    _ensure_can_manage(schema, current_user)

    # Log activity before deletion
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.DELETE_SCHEMA,
        resource_type="schema",
        resource_id=schema.id,
        details={"schema_name": schema.name}
    )

    db.delete(schema)
    db.commit()
    return schema
