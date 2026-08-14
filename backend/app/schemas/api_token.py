from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.api_token_scopes import DEFAULT_API_TOKEN_SCOPES, normalize_api_token_scopes


class APIAccessTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)
    mcp_access_only: bool = False
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_API_TOKEN_SCOPES))

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Token name must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("Token name must not be empty")
        return normalized

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        return normalize_api_token_scopes(value)

    def model_post_init(self, __context: object) -> None:
        if not self.mcp_access_only and self.scopes != DEFAULT_API_TOKEN_SCOPES:
            raise ValueError("MCP action scopes require mcp_access_only=true")


class APIAccessTokenResponse(BaseModel):
    id: UUID
    name: str
    token_prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    mcp_access_only: bool = False
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_API_TOKEN_SCOPES))
    is_revoked: bool
    is_expired: bool

    class Config:
        from_attributes = True


class APIAccessTokenCreateResponse(BaseModel):
    token: str
    token_info: APIAccessTokenResponse
