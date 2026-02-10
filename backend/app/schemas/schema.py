from typing import List, Optional, Any, Dict
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class SchemaField(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    required: bool = False
    validation_rules: Optional[Dict[str, Any]] = None

class DocumentSchemaBase(BaseModel):
    name: str
    description: Optional[str] = None
    document_type: str
    ocr_engine: Optional[str] = "tesseract"
    fields: List[SchemaField] = []

class DocumentSchemaCreate(DocumentSchemaBase):
    pass

class DocumentSchemaUpdate(DocumentSchemaBase):
    name: Optional[str] = None
    description: Optional[str] = None
    document_type: Optional[str] = None
    ocr_engine: Optional[str] = None
    fields: Optional[List[SchemaField]] = None

class DocumentSchema(DocumentSchemaBase):
    id: UUID
    created_by: Optional[UUID] = None
    created_by_email: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
