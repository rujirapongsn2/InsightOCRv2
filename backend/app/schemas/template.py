from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


class TemplateField(BaseModel):
    """Field definition in a template"""
    name: str
    type: str  # text, number, date, currency, boolean
    description: Optional[str] = None
    required: bool = False
    validation_rules: Optional[Dict[str, Any]] = None
    help_text: Optional[str] = None
    example: Optional[str] = None
    order: int = 0


class SchemaTemplateBase(BaseModel):
    """Base schema for template"""
    name: str
    description: Optional[str] = None
    document_type: str
    category: str = "general"
    thumbnail_url: Optional[str] = None
    fields: List[TemplateField] = []


class SchemaTemplateCreate(SchemaTemplateBase):
    """Schema for creating a template"""
    is_system_template: bool = False


class SchemaTemplateUpdate(BaseModel):
    """Schema for updating a template (all fields optional)"""
    name: Optional[str] = None
    description: Optional[str] = None
    document_type: Optional[str] = None
    category: Optional[str] = None
    thumbnail_url: Optional[str] = None
    fields: Optional[List[TemplateField]] = None
    is_active: Optional[bool] = None


class SchemaTemplate(SchemaTemplateBase):
    """Schema for template response"""
    id: UUID
    is_system_template: bool
    usage_count: int
    created_by: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Optional creator info (populated from relationship)
    created_by_email: Optional[str] = None
    created_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class SchemaTemplateList(BaseModel):
    """Schema for list of templates with metadata"""
    templates: List[SchemaTemplate]
    total: int
    categories: List[str]
