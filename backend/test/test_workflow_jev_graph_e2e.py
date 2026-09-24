"""Graph E2E for Jev decision workflows (score / choice / noul).

Runs **full multi-node graphs** through ``execute_workflow_run`` with mocked
``app.services.typesafe.typesafe_score|typesafe_choice|typesafe_noul`` — the
same symbols ``workflow_engine._exec_jev_*`` actually call — asserting node
routing (single outbound, N-way handles + fallback, condition branching) and
structured outputs.

Run (container pattern, same as other backend tests):
    cd /Volumes/Seagate/myapp/InsightOCRv2
    docker run --rm --env-file backend/.env \
      -v "$PWD/backend/app:/app/app:ro" -v "$PWD/backend/test:/app/test:ro" \
      insightocrv2-backend pytest test/test_workflow_jev_graph_e2e.py -v -p no:warnings

No live TypeSafe calls in the default path. Optional live smoke (skipped unless
INSIGHTDOC_JEV_LIVE=1 + auth token available) re-runs production smoke WFs via
the API instead — see ``test_live_smoke_workflows``.
"""
import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")

from types import SimpleNamespace

import pytest

from app.models.workflow import WorkflowNodeRun
from app.services.workflow_engine import execute_workflow_run


class FakeSession:
    """Minimal session double: collect node-run rows, keep query() unusable.

    Decision executors call ``_jev_decision_setting`` (seam) so the session's
    ``query`` is never reached; TypeSafe is mocked below.
    """

    def __init__(self):
        self.node_runs = []

    def add(self, value):
        if isinstance(value, WorkflowNodeRun):
            self.node_runs.append(value)

    def commit(self):
        pass

    def refresh(self, obj):
        pass

    def query(self, *a, **k):  # pragma: no cover — guards accidental DB use
        raise AssertionError("Graph E2E must not hit the DB; mock TypeSafe instead")


def make_run(nodes, edges, trigger_input=None):
    return type("R", (), {
        "id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "status": "queued",
        "trigger_type": "manual",
        "trigger_input": trigger_input or {},
        "definition_snapshot": {"nodes": nodes, "edges": edges},
        "result": None,
        "result_node_id": None,
        "error": None,
        "started_at": None,
        "finished_at": None,
    })()


def node_outputs(run):
    """Map node_id -> output dict, taken from the engine's own node-run rows."""
    out = {}
    for nr in run_nodes(run):
        output = getattr(nr, "output", None)
        if isinstance(output, dict):
            out[nr.node_id] = output
    return out


def node_statuses(run):
    return {nr.node_id: nr.status for nr in run_nodes(run)}


def run_nodes(run):
    return run.__dict__.setdefault("_captured_node_runs", [])


@pytest.fixture
def capture_node_runs(monkeypatch):
    """Capture WorkflowNodeRun rows created by execute_workflow_run onto the run.

    The engine writes node outputs both into its in-memory context (which
    downstream routing reads) and into WorkflowNodeRun rows via db.add(). The
    FakeSession collects those rows so tests can assert outputs per node.
    """
    def _attach(run):
        session = FakeSession()
        originals = {}

        real_add = session.add

        def add_and_bind(value):
            real_add(value)
            if isinstance(value, WorkflowNodeRun):
                run_nodes(run).append(value)

        originals["add"] = add_and_bind
        session.add = add_and_bind
        return session

    return _attach


@pytest.fixture
def mock_typesafe(monkeypatch):
    """Patch the wrapper symbols workflow_engine calls via ts_mod attributes."""
    calls = {"score": [], "choice": [], "noul": []}

    def patch(name, fn):
        monkeypatch.setattr(f"app.services.typesafe.{name}", fn)

    def score(config, state, score_name, rubric, scale, **kw):
        calls["score"].append({"name": score_name, "rubric": rubric, "scale": scale})
        # Tests set calls["next_score_index"] to control the outcome; default top.
        index = calls.get("next_score_index", 4.0)
        return {"index": index, "confidence": 0.9, "probabilities": {}, "model": "jev-mock"}

    def choice(config, state, choice_name, options, **kw):
        calls["choice"].append({"name": choice_name, "options": [o["key"] for o in options]})
        # Route to the first option whose key mentions "risk"; else the last.
        keys = [o["key"] for o in options]
        pick = next((k for k in keys if "risk" in k), keys[-1])
        probabilities = {k: (0.9 if k == pick else round(0.1 / max(1, len(keys) - 1), 4)) for k in keys}
        return {"choice": pick, "confidence": 0.88, "probabilities": probabilities, "model": "jev-mock"}

    def noul(config, state, question, **kw):
        calls["noul"].append({"question": question})
        # Tests set calls["next_noul"] to control the outcome; default 0.2 (No).
        return {"noul": calls.get("next_noul", 0.2), "model": "jev-mock"}

    patch("typesafe_score", score)
    patch("typesafe_choice", choice)
    patch("typesafe_noul", noul)

    # Decision nodes resolve Settings via the seam; FakeSession must not be queried.
    from app.services import workflow_engine as we
    monkeypatch.setattr(we, "_jev_decision_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="mock"))
    return calls


def json_state(state):
    import json
    try:
        return json.dumps(state, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(state)


TRIGGER = {"id": "t1", "type": "trigger_manual", "data": {"label": "Trigger", "config": {}}}


def transform_node(node_id, label, text_value):
    return {"id": node_id, "type": "transform",
            "data": {"label": label, "config": {"mappings": [{"target": "text", "value": text_value}]}}}


# ── Score ─────────────────────────────────────────────────────────────────

def test_graph_score_threshold_met_propagates(mock_typesafe, capture_node_runs):
    """trigger → transform(text) → jev_score → sink; score/threshold_met flow downstream."""
    mock_typesafe["next_score_index"] = 4.0  # top anchor → 100 on 0_100
    run = make_run(
        nodes=[
            TRIGGER,
            transform_node("tf1", "Text", "{{trigger.body.document}}"),
            {"id": "sc1", "type": "jev_score",
             "data": {"label": "Score", "config": {
                 "score_name": "ความครบเอกสาร", "input_source": "{{tf1.text}}",
                 "criteria": "ความครบถ้วน|0.5|ครบ\nความชัดเจน|0.5|ชัด",
                 "scale": "0_100", "threshold": 70, "engine": "typesafe_jev"}}},
            transform_node("sink1", "Sink", "ผ่าน: {{sc1.score}} met={{sc1.threshold_met}}"),
        ],
        edges=[
            {"source": "t1", "target": "tf1"},
            {"source": "tf1", "target": "sc1"},
            {"source": "sc1", "target": "sink1"},
        ],
        trigger_input={"body": {"document": "เอกสารครบถ้วนผ่านเกณฑ์"}},
    )
    execute_workflow_run(capture_node_runs(run), run)

    assert run.status == "succeeded", run.error
    out = node_outputs(run)
    assert out["sc1"]["score"] == 100.0
    assert out["sc1"]["threshold_met"] is True
    assert out["sc1"]["provider"].startswith("jev:jev-mock")
    assert "ผ่าน: 100.0" in out["sink1"]["text"] and "met=True" in out["sink1"]["text"]


def test_graph_score_full_below_threshold(mock_typesafe, capture_node_runs):
    run = make_run(
        nodes=[
            TRIGGER,
            transform_node("tf1", "Text", "{{trigger.body.document}}"),
            {"id": "sc1", "type": "jev_score",
             "data": {"label": "Score", "config": {
                 "score_name": "ความครบเอกสาร", "input_source": "{{tf1.text}}",
                 "criteria": "ความครบถ้วน|1.0", "scale": "0_100", "threshold": 70,
                 "engine": "typesafe_jev"}}},
            transform_node("sink1", "Sink", "ได้ {{sc1.score}} met={{sc1.threshold_met}}"),
        ],
        edges=[
            {"source": "t1", "target": "tf1"},
            {"source": "tf1", "target": "sc1"},
            {"source": "sc1", "target": "sink1"},
        ],
        trigger_input={"body": {"document": "ยังไม่ผ่าน"}},
    )
    mock_typesafe["next_score_index"] = 1.0  # second anchor → 25 on 0_100
    execute_workflow_run(capture_node_runs(run), run)

    assert run.status == "succeeded", run.error
    out = node_outputs(run)
    assert out["sc1"]["score"] == 25.0
    assert out["sc1"]["threshold_met"] is False


# ── Choice ────────────────────────────────────────────────────────────────

def _choice_graph(extra_option_line=""):
    options = "sales_agent|Sales\nsupport_agent|Support"
    if extra_option_line:
        options += "\n" + extra_option_line
    # (nodes, edges, trigger_input)
    nodes = [
        TRIGGER,
        transform_node("tf1", "Text", "{{trigger.body.text}}"),
        {"id": "ch1", "type": "jev_choice",
         "data": {"label": "Choice", "config": {
             "choice_name": "เส้นทาง", "input_source": "{{tf1.text}}",
             "options": options, "min_confidence": 0.5, "enable_fallback": True,
             "engine": "typesafe_jev"}}},
        # Three candidate sinks, one per handle; each writes its route name.
        transform_node("s_sales", "SinkSales", "route=sales_agent"),
        transform_node("s_support", "SinkSupport", "route=support_agent"),
        transform_node("s_fallback", "SinkFallback", "route=fallback"),
    ]
    edges = [
        {"source": "t1", "target": "tf1"},
        {"source": "tf1", "target": "ch1"},
        {"source": "ch1", "target": "s_sales", "sourceHandle": "sales_agent"},
        {"source": "ch1", "target": "s_support", "sourceHandle": "support_agent"},
        {"source": "ch1", "target": "s_fallback", "sourceHandle": "fallback"},
    ]
    return nodes, edges, {"body": {"text": "ข้อมูลตัวอย่างสำหรับตัดสินใจ"}}


def test_graph_choice_routes_only_matching_handle(mock_typesafe, capture_node_runs):
    """Only the sink on the chosen handle runs; the other handle sink is skipped."""
    nodes, edges, trigger = _choice_graph()
    run = make_run(nodes, edges, trigger)
    execute_workflow_run(capture_node_runs(run), run)

    assert run.status == "succeeded", run.error
    statuses = node_statuses(run)
    out = node_outputs(run)
    # Mock routes to the LAST key (support_agent — no "risk" present).
    assert out["ch1"]["choice"] == "support_agent"
    assert statuses["s_support"] == "succeeded"
    assert statuses["s_sales"] == "skipped"
    assert statuses["s_fallback"] == "skipped"
    assert out["s_support"]["text"] == "route=support_agent"


def test_graph_choice_risk_key_wins(mock_typesafe, capture_node_runs):
    """Adding a risk_* option flips the mock's pick — proves handle = choice key."""
    nodes, edges, trigger = _choice_graph(extra_option_line="risk_agent|Risk")
    run = make_run(nodes, edges, trigger)
    execute_workflow_run(capture_node_runs(run), run)

    out = node_outputs(run)
    statuses = node_statuses(run)
    assert out["ch1"]["choice"] == "risk_agent"
    assert statuses["s_fallback"] == "skipped"
    # risk_agent handle has no connected sink in this graph; both existing sinks skipped.


def test_graph_choice_fallback_route(mock_typesafe, capture_node_runs):
    """confidence < min_confidence → used_fallback → only the fallback edge runs."""
    nodes, edges, trigger = _choice_graph()
    run = make_run(nodes, edges, trigger)
    # Raise the bar so the mock's 0.88 confidence falls below it.
    run.definition_snapshot["nodes"][2]["data"]["config"]["min_confidence"] = 0.95
    execute_workflow_run(capture_node_runs(run), run)

    statuses = node_statuses(run)
    out = node_outputs(run)
    assert out["ch1"]["used_fallback"] is True
    assert statuses["s_fallback"] == "succeeded"
    assert statuses["s_sales"] == "skipped"
    assert statuses["s_support"] == "skipped"


# ── Noul ──────────────────────────────────────────────────────────────────

def _noul_graph(threshold=0.5, document_text="{{trigger.body.text}}", trigger=None):
    return (
        [
            TRIGGER,
            transform_node("tf1", "Text", document_text),
            {"id": "nl1", "type": "jev_noul",
             "data": {"label": "Noul", "config": {
                 "noul_name": "needs_manual_review",
                 "question": "เอกสารนี้ต้องรีวิวด้วยมือหรือไม่?",
                 "input_source": "{{tf1.text}}", "threshold": threshold,
                 "engine": "typesafe_jev"}}},
            {"id": "cond1", "type": "condition",
             "data": {"label": "Yes?", "config": {
                 "left": "{{nl1.threshold_met}}", "operator": "equals", "right": "True"}}},
            transform_node("sink_true", "SinkReview", "route=manual_review"),
            transform_node("sink_false", "SinkAuto", "route=auto"),
        ],
        [
            {"source": "t1", "target": "tf1"},
            {"source": "tf1", "target": "nl1"},
            {"source": "nl1", "target": "cond1"},
            {"source": "cond1", "target": "sink_true", "sourceHandle": "true"},
            {"source": "cond1", "target": "sink_false", "sourceHandle": "false"},
        ],
        trigger or {"body": {"text": "เอกสารครบถ้วน"}},
    )


def test_graph_noul_condition_true_path(mock_typesafe, capture_node_runs):
    """Incomplete text → noul 0.9 ≥ 0.5 → condition true → review sink runs."""
    nodes, edges, trigger = _noul_graph(trigger={"body": {"text": "ข้อมูลไม่ครบ"}})
    run = make_run(nodes, edges, trigger)
    mock_typesafe["next_noul"] = 0.9
    execute_workflow_run(capture_node_runs(run), run)

    assert run.status == "succeeded", run.error
    out = node_outputs(run)
    statuses = node_statuses(run)
    assert out["nl1"]["noul"] == 0.9
    assert out["nl1"]["threshold_met"] is True
    # Noul must NOT invent vendor-absent fields.
    assert "confidence" not in out["nl1"] and "evidence" not in out["nl1"]
    assert statuses["sink_true"] == "succeeded"
    assert statuses["sink_false"] == "skipped"
    assert out["sink_true"]["text"] == "route=manual_review"


def test_graph_noul_condition_false_path(mock_typesafe, capture_node_runs):
    """Complete text → noul 0.2 < 0.5 → condition false → auto sink runs."""
    nodes, edges, trigger = _noul_graph()  # default trigger already "เอกสารครบถ้วน"
    run = make_run(nodes, edges, trigger)
    mock_typesafe["next_noul"] = 0.2
    execute_workflow_run(capture_node_runs(run), run)

    out = node_outputs(run)
    statuses = node_statuses(run)
    assert out["nl1"]["noul"] == 0.2
    assert out["nl1"]["threshold_met"] is False
    assert statuses["sink_false"] == "succeeded"
    assert statuses["sink_true"] == "skipped"
    assert out["sink_false"]["text"] == "route=auto"


# ── Combined chain ────────────────────────────────────────────────────────

def test_graph_score_then_noul_chain(mock_typesafe, capture_node_runs):
    """score → noul → condition in one graph (roadmap pattern from docs §12)."""
    run = make_run(
        nodes=[
            TRIGGER,
            transform_node("tf1", "Text", "{{trigger.body.document}}"),
            {"id": "sc1", "type": "jev_score",
             "data": {"label": "Score", "config": {
                 "score_name": "ความครบเอกสาร", "input_source": "{{tf1.text}}",
                 "criteria": "ความครบถ้วน|1.0", "scale": "0_100",
                 "engine": "typesafe_jev"}}},
            {"id": "nl1", "type": "jev_noul",
             "data": {"label": "Noul", "config": {
                 "noul_name": "needs_manual_review",
                 "question": "คะแนนยังไม่ผ่านเกณฑ์ ต้องรีวิวด้วยมือหรือไม่?",
                 "input_source": "{{sc1.score}} — {{tf1.text}}",
                 "threshold": 0.5, "engine": "typesafe_jev"}}},
            {"id": "cond1", "type": "condition",
             "data": {"label": "Yes?", "config": {
                 "left": "{{nl1.threshold_met}}", "operator": "equals", "right": "True"}}},
            transform_node("sink_true", "SinkReview", "route=manual_review"),
            transform_node("sink_false", "SinkAuto", "route=auto"),
        ],
        edges=[
            {"source": "t1", "target": "tf1"},
            {"source": "tf1", "target": "sc1"},
            {"source": "sc1", "target": "nl1"},
            {"source": "nl1", "target": "cond1"},
            {"source": "cond1", "target": "sink_true", "sourceHandle": "true"},
            {"source": "cond1", "target": "sink_false", "sourceHandle": "false"},
        ],
        trigger_input={"body": {"document": "ยังไม่ผ่าน"}},
    )
    mock_typesafe["next_score_index"] = 1.0
    mock_typesafe["next_noul"] = 0.9
    execute_workflow_run(capture_node_runs(run), run)

    assert run.status == "succeeded", run.error
    out = node_outputs(run)
    assert out["sc1"]["score"] == 25.0
    assert out["nl1"]["noul"] == 0.9
    assert out["nl1"]["threshold_met"] is True
    assert node_statuses(run)["sink_true"] == "succeeded"
    assert node_statuses(run)["sink_false"] == "skipped"


# ── Fail loud ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("node_type", ["jev_score", "jev_choice", "jev_noul"])
def test_graph_jev_not_configured_fails_run(monkeypatch, capture_node_runs, node_type):
    """TypeSafe missing + required engine → whole run failed, TypeSafe named in error."""
    monkeypatch.setattr("app.services.typesafe.typesafe_is_configured", lambda setting=None: False)
    configs = {
        "jev_score": {"score_name": "s", "input_source": "x", "criteria": "a|1",
                      "scale": "0_100", "engine": "typesafe_jev"},
        "jev_choice": {"choice_name": "c", "input_source": "x",
                       "options": "a|A\nb|B", "engine": "typesafe_jev"},
        "jev_noul": {"noul_name": "n", "question": "q?", "input_source": "x",
                     "threshold": 0.5, "engine": "typesafe_jev"},
    }
    run = make_run(
        nodes=[
            TRIGGER,
            {"id": "d1", "type": node_type, "data": {"label": "Decision", "config": configs[node_type]}},
        ],
        edges=[{"source": "t1", "target": "d1"}],
    )
    execute_workflow_run(capture_node_runs(run), run)

    assert run.status == "failed"
    assert "TypeSafe" in (run.error or "")
    statuses = node_statuses(run)
    assert statuses["d1"] == "failed"


def test_graph_jev_auto_engine_also_fails_without_typesafe(monkeypatch, capture_node_runs):
    """Decision 'auto' ≠ mapping auto-prune: TypeSafe missing still fails loud."""
    monkeypatch.setattr("app.services.typesafe.typesafe_is_configured", lambda setting=None: False)
    run = make_run(
        nodes=[
            TRIGGER,
            {"id": "sc1", "type": "jev_score",
             "data": {"label": "Score", "config": {
                 "score_name": "s", "input_source": "x", "criteria": "a|1",
                 "scale": "0_100", "engine": "auto"}}},
        ],
        edges=[{"source": "t1", "target": "sc1"}],
    )
    execute_workflow_run(capture_node_runs(run), run)

    assert run.status == "failed"
    assert "TypeSafe" in (run.error or "")


# ── Optional live mark ────────────────────────────────────────────────────

@pytest.mark.skipif(
    os.environ.get("INSIGHTDOC_JEV_LIVE") != "1",
    reason="Live smoke: set INSIGHTDOC_JEV_LIVE=1 with auth in /tmp/jev_tok.txt",
)
def test_live_smoke_workflows():
    """Re-trigger production smoke WFs via API (manual, no credential edits)."""
    from hermes_tools import terminal  # only available in agent runtime

    token = open("/tmp/jev_tok.txt").read().strip().splitlines()[-1]
    results = []
    for wf_id in (
        "2f172e04-5aa6-4804-9412-ff5d81431c68",  # jev-p0-smoke (field_mapping)
    ):
        r = terminal(
            f"curl -s --max-time 60 -X POST https://insightdoc-mini.softnix.ai/api/v1/workflows/{wf_id}/run "
            f"-H 'Authorization: Bearer {token}' -H 'Content-Type: application/json' -d '{{}}'",
            timeout=90,
        )
        results.append(r["output"])
    assert all("202" in x or '"status"' in x for x in results)
