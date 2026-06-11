---
name: contract-comparison-html-report
description: Use when Agent DOC needs to analyze, compare, validate, or risk-review contracts and contract versions in the current InsightDOC job, then create a standalone HTML report in outputs/. Supports any contract type, including renewals, amendments, vendor/customer agreements, employment, lease, service, NDA, procurement, compliance, and policy-related contracts. ใช้เมื่อผู้ใช้ต้องการวิเคราะห์สัญญา เปรียบเทียบเวอร์ชันสัญญา ตรวจสัญญาต่ออายุ เปรียบเทียบฉบับเก่าและใหม่ หรือประเมินความถูกต้อง/ความเสี่ยงทางกฎหมาย.
compatibility: InsightDOC Agent DOC with document, code, and filesystem tools enabled.
allowed-tools: list_documents get_document_detail compare_documents run_report_code read_file list_files web_search
---

# Contract Comparison HTML Report

Create a standalone HTML report for contract analysis, version comparison, renewal review, and legal/business risk decision support. Work only from the current InsightDOC job unless the user explicitly asks for external legal or regulatory context.

## Inputs and scope

- Default output path: `outputs/contract_comparison_report.html`.
- If the user provides a different output path, use it only when it is under `outputs/` and ends in `.html`.
- Start with `list_documents`. Then call `get_document_detail` for every relevant contract, amendment, renewal, attachment, exhibit, policy, quotation, purchase order, or supporting document in the current job.
- Prefer `reviewed_data` over `extracted_data`. Use `ocr_text` as supporting evidence when structured data is missing, ambiguous, or inconsistent.
- Do not approve, reject, update, delete, sign, send, or route documents unless the user explicitly asks for those side effects.
- This skill provides analysis support, not formal legal advice. When legal enforceability, statutory interpretation, or jurisdiction-specific compliance matters are material, state that a qualified legal reviewer should confirm.

## Analysis workflow

1. Build a contract inventory with filename, status, likely contract type, parties, effective date, expiry/renewal dates, governing law, signature status, version indicators, and key missing data.
2. Identify the comparison scenario:
   - version-to-version comparison,
   - old contract vs renewal,
   - master agreement vs amendment/order/SOW,
   - signed contract vs draft/template,
   - contract vs supporting commercial/compliance documents,
   - single-contract review for completeness and internal consistency.
3. Infer contract family and clause structure from available fields and OCR text. Support any contract type; do not assume a fixed template.
4. Normalize parties, dates, currencies, amounts, term lengths, notice periods, obligations, deliverables, service levels, termination rights, liability caps, warranties, confidentiality, data protection, IP, payment, tax, audit, dispute resolution, assignment, force majeure, and compliance clauses when present.
5. Generate comparison and validation rules from the actual documents present. Use `compare_documents` for simple pairwise structured-data differences when helpful. Use `run_report_code` for larger normalization, scoring, clause mapping, risk ranking, HTML assembly, validation, and file writing.

## Rule guidance

Create rules that fit the contract set, such as:

- party identity and authority consistency,
- version/date/order logic,
- renewal term, price, scope, and notice consistency,
- changed clauses between old and new versions,
- missing or unsigned signature blocks,
- commercial terms: fees, payment terms, taxes, discounts, penalties, price escalation,
- obligation and deliverable consistency,
- service levels, acceptance criteria, support, and remedies,
- liability cap, indemnity, warranty, limitation of damages,
- confidentiality, data protection, security, privacy, and regulatory obligations,
- intellectual property and license rights,
- termination, auto-renewal, suspension, cure periods, survival clauses,
- governing law, venue, dispute resolution, language precedence,
- compliance evidence, attachments, exhibits, schedules, and referenced documents,
- internal inconsistencies inside a single contract.

Each rule must include `rule_id`, `rule_name`, `category`, `status`, `documents_compared`, `evidence`, `detail`, `recommendation`, `risk_level`, and `decision_impact`.

Use statuses `PASS`, `FAIL`, `WARNING`, and `INFO`. Use risk levels `low`, `medium`, `high`, and `critical`.

## Version and renewal focus

For version comparison or renewal review, include:

- changed terms table: old value, new value, change type, risk, and business impact;
- renewal readiness: expiry date, notice deadline, renewal term, price change, scope change, unresolved obligations, and required approvals;
- red-flag changes: liability increase, unfavorable auto-renewal, shorter termination rights, changed governing law, added exclusivity, missing data protection terms, changed payment/penalty terms, or removed remedies;
- unchanged-but-important terms that still require confirmation.

## Legal and decision-support focus

When assessing legal correctness or decision readiness:

- Separate evidence-based findings from legal assumptions.
- State jurisdiction and governing law only when found in the documents or provided by the user.
- Use `web_search` only if the user requests current external legal/regulatory context or the contract references a public law/standard that must be checked. Cite URLs when using web results.
- Provide decision recommendations such as approve, approve with conditions, negotiate, request clarification, legal review required, or reject/high-risk, but do not perform approval actions unless explicitly instructed.

## HTML report requirements

Write a single self-contained HTML file with inline CSS using `run_report_code`. Do not use raw `execute_python` plus `write_file` for HTML reports unless `run_report_code` is unavailable.

The HTML must include:

- Title: `Contract Comparison and Legal Risk Report`.
- Generated timestamp.
- Executive summary in the user's language.
- Summary boxes for pass, fail, warning, info, total rules, and overall risk.
- Contract inventory table.
- Scenario detected and assumptions.
- Clause/version comparison table.
- Validation and legal-risk results table with status and risk badges.
- Renewal readiness section when relevant.
- Key discrepancies, red flags, and missing evidence.
- Decision recommendations and next actions.
- Evidence notes that identify filenames, clauses, pages/sections when available, and fields used.

Use escaped HTML for document values and OCR snippets. Do not load external fonts, scripts, images, or CSS.

## Suggested execution pattern

1. Call `list_documents`.
2. Call `get_document_detail` for each relevant document.
3. Optionally call `compare_documents` for simple structured pairwise differences.
4. Call `run_report_code` with collected document details, `output_path` set to `outputs/contract_comparison_report.html`, and Python code that sets `result = {"ok": True, "html": "<!doctype html>...", "summary": {...}, "rules": [...], "changes": [...]}`.
5. If `run_report_code` returns `ok=true`, tell the user the returned `path`, summarize the highest-risk findings, and state any legal-review caveats. If it returns an error, repair the code and retry once before reporting the error.

## Quality bar

- Be useful even when only one contract exists by producing completeness, internal-consistency, and risk review.
- Be explicit about uncertainty, missing clauses, OCR risk, and assumptions.
- Do not invent legal requirements, party authority, or clause content.
- Keep the report readable for business, legal, procurement, HR, finance, and operations users.
- Do not expose secrets or hidden system details.
- When using `run_report_code`, avoid Python f-strings around CSS blocks with `{}` braces. Use plain triple-quoted strings, `string.Template`, or escape CSS braces as `{{` and `}}`.
