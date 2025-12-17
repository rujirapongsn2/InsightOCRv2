import requests
import urllib3
import os
from sqlalchemy.orm import Session
from app.models.setting import Setting
from pypdf import PdfReader
from datetime import datetime

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def count_pdf_pages(file_path: str) -> int:
    """
    Count the number of pages in a PDF file.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Number of pages in the PDF.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file is not a valid PDF.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' not found.")

    try:
        reader = PdfReader(file_path)
        return len(reader.pages)
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {str(e)}")

def process_ocr(file_path: str, db: Session, page_number: int = 1) -> dict:
    """
    Process a specific page of a file using the external OCR service.

    Args:
        file_path: Path to the file to process.
        db: Database session to fetch settings.
        page_number: Specific page number to process (default: 1).

    Returns:
        A dictionary containing the OCR result for the specified page.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' not found.")

    # Fetch settings from database
    setting = db.query(Setting).first()
    if not setting:
        raise ValueError(
            "API Settings not configured. Please configure the following in /settings page:\n"
            "- OCR Endpoint\n"
            "- API Token\n"
            "- OCR Engine (optional)\n"
            "- Model (optional)"
        )

    # Use ocr_endpoint, fallback to legacy api_endpoint if not set
    ocr_api_url = setting.ocr_endpoint or setting.api_endpoint

    if not ocr_api_url or not setting.api_token:
        raise ValueError(
            "OCR Endpoint and API Token are required. Please configure them in /settings page."
        )
    api_key = setting.api_token
    verify_ssl = setting.verify_ssl if setting.verify_ssl is not None else False

    # If 'default', send empty string to let External API use its own default
    ocr_engine = '' if not setting.ocr_engine or setting.ocr_engine == 'default' else setting.ocr_engine
    model = '' if not setting.model or setting.model == 'default' else setting.model

    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }

    data = {
        'pages': str(page_number),  # Process specific page number
        'prompt': '',
        'ocr_engine': ocr_engine,
        'model': model
    }

    try:
        # Determine file content type based on extension
        file_ext = os.path.splitext(file_path)[1].lower()
        content_type = 'application/pdf' if file_ext == '.pdf' else f'image/{file_ext[1:]}'

        # Debug logging
        print("=" * 80)
        print("OCR REQUEST DEBUG:")
        print(f"URL: {ocr_api_url}")
        print(f"File: {os.path.basename(file_path)}")
        print(f"Content-Type: {content_type}")
        print(f"Headers: {headers}")
        print(f"Data: {data}")
        print("=" * 80)

        with open(file_path, 'rb') as f:
            files = {
                'file': (os.path.basename(file_path), f, content_type)
            }

            response = requests.post(
                ocr_api_url,
                headers=headers,
                data=data,
                files=files,
                verify=verify_ssl
            )

            # Log response details before raising error
            print("=" * 80)
            print("OCR RESPONSE DEBUG:")
            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            print(f"Response Body: {response.text[:500]}")  # First 500 chars
            print("=" * 80)

            response.raise_for_status()
            result = response.json()
            
            # Debug: Print the API response
            print("=" * 80)
            print("OCR API Response:")
            print(f"Status: {result.get('status')}")
            print(f"Filename: {result.get('filename')}")
            if 'results' in result:
                print(f"Results keys: {result['results'].keys()}")
                if 'pages' in result['results']:
                    print(f"Number of pages: {len(result['results']['pages'])}")
                    if result['results']['pages']:
                        first_page = result['results']['pages'][0]
                        print(f"First page keys: {first_page.keys()}")

                        # Check ai_processing type and content
                        ai_proc = first_page.get('ai_processing')
                        print(f"AI Processing type: {type(ai_proc)}, value: {ai_proc}")

                        # Check ocr_text content
                        ocr_text = first_page.get('ocr_text', '')
                        print(f"OCR Text type: {type(ocr_text)}, length: {len(ocr_text)}")
                        print(f"OCR Text preview (first 200 chars): {ocr_text[:200]}")

                        if isinstance(ai_proc, dict):
                            print(f"AI Processing Success: {ai_proc.get('success')}")
                            content = ai_proc.get('content', '')
                            print(f"AI Content length: {len(content)}")
                            print(f"AI Content preview (first 200 chars): {content[:200]}")
            print("=" * 80)
            
            return result
            
    except requests.exceptions.RequestException as e:
        print(f"OCR API Request failed: {e}")
        raise
    except Exception as e:
        print(f"An error occurred during OCR processing: {e}")
        raise
