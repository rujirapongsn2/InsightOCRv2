from uuid import UUID
import json
import re
from sqlalchemy.orm import Session
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_memory import agent_memory as crud_memory
from app.crud.crud_agent_skill import agent_skill as crud_skill


_CROSS_DOCUMENT_SKILL_NAME = "cross-document-html-report"
_CONTRACT_SKILL_NAME = "contract-comparison-html-report"
_CROSS_DOCUMENT_QUERY_HINTS = (
    "ระหว่างเอกสาร",
    "ข้ามเอกสาร",
    "เปรียบเทียบ",
    "วิเคราะห์ข้อมูล",
    "รายงานความไม่ถูกต้อง",
    "ความไม่ถูกต้อง",
    "ไม่สอดคล้อง",
    "ผิดปกติ",
    "cross document",
    "cross-document",
    "compare documents",
    "validation report",
    "html report",
)
_CONTRACT_QUERY_HINTS = (
    "สัญญา",
    "วิเคราะห์สัญญา",
    "เปรียบเทียบสัญญา",
    "ต่ออายุสัญญา",
    "ฉบับเก่า",
    "ฉบับใหม่",
    "เวอร์ชันสัญญา",
    "ความเสี่ยงทางกฎหมาย",
    "ถูกต้องตามกฎหมาย",
    "contract",
    "agreement",
    "renewal",
    "amendment",
    "legal risk",
    "version comparison",
)


def _skill_search_text(skill) -> str:
    parts = [
        getattr(skill, "name", "") or "",
        getattr(skill, "description", "") or "",
        getattr(skill, "trigger_hint", "") or "",
    ]
    return " ".join(parts).lower()


def _query_terms(query: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[a-z0-9][a-z0-9_-]{2,}|[฀-๿]{4,}", query.lower())
        if term
    ]


def _skill_matches_query(skill, query: str) -> bool:
    if not query:
        return True

    query_lower = query.lower()
    search_text = _skill_search_text(skill)

    if query_lower in search_text or search_text in query_lower:
        return True

    if getattr(skill, "name", "") == _CROSS_DOCUMENT_SKILL_NAME:
        return any(hint in query_lower for hint in _CROSS_DOCUMENT_QUERY_HINTS)

    if getattr(skill, "name", "") == _CONTRACT_SKILL_NAME:
        return any(hint in query_lower for hint in _CONTRACT_QUERY_HINTS)

    return any(term in search_text for term in _query_terms(query_lower))


class AgentContext:
    def __init__(self, db: Session, user_id: UUID, job_id: UUID, conversation_id: UUID):
        self.db = db
        self.user_id = user_id
        self.job_id = job_id
        self.conversation_id = conversation_id

    async def load_history(self, limit: int = 20) -> list[dict]:
        messages = crud_conv.get_messages(self.db, self.conversation_id, limit=limit)
        history = []
        for m in messages:
            if m.role == "user":
                history.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                entry = {"role": "assistant", "content": m.content}
                if m.tool_calls:
                    entry["tool_calls"] = m.tool_calls
                history.append(entry)
            elif m.role == "tool":
                history.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id,
                    "content": m.tool_result if isinstance(m.tool_result, str) else json.dumps(m.tool_result, ensure_ascii=False, default=str),
                })
        return history

    def recall_relevant_memories(self, query: str, limit: int = 10) -> list:
        return crud_memory.search(self.db, user_id=self.user_id, job_id=self.job_id, query=query, limit=limit)

    def list_relevant_skills(self, query: str, limit: int = 5) -> list:
        """Stage 1 progressive disclosure: return skill metadata only (name + description).

        Full procedures are loaded on demand via execute_skill tool (Stage 2).
        """
        skills = crud_skill.list_by_user(self.db, user_id=self.user_id, include_system=True)
        if query:
            skills = [s for s in skills if _skill_matches_query(s, query)]
        return skills[:limit]

    def get_skill_by_name(self, name: str) -> object | None:
        """Get a specific skill by name (user scope first, then system)."""
        skill = crud_skill.get_by_name(self.db, user_id=self.user_id, name=name, scope="user")
        if not skill:
            skill = crud_skill.get_by_name(self.db, user_id=None, name=name, scope="system")
        return skill


def build_system_prompt(context: AgentContext, user_message: str) -> str:
    memories = context.recall_relevant_memories(user_message, limit=10)
    skills = context.list_relevant_skills(user_message, limit=5)

    memory_section = ""
    if memories:
        lines = ["## Relevant Memories"]
        for m in memories:
            lines.append(f"- [{m.scope}/{m.key}]: {m.content}")
        memory_section = "\n".join(lines)

    # Stage 1 progressive disclosure: only name + description (~100 tokens each)
    skills_section = ""
    if skills:
        lines = ["## Available Skills (Stage 1 — use execute_skill for full procedure)"]
        for s in skills:
            hint = f" | trigger: {s.trigger_hint}" if s.trigger_hint else ""
            lines.append(f"- **{s.name}** [{s.scope}]: {s.description}{hint}")
        lines.append("If a skill matches the current task, you must call execute_skill(name=...) before solving so the full procedure is loaded.")
        skills_section = "\n".join(lines)

    return f"""You are Agent DOC, an Agentic Document Management assistant inside InsightDOC.

## Mission
Help users understand, validate, correct, enrich, approve, route, and export documents inside the current Job. You are not a schema generator unless the user explicitly asks to design a schema.

## Current Scope
- Job ID: {context.job_id}
- User ID: {context.user_id}
- You may only access data for the current Job through tools.

{memory_section}

{skills_section}

## Core Workflow
1. Observe: use `list_documents` first, then `get_document_detail` for relevant documents.
2. Reason: compare OCR text, extracted_data, reviewed_data, confidence, statuses, and user intent.
3. Act: use tools for document updates, approvals/rejections, files, integrations, memory, skills, web search, or code sandbox.
4. Verify: after write/action tools, read back or summarize the result.
5. Report: answer in the user's language with concise evidence, filenames, fields, and any uncertainty.

## Tool Guidance
- Document tools are the source of truth for uploaded documents. Never invent document values.
- Use `create_docx` when the user asks for a Word/.docx quotation, report, letter, or draft. Only say the file was created after `create_docx` or `write_file` returns `ok=true` with a path.
- Use `run_report_code` for AI-generated HTML reports because it performs syntax checks, sandbox execution, result validation, and safe file writing. Use raw `execute_python` only for calculations, table normalization, CSV/Excel generation, validation scripts, or non-report transformations. If a Python package is missing, retry with `_pip_install(...)` or switch to a more specific tool such as `create_docx`.
- Use filesystem tools to read/write reports and generated artifacts under the Job scope. If any tool returns `error`, report or fix that error before claiming success.
- Use memory tools for durable user/job preferences only when helpful. Memories are hints, not source of truth.
- Use skill tools when a reusable procedure is relevant; load full procedures with `execute_skill`.
- Use `web_search` only for external context such as public product/vendor/regulatory information. Cite URLs when relying on web results.
- Use integration tools only after checking available integrations.

## Safety and Governance
- Destructive or externally visible actions require confirmation; the system gates these tools.
- Never bypass tenant isolation, confirmation gates, or integration access checks.
- Prefer reviewed_data over extracted_data when both exist. Mention when OCR/extraction appears inconsistent.
- Do not output JSON Schema unless the user explicitly requests a schema.
- For document QA questions, answer directly from tool results and include filename evidence.
- If data is missing or ambiguous, say what is missing and propose the next tool/action.

## Response Style
- Same language as the user.
- For totals/items, use clear bullets or a compact table.
- Include follow-up actions only when they are useful for document management.
- After completing a complex workflow, suggest saving it as a skill with `create_skill`.
"""
