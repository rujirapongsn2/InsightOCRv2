from typing import Optional, Any
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.agent_message import AgentMessage


def _sanitize_jsonb(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_jsonb(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_jsonb(item) for key, item in value.items()}
    return value


class CRUDAgentMessage:
    def add(self, db: Session, *, conversation_id: UUID, role: str, content: Optional[str] = None, tool_calls: Optional[list] = None, tool_call_id: Optional[str] = None, tool_name: Optional[str] = None, tool_result: Optional[dict] = None, iteration: Optional[int] = None, model_used: Optional[str] = None, tokens_in: Optional[int] = None, tokens_out: Optional[int] = None) -> AgentMessage:
        msg = AgentMessage(conversation_id=conversation_id, role=role, content=content, tool_calls=_sanitize_jsonb(tool_calls), tool_call_id=tool_call_id, tool_name=tool_name, tool_result=_sanitize_jsonb(tool_result), iteration=iteration, model_used=model_used, tokens_in=tokens_in, tokens_out=tokens_out)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg


agent_message = CRUDAgentMessage()