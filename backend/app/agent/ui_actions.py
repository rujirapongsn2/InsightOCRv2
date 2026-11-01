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

from app.crud.crud_agent_run import agent_run
from app.crud.crud_agent_surface import agent_surface
from app.models.agent_run import AgentRun

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


def user_turn(content: str, ui_action: dict | None) -> str:
    """A user turn as the model reads it: the rendered action for a click, the text otherwise."""
    return llm_content(ui_action) if ui_action else content


def _canonical_ids(raw_ids: list[str]) -> list[str]:
    ids: list[str] = []
    for raw in raw_ids:
        try:
            ids.append(str(uuid.UUID(raw.strip())))
        except (ValueError, AttributeError):
            raise UiActionRefused(422, f"document id {raw!r} is not a document id") from None
    return list(dict.fromkeys(ids))


def accept(db: Session, conversation_id: UUID, user_id: UUID, *, surface_id: str, name: str,
           source_component_id: str, document_ids: list[str]) -> AgentRun:
    """Check a click against its panel, queue the run that answers it, and mark the panel answered by that run.

    Nothing is committed; the caller commits the run, its user turn and the
    claim together. The run is inserted before the claim names it
    (agent_surfaces.answered_by_run_id references agent_runs). The claim is a
    conditional update, so of two concurrent clicks on one panel the second
    waits on the panel row, then finds it answered and is refused here.
    """
    surface = agent_surface.get(db, surface_id)
    if surface is None or surface.conversation_id != conversation_id:
        raise UiActionRefused(404, "ไม่พบแผงนี้ในบทสนทนานี้")
    status = agent_surface.status(db, surface)
    if status == "answered":
        raise UiActionRefused(409, "แผงนี้ส่งคำสั่งไปแล้ว")
    if status == "superseded":
        raise UiActionRefused(409, "แผงนี้ไม่ใช่แผงล่าสุด ใช้ปุ่มในแผงล่าสุดแทน")
    offered = {(action["component_id"], action["name"]) for action in surface.actions or []}
    if (source_component_id, name) not in offered:
        raise UiActionRefused(422, f"แผงนี้ไม่มีปุ่ม {name}")
    ids = _canonical_ids(document_ids)
    shown = set(surface.document_ids or [])
    if outside := [doc_id for doc_id in ids if doc_id not in shown]:
        raise UiActionRefused(422, f"เอกสาร {outside[:_SHOWN_IDS]} ไม่อยู่ในแผงนี้")
    action = {"surface_id": surface_id, "name": name, "document_ids": ids,
              "source_component_id": source_component_id, "timestamp": datetime.now(timezone.utc).isoformat()}
    run = agent_run.create(db, conversation_id=conversation_id, user_id=user_id,
                           user_message=display_text(name, len(ids)), ui_action=action)
    if not agent_surface.claim(db, surface, run.id):
        raise UiActionRefused(409, "แผงนี้ส่งคำสั่งไปแล้ว")
    return run
