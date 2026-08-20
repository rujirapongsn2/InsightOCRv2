"""Headless Agent execution for Workflow nodes.

This adapter reuses Agent DOC's planning/tool loop without its interactive
confirmation channel. Workflow runs receive a strict, pre-authorized tool
allowlist and always return a terminal structured result.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.agent.loop import AgentLoop
from app.agent.tools.skill_tools import _normalize_allowed_tools
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_skill import agent_skill as crud_skill
from app.api.permissions import can_access_job
from app.models.job import Job
from app.models.user import User
from app.services.workflow_agent_contracts import (
    FILE_OUTPUT_FORMATS,
    OUTPUT_FORMAT_REQUIRED_TOOLS,
)


SAFE_WORKFLOW_AGENT_TOOLS = frozenset({
    "list_documents",
    "get_document_detail",
    "search_documents",
    "compare_documents",
    "inspect_job_data",
    "list_files",
    "read_file",
    "write_file",
    "execute_python",
    "run_report_code",
    "create_docx",
    "create_pdf",
    "convert_to_xlsx",
})

# The no-policy fallback: when a Skill declares no ``allowed_tools``, grant only
# read-only tools (plus whatever the output format requires) — never code
# execution or file-writing by default.
SAFE_WORKFLOW_READ_ONLY_TOOLS = frozenset({
    "list_documents",
    "get_document_detail",
    "search_documents",
    "compare_documents",
    "inspect_job_data",
    "list_files",
    "read_file",
})

OUTPUT_INSTRUCTIONS = {
    "text": "Return a concise final response in text.",
    "json": "Return valid JSON only as the final response.",
    "html": "Create and verify a polished standalone HTML report in outputs/ using run_report_code.",
    "docx": "Create and verify a usable DOCX document in outputs/ using create_docx.",
    "pdf": "Create and verify a usable PDF document in outputs/ using create_pdf.",
    "xlsx": "Create and verify a usable XLSX workbook in outputs/ using convert_to_xlsx.",
}


class WorkflowAgentConfigurationError(ValueError):
    pass


def _skill_fingerprint(skill: Any) -> str:
    payload = "\0".join(
        str(value or "")
        for value in (
            skill.name,
            skill.description,
            skill.procedure,
            skill.allowed_tools,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _selected_skills(
    db: Session,
    user_id: UUID,
    skill_ids: list[str],
    skill_fingerprints: dict[str, str] | None = None,
) -> list[Any]:
    if not isinstance(skill_ids, list) or not skill_ids:
        raise WorkflowAgentConfigurationError("Agent mode requires a non-empty Skill list")
    available = {str(skill.id): skill for skill in crud_skill.list_by_user(
        db, user_id=user_id, include_system=True
    )}
    selected = []
    for skill_id in dict.fromkeys(skill_ids):
        skill = available.get(str(skill_id))
        if not skill:
            raise WorkflowAgentConfigurationError(
                f"Selected Agent Skill is missing or inaccessible: {skill_id}"
            )
        expected_fingerprint = (skill_fingerprints or {}).get(str(skill.id))
        if expected_fingerprint and expected_fingerprint != _skill_fingerprint(skill):
            raise WorkflowAgentConfigurationError(
                f"Selected Agent Skill has changed since this Workflow was saved: {skill.name}"
            )
        selected.append(skill)
    if not selected:
        raise WorkflowAgentConfigurationError("Agent mode requires at least one Skill")
    return selected


def _skill_tool_allowlist(skills: list[Any], output_format: str = "text") -> set[str]:
    declared: set[str] = set()
    has_declared_policy = False
    for skill in skills:
        names, normalized = _normalize_allowed_tools(skill.allowed_tools)
        if normalized is not None:
            has_declared_policy = True
            declared.update(names)
    required_tools = OUTPUT_FORMAT_REQUIRED_TOOLS.get(output_format, set())
    if not has_declared_policy:
        # No declared policy → read-only baseline plus the tool(s) the output
        # format actually needs. Never grant write/execute tools implicitly.
        base_tools = set(SAFE_WORKFLOW_READ_ONLY_TOOLS) | set(required_tools)
    else:
        base_tools = set(SAFE_WORKFLOW_AGENT_TOOLS) & declared
        if not required_tools.issubset(base_tools):
            missing = ", ".join(sorted(required_tools - base_tools))
            raise WorkflowAgentConfigurationError(
                f"Selected Skills do not allow required output tool(s) for {output_format}: {missing}"
            )
    return base_tools


def _system_instructions(skills: list[Any], output_format: str, output_filename: str | None) -> str:
    skill_sections = []
    for skill in skills:
        skill_sections.append(
            f"### Skill: {skill.name}\n{skill.description}\n\n{skill.procedure}"
        )
    output_rule = OUTPUT_INSTRUCTIONS.get(output_format, OUTPUT_INSTRUCTIONS["text"])
    approach = _format_approach(output_format)
    filename_rule = (
        f"Required output format: {output_format.upper()}, filename '{output_filename}'. "
        f"{approach} Save the final file at 'outputs/{output_filename}' (or '{output_filename}'). "
        f"Ignore any default output format (such as Markdown or PDF) mentioned in the Skill procedure above when it differs from {output_format.upper()}."
        if output_filename else
        f"Required output format: {output_format.upper()}. {approach} Save the final file in outputs/."
    )
    return f"""## Autonomous Workflow Agent
You are running inside a background Workflow with no interactive user present.
- Never ask a follow-up question and never present choices that require a reply.
- Use the supplied task, Job context, selected Skills, and conservative defaults.
- Work until the requested result is complete or a blocking condition is proven.
- Never claim that a file exists unless a file tool returned a verified success.
- Do not attempt tools that are absent from the provided tool catalog.
- If completion is impossible, return one final explanation naming the missing
  configuration or evidence. Do not wait for confirmation.

## Required Output Format (MANDATORY)
{output_rule}
{filename_rule}

## Selected Skills
{chr(10).join(skill_sections)}
"""


def _format_tool_name(output_format: str) -> str:
    mapping = {
        "docx": "create_docx",
        "pdf": "create_pdf",
        "xlsx": "convert_to_xlsx",
        "html": "run_report_code",
    }
    return mapping.get(output_format, "file tool")


def _format_approach(output_format: str) -> str:
    """Human-readable guidance on how to produce each output format, giving the
    agent more than one valid route so a single omitted tool argument (which
    large models occasionally produce) does not fail the whole node."""
    mapping = {
        "docx": (
            "Produce the Word document with the dedicated `create_docx` tool: pass the full "
            "report as `content` (well-formatted markdown, including a markdown comparison "
            "table) and an optional `title`; `path` is optional and defaults to "
            "outputs/<title>.docx. Preferred over `execute_python`, because `create_docx` "
            "builds a valid DOCX deterministically."
        ),
        "pdf": (
            "Produce the PDF with `create_pdf`, or with `execute_python` (fpdf2 / reportlab) "
            "plus `_save_file()` + `write_file` when `create_pdf` is insufficient."
        ),
        "xlsx": (
            "Produce the workbook with `convert_to_xlsx`, or with `execute_python` "
            "(openpyxl / xlsxwriter) plus `_save_file()` + `write_file`."
        ),
        "html": (
            "Produce the HTML report with `run_report_code`, or `execute_python` + `write_file`."
        ),
    }
    return mapping.get(output_format, "Produce the requested file with the appropriate file tool.")


def _decode_sse(raw: str) -> dict[str, Any] | None:
    line = next((line for line in raw.splitlines() if line.startswith("data: ")), None)
    if not line:
        return None
    try:
        payload = json.loads(line[6:])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _artifact_from_result(tool_name: str, result: Any) -> dict[str, Any] | None:
    if (
        not isinstance(result, dict)
        or result.get("error")
        or result.get("ok") is not True
        or result.get("verified") is not True
    ):
        return None
    path = next(
        (result.get(key) for key in ("path", "output_path", "file_path", "saved_path") if result.get(key)),
        None,
    )
    if not isinstance(path, str) or "outputs/" not in path.replace("\\", "/"):
        return None
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else "file"
    return {
        "filename": path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1],
        "path": path,
        "type": suffix,
        "tool": tool_name,
        "mime_type": result.get("mime_type"),
        "size": result.get("size"),
        "verified": bool(result.get("verified", True)),
    }


def _json_data(text: str, output_format: str) -> Any:
    if output_format != "json":
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _remove_interactive_tail(text: str) -> str:
    """Drop follow-up prompts that cannot be answered in a background run."""
    blocked = (
        "ต้องการให้", "กรุณาสั่ง", "ลองสั่ง", "เลือกเอกสาร", "อัปโหลดเพิ่ม",
        "would you like", "do you want", "please provide", "please choose",
    )
    lines = text.splitlines()
    while lines and any(marker in lines[-1].lower() for marker in blocked):
        lines.pop()
    return "\n".join(lines).strip()


def _agent_status(
    done: dict[str, Any],
    done_seen: bool,
    error_message: str | None,
    final_text: str,
    artifacts: list[dict[str, Any]],
    output_format: str,
) -> str:
    stopped = done.get("stopped")
    success = (
        done_seen
        and not error_message
        and stopped != "max_iterations"
        and done.get("success", True) is not False
    )
    if error_message:
        status = "partial" if final_text or artifacts else "failed"
    elif success:
        status = "succeeded"
    else:
        status = "partial" if final_text or artifacts else "failed"

    if output_format in FILE_OUTPUT_FORMATS:
        if not artifacts:
            status = "partial" if final_text else "failed"
        elif not any(a.get("type") == output_format for a in artifacts):
            # An artifact was produced, but its extension doesn't match the
            # node's output_format — a false success for a node whose contract
            # is this specific file type (e.g. a .md produced for a DOCX node).
            status = "partial"
    return status


async def run_workflow_agent(
    db: Session,
    *,
    user_id: UUID,
    job_id: UUID | None,
    provider: dict[str, Any],
    prompt: str,
    skill_ids: list[str],
    output_format: str = "text",
    output_filename: str | None = None,
    skill_fingerprints: dict[str, str] | None = None,
    max_iterations: int = 7,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    if output_format in FILE_OUTPUT_FORMATS and not job_id:
        raise WorkflowAgentConfigurationError(
            "File output requires a Job context so artifacts can be stored and downloaded safely"
        )
    skills = _selected_skills(db, user_id, skill_ids, skill_fingerprints)
    allowed_tools = _skill_tool_allowlist(skills, output_format=output_format)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise WorkflowAgentConfigurationError("Workflow owner no longer exists")
    if job_id:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or not can_access_job(user, job):
            raise WorkflowAgentConfigurationError("Job context is missing or inaccessible")

    max_iterations = min(max(int(max_iterations or 7), 3), 20)
    timeout_seconds = min(max(int(timeout_seconds or 300), 60), 900)
    conversation = crud_conv.create(
        db,
        job_id=job_id,
        user_id=user_id,
        max_iterations=max_iterations,
        kind="workflow_agent",
    )
    text_parts: list[str] = []
    artifacts: list[dict[str, Any]] = []
    tool_summary: list[dict[str, Any]] = []
    warnings: list[str] = []
    done: dict[str, Any] = {}
    done_seen = False
    error_message: str | None = None

    loop = AgentLoop(
        db=db,
        conversation_id=conversation.id,
        user_id=user_id,
        job_id=job_id,
        llm_config=provider,
        max_iterations=max_iterations,
        kind="document",
        initial_allowed_tools=allowed_tools,
        additional_system_prompt=_system_instructions(skills, output_format, output_filename),
        autonomous=True,
        output_format=output_format,
        output_filename=output_filename,
    )

    async def consume() -> None:
        nonlocal done, done_seen, error_message
        async for raw_event in loop.run(prompt):
            event = _decode_sse(raw_event)
            if not event:
                continue
            event_type = event.get("type")
            if event_type == "delta":
                text_parts.append(str(event.get("text") or ""))
            elif event_type == "tool_result":
                result = event.get("result")
                tool_name = str(event.get("name") or "unknown")
                failed = (
                    isinstance(result, dict)
                    and (bool(result.get("error")) or result.get("ok") is False)
                )
                tool_summary.append({"tool": tool_name, "ok": not failed})
                artifact = _artifact_from_result(tool_name, result)
                if artifact and job_id:
                    artifact["job_id"] = str(job_id)
                if artifact and artifact["path"] not in {item["path"] for item in artifacts}:
                    artifacts.append(artifact)
                if failed:
                    warnings.append(f"{tool_name}: {result.get('error') or 'tool returned ok=false'}")
            elif event_type == "done":
                done = event
                done_seen = True
                # Surface the aggregation gaps (reflection "missing", max-iteration
                # stop, missing file output) as warnings so a partial run explains
                # *why* it is partial instead of failing opaquely.
                for step in (event.get("failed_steps") or []):
                    if step not in warnings:
                        warnings.append(str(step))
            elif event_type == "confirmation_required":
                error_message = "Autonomous Agent attempted an action that requires confirmation"
            elif event_type == "error":
                error_message = str(event.get("message") or "Agent execution failed")

    try:
        await asyncio.wait_for(consume(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        error_message = f"Agent exceeded the configured timeout of {timeout_seconds} seconds"
    finally:
        # Workflow node activity is the audit surface; do not expose these
        # internal runs in the user's Agent DOC conversation history.
        crud_conv.delete(db, conversation.id)

    final_text = _remove_interactive_tail("".join(text_parts).strip())
    status = _agent_status(done, done_seen, error_message, final_text, artifacts, output_format)
    if output_format in {"html", "docx", "pdf", "xlsx"} and not artifacts:
        warnings.append(f"Agent did not produce the required {output_format.upper()} artifact")

    return {
        "status": status,
        "text": final_text or error_message or "Agent finished without a final response",
        "data": _json_data(final_text, output_format),
        "artifacts": artifacts,
        "job_id": str(job_id) if job_id else None,
        "tool_summary": tool_summary,
        "iterations": int(done.get("iterations") or max_iterations),
        "warnings": list(dict.fromkeys(warnings)),
        "error": error_message,
        "selected_skills": [
            {"id": str(skill.id), "name": skill.name, "version": skill.version}
            for skill in skills
        ],
    }
