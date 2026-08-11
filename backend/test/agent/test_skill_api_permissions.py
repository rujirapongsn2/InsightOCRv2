import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.agent import confirm_pending_action, create_skill, publish_skill, update_skill
from app.schemas.agent import AgentSkillCreate, AgentSkillUpdate, ConfirmActionRequest


pytestmark = pytest.mark.asyncio


def _user(*, admin: bool = False):
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=admin,
        role="admin" if admin else "user",
    )


def _skill(owner_id):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=owner_id,
        scope="user",
        name="invoice-check",
        description="Check invoice fields",
        procedure="# Steps\n1. List documents",
        trigger_hint="when checking invoices",
        tools_used=["list_skills"],
        allowed_tools="list_skills",
        license=None,
        compatibility=None,
        metadata_={"tool_policy": "strict"},
        created_by="agent",
        source="db",
        file_path=None,
        version=None,
        success_count=0,
        created_at=None,
        updated_at=None,
    )


async def test_create_skill_rejects_system_scope():
    with pytest.raises(HTTPException) as exc:
        await create_skill(
            AgentSkillCreate(
                name="shared-skill",
                description="Should not create a shared skill directly",
                procedure="# Step",
                scope="system",
            ),
            db=MagicMock(),
            current_user=_user(),
        )

    assert exc.value.status_code == 403


async def test_publish_requires_admin():
    with pytest.raises(HTTPException) as exc:
        await publish_skill(uuid.uuid4(), db=MagicMock(), current_user=_user())

    assert exc.value.status_code == 403


async def test_admin_can_publish_only_own_personal_skill():
    admin = _user(admin=True)
    skill = _skill(admin.id)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = skill
    published = _skill(None)
    published.scope = "system"
    published.user_id = None

    with patch("app.api.v1.endpoints.agent.crud_skill.get_by_name", return_value=None), \
         patch("app.api.v1.endpoints.agent.crud_skill.create", return_value=published) as create:
        result = await publish_skill(skill.id, db=db, current_user=admin)

    assert result["scope"] == "system"
    assert create.call_args.kwargs["user_id"] is None
    assert create.call_args.kwargs["scope"] == "system"


async def test_admin_cannot_publish_another_users_personal_skill():
    admin = _user(admin=True)
    skill = _skill(uuid.uuid4())
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = skill

    with pytest.raises(HTTPException) as exc:
        await publish_skill(skill.id, db=db, current_user=admin)

    assert exc.value.status_code == 404


async def test_strict_skill_cannot_drop_policy_through_metadata_update():
    owner = _user()
    skill = _skill(owner.id)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = skill

    result = await update_skill(
        skill.id,
        AgentSkillUpdate(metadata={"author": "owner"}),
        db=db,
        current_user=owner,
    )

    assert result["metadata"]["tool_policy"] == "strict"
    assert result["metadata"]["author"] == "owner"


async def test_create_skill_confirmation_requires_explicit_confirmation():
    owner = _user()
    action = SimpleNamespace(
        user_id=owner.id,
        tool_name="create_skill",
        status="pending",
    )
    db = MagicMock()
    with patch("app.api.v1.endpoints.agent.crud_pending.get", return_value=action), \
         patch("app.api.v1.endpoints.agent.crud_pending.resolve") as resolve:
        with pytest.raises(HTTPException) as exc:
            await confirm_pending_action(
                uuid.uuid4(),
                ConfirmActionRequest(approved=True),
                db=db,
                current_user=owner,
            )

    assert exc.value.status_code == 400
    resolve.assert_not_called()


async def test_create_skill_confirmation_accepts_explicit_confirmation():
    owner = _user()
    action = SimpleNamespace(
        user_id=owner.id,
        tool_name="create_skill",
        status="pending",
    )
    db = MagicMock()
    with patch("app.api.v1.endpoints.agent.crud_pending.get", return_value=action), \
         patch("app.api.v1.endpoints.agent.crud_pending.resolve", return_value=True) as resolve:
        result = await confirm_pending_action(
            uuid.uuid4(),
            ConfirmActionRequest(approved=True, explicit_confirmation=True),
            db=db,
            current_user=owner,
        )

    assert result == {"ok": True}
    resolve.assert_called_once()
