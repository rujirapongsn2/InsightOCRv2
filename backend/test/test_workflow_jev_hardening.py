"""Choice routing guards, save-time validation, decision input cap, Field Mapping aggregate status."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import workflow_engine as we
from app.services.workflow_validation import _validate_jev_node

from test.test_workflow_jev_graph_e2e import (  # noqa: F401 — fixtures
    TRIGGER, _choice_graph, capture_node_runs, make_run, mock_typesafe, node_statuses, transform_node,
)


def test_fallback_key_is_reserved():
    with pytest.raises(we.NodeExecutionError, match="fallback"):
        we._normalize_jev_options("a|A\nFallback|Other")


def test_unwired_choice_fails_run_instead_of_skipping_silently(mock_typesafe, capture_node_runs):
    nodes, edges, trigger = _choice_graph("risk_c|Risk")  # mock picks risk_c; no edge from it
    run = make_run(nodes, edges, trigger)
    we.execute_workflow_run(capture_node_runs(run), run)
    assert run.status == "failed"
    assert "risk_c" in run.error
    statuses = node_statuses(run)
    assert statuses["ch1"] == "failed"
    assert {statuses["s_sales"], statuses["s_support"], statuses["s_fallback"]} == {"skipped"}


def test_terminal_choice_without_edges_succeeds(mock_typesafe, capture_node_runs):
    nodes, edges, trigger = _choice_graph()
    edges = [e for e in edges if e["source"] != "ch1"]
    run = make_run(nodes[:3], edges, trigger)
    we.execute_workflow_run(capture_node_runs(run), run)
    assert run.status == "succeeded", run.error


def _choice_config(options="a|A\nb|B", **extra):
    return {"choice_name": "route", "input_source": "x", "options": options, **extra}


def test_validation_flags_bad_choice_options():
    issues = _validate_jev_node("ch", "jev_choice", _choice_config("only|One"), [])
    assert [i["level"] for i in issues] == ["error"]
    issues = _validate_jev_node("ch", "jev_choice", _choice_config("a|A\nfallback|F"), [])
    assert issues and "fallback" in issues[0]["message"]


def test_validation_flags_stale_and_unwired_choice_edges():
    edges = [
        {"source": "ch", "target": "n1", "sourceHandle": "a"},
        {"source": "ch", "target": "n2", "sourceHandle": "old_key"},
    ]
    issues = _validate_jev_node("ch", "jev_choice", _choice_config(), edges)
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    assert len(errors) == 1 and "old_key" in errors[0]["message"]
    assert len(warnings) == 1 and "b" in warnings[0]["message"] and "fallback" in warnings[0]["message"]


def test_validation_flags_fallback_edge_when_fallback_disabled():
    edges = [{"source": "ch", "target": "n", "sourceHandle": "fallback"}]
    issues = _validate_jev_node("ch", "jev_choice", _choice_config(enable_fallback=False), edges)
    assert any(i["level"] == "error" for i in issues)


def test_validation_flags_bad_score_weights_and_skips_templates():
    issues = _validate_jev_node("sc", "jev_score", {"criteria": "a|0.5\nb"}, [])
    assert issues and issues[0]["field"] == "criteria"
    assert _validate_jev_node("ch", "jev_choice", _choice_config("{{prev.options}}"), []) == []


def test_decision_input_is_capped_and_batch_is_logged(monkeypatch):
    monkeypatch.setattr(we, "_jev_decision_input", lambda config, context: json.dumps([{"t": "x" * 50}] * 10))
    from app.core.config import settings
    monkeypatch.setattr(settings, "JEV_DECISION_INPUT_MAX_CHARS", 100)
    logs = []
    state = we._jev_decision_state({}, {}, logs.append, "Score")
    assert len(state["input"]) < 200 and "ตัดทอน" in state["input"]
    assert any("10 รายการ" in line for line in logs)
    assert any("เพดาน" in line for line in logs)


def test_field_mapping_status_is_worst_case_across_documents(monkeypatch):
    docs = [SimpleNamespace(id=f"d{i}", filename=f"{i}.pdf", ocr_text="Reference: R-9", file_path=None,
                            uploaded_at=None) for i in range(3)]
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: None)
    monkeypatch.setattr(we, "_field_mapping_schema", lambda db, sid: SimpleNamespace(
        name="s", fields=[{"name": "id", "type": "text"}]))
    monkeypatch.setattr(we, "_field_mapping_documents", lambda db, cfg, ctx, limit: docs)
    statuses = iter(["completed", "failed", "partial"])

    def fake_map_fields(*a, **k):
        return {"id": "R-9"}, {"status": next(statuses), "engine": "auto", "attempts": [], "fields": {},
                               "review_fields": [], "unresolved_fields": [], "missing_fields": []}

    monkeypatch.setattr("app.services.field_mapping.map_fields", fake_map_fields)
    out = we._exec_field_mapping(Mock(), {"schema_id": "s", "engine": "auto"}, {"_node_id": "n1"}, lambda m: None)
    assert out["status"] == "failed"
    assert out["first_document_status"] == "completed"
    assert out["incomplete_documents"] == ["1.pdf", "2.pdf"]
    assert any("เอกสารแรก" in w for w in out["warnings"])


def test_fields_to_use_skips_none_records_and_explains_empty_input():
    from app.services import workflow_engine as we

    text = we._jev_decision_input({"input_source": '[{"total": 1, "x": 2}, null]', "fields_to_use": "total"}, {})
    assert text == '[{"total": 1}]'
    with pytest.raises(we.NodeExecutionError, match="ทุกรายการเป็น None"):
        we._jev_decision_input({"input_source": "[null, null]", "fields_to_use": "total"}, {})
    with pytest.raises(we.NodeExecutionError, match="ว่าง \\(None\\)"):
        we._jev_decision_input({"input_source": "None", "fields_to_use": "total"}, {})
