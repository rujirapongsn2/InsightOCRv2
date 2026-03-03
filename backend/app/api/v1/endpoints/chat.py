import json
from typing import Dict, Any, Optional
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from openai import OpenAI

from app.api import deps
from app.models.user import User
from app.models.document import Document
from app.crud.crud_chat import chat as crud_chat
from app.crud.crud_integration import integration as crud_integration
from app.schemas.chat import (
    ChatConversationCreate,
    ChatConversationDetailResponse,
    ChatConversationResponse,
    ChatMessageCreate,
    ChatMessageResponse,
)
from app.api.v1.endpoints.integrations import _supports_reasoning

router = APIRouter()


CHATDOC_SYSTEM_INSTRUCTIONS = """You are ChatDOC — a document analysis assistant for InsightDOC.

You have access to OCR-processed documents from this job. Your capabilities:
- Answer questions about document content
- Compare data across multiple documents
- Summarize information from documents
- Extract specific data points
- Identify discrepancies between documents

When referencing specific data, always cite the document filename.
Respond in the same language the user uses (Thai or English)."""


def _build_chat_document_context(documents: list) -> str:
    """Build context from job documents for ChatDOC."""
    doc_blocks = []
    for doc in documents:
        parts = [f"## Document: {doc.filename} ({doc.page_count or '?'} pages)"]

        # Use reviewed_data > extracted_data (compact, structured)
        data = doc.reviewed_data or doc.extracted_data
        if data:
            parts.append(
                f"### Structured Data\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
            )

        # Add ocr_text (truncate if too long)
        if doc.ocr_text:
            text = doc.ocr_text[:8000]
            if len(doc.ocr_text) > 8000:
                text += f"\n... (truncated, {len(doc.ocr_text)} chars total)"
            parts.append(f"### OCR Text\n{text}")

        doc_blocks.append("\n\n".join(parts))

    return "\n\n---\n\n".join(doc_blocks)


def _format_conversation_history(messages: list, limit: int = 20) -> str:
    """Format recent conversation messages for LLM context."""
    recent = messages[-limit:] if len(messages) > limit else messages
    lines = []
    for msg in recent:
        role_label = "User" if msg.role == "user" else "Assistant"
        lines.append(f"**{role_label}:** {msg.content}")
    return "\n\n".join(lines)


# ============================================================================
# Conversation CRUD
# ============================================================================


@router.post("/conversations", response_model=ChatConversationResponse, status_code=201)
async def create_conversation(
    data: ChatConversationCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Create a new chat conversation for a job."""
    conversation = crud_chat.create_conversation(
        db,
        job_id=data.job_id,
        user_id=current_user.id,
        integration_id=data.integration_id,
    )
    return ChatConversationResponse(
        id=conversation.id,
        job_id=conversation.job_id,
        integration_id=conversation.integration_id,
        title=conversation.title,
        created_at=conversation.created_at,
        message_count=0,
    )


@router.get("/conversations", response_model=list[ChatConversationResponse])
async def list_conversations(
    job_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """List conversations for a job (current user only)."""
    conversations = crud_chat.get_conversations_by_job(db, job_id=job_id, user_id=current_user.id)
    result = []
    for conv in conversations:
        count = crud_chat.get_message_count(db, conv.id)
        result.append(
            ChatConversationResponse(
                id=conv.id,
                job_id=conv.job_id,
                integration_id=conv.integration_id,
                title=conv.title,
                created_at=conv.created_at,
                message_count=count,
            )
        )
    return result


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Get conversation with all messages."""
    conv = crud_chat.get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    messages = crud_chat.get_messages(db, conversation_id)
    count = len(messages)

    return ChatConversationDetailResponse(
        id=conv.id,
        job_id=conv.job_id,
        integration_id=conv.integration_id,
        title=conv.title,
        created_at=conv.created_at,
        message_count=count,
        messages=[
            ChatMessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                model_used=m.model_used,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Delete a conversation."""
    conv = crud_chat.get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    crud_chat.delete_conversation(db, conversation_id)
    return None


# ============================================================================
# Chat Message + Streaming
# ============================================================================


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    data: ChatMessageCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Send a message and stream the assistant's response via SSE.

    Events:
      data: {"type":"delta","text":"..."}
      data: {"type":"done","full_output":"...","message_id":"..."}
      data: {"type":"error","message":"..."}
    """
    # Validate conversation
    conv = crud_chat.get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    # Save user message
    user_msg = crud_chat.add_message(
        db, conversation_id=conversation_id, role="user", content=data.content
    )

    # Auto-generate title from first message
    existing_messages = crud_chat.get_messages(db, conversation_id)
    user_messages = [m for m in existing_messages if m.role == "user"]
    if len(user_messages) == 1:
        title = data.content[:50]
        if len(data.content) > 50:
            title += "..."
        crud_chat.update_title(db, conversation_id, title)

    # Load integration config
    integration = crud_integration.get(db, integration_id=conv.integration_id) if conv.integration_id else None
    if not integration:
        raise HTTPException(status_code=400, detail="No LLM integration linked to this conversation")
    if integration.type != "llm":
        raise HTTPException(status_code=400, detail="Integration is not an LLM type")

    llm_api_key = integration.config.get("apiKey")
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="API Key is missing from integration config")

    llm_model = integration.config.get("model", "gpt-4o")
    llm_base_url = integration.config.get("baseUrl")
    llm_reasoning_effort = integration.config.get("reasoningEffort", "low")

    # Load documents for context
    documents = (
        db.query(Document)
        .filter(Document.job_id == conv.job_id)
        .filter(Document.status.in_(["extraction_completed", "reviewed"]))
        .all()
    )
    document_context = _build_chat_document_context(documents)

    # Build conversation history (exclude the message we just added — it's the current question)
    history_messages = [m for m in existing_messages if m.id != user_msg.id]
    formatted_history = _format_conversation_history(history_messages)

    # Build LLM input
    input_text = f"""# Documents in this Job

{document_context}"""

    if formatted_history:
        input_text += f"""

---

# Conversation History

{formatted_history}"""

    input_text += f"""

---

# Current Question

{data.content}"""

    async def _event_generator():
        full_output = ""
        try:
            client_kwargs: Dict[str, Any] = {"api_key": llm_api_key}
            if llm_base_url:
                client_kwargs["base_url"] = llm_base_url

            client = OpenAI(**client_kwargs)

            create_params: Dict[str, Any] = {
                "model": llm_model,
                "instructions": CHATDOC_SYSTEM_INSTRUCTIONS,
                "input": input_text,
                "stream": True,
            }
            if _supports_reasoning(llm_model):
                create_params["reasoning"] = {"effort": llm_reasoning_effort}

            stream = client.responses.create(**create_params)

            for event in stream:
                if hasattr(event, "type"):
                    if event.type == "response.output_text.delta":
                        delta = event.delta if hasattr(event, "delta") else ""
                        if delta:
                            full_output += delta
                            yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
                    elif event.type == "response.completed":
                        if hasattr(event, "response") and hasattr(event.response, "output_text"):
                            full_output = event.response.output_text
                    elif event.type == "response.output_text.done":
                        if hasattr(event, "text"):
                            full_output = event.text

            # Save assistant message
            assistant_msg = crud_chat.add_message(
                db,
                conversation_id=conversation_id,
                role="assistant",
                content=full_output,
                model_used=llm_model,
            )

            yield f"data: {json.dumps({'type': 'done', 'full_output': full_output, 'message_id': str(assistant_msg.id)}, ensure_ascii=False)}\n\n"

        except Exception as e:
            # Save error as assistant message so user sees it
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
