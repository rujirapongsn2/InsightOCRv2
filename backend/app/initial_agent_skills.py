from pathlib import Path

from sqlalchemy.orm import Session

from app.crud.crud_agent_skill import agent_skill as crud_skill
from app.db.session import SessionLocal
from app.services.skill_discovery import discover_skills


def default_system_skill_paths() -> list[str]:
    """Return system skill directories visible to this runtime."""
    paths: list[str] = []
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".agents" / "skills"
        if candidate.is_dir():
            paths.append(str(candidate))

    cwd_candidate = Path.cwd() / ".agents" / "skills"
    if cwd_candidate.is_dir() and str(cwd_candidate) not in paths:
        paths.append(str(cwd_candidate))

    return paths or [str(cwd_candidate)]


def sync_system_agent_skills(
    db: Session,
    search_paths: list[str] | None = None,
) -> list[dict]:
    """Discover file-backed system skills and upsert them into the registry."""
    discovered = discover_skills(search_paths or default_system_skill_paths())
    synced: list[dict] = []

    for skill_data in discovered:
        skill = crud_skill.upsert_file_skill(
            db,
            user_id=None,
            scope="system",
            name=skill_data["name"],
            description=skill_data["description"],
            procedure=skill_data["body"],
            file_path=skill_data["file_path"],
            license_=skill_data.get("license"),
            compatibility=skill_data.get("compatibility"),
            metadata_=skill_data.get("metadata_"),
            allowed_tools=skill_data.get("allowed_tools"),
        )
        synced.append({"name": skill.name, "scope": skill.scope, "source": skill.source})

    return synced


def ensure_system_agent_skills() -> list[dict]:
    db = SessionLocal()
    try:
        return sync_system_agent_skills(db)
    finally:
        db.close()
