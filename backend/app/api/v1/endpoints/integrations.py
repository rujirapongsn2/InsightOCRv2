from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from openai import OpenAI
from app.api import deps
from app.models.user import User
import json

router = APIRouter()


class TestLLMRequest(BaseModel):
    apiKey: str
    baseUrl: Optional[str] = None
    model: str
    reasoningEffort: str = "low"
    instructions: str
    testInput: str


class TestLLMResponse(BaseModel):
    output: str


from typing import Optional, List, Dict, Any, Union

class DocumentInput(BaseModel):
    id: str
    filename: str
    data: Optional[Union[Dict[str, Any], List[Any], Any]] = None


class SendLLMRequest(BaseModel):
    apiKey: str
    baseUrl: Optional[str] = None
    model: str
    reasoningEffort: str = "low"
    instructions: str
    documents: List[DocumentInput]


class DocumentResult(BaseModel):
    id: str
    filename: str
    output: str
    success: bool
    error: Optional[str] = None


class SendLLMResponse(BaseModel):
    results: List[DocumentResult]


@router.post("/test-llm", response_model=TestLLMResponse)
async def test_llm(
    request: TestLLMRequest,
    current_user: User = Depends(deps.get_current_user)
):
    """
    Test LLM configuration by sending a test request to OpenAI Responses API
    """
    try:
        # Initialize OpenAI client with provided credentials
        client_kwargs = {"api_key": request.apiKey}
        if request.baseUrl:
            client_kwargs["base_url"] = request.baseUrl
        
        client = OpenAI(**client_kwargs)
        
        # Call OpenAI Responses API
        response = client.responses.create(
            model=request.model,
            reasoning={"effort": request.reasoningEffort},
            instructions=request.instructions,
            input=request.testInput,
        )
        
        # Extract output text
        output_text = response.output_text if hasattr(response, 'output_text') else str(response)
        
        return TestLLMResponse(output=output_text)
    
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"LLM test failed: {str(e)}"
        )


@router.post("/send-llm", response_model=SendLLMResponse)
async def send_to_llm(
    request: SendLLMRequest,
    current_user: User = Depends(deps.get_current_user)
):
    """
    Process multiple documents with LLM using configured instructions
    """
    results = []
    
    try:
        # Initialize OpenAI client with provided credentials
        client_kwargs = {"api_key": request.apiKey}
        if request.baseUrl:
            client_kwargs["base_url"] = request.baseUrl
        
        client = OpenAI(**client_kwargs)
        
        for doc in request.documents:
            try:
                # Convert document data to string input
                doc_input = json.dumps(doc.data, ensure_ascii=False, indent=2) if doc.data else "No data"
                
                # Call OpenAI Responses API
                response = client.responses.create(
                    model=request.model,
                    reasoning={"effort": request.reasoningEffort},
                    instructions=request.instructions,
                    input=f"Document: {doc.filename}\n\nData:\n{doc_input}",
                )
                
                # Extract output text
                output_text = response.output_text if hasattr(response, 'output_text') else str(response)
                
                results.append(DocumentResult(
                    id=doc.id,
                    filename=doc.filename,
                    output=output_text,
                    success=True
                ))
            except Exception as e:
                results.append(DocumentResult(
                    id=doc.id,
                    filename=doc.filename,
                    output="",
                    success=False,
                    error=str(e)
                ))
        
        return SendLLMResponse(results=results)
    
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"LLM processing failed: {str(e)}"
        )
