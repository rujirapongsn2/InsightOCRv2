import ast
import base64
import io
from pathlib import Path

from app.agent.tools.filesystem_tools import MAX_FILE_SIZE_WRITE, _normalize_job_path, _resolve_path, verify_saved_file
from app.agent.tools.registry import ToolDef, tool_registry
from app.services.code_sandbox import execute_python
from app.services.storage import get_storage_service


MAX_REPORT_CODE_LENGTH = 120_000
MAX_REPORT_HTML_LENGTH = 5_000_000
MAX_PDF_SOURCE_CHARS = 80_000


def _normalize_output_file_path(filename: str) -> str:
    cleaned = Path(filename or "output.bin").name.strip() or "output.bin"
    return f"outputs/{cleaned}"


def _persist_execution_files(execution: dict, context) -> dict:
    files = execution.get("files") if isinstance(execution, dict) else None
    if not isinstance(files, list) or not files:
        return execution

    storage = get_storage_service()
    saved_files: list[dict] = []
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        filename = Path(str(file_info.get("filename") or file_info.get("path") or "output.bin")).name
        encoded = file_info.get("base64")
        if not filename or not isinstance(encoded, str) or not encoded:
            continue
        try:
            data = base64.b64decode(encoded)
        except Exception as e:
            return {"error": f"Generated file has invalid base64: {str(e)}", "execution": execution}
        if len(data) > MAX_FILE_SIZE_WRITE:
            return {"error": f"Generated file too large ({len(data)} bytes, max {MAX_FILE_SIZE_WRITE})", "execution": execution}

        output_path = _normalize_output_file_path(filename)
        try:
            scoped = _resolve_path(str(context.job_id), output_path)
        except ValueError as e:
            return {"error": str(e), "execution": execution}

        content_type = file_info.get("mime_type") or "application/octet-stream"
        storage.upload_file(io.BytesIO(data), scoped, content_type=content_type)
        verification = verify_saved_file(str(context.job_id), output_path, expected_size=len(data))
        if verification.get("ok") is not True:
            return {"error": verification.get("error") or "Generated file verification failed", "execution": execution}
        saved_files.append({
            "path": output_path,
            "filename": filename,
            "size": len(data),
            "mime_type": verification.get("mime_type") or content_type,
            "verified": True,
            "auto_captured": bool(file_info.get("auto_captured")),
        })

    if not saved_files:
        return execution

    persisted = dict(execution)
    persisted.pop("files", None)
    persisted.pop("stdout", None)
    if isinstance(persisted.get("result"), dict):
        result_summary = dict(persisted["result"])
        result_summary.pop("base64", None)
        persisted["result"] = result_summary
    persisted["ok"] = True
    persisted["saved_files"] = saved_files
    persisted["path"] = saved_files[0]["path"]
    persisted["size"] = saved_files[0]["size"]
    persisted["mime_type"] = saved_files[0]["mime_type"]
    persisted["verified"] = True
    return persisted


def _normalize_report_path(path: str) -> str:
    cleaned = (path or "").strip().lstrip("/")
    if not cleaned:
        cleaned = "outputs/report.html"
    outputs_index = cleaned.find("outputs/")
    if outputs_index >= 0:
        cleaned = cleaned[outputs_index:]
    elif "/" not in cleaned:
        cleaned = f"outputs/{cleaned}"
    if not cleaned.startswith("outputs/"):
        return ""
    if ".." in Path(cleaned).parts:
        return ""
    if not cleaned.lower().endswith(".html"):
        cleaned = f"{cleaned}.html"
    return cleaned


def _normalize_pdf_path(path: str) -> str:
    cleaned = (path or "").strip().lstrip("/")
    if not cleaned:
        cleaned = "outputs/agent_export.pdf"
    outputs_index = cleaned.find("outputs/")
    if outputs_index >= 0:
        cleaned = cleaned[outputs_index:]
    elif "/" not in cleaned:
        cleaned = f"outputs/{cleaned}"
    if not cleaned.startswith("outputs/"):
        return ""
    if ".." in Path(cleaned).parts:
        return ""
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned


def _read_text_source(context, source_path: str) -> tuple[str, str | None]:
    try:
        display_path = _normalize_job_path(str(context.job_id), source_path)
        scoped = _resolve_path(str(context.job_id), display_path)
    except ValueError as e:
        return "", str(e)

    ext = Path(display_path).suffix.lower()
    if ext not in {".txt", ".md", ".html", ".xml", ".log", ".summary", ".report", ".csv", ".tsv", ".json"}:
        return "", f"Unsupported PDF source file type: {ext or '(none)'}"

    storage = get_storage_service()
    if not storage.exists(scoped):
        return "", f"Source file not found: {display_path}"
    try:
        with storage.get_local_path(scoped) as local_path:
            text = Path(local_path).read_text(encoding="utf-8", errors="replace").replace("\x00", "")
        return text[:MAX_PDF_SOURCE_CHARS], None
    except Exception as e:
        return "", f"Source read failed: {str(e)}"


def _validate_report_result(value) -> tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "result must be an object"
    if value.get("ok") is not True:
        return False, "result.ok must be true"
    html = value.get("html")
    if not isinstance(html, str) or not html.strip():
        return False, "result.html must be a non-empty string"
    if "<html" not in html.lower() or "</html>" not in html.lower():
        return False, "result.html must be a complete HTML document"
    if len(html.encode("utf-8")) > MAX_REPORT_HTML_LENGTH:
        return False, f"result.html is too large (max {MAX_REPORT_HTML_LENGTH} bytes)"
    return True, ""


async def _execute_python_handler(args: dict, context) -> dict:
    code = args.get("code", "")
    if not code.strip():
        return {"error": "code is required"}
    if len(code) > 100_000:
        return {"error": "code must be under 100,000 characters"}

    inputs = args.get("inputs", {})
    if not isinstance(inputs, dict):
        return {"error": "inputs must be a dict"}

    allow_network = args.get("allow_network", True)
    timeout = min(int(args.get("timeout", 30)), 60)  # cap at 60s

    execution = await execute_python(
        code=code, inputs=inputs,
        timeout=timeout,
        allow_network=allow_network,
    )
    if execution.get("error"):
        return execution
    return _persist_execution_files(execution, context)


async def _create_pdf_handler(args: dict, context) -> dict:
    content = str(args.get("content") or "")
    source_path = (args.get("source_path") or "").strip()
    title = (args.get("title") or "InsightDOC PDF Export").strip()
    output_path = _normalize_pdf_path(args.get("output_path") or "")

    if source_path and not content.strip():
        content, error = _read_text_source(context, source_path)
        if error:
            return {"error": error}

    if not content.strip():
        return {"error": "content or source_path is required"}
    if not output_path:
        stem = Path(source_path).stem if source_path else "agent_export"
        output_path = _normalize_pdf_path(f"outputs/{stem}.pdf")
    if not output_path:
        return {"error": "output_path must be a .pdf file under outputs/"}

    filename = Path(output_path).name
    code = r'''
from fpdf import FPDF

content = str(inputs.get("content") or "")
title = str(inputs.get("title") or "InsightDOC PDF Export")
filename = str(inputs.get("filename") or "agent_export.pdf")

REPLACEMENTS = {
    "\ufeff": "",
    "\ufe0f": "",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\t": "    ",
    "✅": "[OK]",
    "❌": "[X]",
    "⚠": "[!]",
    "⚠️": "[!]",
    "🔴": "[HIGH]",
    "🟡": "[MED]",
    "🟢": "[LOW]",
    "📌": "*",
    "📋": "*",
    "📊": "*",
    "🎯": "*",
    "→": "->",
    "←": "<-",
    "⬆": "up",
    "⬇": "down",
}


def clean_text(value):
    text = str(value or "")
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    return "".join(ch if ch == "\n" or ch >= " " else " " for ch in text)

pdf = FPDF(format="A4")
pdf.set_auto_page_break(auto=False)
pdf.set_margins(12, 12, 12)
pdf.add_page()
font_path = _thai_font_path()
pdf.add_font("Thai", "", font_path)
page_width = pdf.w - pdf.l_margin - pdf.r_margin
bottom_y = pdf.h - pdf.b_margin


def ensure_space(line_height):
    if pdf.get_y() + line_height > bottom_y:
        pdf.add_page()


def emit_line(text, line_height=5):
    ensure_space(line_height)
    pdf.cell(0, line_height, text=clean_text(text), new_x="LMARGIN", new_y="NEXT")


def wrap_by_width(text, max_width):
    text = clean_text(text).rstrip()
    if not text:
        return [""]
    lines = []
    current = ""
    for ch in text:
        candidate = current + ch
        if current and pdf.get_string_width(candidate) > max_width:
            lines.append(current.rstrip())
            current = ch.lstrip(" ")
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def emit_wrapped(text, line_height=5):
    for part in wrap_by_width(text, page_width):
        if part:
            emit_line(part, line_height)
        else:
            ensure_space(line_height)
            pdf.ln(line_height)


pdf.set_font("Thai", "", 14)
emit_wrapped(title, 8)
pdf.ln(2)
pdf.set_font("Thai", "", 8)

for raw_line in clean_text(content).splitlines():
    line = raw_line.rstrip()
    if not line.strip():
        pdf.ln(3)
        continue
    emit_wrapped(line, 4.8)

pdf.output("/tmp/" + filename)
result = _save_file("/tmp/" + filename)
'''
    execution = await execute_python(
        code=code,
        inputs={
            "content": content[:MAX_PDF_SOURCE_CHARS],
            "title": title,
            "filename": filename,
        },
        timeout=60,
        allow_network=False,
    )
    if execution.get("error"):
        return {
            "error": "PDF creation failed",
            "execution_error": execution.get("error"),
            "stdout": execution.get("stdout"),
        }

    persisted = _persist_execution_files(execution, context)
    if persisted.get("ok") is not True or not persisted.get("path"):
        return {
            "error": "PDF creation produced no verified file",
            "execution": execution,
        }
    result = dict(persisted)
    result["source_path"] = source_path or None
    result["summary"] = "Created PDF from saved source text" if source_path else "Created PDF from provided content"
    return result


async def _run_report_code_handler(args: dict, context) -> dict:
    code = args.get("code", "")
    if not code.strip():
        return {"error": "code is required"}
    if len(code) > MAX_REPORT_CODE_LENGTH:
        return {"error": f"code must be under {MAX_REPORT_CODE_LENGTH} characters"}

    try:
        ast.parse(code)
    except SyntaxError as e:
        return {
            "error": "Syntax check failed",
            "syntax_error": {"message": e.msg, "line": e.lineno, "offset": e.offset},
        }

    inputs = args.get("inputs", {})
    if not isinstance(inputs, dict):
        return {"error": "inputs must be a dict"}

    output_path = _normalize_report_path(args.get("output_path") or "outputs/report.html")
    if not output_path:
        return {"error": "output_path must be an .html file under outputs/"}

    timeout = min(int(args.get("timeout", 45)), 60)
    execution = await execute_python(
        code=code,
        inputs=inputs,
        timeout=timeout,
        allow_network=False,
    )

    if execution.get("error"):
        return {
            "error": "Report code execution failed",
            "execution_error": execution.get("error"),
            "stdout": execution.get("stdout"),
        }

    valid, validation_error = _validate_report_result(execution.get("result"))
    if not valid:
        return {
            "error": "Report result validation failed",
            "validation_error": validation_error,
            "result": execution.get("result"),
            "stdout": execution.get("stdout"),
        }

    html = execution["result"]["html"]
    try:
        scoped = _resolve_path(str(context.job_id), output_path)
    except ValueError as e:
        return {"error": str(e)}

    try:
        storage = get_storage_service()
        data = html.encode("utf-8")
        storage.upload_file(io.BytesIO(data), scoped, content_type="text/html; charset=utf-8")
    except Exception as e:
        return {"error": f"Report write failed: {str(e)}"}

    report_result = execution.get("result") or {}
    return {
        "ok": True,
        "path": output_path,
        "download_path": output_path,
        "size": len(html.encode("utf-8")),
        "summary": report_result.get("summary"),
        "validation_summary": report_result.get("validation_summary"),
        "rule_count": len(report_result.get("rules") or report_result.get("validation_results") or []),
    }


tool_registry.register(ToolDef(
    name="execute_python",
    category="code",
    description=(
        "Execute Python code in an isolated Docker sandbox. "
        "The code has access to `inputs` (dict) and should assign to a `result` variable to return data. "
        "Common document/data packages are preinstalled: fpdf2, reportlab, requests, openpyxl, xlsxwriter, pandas, python-docx, pypdf, pillow, xlrd. "
        "CSV uses Python's built-in csv module. "
        "If a package is missing, call `_pip_install('pkg1 pkg2')` — this is the ONLY safe install method. "
        "NEVER call subprocess pip install directly; the filesystem is read-only so direct pip will always fail. "
        "For binary output files (xlsx, pdf, docx, pptx, png): save to /tmp/<filename> then call `_save_file('/tmp/<filename>')` "
        "to get base64 — then pass to write_file with `content_base64` to store. "
        "PDF with Thai text: use fpdf2 with `_thai_font_path()` and pdf.add_font(...); built-in fonts (Helvetica/Times) do NOT support Thai. "
        "Excel: use openpyxl or xlsxwriter. CSV: use csv.StringIO/TextIO patterns and UTF-8. "
        "Set `allow_network=false` to disable outbound network if not needed. "
        "For HTML reports, prefer run_report_code because it validates and writes the report safely."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute. Use 'inputs' dict for input data. Set 'result' variable to return data. Common document/data packages are preinstalled; call _pip_install('pkg') only for missing dependencies.",
            },
            "inputs": {
                "type": "object",
                "description": "Data passed to the code as an 'inputs' dict variable",
            },
            "allow_network": {
                "type": "boolean",
                "default": True,
                "description": "Allow outbound network (for pip install, HTTP requests). Set false for untrusted code.",
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": 60,
                "default": 30,
                "description": "Execution timeout in seconds.",
            },
        },
        "required": ["code"],
    },
    handler=_execute_python_handler,
))


tool_registry.register(ToolDef(
    name="create_pdf",
    category="filesystem",
    description=(
        "Create a verified PDF file under outputs/ from provided text content or a saved text/Markdown/CSV/HTML report source. "
        "Use this for requests like 'ช่วยสร้างเป็น pdf' or 'convert this table/report to PDF'. "
        "This deterministic tool supports Thai text and should be preferred over raw execute_python for PDF creation."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Text or Markdown content to render into the PDF. Optional if source_path is provided.",
            },
            "source_path": {
                "type": "string",
                "description": "Existing saved text-like file relative to job root, e.g. outputs/risk_comparison_table.md.",
            },
            "output_path": {
                "type": "string",
                "description": "PDF output path under outputs/, e.g. outputs/risk_comparison_table.pdf.",
            },
            "title": {
                "type": "string",
                "description": "PDF title rendered at the top of the document.",
            },
        },
        "required": [],
    },
    handler=_create_pdf_handler,
))


tool_registry.register(ToolDef(
    name="run_report_code",
    category="code",
    description=(
        "Run AI-generated Python report code with guardrails, validate that it returns a complete HTML document, "
        "and write the report under outputs/. The code must set result to an object with ok=true and html='<html>...</html>'. "
        "Use this instead of raw execute_python + write_file for HTML reports."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code. It can read inputs dict and must set result={'ok': True, 'html': '<!doctype html>...', 'summary': {...}, 'rules': [...]}",
            },
            "inputs": {
                "type": "object",
                "description": "Structured report inputs such as documents, rules, and language preferences.",
            },
            "output_path": {
                "type": "string",
                "default": "outputs/report.html",
                "description": "HTML output path under outputs/, e.g. outputs/cross_document_validation_report.html.",
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": 60,
                "default": 45,
            },
        },
        "required": ["code", "inputs", "output_path"],
    },
    handler=_run_report_code_handler,
))
