"""Static validator tests — no DB rows needed for the structural cases.

Uses a lightweight fake session for reference lookups (job/integration/provider),
so these run without a live database.
"""
import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")

from app.services.workflow_validation import validate_workflow_definition


class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def first(self):
        return None  # every referenced id "not found" → warning-level


class _FakeSession:
    def query(self, *a, **k):
        return _FakeQuery()


class _User:
    def __init__(self):
        self.id = uuid.uuid4()
        self.is_superuser = False
        self.role = "user"


def _node(nid, ntype, config=None, label="n"):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0},
            "data": {"label": label, "config": config or {}}}


def _levels(issues):
    return {i["level"] for i in issues}


def test_valid_minimal_workflow_has_no_errors():
    definition = {
        "nodes": [
            _node("t1", "trigger_manual"),
            _node("tf1", "transform", {"mappings": [{"target": "x", "value": "1"}]}),
        ],
        "edges": [{"id": "e1", "source": "t1", "target": "tf1"}],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    errors = [i for i in issues if i["level"] == "error"]
    assert errors == [], errors


def test_empty_workflow_errors():
    issues = validate_workflow_definition(_FakeSession(), {"nodes": [], "edges": []}, _User())
    assert any(i["level"] == "error" for i in issues)


def test_unknown_node_type_errors():
    definition = {"nodes": [_node("t1", "trigger_manual"), _node("x1", "does_not_exist")], "edges": []}
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert any(i["node_id"] == "x1" and i["level"] == "error" for i in issues)


def test_missing_required_config_errors():
    # llm node requires 'prompt'
    definition = {"nodes": [_node("t1", "trigger_manual"), _node("l1", "llm", {})],
                  "edges": [{"id": "e", "source": "t1", "target": "l1"}]}
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert any(i["node_id"] == "l1" and i["field"] == "prompt" and i["level"] == "error" for i in issues)


def test_cycle_errors():
    definition = {
        "nodes": [_node("a", "trigger_manual"), _node("b", "transform", {"mappings": [{"target": "x", "value": "1"}]})],
        "edges": [{"id": "e1", "source": "a", "target": "b"}, {"id": "e2", "source": "b", "target": "a"}],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert any("cycle" in i["message"].lower() or "DAG" in i["message"] for i in issues)


def test_dangling_template_ref_errors():
    definition = {
        "nodes": [_node("t1", "trigger_manual"),
                  _node("l1", "llm", {"prompt": "summarize {{ghost.records}}"})],
        "edges": [{"id": "e", "source": "t1", "target": "l1"}],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert any("ghost" in i["message"] and i["level"] == "error" for i in issues)


def test_missing_job_reference_warns():
    definition = {
        "nodes": [_node("j1", "job_source", {"job_id": str(uuid.uuid4())})],
        "edges": [],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert any(i["node_id"] == "j1" and i["field"] == "job_id" and i["level"] == "warning" for i in issues)
