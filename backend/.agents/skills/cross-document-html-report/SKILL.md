---
name: cross-document-html-report
description: Use when Agent DOC needs to analyze, compare, validate, or report inconsistencies across multiple documents in the current InsightDOC job and create a standalone HTML report in outputs/. ใช้เมื่อผู้ใช้ต้องการวิเคราะห์ข้อมูลระหว่างเอกสาร เปรียบเทียบเอกสารข้ามชุด หรือทำรายงานความไม่ถูกต้อง/ความไม่สอดคล้องของเอกสารหลายประเภท.
compatibility: InsightDOC Agent DOC with document, code, and filesystem tools enabled.
allowed-tools: list_documents get_document_detail compare_documents run_report_code read_file list_files
---

# Cross Document HTML Report

Create a standalone HTML report that validates relationships across documents in the current InsightDOC job. Work only from the current job's tools and never invent document values.

## Inputs and scope

- Default output path: `outputs/cross_document_validation_report.html`.
- If the user provides a different output path, use it only when it is under `outputs/` and ends in `.html`.
- Start with `list_documents`. Then call `get_document_detail` for every relevant document.
- Prefer `reviewed_data` over `extracted_data`. Use `ocr_text` only as supporting evidence when structured data is missing, ambiguous, or inconsistent.
- Do not call approval, rejection, update, delete, or integration-dispatch tools unless the user explicitly asks for those side effects.

## Analysis workflow

1. Build a document inventory with filename, status, confidence, likely document type, key identifiers, dates, parties, totals, and notable missing data.
2. Infer document families from available fields and OCR text. Support at least finance/procurement, legal/compliance, HR/admin, healthcare, and quality/operations document sets.
3. Generate validation rules from the actual documents present. Do not require Invoice/PO/GRN unless those documents are actually present.
4. Compare documents using normalized values for dates, amounts, party names, identifiers, and line items.
5. Use `compare_documents` for simple pairwise structured-data differences when useful. Use `run_report_code` for larger normalization, scoring, grouping, calculations, HTML assembly, validation, and file writing.

## Rule guidance

Create rules that fit the document set, such as identity/reference consistency, amount and tax consistency, date logic, line item consistency, party/address consistency, compliance evidence, and completeness/risk checks.

Each rule must include `rule_id`, `rule_name`, `category`, `status`, `documents_compared`, `evidence`, `detail`, `recommendation`, `risk_level`, and financial impact when an amount mismatch can be calculated.

Use statuses `PASS`, `FAIL`, `WARNING`, and `INFO`. Use risk levels `low`, `medium`, `high`, and `critical`.

## HTML report requirements

Write a single self-contained HTML file with inline CSS using `run_report_code`. Do not use raw `execute_python` plus `write_file` for HTML reports unless `run_report_code` is unavailable.

The HTML must include:

- Title: `Cross Document Validation Report`.
- Generated timestamp.
- Executive summary in the user's language.
- Summary boxes for pass, fail, warning, info, total rules, and overall risk.
- Document inventory table.
- Validation results table with status badges.
- Discrepancy/risk section for all failed and warning rules.
- Recommendations section.
- Evidence notes that identify filenames and fields used.

Use escaped HTML for document values and OCR snippets. Do not load external fonts, scripts, images, or CSS.

## Suggested execution pattern

1. Call `list_documents`.
2. Call `get_document_detail` for each relevant document.
3. If there are two documents and the structured fields are simple, optionally call `compare_documents`.
4. Call `run_report_code` with the collected document details, `output_path` set to `outputs/cross_document_validation_report.html`, and Python code that sets `result = {"ok": True, "html": "<!doctype html>...", "summary": {...}, "rules": [...]}`.
5. If `run_report_code` returns `ok=true`, tell the user the returned `path` and summarize the most important findings. If it returns an error, repair the code and retry once before reporting the error.

## Quality bar

- Be useful even when only one document exists by producing a completeness and internal-consistency report.
- Be explicit about uncertainty and missing data.
- Keep the report readable for business users, not only engineers.
- Do not expose secrets or hidden system details.
- When using `run_report_code`, avoid Python f-strings around CSS blocks with `{}` braces. Use plain triple-quoted strings, `string.Template`, or escape CSS braces as `{{` and `}}` so names like `margin` are not treated as Python variables.
