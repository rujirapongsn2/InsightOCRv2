from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.loop import AgentLoop, _node_requires_file
from app.agent.events import SSEEventType, sse_event
from app.services import workflow_agent as workflow_agent_mod
from app.services import workflow_engine
from app.services.workflow_agent import (
    SAFE_WORKFLOW_AGENT_TOOLS,
    SAFE_WORKFLOW_READ_ONLY_TOOLS,
    WorkflowAgentConfigurationError,
    _agent_status,
    _artifact_from_result,
    _remove_interactive_tail,
    _skill_tool_allowlist,
)


def test_workflow_agent_allowlist_never_includes_confirmation_tools():
    skill = SimpleNamespace(allowed_tools=None)

    allowed = _skill_tool_allowlist([skill])

    # No declared policy → read-only baseline (no write/execute/code tools).
    assert allowed == set(SAFE_WORKFLOW_READ_ONLY_TOOLS)
    assert "approve_document" not in allowed
    assert "delete_file" not in allowed
    assert "call_api_integration" not in allowed
    assert "execute_python" not in allowed
    assert "write_file" not in allowed


def test_strict_skill_tools_are_intersected_with_safe_tools():
    skill = SimpleNamespace(
        allowed_tools="list_documents create_pdf approve_document web_search"
    )

    assert _skill_tool_allowlist([skill], output_format="text") == {"list_documents", "create_pdf"}
    with pytest.raises(WorkflowAgentConfigurationError, match="create_docx"):
        _skill_tool_allowlist([skill], output_format="docx")


def test_strict_skill_must_explicitly_allow_the_requested_output_tool():
    skill = SimpleNamespace(allowed_tools="list_documents create_docx")

    assert _skill_tool_allowlist([skill], output_format="docx") == {
        "list_documents", "create_docx",
    }


def test_artifact_requires_an_outputs_path():
    artifact = _artifact_from_result(
        "create_pdf", {"ok": True, "path": "outputs/legal-report.pdf", "verified": True}
    )

    assert artifact == {
        "filename": "legal-report.pdf",
        "path": "outputs/legal-report.pdf",
        "type": "pdf",
        "tool": "create_pdf",
        "mime_type": None,
        "size": None,
        "verified": True,
    }
    assert _artifact_from_result("read_file", {"path": "source/input.pdf"}) is None


def test_max_iterations_is_never_a_success_without_explicit_completion():
    assert _agent_status(
        {"iterations": 10, "stopped": "max_iterations"},
        True,
        None,
        "บางส่วน",
        [],
        "text",
    ) == "partial"


def test_changed_skill_fingerprint_is_rejected():
    skill = SimpleNamespace(
        id=uuid4(), name="report-skill", description="Create reports",
        procedure="Create and verify the requested report.", allowed_tools="create_pdf",
    )
    from app.services.workflow_agent import _skill_fingerprint

    assert _skill_fingerprint(skill) != _skill_fingerprint(
        SimpleNamespace(
            id=skill.id, name=skill.name, description=skill.description,
            procedure="Changed procedure", allowed_tools=skill.allowed_tools,
        )
    )


def test_job_context_is_limited_to_the_upstream_graph():
    edges = [
        {"source": "job_a", "target": "transform"},
        {"source": "transform", "target": "agent"},
        {"source": "unrelated_job", "target": "other"},
    ]
    context = {
        "job_a": {"job_id": "job-1"},
        "unrelated_job": {"job_id": "job-2"},
    }

    assert workflow_engine._upstream_job_ids("agent", edges, context) == {"job-1"}


def test_partial_agent_result_fails_the_workflow_node(monkeypatch):
    provider = {"provider": "openai_compatible", "apiKey": "test"}

    monkeypatch.setattr(
        workflow_engine,
        "resolve_llm_provider",
        lambda *args, **kwargs: provider,
    )

    async def partial_result(*args, **kwargs):
        return {"status": "partial", "text": "incomplete", "warnings": ["timeout"]}

    monkeypatch.setattr(workflow_agent_mod, "run_workflow_agent", partial_result)

    with pytest.raises(workflow_engine.NodeExecutionError, match="timeout"):
        workflow_engine._exec_llm(
            object(),
            {"mode": "agent", "prompt": "run", "skill_ids": [str(uuid4())]},
            {"_owner_user_id": str(uuid4())},
            lambda _message: None,
        )


def test_autonomous_agent_never_waits_for_confirmation():
    loop = AgentLoop.__new__(AgentLoop)
    loop.autonomous = True

    assert loop._tool_requires_confirmation("approve_document", {}) is False


def test_interactive_follow_up_is_removed_from_terminal_result():
    text = "สร้างรายงานเรียบร้อยแล้ว\nต้องการให้ผมแก้ไขเพิ่มเติมไหมครับ"

    assert _remove_interactive_tail(text) == "สร้างรายงานเรียบร้อยแล้ว"


@pytest.mark.asyncio
async def test_headless_adapter_returns_verified_terminal_artifact(monkeypatch):
    user_id = uuid4()
    skill = SimpleNamespace(
        id=uuid4(), name="report-skill", description="Create reports",
        procedure="Create and verify the requested report.", version="1.0.0",
        allowed_tools="create_pdf",
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(id=user_id)

    class FakeDB:
        def query(self, *args, **kwargs):
            return FakeQuery()

    class FakeLoop:
        def __init__(self, **kwargs):
            assert kwargs["autonomous"] is True
            assert "create_pdf" in kwargs["initial_allowed_tools"]

        async def run(self, prompt):
            yield sse_event(SSEEventType.TOOL_RESULT, {
                "id": "call-1", "name": "create_pdf",
                "result": {"ok": True, "path": "outputs/report.pdf", "verified": True},
            })
            yield sse_event(SSEEventType.DELTA, {"text": "Report created"})
            yield sse_event(SSEEventType.DONE, {"iterations": 2, "success": True})

    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", FakeLoop)
    monkeypatch.setattr(workflow_agent_mod, "can_access_job", lambda *_args: True)
    monkeypatch.setattr(
        workflow_agent_mod.crud_conv, "create",
        lambda *args, **kwargs: SimpleNamespace(id=uuid4()),
    )
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "delete", lambda *args: True)

    result = await workflow_agent_mod.run_workflow_agent(
        FakeDB(), user_id=user_id, job_id=user_id,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Create report", skill_ids=[str(skill.id)], output_format="pdf",
    )

    assert result["status"] == "succeeded"
    assert result["text"] == "Report created"
    assert result["iterations"] == 2
    assert result["artifacts"][0]["path"] == "outputs/report.pdf"
    assert result["artifacts"][0]["filename"] == "report.pdf"


@pytest.mark.asyncio
async def test_file_output_rejects_missing_job_context_before_agent_execution():
    with pytest.raises(WorkflowAgentConfigurationError, match="Job context"):
        await workflow_agent_mod.run_workflow_agent(
            object(),
            user_id=uuid4(),
            job_id=None,
            provider={"provider": "openai_compatible", "apiKey": "test"},
            prompt="Create report",
            skill_ids=[str(uuid4())],
            output_format="docx",
        )


def test_node_requires_file_uses_output_format_for_autonomous_agent():
    # A docx node always requires a file even when the prompt omits "ไฟล์".
    assert _node_requires_file("docx", "summarize the contract", autonomous=True) is True
    assert _node_requires_file("xlsx", "compare the two contracts", autonomous=True) is True
    # Interactive turns still fall back to prompt keyword matching.
    assert _node_requires_file("text", "สรุปสัญญา", autonomous=False) is False
    assert _node_requires_file("text", "สร้างไฟล์สรุป", autonomous=False) is True


def test_agent_status_rejects_artifact_of_wrong_type():
    # A DOCX node must not report success on a markdown artifact.
    status = _agent_status(
        {"success": True},
        done_seen=True,
        error_message=None,
        final_text="done",
        artifacts=[{"type": "md", "path": "outputs/report.md", "verified": True}],
        output_format="docx",
    )
    assert status == "partial"

    # Matching type succeeds.
    status = _agent_status(
        {"success": True},
        done_seen=True,
        error_message=None,
        final_text="done",
        artifacts=[{"type": "docx", "path": "outputs/report.docx", "verified": True}],
        output_format="docx",
    )
    assert status == "succeeded"
