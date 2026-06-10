from datetime import datetime, timedelta, timezone

from app.agent.tools.registry import ToolDef, tool_registry
from app.crud.crud_agent_memory import agent_memory as crud_memory

ALLOWED_SCOPES = {"user", "job"}
ALLOWED_TYPES = {"fact", "preference", "observation", "field_mapping", "review_rule", "integration_preference", "general"}
MAX_KEY_LENGTH = 200
MAX_CONTENT_LENGTH = 10000


async def _save_memory_handler(args: dict, context) -> dict:
    scope = args.get("scope", "user")
    if scope not in ALLOWED_SCOPES:
        return {"error": f"Invalid scope '{scope}'. Allowed: {', '.join(sorted(ALLOWED_SCOPES))}"}
    memory_type = args.get("memory_type", "general")
    if memory_type not in ALLOWED_TYPES:
        return {"error": f"Invalid memory_type '{memory_type}'. Allowed: {', '.join(sorted(ALLOWED_TYPES))}"}
    key = args["key"].strip()
    if not key:
        return {"error": "key must not be empty"}
    if len(key) > MAX_KEY_LENGTH:
        return {"error": f"key must be at most {MAX_KEY_LENGTH} characters"}
    content = args["content"].strip()
    if not content:
        return {"error": "content must not be empty"}
    if len(content) > MAX_CONTENT_LENGTH:
        return {"error": f"content must be at most {MAX_CONTENT_LENGTH} characters"}
    importance = max(0.0, min(5.0, float(args.get("importance", 1.0))))

    # Parse optional expiration
    expires_at = None
    ttl_minutes = args.get("ttl_minutes")
    if ttl_minutes is not None:
        ttl_minutes = max(1, min(int(ttl_minutes), 525600))  # 1 min to 1 year
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

    job_id = context.job_id if scope == "job" else None
    mem = crud_memory.upsert(
        context.db,
        user_id=context.user_id,
        job_id=job_id,
        scope=scope,
        memory_type=memory_type,
        key=key,
        content=content,
        importance=importance,
        expires_at=expires_at,
    )
    return {"ok": True, "id": str(mem.id), "key": mem.key, "scope": mem.scope, "memory_type": mem.memory_type}


async def _recall_memory_handler(args: dict, context) -> dict:
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 20)
    scope_filter = args.get("scope")
    memories = crud_memory.search(context.db, user_id=context.user_id, job_id=context.job_id, query=query, limit=limit)
    if scope_filter and scope_filter in ALLOWED_SCOPES:
        memories = [m for m in memories if m.scope == scope_filter]
    result = [
        {"id": str(m.id), "scope": m.scope, "memory_type": m.memory_type,
         "key": m.key, "content": m.content, "importance": m.importance,
         "access_count": m.access_count}
        for m in memories
    ]
    return {"count": len(result), "memories": result}


async def _list_memories_handler(args: dict, context) -> dict:
    scope = args.get("scope", "user")
    if scope not in ALLOWED_SCOPES:
        return {"error": f"Invalid scope '{scope}'. Allowed: {', '.join(sorted(ALLOWED_SCOPES))}"}
    job_id = context.job_id if scope == "job" else None
    memories = crud_memory.list_by_scope(context.db, user_id=context.user_id, scope=scope, job_id=job_id)
    result = [
        {"id": str(m.id), "scope": m.scope, "memory_type": m.memory_type,
         "key": m.key, "content": m.content, "importance": m.importance,
         "access_count": m.access_count, "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in memories
    ]
    return {"count": len(result), "memories": result}


async def _forget_memory_handler(args: dict, context) -> dict:
    scope = args.get("scope", "user")
    if scope not in ALLOWED_SCOPES:
        return {"error": f"Invalid scope '{scope}'. Allowed: {', '.join(sorted(ALLOWED_SCOPES))}"}
    key = args["key"].strip()
    if not key:
        return {"ok": False, "error": "key must not be empty"}
    job_id = context.job_id if scope == "job" else None
    deleted = crud_memory.delete(context.db, user_id=context.user_id, key=key, scope=scope, job_id=job_id)
    if not deleted:
        return {"ok": False, "error": "Memory not found"}
    return {"ok": True, "key": key, "scope": scope}


tool_registry.register(ToolDef(
    name="save_memory",
    category="memory",
    description="Save a user or job scoped preference, field mapping, review rule, or integration preference for future conversations. Optionally set a TTL to auto-expire the memory.",
    parameters_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string", "maxLength": MAX_KEY_LENGTH},
            "content": {"type": "string", "maxLength": MAX_CONTENT_LENGTH},
            "scope": {"type": "string", "enum": ["user", "job"], "default": "user"},
            "memory_type": {"type": "string", "enum": sorted(ALLOWED_TYPES), "default": "general"},
            "importance": {"type": "number", "minimum": 0, "maximum": 5, "default": 1.0},
            "ttl_minutes": {"type": "integer", "minimum": 1, "maximum": 525600, "description": "Auto-expire after N minutes. Omit for permanent storage."},
        },
        "required": ["key", "content"],
    },
    handler=_save_memory_handler,
))

tool_registry.register(ToolDef(
    name="recall_memory",
    category="memory",
    description="Recall relevant user or job scoped memories using a search query.",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "scope": {"type": "string", "enum": ["user", "job"]},
            "limit": {"type": "integer", "default": 10},
        },
    },
    handler=_recall_memory_handler,
))

tool_registry.register(ToolDef(
    name="list_memories",
    category="memory",
    description="List saved memories for the current user or current job scope.",
    parameters_schema={
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["user", "job"], "default": "user"},
        },
    },
    handler=_list_memories_handler,
))

tool_registry.register(ToolDef(
    name="forget_memory",
    category="memory",
    description="Delete a saved user or job scoped memory by key.",
    parameters_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "scope": {"type": "string", "enum": ["user", "job"], "default": "user"},
        },
        "required": ["key"],
    },
    handler=_forget_memory_handler,
))
