import json
import httpx
from app.agent.tools.registry import ToolDef, tool_registry
from app.crud.crud_integration import integration as crud_integration


def _value(field) -> str:
    return field.value if hasattr(field, "value") else str(field)


def _visible_to(integration, user_id) -> bool:
    """The user's own integrations and shared ones (no owner); never another user's.

    Same rule the workflow validator applies to integration references.
    """
    owner = getattr(integration, "user_id", None)
    return owner is None or str(owner) == str(user_id)


def _accessible_integrations(db, user_id, *, active_only: bool = True) -> list:
    from app.models.integration import Integration

    query = db.query(Integration)
    if active_only:
        query = query.filter(Integration.status == "active")
    return [integration for integration in query.all() if _visible_to(integration, user_id)]


def _find_integration(db, user_id, *, integration_id=None, integration_name=None, itype=None):
    """Resolve by id or name among the integrations this user may use."""
    if integration_id:
        integration = crud_integration.get(db, integration_id=integration_id)
        return integration if integration is not None and _visible_to(integration, user_id) else None
    name = (integration_name or "").strip().lower()
    matches = [integration for integration in _accessible_integrations(db, user_id)
               if integration.name and integration.name.strip().lower() == name
               and (itype is None or _value(integration.type) == itype)]
    # Prefer the user's own over a shared integration with the same name.
    matches.sort(key=lambda integration: getattr(integration, "user_id", None) is None)
    return matches[0] if matches else None


async def _list_integrations_handler(args: dict, context) -> dict:
    type_filter = args.get("type_filter")
    out = []
    for integration in _accessible_integrations(context.db, context.user_id, active_only=False):
        itype = _value(integration.type)
        if type_filter and itype != type_filter:
            continue
        # No secrets: id/name/type/status/description only.
        out.append({"id": str(integration.id), "name": integration.name, "type": itype,
                    "status": _value(integration.status), "description": getattr(integration, "description", None)})
    return {"count": len(out), "integrations": out}


async def _call_api_integration_handler(args: dict, context) -> dict:
    db = context.db
    integration_id = args.get("integration_id")
    integration_name = args.get("integration_name")
    method = args.get("method", "GET").upper()
    path = args.get("path", "")
    query_params = args.get("query_params") or {}
    body = args.get("body")

    integration = _find_integration(db, context.user_id, integration_id=integration_id,
                                    integration_name=integration_name)

    if not integration:
        return {"error": f"Integration not found: {integration_id or integration_name}"}
    itype = integration.type.value if hasattr(integration.type, "value") else str(integration.type)
    if itype != "api":
        return {"error": f"Integration type must be 'api', got '{itype}'"}
    istatus = integration.status.value if hasattr(integration.status, "value") else str(integration.status)
    if istatus != "active":
        return {"error": f"Integration is not active (status: {istatus})"}

    base = (integration.config.get("baseUrl") or integration.config.get("endpoint", "")).rstrip("/")
    if not base:
        return {"error": "Integration has no baseUrl/endpoint configured"}
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"

    headers = {"Content-Type": "application/json"}
    auth_header = integration.config.get("authHeader")
    if auth_header:
        for line in auth_header.split("\n"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                headers[parts[0].strip()] = parts[1].strip()
    headers_json = integration.config.get("headersJson")
    if headers_json:
        try:
            headers.update(json.loads(headers_json))
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.request(
                method=method, url=url,
                params=query_params if query_params else None,
                json=body if body and method in ("POST", "PUT", "PATCH") else None,
                headers=headers,
            )
        content_type = res.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = res.json()
            except Exception:
                data = res.text
        else:
            data = res.text
        return {"ok": res.status_code < 400, "status_code": res.status_code, "url": url, "method": method, "data": data}
    except httpx.TimeoutException:
        return {"error": "Request timed out", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


async def _send_to_workflow_handler(args: dict, context) -> dict:
    db = context.db
    integration_name = args.get("integration_name")
    payload = args.get("payload", {})

    integration = _find_integration(db, context.user_id, integration_name=integration_name, itype="workflow")

    if not integration:
        return {"error": f"Workflow integration not found: {integration_name}"}

    webhook_url = integration.config.get("webhookUrl")
    if not webhook_url:
        return {"error": "Webhook URL not configured"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(webhook_url, json=payload)
        return {"ok": res.status_code < 400, "status_code": res.status_code, "url": webhook_url}
    except Exception as e:
        return {"error": str(e)}


# ── Tool Registrations ──

tool_registry.register(ToolDef(
    name="list_integrations", category="integration", also_categories=("workflow",),
    description="List the integrations you can use (api, workflow, llm, gdrive, onedrive), without secrets. "
                "Use before call_api_integration or when a workflow node needs an integration.",
    parameters_schema={"type": "object", "properties": {
        "type_filter": {"type": "string", "enum": ["api", "workflow", "llm", "gdrive", "onedrive"]},
    }, "required": []},
    handler=_list_integrations_handler,
    requires_job_context=False,
))

tool_registry.register(ToolDef(
    name="call_api_integration", category="integration",
    description="Call an external API through a configured API Integration (ERP, CRM, etc.). GET is safe; POST/PUT/PATCH/DELETE require confirmation.",
    parameters_schema={"type": "object", "properties": {
        "integration_name": {"type": "string", "description": "Name of the integration (use list_integrations first)"},
        "integration_id": {"type": "string", "description": "UUID of the integration (alternative to name)"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
        "path": {"type": "string", "description": "Path appended to baseUrl e.g. '/api/stock/PRD-001'"},
        "query_params": {"type": "object", "description": "URL query parameters"},
        "body": {"type": "object", "description": "Request body for POST/PUT/PATCH"},
    }, "required": ["path"]},
    handler=_call_api_integration_handler,
    requires_confirmation=False,
))

tool_registry.register(ToolDef(
    name="send_to_workflow", category="integration",
    description="Trigger a webhook/workflow integration with a payload.",
    parameters_schema={"type": "object", "properties": {
        "integration_name": {"type": "string"},
        "payload": {"type": "object"},
    }, "required": ["integration_name"]},
    handler=_send_to_workflow_handler,
    requires_confirmation=True,
))
