from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from uuid import UUID
from openai import OpenAI
from sqlalchemy.orm import Session
from app.api import deps
from app.models.user import User
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationUpdate,
    IntegrationResponse,
    IntegrationListResponse
)
from app.crud.crud_integration import integration as crud_integration
from app.utils.activity_logger import log_activity, Actions
import json

router = APIRouter()


# ============================================================================
# Integration CRUD Endpoints
# ============================================================================

@router.get("/", response_model=IntegrationListResponse)
async def get_integrations(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Get all integrations (all users can view all integrations).

    Query parameters:
    - skip: Number of integrations to skip (pagination)
    - limit: Maximum number of integrations to return
    - status: Filter by status (active/paused)
    """
    integrations = crud_integration.get_all(
        db=db,
        skip=skip,
        limit=limit,
        status=status
    )
    total = crud_integration.count_all(db=db)

    return IntegrationListResponse(
        integrations=integrations,
        total=total
    )
    total = crud_integration.count_by_user(db=db, user_id=current_user.id)

    return IntegrationListResponse(
        integrations=integrations,
        total=total
    )


@router.get("/active", response_model=List[IntegrationResponse])
async def get_active_integrations(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get all active integrations (all users can view all integrations)."""
    integrations = crud_integration.get_all_active(db=db)
    return integrations


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get a specific integration by ID (all users can view all integrations for LLM usage)."""
    integration = crud_integration.get(db=db, integration_id=integration_id)

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    return integration


@router.post("/", response_model=IntegrationResponse, status_code=201)
async def create_integration(
    integration_data: IntegrationCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Create a new integration (only managers and admins can create)."""
    role_value = str(current_user.role) if current_user.role else None
    normalized = deps._normalize_role(role_value)
    is_admin = current_user.is_superuser or normalized == "admin"

    if normalized != "manager" and not is_admin:
        raise HTTPException(status_code=403, detail="Only managers and admins can create integrations")

    integration = crud_integration.create(
        db=db,
        integration=integration_data,
        user_id=current_user.id
    )

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_INTEGRATION,
        resource_type="integration",
        resource_id=str(integration.id),
        details={
            "name": integration.name,
            "type": integration.type,
            "status": integration.status
        }
    )

    return integration


@router.put("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: UUID,
    integration_data: IntegrationUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Update an existing integration (only managers and admins can update their own integrations)."""
    role_value = str(current_user.role) if current_user.role else None
    normalized = deps._normalize_role(role_value)
    is_admin = current_user.is_superuser or normalized == "admin"

    # Check if integration exists
    existing = crud_integration.get(db=db, integration_id=integration_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Check permissions: admin can update any, managers can only update their own
    if not is_admin and existing.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only update your own integrations")

    # Update integration
    updated_integration = crud_integration.update(
        db=db,
        integration_id=integration_id,
        integration=integration_data
    )

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_INTEGRATION,
        resource_type="integration",
        resource_id=str(integration_id),
        details={
            "name": updated_integration.name,
            "type": updated_integration.type,
            "status": updated_integration.status
        }
    )

    return updated_integration


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Delete an integration (only managers and admins can delete their own integrations)."""
    role_value = str(current_user.role) if current_user.role else None
    normalized = deps._normalize_role(role_value)
    is_admin = current_user.is_superuser or normalized == "admin"

    # Check if integration exists
    existing = crud_integration.get(db=db, integration_id=integration_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Check permissions: admin can delete any, managers can only delete their own
    if not is_admin and existing.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own integrations")

    # Delete integration
    success = crud_integration.delete(db=db, integration_id=integration_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete integration")

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.DELETE_INTEGRATION,
        resource_type="integration",
        resource_id=str(integration_id),
        details={
            "name": existing.name,
            "type": existing.type
        }
    )

    return None


# ============================================================================
# LLM Integration Endpoints
# ============================================================================

class TestLLMRequest(BaseModel):
    apiKey: str
    baseUrl: Optional[str] = None
    model: str
    reasoningEffort: str = "low"
    instructions: str
    testInput: str


class TestLLMResponse(BaseModel):
    output: str


from typing import Optional, List, Dict, Any, Union

class DocumentInput(BaseModel):
    id: str
    filename: str
    data: Optional[Union[Dict[str, Any], List[Any], Any]] = None


class SendLLMRequest(BaseModel):
    apiKey: str
    baseUrl: Optional[str] = None
    model: str
    reasoningEffort: str = "low"
    instructions: str
    documents: List[DocumentInput]


class DocumentResult(BaseModel):
    id: str
    filename: str
    output: str
    success: bool
    error: Optional[str] = None


class SendLLMResponse(BaseModel):
    results: List[DocumentResult]


@router.post("/test-llm", response_model=TestLLMResponse)
async def test_llm(
    request: TestLLMRequest,
    current_user: User = Depends(deps.get_current_user)
):
    """
    Test LLM configuration by sending a test request to OpenAI Responses API
    """
    try:
        # Initialize OpenAI client with provided credentials
        client_kwargs = {"api_key": request.apiKey}
        if request.baseUrl:
            client_kwargs["base_url"] = request.baseUrl
        
        client = OpenAI(**client_kwargs)
        
        # Call OpenAI Responses API
        response = client.responses.create(
            model=request.model,
            reasoning={"effort": request.reasoningEffort},
            instructions=request.instructions,
            input=request.testInput,
        )
        
        # Extract output text
        output_text = response.output_text if hasattr(response, 'output_text') else str(response)
        
        return TestLLMResponse(output=output_text)
    
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"LLM test failed: {str(e)}"
        )


@router.post("/send-llm", response_model=SendLLMResponse)
async def send_to_llm(
    http_request: Request,
    request: SendLLMRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Process multiple documents with LLM using configured instructions
    """
    results = []

    # Get client info for logging
    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    try:
        # Initialize OpenAI client with provided credentials
        client_kwargs = {"api_key": request.apiKey}
        if request.baseUrl:
            client_kwargs["base_url"] = request.baseUrl

        client = OpenAI(**client_kwargs)

        for doc in request.documents:
            try:
                # Convert document data to string input
                doc_input = json.dumps(doc.data, ensure_ascii=False, indent=2) if doc.data else "No data"

                # Call OpenAI Responses API
                response = client.responses.create(
                    model=request.model,
                    reasoning={"effort": request.reasoningEffort},
                    instructions=request.instructions,
                    input=f"Document: {doc.filename}\n\nData:\n{doc_input}",
                )

                # Extract output text
                output_text = response.output_text if hasattr(response, 'output_text') else str(response)

                results.append(DocumentResult(
                    id=doc.id,
                    filename=doc.filename,
                    output=output_text,
                    success=True
                ))
            except Exception as e:
                results.append(DocumentResult(
                    id=doc.id,
                    filename=doc.filename,
                    output="",
                    success=False,
                    error=str(e)
                ))

        # Log activity for successful integration send
        successful_count = sum(1 for r in results if r.success)
        failed_count = len(results) - successful_count

        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.SEND_TO_INTEGRATION,
            resource_type="integration",
            resource_id=None,
            details={
                "integration_name": "LLM Integration",
                "integration_type": "llm",
                "model": request.model,
                "document_count": len(request.documents),
                "successful_count": successful_count,
                "failed_count": failed_count,
                "documents": [{"id": r.id, "filename": r.filename, "status": "success" if r.success else "failed"} for r in results]
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

        return SendLLMResponse(results=results)

    except Exception as e:
        # Log failed integration attempt
        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.SEND_TO_INTEGRATION,
            resource_type="integration",
            resource_id=None,
            details={
                "integration_name": "LLM Integration",
                "integration_type": "llm",
                "status": "failed",
                "error": str(e)
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

        raise HTTPException(
            status_code=400,
            detail=f"LLM processing failed: {str(e)}"
        )
