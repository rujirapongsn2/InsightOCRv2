"""
Unit tests for agent skill tools (agentskills.io compliant).

Run: cd backend && python -m pytest test/agent/test_skill_tools.py -v
"""
import uuid
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.agent.context import AgentContext
from app.agent.tools.skill_tools import (
    _create_skill_handler,
    _import_skill_handler,
    _export_skill_handler,
    _list_skills_handler,
    _execute_skill_handler,
    _delete_skill_handler,
    _discover_skills_handler,
    ALLOWED_SCOPES,
    MAX_NAME_LENGTH,
    MAX_DESC_LENGTH,
    MAX_PROCEDURE_LENGTH,
)
from app.crud.crud_agent_skill import agent_skill as crud_skill

pytestmark = pytest.mark.asyncio


def _make_context(user_id=None, job_id=None):
    db = MagicMock()
    return AgentContext(
        db=db,
        user_id=user_id or uuid.uuid4(),
        job_id=job_id or uuid.uuid4(),
        conversation_id=uuid.uuid4(),
    )


def _fake_skill(**overrides):
    s = MagicMock()
    defaults = {
        "id": uuid.uuid4(), "name": "test-skill", "scope": "user",
        "description": "A test skill", "procedure": "# Step 1\nDo something",
        "trigger_hint": None, "success_count": 0, "created_by": "agent",
        "source": "db", "file_path": None, "version": None,
        "license": None, "compatibility": None, "metadata_": None,
        "allowed_tools": None,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# ── create_skill ──────────────────────────────────────────────────────────────

class TestCreateSkill:
    async def test_create_basic(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=None), \
             patch.object(crud_skill, "create", return_value=_fake_skill()) as mock_create:
            result = await _create_skill_handler(
                {"name": "my-workflow", "description": "Does things", "procedure": "# Steps\n1. Do A\n2. Do B"},
                ctx,
            )
        assert result["ok"] is True
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["name"] == "my-workflow"
        assert kwargs["scope"] == "user"

    async def test_name_normalized_to_lowercase(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=None), \
             patch.object(crud_skill, "create", return_value=_fake_skill(name="pdf-tools")) as mock_create:
            result = await _create_skill_handler(
                {"name": "PDF-Tools", "description": "D", "procedure": "P"},
                ctx,
            )
        assert result["ok"] is True
        assert mock_create.call_args.kwargs["name"] == "pdf-tools"

    async def test_name_with_hyphens(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=None), \
             patch.object(crud_skill, "create", return_value=_fake_skill(name="pdf-processing")):
            result = await _create_skill_handler(
                {"name": "pdf-processing", "description": "D", "procedure": "P"},
                ctx,
            )
        assert result["ok"] is True

    async def test_name_too_long_rejected(self):
        ctx = _make_context()
        result = await _create_skill_handler(
            {"name": "x" * (MAX_NAME_LENGTH + 1), "description": "D", "procedure": "P"},
            ctx,
        )
        assert "error" in result

    async def test_name_consecutive_hyphens_rejected(self):
        ctx = _make_context()
        result = await _create_skill_handler(
            {"name": "bad--name", "description": "D", "procedure": "P"},
            ctx,
        )
        assert "error" in result

    async def test_empty_description_rejected(self):
        ctx = _make_context()
        result = await _create_skill_handler(
            {"name": "test", "description": "  ", "procedure": "P"},
            ctx,
        )
        assert "error" in result

    async def test_description_too_long_rejected(self):
        ctx = _make_context()
        result = await _create_skill_handler(
            {"name": "test", "description": "x" * (MAX_DESC_LENGTH + 1), "procedure": "P"},
            ctx,
        )
        assert "error" in result

    async def test_procedure_too_long_rejected(self):
        ctx = _make_context()
        result = await _create_skill_handler(
            {"name": "test", "description": "D", "procedure": "x" * (MAX_PROCEDURE_LENGTH + 1)},
            ctx,
        )
        assert "error" in result

    async def test_duplicate_name_rejected(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=_fake_skill()):
            result = await _create_skill_handler(
                {"name": "existing", "description": "D", "procedure": "P"},
                ctx,
            )
        assert "error" in result
        assert "already exists" in result["error"]

    async def test_system_scope_allowed(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=None), \
             patch.object(crud_skill, "create", return_value=_fake_skill(scope="system")) as mock_create:
            result = await _create_skill_handler(
                {"name": "sys-skill", "description": "D", "procedure": "P", "scope": "system"},
                ctx,
            )
        assert result["ok"] is True
        assert mock_create.call_args.kwargs["scope"] == "system"

    async def test_invalid_scope_rejected(self):
        ctx = _make_context()
        result = await _create_skill_handler(
            {"name": "test", "description": "D", "procedure": "P", "scope": "team"},
            ctx,
        )
        assert "error" in result

    async def test_with_all_optional_fields(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=None), \
             patch.object(crud_skill, "create", return_value=_fake_skill()) as mock_create:
            result = await _create_skill_handler(
                {
                    "name": "full-skill",
                    "description": "Does everything",
                    "procedure": "# Steps\n1. Step one\n2. Step two",
                    "scope": "user",
                    "trigger_hint": "when user mentions invoices",
                    "tools_used": ["list_documents", "approve_document"],
                    "allowed_tools": "Bash(git:*) Read",
                    "license": "MIT",
                    "compatibility": "Requires Python 3.12+",
                    "metadata": {"author": "test", "version": "1.0"},
                    "created_by": "agent",
                },
                ctx,
            )
        assert result["ok"] is True
        kwargs = mock_create.call_args.kwargs
        assert kwargs["trigger_hint"] == "when user mentions invoices"
        assert kwargs["tools_used"] == ["list_documents", "approve_document"]
        assert kwargs["license_"] == "MIT"


# ── execute_skill (progressive disclosure) ─────────────────────────────────────

class TestExecuteSkill:
    async def test_execute_user_skill(self):
        ctx = _make_context()
        skill = _fake_skill(name="invoice-bulk", procedure="# Approve all\nCall bulk_approve")
        with patch.object(crud_skill, "get_by_name", return_value=skill), \
             patch.object(crud_skill, "increment_usage") as mock_inc:
            result = await _execute_skill_handler({"name": "invoice-bulk"}, ctx)
        assert result["ok"] is True
        assert result["skill_name"] == "invoice-bulk"
        assert "bulk_approve" in result["procedure"]
        assert "instruction" in result  # Stage 3 instruction injected
        mock_inc.assert_called_once()

    async def test_execute_falls_back_to_system_scope(self):
        ctx = _make_context()
        skill = _fake_skill(name="sys-tool", scope="system")
        # First call (user scope) returns None, second call (system) returns skill
        with patch.object(crud_skill, "get_by_name", side_effect=[None, skill]), \
             patch.object(crud_skill, "increment_usage"):
            result = await _execute_skill_handler({"name": "sys-tool"}, ctx)
        assert result["ok"] is True
        assert result["scope"] == "system"

    async def test_execute_not_found(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=None):
            result = await _execute_skill_handler({"name": "nonexistent"}, ctx)
        assert "error" in result

    async def test_execute_template_substitution(self):
        ctx = _make_context()
        skill = _fake_skill(
            name="greet",
            procedure="Hello {{name}}, your order {{order_id}} is ready.",
        )
        with patch.object(crud_skill, "get_by_name", return_value=skill), \
             patch.object(crud_skill, "increment_usage"):
            result = await _execute_skill_handler(
                {"name": "greet", "arguments": {"name": "ACME", "order_id": "ORD-001"}},
                ctx,
            )
        assert "Hello ACME" in result["procedure"]
        assert "ORD-001" in result["procedure"]
        assert "{{name}}" not in result["procedure"]

    async def test_execute_empty_name_rejected(self):
        ctx = _make_context()
        result = await _execute_skill_handler({"name": "  "}, ctx)
        assert "error" in result


# ── list_skills ────────────────────────────────────────────────────────────────

class TestListSkills:
    async def test_list_includes_user_and_system(self):
        ctx = _make_context()
        with patch.object(crud_skill, "list_by_user", return_value=[
            _fake_skill(name="a", scope="user"),
            _fake_skill(name="b", scope="system"),
        ]):
            result = await _list_skills_handler({}, ctx)
        assert result["count"] == 2

    async def test_list_user_only(self):
        ctx = _make_context()
        with patch.object(crud_skill, "list_by_user", return_value=[
            _fake_skill(name="a", scope="user"),
        ]) as mock_list:
            result = await _list_skills_handler({"include_system": False}, ctx)
        assert result["count"] == 1
        mock_list.assert_called_once_with(ANY, user_id=ctx.user_id, include_system=False)


# ── delete_skill ──────────────────────────────────────────────────────────────

class TestDeleteSkill:
    async def test_delete_existing(self):
        ctx = _make_context()
        with patch.object(crud_skill, "delete", return_value=True):
            result = await _delete_skill_handler({"name": "old-skill", "scope": "user"}, ctx)
        assert result["ok"] is True

    async def test_delete_nonexistent(self):
        ctx = _make_context()
        with patch.object(crud_skill, "delete", return_value=False):
            result = await _delete_skill_handler({"name": "ghost", "scope": "user"}, ctx)
        assert result["ok"] is False
        assert "error" in result

    async def test_delete_empty_name_rejected(self):
        ctx = _make_context()
        result = await _delete_skill_handler({"name": "  ", "scope": "user"}, ctx)
        assert "error" in result


# ── import_skill ──────────────────────────────────────────────────────────────

class TestImportSkill:
    async def test_import_file_not_found(self):
        ctx = _make_context()
        result = await _import_skill_handler({"file_path": "/nonexistent/path/SKILL.md"}, ctx)
        assert "error" in result

    async def test_import_duplicate_without_overwrite(self, tmp_path):
        ctx = _make_context()
        # Create a real temp SKILL.md
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("""---
name: existing-skill
description: A test skill that already exists
---
# Steps
1. Do something
""")
        with patch.object(crud_skill, "get_by_name", return_value=_fake_skill()):
            result = await _import_skill_handler({"file_path": str(skill_md)}, ctx)
        assert "error" in result
        assert "already exists" in result["error"]

    async def test_import_success(self, tmp_path):
        ctx = _make_context()
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("""---
name: new-skill
description: A brand new skill to import
license: MIT
compatibility: Requires Python 3.12+
metadata:
  author: test
  version: "1.0"
allowed-tools: Bash(git:*) Read
---
# New Skill
This is the procedure.
""")
        with patch.object(crud_skill, "get_by_name", return_value=None), \
             patch.object(crud_skill, "create", return_value=_fake_skill(
                 name="new-skill", source="imported",
                 license="MIT", compatibility="Requires Python 3.12+",
             )) as mock_create:
            result = await _import_skill_handler({"file_path": str(skill_md)}, ctx)
        assert result["ok"] is True
        assert result["name"] == "new-skill"
        assert result["source"] == "imported"
        mock_create.assert_called_once()

    async def test_import_invalid_skill_md(self, tmp_path):
        ctx = _make_context()
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("""---
name: INVALID-NAME
description:
---
""")
        result = await _import_skill_handler({"file_path": str(skill_md)}, ctx)
        assert "error" in result
        assert "validation_errors" in result


# ── export_skill ──────────────────────────────────────────────────────────────

class TestExportSkill:
    async def test_export_not_found(self):
        ctx = _make_context()
        with patch.object(crud_skill, "get_by_name", return_value=None):
            result = await _export_skill_handler({"name": "no-skill"}, ctx)
        assert "error" in result

    async def test_export_as_markdown(self):
        ctx = _make_context()
        skill = _fake_skill(name="my-skill", description="Test skill", procedure="# Hello")
        with patch.object(crud_skill, "get_by_name", return_value=skill):
            result = await _export_skill_handler({"name": "my-skill", "bundle": False}, ctx)
        assert result["ok"] is True
        assert result["format"] == "markdown"
        assert "name: my-skill" in result["content"]
        assert "# Hello" in result["content"]


# ── discover_skills ───────────────────────────────────────────────────────────

class TestDiscoverSkills:
    async def test_discover_empty(self):
        ctx = _make_context()
        with patch("app.agent.tools.skill_tools.discover_skills", return_value=[]):
            result = await _discover_skills_handler({}, ctx)
        assert result["ok"] is True
        assert result["count"] == 0

    async def test_discover_with_registration(self):
        ctx = _make_context()
        fake_discovered = [{
            "name": "found-skill",
            "description": "Found on disk",
            "body": "# Instructions",
            "file_path": "/fake/skills/found-skill/SKILL.md",
            "license": "MIT",
            "compatibility": None,
            "metadata_": None,
            "allowed_tools": None,
        }]
        with patch("app.agent.tools.skill_tools.discover_skills", return_value=fake_discovered), \
             patch.object(crud_skill, "upsert_file_skill", return_value=_fake_skill(name="found-skill", source="file")):
            result = await _discover_skills_handler({}, ctx)
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["skills"][0]["status"] == "registered"


# ── Constants ─────────────────────────────────────────────────────────────────

class TestAllowedValues:
    async def test_allowed_scopes(self):
        assert "user" in ALLOWED_SCOPES
        assert "system" in ALLOWED_SCOPES
