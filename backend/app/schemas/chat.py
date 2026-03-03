from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class ChatConversationCreate(BaseModel):
    job_id: UUID
    integration_id: UUID


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class ChatMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    model_used: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatConversationResponse(BaseModel):
    id: UUID
    job_id: UUID
    integration_id: Optional[UUID] = None
    title: Optional[str] = None
    created_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class ChatConversationDetailResponse(ChatConversationResponse):
    messages: list[ChatMessageResponse] = []
