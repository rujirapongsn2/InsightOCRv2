import json
import httpx
from app.agent.tools.registry import ToolDef, tool_registry
from app.crud.crud_integration import integration as crud_integration


async def _list_integrations_handler(args: dict, context) -> dict:
    integrations = crud_integration.get_all_active(context.db)
    result = [
        {"id": str(i.id), "name": i.name, "type": i.type.value if hasattr(i.type, "value") else str(i.type), "description": i.description}
        for i in integrations
        if (i.type.value if hasattr(i.type, "value") else str(i.type)) in ("api", "workflow")
    ]
    return {"count": len(result), "integrations": result}


async def _call_api_integration_handler(args: dict, context) -> dict:
    db = context.db
    integration_id = args.get("integration_id")
    integration_name = args.get("integration_name")
    method = args.get("method", "GET").upper()
    path = args.get("path", "")
    query_params = args.get("query_params") or {}
    body = args.get("body")

    integration = None
    if integration_id:
        integration = crud_integration.get(db, integration_id=integration_id)
    elif integration_name:
        for i in crud_integration.get_all_active(db):
            if i.name and i.name.strip().lower() == integration_name.strip().lower():
                integration = i
                break

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

    integration = None
    for i in crud_integration.get_all_active(db):
        itype = i.type.value if hasattr(i.type, "value") else str(i.type)
        if itype == "workflow" and i.name and i.name.strip().lower() == (integration_name or "").strip().lower():
            integration = i
            break

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
    name="list_integrations", category="integration",
    description="List active API and Workflow integrations available. Use before calling call_api_integration.",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    handler=_list_integrations_handler,
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
