from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from uuid import UUID
from openai import OpenAI


def _build_llm_input(
    doc_filename: str,
    doc_input: str,
    user_prompt: Optional[str] = None,
    output_format_prompt: Optional[str] = None,
) -> str:
    """Compose the input string: [userPrompt] + OCR data + [outputFormatPrompt]."""
    parts: list[str] = []
    if user_prompt and user_prompt.strip():
        parts.append(user_prompt.strip())
    parts.append(f"Document: {doc_filename}\n\nData:\n{doc_input}")
    if output_format_prompt and output_format_prompt.strip():
        parts.append(output_format_prompt.strip())
    return "\n\n".join(parts)


def _build_combined_llm_input(
    documents: List[tuple],
    user_prompt: Optional[str] = None,
    output_format_prompt: Optional[str] = None,
) -> str:
    """Compose input with ALL documents combined into one block for cross-document validation."""
    import json as _json
    parts: list[str] = []
    if user_prompt and user_prompt.strip():
        parts.append(user_prompt.strip())
    doc_blocks = []
    for filename, data in documents:
        doc_json = _json.dumps(data, ensure_ascii=False, indent=2) if data is not None else "No data"
        doc_blocks.append(f"## Document: {filename}\n\n```json\n{doc_json}\n```")
    parts.append("\n\n---\n\n".join(doc_blocks))
    if output_format_prompt and output_format_prompt.strip():
        parts.append(output_format_prompt.strip())
    return "\n\n".join(parts)


def _supports_reasoning(model: str) -> bool:
    """Return True only for o-series OpenAI models that support reasoning.effort."""
    if not model:
        return False
    m = model.lower()
    return m.startswith("o1") or m.startswith("o3") or m.startswith("o4")
from sqlalchemy.orm import Session
import httpx
import json
from app.api import deps
from app.models.user import User
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationUpdate,
    IntegrationResponse,
    IntegrationListResponse
)
from app.crud.crud_integration import integration as crud_integration
from app.crud.crud_integration_result import integration_result as crud_integration_result
from app.utils.activity_logger import log_activity, Actions

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


@router.get("/results")
async def get_integration_results_by_job(
    job_id: UUID,
    limit: int = 50,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Get all integration results for a job, newest first."""
    results = crud_integration_result.get_by_job(db, job_id=job_id, limit=limit)
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "integration_id": str(r.integration_id) if r.integration_id else None,
            "integration_type": r.integration_type,
            "integration_name": r.integration_name,
            "status": r.status,
            "model_used": r.model_used,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ]


@router.get("/results/{result_id}")
async def get_integration_result(
    result_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Get a single integration result with full output."""
    result = crud_integration_result.get(db, result_id=result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return {
        "id": str(result.id),
        "job_id": str(result.job_id),
        "integration_id": str(result.integration_id) if result.integration_id else None,
        "integration_type": result.integration_type,
        "integration_name": result.integration_name,
        "status": result.status,
        "output": result.output,
        "error_message": result.error_message,
        "model_used": result.model_used,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


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
    instructions: str = ""
    userPrompt: Optional[str] = None
    outputFormatPrompt: Optional[str] = None
    testInput: str = ""


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
    userPrompt: Optional[str] = None
    outputFormatPrompt: Optional[str] = None
    documents: List[DocumentInput]


class DocumentResult(BaseModel):
    id: str
    filename: str
    output: str
    success: bool
    error: Optional[str] = None


class SendLLMResponse(BaseModel):
    results: List[DocumentResult]


class SendToIntegrationRequest(BaseModel):
    integration_id: Optional[UUID] = None
    integration_name: Optional[str] = None
    job_id: Optional[UUID] = None
    job_name: str
    documents: List[DocumentInput]


class SendToIntegrationResponse(BaseModel):
    success: bool
    message: str
    results: Optional[List[DocumentResult]] = None


def _resolve_send_target_integration(db: Session, request: SendToIntegrationRequest):
    if request.integration_id is not None:
        integration = crud_integration.get(db=db, integration_id=request.integration_id)
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")
        return integration

    if not request.integration_name or not request.integration_name.strip():
        raise HTTPException(status_code=400, detail="integration_id or integration_name is required")

    normalized_name = request.integration_name.strip().lower()
    matches = [
        integration
        for integration in crud_integration.get_all_active(db=db)
        if integration.name and integration.name.strip().lower() == normalized_name
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Integration not found")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Multiple integrations share this name; use integration_id instead")
    return matches[0]


@router.post("/test-llm", response_model=TestLLMResponse)
async def test_llm(
    request: TestLLMRequest,
    current_user: User = Depends(deps.get_current_user)
):
    """
    Test LLM connectivity by sending a minimal hello request to OpenAI Responses API.
    This endpoint intentionally ignores userPrompt/outputFormatPrompt/testInput.
    """
    try:
        # Initialize OpenAI client with provided credentials
        client_kwargs = {"api_key": request.apiKey}
        if request.baseUrl:
            client_kwargs["base_url"] = request.baseUrl
        
        client = OpenAI(**client_kwargs)

        # Build request params — reasoning.effort is only supported by o-series models
        create_params: Dict[str, Any] = {
            "model": request.model,
            "input": "hello",
        }
        if _supports_reasoning(request.model):
            create_params["reasoning"] = {"effort": request.reasoningEffort}

        # Call OpenAI Responses API
        response = client.responses.create(**create_params)

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

                # Compose input: userPrompt + OCR data + outputFormatPrompt
                composed_input = _build_llm_input(
                    doc_filename=doc.filename,
                    doc_input=doc_input,
                    user_prompt=request.userPrompt,
                    output_format_prompt=request.outputFormatPrompt,
                )

                # Build request params — reasoning.effort is only supported by o-series models
                create_params: Dict[str, Any] = {
                    "model": request.model,
                    "instructions": request.instructions,
                    "input": composed_input,
                }
                if _supports_reasoning(request.model):
                    create_params["reasoning"] = {"effort": request.reasoningEffort}

                # Call OpenAI Responses API
                response = client.responses.create(**create_params)

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
                "name": "LLM Integration",
                "type": "llm",
                "result": "success" if failed_count == 0 else "failed"
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
                "name": "LLM Integration",
                "type": "llm",
                "result": "failed"
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

        raise HTTPException(
            status_code=400,
            detail=f"LLM processing failed: {str(e)}"
        )


@router.post("/send-stream")
async def send_to_integration_stream(
    request: SendToIntegrationRequest,
    http_request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Stream LLM output as SSE events.
    Events:
      data: {"type":"delta","text":"..."}
      data: {"type":"done","full_output":"...","filename":"..."}
      data: {"type":"error","message":"..."}
    """
    import uuid as _uuid

    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    integration = _resolve_send_target_integration(db, request)

    if integration.type != "llm":
        raise HTTPException(status_code=400, detail="Streaming is only supported for LLM integrations")

    llm_api_key = integration.config.get("apiKey")
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="API Key is required for LLM integration")

    llm_model = integration.config.get("model", "gpt-4o")
    llm_base_url = integration.config.get("baseUrl")
    llm_instructions = integration.config.get("instructions", "")
    llm_user_prompt = integration.config.get("userPrompt")
    llm_output_format = integration.config.get("outputFormatPrompt")
    llm_reasoning_effort = integration.config.get("reasoningEffort", "low")

    doc_tuples = [(doc.filename, doc.data) for doc in request.documents]
    composed_input = _build_combined_llm_input(
        documents=doc_tuples,
        user_prompt=llm_user_prompt,
        output_format_prompt=llm_output_format,
    )

    report_filename = f"{request.job_name} — Validation Report"

    async def _event_generator():
        full_output = ""
        try:
            client_kwargs: Dict[str, Any] = {"api_key": llm_api_key}
            if llm_base_url:
                client_kwargs["base_url"] = llm_base_url

            client = OpenAI(**client_kwargs)

            create_params: Dict[str, Any] = {
                "model": llm_model,
                "instructions": llm_instructions,
                "input": composed_input,
                "stream": True,
            }
            if _supports_reasoning(llm_model):
                create_params["reasoning"] = {"effort": llm_reasoning_effort}

            stream = client.responses.create(**create_params)

            for event in stream:
                # OpenAI Responses API streaming emits various event types
                if hasattr(event, "type"):
                    if event.type == "response.output_text.delta":
                        delta = event.delta if hasattr(event, "delta") else ""
                        if delta:
                            full_output += delta
                            yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
                    elif event.type == "response.completed":
                        # Final event — extract full text if available
                        if hasattr(event, "response") and hasattr(event.response, "output_text"):
                            full_output = event.response.output_text
                    elif event.type == "response.output_text.done":
                        if hasattr(event, "text"):
                            full_output = event.text

            # Save result to DB
            saved_result_id = None
            if request.job_id:
                try:
                    saved = crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type="llm",
                        integration_name=integration.name,
                        status="success",
                        output=full_output,
                        model_used=llm_model,
                    )
                    saved_result_id = str(saved.id)
                except Exception:
                    pass

            done_payload: Dict[str, Any] = {
                "type": "done",
                "full_output": full_output,
                "filename": report_filename,
            }
            if saved_result_id:
                done_payload["result_id"] = saved_result_id
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

            # Log activity after stream completes
            try:
                log_activity(
                    db=db,
                    user_id=current_user.id,
                    action=Actions.SEND_TO_INTEGRATION,
                    resource_type="integration",
                    resource_id=integration.id,
                    details={
                        "job_name": request.job_name,
                        "name": integration.name,
                        "type": integration.type,
                        "result": "success",
                        "stream": True,
                    },
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
            except Exception:
                pass

        except Exception as e:
            # Save error result to DB
            if request.job_id:
                try:
                    crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type="llm",
                        integration_name=integration.name,
                        status="error",
                        error_message=str(e),
                        model_used=llm_model,
                    )
                except Exception:
                    pass

            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            try:
                log_activity(
                    db=db,
                    user_id=current_user.id,
                    action=Actions.SEND_TO_INTEGRATION,
                    resource_type="integration",
                    resource_id=integration.id,
                    details={
                        "job_name": request.job_name,
                        "name": integration.name,
                        "type": integration.type,
                        "result": "failed",
                        "stream": True,
                    },
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
            except Exception:
                pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/send", response_model=SendToIntegrationResponse)
async def send_to_integration(
    request: SendToIntegrationRequest,
    http_request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Send documents to integration endpoint (supports all integration types: llm, workflow, api)
    """
    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    integration = None

    try:
        integration = _resolve_send_target_integration(db, request)

        print(f"[DEBUG] Integration type: {integration.type}")
        print(f"[DEBUG] Integration config: {integration.config}")

        results = []
        success = False
        message = ""

        if integration.type == "llm":
            llm_api_key = integration.config.get("apiKey")
            if not llm_api_key:
                raise HTTPException(status_code=400, detail="API Key is required for LLM integration")

            llm_model = integration.config.get("model", "gpt-4o")
            llm_base_url = integration.config.get("baseUrl")
            llm_instructions = integration.config.get("instructions", "")
            llm_user_prompt = integration.config.get("userPrompt")
            llm_output_format = integration.config.get("outputFormatPrompt")
            llm_reasoning_effort = integration.config.get("reasoningEffort", "low")

            client_kwargs = {"api_key": llm_api_key}
            if llm_base_url:
                client_kwargs["base_url"] = llm_base_url

            client = OpenAI(**client_kwargs)

            # Combine all documents into ONE LLM call so cross-document validation works
            try:
                doc_tuples = [(doc.filename, doc.data) for doc in request.documents]
                composed_input = _build_combined_llm_input(
                    documents=doc_tuples,
                    user_prompt=llm_user_prompt,
                    output_format_prompt=llm_output_format,
                )

                print(f"[DEBUG] Sending {len(request.documents)} documents combined to LLM model={llm_model}")

                # Build request params — reasoning.effort only supported by o-series models
                create_params: Dict[str, Any] = {
                    "model": llm_model,
                    "instructions": llm_instructions,
                    "input": composed_input,
                }
                if _supports_reasoning(llm_model):
                    create_params["reasoning"] = {"effort": llm_reasoning_effort}

                response = client.responses.create(**create_params)
                output_text = response.output_text if hasattr(response, 'output_text') else str(response)

                print(f"[DEBUG] LLM response length: {len(output_text)} chars")

                results.append(DocumentResult(
                    id="combined",
                    filename=f"{request.job_name} — Validation Report",
                    output=output_text,
                    success=True
                ))
            except Exception as e:
                print(f"[DEBUG] LLM combined call error: {str(e)}")
                results.append(DocumentResult(
                    id="combined",
                    filename=request.job_name,
                    output="",
                    success=False,
                    error=str(e)
                ))

            successful_count = sum(1 for r in results if r.success)
            failed_count = len(results) - successful_count
            success = failed_count == 0
            message = "Sent successfully" if success else f"Partial success: {successful_count} succeeded, {failed_count} failed"

        elif integration.type == "workflow":
            webhook_url = integration.config.get("webhookUrl")
            if not webhook_url:
                raise HTTPException(status_code=400, detail="Webhook URL is required for workflow integration")

            payload = {
                "documents": [{"id": d.id, "filename": d.filename, "data": d.data} for d in request.documents]
            }

            print(f"[DEBUG] Sending to webhook: {webhook_url}")
            print(f"[DEBUG] Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")

            async with httpx.AsyncClient() as client:
                res = await client.post(webhook_url, json=payload, timeout=30.0)
                print(f"[DEBUG] Webhook response status: {res.status_code}")
                print(f"[DEBUG] Webhook response: {res.text}")
                if res.status_code >= 400:
                    raise HTTPException(status_code=res.status_code, detail=f"Webhook responded {res.status_code}: {res.text}")

            success = True
            message = "Sent successfully to workflow"

        elif integration.type == "api":
            endpoint = integration.config.get("endpoint")
            if not endpoint:
                raise HTTPException(status_code=400, detail="Endpoint URL is required for API integration")

            payload = {
                "documents": [{"id": d.id, "filename": d.filename, "data": d.data} for d in request.documents]
            }

            headers: Dict[str, str] = {"Content-Type": "application/json"}
            auth_header = integration.config.get("authHeader")
            if auth_header:
                for line in auth_header.split("\n"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        headers[parts[0].strip()] = parts[1].strip()

            headers_json = integration.config.get("headersJson")
            if headers_json:
                try:
                    parsed = json.loads(headers_json)
                    headers.update(parsed)
                except:
                    pass

            method = integration.config.get("method", "POST")

            print(f"[DEBUG] Sending to API: {method} {endpoint}")
            print(f"[DEBUG] Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")

            async with httpx.AsyncClient() as client:
                res = await client.request(method, endpoint, json=payload, headers=headers, timeout=30.0)
                print(f"[DEBUG] API response status: {res.status_code}")
                print(f"[DEBUG] API response: {res.text}")
                if res.status_code >= 400:
                    raise HTTPException(status_code=res.status_code, detail=f"API responded {res.status_code}: {res.text}")

            success = True
            message = "Sent successfully to API endpoint"

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported integration type: {integration.type}")

        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.SEND_TO_INTEGRATION,
            resource_type="integration",
            resource_id=integration.id,
            details={
                "job_name": request.job_name,
                "name": integration.name,
                "type": integration.type,
                "result": "success" if success else "failed"
            },
            ip_address=client_ip,
            user_agent=user_agent
        )

        # Save integration result for history
        if request.job_id:
            try:
                crud_integration_result.create(
                    db,
                    job_id=request.job_id,
                    integration_id=integration.id,
                    user_id=current_user.id,
                    integration_type=integration.type.value if hasattr(integration.type, "value") else str(integration.type),
                    integration_name=integration.name,
                    status="success" if success else "error",
                    output=results[0].output if results and integration.type == "llm" else None,
                    error_message=results[0].error if results and not success else None,
                    model_used=integration.config.get("model") if integration.type == "llm" else None,
                )
            except Exception:
                pass

        return SendToIntegrationResponse(
            success=success,
            message=message,
            results=results if integration.type == "llm" else None
        )

    except HTTPException as he:
        print(f"[DEBUG] HTTPException: {he.detail}")
        if integration:
            log_activity(
                db=db,
                user_id=current_user.id,
                action=Actions.SEND_TO_INTEGRATION,
                resource_type="integration",
                resource_id=integration.id,
                details={
                    "name": integration.name,
                    "type": integration.type,
                    "result": "failed"
                },
                ip_address=client_ip,
                user_agent=user_agent
            )
            if request.job_id:
                try:
                    crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type=integration.type.value if hasattr(integration.type, "value") else str(integration.type),
                        integration_name=integration.name,
                        status="error",
                        error_message=str(he.detail),
                    )
                except Exception:
                    pass
        raise

    except Exception as e:
        print(f"[DEBUG] Exception: {str(e)}")
        import traceback
        traceback.print_exc()

        if integration:
            log_activity(
                db=db,
                user_id=current_user.id,
                action=Actions.SEND_TO_INTEGRATION,
                resource_type="integration",
                resource_id=integration.id,
                details={
                    "name": integration.name,
                    "type": integration.type,
                    "result": "failed"
                },
                ip_address=client_ip,
                user_agent=user_agent
            )
            if request.job_id:
                try:
                    crud_integration_result.create(
                        db,
                        job_id=request.job_id,
                        integration_id=integration.id,
                        user_id=current_user.id,
                        integration_type=integration.type.value if hasattr(integration.type, "value") else str(integration.type),
                        integration_name=integration.name,
                        status="error",
                        error_message=str(e),
                    )
                except Exception:
                    pass

        raise HTTPException(
            status_code=400,
            detail=f"Integration send failed: {str(e)}"
        )
