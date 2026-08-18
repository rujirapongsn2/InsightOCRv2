from pydantic import BaseModel, Field
from uuid import UUID

class SettingBase(BaseModel):
    ocr_engine: str = "default"
    model: str = "default"

    # Separate endpoints for different purposes
    ocr_endpoint: str | None = "https://111.223.37.41:9001/v3/ai-process-file"
    structured_output_endpoint: str | None = "https://111.223.37.41:9001/structured-output"
    schema_suggestion_endpoint: str | None = "https://111.223.37.41:9001/suggest-schema"
    test_endpoint: str | None = "https://111.223.37.41:9001/me"

    # Legacy field for backward compatibility
    api_endpoint: str | None = None

    api_token: str | None = None
    verify_ssl: bool = False
    ocr_fallback_enabled: bool = False
    ocr_fallback_api_key: str | None = None

class SettingUpdate(SettingBase):
    pass

class Setting(SettingBase):
    id: UUID
    app_commit_sha: str | None = None
    ocr_fallback_configured: bool = False
    ocr_fallback_source: str = "none"

    class Config:
        from_attributes = True


class MicrosoftOAuthConfigUpdate(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=4096)
    tenant: str = Field(default="common", min_length=1, max_length=255)
    redirect_uri: str | None = Field(default=None, max_length=2048)
    scope: str = Field(
        default="openid profile email offline_access User.Read Files.ReadWrite",
        min_length=1,
        max_length=2048,
    )


class MicrosoftOAuthConfigResponse(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    tenant: str = "common"
    redirect_uri: str
    scope: str
    configured: bool = False


class GoogleOAuthConfigUpdate(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=4096)
    redirect_uri: str | None = Field(default=None, max_length=2048)
    scope: str = Field(
        default="https://www.googleapis.com/auth/drive",
        min_length=1,
        max_length=2048,
    )


class GoogleOAuthConfigResponse(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str
    scope: str
    configured: bool = False
