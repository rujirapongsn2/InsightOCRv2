from types import SimpleNamespace

import pytest

from app.agent.context import AgentContext
from app.agent.loop import (
    _skill_creation_final_text,
    _skill_policy_blocked_call_ids,
    _skill_policy_blocked_indexes,
)
from app.agent.tools.registry import ToolDef, ToolRegistry


pytestmark = pytest.mark.asyncio


async def _ok_handler(args, context):
    return {"ok": True, "args": args}


async def test_strict_skill_policy_filters_schemas_and_blocks_execution():
    registry = ToolRegistry()
    registry.register(ToolDef(
        name="allowed_tool", category="document", description="Allowed",
        parameters_schema={"type": "object"}, handler=_ok_handler,
    ))
    registry.register(ToolDef(
        name="blocked_tool", category="document", description="Blocked",
        parameters_schema={"type": "object"}, handler=_ok_handler,
    ))
    context = SimpleNamespace(active_skill_allowed_tools={"allowed_tool"})

    schemas = registry.get_openai_schemas(allowed_names=context.active_skill_allowed_tools)
    assert [schema["function"]["name"] for schema in schemas] == ["allowed_tool"]

    allowed = await registry.execute("allowed_tool", {"value": 1}, context)
    blocked = await registry.execute("blocked_tool", {}, context)

    assert allowed["ok"] is True
    assert blocked["blocked_by_skill_policy"] is True


async def test_strict_policy_blocks_execute_skill_when_not_allowlisted():
    registry = ToolRegistry()
    registry.register(ToolDef(
        name="execute_skill", category="skill", description="Nested skill",
        parameters_schema={"type": "object"}, handler=_ok_handler,
    ))
    context = SimpleNamespace(active_skill_allowed_tools={"allowed_tool"})

    result = await registry.execute("execute_skill", {}, context)

    assert result["blocked_by_skill_policy"] is True


async def test_skill_activation_is_atomic_for_a_multi_tool_turn():
    calls = [
        (SimpleNamespace(id="skill"), "execute_skill", {}),
        (SimpleNamespace(id="read"), "list_documents", {}),
    ]

    assert _skill_policy_blocked_call_ids(calls) == {"read"}

    create_calls = [
        (SimpleNamespace(id="create"), "create_skill", {}),
        (SimpleNamespace(id="document"), "list_documents", {}),
    ]
    assert _skill_policy_blocked_call_ids(create_calls) == {"document"}

    assert _skill_policy_blocked_indexes(["list_documents", "execute_skill"]) == {0}
    assert _skill_policy_blocked_indexes(["create_skill", "list_documents"]) == {1}
    assert _skill_policy_blocked_indexes(["list_documents", "get_document_detail"]) == set()


async def test_nested_skill_policy_cannot_expand_parent_policy():
    context = AgentContext.__new__(AgentContext)
    context.active_skill_allowed_tools = {"list_documents", "execute_skill"}
    context.activate_skill_tool_policy(["read_file", "execute_python"], enforce=True)

    assert context.active_skill_allowed_tools == set()


async def test_skill_creation_returns_terminal_invocation_message():
    text = _skill_creation_final_text({"name": "thai-contract-analysis"})

    assert "สร้าง Personal Skill" in text
    assert "/thai-contract-analysis" in text
