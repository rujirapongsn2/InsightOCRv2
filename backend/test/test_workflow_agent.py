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
    _workflow_artifact_prefix,
    _workflow_output_filename,
    _system_instructions,
)
from app.services.workflow_agent_contracts import missing_output_tools


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


def test_workflow_artifacts_are_namespaced_per_run_and_node():
    prefix = _workflow_artifact_prefix("run-123", "agent_node")

    assert prefix == "outputs/workflow/run-123/agent_node"
    assert _workflow_output_filename("reports/summary.docx", prefix) == (
        "outputs/workflow/run-123/agent_node/summary.docx"
    )


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
            self.context = SimpleNamespace(output_path_prefix=None)

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


@pytest.mark.asyncio
async def test_agent_rejects_completion_only_provider_before_execution():
    with pytest.raises(WorkflowAgentConfigurationError, match="OpenAI-compatible"):
        await workflow_agent_mod.run_workflow_agent(
            object(),
            user_id=uuid4(),
            job_id=uuid4(),
            provider={"provider": "completion_messages", "apiKey": "test"},
            prompt="Create report",
            skill_ids=[str(uuid4())],
            output_format="html",
        )


def test_node_requires_file_uses_output_format_for_autonomous_agent():
    # A docx node always requires a file even when the prompt omits "ไฟล์".
    assert _node_requires_file("docx", "summarize the contract", autonomous=True) is True
    assert _node_requires_file("xlsx", "compare the two contracts", autonomous=True) is True
    # Interactive turns still fall back to prompt keyword matching.
    assert _node_requires_file("text", "สรุปสัญญา", autonomous=False) is False
    assert _node_requires_file("text", "สร้างไฟล์สรุป", autonomous=False) is True


def test_text_workflow_agent_does_not_inherit_file_requirement_from_handoff():
    assert _node_requires_file(
        "text",
        "ผลจาก Agent ก่อนหน้า: บันทึกไฟล์ outputs/summary.md แล้ว",
        autonomous=True,
    ) is False


def test_handoff_preset_excludes_filesystem_tools_even_when_skill_allows_them():
    skill = SimpleNamespace(
        allowed_tools="list_documents get_document_detail read_file write_file create_pdf"
    )

    assert _skill_tool_allowlist([skill], agent_task="analysis") == set()


def test_handoff_system_prompt_uses_compact_skill_guidance():
    skill = SimpleNamespace(
        name="long-skill", description="Domain guidance",
        procedure="very long interactive instruction " * 1000,
    )

    prompt = _system_instructions([skill], "text", None, "risk_assessment")

    assert "Domain guidance" in prompt
    assert "very long interactive instruction" not in prompt


def test_report_preset_exposes_only_the_required_artifact_tool():
    skill = SimpleNamespace(allowed_tools="list_documents read_file write_file run_report_code")

    assert _skill_tool_allowlist([skill], output_format="html", agent_task="report") == {
        "create_html",
    }


def test_workflow_agent_presets_skip_the_extra_planning_call(monkeypatch):
    captured = {}

    class FakeLoop:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.context = SimpleNamespace(output_path_prefix=None)

        async def run(self, _prompt):
            yield sse_event(SSEEventType.DELTA, {"text": "handoff"})
            yield sse_event(SSEEventType.DONE, {"iterations": 1, "success": True})

    user_id = uuid4()
    skill = SimpleNamespace(id=uuid4(), name="analysis", description="", procedure="", version=None, allowed_tools=None)
    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *_args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", FakeLoop)
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "create", lambda *_args, **_kwargs: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "delete", lambda *_args: True)

    class FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(id=user_id)

    class FakeDB:
        def query(self, *_args, **_kwargs):
            return FakeQuery()

    import asyncio
    result = asyncio.run(workflow_agent_mod.run_workflow_agent(
        FakeDB(), user_id=user_id, job_id=None,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Analyze the supplied dossier", skill_ids=[str(skill.id)], agent_task="analysis",
    ))

    assert result["status"] == "succeeded"
    assert captured["initial_allowed_tools"] == set()
    assert captured["skip_planning"] is True


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


def _file_node_db(user_id, job_id, monkeypatch):
    """Minimal DB/permission stubs for a file-producing Agent node."""
    class FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(id=user_id)

    class FakeDB:
        def query(self, *_args, **_kwargs):
            return FakeQuery()

    monkeypatch.setattr(workflow_agent_mod, "can_access_job", lambda *_args: True)
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "create", lambda *_a, **_k: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "delete", lambda *_args: True)
    monkeypatch.setattr(workflow_agent_mod, "_verify_file_tool_result", lambda _ctx, _name, result: result)
    return FakeDB()


def _fake_render(recorder):
    async def execute(tool_name, args, _context):
        recorder.append({"tool": tool_name, "args": args})
        return {
            "ok": True,
            "verified": True,
            "path": "outputs/workflow/run1/node1/report.html",
            "size": 2048,
            "mime_type": "text/html; charset=utf-8",
        }

    return execute


def test_report_node_composes_content_and_renders_the_file_itself(monkeypatch):
    """The report preset must not depend on the model generating code."""
    import asyncio

    user_id, job_id = uuid4(), uuid4()
    calls: list[dict] = []
    skill = SimpleNamespace(id=uuid4(), name="report", description="", procedure="", version=None, allowed_tools=None)
    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *_args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", None)  # must never be used
    monkeypatch.setattr(workflow_agent_mod.tool_registry, "execute", _fake_render(calls))

    async def fake_compose(**_kwargs):
        return "# Contract Report\n\n## Findings\n- one", False

    monkeypatch.setattr(workflow_agent_mod, "_compose_document_content", fake_compose)

    result = asyncio.run(workflow_agent_mod.run_workflow_agent(
        _file_node_db(user_id, job_id, monkeypatch),
        user_id=user_id, job_id=job_id,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Write the report", skill_ids=[str(skill.id)],
        output_format="html", agent_task="report",
        workflow_run_id="run1", workflow_node_id="node1",
    ))

    assert result["status"] == "succeeded"
    assert [a["path"] for a in result["artifacts"]] == ["outputs/workflow/run1/node1/report.html"]
    assert [call["tool"] for call in calls] == ["create_html"]
    assert calls[0]["args"]["title"] == "Contract Report"
    assert result["metrics"]["stop_reason"] == "composed"
    # Composition is the primary route here, not a fallback after a failed loop.
    assert not any("rendered" in warning for warning in result["warnings"])


def test_file_node_renders_a_fallback_document_instead_of_failing(monkeypatch):
    """A stalled agent loop degrades to a rendered file plus a warning."""
    import asyncio

    user_id, job_id = uuid4(), uuid4()
    calls: list[dict] = []

    class StalledLoop:
        def __init__(self, **_kwargs):
            self.context = SimpleNamespace(output_path_prefix=None)

        async def run(self, _prompt):
            yield sse_event(SSEEventType.DONE, {
                "iterations": 3, "success": False, "stopped": "no_progress",
                "failed_steps": ["Agent made no progress"],
            })

    skill = SimpleNamespace(id=uuid4(), name="custom", description="", procedure="", version=None, allowed_tools=None)
    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *_args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", StalledLoop)
    monkeypatch.setattr(workflow_agent_mod.tool_registry, "execute", _fake_render(calls))

    async def fake_compose(**_kwargs):
        return "# Fallback Report\n\ncontent", False

    monkeypatch.setattr(workflow_agent_mod, "_compose_document_content", fake_compose)

    result = asyncio.run(workflow_agent_mod.run_workflow_agent(
        _file_node_db(user_id, job_id, monkeypatch),
        user_id=user_id, job_id=job_id,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Write the report", skill_ids=[str(skill.id)],
        output_format="html", agent_task="custom",
        workflow_run_id="run1", workflow_node_id="node1",
    ))

    assert result["status"] == "succeeded"
    assert result["error"] is None
    assert result["artifacts"]
    assert any("rendered" in warning for warning in result["warnings"])


def test_fallback_renders_the_agent_answer_without_a_second_llm_call(monkeypatch):
    import asyncio

    user_id, job_id = uuid4(), uuid4()
    calls: list[dict] = []
    answer = "# Contract Review\n\n" + ("Clause analysis paragraph. " * 40)

    class TextOnlyLoop:
        def __init__(self, **_kwargs):
            self.context = SimpleNamespace(output_path_prefix=None)

        async def run(self, _prompt):
            yield sse_event(SSEEventType.DELTA, {"text": answer})
            yield sse_event(SSEEventType.DONE, {"iterations": 2, "success": True})

    skill = SimpleNamespace(id=uuid4(), name="custom", description="", procedure="", version=None, allowed_tools=None)
    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *_args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", TextOnlyLoop)
    monkeypatch.setattr(workflow_agent_mod.tool_registry, "execute", _fake_render(calls))

    async def forbidden_compose(**_kwargs):
        raise AssertionError("the agent's own answer should be rendered as-is")

    monkeypatch.setattr(workflow_agent_mod, "_compose_document_content", forbidden_compose)

    result = asyncio.run(workflow_agent_mod.run_workflow_agent(
        _file_node_db(user_id, job_id, monkeypatch),
        user_id=user_id, job_id=job_id,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Write the report", skill_ids=[str(skill.id)],
        output_format="html", agent_task="custom",
        workflow_run_id="run1", workflow_node_id="node1",
    ))

    assert result["status"] == "succeeded"
    assert calls[0]["args"]["content"].startswith("# Contract Review")


def test_max_output_tokens_override_reaches_the_agent_loop(monkeypatch):
    """A per-node override must win over the task preset's fixed budget."""
    import asyncio

    captured = {}
    user_id = uuid4()

    class FakeLoop:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.context = SimpleNamespace(output_path_prefix=None)

        async def run(self, _prompt):
            yield sse_event(SSEEventType.DELTA, {"text": "handoff"})
            yield sse_event(SSEEventType.DONE, {"iterations": 1, "success": True})

    skill = SimpleNamespace(id=uuid4(), name="analysis", description="", procedure="", version=None, allowed_tools=None)
    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *_args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", FakeLoop)
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "create", lambda *_args, **_kwargs: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "delete", lambda *_args: True)

    class FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(id=user_id)

    class FakeDB:
        def query(self, *_args, **_kwargs):
            return FakeQuery()

    asyncio.run(workflow_agent_mod.run_workflow_agent(
        FakeDB(), user_id=user_id, job_id=None,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Analyze the supplied dossier", skill_ids=[str(skill.id)], agent_task="analysis",
        max_output_tokens=512,
    ))

    # The preset default for "analysis" is 1600 — the override must replace it.
    assert captured["max_output_tokens"] == 512


def test_max_output_tokens_override_is_clamped_to_a_safe_range(monkeypatch):
    import asyncio

    captured = {}
    user_id = uuid4()

    class FakeLoop:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.context = SimpleNamespace(output_path_prefix=None)

        async def run(self, _prompt):
            yield sse_event(SSEEventType.DONE, {"iterations": 1, "success": True})

    skill = SimpleNamespace(id=uuid4(), name="analysis", description="", procedure="", version=None, allowed_tools=None)
    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *_args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", FakeLoop)
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "create", lambda *_args, **_kwargs: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "delete", lambda *_args: True)

    class FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(id=user_id)

    class FakeDB:
        def query(self, *_args, **_kwargs):
            return FakeQuery()

    asyncio.run(workflow_agent_mod.run_workflow_agent(
        FakeDB(), user_id=user_id, job_id=None,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Analyze the supplied dossier", skill_ids=[str(skill.id)], agent_task="analysis",
        max_output_tokens=999_999,
    ))

    assert captured["max_output_tokens"] == 16000


def test_max_output_tokens_override_of_zero_is_clamped_not_ignored(monkeypatch):
    """An explicit 0 (e.g. from a definition saved before the 256-16000
    validator existed) must be clamped to the floor, not silently treated as
    'unset' and fall back to the task preset's default."""
    import asyncio

    captured = {}
    user_id = uuid4()

    class FakeLoop:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.context = SimpleNamespace(output_path_prefix=None)

        async def run(self, _prompt):
            yield sse_event(SSEEventType.DONE, {"iterations": 1, "success": True})

    skill = SimpleNamespace(id=uuid4(), name="analysis", description="", procedure="", version=None, allowed_tools=None)
    monkeypatch.setattr(workflow_agent_mod, "_selected_skills", lambda *_args: [skill])
    monkeypatch.setattr(workflow_agent_mod, "AgentLoop", FakeLoop)
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "create", lambda *_args, **_kwargs: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(workflow_agent_mod.crud_conv, "delete", lambda *_args: True)

    class FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(id=user_id)

    class FakeDB:
        def query(self, *_args, **_kwargs):
            return FakeQuery()

    asyncio.run(workflow_agent_mod.run_workflow_agent(
        FakeDB(), user_id=user_id, job_id=None,
        provider={"provider": "openai_compatible", "apiKey": "test"},
        prompt="Analyze the supplied dossier", skill_ids=[str(skill.id)], agent_task="analysis",
        max_output_tokens=0,
    ))

    # analysis preset default is 1600 — if 0 were treated as "unset" that's
    # what would come through instead of the clamped floor.
    assert captured["max_output_tokens"] == 256


def test_html_output_accepts_a_skill_that_only_declares_run_report_code():
    # Skills authored before create_html existed stay valid for HTML nodes.
    assert missing_output_tools({"run_report_code"}, "html") == set()
    assert missing_output_tools({"read_file"}, "html") == {"create_html"}
