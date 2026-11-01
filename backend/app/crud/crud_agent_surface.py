from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.crud.crud_agent_run import ACTIVE_AGENT_RUN_STATUSES
from app.models.agent_pending_action import AgentPendingAction
from app.models.agent_run import AgentRun
from app.models.agent_surface import AgentSurface


def panel_status(surface: AgentSurface, run_status: Optional[str], run_confirmed: bool,
                 newer_actionable: bool) -> str:
    """The status the server reports for a panel.

    A click's answer stands while the run it started is still working, and
    after it once the user confirmed an action in that run. A run that ended
    without a confirmed action (it failed, was stopped, or its request was
    rejected or expired) did nothing for the click, so the panel is usable
    again: "active", or "superseded" when a newer panel with buttons appeared
    meanwhile. A click with no recorded run (converted by migration 0031) stands.
    """
    if surface.status != "answered":
        return surface.status
    if surface.answered_by_run_id is None or run_status in ACTIVE_AGENT_RUN_STATUSES or run_confirmed:
        return "answered"
    return "superseded" if newer_actionable else "active"


class CRUDAgentSurface:
    def register(self, db: Session, *, conversation_id: UUID, surface_id: str, tool_name: str,
                 actions: list[dict], document_ids: list[str]) -> AgentSurface:
        """Record a new panel. A panel with buttons supersedes every older panel whose buttons still worked."""
        if actions:
            for older in (db.query(AgentSurface)
                          .filter(AgentSurface.conversation_id == conversation_id, AgentSurface.status == "active")):
                if older.actions:
                    older.status = "superseded"
        surface = AgentSurface(surface_id=surface_id, conversation_id=conversation_id, tool_name=tool_name,
                               actions=actions, document_ids=document_ids, status="active",
                               created_at=datetime.now(timezone.utc))
        db.add(surface)
        db.commit()
        return surface

    def get(self, db: Session, surface_id: str) -> Optional[AgentSurface]:
        return db.query(AgentSurface).filter(AgentSurface.surface_id == surface_id).first()

    def _with_status(self, db: Session, conversation_id: UUID) -> list[tuple[AgentSurface, str]]:
        """Every panel of the conversation with the status panel_status gives it."""
        confirmed = (db.query(AgentPendingAction.id)
                     .filter(AgentPendingAction.run_id == AgentSurface.answered_by_run_id,
                             AgentPendingAction.kind == "confirmation",
                             AgentPendingAction.status == "confirmed")
                     .exists())
        rows = (db.query(AgentSurface, AgentRun.status, confirmed)
                .outerjoin(AgentRun, AgentRun.id == AgentSurface.answered_by_run_id)
                .filter(AgentSurface.conversation_id == conversation_id)
                .all())
        actionable = [surface.created_at for surface, _, _ in rows if surface.actions]
        return [(surface, panel_status(surface, run_status, bool(run_confirmed),
                                       any(created > surface.created_at for created in actionable)))
                for surface, run_status, run_confirmed in rows]

    def status(self, db: Session, surface: AgentSurface) -> str:
        return next(status for row, status in self._with_status(db, surface.conversation_id)
                    if row.surface_id == surface.surface_id)

    def claim(self, db: Session, surface: AgentSurface, run_id: UUID) -> bool:
        """Mark the panel answered by run_id if it is still as read; False when a concurrent click won.

        The caller commits.
        """
        query = db.query(AgentSurface).filter(AgentSurface.surface_id == surface.surface_id,
                                              AgentSurface.status == surface.status)
        query = query.filter(AgentSurface.answered_by_run_id.is_(None) if surface.answered_by_run_id is None
                             else AgentSurface.answered_by_run_id == surface.answered_by_run_id)
        return bool(query.update({"status": "answered", "answered_at": datetime.now(timezone.utc),
                                  "answered_by_run_id": run_id}, synchronize_session=False))

    def states(self, db: Session, conversation_id: UUID) -> dict[str, dict]:
        """Every panel of the conversation, whatever page of messages the client holds."""
        return {surface.surface_id: {"status": status, "actionable": bool(surface.actions),
                                     "generated_at": surface.created_at.isoformat() if surface.created_at else None}
                for surface, status in self._with_status(db, conversation_id)}


agent_surface = CRUDAgentSurface()
