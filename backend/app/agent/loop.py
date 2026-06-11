"""
Agent Loop — multi-turn tool calling with streaming.

Optimizations (Phase 6):
  - System prompt sent only once (saves tokens across iterations)
  - Parallel tool execution via asyncio.gather when no confirmation needed
"""
import json
import asyncio
import re
from typing import AsyncGenerator, Any
from uuid import UUID, uuid4
from types import SimpleNamespace
from sqlalchemy.orm import Session
from openai import AsyncOpenAI
import httpx

from app.agent.context import AgentContext, build_system_prompt
from app.agent.events import sse_event, SSEEventType
from app.agent.confirmations import requires_confirmation, describe_action
from app.agent.tools.registry import tool_registry
from app.agent.tools import document_tools, integration_tools, memory_tools, code_tools, skill_tools, filesystem_tools, web_search_tools  # noqa: F401 — side-effect: registers tools
from app.crud.crud_agent_message import agent_message as crud_msg
from app.crud.crud_agent_pending import agent_pending as crud_pending
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.utils.activity_logger import log_activity


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




def _tool_failed(result: Any) -> bool:
    return isinstance(result, dict) and ("error" in result or result.get("ok") is False)


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
    return tool_name in {"write_file", "create_docx", "run_report_code"} and isinstance(result, dict) and result.get("ok") is True and bool(result.get("path"))


def _is_report_success(tool_name: str, result: Any) -> bool:
    return tool_name == "run_report_code" and isinstance(result, dict) and result.get("ok") is True and bool(result.get("path"))


def _looks_like_raw_tool_payload(text: str | None) -> bool:
    stripped = (text or "").strip()
    if not stripped.startswith("{") or len(stripped) < 20:
        return False
    lowered = stripped.lower()
    return "tool_calls" in lowered or "run_report_code" in lowered or '"type":"tool_call"' in lowered or '"type": "tool_call"' in lowered


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
    return any(token in lowered for token in [
        "เรียบร้อย", "บันทึก", "สร้างไฟล์", "ทำไฟล์", "saved", "created", "generated", "download", ".docx", "outputs/",
    ])


def _requires_web_search(user_message: str) -> bool:
    text = (user_message or "").lower()
    return any(token in text for token in [
        "ค้น", "หาข้อมูล", "จากเว็บ", "เว็บไซต์", "www.", "http://", "https://",
        "softnix.co.th", "web search", "search web", "internet",
    ])


def _requires_file_output(user_message: str) -> bool:
    text = (user_message or "").lower()
    file_tokens = ["ไฟล์", "docx", "word", "ใบเสนอราคา", "quotation", "บันทึก"]
    action_tokens = ["สร้าง", "ทำ", "เขียน", "แก้", "แก้ไข", "เพิ่ม", "อัปเดต", "update", "export", "save"]
    return any(token in text for token in file_tokens) and any(token in text for token in action_tokens)


def _required_tool_instruction(kind: str) -> str:
    if kind == "web_search":
        return (
            "The user's current request explicitly requires external web research. "
            "Call web_search in this same turn before answering or creating/updating files. "
            "Use the returned URLs/snippets as evidence and do not answer from memory alone."
        )
    return (
        "The user's current request asks to create or update a Word/file artifact. "
        "Call create_docx or write_file in this same turn and only give the file name after the tool returns ok=true. "
        "Do not reuse an older file-success result from conversation history."
    )


def _tool_failure_instruction(tool_name: str, result: Any) -> str:
    return (
        "A tool just failed. You must either fix the problem with another appropriate tool call, "
        "or clearly tell the user the action failed. Do not claim that any file was created or saved "
        f"unless a later write_file or create_docx tool returns ok=true. Failure: {_tool_error_summary(tool_name, result)}"
    )


def _failure_final_text(tool_errors: list[dict[str, Any]]) -> str:
    last = tool_errors[-1]
    return (
        "ยังดำเนินการไม่สำเร็จครับ: "
        f"{_tool_error_summary(last.get('tool', 'tool'), last.get('result'))}. "
        "ผมยังไม่พบผลลัพธ์จากเครื่องมือที่ยืนยันว่าไฟล์ถูกสร้างหรือบันทึกสำเร็จ"
    )

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

    def __init__(self, db: Session, conversation_id: UUID, user_id: UUID, job_id: UUID, llm_config: dict, max_iterations: int = 15):
        self.db = db
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.job_id = job_id
        self.llm_config = llm_config
        self.max_iterations = max_iterations
        self.context = AgentContext(db=db, user_id=user_id, job_id=job_id, conversation_id=conversation_id)

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="user", content=user_message, iteration=0)
        crud_conv.update_title(self.db, self.conversation_id, user_message[:60])

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
        latest_report_success: dict[str, Any] | None = None
        unresolved_tool_errors: list[dict[str, Any]] = []
        current_turn_tools: set[str] = set()
        current_turn_file_success = False
        nudged_required_search = False
        nudged_required_file = False

        for iteration in range(1, self.max_iterations + 1):
            yield sse_event(SSEEventType.THINKING, {"iteration": iteration})

            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice="auto",
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
                                log_activity(
                                    self.db, user_id=self.user_id,
                                    action=f"agent_tool_{tool_name}",
                                    resource_type="agent_conversation",
                                    resource_id=self.conversation_id,
                                    details={"tool_name": tool_name, "arguments": tool_args, "agent_initiated": True},
                                )
                        else:
                            result = await tool_registry.execute(tool_name, tool_args, self.context)

                        yield sse_event(SSEEventType.TOOL_RESULT, {"id": tc.id, "name": tool_name, "result": result})
                        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                                     tool_call_id=tc.id, tool_name=tool_name,
                                     tool_result=result, iteration=iteration)
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })
                        tool_events_seen += 1
                        current_turn_tools.add(tool_name)
                        if _is_file_write_success(tool_name, result):
                            current_turn_file_success = True
                        if _is_report_success(tool_name, result):
                            latest_report_success = result
                        if _tool_failed(result):
                            latest_tool_error_index = tool_events_seen
                            unresolved_tool_errors.append({"tool": tool_name, "result": result})
                            messages.append({"role": "system", "content": _tool_failure_instruction(tool_name, result)})
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
                        yield sse_event(SSEEventType.TOOL_RESULT, {"id": tc.id, "name": tool_name, "result": result})
                        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                                     tool_call_id=tc.id, tool_name=tool_name,
                                     tool_result=result, iteration=iteration)
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })
                        tool_events_seen += 1
                        current_turn_tools.add(tool_name)
                        if _is_file_write_success(tool_name, result):
                            current_turn_file_success = True
                        if _is_report_success(tool_name, result):
                            latest_report_success = result
                        if _tool_failed(result):
                            latest_tool_error_index = tool_events_seen
                            unresolved_tool_errors.append({"tool": tool_name, "result": result})
                            messages.append({"role": "system", "content": _tool_failure_instruction(tool_name, result)})
                        elif _is_file_write_success(tool_name, result):
                            latest_file_success_index = tool_events_seen
                            unresolved_tool_errors.clear()

            else:
                final_text = msg.content or ""
                if latest_report_success and (_looks_like_raw_tool_payload(final_text) or len(final_text) > 800):
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
                    final_text = "ยังไม่ได้สร้างหรือแก้ไขไฟล์ในรอบคำสั่งนี้ครับ เพราะยังไม่มีผลลัพธ์จาก create_docx หรือ write_file ที่ยืนยันว่า ok=true"
                if (
                    latest_tool_error_index > latest_file_success_index
                    and unresolved_tool_errors
                    and _claims_file_success(final_text)
                ):
                    final_text = _failure_final_text(unresolved_tool_errors)

                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model)

                for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
                    yield sse_event(SSEEventType.DELTA, {"text": chunk})

                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

        yield sse_event(SSEEventType.DONE, {"iterations": self.max_iterations, "stopped": "max_iterations"})

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
                "tool_results": json.dumps(tool_results[-5:], ensure_ascii=False, default=str),
            },
            "user": str(self.user_id),
            "citation": False,
            "response_mode": "blocking",
        }
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
                prompt = base_prompt + "\n## Recent Tool Results\n" + json.dumps(tool_results[-5:], ensure_ascii=False, default=str)
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
                if report_result and _looks_like_raw_tool_payload(final_text):
                    final_text = _short_report_final_text(report_result, user_message)
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model_name)
                for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
                    yield sse_event(SSEEventType.DELTA, {"text": chunk})
                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

            if action.get("type") == "final":
                report_result = _latest_successful_report(tool_results)
                final_text = str(action.get("answer") or "")
                if report_result and (_looks_like_raw_tool_payload(final_text) or len(final_text) > 1200):
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
                if report_result and (_looks_like_raw_tool_payload(final_text) or len(final_text) > 1200):
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
                    log_activity(
                        self.db, user_id=self.user_id,
                        action=f"agent_tool_{tool_name}",
                        resource_type="agent_conversation",
                        resource_id=self.conversation_id,
                        details={"tool_name": tool_name, "arguments": tool_args, "agent_initiated": True},
                    )
            else:
                result = await tool_registry.execute(tool_name, tool_args, self.context)

            yield sse_event(SSEEventType.TOOL_RESULT, {"id": call_id, "name": tool_name, "result": result})
            crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                         tool_call_id=call_id, tool_name=tool_name,
                         tool_result=result, iteration=iteration)
            tool_results.append({"tool": tool_name, "arguments": tool_args, "result": result})
            if _is_report_success(tool_name, result):
                tool_results.append({"tool": "__report_final_hint", "arguments": {}, "result": {"message": _short_report_final_text(result, user_message)}})

        final_text = "Stopped after reaching the maximum agent iterations."
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                     content=final_text, iteration=self.max_iterations, model_used=model_name)
        yield sse_event(SSEEventType.DELTA, {"text": final_text})
        yield sse_event(SSEEventType.DONE, {"iterations": self.max_iterations, "stopped": "max_iterations"})

    async def _wait_for_confirmation(self, pending_id: UUID, timeout_s: int = 300) -> bool:
        for _ in range(timeout_s):
            await asyncio.sleep(1)
            self.db.expire_all()
            action = crud_pending.get(self.db, pending_id)
            if action and action.status == "confirmed":
                return True
            if action and action.status == "rejected":
                return False
        crud_pending.resolve(self.db, pending_id, "rejected")
        return False
