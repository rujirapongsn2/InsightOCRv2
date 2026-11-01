"""A stored result for every tool call whose run ended before the call returned.

Without one the chat shows such a call as still running forever, because the
UI knows a call is over only from its result row.

A run's calls are the assistant tool calls of its conversation written in its
time span: from the run's creation (its user turn is stored in the same
transaction) until the next run of the conversation was created.
agent_messages has no run_id; _run_pending_action attributes requests the
same way. A conversation runs one run at a time (_idle_conversation).

Only a run's own loop writes real results, so close_unfinished_calls runs
only where no loop can still write one for that run: in the worker once its
loop has returned, and for runs whose worker is known to be gone (a
redelivered task, maintenance, migration 0032). The Stop endpoint never calls
it: the worker may still be about to store the real result.

Plain SQLAlchemy Core on purpose: migration 0032 runs it on its connection.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Iterable

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

_runs = sa.table(
    "agent_runs",
    sa.column("id", sa.Uuid()), sa.column("conversation_id", sa.Uuid()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_messages = sa.table(
    "agent_messages",
    sa.column("id", sa.Uuid()), sa.column("conversation_id", sa.Uuid()), sa.column("role", sa.String()),
    sa.column("kind", sa.String()), sa.column("tool_calls", JSONB), sa.column("tool_call_id", sa.String()),
    sa.column("tool_name", sa.String()), sa.column("tool_result", JSONB), sa.column("iteration", sa.Integer()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def call_name(call: dict) -> str | None:
    return (call.get("function") or {}).get("name") or call.get("name")


def unfinished_call_result(tool_name: str | None) -> dict:
    """What the model and the chat are told about a call whose run ended before it returned."""
    name = tool_name or "this tool"
    return {
        "error": (f"{name} did not finish: the run was stopped by the user or interrupted before it returned, "
                  "so it had no result. Do not assume it took effect. That request is over: answer the user's "
                  "latest message, and repeat this call only if that message asks for it."),
        "unfinished": True,
    }


def close_unfinished_calls(connection, run_ids: Iterable[uuid.UUID]) -> int:
    """Store the unfinished result for each call of these runs that has none; the caller commits.

    Idempotent: a call that has a result in its run's span is skipped, and the
    stored row is dated just after its call, inside that span. Returns how many rows were stored.
    """
    stored = 0
    for run_id in run_ids:
        run = connection.execute(
            sa.select(_runs.c.conversation_id, _runs.c.created_at).where(_runs.c.id == run_id)).first()
        if run is None or run.created_at is None:
            continue
        next_run_at = connection.execute(
            sa.select(sa.func.min(_runs.c.created_at))
            .where(_runs.c.conversation_id == run.conversation_id, _runs.c.created_at > run.created_at)).scalar()
        span = [_messages.c.conversation_id == run.conversation_id, _messages.c.created_at >= run.created_at]
        if next_run_at is not None:
            span.append(_messages.c.created_at < next_run_at)
        answered = set(connection.execute(
            sa.select(_messages.c.tool_call_id).where(*span, _messages.c.role == "tool")).scalars())
        calls = connection.execute(
            sa.select(_messages.c.tool_calls, _messages.c.iteration, _messages.c.created_at)
            .where(*span, _messages.c.role == "assistant", _messages.c.tool_calls.isnot(None))
            .order_by(_messages.c.created_at)).all()
        for message in calls:
            for call in message.tool_calls if isinstance(message.tool_calls, list) else []:
                call_id = call.get("id") if isinstance(call, dict) else None
                if not call_id or call_id in answered:
                    continue
                connection.execute(sa.insert(_messages).values(
                    id=uuid.uuid4(), conversation_id=run.conversation_id, role="tool", kind="text",
                    tool_call_id=call_id, tool_name=call_name(call), tool_result=unfinished_call_result(call_name(call)),
                    iteration=message.iteration, created_at=message.created_at + timedelta(microseconds=1),
                ))
                answered.add(call_id)
                stored += 1
    return stored
