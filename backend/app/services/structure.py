import requests
import urllib3
import json
from sqlalchemy.orm import Session
from app.models.setting import Setting

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    
    if not setting.api_endpoint or not setting.api_token:
        raise ValueError(
            "API Endpoint and Token are required. Please configure them in /settings page."
        )
    
    base_api_url = setting.api_endpoint
    api_key = setting.api_token
    verify_ssl = setting.verify_ssl if setting.verify_ssl is not None else False
    
    # Replace /ai-process-file with /structured-output
    structure_api_url = base_api_url.replace('/ai-process-file', '/structured-output')

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
            verify=verify_ssl
        )
        
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Structure API Request failed: {e}")
        raise
    except Exception as e:
        print(f"An error occurred during structure extraction: {e}")
        raise
