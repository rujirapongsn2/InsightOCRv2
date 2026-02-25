"""
test_structured_data.py
=======================
ทดสอบ External OCR API (v3/ai-process-file) เพื่อทำความเข้าใจ
โครงสร้างของ Structured Data ในกรณี:

  Case A — Auto mode   : ไม่ส่ง json_schema
  Case B — Schema mode : ส่ง json_schema ที่กำหนดเอง (Thai_PurchaseOrder)

สิ่งที่ต้องการพิสูจน์
--------------------
1. API return structured_output ใน results.structured_output หรือไม่
2. schema_source = "auto" | "user_provided" ตรงตาม mode หรือไม่
3. structured_output.data มี field ตรงกับ json_schema ที่ส่งไปหรือไม่
4. results.pages[n].structured_data มีข้อมูลหรือไม่

Usage
-----
  cd test
  pip install -r requirements.txt   # requests urllib3
  python test_structured_data.py

  หรือระบุ token โดยตรง:
  API_TOKEN=<token> python test_structured_data.py
"""

import json
import os
import sys
import time
import urllib3
from pathlib import Path

import requests

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BASE_URL = "https://111.223.37.41:9001"
API_TOKEN = os.environ.get("API_TOKEN", "")          # set ผ่าน env หรือ hardcode ด้านล่าง
API_USERNAME = os.environ.get("API_USERNAME", "admin")
API_PASSWORD = os.environ.get("API_PASSWORD", "admin")

# ไฟล์ทดสอบ — ใช้ไฟล์ที่มีอยู่ใน test/
TEST_FILE = Path(__file__).parent / "01_Purchase_Order_PO-2026-0210.pdf"

# JSON Schema สำหรับ Thai Purchase Order
THAI_PO_SCHEMA = {
    "type": "object",
    "properties": {
        "no":            {"type": "string",  "description": "Purchase Order number"},
        "date":          {"type": "string",  "description": "Document date"},
        "buyer":         {"type": "string",  "description": "Buyer company name and address"},
        "buyer_tax_id":  {"type": "string",  "description": "Buyer Tax ID"},
        "seller":        {"type": "string",  "description": "Seller company name and address"},
        "shipping_terms":{"type": "string",  "description": "Shipping terms (FOB, CIF, etc.)"},
        "payment_terms": {"type": "string",  "description": "Payment terms"},
        "delivery_date": {"type": "string",  "description": "Delivery date"},
        "port_of_loading":   {"type": "string", "description": "Port of loading"},
        "port_of_discharge": {"type": "string", "description": "Port of discharge"},
        "items": {
            "type": "array",
            "description": "Line items / order items",
            "items": {
                "type": "object",
                "properties": {
                    "no":          {"type": "number"},
                    "description": {"type": "string"},
                    "sku":         {"type": "string"},
                    "qty":         {"type": "number"},
                    "unit":        {"type": "string"},
                    "unit_price":  {"type": "number"},
                    "total":       {"type": "number"},
                }
            }
        },
        "total_amount": {"type": "number", "description": "Grand total amount"},
    }
}

POLL_INTERVAL = 3   # seconds between status polls
POLL_TIMEOUT  = 180 # max seconds to wait

# suppress SSL warnings (self-signed cert)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_token() -> str:
    """Login และรับ Bearer token"""
    if API_TOKEN:
        return API_TOKEN
    print(f"  [login] POST {BASE_URL}/login as {API_USERNAME}")
    res = requests.post(
        f"{BASE_URL}/login",
        data={"username": API_USERNAME, "password": API_PASSWORD},
        verify=False,
        timeout=15,
    )
    res.raise_for_status()
    token = res.json().get("access_token", "")
    if not token:
        raise RuntimeError(f"Login failed: {res.json()}")
    print(f"  [login] OK — token={token[:20]}...")
    return token


def submit_job(token: str, json_schema: dict | None = None) -> str:
    """Submit ไฟล์ไปยัง v3/ai-process-file แล้ว return job_id"""
    url = f"{BASE_URL}/v3/ai-process-file"
    headers = {"Authorization": f"Bearer {token}"}
    with open(TEST_FILE, "rb") as f:
        data = {"ocr_engine": "tesseract"}
        if json_schema is not None:
            data["json_schema"] = json.dumps(json_schema)
        res = requests.post(
            url,
            headers=headers,
            data=data,
            files={"file": (TEST_FILE.name, f, "application/pdf")},
            verify=False,
            timeout=60,
        )
    res.raise_for_status()
    payload = res.json()
    job_id = payload.get("job_id", "")
    schema_mode = payload.get("schema_mode", "?")
    print(f"  [submit] job_id={job_id}  schema_mode={schema_mode}")
    return job_id


def poll_until_done(token: str, job_id: str) -> dict:
    """Poll status จนกว่าจะ completed หรือ failed แล้ว return result"""
    headers = {"Authorization": f"Bearer {token}"}
    status_url = f"{BASE_URL}/v3/ai-process-file/{job_id}/status"
    result_url  = f"{BASE_URL}/v3/ai-process-file/{job_id}/result"
    deadline = time.time() + POLL_TIMEOUT

    while time.time() < deadline:
        res = requests.get(status_url, headers=headers, verify=False, timeout=15)
        res.raise_for_status()
        payload = res.json()
        status = payload.get("status", "").lower()
        progress = payload.get("progress", {})
        pct   = progress.get("percent", "?")
        stage = progress.get("stage", "")
        print(f"  [poll]  status={status:12s}  {pct:>3}%  stage={stage}")

        if status in {"completed", "success", "done"}:
            res2 = requests.get(result_url, headers=headers, verify=False, timeout=60)
            res2.raise_for_status()
            return res2.json()

        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"Job failed: {payload}")

        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Job {job_id} did not complete within {POLL_TIMEOUT}s")


def inspect_result(result: dict, label: str) -> None:
    """วิเคราะห์และแสดงผล structured_output จาก result"""
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  RESULT ANALYSIS: {label}")
    print(sep)

    # 1. Top-level keys
    top_keys = list(result.keys()) if isinstance(result, dict) else []
    print(f"  top-level keys       : {top_keys}")

    results_block = result.get("results", {})
    results_keys  = list(results_block.keys()) if isinstance(results_block, dict) else []
    print(f"  results.*  keys      : {results_keys}")

    # 2. structured_output (top-level)
    so_top = result.get("structured_output")
    print(f"\n  result.structured_output       = {_fmt(so_top)}")

    # 3. results.structured_output (nested)
    so_nested = results_block.get("structured_output")
    print(f"  result.results.structured_output = {_fmt(so_nested)}")

    # 4. Per-page structured_data
    pages = results_block.get("pages", [])
    print(f"\n  total pages          : {len(pages)}")
    for i, page in enumerate(pages):
        pg_sd = page.get("structured_data")
        pg_ai_keys = list(page.get("ai_processing", {}).keys()) if isinstance(page.get("ai_processing"), dict) else []
        print(f"  page[{i}].structured_data  = {_fmt(pg_sd)}")
        print(f"  page[{i}].ai_processing.*  = {pg_ai_keys}")

    # 5. Summary assertions
    print(f"\n  {'─'*40}")
    best_so = so_top or so_nested
    if best_so is None:
        print("  ⚠️  structured_output is NONE — fallback to markdown parser will be used")
    else:
        schema_source = best_so.get("schema_source", "?")
        data          = best_so.get("data", {})
        schema        = best_so.get("schema", {})
        print(f"  ✅ structured_output found")
        print(f"     schema_source = {schema_source}")
        print(f"     schema keys   = {list(schema.get('properties', {}).keys()) if isinstance(schema, dict) else 'N/A'}")
        print(f"     data keys     = {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
        print(f"     data preview  :")
        _print_data(data, indent=10)

    print(sep)


def _fmt(v) -> str:
    """Short representation for display"""
    if v is None:
        return "None"
    if isinstance(v, dict):
        keys = list(v.keys())
        return f"dict  keys={keys}"
    if isinstance(v, list):
        return f"list  len={len(v)}"
    return repr(v)[:120]


def _print_data(data, indent=0):
    prefix = " " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                print(f"{prefix}{k}: {_fmt(v)}")
            else:
                print(f"{prefix}{k}: {repr(v)[:80]}")
    elif isinstance(data, list):
        for i, item in enumerate(data[:3]):
            print(f"{prefix}[{i}]: {_fmt(item) if isinstance(item, dict) else repr(item)[:80]}")
        if len(data) > 3:
            print(f"{prefix}... (+{len(data)-3} more)")


def save_result(result: dict, filename: str) -> None:
    """บันทึก raw result เป็น JSON file"""
    out = Path(__file__).parent / filename
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  [save]  raw result → {out}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run_case(token: str, label: str, json_schema: dict | None, save_as: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  CASE: {label}")
    print(f"  json_schema: {'(none — auto mode)' if json_schema is None else 'provided'}")
    print(f"{'='*60}")
    job_id = submit_job(token, json_schema=json_schema)
    result = poll_until_done(token, job_id)
    save_result(result, save_as)
    inspect_result(result, label)
    return result


def main():
    if not TEST_FILE.exists():
        print(f"ERROR: Test file not found: {TEST_FILE}")
        print("  Please put a PDF file named '1-page.pdf' in the test/ directory")
        sys.exit(1)

    print(f"Test file : {TEST_FILE.name}  ({TEST_FILE.stat().st_size:,} bytes)")
    print(f"API       : {BASE_URL}")

    token = get_token()

    # Case A — Auto mode
    result_auto = run_case(
        token,
        label="Auto Mode (no json_schema)",
        json_schema=None,
        save_as="result_auto.json",
    )

    # Case B — Schema mode
    result_schema = run_case(
        token,
        label="Schema Mode (Thai_PurchaseOrder)",
        json_schema=THAI_PO_SCHEMA,
        save_as="result_schema.json",
    )

    # ─── COMPARISON ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  COMPARISON SUMMARY")
    print(f"{'='*60}")

    def has_structured(r: dict) -> bool:
        so = r.get("structured_output") or r.get("results", {}).get("structured_output")
        return so is not None

    def get_so(r: dict) -> dict | None:
        return r.get("structured_output") or r.get("results", {}).get("structured_output")

    so_auto   = get_so(result_auto)
    so_schema = get_so(result_schema)

    print(f"  {'':30s}  {'AUTO':^20}  {'SCHEMA':^20}")
    print(f"  {'─'*72}")
    print(f"  {'structured_output present':30s}  {str(so_auto is not None):^20}  {str(so_schema is not None):^20}")

    if so_auto:
        print(f"  {'schema_source (auto)':30s}  {so_auto.get('schema_source','?'):^20}")
    if so_schema:
        print(f"  {'schema_source (schema)':30s}  {'':^20}  {so_schema.get('schema_source','?'):^20}")
        schema_keys = list(so_schema.get("schema", {}).get("properties", {}).keys()) if isinstance(so_schema.get("schema"), dict) else []
        data_keys   = list(so_schema.get("data", {}).keys()) if isinstance(so_schema.get("data"), dict) else []
        print(f"  {'schema fields defined':30s}  {'':^20}  {schema_keys}")
        print(f"  {'data fields returned':30s}  {'':^20}  {data_keys}")

        if schema_keys and data_keys:
            matched = [k for k in schema_keys if k in data_keys]
            missing = [k for k in schema_keys if k not in data_keys]
            print(f"\n  Fields matched  : {matched}")
            print(f"  Fields missing  : {missing}")
            coverage = len(matched) / len(schema_keys) * 100 if schema_keys else 0
            print(f"  Coverage        : {coverage:.0f}%")

    print(f"\n  Raw results saved:")
    print(f"    test/result_auto.json")
    print(f"    test/result_schema.json")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
