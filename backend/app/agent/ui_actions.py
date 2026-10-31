"""A click on a panel button, as a structured user message.

The browser sends {surface_id, name, source_component_id, document_ids}. The
server checks it against the panel it recorded (app.models.agent_surface),
writes the display text the chat and the conversation title show, and stores
the action on the message. The model reads the action rendered from that
payload; nothing downstream parses text.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.crud.crud_agent_surface import agent_surface

UiActionName = Literal["approve_documents", "reject_documents"]
_VERBS: dict[str, str] = {"approve_documents": "อนุมัติ", "reject_documents": "ปฏิเสธ"}
_SHOWN_IDS = 5


class UiActionRefused(Exception):
    """A click the server will not act on; reason is shown to the user."""

    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


def display_text(name: str, count: int) -> str:
    return f"{_VERBS[name]}เอกสาร {count} รายการที่เลือก"


def llm_content(action: dict) -> str:
    """The click as the model reads it, rendered from the stored payload."""
    payload = {key: action[key] for key in ("surface_id", "name", "document_ids")}
    return f"[ui_action] {json.dumps(payload, ensure_ascii=False)}"


def _canonical_ids(raw_ids: list[str]) -> list[str]:
    ids: list[str] = []
    for raw in raw_ids:
        try:
            ids.append(str(uuid.UUID(raw.strip())))
        except (ValueError, AttributeError):
            raise UiActionRefused(422, f"document id {raw!r} is not a document id") from None
    return list(dict.fromkeys(ids))


def accept(db: Session, conversation_id: UUID, *, surface_id: str, name: str, source_component_id: str,
           document_ids: list[str]) -> dict:
    """Check a click against its panel and mark the panel answered (uncommitted); returns the stored action."""
    surface = agent_surface.get(db, surface_id)
    if surface is None or surface.conversation_id != conversation_id:
        raise UiActionRefused(404, "ไม่พบแผงนี้ในบทสนทนานี้")
    if surface.status == "answered":
        raise UiActionRefused(409, "แผงนี้ส่งคำสั่งไปแล้ว")
    if surface.status == "superseded":
        raise UiActionRefused(409, "แผงนี้ไม่ใช่แผงล่าสุด ใช้ปุ่มในแผงล่าสุดแทน")
    offered = {(action["component_id"], action["name"]) for action in surface.actions or []}
    if (source_component_id, name) not in offered:
        raise UiActionRefused(422, f"แผงนี้ไม่มีปุ่ม {name}")
    ids = _canonical_ids(document_ids)
    if outside := [doc_id for doc_id in ids if doc_id not in set(surface.document_ids or [])]:
        raise UiActionRefused(422, f"เอกสาร {outside[:_SHOWN_IDS]} ไม่อยู่ในแผงนี้")
    if not agent_surface.claim(db, surface_id):
        raise UiActionRefused(409, "แผงนี้ส่งคำสั่งไปแล้ว")
    return {"surface_id": surface_id, "name": name, "document_ids": ids,
            "source_component_id": source_component_id, "timestamp": datetime.now(timezone.utc).isoformat()}
