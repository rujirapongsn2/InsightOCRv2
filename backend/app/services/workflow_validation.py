"""Static validation of a workflow definition.

Shared by the AI-agent builder tools (validate_workflow / save_workflow), the
import endpoint, and any caller that wants to know — without running anything —
whether every node is structurally runnable and its references resolve for a
given owner. This is what backs the product guarantee "ทุก node รันได้สำเร็จ"
short of an actual (side-effecting) run.

Returns a flat list of Issue dicts: {node_id, level, field, message}.
- level "error"   → the workflow cannot run as-is (blocks save).
- level "warning" → runnable but a reference/config is missing or unresolved
                    (used by import so the user can fill it in manually).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.permissions import can_access_job
from app.models.ai_settings import AISettings
from app.models.agent_skill import AgentSkill
from app.models.integration import Integration
from app.models.job import Job
from app.models.schema import DocumentSchema
from app.models.user import User
from app.services.workflow_engine import (
    EXECUTORS,
    NODE_TYPES,
    TEMPLATE_RE,
    NodeExecutionError,
    _topological_order,
)
from app.services.workflow_agent_contracts import (
    FILE_OUTPUT_FORMATS,
    OUTPUT_FORMAT_REQUIRED_TOOLS,
)
from app.agent.tools.skill_tools import _normalize_allowed_tools

TRIGGER_TYPES = {"trigger_manual", "trigger_schedule", "trigger_webhook"}

# type -> {config field name -> required?} derived from the NODE_TYPES catalog.
_REQUIRED_FIELDS: Dict[str, List[str]] = {
    nt["type"]: [f["name"] for f in nt.get("config_fields", []) if f.get("required")]
    for nt in NODE_TYPES
}
# type -> {integration field: provider} for credentialed nodes.
_INTEGRATION_FIELDS: Dict[str, str] = {
    nt["type"]: next(
        (f["provider"] for f in nt.get("config_fields", [])
         if f.get("type") == "integration_select" and f.get("provider")),
        "",
    )
    for nt in NODE_TYPES
    if any(f.get("type") == "integration_select" for f in nt.get("config_fields", []))
}
_JOB_FIELD_TYPES = {"job_select"}


def _issue(node_id: str, level: str, field: Optional[str], message: str) -> Dict[str, Any]:
    return {"node_id": node_id, "level": level, "field": field, "message": message}


def _skill_fingerprint(skill: AgentSkill) -> str:
    payload = "\0".join(
        str(value or "")
        for value in (skill.name, skill.description, skill.procedure, skill.allowed_tools)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _node_ids_referenced(value: Any) -> List[str]:
    """Top-level node ids referenced by {{node_id.path}} templates in a value."""
    refs: List[str] = []
    if isinstance(value, str):
        for m in TEMPLATE_RE.finditer(value):
            head = m.group(1).split(".")[0]
            if head and head != "trigger":
                refs.append(head)
    elif isinstance(value, dict):
        for v in value.values():
            refs.extend(_node_ids_referenced(v))
    elif isinstance(value, list):
        for v in value:
            refs.extend(_node_ids_referenced(v))
    return refs


def _has_possible_upstream_job_context(node_id: str, nodes: List[dict], edges: List[dict]) -> bool:
    """Return whether an ancestor can provide a Job id at runtime.

    This intentionally permits dynamic job contexts from document/cloud source
    nodes while catching file-producing Agents that are not connected to any
    Job-aware branch at all. Runtime still verifies the actual context.
    """
    node_by_id = {node.get("id"): node for node in nodes}
    parents: Dict[str, List[str]] = {}
    for edge in edges:
        parents.setdefault(edge.get("target"), []).append(edge.get("source"))

    job_context_types = {
        "job_source", "document_source", "gdrive_import", "onedrive_import",
    }
    seen: set[str] = set()
    queue = list(parents.get(node_id) or [])
    while queue:
        source_id = queue.pop()
        if source_id in seen:
            continue
        seen.add(source_id)
        source = node_by_id.get(source_id) or {}
        source_config = (source.get("data") or {}).get("config") or {}
        if source.get("type") in job_context_types or source_config.get("job_id"):
            return True
        queue.extend(parents.get(source_id) or [])
    return False


def validate_workflow_definition(
    db: Session,
    definition: Dict[str, Any],
    owner: User,
    *,
    allow_unresolved_references: bool = True,
    refresh_skill_fingerprints: bool = False,
) -> List[Dict[str, Any]]:
    """Validate a definition for `owner`.

    Imports may retain unresolved references as warnings so they can be mapped
    in a new environment. Saving, activating, or running a workflow uses strict
    validation and blocks those references before any side effect can occur.
    """
    issues: List[Dict[str, Any]] = []
    definition = definition or {}
    nodes: List[dict] = definition.get("nodes") or []
    edges: List[dict] = definition.get("edges") or []

    if not nodes:
        issues.append(_issue("", "error", None, "Workflow ต้องมีอย่างน้อย 1 โหนด"))
        return issues

    node_ids = {n.get("id") for n in nodes}

    # Cycle / DAG check.
    try:
        _topological_order(nodes, edges)
    except NodeExecutionError as exc:
        issues.append(_issue("", "error", None, str(exc)))

    # Inbound-edge map for trigger sanity + orphan check.
    has_inbound = {n.get("id"): False for n in nodes}
    for e in edges:
        if e.get("target") in has_inbound:
            has_inbound[e["target"]] = True

    trigger_count = 0
    for node in nodes:
        nid = node.get("id") or ""
        ntype = node.get("type") or ""
        config = (node.get("data") or {}).get("config") or {}

        if ntype in TRIGGER_TYPES:
            trigger_count += 1

        # Unknown node type — cannot execute.
        if ntype not in EXECUTORS:
            issues.append(_issue(nid, "error", "type", f"ไม่รู้จักชนิดโหนด '{ntype}'"))
            continue

        # Required config keys present & non-empty.
        for field in _REQUIRED_FIELDS.get(ntype, []):
            val = config.get(field)
            if val is None or (isinstance(val, str) and not val.strip()) or (isinstance(val, list) and not val):
                issues.append(_issue(nid, "error", field, f"โหนด '{ntype}' ต้องระบุ '{field}'"))

        # Referenced Job must exist & be accessible by the owner.
        if config.get("job_id"):
            job = db.query(Job).filter(Job.id == config["job_id"]).first()
            if not job:
                issues.append(_issue(nid, "warning", "job_id", "ไม่พบ Job ที่อ้างถึง — โปรดเลือกใหม่"))
            elif not can_access_job(owner, job):
                issues.append(_issue(nid, "error", "job_id", "ไม่มีสิทธิ์เข้าถึง Job ที่อ้างถึง"))

        # An optional schema override on cloud-import nodes. Empty means the
        # destination Job's schema remains authoritative for compatibility.
        if config.get("schema_id"):
            schema = db.query(DocumentSchema).filter(DocumentSchema.id == config["schema_id"]).first()
            if not schema:
                issues.append(_issue(nid, "warning", "schema_id", "ไม่พบ Schema ที่อ้างถึง — โปรดเลือกใหม่"))

        # Referenced Integration must exist, be owned, and match provider type.
        provider = _INTEGRATION_FIELDS.get(ntype)
        if provider and config.get("integration_id"):
            integ = db.query(Integration).filter(Integration.id == config["integration_id"]).first()
            if not integ:
                level = "warning" if allow_unresolved_references else "error"
                issues.append(_issue(nid, level, "integration_id", "ไม่พบ integration ที่อ้างถึง — โปรดเลือก/สร้างใหม่"))
            else:
                if integ.user_id is not None and str(integ.user_id) != str(owner.id):
                    issues.append(_issue(nid, "error", "integration_id", "integration นี้เป็นของผู้ใช้อื่น"))
                itype = integ.type.value if hasattr(integ.type, "value") else str(integ.type)
                if itype != provider:
                    issues.append(_issue(nid, "error", "integration_id", f"integration ต้องเป็นชนิด {provider} (พบ {itype})"))
                status = integ.status.value if hasattr(integ.status, "value") else str(integ.status)
                if status != "active":
                    issues.append(_issue(nid, "error", "integration_id", "integration ที่เลือกถูกพักการใช้งานอยู่"))

        # Referenced AI provider (llm node) must exist & be active.
        if ntype == "llm" and config.get("ai_provider_id"):
            ai = db.query(AISettings).filter(AISettings.id == config["ai_provider_id"]).first()
            if not ai:
                issues.append(_issue(nid, "warning", "ai_provider_id", "ไม่พบ AI provider ที่อ้างถึง"))
            elif not ai.is_active:
                issues.append(_issue(nid, "error", "ai_provider_id", "AI provider ที่เลือกถูกปิดใช้งาน"))

        if ntype == "llm" and (config.get("mode") or "llm") not in {"llm", "agent"}:
            issues.append(_issue(nid, "error", "mode", "โหมด AI ต้องเป็น llm หรือ agent"))

        if ntype == "llm" and (config.get("mode") or "llm") == "agent":
            skill_ids = config.get("skill_ids") or []
            declared_tools: set[str] = set()
            has_declared_policy = False
            if not isinstance(skill_ids, list) or not skill_ids:
                issues.append(_issue(nid, "error", "skill_ids", "Agent mode ต้องเลือกอย่างน้อย 1 Skill"))
            else:
                accessible_skills = {
                    str(row.id): row
                    for row in db.query(AgentSkill).filter(
                        (AgentSkill.user_id == owner.id)
                        | ((AgentSkill.user_id.is_(None)) & (AgentSkill.scope == "system"))
                    ).all()
                }
                missing = [str(item) for item in skill_ids if str(item) not in accessible_skills]
                if missing:
                    issues.append(_issue(
                        nid, "error", "skill_ids",
                        "มี Skill ที่ไม่พบหรือไม่มีสิทธิ์ใช้งาน: " + ", ".join(missing),
                    ))
                selected_skills = [
                    accessible_skills[str(item)]
                    for item in skill_ids
                    if str(item) in accessible_skills
                ]
                for skill in selected_skills:
                    try:
                        _normalize_allowed_tools(skill.allowed_tools)
                    except ValueError as exc:
                        issues.append(_issue(nid, "error", "skill_ids", f"Skill '{skill.name}' ใช้ tool policy ไม่ถูกต้อง: {exc}"))

                for skill in selected_skills:
                    try:
                        names, normalized = _normalize_allowed_tools(skill.allowed_tools)
                    except ValueError:
                        continue
                    if normalized is not None:
                        has_declared_policy = True
                        declared_tools.update(names)

                if selected_skills and not missing:
                    current_fingerprints = {
                        str(skill.id): _skill_fingerprint(skill)
                        for skill in selected_skills
                    }
                    configured_fingerprints = config.get("skill_fingerprints")
                    if refresh_skill_fingerprints:
                        config["skill_fingerprints"] = current_fingerprints
                    elif configured_fingerprints is None:
                        issues.append(_issue(
                            nid, "error", "skill_ids",
                            "Workflow นี้ยังไม่มี snapshot ของ Skill — โปรดบันทึก Workflow ใหม่ก่อนรัน",
                        ))
                    else:
                        if not isinstance(configured_fingerprints, dict):
                            issues.append(_issue(nid, "error", "skill_ids", "skill_fingerprints ต้องเป็น object"))
                        else:
                            changed = [
                                skill.name
                                for skill in selected_skills
                                if configured_fingerprints.get(str(skill.id))
                                != current_fingerprints[str(skill.id)]
                            ]
                            if changed:
                                issues.append(_issue(
                                    nid, "error", "skill_ids",
                                    "มี Skill ถูกแก้ไขหลังบันทึก Workflow: " + ", ".join(changed),
                                ))

            output_format = str(config.get("output_format") or "text").lower()
            if output_format not in {"text", "json", "html", "docx", "pdf", "xlsx"}:
                issues.append(_issue(nid, "error", "output_format", "รูปแบบผลลัพธ์ Agent ไม่ถูกต้อง"))
            else:
                required_tools = OUTPUT_FORMAT_REQUIRED_TOOLS[output_format]
                if has_declared_policy and not required_tools.issubset(declared_tools):
                    missing_tools = ", ".join(sorted(required_tools - declared_tools))
                    issues.append(_issue(
                        nid,
                        "error",
                        "skill_ids",
                        f"Skill ที่เลือกต้องอนุญาต tool สำหรับผลลัพธ์ {output_format.upper()}: {missing_tools}",
                    ))
                if (
                    output_format in FILE_OUTPUT_FORMATS
                    and not config.get("job_id")
                    and not _has_possible_upstream_job_context(nid, nodes, edges)
                ):
                    issues.append(_issue(
                        nid,
                        "error",
                        "job_id",
                        "Agent ที่สร้างไฟล์ต้องเลือก Job context หรือเชื่อมต่อจากโหนดที่ส่ง Job context",
                    ))
            try:
                max_iterations = int(config.get("max_iterations") or 7)
            except (TypeError, ValueError):
                max_iterations = 0
            if not 3 <= max_iterations <= 20:
                issues.append(_issue(nid, "error", "max_iterations", "จำนวนรอบ Agent ต้องอยู่ระหว่าง 3-20"))
            try:
                timeout_seconds = int(config.get("timeout_seconds") or 300)
            except (TypeError, ValueError):
                timeout_seconds = 0
            if not 60 <= timeout_seconds <= 900:
                issues.append(_issue(nid, "error", "timeout_seconds", "Timeout Agent ต้องอยู่ระหว่าง 60-900 วินาที"))

        # Template refs must point at a node present in the graph.
        for ref in set(_node_ids_referenced(config)):
            if ref not in node_ids:
                issues.append(_issue(nid, "error", None, f"อ้างถึงโหนด '{ref}' ที่ไม่มีอยู่ใน workflow"))

    if trigger_count == 0:
        issues.append(_issue("", "error", None, "Workflow ต้องมี trigger อย่างน้อย 1 โหนด"))

    return issues
