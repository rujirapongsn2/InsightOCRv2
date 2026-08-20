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

    def all(self):
        return []


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


def test_agent_mode_requires_skill_and_bounded_runtime():
    definition = {
        "nodes": [
            _node("t1", "trigger_manual"),
            _node("a1", "llm", {
                "mode": "agent",
                "prompt": "Create a report",
                "skill_ids": [],
                "max_iterations": 30,
                "timeout_seconds": 30,
            }),
        ],
        "edges": [{"id": "e", "source": "t1", "target": "a1"}],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())

    fields = {issue["field"] for issue in issues if issue["level"] == "error"}
    assert {"skill_ids", "max_iterations", "timeout_seconds"} <= fields


def test_file_agent_requires_job_context_or_an_upstream_job_node():
    definition = {
        "nodes": [
            _node("t1", "trigger_manual"),
            _node("a1", "llm", {
                "mode": "agent",
                "prompt": "Create a report",
                "skill_ids": [],
                "output_format": "docx",
            }),
        ],
        "edges": [{"id": "e", "source": "t1", "target": "a1"}],
    }

    issues = validate_workflow_definition(_FakeSession(), definition, _User())

    assert any(issue["node_id"] == "a1" and issue["field"] == "job_id" for issue in issues)


def test_api_node_requires_a_saved_custom_api_connection():
    definition = {
        "nodes": [_node("t1", "trigger_manual"), _node("api1", "api", {})],
        "edges": [{"id": "e", "source": "t1", "target": "api1"}],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert any(i["node_id"] == "api1" and i["field"] == "integration_id" and i["level"] == "error" for i in issues)


def test_api_node_accepts_a_custom_api_connection_reference():
    definition = {
        "nodes": [
            _node("t1", "trigger_manual"),
            _node("api1", "api", {"integration_id": str(uuid.uuid4()), "body": "{{t1.payload}}"}),
        ],
        "edges": [{"id": "e", "source": "t1", "target": "api1"}],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert not any(i["node_id"] == "api1" and i["level"] == "error" for i in issues)
    assert any(i["node_id"] == "api1" and i["field"] == "integration_id" and i["level"] == "warning" for i in issues)


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


def test_gdrive_import_schema_override_is_optional_but_validated():
    definition = {
        "nodes": [
            _node("t1", "trigger_manual"),
            _node("g1", "gdrive_import", {
                "integration_id": str(uuid.uuid4()),
                "folder_id": "drive-folder",
                "job_id": str(uuid.uuid4()),
                "schema_id": str(uuid.uuid4()),
            }),
        ],
        "edges": [{"id": "e1", "source": "t1", "target": "g1"}],
    }
    issues = validate_workflow_definition(_FakeSession(), definition, _User())
    assert not any(i["field"] == "schema_id" and i["level"] == "error" for i in issues)
    assert any(i["node_id"] == "g1" and i["field"] == "schema_id" and i["level"] == "warning" for i in issues)
