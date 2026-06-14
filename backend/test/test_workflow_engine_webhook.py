import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")

from app.models.workflow import WorkflowRun, WorkflowNodeRun
from app.services.workflow_engine import execute_workflow_run


class FakeSession:
    def __init__(self):
        self.node_runs = []

    def add(self, value):
        if isinstance(value, WorkflowNodeRun):
            self.node_runs.append(value)

    def commit(self):
        pass


def make_run(nodes, edges, trigger_input=None):
    return WorkflowRun(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        status="queued",
        trigger_type="webhook",
        trigger_input=trigger_input or {},
        definition_snapshot={"nodes": nodes, "edges": edges},
    )


def test_webhook_trigger_and_response_result():
    run = make_run(
        nodes=[
            {"id": "wh_1", "type": "trigger_webhook", "data": {"label": "Webhook", "config": {}}},
            {
                "id": "res_1",
                "type": "webhook_response",
                "data": {
                    "label": "Response",
                    "config": {
                        "status_code": 200,
                        "body": "{{trigger.body.events.0.message.text}}",
                    },
                },
            },
        ],
        edges=[{"source": "wh_1", "target": "res_1"}],
        trigger_input={"body": {"events": [{"message": {"text": "hello LINE"}}]}},
    )

    execute_workflow_run(FakeSession(), run)

    assert run.status == "succeeded"
    assert run.result_node_id == "res_1"
    assert run.result == {"visible": True, "status_code": 200, "body": "hello LINE"}


def test_webhook_result_falls_back_to_last_successful_non_response_node():
    run = make_run(
        nodes=[
            {"id": "wh_1", "type": "trigger_webhook", "data": {"label": "Webhook", "config": {}}},
            {
                "id": "tf_1",
                "type": "transform",
                "data": {
                    "label": "Transform",
                    "config": {"mappings": [{"target": "value", "value": "{{trigger.body.foo}}"}]},
                },
            },
            {
                "id": "res_1",
                "type": "webhook_response",
                "data": {
                    "label": "Hidden Response",
                    "config": {
                        "body": {"ignored": True},
                        "condition_left": "no",
                        "condition_operator": "equals",
                        "condition_right": "yes",
                    },
                },
            },
        ],
        edges=[
            {"source": "wh_1", "target": "tf_1"},
            {"source": "tf_1", "target": "res_1"},
        ],
        trigger_input={"body": {"foo": "bar"}},
    )

    execute_workflow_run(FakeSession(), run)

    assert run.status == "succeeded"
    assert run.result_node_id == "tf_1"
    assert run.result == {"value": "bar"}


def test_webhook_workflow_cycle_fails_before_execution():
    run = make_run(
        nodes=[
            {"id": "wh_1", "type": "trigger_webhook", "data": {"label": "Webhook", "config": {}}},
            {"id": "tf_1", "type": "transform", "data": {"label": "Transform", "config": {"mappings": []}}},
        ],
        edges=[
            {"source": "wh_1", "target": "tf_1"},
            {"source": "tf_1", "target": "wh_1"},
        ],
    )

    execute_workflow_run(FakeSession(), run)

    assert run.status == "failed"
    assert run.error == "Workflow contains a cycle — must be a DAG"
