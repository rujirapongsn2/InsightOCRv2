from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class APIAccessTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)


class APIAccessTokenResponse(BaseModel):
    id: UUID
    name: str
    token_prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    is_revoked: bool
    is_expired: bool

    class Config:
        from_attributes = True


class APIAccessTokenCreateResponse(BaseModel):
    token: str
    token_info: APIAccessTokenResponse
