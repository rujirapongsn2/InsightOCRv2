from __future__ import annotations

import io
import zipfile
from typing import Dict


SKILL_PACK_NAME = "Softnix-InsightDOC"


def _build_skill_md(api_base_url: str, external_base_url: str) -> str:
    return f"""---
name: Softnix-InsightDOC
description: Use when an AI agent needs to operate InsightDOC through the external workflow API for job management, document upload, OCR processing, review, confirmation, rejection, and integration dispatch.
---

# Softnix-InsightDOC

Use this skill when the task is to automate or assist an InsightDOC workflow through the API instead of the dashboard UI.

## Runtime Setup

- API base URL: {api_base_url}
- External API base URL: {external_base_url}
- Authentication: `Authorization: Bearer $INSIGHTOCR_API_TOKEN`
- Environment variables are stored in `.env`
- Optional helper commands are available in `scripts/insightocr.sh`

## Package Contents

- `SKILL.md`: agent instructions and workflow policy
- `.env`: editable runtime configuration
- `README.md`: setup and usage notes
- `scripts/insightocr.sh`: shell helper for the main API operations

## Operating Rules

- Prefer the external workflow endpoints under `/external` for agent-driven automation.
- Reuse an existing job when the user refers to a known batch; create a new job only when isolation is required.
- Upload documents before processing.
- If a schema is named, resolve it before processing. If no schema is provided, pass `null`.
- Poll document status until extraction is ready before attempting review actions.
- Save corrections with `reviewed_data` before issuing a final decision.
- Use `decision=confirm` to approve and `decision=reject` to reject.
- Send to integration only after the intended documents are confirmed, unless the user explicitly asks to include unconfirmed documents.
- Prefer `integration_name` over UUID when the user gives a human-readable integration label.

## Standard Workflow

1. `GET /external/jobs`
2. `POST /external/jobs`
3. `POST /external/jobs/{{job_id}}/documents`
4. `GET /external/schemas`
5. `POST /external/documents/{{document_id}}/process`
6. `GET /external/documents/{{document_id}}/status`
7. `PUT /external/documents/{{document_id}}/review`
8. `POST /external/documents/{{document_id}}/decision`
9. `GET /external/integrations`
10. `POST /external/jobs/{{job_id}}/send-integration`

## Helper Script Examples

```bash
./scripts/insightocr.sh jobs
./scripts/insightocr.sh create-job "Invoice Batch"
./scripts/insightocr.sh upload JOB_ID /absolute/path/to/file.pdf
./scripts/insightocr.sh process DOCUMENT_ID SCHEMA_ID
./scripts/insightocr.sh status DOCUMENT_ID
./scripts/insightocr.sh review DOCUMENT_ID '{{"reviewed_data": {{"document_number": "INV-0001"}}}}'
./scripts/insightocr.sh decision DOCUMENT_ID confirm
./scripts/insightocr.sh integrations
./scripts/insightocr.sh send JOB_ID "Comply TOR"
```

## Direct API Examples

```bash
curl -sS -H "Authorization: Bearer $INSIGHTOCR_API_TOKEN" \\
  {external_base_url}/jobs
```

```bash
curl -sS -X POST \\
  -H "Authorization: Bearer $INSIGHTOCR_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "name": "Agent Batch",
    "description": "Created by AI agent",
    "schema_id": null
  }}' \\
  {external_base_url}/jobs
```

```bash
curl -sS -X POST \\
  -H "Authorization: Bearer $INSIGHTOCR_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "integration_name": "Comply TOR",
    "include_unconfirmed": false
  }}' \\
  {external_base_url}/jobs/JOB_ID/send-integration
```
"""


def _build_readme(api_base_url: str, external_base_url: str) -> str:
    return f"""# Softnix-InsightDOC

This package contains a portable AI-agent skill for InsightDOC.

## Files

- `SKILL.md`: prompt and operating instructions for the agent
- `.env`: editable runtime values
- `scripts/insightocr.sh`: helper CLI for the main InsightDOC workflow

## Setup

1. Edit `.env`
2. Set `INSIGHTOCR_API_TOKEN` to a personal access token from the InsightDOC Profile page
3. Adjust optional defaults such as job name, schema id, and integration name
4. Run helper commands from the package root

## Default URLs

- API base: `{api_base_url}`
- External API base: `{external_base_url}`

## Example Commands

```bash
./scripts/insightocr.sh jobs
./scripts/insightocr.sh schemas
./scripts/insightocr.sh create-job "Invoice Batch"
./scripts/insightocr.sh upload JOB_ID /absolute/path/to/file.pdf
./scripts/insightocr.sh process DOCUMENT_ID
./scripts/insightocr.sh status DOCUMENT_ID
./scripts/insightocr.sh review DOCUMENT_ID '{{"reviewed_data": {{"document_number": "INV-001"}}}}'
./scripts/insightocr.sh decision DOCUMENT_ID confirm
./scripts/insightocr.sh integrations
./scripts/insightocr.sh send JOB_ID "Comply TOR"
```

## Notes

- Local HTTPS on localhost may require `CURL_INSECURE=true`
- The helper script expects `python3` to be available for safe JSON encoding
- You can use the API directly if your agent does not execute shell scripts
"""


def _build_env(api_base_url: str, external_base_url: str, curl_insecure: bool) -> str:
    curl_insecure_value = "true" if curl_insecure else "false"
    return f"""# Softnix-InsightDOC agent runtime configuration
# Replace the token value with your personal access token.

INSIGHTOCR_API_TOKEN=REPLACE_WITH_PERSONAL_ACCESS_TOKEN
INSIGHTOCR_API_BASE_URL={api_base_url}
INSIGHTOCR_EXTERNAL_BASE_URL={external_base_url}

# Optional defaults for your agent or helper script
INSIGHTOCR_DEFAULT_JOB_NAME=
INSIGHTOCR_DEFAULT_SCHEMA_ID=
INSIGHTOCR_DEFAULT_INTEGRATION_NAME=

# Set true only for local self-signed TLS, such as localhost or 127.0.0.1
CURL_INSECURE={curl_insecure_value}
"""


def _build_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env file at ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required env var: ${name}" >&2
    exit 1
  fi
}

require_env "INSIGHTOCR_API_TOKEN"
require_env "INSIGHTOCR_EXTERNAL_BASE_URL"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required for scripts/insightocr.sh" >&2
  exit 1
fi

CURL_CMD=(curl -sS)
if [[ "${CURL_INSECURE:-false}" == "true" ]]; then
  CURL_CMD+=(-k)
fi

AUTH_HEADER="Authorization: Bearer ${INSIGHTOCR_API_TOKEN}"

json_dump() {
  python3 - "$@" <<'PY'
import json
import sys

mode = sys.argv[1]

if mode == "create_job":
    name = sys.argv[2]
    description = sys.argv[3]
    schema_id = sys.argv[4] if len(sys.argv) > 4 else ""
    payload = {
        "name": name,
        "description": description,
        "schema_id": None if schema_id in ("", "null", "None") else schema_id,
    }
elif mode == "process":
    schema_id = sys.argv[2] if len(sys.argv) > 2 else ""
    payload = {"schema_id": None if schema_id in ("", "null", "None") else schema_id}
elif mode == "send":
    integration_name = sys.argv[2]
    include_unconfirmed = (sys.argv[3].lower() == "true") if len(sys.argv) > 3 else False
    payload = {
        "integration_name": integration_name,
        "include_unconfirmed": include_unconfirmed,
    }
elif mode == "raw":
    print(sys.argv[2])
    sys.exit(0)
else:
    raise SystemExit(f"Unknown json_dump mode: {mode}")

print(json.dumps(payload))
PY
}

request() {
  "${CURL_CMD[@]}" "$@"
}

usage() {
  cat <<'EOF'
Usage:
  ./scripts/insightocr.sh jobs
  ./scripts/insightocr.sh schemas
  ./scripts/insightocr.sh integrations
  ./scripts/insightocr.sh create-job "Job Name" ["Description"] [SCHEMA_ID]
  ./scripts/insightocr.sh upload JOB_ID /absolute/path/to/file.pdf
  ./scripts/insightocr.sh process DOCUMENT_ID [SCHEMA_ID]
  ./scripts/insightocr.sh status DOCUMENT_ID
  ./scripts/insightocr.sh review DOCUMENT_ID '{"reviewed_data":{"document_number":"INV-001"}}'
  ./scripts/insightocr.sh decision DOCUMENT_ID confirm
  ./scripts/insightocr.sh send JOB_ID "Integration Name" [true|false]
EOF
}

command="${1:-}"

case "${command}" in
  jobs)
    request -H "${AUTH_HEADER}" "${INSIGHTOCR_EXTERNAL_BASE_URL}/jobs"
    ;;
  schemas)
    request -H "${AUTH_HEADER}" "${INSIGHTOCR_EXTERNAL_BASE_URL}/schemas"
    ;;
  integrations)
    request -H "${AUTH_HEADER}" "${INSIGHTOCR_EXTERNAL_BASE_URL}/integrations"
    ;;
  create-job)
    name="${2:-${INSIGHTOCR_DEFAULT_JOB_NAME:-}}"
    description="${3:-Created by agent}"
    schema_id="${4:-${INSIGHTOCR_DEFAULT_SCHEMA_ID:-}}"
    if [[ -z "${name}" ]]; then
      echo "Job name is required" >&2
      exit 1
    fi
    payload="$(json_dump create_job "${name}" "${description}" "${schema_id}")"
    request -X POST -H "${AUTH_HEADER}" -H "Content-Type: application/json" -d "${payload}" \
      "${INSIGHTOCR_EXTERNAL_BASE_URL}/jobs"
    ;;
  upload)
    job_id="${2:-}"
    file_path="${3:-}"
    if [[ -z "${job_id}" || -z "${file_path}" ]]; then
      echo "Usage: upload JOB_ID /absolute/path/to/file" >&2
      exit 1
    fi
    request -X POST -H "${AUTH_HEADER}" -F "file=@${file_path}" \
      "${INSIGHTOCR_EXTERNAL_BASE_URL}/jobs/${job_id}/documents"
    ;;
  process)
    document_id="${2:-}"
    schema_id="${3:-${INSIGHTOCR_DEFAULT_SCHEMA_ID:-}}"
    if [[ -z "${document_id}" ]]; then
      echo "Usage: process DOCUMENT_ID [SCHEMA_ID]" >&2
      exit 1
    fi
    payload="$(json_dump process "${schema_id}")"
    request -X POST -H "${AUTH_HEADER}" -H "Content-Type: application/json" -d "${payload}" \
      "${INSIGHTOCR_EXTERNAL_BASE_URL}/documents/${document_id}/process"
    ;;
  status)
    document_id="${2:-}"
    if [[ -z "${document_id}" ]]; then
      echo "Usage: status DOCUMENT_ID" >&2
      exit 1
    fi
    request -H "${AUTH_HEADER}" "${INSIGHTOCR_EXTERNAL_BASE_URL}/documents/${document_id}/status"
    ;;
  review)
    document_id="${2:-}"
    raw_json="${3:-}"
    if [[ -z "${document_id}" || -z "${raw_json}" ]]; then
      echo "Usage: review DOCUMENT_ID '{\"reviewed_data\": {...}}'" >&2
      exit 1
    fi
    payload="$(json_dump raw "${raw_json}")"
    request -X PUT -H "${AUTH_HEADER}" -H "Content-Type: application/json" -d "${payload}" \
      "${INSIGHTOCR_EXTERNAL_BASE_URL}/documents/${document_id}/review"
    ;;
  decision)
    document_id="${2:-}"
    decision="${3:-confirm}"
    if [[ -z "${document_id}" ]]; then
      echo "Usage: decision DOCUMENT_ID confirm|reject" >&2
      exit 1
    fi
    request -X POST -H "${AUTH_HEADER}" -H "Content-Type: application/json" \
      -d "{\"decision\":\"${decision}\"}" \
      "${INSIGHTOCR_EXTERNAL_BASE_URL}/documents/${document_id}/decision"
    ;;
  send)
    job_id="${2:-}"
    integration_name="${3:-${INSIGHTOCR_DEFAULT_INTEGRATION_NAME:-}}"
    include_unconfirmed="${4:-false}"
    if [[ -z "${job_id}" || -z "${integration_name}" ]]; then
      echo "Usage: send JOB_ID \"Integration Name\" [true|false]" >&2
      exit 1
    fi
    payload="$(json_dump send "${integration_name}" "${include_unconfirmed}")"
    request -X POST -H "${AUTH_HEADER}" -H "Content-Type: application/json" -d "${payload}" \
      "${INSIGHTOCR_EXTERNAL_BASE_URL}/jobs/${job_id}/send-integration"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: ${command}" >&2
    usage >&2
    exit 1
    ;;
esac
"""


def build_skill_pack_archive(api_base_url: str, external_base_url: str, curl_insecure: bool) -> bytes:
    root = f"{SKILL_PACK_NAME}/"
    files: Dict[str, tuple[str, int]] = {
        f"{root}SKILL.md": (_build_skill_md(api_base_url, external_base_url), 0o644),
        f"{root}README.md": (_build_readme(api_base_url, external_base_url), 0o644),
        f"{root}.env": (_build_env(api_base_url, external_base_url, curl_insecure), 0o644),
        f"{root}scripts/insightocr.sh": (_build_script(), 0o755),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        directory_info = zipfile.ZipInfo(root)
        directory_info.external_attr = 0o755 << 16
        zip_file.writestr(directory_info, "")

        scripts_directory_info = zipfile.ZipInfo(f"{root}scripts/")
        scripts_directory_info.external_attr = 0o755 << 16
        zip_file.writestr(scripts_directory_info, "")

        for path, (content, file_mode) in files.items():
            file_info = zipfile.ZipInfo(path)
            file_info.external_attr = file_mode << 16
            zip_file.writestr(file_info, content)

    return buffer.getvalue()
