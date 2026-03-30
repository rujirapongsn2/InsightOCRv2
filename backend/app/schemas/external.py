from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ExternalJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    schema_id: Optional[UUID] = None


class ExternalJobResponse(BaseModel):
    id: UUID
    name: Optional[str] = None
    description: Optional[str] = None
    schema_id: Optional[UUID] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    document_count: int = 0


class ExternalDocumentSummary(BaseModel):
    id: UUID
    job_id: UUID
    filename: str
    mime_type: Optional[str] = None
    status: str
    schema_id: Optional[UUID] = None
    review_decision: Optional[str] = None
    uploaded_at: datetime
    reviewed_at: Optional[datetime] = None
    page_count: Optional[int] = None
    processing_error: Optional[str] = None


class ExternalDocumentDetail(ExternalDocumentSummary):
    ocr_text: Optional[str] = None
    extracted_data: Any = None
    reviewed_data: Any = None


class ExternalDocumentReviewRequest(BaseModel):
    reviewed_data: Any


class ExternalDocumentDecisionRequest(BaseModel):
    decision: str = Field(..., description="confirm, yes, or reject")
    reviewed_data: Any = None


class ExternalProcessRequest(BaseModel):
    schema_id: Optional[UUID] = None


class ExternalProgressInfo(BaseModel):
    percent: int = 0
    stage: str = ""
    message: str = ""


class ExternalDocumentStatusResponse(BaseModel):
    document_id: UUID
    status: str
    review_decision: Optional[str] = None
    extracted_data: Any = None
    reviewed_data: Any = None
    processing_error: Optional[str] = None
    page_count: Optional[int] = None
    progress: Optional[ExternalProgressInfo] = None


class ExternalSchemaResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    document_type: str
    field_count: int
    fields: list[dict[str, Any]]


class ExternalIntegrationResponse(BaseModel):
    id: UUID
    name: str
    type: str
    description: Optional[str] = None
    status: str


class ExternalSendToIntegrationRequest(BaseModel):
    integration_id: Optional[UUID] = None
    integration_name: Optional[str] = None
    document_ids: Optional[list[UUID]] = None
    include_unconfirmed: bool = False
