from pydantic import BaseModel
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
