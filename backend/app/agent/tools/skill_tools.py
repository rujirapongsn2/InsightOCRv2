"""
Agent skills tools — agentskills.io compliant.

7 tools:
  create_skill    — save a reusable procedure from conversation
  import_skill    — import a SKILL.md file from the filesystem
  export_skill    — export a skill as SKILL.md or ZIP bundle
  list_skills     — list available skills (user + system)
  execute_skill   — run a skill with progressive disclosure
  delete_skill    — remove a skill (requires confirmation)
  discover_skills — scan filesystem for SKILL.md files
"""
import logging
from pathlib import Path
import re

from app.agent.context import FOCUSED_LEGAL_QA_TOOLS, is_focused_legal_qa
from app.agent.tools.registry import ToolDef, tool_registry
from app.crud.crud_agent_skill import agent_skill as crud_skill
from app.services.skill_discovery import (
    discover_skills,
    export_skill_to_md,
    parse_skill_md,
    validate_skill,
)

logger = logging.getLogger(__name__)

ALLOWED_SCOPES = {"user"}
ALLOWED_CREATED_BY = {"user", "agent", "imported"}
MAX_NAME_LENGTH = 64
MAX_DESC_LENGTH = 1024
MAX_PROCEDURE_LENGTH = 50000


def _normalize_allowed_tools(value) -> tuple[list[str], str | None]:
    """Normalize a UI or model supplied tool list to registered tool names."""
    if value is None:
        return [], None
    if isinstance(value, str):
        raw_names = re.split(r"[\s,]+", value.strip()) if value.strip() else []
    elif isinstance(value, list):
        raw_names = [str(name).strip() for name in value if str(name).strip()]
    else:
        raise ValueError("allowed_tools must be a string or list of tool names")

    names = list(dict.fromkeys(raw_names))
    unknown = [name for name in names if not tool_registry.has_tools([name])]
    if unknown:
        raise ValueError(f"Unknown platform tool(s): {', '.join(unknown)}")
    return names, " ".join(names) if names else ""


def _strict_skill_metadata(metadata) -> dict:
    value = dict(metadata) if isinstance(metadata, dict) else {}
    value["tool_policy"] = "strict"
    return value


# ── create_skill ──────────────────────────────────────────────────────────────

async def _create_skill_handler(args: dict, context) -> dict:
    name = args["name"].strip().lower()
    if not name:
        return {"error": "name must not be empty"}
    if len(name) > MAX_NAME_LENGTH:
        return {"error": f"name must be <= {MAX_NAME_LENGTH} chars"}
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return {"error": "name must be lowercase letters, numbers, and single hyphens only"}

    description = args["description"].strip()
    if not description:
        return {"error": "description must not be empty"}
    if len(description) > MAX_DESC_LENGTH:
        return {"error": f"description must be <= {MAX_DESC_LENGTH} chars"}

    procedure = args["procedure"].strip()
    if not procedure:
        return {"error": "procedure must not be empty"}
    if len(procedure) > MAX_PROCEDURE_LENGTH:
        return {"error": f"procedure must be <= {MAX_PROCEDURE_LENGTH} chars"}

    if args.get("scope") not in (None, "user"):
        return {"error": "Skills created through Agent DOC are always personal skills"}
    scope = "user"

    try:
        tool_names, allowed_tools = _normalize_allowed_tools(args.get("allowed_tools"))
    except ValueError as exc:
        return {"error": str(exc)}

    # Check for duplicate
    user_id = context.user_id if scope == "user" else None
    existing = crud_skill.get_by_name(context.db, user_id=user_id, name=name, scope=scope)
    if existing:
        return {"error": f"Skill '{name}' already exists in {scope} scope. Use a different name or delete the existing skill."}

    try:
        skill = crud_skill.create(
            context.db,
            user_id=user_id,
            scope=scope,
            name=name,
            description=description,
            procedure=procedure,
            trigger_hint=args.get("trigger_hint"),
            tools_used=tool_names,
            allowed_tools=allowed_tools,
            license_=args.get("license"),
            compatibility=args.get("compatibility"),
            metadata_=_strict_skill_metadata(args.get("metadata")),
            created_by="agent",
            source="db",
        )
    except Exception as e:
        logger.error(f"Failed to create skill: {e}")
        return {"error": f"Failed to create skill: {str(e)}"}

    return {
        "ok": True,
        "id": str(skill.id),
        "name": skill.name,
        "scope": skill.scope,
        "description": skill.description,
        "created_by": skill.created_by,
    }


# ── import_skill ──────────────────────────────────────────────────────────────

def _job_scoped_path(context, path: str) -> tuple[str | None, str | None]:
    """(storage key, error): skill files are read and written only inside the job's own files.

    Arbitrary server paths let the agent read any file on the host and fail on
    read-only containers.
    """
    from app.agent.tools.filesystem_tools import _normalize_job_path, _resolve_path

    if not getattr(context, "job_id", None):
        return None, "Skill files can only be imported or exported inside a Job's files"
    try:
        return _resolve_path(str(context.job_id), _normalize_job_path(str(context.job_id), path)), None
    except ValueError as exc:
        return None, str(exc)


async def _import_skill_handler(args: dict, context) -> dict:
    import tempfile
    from app.services.storage import get_storage_service

    file_path = args["file_path"].strip()
    if not file_path:
        return {"error": "file_path is required"}
    if not file_path.lower().endswith(".md"):
        return {"error": "file_path must be a SKILL.md (markdown) file in the Job's files"}
    key, error = _job_scoped_path(context, file_path)
    if error:
        return {"error": error}
    storage = get_storage_service()
    if not storage.exists(key):
        return {"error": f"File not found: {file_path}"}

    try:
        with storage.get_local_path(key) as local_path, tempfile.TemporaryDirectory() as workdir:
            skill_file = Path(workdir) / "SKILL.md"
            skill_file.write_bytes(Path(local_path).read_bytes())
            skill_data = parse_skill_md(str(skill_file))
    except Exception as e:
        return {"error": f"Failed to parse SKILL.md: {str(e)}"}

    if not skill_data.get("name"):
        return {"error": "SKILL.md is missing required 'name' field"}

    errors = validate_skill(skill_data)
    if errors:
        return {"error": "Validation failed", "validation_errors": errors}

    if args.get("scope") not in (None, "user"):
        return {"error": "Imported skills through Agent DOC are always personal skills"}
    scope = "user"
    user_id = context.user_id

    try:
        tool_names, allowed_tools = _normalize_allowed_tools(skill_data.get("allowed_tools"))
    except ValueError as exc:
        return {"error": str(exc)}

    # Check for duplicate
    existing = crud_skill.get_by_name(context.db, user_id=user_id, name=skill_data["name"], scope=scope)
    if existing:
        overwrite = args.get("overwrite", False)
        if not overwrite:
            return {
                "error": f"Skill '{skill_data['name']}' already exists. Set overwrite=true to replace.",
                "existing_id": str(existing.id),
            }

    fields = dict(
        description=skill_data["description"],
        procedure=skill_data["body"],
        trigger_hint=args.get("trigger_hint"),
        tools_used=tool_names,
        allowed_tools=allowed_tools,
        license_=skill_data.get("license"),
        compatibility=skill_data.get("compatibility"),
        metadata_=_strict_skill_metadata(skill_data.get("metadata_")),
        source="imported",
        file_path=file_path,
    )
    if existing:
        # Replace in place: deleting first lost the user's skill whenever creating the new one failed.
        try:
            for attribute, value in fields.items():
                # crud_skill.create maps license_ to the "license" column; do the same here.
                setattr(existing, "license" if attribute == "license_" else attribute, value)
            context.db.commit()
            context.db.refresh(existing)
        except Exception as e:
            context.db.rollback()
            return {"error": f"Failed to import skill: {str(e)}"}
        skill = existing
        return {"ok": True, "id": str(skill.id), "name": skill.name, "scope": skill.scope,
                "description": skill.description, "created_by": skill.created_by, "replaced": True}

    try:
        skill = crud_skill.create(
            context.db,
            user_id=user_id,
            scope=scope,
            name=skill_data["name"],
            description=skill_data["description"],
            procedure=skill_data["body"],
            trigger_hint=args.get("trigger_hint"),
            tools_used=tool_names,
            allowed_tools=allowed_tools,
            license_=skill_data.get("license"),
            compatibility=skill_data.get("compatibility"),
            metadata_=_strict_skill_metadata(skill_data.get("metadata_")),
            created_by="imported",
            source="imported",
            file_path=file_path,
        )
    except Exception as e:
        return {"error": f"Failed to import skill: {str(e)}"}

    return {
        "ok": True,
        "id": str(skill.id),
        "name": skill.name,
        "scope": skill.scope,
        "description": skill.description,
        "source": skill.source,
    }


# ── export_skill ──────────────────────────────────────────────────────────────

async def _export_skill_handler(args: dict, context) -> dict:
    name = args["name"].strip().lower()
    if not name:
        return {"error": "name is required"}

    scope = args.get("scope", "user")
    if scope not in ("user", "system"):
        return {"error": "scope must be 'user' or 'system'"}
    user_id = context.user_id if scope == "user" else None

    skill = crud_skill.get_by_name(context.db, user_id=user_id, name=name, scope=scope)
    if not skill:
        return {"error": f"Skill '{name}' not found in {scope} scope"}

    include_bundle = args.get("bundle", False)
    output_dir = args.get("output_dir", "").strip()

    try:
        if include_bundle:
            zip_bytes = export_skill_to_md(skill, include_bundle=True)
            if output_dir:
                return _write_job_file(context, f"{output_dir.rstrip('/')}/{skill.name}.zip", zip_bytes, "application/zip")
            # Return as base64 if no output dir
            import base64
            return {"ok": True, "format": "zip", "base64": base64.b64encode(zip_bytes).decode(), "size": len(zip_bytes)}
        else:
            md_content = export_skill_to_md(skill, include_bundle=False)
            if output_dir:
                return _write_job_file(context, f"{output_dir.rstrip('/')}/SKILL.md", md_content.encode("utf-8"),
                                       "text/markdown; charset=utf-8")
            return {"ok": True, "format": "markdown", "content": md_content}
    except Exception as e:
        return {"error": f"Export failed: {str(e)}"}


def _write_job_file(context, path: str, data: bytes, content_type: str) -> dict:
    import io
    from app.services.storage import get_storage_service

    key, error = _job_scoped_path(context, path)
    if error:
        return {"error": error}
    get_storage_service().upload_file(io.BytesIO(data), key, content_type=content_type)
    return {"ok": True, "file": path, "size": len(data)}


# ── list_skills ───────────────────────────────────────────────────────────────

async def _list_skills_handler(args: dict, context) -> dict:
    scope_filter = args.get("scope")  # None = all scopes for this user
    include_system = args.get("include_system", True)

    if scope_filter == "system":
        skills = crud_skill.list_by_scope(context.db, scope="system")
    elif scope_filter == "user":
        skills = crud_skill.list_by_user(context.db, user_id=context.user_id, include_system=False)
    else:
        skills = crud_skill.list_by_user(context.db, user_id=context.user_id, include_system=include_system)

    result = [
        {
            "id": str(s.id),
            "name": s.name,
            "scope": s.scope,
            "description": s.description,
            "trigger_hint": s.trigger_hint,
            "success_count": s.success_count,
            "created_by": s.created_by,
            "source": s.source,
            "version": s.version,
        }
        for s in skills
    ]
    return {"count": len(result), "skills": result}


# ── execute_skill (progressive disclosure) ────────────────────────────────────

async def _execute_skill_handler(args: dict, context) -> dict:
    """Execute a saved skill using progressive disclosure.

    Stage 1: Match skill by name → load name + description
    Stage 2: Load the full procedure (SKILL.md body)
    Stage 3: Agent follows procedure, loading referenced files as needed
    """
    name = args["name"].strip().lower()
    if not name:
        return {"error": "skill name is required"}

    skill_args = args.get("arguments", {})

    # Stage 1: Discovery — find by name in user + system scope
    skill = crud_skill.get_by_name(context.db, user_id=context.user_id, name=name, scope="user")
    if not skill:
        skill = crud_skill.get_by_name(context.db, user_id=None, name=name, scope="system")

    if not skill:
        return {"error": f"Skill '{name}' not found. Use list_skills to see available skills."}

    # Stage 2: Activation — load full procedure
    procedure = skill.procedure or ""

    # Inject arguments into procedure template ({{key}} substitution)
    if skill_args:
        for k, v in skill_args.items():
            procedure = procedure.replace(f"{{{{{k}}}}}", str(v))

    # Stage 3: Execution instructions
    instruction = (
        f"You are now executing the skill: **{skill.name}**\n\n"
        f"**Description**: {skill.description}\n\n"
    )

    if getattr(skill, "compatibility", None):
        instruction += f"**Requirements**: {skill.compatibility}\n\n"

    if getattr(skill, "allowed_tools", None) and not is_focused_legal_qa(getattr(context, "current_request", "")):
        instruction += f"**Pre-approved tools**: {skill.allowed_tools}\n\n"

    # Tool results are cut at TOOL_RESULT_MAX_CHARS, so a long procedure is served in
    # parts; otherwise the agent would silently follow only its first steps.
    parts = [procedure[start:start + SKILL_PROCEDURE_PART_CHARS]
             for start in range(0, len(procedure), SKILL_PROCEDURE_PART_CHARS)] or [""]
    try:
        part = min(max(int(args.get("part") or 1), 1), len(parts))
    except (TypeError, ValueError):
        part = 1
    more = (f"\n\n**This is part {part} of {len(parts)} of the procedure.** Before acting on later steps, "
            f"call execute_skill again with name=\"{skill.name}\" and part={part + 1}.") if part < len(parts) else ""
    instruction += (
        f"**Procedure**{f' (part {part} of {len(parts)})' if len(parts) > 1 else ''}:\n\n{parts[part - 1]}{more}\n\n"
        "Follow the procedure above step by step. "
        "Use the available tools to accomplish each step. "
        "If a step references a script or file, check the skill's directory first. "
        "Report progress as you complete each step."
    )

    # Track usage once per activation, not once per part.
    if part == 1:
        crud_skill.increment_usage(context.db, skill.id)

    try:
        allowed_tool_names, _ = _normalize_allowed_tools(getattr(skill, "allowed_tools", None))
    except ValueError:
        return {"error": f"Skill '{skill.name}' contains unknown platform tools and cannot run"}

    # Older database skills may contain broad artifact/code tools. A legal
    # question is read-only by default, so narrow the active policy at runtime
    # without mutating the saved skill or changing its contract-analysis use.
    if is_focused_legal_qa(getattr(context, "current_request", "")):
        allowed_tool_names = sorted(FOCUSED_LEGAL_QA_TOOLS - {"execute_skill"})
        instruction += (
            "\n\n**Focused legal Q&A policy:** Answer the current legal question from the Job's documents. "
            "Use one focused search per concept, load the relevant document detail, and stop when the "
            "evidence is sufficient. Do not create files, run Python, search the web, compare documents, "
            "or perform write/integration actions for this question."
        )
    metadata = getattr(skill, "metadata_", None)
    enforce_tools = bool(
        (isinstance(metadata, dict) and metadata.get("tool_policy") == "strict")
        or (getattr(skill, "source", None) == "file" and getattr(skill, "allowed_tools", None))
    )
    enforce_tools = enforce_tools or is_focused_legal_qa(getattr(context, "current_request", ""))

    return {
        "ok": True,
        "skill_name": skill.name,
        "scope": skill.scope,
        "description": skill.description,
        # The procedure is inside ``instruction`` (once, possibly in parts); repeating it
        # here doubled the result and pushed later steps past the size limit.
        "procedure_part": part,
        "procedure_parts": len(parts),
        "instruction": instruction,
        "arguments": skill_args,
        "has_file_backing": bool(skill.file_path),
        "file_path": skill.file_path,
        "allowed_tool_names": allowed_tool_names,
        "enforce_tools": enforce_tools,
    }


SKILL_PROCEDURE_PART_CHARS = 8000


# ── delete_skill ──────────────────────────────────────────────────────────────

async def _delete_skill_handler(args: dict, context) -> dict:
    name = args["name"].strip().lower()
    if not name:
        return {"error": "name must not be empty"}

    if args.get("scope") not in (None, "user"):
        return {"error": "Only personal skills can be deleted through Agent DOC"}
    scope = "user"
    user_id = context.user_id
    deleted = crud_skill.delete(context.db, user_id=user_id, name=name, scope=scope)
    if not deleted:
        return {"ok": False, "error": f"Skill '{name}' not found in {scope} scope"}
    return {"ok": True, "name": name, "scope": scope}


# ── discover_skills ───────────────────────────────────────────────────────────

async def _discover_skills_handler(args: dict, context) -> dict:
    """Scan filesystem directories for SKILL.md files and register them."""
    search_paths = args.get("search_paths")
    auto_register = args.get("auto_register", True)
    scope = args.get("scope", "user")
    if scope != "user":
        return {"error": "Discovered skills can only be registered as personal skills through Agent DOC"}

    if search_paths and isinstance(search_paths, list):
        discovered = discover_skills(search_paths)
    else:
        discovered = discover_skills()

    if not discovered:
        return {"ok": True, "count": 0, "skills": [], "message": "No SKILL.md files found in default directories."}

    registered = []
    for skill_data in discovered:
        if auto_register:
            try:
                crud_skill.upsert_file_skill(
                    context.db,
                    user_id=context.user_id,
                    scope=scope,
                    name=skill_data["name"],
                    description=skill_data["description"],
                    procedure=skill_data["body"],
                    file_path=skill_data["file_path"],
                    license_=skill_data.get("license"),
                    compatibility=skill_data.get("compatibility"),
                    metadata_=skill_data.get("metadata_"),
                    allowed_tools=skill_data.get("allowed_tools"),
                )
                registered.append({"name": skill_data["name"], "status": "registered"})
            except Exception as e:
                registered.append({"name": skill_data["name"], "status": f"error: {e}"})
        else:
            registered.append({"name": skill_data["name"], "status": "found"})

    return {
        "ok": True,
        "count": len(discovered),
        "skills": registered,
    }


# ── Tool Registrations ────────────────────────────────────────────────────────

tool_registry.register(ToolDef(
    name="create_skill",
    category="skill",
    description=(
        "Save a reusable personal skill after the user has reviewed its draft. "
        "The skill name must be lowercase letters, numbers, and hyphens only (agentskills.io format). "
        "The user must confirm before this tool can save the skill."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": MAX_NAME_LENGTH, "description": "Skill name (lowercase, hyphens). Must match agentskills.io naming."},
            "description": {"type": "string", "maxLength": MAX_DESC_LENGTH, "description": "What the skill does and when to use it."},
            "procedure": {"type": "string", "description": "Step-by-step procedure in markdown. Can include {{variable}} templates."},
            "trigger_hint": {"type": "string", "description": "When to suggest this skill (e.g. 'when user wants to bulk approve invoices')"},
            "allowed_tools": {"type": "array", "items": {"type": "string"}, "description": "Only registered InsightDOC tool names needed by this skill. An empty list means no tools."},
            "license": {"type": "string", "description": "License name (agentskills.io format)"},
            "compatibility": {"type": "string", "maxLength": 500, "description": "Environment requirements"},
            "metadata": {"type": "object", "description": "Additional key-value metadata"},
        },
        "required": ["name", "description", "procedure"],
    },
    handler=_create_skill_handler,
    requires_confirmation=True,
))

tool_registry.register(ToolDef(
    name="import_skill",
    category="skill",
    description="Import a SKILL.md file from the filesystem into the skill registry.",
    parameters_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path of a SKILL.md in the Job's files, e.g. 'outputs/SKILL.md'"},
            "overwrite": {"type": "boolean", "default": False, "description": "Overwrite if skill already exists"},
        },
        "required": ["file_path"],
    },
    handler=_import_skill_handler,
))

tool_registry.register(ToolDef(
    name="export_skill",
    category="skill",
    description="Export a skill to SKILL.md format (markdown or ZIP bundle).",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name to export"},
            "bundle": {"type": "boolean", "default": False, "description": "Export as ZIP bundle instead of markdown"},
            "output_dir": {"type": "string", "description": "Folder in the Job's files to write to, e.g. 'outputs' (optional; otherwise the content is returned)"},
        },
        "required": ["name"],
    },
    handler=_export_skill_handler,
))

tool_registry.register(ToolDef(
    name="list_skills",
    category="skill",
    description="List available skills — user-scoped and optionally system-scoped.",
    parameters_schema={
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["user", "system"]},
            "include_system": {"type": "boolean", "default": True},
        },
    },
    handler=_list_skills_handler,
))

tool_registry.register(ToolDef(
    name="execute_skill",
    category="skill",
    description=(
        "Execute a saved skill. The skill's procedure is injected as instructions. "
        "Uses progressive disclosure: first loads metadata, then full procedure, then referenced files as needed. "
        "Supports {{variable}} template substitution in procedures."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the skill to execute"},
            "arguments": {"type": "object", "description": "Variable values for template substitution (e.g. {'customer_name': 'ACME'})"},
            "part": {"type": "integer", "minimum": 1, "description": "Part of a long procedure to load (the result says when there are more parts)"},
        },
        "required": ["name"],
    },
    handler=_execute_skill_handler,
))

tool_registry.register(ToolDef(
    name="delete_skill",
    category="skill",
    description="Delete one of the current user's saved personal skills. Requires confirmation.",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name to delete"},
        },
        "required": ["name"],
    },
    handler=_delete_skill_handler,
    requires_confirmation=True,
))

tool_registry.register(ToolDef(
    name="discover_skills",
    category="skill",
    description="Scan filesystem directories for SKILL.md files and register them as personal skills.",
    parameters_schema={
        "type": "object",
        "properties": {
            "search_paths": {"type": "array", "items": {"type": "string"}, "description": "Directories to search (default: standard locations)"},
            "auto_register": {"type": "boolean", "default": True, "description": "Auto-register discovered skills in DB"},
        },
    },
    handler=_discover_skills_handler,
))
