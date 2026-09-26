"""Thresholds outside the range a Jev node can produce are rejected, not silently never met."""
import pytest

from app.services import workflow_engine as we


@pytest.mark.parametrize("ntype,config,fields", [
    ("jev_score", {"scale": "1_5", "threshold": 80}, ["threshold"]),
    ("jev_score", {"scale": "1_5", "threshold": 4}, []),
    ("jev_score", {"threshold": 80}, []),  # default 0–100
    ("jev_score", {"scale": "0_10", "threshold": "abc"}, ["threshold"]),
    ("jev_score", {"scale": "0_10", "threshold": ""}, []),
    ("jev_score", {"scale": "0_10", "threshold": "{{ n1.value }}"}, []),
    ("jev_noul", {"threshold": 70}, ["threshold"]),
    ("jev_noul", {"threshold": 0.7}, []),
    ("jev_choice", {"pick_rule": "first_above_threshold", "probability_threshold": 1.5}, ["probability_threshold"]),
    ("jev_choice", {"pick_rule": "highest", "probability_threshold": 1.5}, []),  # not used by this rule
    ("jev_choice", {"min_confidence": -0.1}, ["min_confidence"]),
])
def test_threshold_ranges(ntype, config, fields):
    assert [field for field, _message in we.jev_threshold_issues(ntype, config)] == fields


def test_run_time_check_names_the_node():
    with pytest.raises(we.NodeExecutionError, match="Score: คะแนนขั้นต่ำต้องอยู่ในช่วงคะแนน 1–5"):
        we._exec_jev_score(None, {"scale": "1_5", "threshold": 80}, {}, lambda m: None)
