import importlib.util
from pathlib import Path

from sqlalchemy import inspect

# Import related models so SQLAlchemy can resolve mapper relationship targets.
from app.models.agent_conversation import AgentConversation  # noqa: F401
from app.models.agent_memory import AgentMemory  # noqa: F401
from app.models.chat import ChatConversation  # noqa: F401
from app.models.integration_result import IntegrationResult  # noqa: F401
from app.models.job import Job


def _load_job_fk_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0006_job_fk_cascade.py"
    )
    spec = importlib.util.spec_from_file_location("job_fk_cascade", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_job_delete_uses_database_cascade_for_non_document_children():
    relationships = inspect(Job).relationships

    for relationship_name in (
        "chat_conversations",
        "agent_conversations",
        "agent_memories",
        "integration_results",
    ):
        assert relationships[relationship_name].passive_deletes is True
        assert "delete-orphan" in relationships[relationship_name].cascade


def test_job_fk_migration_covers_integration_results():
    migration = _load_job_fk_migration()
    fk_tables = {table_name for table_name, _, _ in migration.JOB_FKS}

    assert "integration_results" in fk_tables
    assert "documents" in fk_tables
    assert "chat_conversations" in fk_tables
    assert "agent_conversations" in fk_tables
    assert "agent_memories" in fk_tables
