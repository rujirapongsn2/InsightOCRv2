from uuid import UUID
import json
import re
from sqlalchemy.orm import Session
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_memory import agent_memory as crud_memory
from app.crud.crud_agent_skill import agent_skill as crud_skill

# Cap on how much of a tool result is fed back to the LLM. Full results stay in
# the DB; only the model-facing copy is truncated so giant OCR payloads don't
# blow the context window or drown the model in noise.
TOOL_RESULT_MAX_CHARS = 12000


def _looks_like_prior_file_claim(content: str | None) -> bool:
    lowered = (content or "").lower()
    if not lowered:
        return False
    has_file_ref = "outputs/" in lowered or any(ext in lowered for ext in [".csv", ".docx", ".md", ".pdf", ".pptx", ".xlsx"])
    has_claim = any(token in lowered for token in [
        "ไฟล์", "ดาวน์โหลด", "สร้างเสร็จ", "บันทึก", "ตรวจสอบไฟล์", "มีอยู่แล้ว",
        "created", "generated", "saved", "download", "verified",
    ])
    return has_file_ref and has_claim


def tool_content_for_llm(result) -> str:
    """Serialize a tool result for the LLM, truncating oversized payloads."""
    content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    if len(content) > TOOL_RESULT_MAX_CHARS:
        omitted = len(content) - TOOL_RESULT_MAX_CHARS
        content = (
            content[:TOOL_RESULT_MAX_CHARS]
            + f'... [truncated {omitted} chars — make a narrower tool call (e.g. one document, a filter, or a limit) if you need the rest]'
        )
    return content


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
    def __init__(self, db: Session, user_id: UUID, job_id: UUID | None, conversation_id: UUID, kind: str = "document"):
        self.db = db
        self.user_id = user_id
        self.job_id = job_id
        self.conversation_id = conversation_id
        self.kind = kind

    async def load_history(self, limit: int = 20) -> list[dict]:
        messages = crud_conv.get_messages(self.db, self.conversation_id, limit=limit)
        history = []
        for m in messages:
            if m.role == "user":
                history.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                if _looks_like_prior_file_claim(m.content) and not m.tool_calls:
                    history.append({
                        "role": "assistant",
                        "content": "[Previous assistant file/download claim omitted. File creation must be verified by a current-turn tool result.]",
                    })
                    continue
                entry = {"role": "assistant", "content": m.content}
                if m.tool_calls:
                    entry["tool_calls"] = m.tool_calls
                history.append(entry)
            elif m.role == "tool":
                history.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id,
                    "content": tool_content_for_llm(m.tool_result),
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


def _resolve_builder_default_provider(db):
    """The AI provider llm nodes should default to: the workflow-builder provider,
    else the agent provider, else the active default — so the builder never has to
    ask the user which model to use."""
    from app.models.ai_settings import AISettings
    for flt in (
        (AISettings.is_workflow_builder_provider == True,),  # noqa: E712
        (AISettings.is_agent_provider == True,),             # noqa: E712
        (AISettings.is_default == True,),                    # noqa: E712
        tuple(),
    ):
        q = db.query(AISettings).filter(AISettings.is_active == True)  # noqa: E712
        for cond in flt:
            q = q.filter(cond)
        row = q.first()
        if row:
            return row
    return None


def build_workflow_builder_prompt(context: AgentContext) -> str:
    """System prompt for the non-job-scoped AI workflow builder (Agent FLOW)."""
    provider = _resolve_builder_default_provider(context.db)
    if provider:
        provider_section = (
            f'The default AI provider for `llm` nodes is already configured: '
            f'ai_provider_id = "{provider.id}" ({provider.display_name or provider.name}). '
            f'Set this ai_provider_id on every `llm` node automatically. '
            f'DO NOT ask the user which AI/model/provider to use — it is already chosen.'
        )
    else:
        provider_section = (
            'No AI provider is configured yet. Leave `llm` nodes\' ai_provider_id blank '
            '(the system default will be used) and DO NOT ask the user which model to use.'
        )
    return f"""You are Agent FLOW, a no-code workflow builder inside InsightDOC.
Your user may not be technical. Design a runnable automation workflow from their goal.

## User
- User ID: {context.user_id}
- You are NOT tied to a single Job. Use tools to discover what the user has.

## AI provider for llm nodes (do not ask about this)
{provider_section}

## How to work (in order)
1. Understand the goal in the user's own words. If a BUSINESS requirement is
   ambiguous (which Job, which fields, output filename, manual vs schedule
   trigger), ASK a short question with concrete options — never guess. But do
   NOT ask about the AI model/provider — it is already configured (see above).
2. Discover resources before wiring: call `list_node_types` (valid node types +
   required config), `list_jobs`, `list_document_schemas`, `list_integrations`,
   `list_ai_providers` as needed.
3. For any node that reads a Job (job_source / document_source / *_import), call
   `inspect_job_data(job_id)` first and wire templates ({{node_id.records.0.field}})
   to fields that ACTUALLY exist. Never invent field names.
4. Build the definition as a DAG: nodes = [{{id, type, position:{{x,y}}, data:{{label, config}}}}],
   edges = [{{id, source, target, sourceHandle?}}]. Put ALL node config under data.config.
   Exactly one trigger node (trigger_manual unless the user wants schedule/webhook).
   For condition branches, set edge sourceHandle to "true"/"false".
5. Call `propose_workflow(name, description, definition)` to show the live preview,
   then `validate_workflow(definition)`. Fix every error and re-validate until clean.
6. If a node needs an API key/token or a cloud account you don't have, call
   `request_credential(kind, purpose, node_ref)`. This opens a secure card for the
   user to enter the key — the key is saved directly and never passes through chat.
   After calling it, STOP and wait; the created integration_id/ai_provider_id will
   arrive as the next user message. Then set it on the node and continue.
   NEVER ask the user to paste an API key into the chat.
7. Only when `validate_workflow` returns no errors, call `save_workflow`. It will
   ask the user to confirm. Only AFTER save_workflow returns ok may you tell the
   user the workflow was created (include its name). If validation fails, fix and retry.

## Rules
- Reply in the user's language (Thai by default). Keep questions short with clear options.
- Reference only jobs/integrations/providers returned by the list tools (by id).
- Do not claim success before save_workflow returns ok=true.
"""


def build_system_prompt(context: AgentContext, user_message: str) -> str:
    if getattr(context, "kind", "document") == "workflow_builder":
        return build_workflow_builder_prompt(context)

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
- Use `run_report_code` for AI-generated HTML reports because it performs syntax checks, sandbox execution, result validation, and safe file writing. Use raw `execute_python` only for calculations, table normalization, CSV/Excel generation, PDF creation, validation scripts, or non-report transformations.
- Use `create_pdf` when the user asks to create/convert the latest answer, report, Markdown table, or saved text-like output to PDF. Prefer this deterministic PDF tool over raw `execute_python`.
- Use `convert_to_xlsx` when the user asks to convert an existing saved output/report/Word/PDF/CSV/text file to Excel. Prefer this deterministic conversion tool over `read_file` + `execute_python`.
- The sandbox image preinstalls common document/data packages: `fpdf2`, `reportlab`, `requests`, `openpyxl`, `xlsxwriter`, `pandas`, `python-docx`, `pypdf`, `pillow`, and `xlrd`. CSV uses Python's built-in `csv` module. If a package is missing, call `_pip_install('pkg1 pkg2')`; NEVER call subprocess or os.system pip directly (the sandbox filesystem is read-only; only /tmp is writable).
- For Excel output: use `openpyxl` or `xlsxwriter`, save to `/tmp/<name>.xlsx`, then call `_save_file('/tmp/<name>.xlsx')` and pass the returned base64 to `write_file`.
- For editing an existing Excel/PDF/DOCX output: first call `read_file(path='outputs/name.xlsx', return_base64=true)`, pass that base64 into `execute_python`, decode it to `/tmp/input.xlsx` or `BytesIO`, modify it, save a new `/tmp/output.xlsx`, then call `_save_file('/tmp/output.xlsx')` and `write_file`. Never read an old `/tmp/...` path from a previous tool call; every execute_python run is a fresh ephemeral container.
- For CSV output: use Python's built-in `csv` module, encode as UTF-8, save to `/tmp/<name>.csv`, then call `_save_file('/tmp/<name>.csv')` or write text directly with `write_file`.
- For custom PDF output with Thai text only when `create_pdf` is insufficient: use `execute_python`, `fpdf2`, and `_thai_font_path()` to load a Thai-capable font already present in the sandbox. Template:
```python
from fpdf import FPDF
font_path = _thai_font_path()
pdf = FPDF(); pdf.add_page()
pdf.add_font('Thai', '', font_path)
pdf.set_font('Thai', size=14)
pdf.cell(0, 10, 'ข้อความภาษาไทย')
pdf.output('/tmp/output.pdf')
result = _save_file('/tmp/output.pdf')
```
- For PDF output: do NOT attempt to convert an existing docx to pdf (no conversion tool is available in the sandbox).
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
