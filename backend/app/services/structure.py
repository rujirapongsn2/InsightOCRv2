import requests
import json
import logging
from sqlalchemy.orm import Session
from app.models.setting import Setting
from app.services.tls import get_verify_ssl

logger = logging.getLogger(__name__)

def extract_structure(context: str, schema_json: str, db: Session, prompt: str = "Please return the extracted information in JSON format that matches the schema.") -> dict:
    """
    Extract structured data from context using a JSON schema.
    
    Args:
        context: The text context to extract from (e.g., OCR result).
        schema_json: The JSON schema string defining the structure.
        db: Database session to fetch settings.
        
    Returns:
        A dictionary containing the structured output.
    """
    # Fetch settings from database
    setting = db.query(Setting).first()
    if not setting:
        raise ValueError(
            "API Settings not configured. Please configure the following in /settings page:\n"
            "- API Endpoint\n"
            "- API Token"
        )
    
    if not setting.api_token:
        raise ValueError(
            "API Endpoint and Token are required. Please configure them in /settings page."
        )
    
    api_key = setting.api_token
    verify_ssl = get_verify_ssl(setting, "structured extraction provider requests")
    structure_api_url = setting.structured_output_endpoint
    if not structure_api_url and setting.api_endpoint:
        structure_api_url = setting.api_endpoint.replace('/ai-process-file', '/structured-output')
    if not structure_api_url:
        raise ValueError("Structured Output Endpoint and API Token are required. Please configure them in Settings.")

    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'context': context,
        'json_schema': schema_json,
        'prompt': prompt
    }

    try:
        response = requests.post(
            structure_api_url,
            headers=headers,
            data=data,
            verify=verify_ssl,
            timeout=120,
        )
        
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.warning("Structured extraction request failed: %s", e)
        raise
    except Exception as e:
        logger.exception("Structured extraction failed: %s", e)
        raise
