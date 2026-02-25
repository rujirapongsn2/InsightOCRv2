import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from sqlalchemy.orm import Session

from app.models.setting import Setting


class SchemaSuggestionService:
    def __init__(self, db: Session):
        self.db = db

    def suggest_from_file(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        document_type: str | None = None,
    ) -> dict[str, Any]:
        setting = self.db.query(Setting).first()
        if not setting:
            raise ValueError("Settings are not configured")

        endpoint = setting.schema_suggestion_endpoint
        token = setting.api_token
        verify_ssl = setting.verify_ssl if setting.verify_ssl is not None else False

        if not endpoint or not token:
            raise ValueError("Schema Suggestion Endpoint and Bearer Token are required in Settings")

        headers = {"Authorization": f"Bearer {token}"}
        files = {
            "file": (filename, file_bytes, content_type or "application/octet-stream")
        }
        data: dict[str, str] = {}
        if document_type:
            data["document_type"] = document_type

        submit_resp = requests.post(
            endpoint,
            headers=headers,
            files=files,
            data=data,
            timeout=120,
            verify=verify_ssl,
        )
        submit_resp.raise_for_status()
        submit_payload = submit_resp.json()

        final_payload = submit_payload
        schema_obj = submit_payload.get("schema")

        if not schema_obj:
            job_id = submit_payload.get("job_id")
            if not job_id:
                raise ValueError("Schema suggestion API did not return schema or job_id")

            status_url = self._build_job_url(endpoint, job_id, "status")
            result_url = self._build_job_url(endpoint, job_id, "result")

            for _ in range(60):
                status_resp = requests.get(
                    status_url,
                    headers=headers,
                    timeout=30,
                    verify=verify_ssl,
                )
                status_resp.raise_for_status()
                status_payload = status_resp.json()
                status = (status_payload.get("status") or "").lower()

                if status in {"completed", "success"}:
                    result_resp = requests.get(
                        result_url,
                        headers=headers,
                        timeout=60,
                        verify=verify_ssl,
                    )
                    result_resp.raise_for_status()
                    final_payload = result_resp.json()
                    schema_obj = final_payload.get("schema")
                    break

                if status in {"failed", "error"}:
                    raise ValueError(f"Schema suggestion failed: {status_payload}")

                time.sleep(2)

        if not schema_obj:
            raise ValueError("Unable to fetch schema suggestion result")

        return {
            "schema": schema_obj,
            "suggested_fields": self._schema_to_fields(schema_obj),
            "raw_result": final_payload,
        }

    def _build_job_url(self, endpoint: str, job_id: str, action: str) -> str:
        parsed = urlparse(endpoint)
        base = f"{parsed.scheme}://{parsed.netloc}"
        return urljoin(base, f"/suggest-schema/{job_id}/{action}")

    def _schema_to_fields(self, schema: dict[str, Any]) -> list[dict[str, Any]]:
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        fields: list[dict[str, Any]] = []

        for field_name, field_schema in properties.items():
            json_type = field_schema.get("type", "string")
            field_type = self._map_type(json_type, field_schema.get("format"))
            fields.append(
                {
                    "name": field_name,
                    "type": field_type,
                    "description": field_schema.get("description", ""),
                    "required": field_name in required,
                }
            )

        return fields

    def _map_type(self, json_type, json_format: str | None) -> str:
        # Handle nullable types e.g. ["string", "null"] — extract the non-null type
        if isinstance(json_type, list):
            json_type = next((t for t in json_type if t != "null"), "string")
        if json_type == "array":
            return "array"
        if json_type in {"number", "integer"}:
            return "number"
        if json_type == "boolean":
            return "boolean"
        if json_format in {"date", "date-time"}:
            return "date"
        return "text"
