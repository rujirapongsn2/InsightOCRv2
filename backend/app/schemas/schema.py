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
    """One column of a table (array) field.

    For a fixed-position table, ``x`` and ``width`` are percentages relative to
    the parent field BBox, not to the PDF page, so the definition stays stable
    when the parent rectangle moves. A text-mapped table (no BBox) only needs
    ``name`` and ``type``; the mapping engines read the columns as item
    properties.
    """

    name: str
    type: Literal["text", "number", "date", "currency"] = "text"
    x: Optional[float] = None
    width: Optional[float] = None

    @property
    def positioned(self) -> bool:
        return self.x is not None and self.width is not None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ArrayColumn":
        if not FIELD_NAME_PATTERN.fullmatch(self.name):
            raise ValueError(
                f'Invalid array column name "{self.name}". Use English letters, numbers, and underscores only.'
            )
        if (self.x is None) != (self.width is None):
            raise ValueError("Array column needs both x and width, or neither")
        if self.positioned and (self.x < 0 or self.width <= 0 or self.x + self.width > 100):
            raise ValueError("Array column must remain inside the parent BBox (0-100%)")
        return self


class ArrayConfig(BaseModel):
    """Row and column settings for an array field (BBox or text-mapped)."""

    item_type: Literal["object"] = "object"
    row_detection: Literal["anchor_column", "line"] = "anchor_column"
    anchor_column: Optional[str] = None
    header_rows: int = 1
    columns: List[ArrayColumn]

    @property
    def positioned(self) -> bool:
        return all(column.positioned for column in self.columns)

    @model_validator(mode="after")
    def _validate_columns(self) -> "ArrayConfig":
        if not self.columns:
            raise ValueError("An array field must define at least one column")
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("Array column names must be unique")
        if self.header_rows < 0:
            raise ValueError("Array header rows cannot be negative")
        if not any(column.positioned for column in self.columns):
            return self
        if not self.positioned:
            raise ValueError("Either every array column has x and width, or none does")
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
        if self.type == "array" and self.locator and not self.array_config.positioned:
            raise ValueError("A fixed-position array field needs x and width on every column")
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
        pattern = (field.validation_rules or {}).get("pattern")
        if pattern:
            try:
                re.compile(str(pattern))
            except re.error as exc:
                raise ValueError(
                    f'The format rule for field "{field.name}" is not a valid regular expression ({exc.msg}).'
                ) from exc

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
    current_version: Optional[int] = None
    created_by: Optional[UUID] = None
    created_by_email: Optional[str] = None
    created_by_name: Optional[str] = None
    can_manage: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
