from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class GroupBase(BaseModel):
    name: str


class GroupCreate(GroupBase):
    pass


class GroupOut(GroupBase):
    id: UUID
    created_at: datetime | None = None
    member_count: int = 0

    class Config:
        from_attributes = True
