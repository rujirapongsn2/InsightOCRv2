from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from uuid import UUID
import os
from urllib.parse import quote

from app.api import deps
from app.agent.loop import AgentLoop
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_memory import agent_memory as crud_memory
from app.crud.crud_agent_pending import agent_pending as crud_pending
from app.crud.crud_agent_skill import agent_skill as crud_skill
from app.crud.crud_integration import integration as crud_integration
from app.models.job import Job
from app.models.ai_settings import AISettings
from app.core.config import settings
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


def _get_default_agent_ai_settings(db: Session) -> AISettings:
    setting = db.query(AISettings).filter(
        AISettings.is_default == True,
        AISettings.is_active == True,
    ).first()
    if not setting:
        setting = db.query(AISettings).filter(AISettings.is_active == True).first()
    if not setting:
        raise HTTPException(status_code=400, detail="No active default AI provider configured")
    if not setting.api_url or not setting.api_key:
        raise HTTPException(status_code=400, detail="Default AI provider is missing URL or key")
    return setting


def _build_agent_llm_config(db: Session, conv) -> dict:
    if conv.integration_id:
        integration = _ensure_llm_integration(db, conv.integration_id)
        return {
            "provider": "openai_compatible",
            "apiKey": integration.config.get("apiKey"),
            "baseUrl": integration.config.get("baseUrl"),
            "model": integration.config.get("model", settings.AGENT_MODEL or "gpt-4o-mini"),
        }

    if settings.AGENT_PROVIDER_KEY:
        return {
            "provider": "openai_compatible",
            "apiKey": settings.AGENT_PROVIDER_KEY,
            "baseUrl": settings.AGENT_PROVIDER_URL,
            "model": settings.AGENT_MODEL or "gpt-4o-mini",
            "source": "system_agent_provider",
        }

    # Check for an ai_settings entry explicitly marked as the agent provider.
    # This is the recommended path when AGENT_PROVIDER_KEY is not set via env.
    agent_setting = db.query(AISettings).filter(
        AISettings.is_agent_provider == True,
        AISettings.is_active == True,
    ).first()
    if agent_setting and agent_setting.api_url and agent_setting.api_key:
        provider_type = getattr(agent_setting, "provider_type", None) or "openai_compatible"
        model = getattr(agent_setting, "model", None) or "gpt-4o-mini"
        if provider_type == "openai_compatible":
            return {
                "provider": "openai_compatible",
                "apiKey": agent_setting.api_key,
                "baseUrl": agent_setting.api_url,
                "model": model,
                "source": "ai_settings_agent_provider",
            }
        return {
            "provider": "completion_messages",
            "apiUrl": agent_setting.api_url,
            "apiKey": agent_setting.api_key,
            "model": model,
            "source": "ai_settings_agent_provider",
        }

    # Backward-compatible fallback for environments that only configured the
    # older schema-suggestion provider. This is less capable than the dedicated
    # Agent provider because it may not support native tool calling.
    setting = _get_default_agent_ai_settings(db)
    return {
        "provider": "completion_messages",
        "apiUrl": setting.api_url,
        "apiKey": setting.api_key,
        "model": getattr(setting, "model", None) or setting.name,
        "source": "fallback_ai_settings",
    }


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
    llm_config = _build_agent_llm_config(db, conv)

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
            with open(local_path, "rb") as file_obj:
                file_content = file_obj.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

    filename = os.path.basename(path)
    encoded_filename = quote(filename)
    ext = os.path.splitext(filename)[1].lower()
    media_type = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".zip": "application/zip",
    }.get(ext, "application/octet-stream")

    return StreamingResponse(
        iter([file_content]),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(len(file_content)),
        },
    )


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


# ---------------------------------------------------------------------------
# Agent success metrics (admin dashboard)
# ---------------------------------------------------------------------------

def _tool_result_failed(result) -> bool:
    """Mirror AgentLoop._tool_failed: a dict carrying an error or ok=false."""
    return isinstance(result, dict) and ("error" in result or result.get("ok") is False)


def _classify_runs(messages, max_iter_by_conv: dict, default_max_iter: int):
    """Group ordered messages into runs (one run per user message) and tally outcomes.

    A run runs from one user message up to (but not including) the next user
    message in the same conversation. Outcome heuristic:
      - completed       : ends with a plain assistant text answer, below the cap
      - max_iterations  : that final answer landed at the conversation's cap
      - errored         : the run never produced a final assistant answer
                          (loop returned early on an LLM/stream error, or the
                          last activity is a tool / tool-call message)
    """
    by_conv: dict = {}
    for m in messages:
        by_conv.setdefault(m.conversation_id, []).append(m)

    completed = max_hit = errored = 0
    iteration_totals = 0
    counted_runs = 0

    for conv_id, msgs in by_conv.items():
        cap = max_iter_by_conv.get(conv_id) or default_max_iter
        # Split into runs on each user message.
        runs: list[list] = []
        current: list = []
        for m in msgs:
            if m.role == "user":
                if current:
                    runs.append(current)
                current = [m]
            elif current:
                current.append(m)
        if current:
            runs.append(current)

        for run in runs:
            # A run must start with a user message to be a real run.
            if not run or run[0].role != "user":
                continue
            counted_runs += 1
            run_max_iter = max((m.iteration or 0) for m in run)
            iteration_totals += run_max_iter

            last = run[-1]
            is_final_answer = (
                last.role == "assistant"
                and bool((last.content or "").strip())
                and not last.tool_calls
            )
            if not is_final_answer:
                errored += 1
            elif run_max_iter >= cap:
                max_hit += 1
            else:
                completed += 1

    avg_iterations = round(iteration_totals / counted_runs, 2) if counted_runs else 0.0
    return {
        "total_runs": counted_runs,
        "completed": completed,
        "hit_max_iterations": max_hit,
        "errored": errored,
        "success_rate": round(completed / counted_runs, 4) if counted_runs else 0.0,
        "avg_iterations": avg_iterations,
    }


@router.get("/metrics")
async def agent_metrics(
    days: int = 30,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    """Aggregate AI Agent reliability metrics for an admin dashboard.

    Computed from existing data in agent_messages / agent_conversations /
    agent_pending_actions — no new instrumentation required. Use `days` to
    bound the window (0 or negative = all time).
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="The user doesn't have enough privileges")

    from datetime import datetime, timedelta, timezone
    from app.models.agent_message import AgentMessage
    from app.models.agent_conversation import AgentConversation
    from app.models.agent_pending_action import AgentPendingAction

    since = None
    if days and days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)

    # max_iterations per conversation (for the cap comparison)
    conv_rows = db.query(AgentConversation.id, AgentConversation.max_iterations).all()
    max_iter_by_conv = {cid: (mi or 15) for cid, mi in conv_rows}

    # Pull only the columns the run classifier needs, in chronological order.
    msg_q = db.query(
        AgentMessage.conversation_id,
        AgentMessage.role,
        AgentMessage.content,
        AgentMessage.tool_calls,
        AgentMessage.tool_name,
        AgentMessage.tool_result,
        AgentMessage.iteration,
        AgentMessage.created_at,
    )
    if since is not None:
        msg_q = msg_q.filter(AgentMessage.created_at >= since)
    messages = msg_q.order_by(
        AgentMessage.conversation_id, AgentMessage.created_at
    ).all()

    run_stats = _classify_runs(messages, max_iter_by_conv, default_max_iter=15)

    # Tool failure rate per tool name.
    tool_stats: dict = {}
    for m in messages:
        if m.role != "tool" or not m.tool_name:
            continue
        entry = tool_stats.setdefault(m.tool_name, {"calls": 0, "failures": 0})
        entry["calls"] += 1
        if _tool_result_failed(m.tool_result):
            entry["failures"] += 1

    tools = [
        {
            "tool_name": name,
            "calls": s["calls"],
            "failures": s["failures"],
            "failure_rate": round(s["failures"] / s["calls"], 4) if s["calls"] else 0.0,
        }
        for name, s in sorted(
            tool_stats.items(),
            key=lambda kv: (kv[1]["failures"] / kv[1]["calls"] if kv[1]["calls"] else 0, kv[1]["calls"]),
            reverse=True,
        )
    ]
    total_tool_calls = sum(s["calls"] for s in tool_stats.values())
    total_tool_failures = sum(s["failures"] for s in tool_stats.values())

    # Confirmation outcomes (human-in-the-loop gate).
    pend_q = db.query(AgentPendingAction.status, func.count(AgentPendingAction.id))
    if since is not None:
        pend_q = pend_q.filter(AgentPendingAction.created_at >= since)
    pend_rows = pend_q.group_by(AgentPendingAction.status).all()
    pend_counts = {status: count for status, count in pend_rows}
    confirmed = pend_counts.get("confirmed", 0)
    rejected = pend_counts.get("rejected", 0)
    resolved = confirmed + rejected

    return {
        "window_days": days if (days and days > 0) else None,
        "runs": run_stats,
        "tools": {
            "total_calls": total_tool_calls,
            "total_failures": total_tool_failures,
            "overall_failure_rate": round(total_tool_failures / total_tool_calls, 4) if total_tool_calls else 0.0,
            "per_tool": tools,
        },
        "confirmations": {
            "pending": pend_counts.get("pending", 0),
            "confirmed": confirmed,
            "rejected": rejected,
            "rejection_rate": round(rejected / resolved, 4) if resolved else 0.0,
        },
    }
