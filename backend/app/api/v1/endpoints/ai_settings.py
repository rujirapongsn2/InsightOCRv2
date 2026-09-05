from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from openai import OpenAI
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


def _validate_agent_provider(setting: AISettings) -> None:
    if not setting.is_active or setting.provider_type != "openai_compatible" or not setting.supports_tool_calling:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent Provider must be active, OpenAI-compatible, and have verified native tool calling",
        )


def _verify_native_tool_calling(setting: AISettings) -> None:
    client = OpenAI(api_key=setting.api_key, base_url=setting.api_url or None)
    response = client.chat.completions.create(
        model=setting.model or "gpt-4o-mini",
        messages=[{"role": "user", "content": "Call the connection_check tool now."}],
        tools=[{
            "type": "function",
            "function": {
                "name": "connection_check",
                "description": "Verifies native tool calling.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }],
        tool_choice={"type": "function", "function": {"name": "connection_check"}},
    )
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    calls = getattr(message, "tool_calls", None) if message else None
    name = getattr(getattr(calls[0], "function", None), "name", None) if calls else None
    if name != "connection_check":
        raise ValueError("Provider did not return the required native tool call")


def _automatically_verify_agent_tools(setting: AISettings) -> None:
    """Record Agent tool capability as part of saving a provider connection."""
    setting.supports_tool_calling = False
    setting.agent_tools_checked_at = datetime.now(timezone.utc)
    setting.agent_tools_verification_error = None

    if not setting.is_active or setting.provider_type != "openai_compatible":
        return
    if not setting.api_url or not setting.api_key:
        setting.agent_tools_verification_error = "Provider URL and API key are required"
        return

    try:
        _verify_native_tool_calling(setting)
    except Exception as exc:  # A text-only LLM remains usable outside Agent mode.
        setting.agent_tools_verification_error = str(exc)[:1000]
        return
    setting.supports_tool_calling = True


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
    values = setting_in.model_dump()
    values["supports_tool_calling"] = False
    # Assignment requires successful verification, never a client-supplied flag.
    values["is_agent_provider"] = False
    db_setting = AISettings(**values, created_by=current_user.id)
    db.add(db_setting)
    _automatically_verify_agent_tools(db_setting)
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

    update_data = setting_in.model_dump(exclude_unset=True)
    # Capability evidence is issued by the test endpoint, never accepted from
    # a general create/update payload.
    update_data.pop("supports_tool_calling", None)
    changes_provider_connection = any(
        field in update_data for field in {"api_url", "api_key", "model", "provider_type"}
    )
    changes_active_state = update_data.get("is_active") is False
    if db_setting.is_agent_provider and (changes_provider_connection or changes_active_state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unset this provider as Agent Provider before changing its connection or disabling it",
        )

    # If setting this as default, unset other defaults
    if setting_in.is_default and setting_in.is_default != db_setting.is_default:
        db.query(AISettings).filter(AISettings.id != setting_id).update({"is_default": False})

    # Update fields
    for field, value in update_data.items():
        setattr(db_setting, field, value)

    if changes_provider_connection:
        _automatically_verify_agent_tools(db_setting)

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


@router.post("/{setting_id}/set-agent-provider", response_model=AISettingsSchema)
def set_agent_provider(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)
):
    """Set this AI provider as the Agent's LLM backend (admin only)."""
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI setting not found")
    _validate_agent_provider(db_setting)

    db.query(AISettings).filter(AISettings.id != setting_id).update({"is_agent_provider": False})
    db_setting.is_agent_provider = True
    db.commit()
    db.refresh(db_setting)
    return db_setting


@router.post("/{setting_id}/verify-agent-tools", response_model=AISettingsSchema)
def verify_agent_tools(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser),
):
    """Verify and record native tool calling for the stored provider config."""
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI setting not found")
    if not db_setting.is_active or db_setting.provider_type != "openai_compatible":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only active OpenAI-compatible providers can be verified")
    if not db_setting.api_url or not db_setting.api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider URL and API key are required")
    _automatically_verify_agent_tools(db_setting)
    db.commit()
    db.refresh(db_setting)
    if not db_setting.supports_tool_calling:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent tools verification failed: {db_setting.agent_tools_verification_error or 'Provider does not support native tool calling'}",
        )
    return db_setting


@router.delete("/{setting_id}/set-agent-provider", status_code=status.HTTP_200_OK)
def unset_agent_provider(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)
):
    """Unset this provider as Agent backend — agent will fall back to env or completion_messages."""
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI setting not found")
    db_setting.is_agent_provider = False
    db.commit()
    return {"ok": True}


@router.post("/{setting_id}/set-workflow-builder-provider", response_model=AISettingsSchema)
def set_workflow_builder_provider(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)
):
    """Set this AI provider as the AI workflow builder's LLM backend (admin only)."""
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI setting not found")

    db.query(AISettings).filter(AISettings.id != setting_id).update({"is_workflow_builder_provider": False})
    db_setting.is_workflow_builder_provider = True
    db.commit()
    db.refresh(db_setting)
    return db_setting


@router.delete("/{setting_id}/set-workflow-builder-provider", status_code=status.HTTP_200_OK)
def unset_workflow_builder_provider(
    setting_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_superuser)
):
    """Unset this provider as workflow builder backend — builder falls back to agent/active default."""
    db_setting = db.query(AISettings).filter(AISettings.id == setting_id).first()
    if not db_setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI setting not found")
    db_setting.is_workflow_builder_provider = False
    db.commit()
    return {"ok": True}


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
