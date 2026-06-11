import ast
import io
from pathlib import Path

from app.agent.tools.filesystem_tools import _resolve_path
from app.agent.tools.registry import ToolDef, tool_registry
from app.services.code_sandbox import execute_python
from app.services.storage import get_storage_service


MAX_REPORT_CODE_LENGTH = 120_000
MAX_REPORT_HTML_LENGTH = 5_000_000


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

    return await execute_python(
        code=code, inputs=inputs,
        timeout=timeout,
        allow_network=allow_network,
    )


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
        "Network is enabled by default — use `_pip_install('package1 package2')` to install dependencies. "
        "For binary output files (xlsx, pdf, docx, pptx): save to disk then call `_save_file(path)` to get base64 — "
        "then use write_file with `content_base64` to store the file. "
        "Set `allow_network=false` to disable outbound network if not needed. "
        "For HTML reports, prefer run_report_code because it validates and writes the report safely."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute. Use 'inputs' dict for input data. Set 'result' variable to return data. Call _pip_install('pkg') for dependencies.",
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
