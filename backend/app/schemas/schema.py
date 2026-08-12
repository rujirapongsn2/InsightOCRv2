import re
from typing import List, Optional, Any, Dict, Literal
from pydantic import BaseModel, model_validator
from uuid import UUID
from datetime import datetime

class BboxLocator(BaseModel):
    """A fixed rectangle in percent coordinates, using a top-left origin."""

    type: Literal["bbox"] = "bbox"
    page: int
    x: float
    y: float
    width: float
    height: float
    clean_placeholders: bool = True

    @model_validator(mode="after")
    def _validate_bounds(self) -> "BboxLocator":
        if self.page < 1:
            raise ValueError("BBox page must be 1 or greater")
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError("BBox coordinates must be positive")
        if self.x + self.width > 100 or self.y + self.height > 100:
            raise ValueError("BBox must remain inside the page (0-100%)")
        return self


class SchemaField(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    required: bool = False
    validation_rules: Optional[Dict[str, Any]] = None
    locator: Optional[BboxLocator] = None


FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_field_names(fields: List[SchemaField] | None) -> None:
    if fields is None:
        return
    names: set[str] = set()
    for field in fields:
        if not FIELD_NAME_PATTERN.fullmatch(field.name):
            raise ValueError(
                f'Invalid field name "{field.name}". Use English letters, numbers, and underscores only; '
                "the name must start with a letter or underscore."
            )
        if field.name in names:
            raise ValueError(f'Duplicate field name "{field.name}".')
        names.add(field.name)

ExtractionProfile = Literal["legacy", "anydoc_hybrid"]


class DocumentSchemaBase(BaseModel):
    name: str
    description: Optional[str] = None
    document_type: str
    ocr_engine: Optional[str] = "tesseract"
    extraction_profile: ExtractionProfile = "anydoc_hybrid"
    fields: List[SchemaField] = []

class DocumentSchemaCreate(DocumentSchemaBase):
    @model_validator(mode="after")
    def _validate_names(self) -> "DocumentSchemaCreate":
        _validate_field_names(self.fields)
        return self

class DocumentSchemaUpdate(DocumentSchemaBase):
    name: Optional[str] = None
    description: Optional[str] = None
    document_type: Optional[str] = None
    ocr_engine: Optional[str] = None
    extraction_profile: Optional[ExtractionProfile] = None
    fields: Optional[List[SchemaField]] = None

    @model_validator(mode="after")
    def _validate_names(self) -> "DocumentSchemaUpdate":
        _validate_field_names(self.fields)
        return self

class DocumentSchema(DocumentSchemaBase):
    id: UUID
    created_by: Optional[UUID] = None
    created_by_email: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
