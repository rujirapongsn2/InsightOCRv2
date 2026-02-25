"""
test_stream.py
==============
ทดสอบ SSE stream endpoint: /v3/ai-process-file/{job_id}/stream
เพื่อดู event format ที่ส่งมา (status, progress.percent, progress.stage)
"""
import json
import os
import sys
import urllib3
from pathlib import Path

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://111.223.37.41:9001"
API_USERNAME = os.environ.get("API_USERNAME", "admin")
API_PASSWORD = os.environ.get("API_PASSWORD", "admin")
API_TOKEN = os.environ.get("API_TOKEN", "")
TEST_FILE = Path(__file__).parent / "01_Purchase_Order_PO-2026-0210.pdf"


def login() -> str:
    if API_TOKEN:
        return API_TOKEN
    r = requests.post(
        f"{BASE_URL}/login",
        data={"username": API_USERNAME, "password": API_PASSWORD},
        verify=False,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token") or data.get("data", {}).get("access_token")
    if not token:
        raise ValueError(f"Login failed: {data}")
    print(f"[login] token={token[:30]}...")
    return token


def submit_job(token: str) -> str:
    if not TEST_FILE.exists():
        raise FileNotFoundError(f"Test file not found: {TEST_FILE}")
    headers = {"Authorization": f"Bearer {token}"}
    with open(TEST_FILE, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/v3/ai-process-file",
            headers=headers,
            files={"file": (TEST_FILE.name, f, "application/pdf")},
            data={"settings": json.dumps({"ocr_engine": "tesseract", "model": ""})},
            verify=False,
            timeout=30,
        )
    r.raise_for_status()
    data = r.json()
    job_id = (
        data.get("job_id")
        or data.get("id")
        or data.get("data", {}).get("job_id")
    )
    if not job_id:
        raise ValueError(f"No job_id in submit response: {data}")
    print(f"[submit] job_id={job_id}")
    return job_id


def stream_job(token: str, job_id: str):
    stream_url = f"{BASE_URL}/v3/ai-process-file/{job_id}/stream"
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    print(f"\n[stream] connecting to {stream_url}\n{'='*60}")
    with requests.get(stream_url, headers=headers, verify=False, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        event_type = None
        data_lines = []
        for raw in resp.iter_lines(decode_unicode=True):
            if raw.startswith("event:"):
                event_type = raw[6:].strip()
            elif raw.startswith("data:"):
                data_lines.append(raw[5:].strip())
            elif raw == "":
                # End of event block
                if data_lines:
                    raw_data = "\n".join(data_lines)
                    try:
                        obj = json.loads(raw_data)
                        status = obj.get("status", "")
                        prog = obj.get("progress", {})
                        percent = prog.get("percent", "-") if isinstance(prog, dict) else "-"
                        stage = prog.get("stage", "-") if isinstance(prog, dict) else "-"
                        print(f"[event={event_type or 'message'}] status={status!r:20s} percent={percent!r:6s} stage={stage!r}")
                        if status in {"completed", "success", "done", "failed", "error"}:
                            print(f"\n[stream] terminal status reached: {status}")
                            return
                    except json.JSONDecodeError:
                        print(f"[event={event_type or 'message'}] raw={raw_data[:200]}")
                event_type = None
                data_lines = []


def main():
    token = login()
    job_id = submit_job(token)
    stream_job(token, job_id)


if __name__ == "__main__":
    main()
