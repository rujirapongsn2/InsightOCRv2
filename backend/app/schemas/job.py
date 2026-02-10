from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class JobBase(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schema_id: Optional[UUID] = None

class JobCreate(JobBase):
    pass

class JobUpdate(JobBase):
    status: Optional[str] = None

class Job(JobBase):
    id: UUID
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    user_id: Optional[UUID] = None
    user_name: Optional[str] = None

    class Config:
        from_attributes = True

