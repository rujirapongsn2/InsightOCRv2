"""
File system tools — read/write/list/delete files in MinIO.

All paths are scoped to jobs/{job_id}/ for tenant isolation.
The agent can only access files within its current job's directory.
"""
import io
import logging
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
    """Read file content safely, returning text for known types."""
    if not storage.exists(path):
        return {"error": f"File not found: {path}"}

    try:
        with storage.get_local_path(path) as local_path:
            file_size = Path(local_path).stat().st_size
            if file_size > max_size:
                return {
                    "error": f"File too large ({file_size} bytes, max {max_size})",
                    "size": file_size,
                    "hint": "Use a smaller file or process in chunks with execute_python",
                }

            try:
                content = Path(local_path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                # Binary file — return metadata only
                return {
                    "content": None,
                    "binary": True,
                    "size": file_size,
                    "note": "Binary file — cannot display as text",
                }

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
