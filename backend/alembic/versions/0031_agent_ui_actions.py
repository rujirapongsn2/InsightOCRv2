"""Panel clicks as structured messages, and server-side panel status.

Schema: agent_messages.kind ("text" | "ui_action") and agent_messages.ui_action,
agent_runs.ui_action, and the agent_surfaces table.

Data (idempotent; a second run changes nothing):
- A user message (and its run) whose content ends in an ```a2ui-action block
  becomes kind "ui_action": content keeps only the readable line, ui_action
  holds the parsed action.
- A conversation title cut from such a message gets the readable line.
- Every catalog-v2 panel in a tool result gets an agent_surfaces row. A panel
  is "answered" when a click names it; otherwise a panel with buttons that has
  a newer panel with buttons after it in its conversation is "superseded";
  otherwise it is "active". A converted click keeps answered_by_run_id empty:
  which run carried it out is not recorded reliably, so its answer stands.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_agent_ui_actions"
down_revision = "0030_schema_reference_uploads"
branch_labels = None
depends_on = None

FENCE = "a2ui-action"
_ACTION_BLOCK = re.compile(r"\n*```" + FENCE + r"\n([\s\S]*?)\n```\s*$")
CATALOG_V2 = "https://insightdoc.app/a2ui/catalogs/jobs/v2"
PANEL_TOOLS = ("show_documents", "show_metrics", "show_table", "show_chart", "show_risks")

_messages = sa.table(
    "agent_messages",
    sa.column("id", sa.Uuid()), sa.column("conversation_id", sa.Uuid()), sa.column("role", sa.String()),
    sa.column("kind", sa.String()), sa.column("content", sa.Text()), sa.column("ui_action", sa.JSON()),
    sa.column("tool_name", sa.String()), sa.column("tool_result", sa.JSON()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_runs = sa.table(
    "agent_runs",
    sa.column("id", sa.Uuid()), sa.column("user_message", sa.Text()), sa.column("ui_action", sa.JSON()),
)
_conversations = sa.table(
    "agent_conversations", sa.column("id", sa.Uuid()), sa.column("title", sa.String()),
)
_surfaces = sa.table(
    "agent_surfaces",
    sa.column("surface_id", sa.String()), sa.column("conversation_id", sa.Uuid()), sa.column("tool_name", sa.String()),
    sa.column("actions", sa.JSON()), sa.column("document_ids", sa.JSON()), sa.column("status", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


# ── Pure conversions (tested directly) ─────────────────────────────────────

def legacy_action(content: str | None) -> tuple[str, dict] | None:
    """(display text, ui_action) for a message that encodes a panel click as text; None otherwise."""
    match = _ACTION_BLOCK.search(content or "")
    if not match:
        return None
    try:
        action = json.loads(match.group(1))
    except ValueError:
        return None
    if not isinstance(action, dict) or not isinstance(action.get("surfaceId"), str) \
            or not isinstance(action.get("name"), str):
        return None
    context = action.get("context") if isinstance(action.get("context"), dict) else {}
    ids = context.get("document_ids")
    display = content[:match.start()].strip() or action["name"]
    return display, {
        "surface_id": action["surfaceId"],
        "name": action["name"],
        "document_ids": [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else [],
        "source_component_id": action.get("sourceComponentId") if isinstance(action.get("sourceComponentId"), str) else "",
        "timestamp": action.get("timestamp") if isinstance(action.get("timestamp"), str) else None,
    }


def legacy_text(display: str, action: dict) -> str:
    """The text encoding a downgrade restores."""
    block = {"name": action.get("name"), "surfaceId": action.get("surface_id"),
             "sourceComponentId": action.get("source_component_id"), "timestamp": action.get("timestamp"),
             "context": {"document_ids": action.get("document_ids") or []}}
    return f"{display}\n\n```{FENCE}\n{json.dumps(block, ensure_ascii=False)}\n```"


def fixed_title(title: str | None, legacy_contents: Iterable[str]) -> str | None:
    """The title without a leaked action block; the loop titled conversations with content[:60]."""
    if not title:
        return title
    for content in legacy_contents:
        converted = legacy_action(content)
        if converted and title == content[:60]:
            return converted[0][:60]
    if "```" + FENCE in title:
        return title.split("```", 1)[0].strip() or None
    return title


def panel_surface(tool_result: Any) -> dict | None:
    """{surface_id, actions, document_ids} of a catalog-v2 panel in a stored tool result."""
    messages = tool_result.get("a2ui") if isinstance(tool_result, dict) else None
    if not isinstance(messages, list):
        return None
    surface_id, actions, documents = None, [], []
    for message in messages:
        if not isinstance(message, dict):
            continue
        create = message.get("createSurface")
        if isinstance(create, dict) and create.get("catalogId") == CATALOG_V2 and isinstance(create.get("surfaceId"), str):
            surface_id = create["surfaceId"]
        components = (message.get("updateComponents") or {}).get("components")
        for component in components if isinstance(components, list) else []:
            event = ((component or {}).get("action") or {}).get("event") or {}
            if component.get("component") == "Button" and isinstance(event.get("name"), str):
                actions.append({"component_id": component.get("id"), "name": event["name"]})
        value = (message.get("updateDataModel") or {}).get("value")
        if isinstance(value, dict) and isinstance(value.get("documents"), list):
            documents = [row["document_id"] for row in value["documents"]
                         if isinstance(row, dict) and isinstance(row.get("document_id"), str)]
    if surface_id is None:
        return None
    return {"surface_id": surface_id, "actions": actions, "document_ids": documents if actions else []}


def surface_rows(panels: list[tuple[Any, datetime, str, Any]], answered: set[str]) -> list[dict]:
    """Rows for agent_surfaces from (conversation_id, created_at, tool_name, tool_result), oldest first.

    The same rule the server applies going forward: a click answers its panel;
    a newer panel with buttons in the conversation supersedes an older one.
    """
    rows: list[dict] = []
    for conversation_id, created_at, tool_name, result in panels:
        surface = panel_surface(result)
        if surface is None:
            continue
        if surface["actions"]:
            for older in rows:
                if older["conversation_id"] == conversation_id and older["status"] == "active" and older["actions"]:
                    older["status"] = "superseded"
        rows.append({**surface, "conversation_id": conversation_id, "tool_name": tool_name, "created_at": created_at,
                     "status": "active"})
    for row in rows:
        if row["surface_id"] in answered:
            row["status"] = "answered"
    return rows


# ── Migration ──────────────────────────────────────────────────────────────

def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def upgrade_data(bind) -> None:
    """Convert legacy rows; safe to run again."""
    legacy = bind.execute(sa.select(_messages.c.id, _messages.c.conversation_id, _messages.c.content).where(
        _messages.c.role == "user", _messages.c.content.like(f"%```{FENCE}%"))).all()
    contents_by_conversation: dict[Any, list[str]] = {}
    answered: set[str] = set()
    for message_id, conversation_id, content in legacy:
        converted = legacy_action(content)
        if converted is None:
            continue
        display, action = converted
        bind.execute(_messages.update().where(_messages.c.id == message_id)
                     .values(kind="ui_action", content=display, ui_action=action))
        contents_by_conversation.setdefault(conversation_id, []).append(content)
        answered.add(action["surface_id"])
    # Clicks converted by an earlier run of this migration still answer their panels.
    for (action,) in bind.execute(sa.select(_messages.c.ui_action).where(_messages.c.kind == "ui_action")):
        action = _json(action)
        if isinstance(action, dict) and isinstance(action.get("surface_id"), str):
            answered.add(action["surface_id"])

    for run_id, content in bind.execute(sa.select(_runs.c.id, _runs.c.user_message)
                                        .where(_runs.c.user_message.like(f"%```{FENCE}%"))).all():
        if converted := legacy_action(content):
            bind.execute(_runs.update().where(_runs.c.id == run_id)
                         .values(user_message=converted[0], ui_action=converted[1]))

    for conversation_id, title in bind.execute(sa.select(_conversations.c.id, _conversations.c.title)
                                               .where(_conversations.c.title.like("%`%"))).all():
        fixed = fixed_title(title, contents_by_conversation.get(conversation_id, []))
        if fixed != title:
            bind.execute(_conversations.update().where(_conversations.c.id == conversation_id).values(title=fixed))

    panels = bind.execute(
        sa.select(_messages.c.conversation_id, _messages.c.created_at, _messages.c.tool_name, _messages.c.tool_result)
        .where(_messages.c.role == "tool", _messages.c.tool_name.in_(PANEL_TOOLS))
        .order_by(_messages.c.created_at, _messages.c.id)).all()
    existing = {row[0] for row in bind.execute(sa.select(_surfaces.c.surface_id))}
    rows = [row for row in surface_rows([(c, t, n, _json(r)) for c, t, n, r in panels], answered)
            if row["surface_id"] not in existing]
    if rows:
        bind.execute(_surfaces.insert(), rows)


def downgrade_data(bind) -> None:
    for message_id, content, action in bind.execute(
            sa.select(_messages.c.id, _messages.c.content, _messages.c.ui_action)
            .where(_messages.c.kind == "ui_action")).all():
        bind.execute(_messages.update().where(_messages.c.id == message_id)
                     .values(content=legacy_text(content or "", _json(action) or {})))
    for run_id, content, action in bind.execute(
            sa.select(_runs.c.id, _runs.c.user_message, _runs.c.ui_action).where(_runs.c.ui_action.isnot(None))).all():
        bind.execute(_runs.update().where(_runs.c.id == run_id)
                     .values(user_message=legacy_text(content or "", _json(action) or {})))


def upgrade():
    op.add_column("agent_messages", sa.Column("kind", sa.String(16), nullable=False, server_default="text"))
    op.add_column("agent_messages", sa.Column("ui_action", postgresql.JSONB(), nullable=True))
    op.add_column("agent_runs", sa.Column("ui_action", postgresql.JSONB(), nullable=True))
    op.create_table(
        "agent_surfaces",
        sa.Column("surface_id", sa.String(64), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_by_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index("ix_agent_surfaces_conversation_id", "agent_surfaces", ["conversation_id"])
    upgrade_data(op.get_bind())


def downgrade():
    downgrade_data(op.get_bind())
    op.drop_index("ix_agent_surfaces_conversation_id", table_name="agent_surfaces")
    op.drop_table("agent_surfaces")
    op.drop_column("agent_runs", "ui_action")
    op.drop_column("agent_messages", "ui_action")
    op.drop_column("agent_messages", "kind")
