"""
File system tools — read/write/list/delete files in MinIO.

All paths are scoped to jobs/{job_id}/ for tenant isolation.
The agent can only access files within its current job's directory.
"""
import io
import logging
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from app.agent.tools.registry import ToolDef, tool_registry
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)

SAFE_PREFIX = "outputs/"
MAX_FILE_SIZE_READ = 500_000   # 500KB max for read_file
MAX_FILE_SIZE_WRITE = 5_000_000  # 5MB max for write_file
ALLOWED_EXTENSIONS = {
    # Text formats
    ".txt", ".md", ".csv", ".json", ".jsonl", ".yaml", ".yml",
    ".html", ".xml", ".log", ".py", ".sh", ".sql", ".tsv",
    ".report", ".summary",
    # Office / binary formats
    ".xlsx", ".pdf", ".docx", ".pptx",
    ".png", ".jpg", ".jpeg", ".svg",
    ".zip",
}
BINARY_EXTENSIONS = {".xlsx", ".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".zip"}


def _resolve_path(job_id: str, path: str) -> str:
    """Resolve and validate a path within the job's directory.

    All paths are relative to jobs/{job_id}/.
    Path traversal (..) is blocked.
    """
    path = path.lstrip("/")

    # Block path traversal
    segments = Path(path).parts
    if ".." in segments:
        raise ValueError("Path traversal not allowed")

    # Prepend job scope
    scoped = f"jobs/{job_id}/{path}"
    return scoped


def _safe_read(storage, path: str, max_size: int = MAX_FILE_SIZE_READ) -> dict:
    """Read file content safely, returning text only for text formats."""
    if not storage.exists(path):
        return {"error": f"File not found: {path}"}

    try:
        with storage.get_local_path(path) as local_path:
            local = Path(local_path)
            file_size = local.stat().st_size
            ext = Path(path).suffix.lower()

            if ext in BINARY_EXTENSIONS:
                return {
                    "content": None,
                    "binary": True,
                    "path": path,
                    "size": file_size,
                    "extension": ext,
                    "note": "Binary file; use download_agent_file from the UI or create a new file with create_docx/write_file. Binary content is not returned to the agent.",
                }

            if file_size > max_size:
                return {
                    "error": f"File too large ({file_size} bytes, max {max_size})",
                    "size": file_size,
                    "hint": "Use a smaller text file or process in chunks with execute_python",
                }

            content = local.read_text(encoding="utf-8", errors="replace")
            content = content.replace("\x00", "")

        return {"content": content, "size": file_size, "binary": False}
    except Exception as e:
        return {"error": f"Read failed: {str(e)}"}


def _safe_write(storage, path: str, content: str, max_size: int = MAX_FILE_SIZE_WRITE) -> dict:
    """Write text content to a file."""
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > max_size:
        return {"error": f"Content too large ({len(content_bytes)} bytes, max {max_size})"}

    ext = Path(path).suffix.lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        return {"error": f"File extension '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}

    try:
        file_obj = io.BytesIO(content_bytes)
        storage.upload_file(file_obj, path, content_type="text/plain; charset=utf-8")
        return {"ok": True, "path": path, "size": len(content_bytes)}
    except Exception as e:
        return {"error": f"Write failed: {str(e)}"}


def _safe_list(storage, prefix: str) -> dict:
    """List files under a prefix. Uses S3/MinIO list_objects or local os.walk."""
    try:
        # Try S3-style listing first (MinIO/S3 via boto3)
        if hasattr(storage, "client") and hasattr(storage.client, "list_objects_v2"):
            paginator = storage.client.get_paginator("list_objects_v2")
            files = []
            for page in paginator.paginate(Bucket=storage.bucket, Prefix=prefix, Delimiter="/"):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key == prefix:
                        continue
                    files.append({
                        "path": key,
                        "size": obj["Size"],
                        "last_modified": str(obj["LastModified"]),
                    })
                for common_prefix in page.get("CommonPrefixes", []):
                    files.append({
                        "path": common_prefix["Prefix"],
                        "type": "directory",
                    })
            return {"count": len(files), "files": files}

        # Fallback: local storage — use os.walk equivalent via exists checks
        # For local storage, we just return the prefix info since we can't list
        return {"count": 0, "files": [], "note": "Directory listing not supported on local storage. Use known file paths."}

    except Exception as e:
        return {"error": f"List failed: {str(e)}"}


# ── Tool Handlers ────────────────────────────────────────────────────────────

async def _read_file_handler(args: dict, context) -> dict:
    path = args["path"].strip()
    if not path:
        return {"error": "path is required"}

    try:
        scoped = _resolve_path(str(context.job_id), path)
    except ValueError as e:
        return {"error": str(e)}

    storage = get_storage_service()
    return _safe_read(storage, scoped, max_size=args.get("max_size", MAX_FILE_SIZE_READ))


async def _write_file_handler(args: dict, context) -> dict:
    path = args["path"].strip()
    content = args.get("content", "")
    content_base64 = args.get("content_base64", "")

    if not path:
        return {"error": "path is required"}
    if not content and not content_base64:
        return {"error": "content or content_base64 is required"}

    # Scope writes to outputs/ by default for safety
    if not path.startswith("outputs/") and "/" not in path:
        path = f"outputs/{path}"

    try:
        scoped = _resolve_path(str(context.job_id), path)
    except ValueError as e:
        return {"error": str(e)}

    storage = get_storage_service()

    # Binary content via base64
    if content_base64:
        import base64
        ext = Path(path).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {"error": f"File extension '{ext}' not allowed"}
        try:
            data = base64.b64decode(content_base64)
        except Exception as e:
            return {"error": f"Invalid base64: {str(e)}"}
        if len(data) > MAX_FILE_SIZE_WRITE:
            return {"error": f"Content too large ({len(data)} bytes, max {MAX_FILE_SIZE_WRITE})"}
        try:
            file_obj = io.BytesIO(data)
            content_type = "application/octet-stream"
            if ext == ".xlsx":
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif ext == ".docx":
                content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            elif ext == ".pptx":
                content_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            elif ext == ".pdf":
                content_type = "application/pdf"
            elif ext in (".png", ".jpg", ".jpeg"):
                content_type = f"image/{ext[1:]}"
            storage.upload_file(file_obj, scoped, content_type=content_type)
            return {"ok": True, "path": path, "size": len(data), "binary": True}
        except Exception as e:
            return {"error": f"Write failed: {str(e)}"}

    # Text content
    return _safe_write(storage, scoped, content)


async def _list_files_handler(args: dict, context) -> dict:
    prefix = args.get("prefix", "").strip()
    if prefix:
        prefix = prefix.lstrip("/")

    base = f"jobs/{context.job_id}/"
    if prefix:
        base = f"{base}{prefix}"

    # Ensure trailing / for S3 prefix listing
    if prefix and not prefix.endswith("/"):
        # If it looks like a directory, add slash
        pass

    storage = get_storage_service()
    return _safe_list(storage, base)


async def _delete_file_handler(args: dict, context) -> dict:
    path = args["path"].strip()
    if not path:
        return {"error": "path is required"}

    try:
        scoped = _resolve_path(str(context.job_id), path)
    except ValueError as e:
        return {"error": str(e)}

    storage = get_storage_service()
    if not storage.exists(scoped):
        return {"error": f"File not found: {path}"}

    try:
        storage.delete_file(scoped)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"error": f"Delete failed: {str(e)}"}


def _docx_xml(text: str) -> str:
    lines = text.splitlines() or [""]
    paragraphs: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            paragraphs.append("<w:p/>")
            continue

        style = ""
        if line.startswith("# "):
            style = '<w:pStyle w:val="Heading1"/>'
            line = line[2:].strip()
        elif line.startswith("## "):
            style = '<w:pStyle w:val="Heading2"/>'
            line = line[3:].strip()
        elif line.startswith(("- ", "* ")):
            line = f"• {line[2:].strip()}"

        paragraphs.append(
            "<w:p>"
            f"<w:pPr>{style}</w:pPr>"
            "<w:r>"
            f"<w:t xml:space=\"preserve\">{escape(line)}</w:t>"
            "</w:r>"
            "</w:p>"
        )

    body = "".join(paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        "</w:body></w:document>"
    )


def _build_docx_bytes(content: str, title: str = "InsightDOC Export") -> bytes:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""")
        docx.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""")
        docx.writestr("word/_rels/document.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""")
        docx.writestr("word/document.xml", _docx_xml(content))
        docx.writestr("docProps/core.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{escape(title)}</dc:title>
  <dc:creator>InsightDOC Agent</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>""")
        docx.writestr("docProps/app.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>InsightDOC</Application></Properties>""")
    return buffer.getvalue()


async def _create_docx_handler(args: dict, context) -> dict:
    path = (args.get("path") or "").strip()
    title = (args.get("title") or "InsightDOC Export").strip()
    content = args.get("content") or ""

    if not path:
        return {"error": "path is required"}
    if not path.endswith(".docx"):
        path = f"{path}.docx"
    if not path.startswith("outputs/") and "/" not in path:
        path = f"outputs/{path}"
    if not str(content).strip():
        return {"error": "content is required"}

    try:
        scoped = _resolve_path(str(context.job_id), path)
    except ValueError as e:
        return {"error": str(e)}

    data = _build_docx_bytes(str(content), title=title)
    if len(data) > MAX_FILE_SIZE_WRITE:
        return {"error": f"Content too large ({len(data)} bytes, max {MAX_FILE_SIZE_WRITE})"}

    try:
        storage = get_storage_service()
        storage.upload_file(
            io.BytesIO(data),
            scoped,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        return {"ok": True, "path": path, "size": len(data), "binary": True, "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    except Exception as e:
        return {"error": f"DOCX creation failed: {str(e)}"}


# ── Tool Registrations ────────────────────────────────────────────────────────

tool_registry.register(ToolDef(
    name="read_file",
    category="filesystem",
    description=(
        "Read the contents of a file from the job's storage. "
        "Files up to 500KB are returned as text. "
        "Binary files return metadata only. "
        "Use this to read previously saved outputs, reports, or data files."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to job root (e.g. 'outputs/report.txt'). Path traversal is blocked.",
            },
            "max_size": {
                "type": "integer",
                "description": "Override max read size in bytes (default 500000)",
            },
        },
        "required": ["path"],
    },
    handler=_read_file_handler,
))

tool_registry.register(ToolDef(
    name="write_file",
    category="filesystem",
    description=(
        "Write content to a file in the job's storage. "
        "For text files: use 'content' parameter. "
        "For binary files (xlsx, pdf, docx, pptx, png): use 'content_base64' with base64-encoded data "
        "(use _save_file() in execute_python to get base64). "
        "Supported extensions: .txt, .md, .csv, .json, .html, .xlsx, .pdf, .docx, .pptx, .png, .zip, .py, .sql."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (e.g. 'report.xlsx' or 'outputs/report.pdf'). Defaults to outputs/.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write (for text files)",
            },
            "content_base64": {
                "type": "string",
                "description": "Base64-encoded binary content (for xlsx, pdf, docx, pptx, png). Use _save_file() in execute_python to get this.",
            },
        },
        "required": ["path"],
    },
    handler=_write_file_handler,
))


tool_registry.register(ToolDef(
    name="create_docx",
    category="filesystem",
    description=(
        "Create a .docx file in the current job's outputs from plain text or markdown-like content. "
        "Use this for Word quotation/report/draft files before telling the user a .docx was created. "
        "The result includes a downloadable path when successful."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Output path relative to job root, e.g. 'outputs/quotation_Q26050014-9.docx'.",
            },
            "title": {
                "type": "string",
                "description": "Document title metadata.",
            },
            "content": {
                "type": "string",
                "description": "Plain text content. Lines starting '# ', '## ', '- ', or '* ' are formatted lightly.",
            },
        },
        "required": ["path", "content"],
    },
    handler=_create_docx_handler,
))

tool_registry.register(ToolDef(
    name="list_files",
    category="filesystem",
    description="List files in the job's storage directory. Use to see what output files and reports are available.",
    parameters_schema={
        "type": "object",
        "properties": {
            "prefix": {
                "type": "string",
                "description": "Directory prefix to list (e.g. 'outputs/'). Empty = job root.",
            },
        },
        "required": [],
    },
    handler=_list_files_handler,
))

tool_registry.register(ToolDef(
    name="delete_file",
    category="filesystem",
    description="Delete a file from the job's storage. Requires user confirmation.",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to delete relative to job root",
            },
        },
        "required": ["path"],
    },
    handler=_delete_file_handler,
    requires_confirmation=True,
))
