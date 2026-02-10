import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from sqlalchemy.orm import Session

from app.models.ai_settings import AISettings
from app.schemas.ai_settings import SuggestedField, FieldSuggestionResponse

logger = logging.getLogger(__name__)


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

        # Prepare request payload
        payload = {
            "inputs": {
                "ocr_content": ocr_content
            },
            "user": "insightocr_system",
            "citation": True,
            "response_mode": "blocking"
        }

        # Add document type to inputs if provided
        if document_type:
            payload["inputs"]["document_type"] = document_type

        # Call external API
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    settings.api_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                response.raise_for_status()
                result = response.json()

        except httpx.HTTPError as e:
            error_msg = f"Error calling AI API: {str(e)}"
            if hasattr(e, 'response') and e.response:
                error_msg += f" | Status: {e.response.status_code} | Body: {e.response.text}"
            logger.error(error_msg)
            raise ValueError(f"Failed to call AI provider: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise ValueError(f"Unexpected error calling AI provider: {str(e)}")

        # Log the raw response for debugging
        logger.info(f"AI API Response: {json.dumps(result, indent=2)}")
        print("=" * 80)
        print("AI API RAW RESPONSE:")
        print(json.dumps(result, indent=2))
        print("=" * 80)

        # Parse response and extract suggested fields
        suggested_fields = self._parse_ai_response(result, ocr_content)

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
            logger.info(f"Parsing AI answer: {answer[:500]}...")  # Log first 500 chars
            print("-" * 80)
            print(f"ANSWER FIELD VALUE: {answer}")
            print("-" * 80)

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
                            field_type = self._map_json_schema_type(json_type)

                            suggested_fields.append(SuggestedField(
                                name=field_name,
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

            # Fallback: If no structured data found, return empty list
            # In production, you might want to have better parsing logic
            # based on your specific AI provider's response format
            if not suggested_fields:
                logger.warning("No structured fields found in AI response")

        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}")

        return suggested_fields

    def _map_json_schema_type(self, json_type: str) -> str:
        """
        Map JSON Schema types to our field types

        Args:
            json_type: JSON Schema type (string, number, integer, boolean)

        Returns:
            Our field type (text, number, date, currency, boolean)
        """
        type_mapping = {
            "string": "text",
            "number": "number",
            "integer": "number",
            "boolean": "boolean",
            "date": "date",
            "date-time": "date"
        }
        return type_mapping.get(json_type, "text")

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
