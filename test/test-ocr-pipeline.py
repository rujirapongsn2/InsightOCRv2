#!/usr/bin/env python3
"""
Test OCR Pipeline — Replicate InsightOCR Backend flow
=====================================================
Tests the full pipeline: OCR -> Structure Extraction
Uses raw ocr_text only (bypasses AI Enhancement which fails with 400).

Usage:
    python test-ocr-pipeline.py
    python test-ocr-pipeline.py --file other-image.png
    python test-ocr-pipeline.py --verbose
"""

import argparse
import json
import os
import sys
import time
import urllib3
import requests

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ──────────────────────────────────────────────────────────────────
OCR_API_URL = "https://111.223.37.41:9001/ai-process-file"
STRUCTURE_API_URL = "https://111.223.37.41:9001/structured-output"
API_TOKEN = "ocr_ai_key_987654321fedcba"
VERIFY_SSL = False

# Invoice_Google schema (matching the schema used in InsightOCR)
INVOICE_GOOGLE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier":       {"type": "string", "description": "Company or person who issued the invoice"},
        "invoice":        {"type": "string", "description": "Invoice or quotation number"},
        "bill_to":        {"type": "string", "description": "Customer name and address billed to"},
        "total_amount":   {"type": "string", "description": "Total amount including tax"},
        "tax_amount":     {"type": "string", "description": "Tax or VAT amount"},
        "invoice_number": {"type": "string", "description": "Invoice reference number"},
        "vendor_name":    {"type": "string", "description": "Vendor or supplier name"},
        "invoice_date":   {"type": "string", "description": "Date the invoice was issued"},
    },
    "required": ["supplier", "invoice", "bill_to", "total_amount"],
}

# Expected values for Google-inv.png (for comparison)
EXPECTED_VALUES = {
    "supplier": "Google Asia Pacific Pte. Ltd.",
    "invoice": "Tax Invoice",
    "invoice_number": "5484373571",
    "bill_to": "Softnix Technology, 731, P.M. TOWER, FLOOR 12, ASOK - DINDANG Road, DIN DAENG, Bangkok 10400, Thailand",
    "total_amount": "THB 10.65",
    "tax_amount": "THB 0.70",
    "vendor_name": "Google Asia Pacific Pte. Ltd.",
    "invoice_date": "Jan 31, 2026",
}


def print_header(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_step(num: int, title: str):
    print(f"\n{'─' * 70}")
    print(f"  STEP {num}: {title}")
    print(f"{'─' * 70}")


def step1_ocr(file_path: str, verbose: bool = False) -> dict:
    """Call OCR API and return raw result."""
    print_step(1, f"OCR Processing: {os.path.basename(file_path)}")

    filename = os.path.basename(file_path)
    file_ext = os.path.splitext(filename)[1].lower()
    content_type = "application/pdf" if file_ext == ".pdf" else f"image/{file_ext[1:]}"

    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {API_TOKEN}",
    }
    data = {"pages": "1", "prompt": "", "ocr_engine": "", "model": ""}

    print(f"  URL:          {OCR_API_URL}")
    print(f"  File:         {filename} ({content_type})")

    start = time.time()
    with open(file_path, "rb") as f:
        response = requests.post(
            OCR_API_URL,
            headers=headers,
            data=data,
            files={"file": (filename, f, content_type)},
            verify=VERIFY_SSL,
        )
    elapsed = time.time() - start

    print(f"  Status:       {response.status_code} ({elapsed:.2f}s)")

    if response.status_code != 200:
        print(f"  ERROR:        {response.text[:300]}")
        sys.exit(1)

    result = response.json()

    if verbose:
        print(f"\n  Full response keys: {list(result.keys())}")
        if "results" in result:
            print(f"  Results keys: {list(result['results'].keys())}")

    return result


def step2_analyze_ocr(ocr_result: dict, verbose: bool = False) -> str:
    """Extract and analyze OCR text, report AI enhancement status."""
    print_step(2, "Analyze OCR Result (bypass AI Enhancement)")

    pages = ocr_result.get("results", {}).get("pages", [])
    if not pages:
        print("  ERROR: No pages in OCR result")
        sys.exit(1)

    page = pages[0]
    ai_processing = page.get("ai_processing", {})
    ocr_text = page.get("ocr_text", "")

    # ── AI Enhancement status ──
    ai_success = False
    ai_content = ""
    if isinstance(ai_processing, dict):
        ai_success = ai_processing.get("success", False)
        ai_content = ai_processing.get("content", "")
        ai_error = ai_processing.get("error", "")

    print(f"\n  AI Enhancement:  {'SUCCESS' if ai_success else 'FAILED'}")
    if not ai_success and isinstance(ai_processing, dict):
        print(f"  AI Error:        {ai_processing.get('error', 'N/A')}")
    if ai_success and ai_content:
        print(f"  AI Content:      {len(ai_content)} chars")

    print(f"\n  Raw OCR Text:    {len(ocr_text)} chars")
    print(f"  {'─' * 50}")
    # Show OCR text with line numbers
    for i, line in enumerate(ocr_text.strip().split("\n")[:20], 1):
        print(f"  {i:3d} | {line.rstrip()}")
    if ocr_text.count("\n") > 20:
        print(f"  ... ({ocr_text.count(chr(10)) - 20} more lines)")

    # ── Decision: which text to use ──
    if ai_success and ai_content:
        chosen = ai_content
        source = "AI Enhanced"
    else:
        chosen = ocr_text
        source = "Raw OCR (AI Enhancement bypassed/failed)"

    print(f"\n  Using:           {source}")
    print(f"  Text length:     {len(chosen)} chars")

    return chosen


def step3_structure_extraction(ocr_text: str, verbose: bool = False) -> dict:
    """Call structure extraction API with OCR text + schema."""
    print_step(3, "Structure Extraction (OCR text + JSON Schema)")

    schema_json = json.dumps(INVOICE_GOOGLE_SCHEMA)
    prompt = (
        "Return a JSON array of objects that match the schema. "
        "If multiple people/records appear across pages, include one object per record. "
        "Fill missing values with null or an empty string."
    )

    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "context": ocr_text,
        "json_schema": schema_json,
        "prompt": prompt,
    }

    print(f"  URL:          {STRUCTURE_API_URL}")
    print(f"  Schema:       Invoice_Google ({len(INVOICE_GOOGLE_SCHEMA['properties'])} fields)")
    print(f"  Context:      {len(ocr_text)} chars of OCR text")

    if verbose:
        print(f"\n  Schema fields:")
        for name, prop in INVOICE_GOOGLE_SCHEMA["properties"].items():
            req = "required" if name in INVOICE_GOOGLE_SCHEMA.get("required", []) else "optional"
            print(f"    - {name} ({req}): {prop.get('description', '')}")

    start = time.time()
    response = requests.post(
        STRUCTURE_API_URL,
        headers=headers,
        data=data,
        verify=VERIFY_SSL,
    )
    elapsed = time.time() - start

    print(f"\n  Status:       {response.status_code} ({elapsed:.2f}s)")

    if response.status_code != 200:
        print(f"  ERROR:        {response.text[:300]}")
        sys.exit(1)

    result = response.json()

    if verbose:
        print(f"\n  Full response:")
        print(f"  {json.dumps(result, indent=2, ensure_ascii=False)}")

    return result


def step4_evaluate(structure_result: dict):
    """Compare extracted data with expected values."""
    print_step(4, "Evaluation: Extracted vs Expected")

    extracted = structure_result.get("structured_output", {})

    if not extracted:
        print("  ERROR: No structured_output in result")
        return

    print(f"\n  {'Field':<20} {'Extracted':<35} {'Expected':<35} {'Match'}")
    print(f"  {'─' * 20} {'─' * 35} {'─' * 35} {'─' * 5}")

    total = 0
    matched = 0
    empty = 0

    for field in INVOICE_GOOGLE_SCHEMA["properties"]:
        ext_val = str(extracted.get(field, "")).strip()
        exp_val = EXPECTED_VALUES.get(field, "")
        total += 1

        if not ext_val:
            empty += 1
            status = "EMPTY"
        elif ext_val.lower() in exp_val.lower() or exp_val.lower() in ext_val.lower():
            matched += 1
            status = "OK"
        else:
            status = "DIFF"

        # Truncate display
        ext_display = (ext_val[:32] + "...") if len(ext_val) > 35 else ext_val or "(empty)"
        exp_display = (exp_val[:32] + "...") if len(exp_val) > 35 else exp_val

        print(f"  {field:<20} {ext_display:<35} {exp_display:<35} {status}")

    # Quality score
    quality = (matched / total * 100) if total else 0
    print(f"\n  {'─' * 50}")
    print(f"  Quality Score:  {matched}/{total} fields matched ({quality:.0f}%)")
    print(f"  Empty fields:   {empty}/{total}")

    if quality >= 75:
        print(f"  Verdict:        GOOD - Extraction works well")
    elif quality >= 50:
        print(f"  Verdict:        PARTIAL - Some fields extracted")
    else:
        print(f"  Verdict:        POOR - OCR quality too low for reliable extraction")
        print(f"                  Root cause: AI Enhancement failed, raw OCR is insufficient for images")

    # Note about API
    note = structure_result.get("note", "")
    if note:
        print(f"\n  API Note:       {note}")


def main():
    parser = argparse.ArgumentParser(description="Test OCR Pipeline (replicate InsightOCR Backend)")
    parser.add_argument(
        "--file", "-f",
        default=os.path.join(os.path.dirname(__file__), "Google-inv.png"),
        help="Path to document file (default: Google-inv.png)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"ERROR: File not found: {args.file}")
        sys.exit(1)

    print_header("InsightOCR Pipeline Test")
    print(f"  File:   {args.file}")
    print(f"  OCR:    {OCR_API_URL}")
    print(f"  Struct: {STRUCTURE_API_URL}")

    total_start = time.time()

    # Step 1: OCR
    ocr_result = step1_ocr(args.file, args.verbose)

    # Step 2: Analyze & select text (bypass AI Enhancement)
    ocr_text = step2_analyze_ocr(ocr_result, args.verbose)

    # Step 3: Structure extraction
    structure_result = step3_structure_extraction(ocr_text, args.verbose)

    # Step 4: Evaluate
    step4_evaluate(structure_result)

    total_elapsed = time.time() - total_start
    print_header(f"Done ({total_elapsed:.2f}s total)")


if __name__ == "__main__":
    main()
