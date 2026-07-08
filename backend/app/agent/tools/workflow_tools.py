"""Agent tools for the AI workflow builder (category ``workflow``).

These are NOT job-scoped — they operate for `context.user_id` across all jobs the
user can access. They let the agent enumerate the building blocks (jobs, schemas,
node types, integrations, AI providers), sample real job data so job/data-source
nodes are wired to fields that actually exist, stage a draft for the live preview,
statically validate it, request credentials via a UI card (never through chat),
and finally persist the workflow — only after validation passes.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.agent.tools.registry import ToolDef, tool_registry
from app.api.permissions import can_access_job, is_admin_user
from app.crud.crud_agent_pending import agent_pending as crud_pending
from app.models.ai_settings import AISettings
from app.models.document import Document
from app.models.integration import Integration
from app.models.job import Job
from app.models.schema import DocumentSchema
from app.models.user import User
from app.models.workflow import Workflow
from app.services.workflow_engine import NODE_TYPES
from app.services.workflow_validation import validate_workflow_definition


def _owner(context) -> Optional[User]:
    return context.db.query(User).filter(User.id == context.user_id).first()


async def _list_jobs_handler(args: dict, context) -> dict:
    db = context.db
    owner = _owner(context)
    q = db.query(Job)
    if not (owner and is_admin_user(owner)):
        q = q.filter(Job.user_id == context.user_id)
    jobs = q.order_by(Job.created_at.desc()).limit(100).all()
    out = []
    for j in jobs:
        doc_count = db.query(Document).filter(Document.job_id == j.id).count()
        out.append({"id": str(j.id), "name": j.name, "status": j.status, "document_count": doc_count})
    return {"count": len(out), "jobs": out}


async def _list_document_schemas_handler(args: dict, context) -> dict:
    schemas = context.db.query(DocumentSchema).order_by(DocumentSchema.name.asc()).limit(200).all()
    out = []
    for s in schemas:
        fields = s.fields if isinstance(s.fields, list) else []
        out.append({
            "id": str(s.id),
            "name": s.name,
            "document_type": s.document_type,
            "field_names": [f.get("name") for f in fields if isinstance(f, dict) and f.get("name")],
        })
    return {"count": len(out), "schemas": out}


async def _list_node_types_handler(args: dict, context) -> dict:
    # Trimmed catalog: only what the model needs to assemble valid nodes.
    out = []
    for nt in NODE_TYPES:
        out.append({
            "type": nt["type"],
            "category": nt["category"],
            "label": nt["label"],
            "description": nt["description"],
            "config_fields": [
                {k: f.get(k) for k in ("name", "type", "required", "default", "options", "provider") if k in f}
                for f in nt.get("config_fields", [])
            ],
            "output_fields": [f.get("name") for f in nt.get("output_fields", [])],
        })
    return {"count": len(out), "node_types": out}


async def _list_integrations_handler(args: dict, context) -> dict:
    type_filter = args.get("type_filter")
    q = context.db.query(Integration).filter(Integration.user_id == context.user_id)
    out = []
    for i in q.all():
        itype = i.type.value if hasattr(i.type, "value") else str(i.type)
        istatus = i.status.value if hasattr(i.status, "value") else str(i.status)
        if type_filter and itype != type_filter:
            continue
        # No secrets — id/name/type/status only.
        out.append({"id": str(i.id), "name": i.name, "type": itype, "status": istatus})
    return {"count": len(out), "integrations": out}


async def _list_ai_providers_handler(args: dict, context) -> dict:
    providers = context.db.query(AISettings).filter(AISettings.is_active == True).all()  # noqa: E712
    out = [{
        "id": str(p.id), "name": p.display_name or p.name, "model": p.model,
        "is_workflow_builder_provider": bool(p.is_workflow_builder_provider),
        "is_agent_provider": bool(p.is_agent_provider),
        "is_default": bool(p.is_default),
    } for p in providers]
    # The provider llm nodes should default to (never ask the user to pick).
    default_id = None
    for key in ("is_workflow_builder_provider", "is_agent_provider", "is_default"):
        match = next((p for p in out if p[key]), None)
        if match:
            default_id = match["id"]
            break
    if default_id is None and out:
        default_id = out[0]["id"]
    return {"count": len(out), "ai_providers": out, "default_provider_id": default_id,
            "hint": "ตั้ง ai_provider_id ของโหนด llm เป็น default_provider_id โดยอัตโนมัติ อย่าถามผู้ใช้ว่าจะใช้โมเดลใด"}


def _sample_records(db, job: Job, data_source: str, limit: int = 3):
    docs = (
        db.query(Document)
        .filter(Document.job_id == job.id)
        .order_by(Document.uploaded_at.asc())
        .limit(limit)
        .all()
    )
    records, field_names = [], set()
    for d in docs:
        if data_source == "ocr_text":
            rec = {"ocr_text": (d.ocr_text or "")[:500]}
        else:
            rec = d.reviewed_data if data_source == "reviewed" and d.reviewed_data else d.extracted_data
        if isinstance(rec, dict):
            field_names.update(rec.keys())
            records.append(rec)
        elif isinstance(rec, list):
            for r in rec:
                if isinstance(r, dict):
                    field_names.update(r.keys())
            records.append(rec)
    return sorted(field_names), records


async def _inspect_job_data_handler(args: dict, context) -> dict:
    job_id = args.get("job_id")
    data_source = args.get("data_source") or "reviewed"
    if not job_id:
        return {"error": "job_id is required"}
    db = context.db
    owner = _owner(context)
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return {"error": f"Job not found: {job_id}"}
    if not (owner and can_access_job(owner, job)):
        return {"error": "ไม่มีสิทธิ์เข้าถึง Job นี้"}
    field_names, records = _sample_records(db, job, data_source)
    return {
        "job_id": str(job.id),
        "job_name": job.name,
        "data_source": data_source,
        "available_fields": field_names,
        "sample_records": records[:2],
        "hint": "ใช้ {{<node_id>.records.0.<field>}} เพื่ออ้างค่าจากโหนด job_source",
    }


async def _propose_workflow_handler(args: dict, context) -> dict:
    name = args.get("name") or "Untitled workflow"
    description = args.get("description") or ""
    definition = args.get("definition") or {"nodes": [], "edges": []}
    nodes = definition.get("nodes") or []
    # Returned in the tool_result → the frontend live-preview renders this DAG.
    return {
        "ok": True,
        "name": name,
        "description": description,
        "definition": definition,
        "node_count": len(nodes),
        "message": "แสดงตัวอย่าง workflow ในพรีวิวแล้ว — เรียก validate_workflow ก่อน save",
    }


async def _validate_workflow_handler(args: dict, context) -> dict:
    definition = args.get("definition") or {}
    owner = _owner(context)
    if not owner:
        return {"error": "ไม่พบผู้ใช้"}
    issues = validate_workflow_definition(context.db, definition, owner)
    errors = [i for i in issues if i["level"] == "error"]
    return {"ok": not errors, "error_count": len(errors), "issues": issues}


async def _request_credential_handler(args: dict, context) -> dict:
    """Ask the UI to open a credential card. The key is entered there and saved
    directly to the DB — it never returns through this tool or the chat prompt.
    The frontend reads this tool_result, renders the card, saves the key, then
    sends the created id back as a follow-up message."""
    cred_kind = args.get("kind") or "llm"  # llm | gdrive | onedrive | api
    purpose = args.get("purpose") or ""
    node_ref = args.get("node_ref")
    # Non-secret field spec the card should collect (labels only, no values).
    field_spec = {
        "llm": ["display_name", "api_url", "api_key", "model"],
        "gdrive": ["name", "client_email", "private_key", "token_uri"],
        "onedrive": ["name", "tenant_id", "client_id", "client_secret", "drive_id"],
        "api": ["name", "endpoint", "authHeader"],
    }.get(cred_kind, ["name", "api_key"])
    pending = crud_pending.create(
        context.db,
        conversation_id=context.conversation_id,
        user_id=context.user_id,
        tool_name="request_credential",
        tool_arguments={"kind": cred_kind, "purpose": purpose, "node_ref": node_ref},
        description=f"ขอ credential ({cred_kind}) สำหรับ: {purpose}",
        kind="credential_request",
        expires_minutes=30,
    )
    return {
        "status": "awaiting_credential",
        "pending_action_id": str(pending.id),
        "credential_kind": cred_kind,
        "fields": field_spec,
        "purpose": purpose,
        "node_ref": node_ref,
        "message": (
            "ระบบได้แสดง card ให้ผู้ใช้กรอกคีย์แล้ว — โปรดหยุดรอ ผู้ใช้จะกรอกคีย์ "
            "และระบบจะส่ง integration_id/ai_provider_id กลับมาให้ในข้อความถัดไป "
            "อย่าถามคีย์ผ่านแชท"
        ),
    }


def _latest_proposed_definition(context) -> Optional[dict]:
    # Scan conversation messages for the most recent propose_workflow tool result.
    from app.models.agent_message import AgentMessage
    rows = (
        context.db.query(AgentMessage)
        .filter(AgentMessage.conversation_id == context.conversation_id, AgentMessage.role == "tool")
        .order_by(AgentMessage.created_at.desc())
        .limit(40)
        .all()
    )
    for r in rows:
        if r.tool_name == "propose_workflow" and isinstance(r.tool_result, dict):
            definition = r.tool_result.get("definition")
            if definition:
                return {
                    "name": r.tool_result.get("name"),
                    "description": r.tool_result.get("description"),
                    "definition": definition,
                }
    return None


async def _save_workflow_handler(args: dict, context) -> dict:
    db = context.db
    owner = _owner(context)
    if not owner:
        return {"ok": False, "error": "ไม่พบผู้ใช้"}

    definition = args.get("definition")
    name = args.get("name")
    description = args.get("description")
    if not definition:
        proposed = _latest_proposed_definition(context)
        if proposed:
            definition = proposed["definition"]
            name = name or proposed.get("name")
            description = description or proposed.get("description")
    if not definition:
        return {"ok": False, "error": "ยังไม่มี definition ให้บันทึก — เรียก propose_workflow ก่อน"}
    if not name:
        return {"ok": False, "error": "ต้องระบุชื่อ workflow"}

    issues = validate_workflow_definition(db, definition, owner)
    errors = [i for i in issues if i["level"] == "error"]
    if errors:
        return {"ok": False, "error": "validation ไม่ผ่าน — แก้ไขก่อนบันทึก", "issues": issues}

    schedule_cron = args.get("schedule_cron")
    schedule_enabled = bool(args.get("schedule_enabled"))
    wf = Workflow(
        name=name,
        description=description,
        definition=definition,
        schedule_cron=schedule_cron,
        schedule_enabled=schedule_enabled,
        is_active=True,
        user_id=owner.id,
    )
    if schedule_enabled and schedule_cron:
        from datetime import datetime, timezone
        from app.tasks.workflow_tasks import compute_next_run
        try:
            wf.next_run_at = compute_next_run(schedule_cron, datetime.now(timezone.utc))
        except Exception:
            return {"ok": False, "error": f"cron ไม่ถูกต้อง: {schedule_cron}"}
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return {"ok": True, "workflow_id": str(wf.id), "name": wf.name,
            "warnings": [i for i in issues if i["level"] == "warning"]}


_JSON_OBJ = {"type": "object", "properties": {}, "required": []}


def _register():
    reg = lambda **k: tool_registry.register(ToolDef(category="workflow", requires_job_context=False, **k))  # noqa: E731
    reg(name="list_jobs", description="แสดง Jobs ที่ผู้ใช้เข้าถึงได้ (id, ชื่อ, สถานะ, จำนวนเอกสาร) เพื่อใช้กับโหนด job_source/document_source/import",
        parameters_schema=_JSON_OBJ, handler=_list_jobs_handler)
    reg(name="list_document_schemas", description="แสดง Document Schemas ทั้งหมด (id, ชื่อ, ชนิด, ชื่อฟิลด์)",
        parameters_schema=_JSON_OBJ, handler=_list_document_schemas_handler)
    reg(name="list_node_types", description="แสดง catalog ของชนิดโหนด workflow ทั้งหมดพร้อม config fields ที่จำเป็น",
        parameters_schema=_JSON_OBJ, handler=_list_node_types_handler)
    reg(name="list_integrations", description="แสดง integration ของผู้ใช้ (llm/gdrive/onedrive/api) โดยไม่มีความลับ",
        parameters_schema={"type": "object", "properties": {"type_filter": {"type": "string", "enum": ["api", "workflow", "llm", "gdrive", "onedrive"]}}, "required": []},
        handler=_list_integrations_handler)
    reg(name="list_ai_providers", description="แสดง AI provider (Setting AI) ที่ใช้กับโหนด llm ได้",
        parameters_schema=_JSON_OBJ, handler=_list_ai_providers_handler)
    reg(name="inspect_job_data", description="ดูฟิลด์จริงและตัวอย่างข้อมูลของ Job เพื่อวางเทมเพลต {{...}} ให้ถูกต้อง",
        parameters_schema={"type": "object", "properties": {"job_id": {"type": "string"}, "data_source": {"type": "string", "enum": ["reviewed", "extracted", "ocr_text"]}}, "required": ["job_id"]},
        handler=_inspect_job_data_handler)
    reg(name="propose_workflow", description="เสนอ draft workflow เพื่อแสดงในพรีวิว (ยังไม่บันทึก) — ส่ง {name, description, definition:{nodes,edges}}",
        parameters_schema={"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "definition": {"type": "object"}}, "required": ["name", "definition"]},
        handler=_propose_workflow_handler)
    reg(name="validate_workflow", description="ตรวจ static ว่าทุกโหนดรันได้ (โครงสร้าง/config/สิทธิ์ job & credential/เทมเพลต) คืน issues",
        parameters_schema={"type": "object", "properties": {"definition": {"type": "object"}}, "required": ["definition"]},
        handler=_validate_workflow_handler)
    reg(name="request_credential", description="ขอให้ผู้ใช้กรอก API key/token ผ่าน card (คีย์ไม่ผ่านแชท) — ใช้เมื่อโหนดต้องใช้ credential ที่ยังไม่มี",
        parameters_schema={"type": "object", "properties": {"kind": {"type": "string", "enum": ["llm", "gdrive", "onedrive", "api"]}, "purpose": {"type": "string"}, "node_ref": {"type": "string"}}, "required": ["kind", "purpose"]},
        handler=_request_credential_handler)
    reg(name="save_workflow", description="ตรวจ validation แล้วบันทึก workflow — สำเร็จเฉพาะเมื่อไม่มี error; คืน workflow_id",
        parameters_schema={"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "definition": {"type": "object"}, "schedule_cron": {"type": "string"}, "schedule_enabled": {"type": "boolean"}}, "required": []},
        handler=_save_workflow_handler)


_register()
