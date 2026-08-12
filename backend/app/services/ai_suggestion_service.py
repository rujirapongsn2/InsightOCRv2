import json
import logging
import re
from typing import List, Dict, Any, Optional
import httpx
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.models.ai_settings import AISettings
from app.schemas.ai_settings import SuggestedField, FieldSuggestionResponse

logger = logging.getLogger(__name__)


def _normalize_openai_base_url(api_url: str) -> str:
    """Accept either an OpenAI base URL or a full chat-completions URL."""
    normalized = api_url.rstrip("/")
    suffix = "/chat/completions"
    if normalized.lower().endswith(suffix):
        normalized = normalized[: -len(suffix)]
    return normalized


def _schema_suggestion_messages(ocr_content: str, document_type: Optional[str]) -> list[dict[str, str]]:
    type_hint = document_type or "the document"
    system_prompt = (
        "You design extraction schemas for an OCR document platform. "
        "Return JSON only, with no markdown or explanation. The JSON must have "
        "a top-level `fields` array. Each item must contain `name`, `type`, "
        "`description`, `required`, and optional `example_value`. Use snake_case "
        "names and only these types: text, number, date, currency, boolean. "
        "Suggest stable business fields visible in the document; do not invent fields."
    )
    user_prompt = (
        f"Suggest fields for {type_hint}.\n\n"
        "OCR/Markdown document:\n"
        f"{ocr_content}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


class AISuggestionService:
    """Service for calling external AI API to suggest fields from OCR content"""

    def __init__(self, db: Session):
        self.db = db

    def _get_ai_settings(self, provider_name: Optional[str] = None) -> AISettings:
        """Get AI settings from database"""
        if provider_name:
            settings = self.db.query(AISettings).filter(
                AISettings.name == provider_name,
                AISettings.is_active == True
            ).first()
        else:
            # Get default provider
            settings = self.db.query(AISettings).filter(
                AISettings.is_default == True,
                AISettings.is_active == True
            ).first()

        if not settings:
            # Fallback to any active provider
            settings = self.db.query(AISettings).filter(
                AISettings.is_active == True
            ).first()

        if not settings:
            raise ValueError("No active AI provider configured. Please configure AI settings first.")

        return settings

    async def suggest_fields_from_ocr(
        self,
        ocr_content: str,
        document_type: Optional[str] = None,
        provider_name: Optional[str] = None
    ) -> FieldSuggestionResponse:
        """
        Call external AI API to suggest fields based on OCR content

        Args:
            ocr_content: The OCR extracted text
            document_type: Optional document type hint
            provider_name: Optional specific provider to use

        Returns:
            FieldSuggestionResponse with suggested fields
        """
        # Get AI settings
        settings = self._get_ai_settings(provider_name)

        # Call external API
        try:
            if settings.provider_type == "openai_compatible":
                result = await self._call_openai_compatible(settings, ocr_content, document_type)
            else:
                result = await self._call_completion_messages(settings, ocr_content, document_type)

        except httpx.HTTPError as e:
            error_msg = f"Error calling AI API: {str(e)}"
            if hasattr(e, 'response') and e.response:
                error_msg += f" | Status: {e.response.status_code}"
            logger.error(error_msg)
            raise ValueError(f"Failed to call AI provider: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise ValueError(f"Unexpected error calling AI provider: {str(e)}")

        # Parse response and extract suggested fields
        suggested_fields = self._parse_ai_response(result, ocr_content)
        logger.info(
            "AI schema suggestion completed with provider '%s' (%s fields)",
            settings.display_name,
            len(suggested_fields),
        )

        # Calculate overall confidence
        if suggested_fields:
            avg_confidence = sum(f.confidence for f in suggested_fields) / len(suggested_fields)
        else:
            avg_confidence = 0.0

        return FieldSuggestionResponse(
            suggested_fields=suggested_fields,
            confidence_score=avg_confidence,
            document_preview=ocr_content[:500] if ocr_content else None,  # First 500 chars
            provider_used=settings.display_name
        )

    async def _call_openai_compatible(
        self,
        settings: AISettings,
        ocr_content: str,
        document_type: Optional[str],
    ) -> Dict[str, Any]:
        """Call providers exposing the standard /chat/completions contract."""
        client_kwargs: dict[str, Any] = {
            "api_key": settings.api_key,
            "base_url": _normalize_openai_base_url(settings.api_url),
            "timeout": 60.0,
            "max_retries": 0,
        }
        async with AsyncOpenAI(**client_kwargs) as client:
            response = await client.chat.completions.create(
                model=settings.model or "gpt-4o-mini",
                messages=_schema_suggestion_messages(ocr_content, document_type),
                temperature=0.1,
            )

        content = ""
        if response.choices:
            content = (response.choices[0].message.content or "").strip()
        if not content:
            raise ValueError("AI provider returned an empty response")
        return {"answer": content}

    async def _call_completion_messages(
        self,
        settings: AISettings,
        ocr_content: str,
        document_type: Optional[str],
    ) -> Dict[str, Any]:
        """Call legacy completion-messages providers without changing their contract."""
        payload = {
            "inputs": {"ocr_content": ocr_content},
            "user": "insightocr_system",
            "citation": True,
            "response_mode": "blocking",
        }
        if document_type:
            payload["inputs"]["document_type"] = document_type

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                settings.api_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise ValueError("AI provider returned a non-JSON response") from exc

    def _parse_ai_response(self, ai_response: Dict[str, Any], ocr_content: str) -> List[SuggestedField]:
        """
        Parse the AI response and extract suggested fields

        The external API returns a response with the answer in the 'answer' field.
        We need to parse this and extract structured field suggestions.
        """
        suggested_fields = []

        try:
            # Get the answer from AI response
            answer = ai_response.get("answer", "")
            # Strip markdown code blocks if present
            if "```json" in answer:
                answer = answer.split("```json")[1].split("```")[0].strip()
            elif "```" in answer:
                answer = answer.split("```")[1].split("```")[0].strip()

            # Try to parse as JSON if the answer contains JSON
            if "{" in answer and "}" in answer:
                try:
                    # Extract JSON from the answer
                    json_start = answer.find("{")
                    json_end = answer.rfind("}") + 1
                    json_str = answer[json_start:json_end]
                    parsed = json.loads(json_str)

                    # Handle JSON Schema format (properties + required)
                    if "properties" in parsed:
                        properties = parsed.get("properties", {})
                        required_fields = parsed.get("required", [])

                        for field_name, field_schema in properties.items():
                            # Map JSON Schema types to our types
                            json_type = field_schema.get("type", "string")
                            field_type = self._map_json_schema_type(json_type, field_schema.get("format"), field_schema)

                            suggested_fields.append(SuggestedField(
                                name=self._to_snake_case(field_name),
                                type=field_type,
                                description=field_schema.get("description", ""),
                                required=field_name in required_fields,
                                confidence=0.85,  # Default confidence for schema-based fields
                                example_value=field_schema.get("example")
                            ))

                    # Handle custom fields array format
                    elif "fields" in parsed:
                        for field_data in parsed["fields"]:
                            suggested_fields.append(SuggestedField(
                                name=field_data.get("name", ""),
                                type=field_data.get("type", "text"),
                                description=field_data.get("description", ""),
                                required=field_data.get("required", False),
                                confidence=field_data.get("confidence", 0.7),
                                example_value=field_data.get("example_value")
                            ))

                    # Handle array of fields directly
                    elif isinstance(parsed, list):
                        for field_data in parsed:
                            suggested_fields.append(SuggestedField(
                                name=field_data.get("name", ""),
                                type=field_data.get("type", "text"),
                                description=field_data.get("description", ""),
                                required=field_data.get("required", False),
                                confidence=field_data.get("confidence", 0.7),
                                example_value=field_data.get("example_value")
                            ))

                except json.JSONDecodeError as e:
                    logger.warning(f"Could not parse AI response as JSON: {e}")

            if not suggested_fields:
                suggested_fields.extend(self._parse_labeled_answer(answer))

            if not suggested_fields:
                logger.warning("No structured fields found in AI response")

        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}")

        return suggested_fields

    def _parse_labeled_answer(self, answer: str) -> List[SuggestedField]:
        fields: List[SuggestedField] = []
        seen: set[str] = set()

        for raw_line in answer.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[-*\d.\)\s]+", "", line).strip()
            line = line.replace("**", "").replace("__", "").strip()
            if ":" in line:
                label, value = line.split(":", 1)
            else:
                invoice_match = re.fullmatch(r"(?i)(invoice)\s*#\s*(.+)", line)
                if not invoice_match:
                    continue
                label = "Invoice Number"
                value = invoice_match.group(2)
            label = label.strip(" -–—	")
            value = value.strip()
            if not label or len(label) > 80:
                continue

            field_name = self._to_snake_case(label)
            if not field_name or field_name in seen:
                continue
            seen.add(field_name)

            fields.append(SuggestedField(
                name=field_name,
                type=self._infer_field_type(label, value),
                description=f"Extract the {label} from the document.",
                required=False,
                confidence=0.7,
                example_value=value or None,
            ))

        return fields

    def _to_snake_case(self, value: str) -> str:
        value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
        value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
        return re.sub(r"_+", "_", value)

    def _infer_field_type(self, label: str, value: str) -> str:
        text = f"{label} {value}".lower()
        if any(word in text for word in ["date", "วันที่"]):
            return "date"
        if any(symbol in value for symbol in ["$", "฿", "€", "£"]):
            return "currency"
        if any(word in text for word in ["amount", "total", "price", "cost", "ยอด", "ราคา"]):
            return "currency"
        normalized = value.replace(",", "").strip()
        if normalized and re.fullmatch(r"[-+]?\d+(\.\d+)?", normalized):
            return "number"
        if normalized.lower() in {"true", "false", "yes", "no"}:
            return "boolean"
        return "text"

    def _map_json_schema_type(
        self,
        json_type: str,
        json_format: Optional[str] = None,
        field_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Map JSON Schema types to field types used by the app."""
        if isinstance(json_type, list):
            json_type = next((item for item in json_type if item != "null"), "string")

        if json_format in {"date", "date-time"}:
            return "date"
        if json_type in {"number", "integer"}:
            return "number"
        if json_type == "boolean":
            return "boolean"
        if json_type == "array":
            return "array"

        schema_text = json.dumps(field_schema or {}, ensure_ascii=False).lower()
        if any(token in schema_text for token in ["currency", "amount", "total", "price", "ยอด", "ราคา"]):
            return "currency"

        return "text"

    async def test_ai_connection(self, provider_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Test connection to AI provider

        Args:
            provider_name: Optional specific provider to test

        Returns:
            Dict with test results
        """
        try:
            settings = self._get_ai_settings(provider_name)

            # Simple test with minimal OCR content
            test_content = "Invoice #123\nDate: 2024-01-01\nTotal: $100.00"

            response = await self.suggest_fields_from_ocr(
                ocr_content=test_content,
                provider_name=provider_name
            )

            return {
                "success": True,
                "provider": settings.display_name,
                "message": "Connection successful",
                "fields_suggested": len(response.suggested_fields)
            }

        except Exception as e:
            return {
                "success": False,
                "provider": provider_name or "default",
                "message": f"Connection failed: {str(e)}"
            }
