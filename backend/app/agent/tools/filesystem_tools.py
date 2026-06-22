"""
File system tools — read/write/list/delete files in MinIO.

All paths are scoped to jobs/{job_id}/ for tenant isolation.
The agent can only access files within its current job's directory.
"""
import io
import logging
import zipfile
import base64
import csv
import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

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
OFFICE_ZIP_REQUIRED_ENTRIES = {
    ".xlsx": ("[Content_Types].xml", "xl/workbook.xml"),
    ".docx": ("[Content_Types].xml", "word/document.xml"),
    ".pptx": ("[Content_Types].xml", "ppt/presentation.xml"),
}


def _content_type_for_extension(ext: str) -> str:
    return {
        ".csv": "text/csv; charset=utf-8",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".zip": "application/zip",
    }.get(ext, f"image/{ext[1:]}" if ext in (".png", ".jpg", ".jpeg") else "application/octet-stream")


def _xlsx_col(index: int) -> str:
    index += 1
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _build_xlsx_bytes(rows: list[list[object]], title: str = "InsightDOC Excel Export") -> bytes:
    """Build a small valid XLSX workbook using inline strings, no external deps."""
    cleaned: list[list[str]] = []
    for row in rows:
        cleaned.append(["" if cell is None else str(cell) for cell in row])
    if not cleaned:
        cleaned = [["Content"], [""]]

    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sheet_rows: list[str] = []
    for r_idx, row in enumerate(cleaned, start=1):
        cells: list[str] = []
        for c_idx, value in enumerate(row):
            ref = f"{_xlsx_col(c_idx)}{r_idx}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as xlsx:
        xlsx.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""")
        xlsx.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""")
        xlsx.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>""")
        xlsx.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""")
        xlsx.writestr("xl/worksheets/sheet1.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{"".join(sheet_rows)}</sheetData>
</worksheet>""")
        xlsx.writestr("docProps/core.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{escape(title)}</dc:title>
  <dc:creator>InsightDOC Agent</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>""")
        xlsx.writestr("docProps/app.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>InsightDOC</Application></Properties>""")
    return buffer.getvalue()


def _docx_rows(data: bytes) -> list[list[str]]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data), "r") as docx:
        root = ET.fromstring(docx.read("word/document.xml"))

    rows: list[list[str]] = []
    for tbl in root.findall(".//w:tbl", ns):
        for tr in tbl.findall(".//w:tr", ns):
            cells: list[str] = []
            for tc in tr.findall("./w:tc", ns):
                text = "".join(t.text or "" for t in tc.findall(".//w:t", ns)).strip()
                cells.append(text)
            if any(cells):
                rows.append(cells)

    paragraph_rows: list[list[str]] = []
    for para in root.findall(".//w:body/w:p", ns):
        text = "".join(t.text or "" for t in para.findall(".//w:t", ns)).strip()
        if text:
            paragraph_rows.append([text])

    if rows:
        return [["Extracted table from DOCX"]] + rows + ([[]] + paragraph_rows if paragraph_rows else [])
    return [["Content"]] + paragraph_rows


def _markdown_table_rows(text: str) -> list[list[str]] | None:
    table_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|") and line.strip().endswith("|")]
    if len(table_lines) < 2:
        return None
    rows: list[list[str]] = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
            continue
        rows.append(cells)
    return rows or None


def _rows_from_text(text: str) -> list[list[str]]:
    markdown_rows = _markdown_table_rows(text)
    if markdown_rows:
        return markdown_rows
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [["Content"]] + [[line] for line in lines]


def _extract_rows_for_xlsx(path: str, data: bytes) -> tuple[list[list[str]], str]:
    ext = Path(path).suffix.lower()
    if ext == ".docx":
        return _docx_rows(data), "Converted DOCX content to rows"
    if ext in {".csv", ".tsv"}:
        delimiter = "\t" if ext == ".tsv" else ","
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)], "Converted delimited text to rows"
    if ext in {".txt", ".md", ".html", ".xml", ".log", ".summary", ".report"}:
        return _rows_from_text(data.decode("utf-8", errors="replace")), "Converted text content to rows"
    if ext in {".json", ".jsonl"}:
        text = data.decode("utf-8", errors="replace")
        obj = [json.loads(line) for line in text.splitlines() if line.strip()] if ext == ".jsonl" else json.loads(text)
        if isinstance(obj, list) and all(isinstance(item, dict) for item in obj):
            headers = sorted({key for item in obj for key in item.keys()})
            return [headers] + [[item.get(h, "") for h in headers] for item in obj], "Converted JSON objects to rows"
        if isinstance(obj, dict):
            return [["Key", "Value"]] + [[k, json.dumps(v, ensure_ascii=False)] for k, v in obj.items()], "Converted JSON object to rows"
        return [["Value"]] + [[json.dumps(item, ensure_ascii=False)] for item in obj], "Converted JSON array to rows"
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return _rows_from_text(text), "Converted PDF text to rows"
        except Exception as e:
            return [["PDF conversion error"], [str(e)]], "PDF text extraction failed"
    return _rows_from_text(data.decode("utf-8", errors="replace")), "Converted file text to rows"


def _validate_binary_payload(ext: str, data: bytes) -> str | None:
    """Return an error message if binary data is not valid for the target extension."""
    if ext in OFFICE_ZIP_REQUIRED_ENTRIES or ext == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
                names = set(archive.namelist())
                bad_file = archive.testzip()
        except zipfile.BadZipFile:
            return f"{ext} content is not a valid ZIP/OpenXML file. Generate it with openpyxl/xlsxwriter/python-docx and pass _save_file(...).base64."
        if bad_file:
            return f"{ext} archive is corrupt at entry: {bad_file}"
        for required in OFFICE_ZIP_REQUIRED_ENTRIES.get(ext, ()):
            if required not in names:
                return f"{ext} archive is missing required entry: {required}"
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        return "PDF content is invalid: missing %PDF header"
    if ext in (".png", ".jpg", ".jpeg"):
        signatures = {
            ".png": b"\x89PNG\r\n\x1a\n",
            ".jpg": b"\xff\xd8\xff",
            ".jpeg": b"\xff\xd8\xff",
        }
        if not data.startswith(signatures[ext]):
            return f"{ext} content has an invalid image header"
    return None


def verify_saved_file(job_id: str, path: str, expected_size: int | None = None) -> dict:
    """Verify a generated file exists in job storage and is structurally readable."""
    try:
        display_path = _normalize_job_path(str(job_id), path)
        scoped = _resolve_path(str(job_id), display_path)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    storage = get_storage_service()
    if not storage.exists(scoped):
        return {"ok": False, "error": f"File verification failed: not found after write: {display_path}"}

    try:
        with storage.get_local_path(scoped) as local_path:
            local = Path(local_path)
            size = local.stat().st_size
            ext = Path(display_path).suffix.lower()
            if size <= 0:
                return {"ok": False, "error": f"File verification failed: empty file: {display_path}", "size": size}
            if expected_size is not None and int(expected_size) != size:
                return {
                    "ok": False,
                    "error": f"File verification failed: size mismatch for {display_path} (reported {expected_size}, stored {size})",
                    "size": size,
                }
            if ext in BINARY_EXTENSIONS:
                validation_error = _validate_binary_payload(ext, local.read_bytes())
                if validation_error:
                    return {"ok": False, "error": f"File verification failed: {validation_error}", "size": size}
            return {
                "ok": True,
                "path": display_path,
                "size": size,
                "mime_type": _content_type_for_extension(ext),
            }
    except Exception as e:
        return {"ok": False, "error": f"File verification failed: {str(e)}"}


def _normalize_job_path(job_id: str, path: str) -> str:
    """Return a job-relative path, accepting either outputs/... or jobs/<job_id>/outputs/...."""
    path = (path or "").strip().lstrip("/")
    current_prefix = f"jobs/{job_id}/"
    if path.startswith(current_prefix):
        path = path[len(current_prefix):]
    elif path.startswith("jobs/"):
        raise ValueError("Cross-job paths are not allowed")
    return path


def _resolve_path(job_id: str, path: str) -> str:
    """Resolve and validate a path within the job's directory.

    All paths are relative to jobs/{job_id}/.
    Path traversal (..) is blocked.
    """
    path = _normalize_job_path(job_id, path)

    # Block path traversal
    segments = Path(path).parts
    if ".." in segments:
        raise ValueError("Path traversal not allowed")

    # Prepend job scope
    scoped = f"jobs/{job_id}/{path}"
    return scoped


def _safe_read(
    storage,
    path: str,
    max_size: int = MAX_FILE_SIZE_READ,
    return_base64: bool = False,
    display_path: str | None = None,
) -> dict:
    """Read file content safely, returning text only for text formats."""
    display_path = display_path or path
    if not storage.exists(path):
        return {"error": f"File not found: {display_path}"}

    try:
        with storage.get_local_path(path) as local_path:
            local = Path(local_path)
            file_size = local.stat().st_size
            ext = Path(path).suffix.lower()

            if ext in BINARY_EXTENSIONS:
                if return_base64:
                    if file_size > max_size:
                        return {
                            "error": f"File too large ({file_size} bytes, max {max_size})",
                            "size": file_size,
                            "binary": True,
                        }
                    data = local.read_bytes()
                    return {
                        "content": None,
                        "content_base64": base64.b64encode(data).decode("ascii"),
                        "binary": True,
                        "path": display_path,
                        "size": file_size,
                        "extension": ext,
                        "mime_type": _content_type_for_extension(ext),
                        "note": "Binary content returned as base64. In execute_python, decode it to /tmp or BytesIO before editing.",
                    }
                return {
                    "content": None,
                    "binary": True,
                    "path": display_path,
                    "size": file_size,
                    "extension": ext,
                    "mime_type": _content_type_for_extension(ext),
                    "note": "Binary file; call read_file with return_base64=true to edit it in execute_python, or download from the UI.",
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


def _safe_write(storage, path: str, content: str, display_path: str, max_size: int = MAX_FILE_SIZE_WRITE) -> dict:
    """Write text content to a file."""
    ext = Path(display_path).suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return {"error": f"Binary extension '{ext}' requires content_base64. Use _save_file() in execute_python and pass its base64 value to write_file."}

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > max_size:
        return {"error": f"Content too large ({len(content_bytes)} bytes, max {max_size})"}

    if ext and ext not in ALLOWED_EXTENSIONS:
        return {"error": f"File extension '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}

    try:
        file_obj = io.BytesIO(content_bytes)
        storage.upload_file(file_obj, path, content_type="text/plain; charset=utf-8")
        return {"ok": True, "path": display_path, "size": len(content_bytes), "mime_type": "text/plain; charset=utf-8"}
    except Exception as e:
        return {"error": f"Write failed: {str(e)}"}


def _safe_list(storage, prefix: str, job_id: str) -> dict:
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
                    display_path = _normalize_job_path(job_id, key)
                    files.append({
                        "path": display_path,
                        "size": obj["Size"],
                        "last_modified": str(obj["LastModified"]),
                    })
                for common_prefix in page.get("CommonPrefixes", []):
                    display_path = _normalize_job_path(job_id, common_prefix["Prefix"])
                    files.append({
                        "path": display_path,
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
        path = _normalize_job_path(str(context.job_id), path)
        scoped = _resolve_path(str(context.job_id), path)
    except ValueError as e:
        return {"error": str(e)}

    storage = get_storage_service()
    return _safe_read(
        storage,
        scoped,
        max_size=args.get("max_size", MAX_FILE_SIZE_WRITE if args.get("return_base64") else MAX_FILE_SIZE_READ),
        return_base64=bool(args.get("return_base64")),
        display_path=path,
    )


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
        path = _normalize_job_path(str(context.job_id), path)
        scoped = _resolve_path(str(context.job_id), path)
    except ValueError as e:
        return {"error": str(e)}

    storage = get_storage_service()

    # Binary content via base64
    if content_base64:
        ext = Path(path).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {"error": f"File extension '{ext}' not allowed"}
        try:
            data = base64.b64decode(content_base64)
        except Exception as e:
            return {"error": f"Invalid base64: {str(e)}"}
        if len(data) > MAX_FILE_SIZE_WRITE:
            return {"error": f"Content too large ({len(data)} bytes, max {MAX_FILE_SIZE_WRITE})"}
        validation_error = _validate_binary_payload(ext, data)
        if validation_error:
            return {"error": validation_error}
        try:
            file_obj = io.BytesIO(data)
            content_type = _content_type_for_extension(ext)
            storage.upload_file(file_obj, scoped, content_type=content_type)
        except Exception as e:
            return {"error": f"Write failed: {str(e)}"}
        verification = verify_saved_file(str(context.job_id), path, expected_size=len(data))
        if verification.get("ok") is not True:
            return {"ok": False, "verified": False, "path": path,
                    "error": verification.get("error") or "File verification failed"}
        return {"ok": True, "verified": True, "path": path, "size": verification.get("size", len(data)),
                "binary": True, "mime_type": content_type}

    # Text content
    result = _safe_write(storage, scoped, content, display_path=path)
    if result.get("ok") is True:
        verification = verify_saved_file(
            str(context.job_id), path, expected_size=result.get("size")
        )
        if verification.get("ok") is not True:
            return {"ok": False, "verified": False, "path": path,
                    "error": verification.get("error") or "File verification failed"}
        result["verified"] = True
        result["verified_size"] = verification.get("size", result.get("size"))
    return result


async def _list_files_handler(args: dict, context) -> dict:
    prefix = args.get("prefix", "").strip()
    if prefix:
        try:
            prefix = _normalize_job_path(str(context.job_id), prefix)
        except ValueError as e:
            return {"error": str(e)}

    base = f"jobs/{context.job_id}/"
    if prefix:
        base = f"{base}{prefix}"

    # Ensure trailing / for S3 prefix listing
    if prefix and not prefix.endswith("/"):
        # If it looks like a directory, add slash
        pass

    storage = get_storage_service()
    return _safe_list(storage, base, str(context.job_id))


async def _delete_file_handler(args: dict, context) -> dict:
    path = args["path"].strip()
    if not path:
        return {"error": "path is required"}

    try:
        path = _normalize_job_path(str(context.job_id), path)
        scoped = _resolve_path(str(context.job_id), path)
    except ValueError as e:
        return {"error": str(e)}

    storage = get_storage_service()
    if not storage.exists(scoped):
        return {"error": f"File not found: {path}"}

    try:
        storage.delete_file(scoped)
    except Exception as e:
        return {"error": f"Delete failed: {str(e)}"}
    if storage.exists(scoped):
        return {"ok": False, "verified": False, "path": path,
                "error": "File still exists after delete — removal may not have persisted"}
    return {"ok": True, "verified": True, "path": path}


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
    except Exception as e:
        return {"error": f"DOCX creation failed: {str(e)}"}
    verification = verify_saved_file(str(context.job_id), path, expected_size=len(data))
    if verification.get("ok") is not True:
        return {"ok": False, "verified": False, "path": path,
                "error": verification.get("error") or "DOCX verification failed"}
    return {"ok": True, "verified": True, "path": path,
            "size": verification.get("size", len(data)), "binary": True,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


async def _convert_to_xlsx_handler(args: dict, context) -> dict:
    source_path = (args.get("source_path") or args.get("path") or "").strip()
    output_path = (args.get("output_path") or "").strip()
    title = (args.get("title") or "InsightDOC Excel Export").strip()

    if not source_path:
        return {"error": "source_path is required"}

    try:
        scoped_source = _resolve_path(str(context.job_id), source_path)
    except ValueError as e:
        return {"error": str(e)}

    source_ext = Path(source_path).suffix.lower()
    if source_ext == ".xlsx":
        return {"error": "source_path is already an .xlsx file"}

    if not output_path:
        source_name = Path(source_path).stem or "converted"
        output_path = f"outputs/{source_name}.xlsx"
    if not output_path.endswith(".xlsx"):
        output_path = f"{output_path}.xlsx"
    if not output_path.startswith("outputs/") and "/" not in output_path:
        output_path = f"outputs/{output_path}"

    try:
        scoped_output = _resolve_path(str(context.job_id), output_path)
    except ValueError as e:
        return {"error": str(e)}

    storage = get_storage_service()
    if not storage.exists(scoped_source):
        return {"error": f"Source file not found: {source_path}"}

    try:
        with storage.get_local_path(scoped_source) as local_path:
            source = Path(local_path)
            if source.stat().st_size > MAX_FILE_SIZE_WRITE:
                return {"error": f"Source file too large ({source.stat().st_size} bytes, max {MAX_FILE_SIZE_WRITE})"}
            source_data = source.read_bytes()
        validation_error = _validate_binary_payload(source_ext, source_data)
        if validation_error and source_ext in BINARY_EXTENSIONS:
            return {"error": f"Source file is invalid: {validation_error}"}

        rows, summary = _extract_rows_for_xlsx(source_path, source_data)
        data = _build_xlsx_bytes(rows, title=title)
        if len(data) > MAX_FILE_SIZE_WRITE:
            return {"error": f"Generated workbook too large ({len(data)} bytes, max {MAX_FILE_SIZE_WRITE})"}

        storage.upload_file(
            io.BytesIO(data),
            scoped_output,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        verification = verify_saved_file(str(context.job_id), output_path, expected_size=len(data))
        if verification.get("ok") is not True:
            return {
                "ok": False,
                "verified": False,
                "path": output_path,
                "source_path": source_path,
                "error": verification.get("error") or "XLSX verification failed",
            }
        return {
            "ok": True,
            "verified": True,
            "path": output_path,
            "source_path": source_path,
            "size": len(data),
            "binary": True,
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "rows": len(rows),
            "columns": max((len(row) for row in rows), default=0),
            "summary": summary,
        }
    except Exception as e:
        return {"error": f"XLSX conversion failed: {str(e)}"}


# ── Tool Registrations ────────────────────────────────────────────────────────

tool_registry.register(ToolDef(
    name="read_file",
    category="filesystem",
    description=(
        "Read the contents of a file from the job's storage. "
        "Files up to 500KB are returned as text. "
        "Binary files return metadata by default; set return_base64=true to retrieve binary content for editing in execute_python. "
        "Use this to read previously saved outputs, reports, or data files. "
        "Never assume /tmp files from earlier execute_python calls still exist; sandbox /tmp is ephemeral."
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
                "description": "Override max read size in bytes (default 500000 for text, 5000000 when return_base64=true)",
            },
            "return_base64": {
                "type": "boolean",
                "default": False,
                "description": "Return base64 for binary files such as xlsx/pdf/docx so execute_python can modify the saved file.",
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
        "(use _save_file() in execute_python to get base64). The file is validated before saving; invalid .xlsx/.docx/.pptx/PDF/image payloads are rejected. "
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
    name="convert_to_xlsx",
    category="filesystem",
    description=(
        "Convert a previously saved job output/document into a valid .xlsx workbook. "
        "Use this for requests like 'ช่วยแปลงเป็น excel', 'convert this Word/PDF/report to Excel', "
        "or when the user wants the latest saved DOCX/CSV/text/report as an Excel file. "
        "Prefer this deterministic tool over read_file + execute_python for file conversion."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "source_path": {
                "type": "string",
                "description": "Existing file path relative to job root, e.g. 'outputs/report.docx'. Supports docx, csv, tsv, txt, md, html, json, jsonl, pdf.",
            },
            "output_path": {
                "type": "string",
                "description": "Optional .xlsx output path. Defaults to outputs/<source-name>.xlsx.",
            },
            "title": {
                "type": "string",
                "description": "Workbook title metadata.",
            },
        },
        "required": ["source_path"],
    },
    handler=_convert_to_xlsx_handler,
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
