from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.ai_settings import AISettings
from app.models.user import User
from app.schemas.ai_settings import (
    AISettings as AISettingsSchema,
    AISettingsPublic,
    AISettingsCreate,
    AISettingsUpdate,
    FieldSuggestionRequest,
    FieldSuggestionResponse
)
from app.services.ai_suggestion_service import AISuggestionService

router = APIRouter()


@router.get("/", response_model=List[AISettingsPublic])
def list_ai_settings(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_user)
):
    """
    List all AI provider settings (without exposing API keys)
    """
    settings = db.query(AISettings).offset(skip).limit(limit).all()
    return settings


@router.get("/{setting_id}", response_model=AISettingsSchema)
def get_ai_setting(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)  # Only admin can see API keys
):
    """
    Get specific AI provider setting (including API key)
    Admin only
    """
    setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI setting not found"
        )
    return setting


@router.post("/", response_model=AISettingsSchema, status_code=status.HTTP_201_CREATED)
def create_ai_setting(
    setting_in: AISettingsCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)  # Only admin can create
):
    """
    Create new AI provider setting
    Admin only
    """
    # Check if name already exists
    existing = db.query(AISettings).filter(AISettings.name == setting_in.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI setting with this name already exists"
        )

    # If this is set as default, unset other defaults
    if setting_in.is_default:
        db.query(AISettings).update({"is_default": False})

    # Create new setting
    db_setting = AISettings(
        **setting_in.model_dump(),
        created_by=current_user.id
    )
    db.add(db_setting)
    db.commit()
    db.refresh(db_setting)

    return db_setting


@router.put("/{setting_id}", response_model=AISettingsSchema)
def update_ai_setting(
    setting_id: UUID,
    setting_in: AISettingsUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)  # Only admin can update
):
    """
    Update AI provider setting
    Admin only
    """
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI setting not found"
        )

    # If setting this as default, unset other defaults
    if setting_in.is_default and setting_in.is_default != db_setting.is_default:
        db.query(AISettings).filter(AISettings.id != setting_id).update({"is_default": False})

    # Update fields
    update_data = setting_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_setting, field, value)

    db.commit()
    db.refresh(db_setting)

    return db_setting


@router.delete("/{setting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_setting(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)  # Only admin can delete
):
    """
    Delete AI provider setting
    Admin only
    """
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI setting not found"
        )

    db.delete(db_setting)
    db.commit()

    return None


@router.post("/{setting_id}/set-default", response_model=AISettingsSchema)
def set_default_ai_provider(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)
):
    """
    Set this AI provider as default
    Admin only
    """
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI setting not found"
        )

    # Unset all other defaults
    db.query(AISettings).update({"is_default": False})

    # Set this one as default
    db_setting.is_default = True
    db.commit()
    db.refresh(db_setting)

    return db_setting


@router.post("/test-connection")
async def test_ai_connection(
    provider_name: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)
):
    """
    Test connection to AI provider
    Admin only
    """
    service = AISuggestionService(db)
    result = await service.test_ai_connection(provider_name)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )

    return result


@router.post("/suggest-fields", response_model=FieldSuggestionResponse)
async def suggest_fields_from_ocr(
    request: FieldSuggestionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Suggest schema fields based on OCR content using AI

    This endpoint accepts OCR extracted text and returns suggested fields
    for schema creation.
    """
    if not request.ocr_content or len(request.ocr_content.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OCR content is required"
        )

    try:
        service = AISuggestionService(db)
        result = await service.suggest_fields_from_ocr(
            ocr_content=request.ocr_content,
            document_type=request.document_type,
            provider_name=request.ai_provider
        )
        return result

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to suggest fields: {str(e)}"
        )
