from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from uuid import UUID
import tempfile
import os

from app.api import deps
from app.agent.loop import AgentLoop
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_memory import agent_memory as crud_memory
from app.crud.crud_agent_pending import agent_pending as crud_pending
from app.crud.crud_agent_skill import agent_skill as crud_skill
from app.crud.crud_integration import integration as crud_integration
from app.models.job import Job
from app.schemas.agent import (
    AgentConversationCreate,
    AgentConversationResponse,
    AgentMessageCreate,
    AgentSkillCreate,
    AgentSkillUpdate,
    AgentSkillResponse,
    AgentSkillImportRequest,
    ConfirmActionRequest,
)
from app.services.storage import get_storage_service

router = APIRouter()


def _enum_value(value):
    return value.value if hasattr(value, "value") else str(value)


def _ensure_job_access(db: Session, job_id: UUID, current_user):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _ensure_llm_integration(db: Session, integration_id: UUID):
    integration = crud_integration.get(db, integration_id=integration_id)
    if not integration:
        raise HTTPException(status_code=400, detail="Integration not found")
    if _enum_value(integration.type) != "llm":
        raise HTTPException(status_code=400, detail="Integration is not LLM type")
    if _enum_value(integration.status) != "active":
        raise HTTPException(status_code=400, detail="Integration is not active")
    return integration


@router.post("/conversations", status_code=201)
async def create_agent_conversation(
    data: AgentConversationCreate,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    _ensure_job_access(db, data.job_id, current_user)
    if data.integration_id:
        _ensure_llm_integration(db, data.integration_id)
    conv = crud_conv.create(db, job_id=data.job_id, user_id=current_user.id, integration_id=data.integration_id, max_iterations=data.max_iterations or 15)
    return {
        "id": str(conv.id), "job_id": str(conv.job_id),
        "integration_id": str(conv.integration_id) if conv.integration_id else None,
        "title": conv.title, "max_iterations": conv.max_iterations,
        "created_at": conv.created_at.isoformat(), "message_count": 0,
    }


@router.get("/conversations")
async def list_agent_conversations(
    job_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    _ensure_job_access(db, job_id, current_user)
    convs = crud_conv.get_by_job(db, job_id=job_id, user_id=current_user.id)
    return [{"id": str(c.id), "job_id": str(c.job_id), "integration_id": str(c.integration_id) if c.integration_id else None, "title": c.title, "max_iterations": c.max_iterations, "created_at": c.created_at.isoformat(), "message_count": len(crud_conv.get_messages(db, c.id, limit=200))} for c in convs]


@router.get("/memories")
async def list_agent_memories(
    job_id: UUID,
    scope: str = "user",
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    _ensure_job_access(db, job_id, current_user)
    if scope not in {"user", "job"}:
        raise HTTPException(status_code=400, detail="scope must be user or job")
    memories = crud_memory.list_by_scope(
        db,
        user_id=current_user.id,
        scope=scope,
        job_id=job_id if scope == "job" else None,
    )
    return {
        "count": len(memories),
        "memories": [
            {
                "id": str(m.id),
                "scope": m.scope,
                "memory_type": m.memory_type,
                "key": m.key,
                "content": m.content,
                "importance": m.importance,
                "access_count": m.access_count,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in memories
        ],
    }


@router.get("/conversations/{conversation_id}")
async def get_agent_conversation(
    conversation_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    conv = crud_conv.get(db, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404)
    _ensure_job_access(db, conv.job_id, current_user)
    messages = crud_conv.get_messages(db, conversation_id)
    return {
        "conversation": {"id": str(conv.id), "job_id": str(conv.job_id), "title": conv.title, "max_iterations": conv.max_iterations, "created_at": conv.created_at.isoformat()},
        "messages": [{"id": str(m.id), "role": m.role, "content": m.content, "tool_calls": m.tool_calls, "tool_call_id": m.tool_call_id, "tool_name": m.tool_name, "tool_result": m.tool_result, "iteration": m.iteration, "model_used": m.model_used, "created_at": m.created_at.isoformat()} for m in messages],
    }


@router.post("/conversations/{conversation_id}/messages")
async def send_agent_message(
    conversation_id: UUID,
    data: AgentMessageCreate,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    conv = crud_conv.get(db, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404)
    _ensure_job_access(db, conv.job_id, current_user)
    if not conv.integration_id:
        raise HTTPException(status_code=400, detail="No LLM integration linked")

    integration = _ensure_llm_integration(db, conv.integration_id)

    llm_config = {
        "apiKey": integration.config.get("apiKey"),
        "baseUrl": integration.config.get("baseUrl"),
        "model": integration.config.get("model", "gpt-4o"),
    }

    loop = AgentLoop(db=db, conversation_id=conversation_id, user_id=current_user.id, job_id=conv.job_id, llm_config=llm_config, max_iterations=conv.max_iterations)

    return StreamingResponse(
        loop.run(data.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/confirm/{pending_action_id}")
async def confirm_pending_action(
    pending_action_id: UUID,
    data: ConfirmActionRequest,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    action = crud_pending.get(db, pending_action_id)
    if not action or action.user_id != current_user.id:
        raise HTTPException(status_code=404)
    if action.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action is {action.status}")
    crud_pending.resolve(db, pending_action_id, "confirmed" if data.approved else "rejected")
    return {"ok": True}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_agent_conversation(
    conversation_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    conv = crud_conv.get(db, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404)
    crud_conv.delete(db, conversation_id)


@router.get("/files/download")
async def download_agent_file(
    conversation_id: UUID,
    path: str,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Download a file created by the agent. Scoped to the conversation's job."""
    conv = crud_conv.get(db, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404)

    # Block path traversal
    if ".." in path:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    scoped = f"jobs/{conv.job_id}/{path.lstrip('/')}"
    storage = get_storage_service()

    if not storage.exists(scoped):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        with storage.get_local_path(scoped) as local_path:
            filename = os.path.basename(path)
            return FileResponse(
                local_path,
                media_type="application/octet-stream",
                filename=filename,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Skills CRUD (agentskills.io compatible)
# ═══════════════════════════════════════════════════════════════════════════════

def _skill_to_response(skill) -> dict:
    return {
        "id": str(skill.id),
        "name": skill.name,
        "scope": skill.scope,
        "description": skill.description,
        "procedure": skill.procedure,
        "trigger_hint": skill.trigger_hint,
        "tools_used": skill.tools_used,
        "allowed_tools": skill.allowed_tools,
        "license": getattr(skill, "license", None),
        "compatibility": getattr(skill, "compatibility", None),
        "metadata": getattr(skill, "metadata_", None),
        "success_count": skill.success_count or 0,
        "created_by": skill.created_by,
        "source": getattr(skill, "source", "db"),
        "file_path": getattr(skill, "file_path", None),
        "version": getattr(skill, "version", None),
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


@router.get("/skills")
async def list_skills(
    scope: str = None,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """List agent skills — user-scoped and system-scoped."""
    if scope == "system":
        skills = crud_skill.list_by_scope(db, scope="system")
    elif scope == "user":
        skills = crud_skill.list_by_user(db, user_id=current_user.id, include_system=False)
    else:
        skills = crud_skill.list_by_user(db, user_id=current_user.id, include_system=True)
    return {
        "count": len(skills),
        "skills": [_skill_to_response(s) for s in skills],
    }


@router.post("/skills", status_code=201)
async def create_skill(
    data: AgentSkillCreate,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Create a new agent skill."""
    name = data.name.strip().lower()
    if not name or "--" in name or name.startswith("-") or name.endswith("-"):
        raise HTTPException(status_code=400, detail="Invalid skill name format")
    scope = data.scope or "user"
    if scope not in ("user", "system"):
        raise HTTPException(status_code=400, detail="scope must be 'user' or 'system'")

    user_id = current_user.id if scope == "user" else None
    existing = crud_skill.get_by_name(db, user_id=user_id, name=name, scope=scope)
    if existing:
        raise HTTPException(status_code=409, detail=f"Skill '{name}' already exists")

    try:
        skill = crud_skill.create(
            db, user_id=user_id, scope=scope,
            name=name, description=data.description, procedure=data.procedure,
            trigger_hint=data.trigger_hint, tools_used=data.tools_used,
            allowed_tools=data.allowed_tools,
            license_=data.license, compatibility=data.compatibility,
            metadata_=data.metadata, created_by="user",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create skill: {str(e)}")

    return _skill_to_response(skill)


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Get a single skill by ID."""
    from app.models.agent_skill import AgentSkill
    skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.scope == "user" and skill.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _skill_to_response(skill)


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: UUID,
    data: AgentSkillUpdate,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Update an existing skill."""
    from app.models.agent_skill import AgentSkill
    skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.scope == "user" and skill.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Skill not found")

    updates = data.model_dump(exclude_unset=True)
    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")
    if "license" in updates:
        updates["license_"] = updates.pop("license")

    for k, v in updates.items():
        if hasattr(skill, k) and v is not None:
            setattr(skill, k, v)
    db.commit()
    db.refresh(skill)
    return _skill_to_response(skill)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Delete a skill by ID."""
    from app.models.agent_skill import AgentSkill
    skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.scope == "user" and skill.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(skill)
    db.commit()


@router.post("/skills/import")
async def import_skill(
    data: AgentSkillImportRequest,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Import a SKILL.md file from the filesystem."""
    from app.services.skill_discovery import parse_skill_md, validate_skill
    from pathlib import Path

    path = Path(data.file_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {data.file_path}")

    try:
        skill_data = parse_skill_md(str(path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse: {str(e)}")

    errors = validate_skill(skill_data)
    if errors:
        raise HTTPException(status_code=400, detail=f"Validation failed: {errors}")

    scope = data.scope or "user"
    user_id = current_user.id if scope == "user" else None

    existing = crud_skill.get_by_name(db, user_id=user_id, name=skill_data["name"], scope=scope)
    if existing and not data.overwrite:
        raise HTTPException(status_code=409, detail=f"Skill '{skill_data['name']}' already exists")
    if existing:
        crud_skill.delete_by_id(db, existing.id)

    skill = crud_skill.create(
        db, user_id=user_id, scope=scope,
        name=skill_data["name"], description=skill_data["description"],
        procedure=skill_data["body"],
        allowed_tools=skill_data.get("allowed_tools"),
        license_=skill_data.get("license"),
        compatibility=skill_data.get("compatibility"),
        metadata_=skill_data.get("metadata_"),
        created_by="imported", source="imported",
        file_path=str(path.resolve()),
    )
    return _skill_to_response(skill)


@router.get("/skills/{skill_id}/export")
async def export_skill(
    skill_id: UUID,
    format: str = "markdown",
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Export a skill as SKILL.md (markdown) or ZIP bundle."""
    from app.models.agent_skill import AgentSkill
    from app.services.skill_discovery import export_skill_to_md
    from fastapi.responses import PlainTextResponse

    skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.scope == "user" and skill.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Skill not found")

    if format == "zip":
        zip_bytes = export_skill_to_md(skill, include_bundle=True)
        from fastapi.responses import Response
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={skill.name}.zip"},
        )

    md_content = export_skill_to_md(skill, include_bundle=False)
    return PlainTextResponse(content=md_content, media_type="text/markdown")
