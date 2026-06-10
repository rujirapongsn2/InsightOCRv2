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

from app.agent.tools.registry import ToolDef, tool_registry
from app.crud.crud_agent_skill import agent_skill as crud_skill
from app.services.skill_discovery import (
    discover_skills,
    export_skill_to_md,
    parse_skill_md,
    validate_skill,
)

logger = logging.getLogger(__name__)

ALLOWED_SCOPES = {"user", "system"}
ALLOWED_CREATED_BY = {"user", "agent", "imported"}
MAX_NAME_LENGTH = 64
MAX_DESC_LENGTH = 1024
MAX_PROCEDURE_LENGTH = 50000


# ── create_skill ──────────────────────────────────────────────────────────────

async def _create_skill_handler(args: dict, context) -> dict:
    name = args["name"].strip().lower()
    if not name:
        return {"error": "name must not be empty"}
    if len(name) > MAX_NAME_LENGTH:
        return {"error": f"name must be <= {MAX_NAME_LENGTH} chars"}
    if "--" in name or name.startswith("-") or name.endswith("-"):
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

    scope = args.get("scope", "user")
    if scope not in ALLOWED_SCOPES:
        return {"error": f"Invalid scope '{scope}'. Allowed: {', '.join(sorted(ALLOWED_SCOPES))}"}

    created_by = args.get("created_by", "agent")
    if created_by not in ALLOWED_CREATED_BY:
        return {"error": f"Invalid created_by '{created_by}'"}

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
            tools_used=args.get("tools_used"),
            allowed_tools=args.get("allowed_tools"),
            license_=args.get("license"),
            compatibility=args.get("compatibility"),
            metadata_=args.get("metadata"),
            created_by=created_by,
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

async def _import_skill_handler(args: dict, context) -> dict:
    file_path = args["file_path"].strip()
    if not file_path:
        return {"error": "file_path is required"}

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    if path.name != "SKILL.md" and path.suffix == ".md":
        # Allow importing any .md file, treat as SKILL.md
        pass

    try:
        skill_data = parse_skill_md(str(path))
    except Exception as e:
        return {"error": f"Failed to parse SKILL.md: {str(e)}"}

    if not skill_data.get("name"):
        return {"error": "SKILL.md is missing required 'name' field"}

    errors = validate_skill(skill_data)
    if errors:
        return {"error": "Validation failed", "validation_errors": errors}

    scope = args.get("scope", "user")
    if scope not in ALLOWED_SCOPES:
        return {"error": f"Invalid scope '{scope}'"}

    user_id = context.user_id if scope == "user" else None

    # Check for duplicate
    existing = crud_skill.get_by_name(context.db, user_id=user_id, name=skill_data["name"], scope=scope)
    if existing:
        overwrite = args.get("overwrite", False)
        if not overwrite:
            return {
                "error": f"Skill '{skill_data['name']}' already exists. Set overwrite=true to replace.",
                "existing_id": str(existing.id),
            }
        crud_skill.delete_by_id(context.db, existing.id)

    try:
        skill = crud_skill.create(
            context.db,
            user_id=user_id,
            scope=scope,
            name=skill_data["name"],
            description=skill_data["description"],
            procedure=skill_data["body"],
            trigger_hint=args.get("trigger_hint"),
            allowed_tools=skill_data.get("allowed_tools"),
            license_=skill_data.get("license"),
            compatibility=skill_data.get("compatibility"),
            metadata_=skill_data.get("metadata_"),
            created_by="imported",
            source="imported",
            file_path=str(path.resolve()),
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
                out_path = Path(output_dir) / f"{skill.name}.zip"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(zip_bytes)
                return {"ok": True, "file": str(out_path), "size": len(zip_bytes)}
            # Return as base64 if no output dir
            import base64
            return {"ok": True, "format": "zip", "base64": base64.b64encode(zip_bytes).decode(), "size": len(zip_bytes)}
        else:
            md_content = export_skill_to_md(skill, include_bundle=False)
            if output_dir:
                out_path = Path(output_dir) / "SKILL.md"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(md_content, encoding="utf-8")
                return {"ok": True, "file": str(out_path)}
            return {"ok": True, "format": "markdown", "content": md_content}
    except Exception as e:
        return {"error": f"Export failed: {str(e)}"}


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

    if getattr(skill, "allowed_tools", None):
        instruction += f"**Pre-approved tools**: {skill.allowed_tools}\n\n"

    instruction += (
        f"**Procedure**:\n\n{procedure}\n\n"
        "Follow the procedure above step by step. "
        "Use the available tools to accomplish each step. "
        "If a step references a script or file, check the skill's directory first. "
        "Report progress as you complete each step."
    )

    # Track usage
    crud_skill.increment_usage(context.db, skill.id)

    return {
        "ok": True,
        "skill_name": skill.name,
        "scope": skill.scope,
        "description": skill.description,
        "procedure": procedure,
        "instruction": instruction,
        "arguments": skill_args,
        "has_file_backing": bool(skill.file_path),
        "file_path": skill.file_path,
    }


# ── delete_skill ──────────────────────────────────────────────────────────────

async def _delete_skill_handler(args: dict, context) -> dict:
    name = args["name"].strip().lower()
    if not name:
        return {"error": "name must not be empty"}

    scope = args.get("scope", "user")
    if scope not in ALLOWED_SCOPES:
        return {"error": f"Invalid scope '{scope}'"}

    user_id = context.user_id if scope == "user" else None
    deleted = crud_skill.delete(context.db, user_id=user_id, name=name, scope=scope)
    if not deleted:
        return {"ok": False, "error": f"Skill '{name}' not found in {scope} scope"}
    return {"ok": True, "name": name, "scope": scope}


# ── discover_skills ───────────────────────────────────────────────────────────

async def _discover_skills_handler(args: dict, context) -> dict:
    """Scan filesystem directories for SKILL.md files and register them."""
    search_paths = args.get("search_paths")
    auto_register = args.get("auto_register", True)
    scope = args.get("scope", "system")

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
                    user_id=None if scope == "system" else context.user_id,
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
        "Save a reusable procedure as a skill for future use. "
        "The skill name must be lowercase letters, numbers, and hyphens only (agentskills.io format). "
        "Use this after successfully completing a complex multi-step task to capture the workflow."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": MAX_NAME_LENGTH, "description": "Skill name (lowercase, hyphens). Must match agentskills.io naming."},
            "description": {"type": "string", "maxLength": MAX_DESC_LENGTH, "description": "What the skill does and when to use it."},
            "procedure": {"type": "string", "description": "Step-by-step procedure in markdown. Can include {{variable}} templates."},
            "scope": {"type": "string", "enum": sorted(ALLOWED_SCOPES), "default": "user"},
            "trigger_hint": {"type": "string", "description": "When to suggest this skill (e.g. 'when user wants to bulk approve invoices')"},
            "tools_used": {"type": "array", "items": {"type": "string"}, "description": "List of tool names used in this skill"},
            "allowed_tools": {"type": "string", "description": "Space-separated pre-approved tools for this skill (agentskills.io format)"},
            "license": {"type": "string", "description": "License name (agentskills.io format)"},
            "compatibility": {"type": "string", "maxLength": 500, "description": "Environment requirements"},
            "metadata": {"type": "object", "description": "Additional key-value metadata"},
            "created_by": {"type": "string", "enum": sorted(ALLOWED_CREATED_BY), "default": "agent"},
        },
        "required": ["name", "description", "procedure"],
    },
    handler=_create_skill_handler,
))

tool_registry.register(ToolDef(
    name="import_skill",
    category="skill",
    description="Import a SKILL.md file from the filesystem into the skill registry.",
    parameters_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to SKILL.md file"},
            "scope": {"type": "string", "enum": sorted(ALLOWED_SCOPES), "default": "user"},
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
            "scope": {"type": "string", "enum": sorted(ALLOWED_SCOPES), "default": "user"},
            "bundle": {"type": "boolean", "default": False, "description": "Export as ZIP bundle instead of markdown"},
            "output_dir": {"type": "string", "description": "Directory to write exported file (optional)"},
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
        },
        "required": ["name"],
    },
    handler=_execute_skill_handler,
))

tool_registry.register(ToolDef(
    name="delete_skill",
    category="skill",
    description="Delete a saved skill by name and scope. Requires confirmation for user-scoped skills.",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name to delete"},
            "scope": {"type": "string", "enum": sorted(ALLOWED_SCOPES), "default": "user"},
        },
        "required": ["name"],
    },
    handler=_delete_skill_handler,
    requires_confirmation=True,
))

tool_registry.register(ToolDef(
    name="discover_skills",
    category="skill",
    description="Scan filesystem directories (.agents/skills, skills, .claude/skills) for SKILL.md files and register them as system skills.",
    parameters_schema={
        "type": "object",
        "properties": {
            "search_paths": {"type": "array", "items": {"type": "string"}, "description": "Directories to search (default: standard locations)"},
            "auto_register": {"type": "boolean", "default": True, "description": "Auto-register discovered skills in DB"},
            "scope": {"type": "string", "enum": sorted(ALLOWED_SCOPES), "default": "system"},
        },
    },
    handler=_discover_skills_handler,
))
