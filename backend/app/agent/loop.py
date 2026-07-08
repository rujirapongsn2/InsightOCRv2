"""
Agent Loop — multi-turn tool calling with streaming.

Optimizations (Phase 6):
  - System prompt sent only once (saves tokens across iterations)
  - Parallel tool execution via asyncio.gather when no confirmation needed
"""
import json
import asyncio
import logging
import os
import re
from typing import AsyncGenerator, Any
from uuid import UUID, uuid4
from types import SimpleNamespace
from pathlib import Path
from sqlalchemy.orm import Session
from openai import AsyncOpenAI
import httpx

logger = logging.getLogger(__name__)

from app.agent.context import AgentContext, build_system_prompt, tool_content_for_llm
from app.agent.events import sse_event, SSEEventType
from app.agent.confirmations import requires_confirmation, describe_action
from app.agent.tools.registry import tool_registry
from app.agent.tools import document_tools, integration_tools, memory_tools, code_tools, skill_tools, filesystem_tools, web_search_tools, workflow_tools  # noqa: F401 — side-effect: registers tools
from app.crud.crud_agent_message import agent_message as crud_msg
from app.crud.crud_agent_pending import agent_pending as crud_pending
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.models.agent_message import AgentMessage
from app.utils.activity_logger import log_activity


# LLM call reliability knobs. Low temperature keeps tool arguments and JSON
# deterministic; retries absorb transient provider failures (429/5xx/timeouts)
# so a single hiccup doesn't kill a run that already did useful work.
LLM_TEMPERATURE = 0.2
LLM_REQUEST_TIMEOUT_S = 120.0
LLM_MAX_ATTEMPTS = 3
LLM_RETRY_BASE_DELAY_S = 2.0

# Hard cap for one agent run. The run lives inside the HTTP request, so
# without a cap a hung tool or provider keeps the connection (and its DB
# session) open until the proxy kills it.
AGENT_MAX_RUNTIME_S = int(os.environ.get("AGENT_MAX_RUNTIME_S", "900"))


async def _chat_with_retry(client: AsyncOpenAI, **kwargs):
    """chat.completions.create with retries and a temperature fallback.

    Some OpenAI-compatible providers reject the temperature parameter; on such
    an error we drop it and retry immediately instead of burning attempts.
    """
    last_exc: Exception | None = None
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "temperature" in msg and "temperature" in kwargs:
                kwargs.pop("temperature")
                continue
            # Some providers don't support function calling — drop tools and retry
            # immediately so callers can fall back to parsing JSON from content.
            if ("tool" in msg or "function" in msg) and "tools" in kwargs:
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                continue
            if attempt < LLM_MAX_ATTEMPTS:
                await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * (2 ** (attempt - 1)))
    raise last_exc


def _max_iterations_fallback_text(user_message: str) -> str:
    thai = bool(re.search(r"[\u0e00-\u0e7f]", user_message or ""))
    if thai:
        return (
            "ผมใช้จำนวนรอบการทำงานครบกำหนดแล้วแต่ยังทำงานไม่เสร็จสมบูรณ์ครับ "
            "ผลลัพธ์บางส่วนอาจถูกบันทึกไว้แล้ว — ลองสั่งต่อโดยระบุขอบเขตให้แคบลง "
            "เช่น เลือกเอกสารหรือขั้นตอนที่ต้องการเป็นพิเศษ"
        )
    return (
        "I reached the maximum number of working iterations before fully completing the task. "
        "Partial results may already be saved — please retry with a narrower request, "
        "such as a specific document or step."
    )


def _tool_calls_data(msg) -> list[dict]:
    """Build OpenAI-format tool_calls array from an assistant message."""
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }
        for tc in msg.tool_calls
    ]


async def _exec_single(tool_name: str, args: dict, context) -> dict:
    """Execute one tool and return its result."""
    return await tool_registry.execute(tool_name, args, context)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]
    try:
        parsed = json.loads(cleaned)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract every top-level JSON object from text via balanced-brace scanning.

    Robust to a model that returns several action objects in one response
    (e.g. three concatenated {"type":"tool_call",...} lines) or wraps them in
    prose / markdown fences. String contents (with escapes) are skipped so
    braces inside string values don't confuse the scan.
    """
    if not text:
        return []
    objs: list[dict[str, Any]] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(text[start:i + 1])
                    if isinstance(obj, dict):
                        objs.append(obj)
                except Exception:
                    pass
                start = -1
    return objs




def _tool_failed(result: Any) -> bool:
    return isinstance(result, dict) and ("error" in result or result.get("ok") is False)


def _aggregate_success(
    stopped: str | None,
    reflection: dict[str, Any] | None,
    critical_failures: list[dict[str, Any]],
    current_turn_file_success: bool,
    requires_file: bool,
) -> tuple[bool, list[str]]:
    """Combine all signals into a single success verdict + human-readable gaps.

    Returns (success, failed_steps). `success` is True only when every signal
    is clean. `failed_steps` is the union of reasons — surfaced to the UI.
    """
    failed_steps: list[str] = []
    if stopped == "max_iterations":
        failed_steps.append("Reached max tool iterations without completing")
    if reflection is not None and not reflection.get("complete"):
        failed_steps.extend(reflection.get("missing") or [])
    for f in critical_failures:
        failed_steps.append(f["error"])
    if requires_file and not current_turn_file_success:
        failed_steps.append("Requested file output was not produced or verified")
    return (len(failed_steps) == 0), failed_steps


def _tool_error_summary(tool_name: str, result: Any) -> str:
    if not isinstance(result, dict):
        return f"{tool_name} failed"
    error = result.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or json.dumps(error, ensure_ascii=False, default=str)
    else:
        message = str(error or result.get("stderr") or "unknown error")
    return f"{tool_name}: {message}"


def _is_file_write_success(tool_name: str, result: Any) -> bool:
    return (
        tool_name in {"execute_python", "write_file", "create_docx", "create_pdf", "convert_to_xlsx", "run_report_code"}
        and isinstance(result, dict)
        and result.get("ok") is True
        and result.get("verified") is True
        and bool(result.get("path"))
    )


def _is_report_success(tool_name: str, result: Any) -> bool:
    return tool_name == "run_report_code" and _is_file_write_success(tool_name, result)


def _verify_file_tool_result(context: AgentContext, tool_name: str, result: Any) -> Any:
    if tool_name not in {"execute_python", "write_file", "create_docx", "create_pdf", "convert_to_xlsx", "run_report_code"}:
        return result
    if not isinstance(result, dict) or result.get("ok") is not True or not result.get("path"):
        return result

    verification = filesystem_tools.verify_saved_file(
        str(context.job_id),
        str(result.get("path")),
        expected_size=result.get("size") if result.get("size") is not None else None,
    )
    if verification.get("ok") is True:
        verified = dict(result)
        verified["verified"] = True
        verified["verified_size"] = verification.get("size")
        verified["mime_type"] = result.get("mime_type") or verification.get("mime_type")
        return verified

    failed = dict(result)
    failed["ok"] = False
    failed["verified"] = False
    failed["error"] = verification.get("error") or "File verification failed"
    return failed


def _looks_like_raw_tool_payload(text: str | None) -> bool:
    stripped = (text or "").strip()
    if not stripped.startswith("{") or len(stripped) < 20:
        return False
    lowered = stripped.lower()
    return "tool_calls" in lowered or "run_report_code" in lowered or '"type":"tool_call"' in lowered or '"type": "tool_call"' in lowered


def _raw_tool_payload_failure_text(user_message: str) -> str:
    thai = bool(re.search(r"[\u0e00-\u0e7f]", user_message or ""))
    if thai:
        return (
            "ยังไม่ได้สร้างรายงานครับ ระบบได้รับ payload เรียก tool แบบ raw "
            "แต่ยังไม่มีผลลัพธ์จาก run_report_code ที่ยืนยันว่าไฟล์ถูกสร้างสำเร็จ กรุณาสั่งใหม่อีกครั้ง"
        )
    return (
        "The report was not created. The model returned a raw tool-call payload, "
        "but run_report_code did not return a successful file result. Please retry the request."
    )


def _short_report_final_text(result: Any, user_message: str) -> str:
    path = result.get("path") or result.get("download_path") or "outputs/report.html"
    thai = bool(re.search(r"[\u0e00-\u0e7f]", user_message or ""))
    if thai:
        return (
            "สร้างรายงาน HTML เรียบร้อยครับ\n\n"
            f"ไฟล์: `{path}`\n\n"
            "ดาวน์โหลดได้จากปุ่ม Download ใต้คำตอบนี้ครับ"
        )
    return (
        "The HTML report has been created.\n\n"
        f"File: `{path}`\n\n"
        "Use the Download button below this answer to open it."
    )


def _latest_successful_report(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(tool_results):
        if _is_report_success(str(item.get("tool") or ""), item.get("result")):
            return item.get("result")
    return None


def _claims_file_success(text: str) -> bool:
    lowered = (text or "").lower()
    if "outputs/" in lowered:
        return True
    if "download" in lowered or "ดาวน์โหลด" in lowered:
        return True
    if any(token in lowered for token in ["สร้างไฟล์", "ทำไฟล์", "บันทึกไฟล์", "ไฟล์ถูกสร้าง", "ไฟล์พร้อมใช้งาน"]):
        return True
    if "ไฟล์" in lowered and any(token in lowered for token in ["บันทึกเรียบร้อย", "ตรวจสอบไฟล์แล้ว", "พร้อมดาวน์โหลด"]):
        return True
    if any(ext in lowered for ext in [".csv", ".docx", ".md", ".pdf", ".pptx", ".xlsx"]):
        return any(token in lowered for token in [
            "created successfully", "saved successfully", "file created", "file saved", "generated file",
        ])
    return False


def _requires_web_search(user_message: str) -> bool:
    text = (user_message or "").lower()
    return any(token in text for token in [
        "ค้น", "หาข้อมูล", "จากเว็บ", "เว็บไซต์", "www.", "http://", "https://",
        "softnix.co.th", "web search", "search web", "internet",
    ])


def _requires_file_output(user_message: str) -> bool:
    text = (user_message or "").lower()
    file_tokens = ["ไฟล์", "pdf", "excel", "xlsx", "csv", "docx", "word", "ใบเสนอราคา", "quotation", "บันทึก"]
    action_tokens = ["สร้าง", "ทำ", "เขียน", "แก้", "แก้ไข", "เพิ่ม", "อัปเดต", "แปลง", "update", "export", "save", "convert"]
    return any(token in text for token in file_tokens) and any(token in text for token in action_tokens)


def _is_xlsx_conversion_request(user_message: str) -> bool:
    text = (user_message or "").lower()
    wants_excel = any(token in text for token in ["excel", "xlsx", "spreadsheet", "เอ็กเซล"])
    wants_convert = any(token in text for token in ["แปลง", "convert", "ทำเป็น", "เปลี่ยนเป็น"])
    return wants_excel and wants_convert


def _is_pdf_creation_request(user_message: str) -> bool:
    text = (user_message or "").lower()
    wants_pdf = "pdf" in text or "พีดีเอฟ" in text
    wants_create = any(token in text for token in ["สร้าง", "แปลง", "ทำเป็น", "เปลี่ยนเป็น", "export", "save", "convert"])
    return wants_pdf and wants_create


def _claims_failure(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in [
        "ไม่สำเร็จ", "ยังไม่ได้", "ไม่พบผลลัพธ์", "failed", "failure", "not created", "not saved",
    ])


def _file_success_final_text(result: dict[str, Any], user_message: str) -> str:
    path = result.get("path")
    source = result.get("source_path")
    thai = bool(re.search(r"[\u0e00-\u0e7f]", user_message or ""))
    suffix = Path(str(path or "")).suffix.lower()
    artifact_name = {
        ".xlsx": "Excel",
        ".xls": "Excel",
        ".csv": "CSV",
        ".pdf": "PDF",
        ".docx": "Word",
        ".html": "HTML",
        ".md": "Markdown",
    }.get(suffix, "ไฟล์" if thai else "file")
    if thai:
        if source:
            return f"เรียบร้อยครับ ผมแปลงไฟล์ `{source}` เป็น {artifact_name} และตรวจสอบไฟล์แล้ว: `{path}`"
        return f"เรียบร้อยครับ ผมสร้างและตรวจสอบไฟล์แล้ว: `{path}`"
    if source:
        return f"Done. I converted `{source}` to {artifact_name} and verified the file: `{path}`"
    return f"Done. I created and verified the file: `{path}`"


def _sanitize_unverified_file_claims(text: str) -> str:
    """Remove stale file/download claims while preserving the useful answer body."""
    cleaned: list[str] = []
    for line in (text or "").splitlines():
        lowered = line.lower()
        has_file_path = "outputs/" in lowered or any(ext in lowered for ext in [".csv", ".docx", ".md", ".pdf", ".pptx", ".xlsx"])
        has_file_claim = any(token in lowered for token in [
            "ไฟล์", "download", "ดาวน์โหลด", "created", "generated", "saved", "verified",
            "สร้างเสร็จ", "บันทึก", "ตรวจสอบไฟล์", "มีอยู่แล้ว",
        ])
        if has_file_path and has_file_claim:
            continue
        if "พร้อมดาวน์โหลด" in lowered or "ให้พร้อมดาวน์โหลด" in lowered:
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _required_tool_instruction(kind: str) -> str:
    if kind == "web_search":
        return (
            "The user's current request explicitly requires external web research. "
            "Call web_search in this same turn before answering or creating/updating files. "
            "Use the returned URLs/snippets as evidence and do not answer from memory alone."
        )
    return (
        "The user's current request asks to create or update a Word/file artifact. "
        "Call convert_to_xlsx for existing-file-to-Excel conversion, or execute_python with _save_file auto-capture, "
        "create_docx, run_report_code, or write_file in this same turn "
        "and only give the file name after the tool returns ok=true and verified=true. "
        "Do not reuse an older file-success result from conversation history."
    )


def _tool_failure_instruction(tool_name: str, result: Any) -> str:
    return (
        "A tool just failed. You must either fix the problem with another appropriate tool call, "
        "or clearly tell the user the action failed. Do not claim that any file was created or saved "
        f"unless a later file-producing tool returns ok=true and verified=true. Failure: {_tool_error_summary(tool_name, result)}"
    )


def _failure_final_text(tool_errors: list[dict[str, Any]]) -> str:
    last = tool_errors[-1]
    return (
        "ยังดำเนินการไม่สำเร็จครับ: "
        f"{_tool_error_summary(last.get('tool', 'tool'), last.get('result'))}. "
        "ผมยังไม่พบผลลัพธ์จากเครื่องมือที่ยืนยันว่าไฟล์ถูกสร้าง บันทึก และตรวจสอบสำเร็จ"
    )


# ── Plan & Reflect stages ────────────────────────────────────────────
# Keywords that signal a multi-step / action task worth an explicit plan.
# Pure QA ("ยอดรวมเท่าไหร่", "เอกสารมีกี่ใบ") stays fast — no planning round-trip.
_PLAN_TRIGGER_TOKENS = (
    "สร้าง", "ทำรายงาน", "รายงาน", "เปรียบเทียบ", "วิเคราะห์", "ตรวจสอบ", "ตรวจ",
    "อนุมัติ", "แก้ไข", "อัปเดต", "นำเข้า", "ส่งออก", "ส่งไป", "จัดทำ", "รวบรวม",
    "ทุกเอกสาร", "แต่ละ", "ทั้งหมด", "แล้วส่ง", "และส่ง", "ใบเสนอราคา",
    "report", "compare", "analyze", "validate", "generate", "export", "import",
    "approve", "create", "build", "all documents", "each",
)


def _is_complex_request(user_message: str) -> bool:
    """Heuristic: should this request get an explicit plan + reflection pass?"""
    text = (user_message or "").strip().lower()
    if len(text) >= 80:
        return True
    if any(tok in text for tok in _PLAN_TRIGGER_TOKENS):
        return True
    # multiple clauses chained → likely multi-step
    if text.count("แล้ว") + text.count(" and ") + text.count("และ") >= 1 and len(text) >= 40:
        return True
    return _requires_file_output(user_message) or _requires_web_search(user_message)


_PLAN_SYSTEM_PROMPT = (
    "You are the planning module of a document-management agent. "
    "Break the user's request into a SHORT ordered checklist of concrete sub-goals "
    "(2–6 items) that, once all done, fully satisfy the request. "
    "Each item is a brief actionable phrase in the user's language — not a tool name. "
    "Return STRICT JSON only: {\"steps\": [\"...\", \"...\"]}. "
    "If the request is a single trivial question, return {\"steps\": []}."
)


def _parse_plan(text: str) -> list[str]:
    obj = _extract_json_object(text)
    if not obj:
        return []
    steps = obj.get("steps")
    if not isinstance(steps, list):
        return []
    out: list[str] = []
    for s in steps:
        s = str(s).strip()
        if s:
            out.append(s[:200])
        if len(out) >= 6:
            break
    return out


_REFLECT_SYSTEM_PROMPT = (
    "You are the final-review module of a document-management agent. "
    "Given the user's original request, the plan checklist, a summary of what was "
    "actually done (tools + results), and the draft answer, decide whether the result "
    "TRULY and COMPLETELY satisfies the user's intent. Be strict: a partially-correct "
    "or incomplete answer is NOT complete. "
    "Return STRICT JSON only: "
    "{\"complete\": true|false, \"missing\": [\"...\"], \"revised_answer\": \"...optional...\"}. "
    "Set complete=false and list concrete gaps in `missing` only when real work remains. "
    "Provide `revised_answer` only if you can improve wording without doing more work."
)


def _parse_reflection(text: str) -> dict[str, Any]:
    obj = _extract_json_object(text) or {}
    missing = obj.get("missing")
    return {
        "complete": bool(obj.get("complete", True)),
        "missing": [str(m).strip() for m in missing if str(m).strip()] if isinstance(missing, list) else [],
        "revised_answer": (str(obj["revised_answer"]).strip() if obj.get("revised_answer") else None),
    }

def _extract_tool_calls_from_content(text: str | None) -> list:
    """Support providers that return tool calls as JSON text instead of native tool_calls."""
    if not text:
        return []

    candidates: list[dict[str, Any]] = []
    parsed = _extract_json_object(text)
    if parsed:
        candidates.append(parsed)

    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            candidate, end = decoder.raw_decode(text[start:])
        except Exception:
            index = start + 1
            continue
        if isinstance(candidate, dict):
            candidates.append(candidate)
        index = start + max(end, 1)

    calls = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        raw_calls = candidate.get("tool_calls") or candidate.get("tools") or []
        if isinstance(raw_calls, dict):
            raw_calls = [raw_calls]
        if not isinstance(raw_calls, list):
            continue
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name") or raw.get("tool") or raw.get("function", {}).get("name")
            arguments = raw.get("arguments") or raw.get("args") or raw.get("function", {}).get("arguments") or {}
            if not name:
                continue
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            key = (str(name), json.dumps(arguments, sort_keys=True, ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            calls.append(SimpleNamespace(
                id=raw.get("id") or f"call_{uuid4().hex[:12]}",
                function=SimpleNamespace(name=str(name), arguments=json.dumps(arguments, ensure_ascii=False)),
            ))
    return calls


class AgentLoop:
    """One agent run for one user message."""

    def __init__(self, db: Session, conversation_id: UUID, user_id: UUID, job_id: UUID | None, llm_config: dict, max_iterations: int = 15, kind: str = "document"):
        self.db = db
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.job_id = job_id
        self.llm_config = llm_config
        self.max_iterations = max_iterations
        self.kind = kind
        self.context = AgentContext(db=db, user_id=user_id, job_id=job_id, conversation_id=conversation_id, kind=kind)

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        deadline = asyncio.get_event_loop().time() + AGENT_MAX_RUNTIME_S
        try:
            async for event in self._run_inner(user_message):
                yield event
                if asyncio.get_event_loop().time() > deadline:
                    logger.warning(
                        "Agent run exceeded %ss cap — stopping", AGENT_MAX_RUNTIME_S
                    )
                    yield sse_event(SSEEventType.ERROR, {
                        "message": f"หยุดการทำงาน: เกินเวลาสูงสุด {AGENT_MAX_RUNTIME_S // 60} นาทีต่อการรันหนึ่งครั้ง"
                    })
                    return
        except Exception as e:
            logger.error("AgentLoop.run crashed (unhandled): %s", e, exc_info=True)
            try:
                yield sse_event(SSEEventType.ERROR, {"message": f"ระบบพบข้อผิดพลาดที่ไม่คาดคิด: {str(e)}"})
            except Exception:
                pass

    async def _run_inner(self, user_message: str) -> AsyncGenerator[str, None]:
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="user", content=user_message, iteration=0)
        crud_conv.update_title(self.db, self.conversation_id, user_message[:60])

        if self.kind == "workflow_builder":
            async for event in self._run_workflow_builder(user_message):
                yield event
            return

        if self.llm_config.get("provider") == "completion_messages":
            async for event in self._run_completion_provider(user_message):
                yield event
            return

        api_key = self.llm_config.get("apiKey")
        if not api_key:
            yield sse_event(SSEEventType.ERROR, {"message": "Agent provider API key is not configured"})
            return

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.llm_config.get("baseUrl") or None,
            timeout=LLM_REQUEST_TIMEOUT_S,
            max_retries=0,  # retries are handled by _chat_with_retry with backoff
        )
        model = self.llm_config.get("model", "gpt-4o-mini")
        system_prompt = build_system_prompt(self.context, user_message)
        tools_schema = tool_registry.get_openai_schemas()

        history = await self.context.load_history()

        # System prompt only once in messages[0] — subsequent iterations append to messages directly
        messages: list[dict] = [{"role": "system", "content": system_prompt}] + history
        tool_events_seen = 0
        latest_tool_error_index = 0
        latest_file_success_index = 0
        latest_file_success_result: dict[str, Any] | None = None
        latest_report_success: dict[str, Any] | None = None
        unresolved_tool_errors: list[dict[str, Any]] = []
        critical_tool_failures: list[dict[str, Any]] = []
        reflection_result: dict[str, Any] | None = None
        current_turn_tools: set[str] = set()
        current_turn_file_success = False
        nudged_required_search = False
        nudged_required_file = False
        stale_file_claim_nudges = 0

        if _is_xlsx_conversion_request(user_message):
            source_path = self._latest_convertible_output_path()
            if source_path:
                async for event in self._run_direct_file_conversion(user_message, source_path):
                    yield event
                return

        if _is_pdf_creation_request(user_message):
            source_path = self._latest_text_output_path()
            source_content = None if source_path else self._latest_assistant_content_for_pdf()
            if source_path or source_content:
                async for event in self._run_direct_pdf_creation(user_message, source_path, source_content):
                    yield event
                return

        # ── Stage: PLAN ──────────────────────────────────────────────
        # For non-trivial requests, decompose into an explicit checklist so the
        # execution loop has concrete sub-goals and the reflection stage has a
        # yardstick. Trivial QA skips this to stay fast.
        plan_steps: list[str] = []
        plan_msg = None
        reflected = False
        if _is_complex_request(user_message):
            plan_steps = await self._build_plan(client, model, user_message, history)
            if plan_steps:
                yield sse_event(SSEEventType.PLAN, {"steps": plan_steps})
                # Persist as a UI-only "plan" message so the checklist survives in
                # history (load_history skips this role, so it never reaches the LLM).
                plan_msg = crud_msg.add(
                    self.db, conversation_id=self.conversation_id, role="plan",
                    tool_result={"steps": plan_steps, "reflection": None}, iteration=0,
                )
                checklist = "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan_steps))
                messages.append({
                    "role": "system",
                    "content": (
                        "Plan for this request — work through every item, then give a final answer that "
                        "covers all of them. Do not stop until each item is genuinely done or you have "
                        f"clearly reported why it cannot be:\n{checklist}"
                    ),
                })

        for iteration in range(1, self.max_iterations + 1):
            yield sse_event(SSEEventType.THINKING, {"iteration": iteration})

            try:
                response = await _chat_with_retry(
                    client,
                    model=model,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice="auto",
                    temperature=LLM_TEMPERATURE,
                    stream=False,
                )
            except Exception as e:
                yield sse_event(SSEEventType.ERROR, {"message": f"LLM error: {str(e)}"})
                return

            choice = response.choices[0]
            msg = choice.message

            content_tool_calls = _extract_tool_calls_from_content(msg.content) if not msg.tool_calls else []
            active_tool_calls = list(msg.tool_calls or content_tool_calls)

            if active_tool_calls:
                if msg.tool_calls:
                    tcd = _tool_calls_data(msg)
                    assistant_content = msg.content
                else:
                    tcd = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in active_tool_calls
                    ]
                    assistant_content = None

                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=assistant_content, tool_calls=tcd,
                             iteration=iteration, model_used=model)
                messages.append({"role": "assistant", "content": assistant_content, "tool_calls": tcd})

                # Parse all tool calls
                parsed: list[tuple] = []
                for tc in active_tool_calls:
                    try:
                        parsed.append((tc, tc.function.name, json.loads(tc.function.arguments or "{}")))
                    except Exception:
                        parsed.append((tc, tc.function.name, {}))

                # Emit TOOL_CALL events
                for tc, name, args in parsed:
                    yield sse_event(SSEEventType.TOOL_CALL, {"id": tc.id, "name": name, "arguments": args})

                # Determine execution strategy
                needs_confirmation = any(requires_confirmation(name, args) for _, name, args in parsed)

                # Tool-failure nudges are deferred and flushed only AFTER every
                # tool response is appended — injecting a system message between
                # the tool messages of one assistant turn breaks the OpenAI
                # "tool_calls must be followed by a tool message per id" rule.
                failure_notes: list[str] = []

                if needs_confirmation:
                    # Sequential — confirmation gates require per-tool user interaction
                    for tc, tool_name, tool_args in parsed:
                        if requires_confirmation(tool_name, tool_args):
                            pending = crud_pending.create(
                                self.db, conversation_id=self.conversation_id, user_id=self.user_id,
                                tool_name=tool_name, tool_arguments=tool_args,
                                description=describe_action(tool_name, tool_args),
                            )
                            yield sse_event(SSEEventType.CONFIRMATION_REQUIRED, {
                                "pending_action_id": str(pending.id),
                                "tool_call_id": tc.id,
                                "tool_name": tool_name,
                                "description": pending.description,
                                "arguments": tool_args,
                            })
                            approved = await self._wait_for_confirmation(pending.id)
                            if not approved:
                                result = {"error": "User rejected action", "tool_name": tool_name}
                                yield sse_event(SSEEventType.TOOL_REJECTED, {"id": tc.id, "name": tool_name})
                            else:
                                result = await tool_registry.execute(tool_name, tool_args, self.context)
                                result = _verify_file_tool_result(self.context, tool_name, result)
                                log_activity(
                                    self.db, user_id=self.user_id,
                                    action=f"agent_tool_{tool_name}",
                                    resource_type="agent_conversation",
                                    resource_id=self.conversation_id,
                                    details={"tool_name": tool_name, "arguments": tool_args, "agent_initiated": True},
                                )
                        else:
                            result = await tool_registry.execute(tool_name, tool_args, self.context)
                            result = _verify_file_tool_result(self.context, tool_name, result)

                        yield sse_event(SSEEventType.TOOL_RESULT, {"id": tc.id, "name": tool_name, "result": result})
                        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                                     tool_call_id=tc.id, tool_name=tool_name,
                                     tool_result=result, iteration=iteration)
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": tool_content_for_llm(result),
                        })
                        tool_events_seen += 1
                        current_turn_tools.add(tool_name)
                        if _is_file_write_success(tool_name, result):
                            current_turn_file_success = True
                            latest_file_success_result = result
                        if _is_report_success(tool_name, result):
                            latest_report_success = result
                        if _tool_failed(result):
                            latest_tool_error_index = tool_events_seen
                            unresolved_tool_errors.append({"tool": tool_name, "result": result})
                            critical_tool_failures.append(
                                {"tool": tool_name, "error": _tool_error_summary(tool_name, result)}
                            )
                            failure_notes.append(_tool_failure_instruction(tool_name, result))
                        elif _is_file_write_success(tool_name, result):
                            latest_file_success_index = tool_events_seen
                            unresolved_tool_errors.clear()
                else:
                    # Parallel — all read-only tools, execute concurrently
                    tasks = [_exec_single(name, args, self.context) for _, name, args in parsed]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for (tc, tool_name, _), result in zip(parsed, results):
                        if isinstance(result, Exception):
                            result = {"error": str(result)}
                        else:
                            result = _verify_file_tool_result(self.context, tool_name, result)
                        yield sse_event(SSEEventType.TOOL_RESULT, {"id": tc.id, "name": tool_name, "result": result})
                        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                                     tool_call_id=tc.id, tool_name=tool_name,
                                     tool_result=result, iteration=iteration)
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": tool_content_for_llm(result),
                        })
                        tool_events_seen += 1
                        current_turn_tools.add(tool_name)
                        if _is_file_write_success(tool_name, result):
                            current_turn_file_success = True
                            latest_file_success_result = result
                        if _is_report_success(tool_name, result):
                            latest_report_success = result
                        if _tool_failed(result):
                            latest_tool_error_index = tool_events_seen
                            unresolved_tool_errors.append({"tool": tool_name, "result": result})
                            critical_tool_failures.append(
                                {"tool": tool_name, "error": _tool_error_summary(tool_name, result)}
                            )
                            failure_notes.append(_tool_failure_instruction(tool_name, result))
                        elif _is_file_write_success(tool_name, result):
                            latest_file_success_index = tool_events_seen
                            unresolved_tool_errors.clear()

                # Flush deferred failure nudges — now that all tool messages for
                # this assistant turn are contiguous, system messages are safe.
                for note in failure_notes:
                    messages.append({"role": "system", "content": note})

            else:
                final_text = msg.content or ""
                if _looks_like_raw_tool_payload(final_text):
                    if latest_report_success:
                        final_text = _short_report_final_text(latest_report_success, user_message)
                    else:
                        final_text = _raw_tool_payload_failure_text(user_message)
                elif latest_report_success and len(final_text) > 800:
                    final_text = _short_report_final_text(latest_report_success, user_message)
                if _requires_web_search(user_message) and "web_search" not in current_turn_tools and not nudged_required_search:
                    messages.append({"role": "system", "content": _required_tool_instruction("web_search")})
                    nudged_required_search = True
                    continue
                if _requires_file_output(user_message) and not current_turn_file_success and not nudged_required_file:
                    messages.append({"role": "system", "content": _required_tool_instruction("file_output")})
                    nudged_required_file = True
                    continue
                if _requires_file_output(user_message) and not current_turn_file_success and _claims_file_success(final_text):
                    final_text = "ยังไม่ได้สร้างหรือแก้ไขไฟล์ในรอบคำสั่งนี้ครับ เพราะยังไม่มีผลลัพธ์จากเครื่องมือสร้างไฟล์ที่ยืนยันว่า ok=true และ verified=true"
                if (
                    _claims_file_success(final_text)
                    and not current_turn_file_success
                    and stale_file_claim_nudges < 2
                    and iteration < self.max_iterations
                ):
                    messages.append({
                        "role": "system",
                        "content": (
                            "Your draft claims a file was created, saved, downloaded, verified, or available at an outputs/ path, "
                            "but no file-producing tool returned ok=true and verified=true in the CURRENT user turn. "
                            "Do not reuse file-success claims from conversation history. "
                            "Either call an appropriate file-producing tool now, or rewrite the answer directly in chat without any claim "
                            "that a file was created/saved/verified. If the user asked for a table, provide the table inline in chat. "
                            "Do not mention outputs/, download, .xlsx, .docx, .pdf, or .md unless a current-turn verified file tool succeeded."
                        ),
                    })
                    stale_file_claim_nudges += 1
                    continue
                if (
                    _requires_file_output(user_message)
                    and current_turn_file_success
                    and latest_file_success_result
                    and _claims_failure(final_text)
                ):
                    final_text = _file_success_final_text(latest_file_success_result, user_message)
                if _claims_file_success(final_text) and not current_turn_file_success and stale_file_claim_nudges >= 2:
                    sanitized = _sanitize_unverified_file_claims(final_text)
                    final_text = (
                        sanitized
                        if sanitized and not _claims_file_success(sanitized)
                        else "รอบคำสั่งนี้ยังไม่มีเครื่องมือที่ยืนยันว่าไฟล์ถูกสร้าง บันทึก และตรวจสอบสำเร็จครับ"
                    )
                if (
                    latest_tool_error_index > latest_file_success_index
                    and unresolved_tool_errors
                    and _claims_file_success(final_text)
                ):
                    final_text = _failure_final_text(unresolved_tool_errors)

                # ── Stage: REFLECT ───────────────────────────────────
                # Before finalizing, grade the draft answer against the plan and
                # the user's intent. If real work remains, feed the gaps back and
                # keep working (once) instead of returning an incomplete answer.
                if (
                    plan_steps and not reflected and current_turn_tools
                    and not unresolved_tool_errors and iteration < self.max_iterations
                ):
                    reflected = True
                    reflection = await self._reflect(
                        client, model, user_message, plan_steps, final_text, current_turn_tools
                    )
                    reflection_result = reflection
                    if not reflection["complete"] and reflection["missing"]:
                        yield sse_event(SSEEventType.REFLECTION, {
                            "complete": False, "missing": reflection["missing"],
                        })
                        self._persist_reflection(plan_msg, plan_steps, False, reflection["missing"])
                        gaps = "\n".join(f"- {m}" for m in reflection["missing"])
                        messages.append({
                            "role": "system",
                            "content": (
                                "Self-review found the request is not yet fully satisfied. "
                                "Address these remaining gaps using tools, then give the final answer. "
                                "Do not claim completion until they are genuinely done:\n" + gaps
                            ),
                        })
                        continue
                    yield sse_event(SSEEventType.REFLECTION, {"complete": True})
                    self._persist_reflection(plan_msg, plan_steps, True, [])
                    if reflection["revised_answer"]:
                        final_text = reflection["revised_answer"]

                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model)

                for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
                    yield sse_event(SSEEventType.DELTA, {"text": chunk})

                success, failed_steps = _aggregate_success(
                    None, reflection_result, critical_tool_failures,
                    current_turn_file_success, _requires_file_output(user_message),
                )
                yield sse_event(SSEEventType.DONE, {
                    "iterations": iteration,
                    "success": success,
                    "failed_steps": failed_steps,
                })
                return

        # Out of iterations — force one tool-free wrap-up call so the user gets
        # a real answer (what was done, what's missing) instead of silence.
        messages.append({
            "role": "system",
            "content": (
                "You have used the maximum number of tool iterations. Do not call any more tools. "
                "Summarize for the user, in the user's language: what was accomplished, what remains "
                "unfinished, and any errors encountered. Never claim a file was created or saved "
                "unless a tool already returned ok=true."
            ),
        })
        final_text = ""
        try:
            response = await _chat_with_retry(
                client, model=model, messages=messages,
                temperature=LLM_TEMPERATURE, stream=False,
            )
            final_text = (response.choices[0].message.content or "").strip()
        except Exception:
            pass
        if not final_text or _looks_like_raw_tool_payload(final_text):
            final_text = (
                _file_success_final_text(latest_file_success_result, user_message)
                if current_turn_file_success and latest_file_success_result
                else _max_iterations_fallback_text(user_message)
            )
        if current_turn_file_success and latest_file_success_result and _claims_failure(final_text):
            final_text = _file_success_final_text(latest_file_success_result, user_message)
        if _claims_file_success(final_text) and not current_turn_file_success:
            final_text = (
                _failure_final_text(unresolved_tool_errors)
                if unresolved_tool_errors
                else "รอบคำสั่งนี้ยังไม่มีเครื่องมือที่ยืนยันว่าไฟล์ถูกสร้าง บันทึก และตรวจสอบสำเร็จครับ"
            )

        crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                     content=final_text, iteration=self.max_iterations, model_used=model)
        for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
            yield sse_event(SSEEventType.DELTA, {"text": chunk})
        success, failed_steps = _aggregate_success(
            "max_iterations", reflection_result, critical_tool_failures,
            current_turn_file_success, _requires_file_output(user_message),
        )
        yield sse_event(SSEEventType.DONE, {
            "iterations": self.max_iterations,
            "stopped": "max_iterations",
            "success": success,
            "failed_steps": failed_steps,
        })

    async def _build_plan(self, client, model, user_message: str, history: list[dict]) -> list[str]:
        """PLAN stage: one tool-free LLM call that decomposes the request into a
        short checklist. Failures degrade gracefully to no plan (legacy behavior)."""
        recent = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")][-4:]
        ctx = "\n".join(f"{m['role']}: {str(m['content'])[:300]}" for m in recent)
        user_block = (f"Recent conversation:\n{ctx}\n\n" if ctx else "") + f"Request to plan:\n{user_message}"
        try:
            response = await _chat_with_retry(
                client, model=model,
                messages=[
                    {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_block},
                ],
                temperature=LLM_TEMPERATURE, stream=False,
            )
            return _parse_plan(response.choices[0].message.content or "")
        except Exception:
            return []

    async def _reflect(self, client, model, user_message: str, plan_steps: list[str],
                       draft_answer: str, tools_used: set[str]) -> dict[str, Any]:
        """REFLECT stage: grade the draft answer against the plan + user intent.

        On reflection failure, return complete=False so the loop surfaces the
        problem to the user instead of silently claiming success.
        """
        checklist = "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan_steps))
        user_block = (
            f"User's original request:\n{user_message}\n\n"
            f"Plan checklist:\n{checklist}\n\n"
            f"Tools actually used: {', '.join(sorted(tools_used)) or 'none'}\n\n"
            f"Draft answer to review:\n{draft_answer[:4000]}"
        )
        try:
            response = await _chat_with_retry(
                client, model=model,
                messages=[
                    {"role": "system", "content": _REFLECT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_block},
                ],
                temperature=LLM_TEMPERATURE, stream=False,
            )
            return _parse_reflection(response.choices[0].message.content or "")
        except Exception as e:
            logger.error("Reflection failed: %s", e, exc_info=True)
            return {"complete": False,
                    "missing": [f"Self-review could not run: {type(e).__name__}: {str(e)[:200]}"],
                    "revised_answer": None}

    def _persist_reflection(self, plan_msg, plan_steps: list[str], complete: bool, missing: list[str]) -> None:
        """Update the persisted plan message with the final reflection outcome so
        the checklist + review result survive in conversation history."""
        if plan_msg is None:
            return
        try:
            # Reassign a fresh dict so SQLAlchemy flags the JSONB column dirty.
            plan_msg.tool_result = {
                "steps": plan_steps,
                "reflection": {"complete": complete, "missing": missing},
            }
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _latest_convertible_output_path(self) -> str | None:
        preferred_exts = {".docx", ".pdf", ".csv", ".tsv", ".txt", ".md", ".html", ".json", ".jsonl", ".report", ".summary"}
        return self._latest_output_path_with_exts(preferred_exts)

    def _latest_text_output_path(self) -> str | None:
        preferred_exts = {".md", ".txt", ".html", ".csv", ".tsv", ".json", ".report", ".summary"}
        return self._latest_output_path_with_exts(preferred_exts)

    def _latest_output_path_with_exts(self, preferred_exts: set[str]) -> str | None:
        try:
            messages = (
                self.db.query(AgentMessage)
                .filter(AgentMessage.conversation_id == self.conversation_id)
                .order_by(AgentMessage.created_at.desc())
                .limit(80)
                .all()
            )
        except Exception:
            return None

        for msg in messages:
            result = msg.tool_result
            candidates: list[str] = []
            if isinstance(result, dict):
                for key in ("path", "download_path", "source_path"):
                    value = result.get(key)
                    if isinstance(value, str):
                        candidates.append(value)
                saved_files = result.get("saved_files")
                if isinstance(saved_files, list):
                    for item in saved_files:
                        if isinstance(item, dict) and isinstance(item.get("path"), str):
                            candidates.append(item["path"])
                        elif isinstance(item, str):
                            candidates.append(item)
            for path in candidates:
                clean_path = path.strip()
                if clean_path.startswith(f"jobs/{self.job_id}/"):
                    clean_path = clean_path[len(f"jobs/{self.job_id}/"):]
                if not clean_path.startswith("outputs/"):
                    continue
                if Path(clean_path).suffix.lower() in preferred_exts:
                    return clean_path
        return None

    def _latest_assistant_content_for_pdf(self) -> str | None:
        try:
            messages = (
                self.db.query(AgentMessage)
                .filter(AgentMessage.conversation_id == self.conversation_id)
                .filter(AgentMessage.role == "assistant")
                .order_by(AgentMessage.created_at.desc())
                .limit(20)
                .all()
            )
        except Exception:
            return None
        for msg in messages:
            content = (msg.content or "").strip()
            if len(content) < 120:
                continue
            if msg.tool_calls:
                continue
            sanitized = _sanitize_unverified_file_claims(content)
            if sanitized:
                return sanitized[:80000]
        return None

    async def _run_direct_file_conversion(self, user_message: str, source_path: str) -> AsyncGenerator[str, None]:
        yield sse_event(SSEEventType.THINKING, {"iteration": 1})
        tool_name = "convert_to_xlsx"
        tool_args = {"source_path": source_path}
        call_id = f"call_{uuid4().hex[:12]}"
        tool_call = {
            "id": call_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)},
        }
        crud_msg.add(
            self.db,
            conversation_id=self.conversation_id,
            role="assistant",
            content=None,
            tool_calls=[tool_call],
            iteration=1,
            model_used=self.llm_config.get("model", "gpt-4o-mini"),
        )
        yield sse_event(SSEEventType.TOOL_CALL, {"id": call_id, "name": tool_name, "arguments": tool_args})
        result = await tool_registry.execute(tool_name, tool_args, self.context)
        result = _verify_file_tool_result(self.context, tool_name, result)
        crud_msg.add(
            self.db,
            conversation_id=self.conversation_id,
            role="tool",
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_result=result,
            iteration=1,
        )
        yield sse_event(SSEEventType.TOOL_RESULT, {"id": call_id, "name": tool_name, "result": result})

        if _is_file_write_success(tool_name, result):
            final_text = _file_success_final_text(result, user_message)
        else:
            final_text = _failure_final_text([{"tool": tool_name, "result": result}])
        crud_msg.add(
            self.db,
            conversation_id=self.conversation_id,
            role="assistant",
            content=final_text,
            iteration=1,
            model_used=self.llm_config.get("model", "gpt-4o-mini"),
        )
        for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
            yield sse_event(SSEEventType.DELTA, {"text": chunk})
        yield sse_event(SSEEventType.DONE, {"iterations": 1})

    async def _run_direct_pdf_creation(
        self,
        user_message: str,
        source_path: str | None,
        source_content: str | None,
    ) -> AsyncGenerator[str, None]:
        yield sse_event(SSEEventType.THINKING, {"iteration": 1})
        tool_name = "create_pdf"
        if source_path:
            stem = Path(source_path).stem or "agent_export"
            tool_args = {
                "source_path": source_path,
                "output_path": f"outputs/{stem}.pdf",
                "title": "InsightDOC PDF Export",
            }
        else:
            tool_args = {
                "content": source_content or "",
                "output_path": "outputs/agent_response.pdf",
                "title": "InsightDOC PDF Export",
            }
        call_id = f"call_{uuid4().hex[:12]}"
        tool_call = {
            "id": call_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)},
        }
        crud_msg.add(
            self.db,
            conversation_id=self.conversation_id,
            role="assistant",
            content=None,
            tool_calls=[tool_call],
            iteration=1,
            model_used=self.llm_config.get("model", "gpt-4o-mini"),
        )
        yield sse_event(SSEEventType.TOOL_CALL, {"id": call_id, "name": tool_name, "arguments": tool_args})
        result = await tool_registry.execute(tool_name, tool_args, self.context)
        result = _verify_file_tool_result(self.context, tool_name, result)
        crud_msg.add(
            self.db,
            conversation_id=self.conversation_id,
            role="tool",
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_result=result,
            iteration=1,
        )
        yield sse_event(SSEEventType.TOOL_RESULT, {"id": call_id, "name": tool_name, "result": result})

        if _is_file_write_success(tool_name, result):
            final_text = _file_success_final_text(result, user_message)
        else:
            final_text = _failure_final_text([{"tool": tool_name, "result": result}])
        crud_msg.add(
            self.db,
            conversation_id=self.conversation_id,
            role="assistant",
            content=final_text,
            iteration=1,
            model_used=self.llm_config.get("model", "gpt-4o-mini"),
        )
        for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
            yield sse_event(SSEEventType.DELTA, {"text": chunk})
        yield sse_event(SSEEventType.DONE, {"iterations": 1})

    def _is_summary_request(self, user_message: str) -> bool:
        text = user_message.lower()
        return any(token in text for token in ["สรุป", "รายการ", "เอกสาร", "summary", "summarize", "document", "documents"])

    def _looks_like_schema_answer(self, answer: str, action: dict[str, Any] | None = None) -> bool:
        if action and ("$schema" in action or "properties" in action):
            return True
        text = answer.lower()
        return "json-schema" in text or '"$schema"' in text or '"properties"' in text

    def _fallback_job_summary(self, tool_results: list[dict]) -> str:
        list_result = next((item.get("result", {}) for item in tool_results if item.get("tool") == "list_documents"), {})
        documents = list_result.get("documents", [])
        if not documents:
            return "Job นี้ยังไม่มีเอกสารในระบบ"

        lines = [f"พบเอกสารใน Job นี้ {len(documents)} รายการ"]
        details_by_id = {
            item.get("arguments", {}).get("doc_id"): item.get("result", {})
            for item in tool_results
            if item.get("tool") == "get_document_detail"
        }

        for index, doc in enumerate(documents, start=1):
            detail = details_by_id.get(doc.get("id"), {})
            data = detail.get("reviewed_data") or detail.get("extracted_data") or {}
            if isinstance(data, list) and data:
                data = data[0]
            if not isinstance(data, dict):
                data = {}

            parts = [
                f"{index}. {doc.get('filename')}",
                f"สถานะ {doc.get('status')}",
                f"จำนวนหน้า {doc.get('page_count') or '-'}",
            ]
            quotation_no = data.get("quotationNumber") or data.get("quotation_number")
            quotation_date = data.get("quotationDate") or data.get("quotation_date")
            grand_total = data.get("grandTotal") or data.get("grand_total")
            company = data.get("companyName") or data.get("company_name")
            line_items = data.get("lineItems") or data.get("line_items") or []
            if quotation_no:
                parts.append(f"เลขที่ {quotation_no}")
            if quotation_date:
                parts.append(f"วันที่ {quotation_date}")
            if company:
                parts.append(f"บริษัท {company}")
            if grand_total is not None:
                parts.append(f"ยอดรวม {grand_total}")
            if isinstance(line_items, list):
                parts.append(f"รายการสินค้า/บริการ {len(line_items)} รายการ")
            lines.append("; ".join(parts))

        return "\n".join(lines)

    async def _call_completion_provider(self, prompt: str, system_prompt: str, tool_results: list[dict]) -> str:
        payload = {
            "inputs": {
                "ocr_content": prompt,
                "document_type": "agent",
                "agent_prompt": prompt,
                "system_prompt": system_prompt,
                "tool_results": tool_content_for_llm(tool_results[-5:]),
            },
            "user": str(self.user_id),
            "citation": False,
            "response_mode": "blocking",
        }
        last_exc: Exception | None = None
        for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        self.llm_config["apiUrl"],
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.llm_config['apiKey']}",
                            "Content-Type": "application/json",
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                return str(data.get("answer") or data.get("text") or data.get("output") or "")
            except Exception as e:
                last_exc = e
                if attempt < LLM_MAX_ATTEMPTS:
                    await asyncio.sleep(LLM_RETRY_BASE_DELAY_S * (2 ** (attempt - 1)))
        raise last_exc

    async def _emit_context_tool(self, tool_name: str, tool_args: dict, iteration: int) -> AsyncGenerator[str, None]:
        call_id = f"call_{uuid4().hex[:12]}"
        tool_call = {
            "id": call_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)},
        }
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                     content=None, tool_calls=[tool_call], iteration=iteration,
                     model_used=self.llm_config.get("model", "default_ai_settings"))
        yield sse_event(SSEEventType.TOOL_CALL, {"id": call_id, "name": tool_name, "arguments": tool_args})
        result = await tool_registry.execute(tool_name, tool_args, self.context)
        yield sse_event(SSEEventType.TOOL_RESULT, {"id": call_id, "name": tool_name, "result": result})
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                     tool_call_id=call_id, tool_name=tool_name, tool_result=result, iteration=iteration)
        self._last_context_result = {"tool": tool_name, "arguments": tool_args, "result": result}

    async def _builder_model_text(self, prompt: str, system_prompt: str, tool_results: list[dict]) -> str:
        """One model call for the workflow builder. Provider-agnostic: uses the
        completion-messages endpoint or an OpenAI-compatible chat call, both
        returning plain text that must contain the JSON action object."""
        if self.llm_config.get("provider") == "completion_messages":
            return await self._call_completion_provider(prompt, system_prompt, tool_results)
        client = AsyncOpenAI(
            api_key=self.llm_config.get("apiKey"),
            base_url=self.llm_config.get("baseUrl") or None,
            timeout=LLM_REQUEST_TIMEOUT_S,
            max_retries=0,
        )
        response = await _chat_with_retry(
            client,
            model=self.llm_config.get("model", "gpt-4o-mini"),
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            temperature=LLM_TEMPERATURE,
            stream=False,
        )
        return response.choices[0].message.content or ""

    async def _run_workflow_builder(self, user_message: str) -> AsyncGenerator[str, None]:
        """Dispatch the AI workflow builder by provider capability.

        openai_compatible → native function calling (structured, correctly-escaped
        tool arguments — avoids the fragile free-text-JSON parsing that breaks on
        large definitions with unescaped quotes). completion_messages → JSON contract.
        """
        if self.llm_config.get("provider") == "completion_messages":
            async for event in self._run_workflow_builder_json(user_message):
                yield event
        else:
            async for event in self._run_workflow_builder_native(user_message):
                yield event

    async def _await_with_keepalive(self, coro, interval: float = 12.0):
        """Await `coro` while emitting SSE keepalive comments, so a long silent
        operation (LLM call, etc.) never leaves the stream idle long enough for a
        browser/proxy to drop it ("Load failed"). Yields keepalive strings; the
        awaited result is stored on self._awaited (re-raises if `coro` raised)."""
        task = asyncio.ensure_future(coro)
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if done:
                break
            yield ": keepalive\n\n"
        self._awaited = task.result()

    async def _builder_execute_call(self, call_id: str, tool_name: str, tool_args: dict, iteration: int, model_name: str):
        """Execute one builder tool call (with confirmation gating), emitting SSE
        events. Returns (result, [event...]) is awkward for a generator, so this is
        a generator that yields SSE strings and stores the result on self._last_builder_result."""
        yield sse_event(SSEEventType.TOOL_CALL, {"id": call_id, "name": tool_name, "arguments": tool_args})
        if requires_confirmation(tool_name, tool_args):
            pending = crud_pending.create(
                self.db, conversation_id=self.conversation_id, user_id=self.user_id,
                tool_name=tool_name, tool_arguments=tool_args,
                description=describe_action(tool_name, tool_args),
            )
            yield sse_event(SSEEventType.CONFIRMATION_REQUIRED, {
                "pending_action_id": str(pending.id), "tool_call_id": call_id,
                "tool_name": tool_name, "description": pending.description, "arguments": tool_args,
            })
            # Poll for the user's decision, emitting a keepalive every ~10s so the
            # SSE stream survives however long the user takes to confirm.
            approved = None
            for tick in range(300):
                self.db.rollback()  # end the read txn before sleeping
                action = crud_pending.get(self.db, pending.id)
                if action and action.status == "confirmed":
                    approved = True
                    break
                if action and action.status == "rejected":
                    approved = False
                    break
                if tick % 10 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)
            if approved is None:
                crud_pending.resolve(self.db, pending.id, "rejected")
                approved = False
            if not approved:
                result = {"error": "User rejected action", "tool_name": tool_name}
                yield sse_event(SSEEventType.TOOL_REJECTED, {"id": call_id, "name": tool_name})
            else:
                result = await tool_registry.execute(tool_name, tool_args, self.context)
        else:
            result = await tool_registry.execute(tool_name, tool_args, self.context)
        yield sse_event(SSEEventType.TOOL_RESULT, {"id": call_id, "name": tool_name, "result": result})
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                     tool_call_id=call_id, tool_name=tool_name, tool_result=result, iteration=iteration)
        self._last_builder_result = result

    async def _run_workflow_builder_native(self, user_message: str) -> AsyncGenerator[str, None]:
        """Workflow builder over an OpenAI-compatible provider using NATIVE function
        calling. Falls back to parsing JSON actions from message content if the
        endpoint ignores the tools parameter."""
        model = self.llm_config.get("model", "gpt-4o-mini")
        system_prompt = build_system_prompt(self.context, user_message)
        tools_schema = tool_registry.get_openai_schemas(categories=["workflow", "web"])
        client = AsyncOpenAI(
            api_key=self.llm_config.get("apiKey"),
            base_url=self.llm_config.get("baseUrl") or None,
            timeout=LLM_REQUEST_TIMEOUT_S,
            max_retries=0,
        )
        history = await self.context.load_history()
        messages: list[dict] = [{"role": "system", "content": system_prompt}] + history
        MAX_TOOLS_PER_TURN = 6

        for iteration in range(1, self.max_iterations + 1):
            yield sse_event(SSEEventType.THINKING, {"iteration": iteration})
            try:
                # Keepalive-wrapped so a slow LLM turn (large definition) doesn't
                # leave the SSE stream idle and get dropped mid-run.
                self._awaited = None
                async for ka in self._await_with_keepalive(_chat_with_retry(
                    client, model=model, messages=messages, tools=tools_schema,
                    tool_choice="auto", temperature=LLM_TEMPERATURE, stream=False,
                )):
                    yield ka
                response = self._awaited
            except Exception as e:
                yield sse_event(SSEEventType.ERROR, {"message": f"AI provider error: {str(e)}"})
                return

            msg = response.choices[0].message
            native_calls = list(msg.tool_calls or [])

            if native_calls:
                calls = []
                for tc in native_calls[:MAX_TOOLS_PER_TURN]:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    calls.append((tc.id, tc.function.name, args if isinstance(args, dict) else {}))
                assistant_tcd = _tool_calls_data(msg)
                assistant_content = msg.content
            else:
                # Endpoint may have ignored `tools` and emitted JSON action(s) as text.
                objs = _extract_json_objects(msg.content or "")
                tool_objs = [o for o in objs if o.get("type") == "tool_call" and o.get("tool")][:MAX_TOOLS_PER_TURN]
                if not tool_objs:
                    final_obj = next((o for o in objs if o.get("type") == "final"), None)
                    final_text = str((final_obj or {}).get("answer") or msg.content or "").strip() or "…"
                    crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                                 content=final_text, iteration=iteration, model_used=model)
                    yield sse_event(SSEEventType.DELTA, {"text": final_text})
                    yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                    return
                calls = [(f"call_{uuid4().hex[:12]}", o["tool"],
                          o.get("arguments") if isinstance(o.get("arguments"), dict) else {}) for o in tool_objs]
                assistant_tcd = [{"id": cid, "type": "function",
                                  "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                                 for cid, n, a in calls]
                assistant_content = None

            crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                         content=assistant_content, tool_calls=assistant_tcd,
                         iteration=iteration, model_used=model)
            messages.append({"role": "assistant", "content": assistant_content, "tool_calls": assistant_tcd})

            for call_id, tool_name, tool_args in calls:
                self._last_builder_result = None
                async for event in self._builder_execute_call(call_id, tool_name, tool_args, iteration, model):
                    yield event
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": tool_content_for_llm(self._last_builder_result)})

        final_text = "ยังออกแบบ workflow ไม่เสร็จภายในจำนวนรอบที่กำหนด ลองระบุเป้าหมายให้ชัดเจนขึ้นได้ไหมครับ"
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                     content=final_text, iteration=self.max_iterations, model_used=model)
        yield sse_event(SSEEventType.DELTA, {"text": final_text})
        yield sse_event(SSEEventType.DONE, {"iterations": self.max_iterations, "stopped": "max_iterations"})

    async def _run_workflow_builder_json(self, user_message: str) -> AsyncGenerator[str, None]:
        """Workflow builder for completion_messages providers (no native function
        calling): JSON tool-calling contract parsed from free-text replies."""
        model_name = self.llm_config.get("model", "default_ai_settings")
        system_prompt = build_system_prompt(self.context, user_message)
        tools_schema = tool_registry.get_openai_schemas(categories=["workflow", "web"])

        history = await self.context.load_history()
        history_lines: list[str] = []
        for m in history[:-1]:  # exclude the just-added user message
            role = m.get("role")
            if role == "user":
                history_lines.append(f"USER: {m.get('content') or ''}")
            elif role == "assistant" and m.get("content"):
                history_lines.append(f"ASSISTANT: {m.get('content')}")
        history_text = "\n".join(history_lines[-20:]) or "(none)"

        action_rules = {"type": "tool_call", "tool": "list_node_types", "arguments": {}}
        final_rules = {"type": "final", "answer": "your message or question to the user"}
        base_prompt = f"""{system_prompt}

## Tool Calling Contract
Reply with JSON objects only — no prose, no markdown fences.
To call a tool: {json.dumps(action_rules, ensure_ascii=False)}
To ask the user a question or give a final message: {json.dumps(final_rules, ensure_ascii=False)}
Prefer ONE object per reply. If you must call several tools, output each as its
own JSON object; they run in order. Never mix a "final" object with "tool_call"
objects in the same reply.

## Available Tools
{json.dumps(tools_schema, ensure_ascii=False)}

## Conversation so far
{history_text}

## Current user message
{user_message}
"""

        MAX_TOOLS_PER_TURN = 5
        tool_results: list[dict] = []
        for iteration in range(1, self.max_iterations + 1):
            yield sse_event(SSEEventType.THINKING, {"iteration": iteration})
            prompt = base_prompt
            if tool_results:
                prompt += "\n## Recent Tool Results\n" + tool_content_for_llm(tool_results[-6:])

            try:
                answer = await self._builder_model_text(prompt, system_prompt, tool_results)
            except Exception as e:
                yield sse_event(SSEEventType.ERROR, {"message": f"AI provider error: {str(e)}"})
                return

            # A model may emit several action objects in one reply — parse them all.
            actions = _extract_json_objects(answer)
            tool_actions = [
                a for a in actions
                if a.get("type") == "tool_call" and a.get("tool")
            ][:MAX_TOOLS_PER_TURN]
            final_action = next((a for a in actions if a.get("type") == "final"), None)

            if not tool_actions:
                # No tools requested → this turn is a final message / question.
                # Prefer an explicit final answer; otherwise, only fall back to raw
                # text if it is NOT leftover action JSON (which must never be shown).
                if final_action and final_action.get("answer"):
                    final_text = str(final_action["answer"]).strip()
                elif actions:
                    # Parsed objects but none usable (e.g. malformed tool_call) —
                    # nudge instead of dumping JSON, then retry the loop.
                    tool_results.append({"tool": "__parse_hint", "arguments": {}, "result": {
                        "error": "ตอบกลับไม่ตรงรูปแบบ ให้ส่ง JSON object เดียวตาม contract (tool_call หรือ final)"
                    }})
                    continue
                else:
                    final_text = answer.strip()
                final_text = final_text or "…"
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model_name)
                yield sse_event(SSEEventType.DELTA, {"text": final_text})
                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

            # Execute each requested tool in order within this turn.
            for act in tool_actions:
                tool_name = str(act.get("tool") or "")
                tool_args = act.get("arguments") if isinstance(act.get("arguments"), dict) else {}
                call_id = f"call_{uuid4().hex[:12]}"
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=None,
                             tool_calls=[{"id": call_id, "type": "function",
                                          "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)}}],
                             iteration=iteration, model_used=model_name)
                yield sse_event(SSEEventType.TOOL_CALL, {"id": call_id, "name": tool_name, "arguments": tool_args})

                if requires_confirmation(tool_name, tool_args):
                    pending = crud_pending.create(
                        self.db, conversation_id=self.conversation_id, user_id=self.user_id,
                        tool_name=tool_name, tool_arguments=tool_args,
                        description=describe_action(tool_name, tool_args),
                    )
                    yield sse_event(SSEEventType.CONFIRMATION_REQUIRED, {
                        "pending_action_id": str(pending.id), "tool_call_id": call_id,
                        "tool_name": tool_name, "description": pending.description, "arguments": tool_args,
                    })
                    approved = await self._wait_for_confirmation(pending.id)
                    if not approved:
                        result = {"error": "User rejected action", "tool_name": tool_name}
                        yield sse_event(SSEEventType.TOOL_REJECTED, {"id": call_id, "name": tool_name})
                    else:
                        result = await tool_registry.execute(tool_name, tool_args, self.context)
                else:
                    result = await tool_registry.execute(tool_name, tool_args, self.context)

                yield sse_event(SSEEventType.TOOL_RESULT, {"id": call_id, "name": tool_name, "result": result})
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                             tool_call_id=call_id, tool_name=tool_name, tool_result=result, iteration=iteration)
                tool_results.append({"tool": tool_name, "arguments": tool_args, "result": result})

        final_text = "ยังออกแบบ workflow ไม่เสร็จภายในจำนวนรอบที่กำหนด ลองระบุเป้าหมายให้ชัดเจนขึ้นได้ไหมครับ"
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                     content=final_text, iteration=self.max_iterations, model_used=model_name)
        yield sse_event(SSEEventType.DELTA, {"text": final_text})
        yield sse_event(SSEEventType.DONE, {"iterations": self.max_iterations, "stopped": "max_iterations"})

    async def _run_completion_provider(self, user_message: str) -> AsyncGenerator[str, None]:
        model_name = self.llm_config.get("model", "default_ai_settings")
        system_prompt = build_system_prompt(self.context, user_message)
        tools_schema = tool_registry.get_openai_schemas()
        tool_results: list[dict] = []

        # The system-level provider may not support native function calling. Always
        # preload the current Job context with backend tools so the AI answers from
        # real job data instead of guessing.
        yield sse_event(SSEEventType.THINKING, {"iteration": 0})
        self._last_context_result = None
        async for event in self._emit_context_tool("list_documents", {"status_filter": "all"}, 0):
            yield event
        if self._last_context_result:
            tool_results.append(self._last_context_result)
            docs = self._last_context_result.get("result", {}).get("documents", [])
            for doc in docs[:3]:
                doc_id = doc.get("id")
                if not doc_id:
                    continue
                self._last_context_result = None
                async for event in self._emit_context_tool("get_document_detail", {"doc_id": doc_id}, 0):
                    yield event
                if self._last_context_result:
                    tool_results.append(self._last_context_result)

        action_rules = {
            "type": "tool_call",
            "tool": "list_documents",
            "arguments": {"status_filter": "all"},
        }
        final_rules = {"type": "final", "answer": "your response"}

        base_prompt = f"""{system_prompt}

## Tool Calling Contract
You can process only the current InsightDOC Job by requesting backend tools.
Return exactly one JSON object and no markdown.
To call a tool, return: {json.dumps(action_rules, ensure_ascii=False)}
To answer the user, return: {json.dumps(final_rules, ensure_ascii=False)}
The backend already preloaded current job documents in Recent Tool Results.
Do not invent document data. Use tool results as source of truth.
If more information or an action is needed, request one tool_call JSON object.
When a report tool such as run_report_code succeeds, final answers must be short: say what was created, provide the outputs/ path, and do not include code, tool arguments, OCR text, or raw JSON.

## Available Tools
{json.dumps(tools_schema, ensure_ascii=False)}

## User Request
{user_message}
"""

        for iteration in range(1, self.max_iterations + 1):
            yield sse_event(SSEEventType.THINKING, {"iteration": iteration})
            if tool_results:
                prompt = base_prompt + "\n## Recent Tool Results\n" + tool_content_for_llm(tool_results[-5:])
            else:
                prompt = base_prompt

            try:
                answer = await self._call_completion_provider(prompt, system_prompt, tool_results)
            except Exception as e:
                yield sse_event(SSEEventType.ERROR, {"message": f"AI provider error: {str(e)}"})
                return

            action = _extract_json_object(answer)
            if self._is_summary_request(user_message) and self._looks_like_schema_answer(answer, action):
                final_text = self._fallback_job_summary(tool_results)
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model_name)
                for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
                    yield sse_event(SSEEventType.DELTA, {"text": chunk})
                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

            if not action:
                report_result = _latest_successful_report(tool_results)
                final_text = answer.strip() or "AI provider returned an empty response."
                if _looks_like_raw_tool_payload(final_text):
                    final_text = _short_report_final_text(report_result, user_message) if report_result else _raw_tool_payload_failure_text(user_message)
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model_name)
                for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
                    yield sse_event(SSEEventType.DELTA, {"text": chunk})
                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

            if action.get("type") == "final":
                report_result = _latest_successful_report(tool_results)
                final_text = str(action.get("answer") or "")
                if _looks_like_raw_tool_payload(final_text):
                    final_text = _short_report_final_text(report_result, user_message) if report_result else _raw_tool_payload_failure_text(user_message)
                elif report_result and len(final_text) > 1200:
                    final_text = _short_report_final_text(report_result, user_message)
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model_name)
                for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
                    yield sse_event(SSEEventType.DELTA, {"text": chunk})
                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

            if action.get("type") != "tool_call":
                report_result = _latest_successful_report(tool_results)
                final_text = str(action.get("answer") or answer)
                if _looks_like_raw_tool_payload(final_text):
                    final_text = _short_report_final_text(report_result, user_message) if report_result else _raw_tool_payload_failure_text(user_message)
                elif report_result and len(final_text) > 1200:
                    final_text = _short_report_final_text(report_result, user_message)
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model_name)
                yield sse_event(SSEEventType.DELTA, {"text": final_text})
                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

            tool_name = str(action.get("tool") or "")
            tool_args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            call_id = f"call_{uuid4().hex[:12]}"
            tool_call = {
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)},
            }
            crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                         content=None, tool_calls=[tool_call], iteration=iteration, model_used=model_name)
            yield sse_event(SSEEventType.TOOL_CALL, {"id": call_id, "name": tool_name, "arguments": tool_args})

            if requires_confirmation(tool_name, tool_args):
                pending = crud_pending.create(
                    self.db, conversation_id=self.conversation_id, user_id=self.user_id,
                    tool_name=tool_name, tool_arguments=tool_args,
                    description=describe_action(tool_name, tool_args),
                )
                yield sse_event(SSEEventType.CONFIRMATION_REQUIRED, {
                    "pending_action_id": str(pending.id),
                    "tool_call_id": call_id,
                    "tool_name": tool_name,
                    "description": pending.description,
                    "arguments": tool_args,
                })
                approved = await self._wait_for_confirmation(pending.id)
                if not approved:
                    result = {"error": "User rejected action", "tool_name": tool_name}
                    yield sse_event(SSEEventType.TOOL_REJECTED, {"id": call_id, "name": tool_name})
                else:
                    result = await tool_registry.execute(tool_name, tool_args, self.context)
                    result = _verify_file_tool_result(self.context, tool_name, result)
                    log_activity(
                        self.db, user_id=self.user_id,
                        action=f"agent_tool_{tool_name}",
                        resource_type="agent_conversation",
                        resource_id=self.conversation_id,
                        details={"tool_name": tool_name, "arguments": tool_args, "agent_initiated": True},
                    )
            else:
                result = await tool_registry.execute(tool_name, tool_args, self.context)
                result = _verify_file_tool_result(self.context, tool_name, result)

            yield sse_event(SSEEventType.TOOL_RESULT, {"id": call_id, "name": tool_name, "result": result})
            crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                         tool_call_id=call_id, tool_name=tool_name,
                         tool_result=result, iteration=iteration)
            tool_results.append({"tool": tool_name, "arguments": tool_args, "result": result})
            if _is_report_success(tool_name, result):
                tool_results.append({"tool": "__report_final_hint", "arguments": {}, "result": {"message": _short_report_final_text(result, user_message)}})

        final_text = _max_iterations_fallback_text(user_message)
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                     content=final_text, iteration=self.max_iterations, model_used=model_name)
        yield sse_event(SSEEventType.DELTA, {"text": final_text})
        yield sse_event(SSEEventType.DONE, {"iterations": self.max_iterations, "stopped": "max_iterations"})

    async def _wait_for_confirmation(self, pending_id: UUID, timeout_s: int = 300) -> bool:
        for _ in range(timeout_s):
            # End the read transaction before sleeping so the session does
            # not sit idle-in-transaction on a pooled connection all night.
            self.db.rollback()
            await asyncio.sleep(1)
            self.db.expire_all()
            action = crud_pending.get(self.db, pending_id)
            if action and action.status == "confirmed":
                return True
            if action and action.status == "rejected":
                return False
        crud_pending.resolve(self.db, pending_id, "rejected")
        return False
