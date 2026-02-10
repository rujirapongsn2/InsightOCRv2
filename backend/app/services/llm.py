import json
from typing import Dict, Any, List
from openai import OpenAI
from app.core.config import settings

class LLMService:
    def __init__(self):
        # Initialize OpenAI client
        # We assume OPENAI_API_KEY is set in env or settings
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    async def extract_data(self, text: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract data from text based on the provided schema.
        """
        if not text:
            return {}

        # Construct prompt based on schema fields
        fields_desc = []
        for field in schema.get("fields", []):
            desc = f"- {field['name']} ({field['type']}): {field.get('description', '')}"
            fields_desc.append(desc)
        
        fields_str = "\n".join(fields_desc)
        
        system_prompt = f"""You are an expert data extraction assistant. 
Your task is to extract structured data from the provided document text.
Return the output strictly as a JSON object.

Target Fields:
{fields_str}

Rules:
1. Extract only the fields listed above.
2. If a field is not found, set it to null.
3. Format dates as YYYY-MM-DD.
4. Do not include any markdown formatting (like ```json), just the raw JSON string.
"""

        user_prompt = f"Document Text:\n{text}"

        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo-0125", # Cost-effective model for quickwin
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            print(f"LLM Extraction Error: {e}")
            return {"error": str(e)}

llm_service = LLMService()
