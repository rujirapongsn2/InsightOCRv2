import re
from typing import List, Optional, Any, Dict, Literal
from pydantic import BaseModel, model_validator
from uuid import UUID
from datetime import datetime

FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


class ArrayColumn(BaseModel):
    """One column inside a fixed-position table BBox.

    ``x`` and ``width`` are percentages relative to the parent field BBox, not
    to the PDF page. This keeps a table definition readable and stable when its
    parent rectangle moves or is resized in the schema editor.
    """

    name: str
    type: Literal["text", "number", "date", "currency"] = "text"
    x: float
    width: float

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ArrayColumn":
        if not FIELD_NAME_PATTERN.fullmatch(self.name):
            raise ValueError(
                f'Invalid array column name "{self.name}". Use English letters, numbers, and underscores only.'
            )
        if self.x < 0 or self.width <= 0 or self.x + self.width > 100:
            raise ValueError("Array column must remain inside the parent BBox (0-100%)")
        return self


class ArrayConfig(BaseModel):
    """Deterministic row and column settings for a BBox array field."""

    item_type: Literal["object"] = "object"
    row_detection: Literal["anchor_column", "line"] = "anchor_column"
    anchor_column: Optional[str] = None
    header_rows: int = 1
    columns: List[ArrayColumn]

    @model_validator(mode="after")
    def _validate_columns(self) -> "ArrayConfig":
        if not self.columns:
            raise ValueError("An array field must define at least one column")
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("Array column names must be unique")
        if self.header_rows < 0:
            raise ValueError("Array header rows cannot be negative")
        ordered_columns = sorted(self.columns, key=lambda column: column.x)
        if any(
            current.x + current.width > following.x
            for current, following in zip(ordered_columns, ordered_columns[1:])
        ):
            raise ValueError("Array columns cannot overlap")
        if self.row_detection == "anchor_column":
            if not self.anchor_column or self.anchor_column not in names:
                raise ValueError("Anchor row detection requires one selected array column")
        return self


class SchemaField(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    required: bool = False
    validation_rules: Optional[Dict[str, Any]] = None
    locator: Optional[BboxLocator] = None
    array_config: Optional[ArrayConfig] = None

    @model_validator(mode="after")
    def _validate_array_config(self) -> "SchemaField":
        if self.array_config and self.type != "array":
            raise ValueError("array_config can only be used with an array field")
        if self.type == "array" and self.locator and not self.array_config:
            raise ValueError("A fixed-position array field must define array_config")
        return self


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
