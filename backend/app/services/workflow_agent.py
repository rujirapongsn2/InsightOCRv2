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
import time
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.agent.context import AgentContext
from app.agent.loop import (
    AgentLoop,
    LLM_MAX_ATTEMPTS,
    LLM_REQUEST_TIMEOUT_S,
    LLM_TEMPERATURE,
    _chat_with_retry,
    _verify_file_tool_result,
)
from app.agent.tools.registry import tool_registry
from app.agent.tools.skill_tools import _normalize_allowed_tools
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_skill import agent_skill as crud_skill
from app.api.permissions import can_access_job
from app.models.job import Job
from app.models.user import User
from app.services.workflow_agent_contracts import (
    AGENT_TASK_PRESETS,
    FILE_OUTPUT_FORMATS,
    OUTPUT_FORMAT_RENDER_TOOLS,
    OUTPUT_FORMAT_REQUIRED_TOOLS,
    agent_task_preset,
    missing_output_tools,
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
    "create_html",
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

# The last-resort fallback render (see `run_workflow_agent`) is a single bounded
# LLM call plus deterministic file rendering; it is worth a fixed grace period
# past the node's configured timeout so it can finish rather than being cut off
# immediately, but the overrun must stay small and visible rather than open-ended.
FALLBACK_RENDER_GRACE_SECONDS = 60.0

# Handoff stages can inspect the Job but cannot depend on, mutate, or create
# files. This prevents a Skill's generic "save outputs" instructions from
# leaking artifacts into intermediate workflow stages.
# Preset handoff stages work from the compact dossier injected by the workflow
# engine.  Keeping their tool catalog empty makes every handoff a bounded
# single-response task instead of a second document-research loop.
SAFE_WORKFLOW_HANDOFF_TOOLS = frozenset()

OUTPUT_INSTRUCTIONS = {
    "text": "Return a concise final response in text.",
    "json": "Return valid JSON only as the final response.",
    "html": "Create and verify a polished standalone HTML report in outputs/ using create_html.",
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


def _skill_tool_allowlist(
    skills: list[Any],
    output_format: str = "text",
    agent_task: str = "custom",
) -> set[str]:
    declared: set[str] = set()
    has_declared_policy = False
    for skill in skills:
        names, normalized = _normalize_allowed_tools(skill.allowed_tools)
        if normalized is not None:
            has_declared_policy = True
            declared.update(names)
    required_tools = OUTPUT_FORMAT_REQUIRED_TOOLS.get(output_format, set())
    preset = agent_task_preset(agent_task)
    if preset and preset.get("handoff_only"):
        return set(SAFE_WORKFLOW_HANDOFF_TOOLS)
    if agent_task == "report":
        # The final report receives prior handoffs as its dossier.  It needs
        # one deterministic artifact tool, not another document-search loop.
        return set(required_tools)
    if not has_declared_policy:
        # No declared policy → read-only baseline plus the tool(s) the output
        # format actually needs. Never grant write/execute tools implicitly.
        base_tools = set(SAFE_WORKFLOW_READ_ONLY_TOOLS) | set(required_tools)
    else:
        base_tools = set(SAFE_WORKFLOW_AGENT_TOOLS) & declared
        missing = missing_output_tools(base_tools, output_format)
        if missing:
            raise WorkflowAgentConfigurationError(
                f"Selected Skills do not allow required output tool(s) for {output_format}: "
                + ", ".join(sorted(missing))
            )
    return base_tools


def _system_instructions(
    skills: list[Any],
    output_format: str,
    output_filename: str | None,
    agent_task: str = "custom",
) -> str:
    preset = agent_task_preset(agent_task)
    skill_sections = []
    for skill in skills:
        # Intermediate handoffs do not have tools and should be prompt-bounded.
        # The full skill procedure is often a long interactive playbook, which
        # adds latency without helping a fixed workflow role complete its task.
        procedure = ""
        if not (preset and preset.get("handoff_only")):
            procedure = str(skill.procedure or "")[:8000]
        skill_sections.append(
            f"### Skill: {skill.name}\n{str(skill.description or '')[:1600]}"
            + (f"\n\n{procedure}" if procedure else "")
        )
    output_rule = OUTPUT_INSTRUCTIONS.get(output_format, OUTPUT_INSTRUCTIONS["text"])
    approach = _format_approach(output_format)
    output_path = (
        str(output_filename).strip()
        if output_filename and str(output_filename).strip().startswith("outputs/")
        else f"outputs/{output_filename}"
    )
    filename_rule = (
        f"Required output format: {output_format.upper()}, filename '{output_filename}'. "
        f"{approach} Save the final file at '{output_path}' (or '{output_filename}'). "
        f"Ignore any default output format (such as Markdown or PDF) mentioned in the Skill procedure above when it differs from {output_format.upper()}."
        if output_filename else
        (
            "Return the result inline as text. Do not create a file."
            if output_format in {"text", "json"}
            else f"Required output format: {output_format.upper()}. {approach} Save the final file in outputs/."
        )
    )
    handoff_rule = ""
    if preset and preset.get("handoff_only"):
        handoff_rule = """
## Handoff Stage (MANDATORY)
This stage produces a text handoff for the next workflow node.
- Work only from the supplied Workflow dossier and handoffs; no tools are available.
- Do not create, read, list, or refer to files or artifact paths.
- Do not follow any Skill instruction that says to save an output file.
- Return only evidence-based analysis in the final response.
"""
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
{handoff_rule}

## Selected Skills
{chr(10).join(skill_sections)}
"""


def _format_tool_name(output_format: str) -> str:
    mapping = {
        "docx": "create_docx",
        "pdf": "create_pdf",
        "xlsx": "convert_to_xlsx",
        "html": "create_html",
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
            "Produce the HTML report with the dedicated `create_html` tool: pass the report body as "
            "`content` (markdown headings, tables and bullets) and an optional `title`; `path` is "
            "optional and defaults to outputs/<title>.html. Preferred over `run_report_code`, because "
            "`create_html` renders and verifies the report without generating code."
        ),
    }
    return mapping.get(output_format, "Produce the requested file with the appropriate file tool.")


COMPOSE_MAX_CONTENT_CHARS = 200_000


def _compose_instructions(skills: list[Any], output_format: str) -> str:
    skill_sections = [
        f"### Skill: {skill.name}\n{str(skill.description or '')[:1600]}"
        + (f"\n\n{str(skill.procedure or '')[:8000]}" if skill.procedure else "")
        for skill in skills
    ]
    return f"""## Workflow Document Composer
You are the final stage of a background Workflow with no interactive user present.
Write the complete deliverable as report content. The Workflow renders and stores
the {output_format.upper()} file for you, so no tool call and no code is needed.
- Use only the supplied task, Workflow dossier, and verified upstream handoffs.
- Never invent documents, figures, dates, or findings the input does not support.
- Write markdown only: one '# ' title line, then '## ' sections, markdown tables
  for comparisons, '- ' bullets, and **bold** for emphasis.
- Do not write Python, HTML, JSON, code fences, or tool calls.
- Do not mention files, paths, downloads, or claim that a file was created.
- Never ask a question and never offer further help.

## Selected Skills
{chr(10).join(skill_sections)}
"""


def _strip_code_fence(text: str) -> str:
    match = re.match(r"^```[a-zA-Z]*\s*\n(.*?)\n?```$", text.strip(), re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _document_title(content: str, output_filename: str | None) -> str:
    heading = re.search(r"^\s*#{1,3}\s+(.+)$", content or "", re.MULTILINE)
    if heading:
        return heading.group(1).strip()[:200]
    if output_filename:
        stem = str(output_filename).rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if stem.strip():
            return stem.replace("_", " ").replace("-", " ").strip()
    return "InsightDOC Report"


async def _compose_document_content(
    *,
    provider: dict[str, Any],
    prompt: str,
    skills: list[Any],
    output_format: str,
    request_timeout_seconds: float,
    max_output_tokens: int | None,
    max_attempts: int,
) -> tuple[str, bool]:
    """One bounded, tool-free LLM call that writes the deliverable's content."""
    api_key = provider.get("apiKey")
    if not api_key:
        raise WorkflowAgentConfigurationError("Agent provider API key is not configured")
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=provider.get("baseUrl") or None,
        timeout=request_timeout_seconds,
        max_retries=0,
    )
    request_kwargs: dict[str, Any] = {
        "model": provider.get("model") or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": _compose_instructions(skills, output_format)},
            {"role": "user", "content": prompt},
        ],
        "temperature": LLM_TEMPERATURE,
        "stream": False,
        "max_attempts": max_attempts,
    }
    if max_output_tokens:
        request_kwargs["max_tokens"] = max_output_tokens
    response = await _chat_with_retry(client, **request_kwargs)
    choice = response.choices[0]
    content = _strip_code_fence(str(choice.message.content or ""))
    truncated = str(getattr(choice, "finish_reason", "") or "") == "length"
    return content[:COMPOSE_MAX_CONTENT_CHARS], truncated


async def _render_document(
    db: Session,
    *,
    user_id: UUID,
    job_id: UUID | None,
    conversation_id: UUID,
    output_format: str,
    content: str,
    title: str,
    output_filename: str | None,
    artifact_prefix: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Render composed content into the node's file format, server-side."""
    tool_name = OUTPUT_FORMAT_RENDER_TOOLS.get(output_format)
    if not tool_name:
        return None, f"No deterministic renderer for output format {output_format}"
    context = AgentContext(
        db=db, user_id=user_id, job_id=job_id,
        conversation_id=conversation_id, kind="document",
    )
    context.output_path_prefix = artifact_prefix or None
    args: dict[str, Any] = {"content": content, "title": title}
    if output_filename:
        args["output_path" if tool_name == "create_pdf" else "path"] = output_filename
    result = _verify_file_tool_result(
        context, tool_name, await tool_registry.execute(tool_name, args, context)
    )
    artifact = _artifact_from_result(tool_name, result)
    if artifact:
        if job_id:
            artifact["job_id"] = str(job_id)
        return artifact, None
    error = result.get("error") if isinstance(result, dict) else None
    return None, str(error or f"{tool_name} did not return a verified file")


async def _compose_and_render(
    db: Session,
    *,
    user_id: UUID,
    job_id: UUID | None,
    conversation_id: UUID,
    provider: dict[str, Any],
    prompt: str,
    skills: list[Any],
    output_format: str,
    output_filename: str | None,
    artifact_prefix: str,
    preset: dict[str, Any] | None,
    content: str | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Write the deliverable as content, then render the file deterministically.

    Splitting composition from rendering is what makes a file-producing node
    dependable: the model spends its whole output budget on the report instead
    of on document-generating code, and the file itself cannot fail on a syntax
    error, a sandbox hiccup, or a truncated tool argument.
    """
    warnings: list[str] = []
    if content is None:
        content, truncated = await _compose_document_content(
            provider=provider,
            prompt=prompt,
            skills=skills,
            output_format=output_format,
            request_timeout_seconds=float(
                (preset or {}).get("request_timeout_seconds") or LLM_REQUEST_TIMEOUT_S
            ),
            max_output_tokens=max_output_tokens or int((preset or {}).get("max_output_tokens") or 0) or None,
            max_attempts=int((preset or {}).get("max_request_attempts") or LLM_MAX_ATTEMPTS),
        )
        if truncated:
            warnings.append(
                "Report content reached the model output limit and may be shortened"
            )
    if not content:
        return {
            "text": "",
            "artifact": None,
            "warnings": warnings,
            "error": "Composer returned no report content",
        }
    artifact, error = await _render_document(
        db,
        user_id=user_id,
        job_id=job_id,
        conversation_id=conversation_id,
        output_format=output_format,
        content=content,
        title=_document_title(content, output_filename),
        output_filename=output_filename,
        artifact_prefix=artifact_prefix,
    )
    return {"text": content, "artifact": artifact, "warnings": warnings, "error": error}


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


def _workflow_artifact_prefix(workflow_run_id: str | None, workflow_node_id: str | None) -> str:
    """Build a storage-safe namespace for one Workflow node execution."""
    if not workflow_run_id or not workflow_node_id:
        return ""
    safe_run = re.sub(r"[^A-Za-z0-9_-]", "", str(workflow_run_id))
    safe_node = re.sub(r"[^A-Za-z0-9_-]", "", str(workflow_node_id))
    if not safe_run or not safe_node:
        raise WorkflowAgentConfigurationError("Workflow artifact namespace is invalid")
    return f"outputs/workflow/{safe_run}/{safe_node}"


def _workflow_output_filename(filename: str | None, artifact_prefix: str) -> str | None:
    """Keep the user-selected filename while placing it under the node namespace."""
    if not artifact_prefix or not filename:
        return filename
    return f"{artifact_prefix}/{str(filename).strip().rsplit('/', 1)[-1]}"


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
    agent_task: str = "custom",
    max_output_tokens: int | None = None,
    workflow_run_id: str | None = None,
    workflow_node_id: str | None = None,
) -> dict[str, Any]:
    preset = agent_task_preset(agent_task)
    if agent_task not in AGENT_TASK_PRESETS:
        raise WorkflowAgentConfigurationError(f"Unknown Agent task preset: {agent_task}")
    fixed_output_format = str((preset or {}).get("output_format") or "")
    if fixed_output_format and output_format != fixed_output_format:
        raise WorkflowAgentConfigurationError(
            f"Agent task '{agent_task}' requires {fixed_output_format.upper()} output"
        )
    if output_format in FILE_OUTPUT_FORMATS and not job_id:
        raise WorkflowAgentConfigurationError(
            "File output requires a Job context so artifacts can be stored and downloaded safely"
        )
    if provider.get("provider") != "openai_compatible":
        raise WorkflowAgentConfigurationError(
            "Agent mode requires an OpenAI-compatible provider with native tool calling"
        )
    skills = _selected_skills(db, user_id, skill_ids, skill_fingerprints)
    allowed_tools = _skill_tool_allowlist(
        skills, output_format=output_format, agent_task=agent_task
    )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise WorkflowAgentConfigurationError("Workflow owner no longer exists")
    if job_id:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or not can_access_job(user, job):
            raise WorkflowAgentConfigurationError("Job context is missing or inaccessible")

    max_iterations = int((preset or {}).get("max_iterations") or max_iterations or 7)
    timeout_seconds = int((preset or {}).get("timeout_seconds") or timeout_seconds or 300)
    max_iterations = min(max(max_iterations, 3), 20)
    timeout_seconds = min(max(timeout_seconds, 60), 900)
    # A node config override wins over the task preset's default — this is the
    # user's escape hatch when the selected model's context window is smaller
    # than what the preset assumes. `is not None` (not truthy) so an explicit
    # 0 from a definition saved before the validator existed is still clamped
    # to the floor instead of silently falling back to the preset default.
    effective_max_output_tokens = (
        min(max(int(max_output_tokens), 256), 16000)
        if max_output_tokens is not None
        else int((preset or {}).get("max_output_tokens") or 0) or None
    )
    artifact_prefix = _workflow_artifact_prefix(workflow_run_id, workflow_node_id)
    effective_output_filename = _workflow_output_filename(output_filename, artifact_prefix)
    started_at = time.monotonic()
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
    trace: list[dict[str, Any]] = []
    warnings: list[str] = []
    done: dict[str, Any] = {}
    done_seen = False
    error_message: str | None = None

    system_instructions = _system_instructions(
        skills, output_format, effective_output_filename, agent_task
    )
    render_tool = OUTPUT_FORMAT_RENDER_TOOLS.get(output_format)
    compose_first = bool((preset or {}).get("compose_and_render") and render_tool)

    async def compose(note: str | None, content: str | None = None) -> None:
        """Write the deliverable as content and render the file server-side."""
        nonlocal done, done_seen, error_message
        outcome = await _compose_and_render(
            db,
            user_id=user_id,
            job_id=job_id,
            conversation_id=conversation.id,
            provider=provider,
            prompt=prompt,
            skills=skills,
            output_format=output_format,
            output_filename=effective_output_filename,
            artifact_prefix=artifact_prefix,
            preset=preset,
            content=content,
            max_output_tokens=effective_max_output_tokens,
        )
        warnings.extend(outcome["warnings"])
        artifact = outcome["artifact"]
        tool_summary.append({"tool": render_tool, "ok": bool(artifact)})
        trace.append({"event": "tool_result", "tool": render_tool, "ok": bool(artifact)})
        if not artifact:
            error_message = outcome["error"] or error_message or "Document rendering failed"
            return
        if artifact["path"] not in {item["path"] for item in artifacts}:
            artifacts.append(artifact)
        if outcome["text"] and not text_parts:
            text_parts.append(outcome["text"])
        if note:
            warnings.append(note)
        # The file exists and is verified, so the node has met its contract even
        # if the agent loop that ran before it did not.
        error_message = None
        done = {"success": True, "stopped": "composed", "iterations": done.get("iterations") or 1}
        done_seen = True

    def build_loop() -> AgentLoop:
        loop = AgentLoop(
            db=db,
            conversation_id=conversation.id,
            user_id=user_id,
            job_id=job_id,
            llm_config=provider,
            max_iterations=max_iterations,
            kind="document",
            initial_allowed_tools=allowed_tools,
            # Workflow stages are isolated, pre-authorized tasks. A compact prompt
            # avoids loading the interactive Agent DOC instruction corpus for every
            # handoff while preserving the selected Skill and output contract.
            system_prompt_override=system_instructions,
            autonomous=True,
            output_format=output_format,
            output_filename=effective_output_filename,
            skip_planning=bool(preset),
            request_timeout_seconds=float((preset or {}).get("request_timeout_seconds") or LLM_REQUEST_TIMEOUT_S),
            max_output_tokens=effective_max_output_tokens,
            max_request_attempts=int((preset or {}).get("max_request_attempts") or LLM_MAX_ATTEMPTS),
        )
        loop.context.output_path_prefix = artifact_prefix or None
        return loop

    async def consume() -> None:
        nonlocal done, done_seen, error_message
        loop = build_loop()
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
                trace.append({"event": "tool_result", "tool": tool_name, "ok": not failed})
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
                trace.append({
                    "event": "done",
                    "success": event.get("success"),
                    "stopped": event.get("stopped"),
                    "iterations": event.get("iterations"),
                })
            elif event_type == "confirmation_required":
                error_message = "Autonomous Agent attempted an action that requires confirmation"
            elif event_type == "error":
                error_message = str(event.get("message") or "Agent execution failed")
                trace.append({"event": "error", "message": error_message[:500]})

    try:
        try:
            if compose_first:
                await asyncio.wait_for(compose(None), timeout=timeout_seconds)
            else:
                await asyncio.wait_for(consume(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            error_message = f"Agent exceeded the configured timeout of {timeout_seconds} seconds"
        except WorkflowAgentConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001 - a node always reports a result
            error_message = f"Agent execution failed: {exc}"

        # Last resort for a file node whose agent loop ended without the artifact:
        # render the document from the composed content so the workflow keeps its
        # downstream steps instead of failing the whole run.
        if render_tool and not compose_first and not artifacts:
            remaining = timeout_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                # The node already exceeded its configured timeout_seconds; note
                # the overrun explicitly instead of silently granting more time.
                warnings.append(
                    f"Fallback rendering ran past the configured {timeout_seconds}s timeout "
                    f"(grace period up to {FALLBACK_RENDER_GRACE_SECONDS:.0f}s)"
                )
            # A substantial answer is already the deliverable — render it as-is
            # rather than paying for a second composition call.
            agent_text = _remove_interactive_tail("".join(text_parts).strip())
            reusable_text = agent_text if len(agent_text) >= 400 else None
            try:
                await asyncio.wait_for(
                    compose(
                        "Agent did not produce the file itself; the Workflow rendered "
                        f"the {output_format.upper()} document from composed content",
                        content=reusable_text,
                    ),
                    timeout=max(remaining, FALLBACK_RENDER_GRACE_SECONDS),
                )
            except asyncio.TimeoutError:
                warnings.append(f"{output_format.upper()} fallback rendering timed out")
            except Exception as exc:  # noqa: BLE001 - fallback must stay non-fatal
                warnings.append(f"{output_format.upper()} fallback rendering failed: {exc}")
    finally:
        # Workflow node activity is the audit surface; do not expose these
        # internal runs in the user's Agent DOC conversation history.
        crud_conv.delete(db, conversation.id)

    final_text = _remove_interactive_tail("".join(text_parts).strip())
    status = _agent_status(done, done_seen, error_message, final_text, artifacts, output_format)
    if output_format in FILE_OUTPUT_FORMATS and not artifacts:
        warnings.append(f"Agent did not produce the required {output_format.upper()} artifact")

    elapsed_ms = round((time.monotonic() - started_at) * 1000)
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
        "trace": trace[-100:],
        "metrics": {
            "elapsed_ms": elapsed_ms,
            "provider": str(provider.get("source") or provider.get("provider") or "unknown"),
            "model": str(provider.get("model") or "unknown"),
            "stop_reason": str(done.get("stopped") or ("timeout" if error_message and "timeout" in error_message.lower() else "completed")),
        },
        "selected_skills": [
            {"id": str(skill.id), "name": skill.name, "version": skill.version}
            for skill in skills
        ],
    }
