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

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.permissions import can_access_job
from app.models.ai_settings import AISettings
from app.models.integration import Integration
from app.models.job import Job
from app.models.user import User
from app.services.workflow_engine import (
    EXECUTORS,
    NODE_TYPES,
    TEMPLATE_RE,
    NodeExecutionError,
    _topological_order,
)

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


def validate_workflow_definition(
    db: Session,
    definition: Dict[str, Any],
    owner: User,
) -> List[Dict[str, Any]]:
    """Validate a definition for `owner`. Returns issues (empty = fully valid)."""
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

        # Referenced Integration must exist, be owned, and match provider type.
        provider = _INTEGRATION_FIELDS.get(ntype)
        if provider and config.get("integration_id"):
            integ = db.query(Integration).filter(Integration.id == config["integration_id"]).first()
            if not integ:
                issues.append(_issue(nid, "warning", "integration_id", "ไม่พบ integration ที่อ้างถึง — โปรดเลือก/สร้างใหม่"))
            else:
                if integ.user_id is not None and str(integ.user_id) != str(owner.id):
                    issues.append(_issue(nid, "error", "integration_id", "integration นี้เป็นของผู้ใช้อื่น"))
                itype = integ.type.value if hasattr(integ.type, "value") else str(integ.type)
                if itype != provider:
                    issues.append(_issue(nid, "error", "integration_id", f"integration ต้องเป็นชนิด {provider} (พบ {itype})"))

        # Referenced AI provider (llm node) must exist & be active.
        if ntype == "llm" and config.get("ai_provider_id"):
            ai = db.query(AISettings).filter(AISettings.id == config["ai_provider_id"]).first()
            if not ai:
                issues.append(_issue(nid, "warning", "ai_provider_id", "ไม่พบ AI provider ที่อ้างถึง"))
            elif not ai.is_active:
                issues.append(_issue(nid, "error", "ai_provider_id", "AI provider ที่เลือกถูกปิดใช้งาน"))

        # Template refs must point at a node present in the graph.
        for ref in set(_node_ids_referenced(config)):
            if ref not in node_ids:
                issues.append(_issue(nid, "error", None, f"อ้างถึงโหนด '{ref}' ที่ไม่มีอยู่ใน workflow"))

    if trigger_count == 0:
        issues.append(_issue("", "error", None, "Workflow ต้องมี trigger อย่างน้อย 1 โหนด"))

    return issues
