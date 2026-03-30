from typing import List, Optional, Any, Dict, Union
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class DocumentBase(BaseModel):
    filename: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None

class DocumentCreate(DocumentBase):
    job_id: UUID
    file_path: str

class DocumentUpdate(BaseModel):
    status: Optional[str] = None
    schema_id: Optional[UUID] = None
    extracted_data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
    reviewed_data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
    review_decision: Optional[str] = None

class Document(DocumentBase):
    id: UUID
    job_id: UUID
    status: str
    file_path: str
    schema_id: Optional[UUID] = None
    ocr_text: Optional[str] = None
    extracted_data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
    reviewed_data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
    review_decision: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[UUID] = None
    uploaded_at: datetime
    page_count: Optional[int] = None
    ocr_pages: Optional[List[Dict[str, Any]]] = None
    processing_error: Optional[str] = None

    class Config:
        from_attributes = True
