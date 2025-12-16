from pydantic import BaseModel
from uuid import UUID

class SettingBase(BaseModel):
    ocr_engine: str = "default"
    model: str = "default"
    api_endpoint: str | None = "https://111.223.37.41:9001/ai-process-file"
    api_token: str | None = None
    verify_ssl: bool = False

class SettingUpdate(SettingBase):
    pass

class Setting(SettingBase):
    id: UUID

    class Config:
        from_attributes = True
