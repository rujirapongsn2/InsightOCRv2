"""jev_score / jev_choice workflow decision node tests (P0 decision nodes)."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import workflow_engine as we


@pytest.fixture
def ts_ready(monkeypatch):
    monkeypatch.setattr(we, "_jev_decision_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="k"))


def _score_answer(index, confidence=0.86):
    """Wrapper-shaped return of typesafe_score (not raw system_one response)."""
    return {"index": index, "confidence": confidence, "probabilities": {}, "model": "jev-test"}


def _choice_answer(key, confidence=0.81, probabilities=None):
    """Wrapper-shaped return of typesafe_choice."""
    return {"choice": key, "confidence": confidence, "probabilities": probabilities or {}, "model": "jev-test"}


# ── registration ──────────────────────────────────────────────────────────

def test_decision_nodes_registered():
    types = {n["type"]: n for n in we.NODE_TYPES}
    for key in ("jev_score", "jev_choice"):
        assert key in types and types[key]["category"] == "data"
        assert key in we.EXECUTORS
    engines = next(f for f in types["jev_score"]["config_fields"] if f["name"] == "engine")
    assert set(engines["options"]) == {"typesafe_jev", "auto"}


# ── jev_score ─────────────────────────────────────────────────────────────

def test_score_requires_score_name(ts_ready):
    with pytest.raises(we.NodeExecutionError, match="score_name"):
        we._exec_jev_score(None, {"score_name": "", "input_source": "x", "criteria": "a|1"}, {}, lambda m: None)


def test_score_requires_criteria(ts_ready):
    with pytest.raises(we.NodeExecutionError, match="เกณฑ์"):
        we._exec_jev_score(None, {"score_name": "s", "input_source": "x", "criteria": []}, {}, lambda m: None)


def test_score_not_configured_fails_loud(monkeypatch):
    monkeypatch.setattr(we, "_jev_decision_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint=None, typesafe_api_key=None))
    with pytest.raises(we.NodeExecutionError, match="TypeSafe"):
        we._exec_jev_score(None, {"score_name": "s", "input_source": "x", "criteria": "a|1",
                                  "engine": "typesafe_jev"}, {}, lambda m: None)
    # auto must ALSO fail loud for decision nodes (no silent prune)
    with pytest.raises(we.NodeExecutionError, match="TypeSafe"):
        we._exec_jev_score(None, {"score_name": "s", "input_source": "x", "criteria": "a|1",
                                  "engine": "auto"}, {}, lambda m: None)


def test_score_maps_index_to_scale(ts_ready, monkeypatch):
    calls = {}

    def fake_typesafe_score(config, state, score_name, rubric, scale, **kw):
        calls["scale"] = scale
        calls["rubric"] = rubric
        calls["state"] = state
        assert state["input"] == "เนื้อหาเอกสาร"
        return _score_answer(4.0)  # index 4/5 levels = 0.8 normalized

    monkeypatch.setattr("app.services.typesafe.typesafe_score", fake_typesafe_score)
    out = we._exec_jev_score(None, {
        "score_name": "ความครบเอกสาร", "input_source": "เนื้อหาเอกสาร",
        "criteria": "คุณภาพเอกสาร|0.4|ครบถ้วน\nความชัดเจน|0.6|อ่านง่าย",
        "scale": "0_100", "threshold": 70, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["score"] == 100.0           # 0_100 anchors 0/25/50/75/100 → index 4/4 = top
    assert out["score"] >= out["threshold"]
    assert out["scale"] == "0_100"
    assert out["threshold"] == 70.0
    assert out["threshold_met"] is True
    assert out["provider"] == "jev:jev-test"
    assert out["confidence"] == 0.86
    # weights normalized to 1.0 total
    assert abs(sum(c["weight"] for c in out["criteria"]) - 1.0) < 1e-3
    assert calls["scale"] == "0_100"


def test_score_scale_1_5_mapping(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_score",
                        lambda *a, **k: _score_answer(0.0))  # lowest index
    out = we._exec_jev_score(None, {
        "score_name": "s", "input_source": "x", "criteria": "a",
        "scale": "1_5", "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["score"] == 1.0             # 1_5 floor
    assert out["threshold_met"] is None    # no threshold configured


def test_score_threshold_not_met(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_score",
                        lambda *a, **k: _score_answer(1.0))  # index 1/5 = 0.2 → 20
    out = we._exec_jev_score(None, {
        "score_name": "s", "input_source": "x", "criteria": "a|1",
        "scale": "0_100", "threshold": 70, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["score"] == 25.0  # 0_100 scale anchors: 0/25/50/75/100 → index1 = 25
    assert out["threshold_met"] is False


def test_score_empty_input_fails(ts_ready):
    with pytest.raises(we.NodeExecutionError, match="input_source"):
        we._exec_jev_score(None, {"score_name": "s", "input_source": "   ",
                                  "criteria": "a|1"}, {}, lambda m: None)


# ── jev_choice ────────────────────────────────────────────────────────────

_OPTIONS = "sales_agent|Sales Agent\nsupport_agent|Support Agent"


def test_choice_requires_two_unique_keys(ts_ready):
    with pytest.raises(we.NodeExecutionError, match="2 ตัว"):
        we._exec_jev_choice(None, {"choice_name": "c", "input_source": "x",
                                   "options": "only_one|One"}, {}, lambda m: None)
    with pytest.raises(we.NodeExecutionError, match="ซ้ำ"):
        we._exec_jev_choice(None, {"choice_name": "c", "input_source": "x",
                                   "options": "dup|One\ndup|Two"}, {}, lambda m: None)


def test_choice_not_configured_fails_loud(monkeypatch):
    monkeypatch.setattr(we, "_jev_decision_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint=None, typesafe_api_key=None))
    with pytest.raises(we.NodeExecutionError, match="TypeSafe"):
        we._exec_jev_choice(None, {"choice_name": "c", "input_source": "x",
                                   "options": _OPTIONS, "engine": "typesafe_jev"}, {}, lambda m: None)


def test_choice_highest_with_probabilities(ts_ready, monkeypatch):
    captured = {}

    def fake_typesafe_choice(config, state, choice_name, options, **kw):
        captured["options"] = options
        captured["state"] = state
        assert state["input"] == "ข้อมูล"
        return _choice_answer("sales_agent", 0.81,
                              {"sales_agent": 0.62, "support_agent": 0.38})

    monkeypatch.setattr("app.services.typesafe.typesafe_choice", fake_typesafe_choice)
    out = we._exec_jev_choice(None, {
        "choice_name": "เส้นทาง", "input_source": "ข้อมูล", "options": _OPTIONS,
        "pick_rule": "highest", "min_confidence": 0.55, "enable_fallback": True,
        "show_probabilities": True, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["choice"] == "sales_agent"
    assert out["label"] == "Sales Agent"
    assert out["probability"] == 0.62
    assert out["confidence"] == 0.81
    assert out["used_fallback"] is False
    assert out["policy"] == {"pick": "highest", "min_confidence": 0.55}
    assert {o["key"]: o["probability"] for o in out["options"]} == {"sales_agent": 0.62, "support_agent": 0.38}
    assert captured["options"][0]["key"] == "sales_agent"


def test_choice_highest_overrides_wrong_api_choice(ts_ready, monkeypatch):
    """Major 1: when probabilities disagree with API choice, highest prob wins."""
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("support_agent", 0.9,
                                                       {"sales_agent": 0.7, "support_agent": 0.3}))
    out = we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": "x", "options": _OPTIONS,
        "pick_rule": "highest", "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["choice"] == "sales_agent"          # 0.7 > 0.3
    assert out["probability"] == 0.7
    assert out["policy"]["pick"] == "highest"


def test_choice_first_above_threshold_picks_first_qualifying(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("support_agent", 0.9,
                                                       {"sales_agent": 0.9, "support_agent": 0.1}))
    out = we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": "x", "options": _OPTIONS,
        "pick_rule": "first_above_threshold", "probability_threshold": 0.05,
        "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["choice"] == "sales_agent"          # first in configured order ≥ 0.05
    assert out["policy"]["probability_threshold"] == 0.05


def test_choice_first_above_none_qualifying_falls_back(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("support_agent", 0.9,
                                                       {"sales_agent": 0.5, "support_agent": 0.5}))
    out = we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": "x", "options": _OPTIONS,
        "pick_rule": "first_above_threshold", "probability_threshold": 0.9,
        "enable_fallback": True, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["used_fallback"] is True
    assert out["policy"]["pick"] == "first_above_threshold"


def test_choice_first_above_none_qualifying_no_fallback_fails(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("support_agent", 0.9,
                                                       {"sales_agent": 0.5, "support_agent": 0.5}))
    with pytest.raises(we.NodeExecutionError, match="fallback"):
        we._exec_jev_choice(None, {
            "choice_name": "c", "input_source": "x", "options": _OPTIONS,
            "pick_rule": "first_above_threshold", "probability_threshold": 0.9,
            "enable_fallback": False, "engine": "typesafe_jev",
        }, {"_node_id": "n1"}, lambda m: None)


def test_choice_fields_to_use_json_string_filters(ts_ready, monkeypatch):
    """Major 4: input_source as JSON string + fields_to_use filters keys."""
    import json as _json
    captured = {}

    def fake_choice(config, state, choice_name, options, **kw):
        captured["state"] = state
        return _choice_answer("sales_agent", 0.9)

    monkeypatch.setattr("app.services.typesafe.typesafe_choice", fake_choice)
    src = _json.dumps({"invoice_no": "INV-1", "noise": "drop-me"}, ensure_ascii=False)
    we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": src, "fields_to_use": "invoice_no",
        "options": _OPTIONS, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert "noise" not in captured["state"]["input"]
    assert "INV-1" in captured["state"]["input"]


def test_choice_fields_to_use_unparseable_fails_loud(ts_ready):
    """Major 4: fields_to_use on a plain-string source → fail, not silent no-op."""
    with pytest.raises(we.NodeExecutionError, match="fields_to_use"):
        we._exec_jev_choice(None, {
            "choice_name": "c", "input_source": "ข้อความล้วน ไม่ใช่ JSON",
            "fields_to_use": "invoice_no", "options": _OPTIONS, "engine": "typesafe_jev",
        }, {"_node_id": "n1"}, lambda m: None)


def test_choice_fields_to_use_missing_key_fails(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("sales_agent", 0.9))
    with pytest.raises(we.NodeExecutionError, match="fields_to_use"):
        we._exec_jev_choice(None, {
            "choice_name": "c",
            "input_source": '{"a": 1}',
            "fields_to_use": "not_there", "options": _OPTIONS, "engine": "typesafe_jev",
        }, {"_node_id": "n1"}, lambda m: None)


def test_choice_resolve_error_wrapped_as_node_error(monkeypatch):
    """Major 3: resolve_typesafe_config raising → NodeExecutionError with Settings CTA."""
    from app.services.typesafe import TypeSafeConfigurationError
    monkeypatch.setattr(we, "_jev_decision_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="k"))
    monkeypatch.setattr("app.services.typesafe.resolve_typesafe_config",
                        lambda setting: (_ for _ in ()).throw(
                            TypeSafeConfigurationError("key invalid")))
    with pytest.raises(we.NodeExecutionError, match="Settings"):
        we._exec_jev_choice(None, {"choice_name": "c", "input_source": "x",
                                   "options": _OPTIONS, "engine": "typesafe_jev"},
                            {"_node_id": "n1"}, lambda m: None)


def test_noul_input_from_is_template_not_self(ts_ready, monkeypatch):
    """Minor 6: input_from records the configured input_source, never the node id."""
    monkeypatch.setattr("app.services.typesafe.typesafe_noul",
                        lambda *a, **k: _noul_answer(0.42))
    out = we._exec_jev_noul(None, {
        "noul_name": "n", "question": "q?", "input_source": "{{jobs_1.ocr_text}}",
        "threshold": 0.5, "engine": "typesafe_jev",
        "_input_source_template": "{{jobs_1.ocr_text}}",
    }, {"_node_id": "nl1"}, lambda m: None)
    assert out["input_from"] == "{{jobs_1.ocr_text}}"
    assert out["input_from"] != "nl1"


def test_score_has_no_evidence_key_and_no_include_evidence_field(ts_ready, monkeypatch):
    """Major 2: score never returns fake evidence; UI field removed."""
    monkeypatch.setattr("app.services.typesafe.typesafe_score",
                        lambda *a, **k: _score_answer(4.0))
    out = we._exec_jev_score(None, {
        "score_name": "s", "input_source": "x", "criteria": "a|1", "scale": "0_100",
        "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert "evidence" not in out
    node_type = next(n for n in we.NODE_TYPES if n["type"] == "jev_score")
    assert "include_evidence" not in [f["name"] for f in node_type["config_fields"]]
    assert "include_evidence" not in [f["name"] for f in node_type["output_fields"] or []]


def test_score_criteria_label_is_rubric_not_scores():
    node_type = next(n for n in we.NODE_TYPES if n["type"] == "jev_score")
    crit = next(f for f in node_type["output_fields"] if f["name"] == "criteria")
    assert "rubric" in crit["label"] or "เกณฑ์" in crit["label"]
    assert "คะแนนรายเกณฑ์" not in crit["label"]  # must not imply per-criterion scores


def test_choice_low_confidence_uses_fallback(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("sales_agent", 0.30,
                                                       {"sales_agent": 0.6, "support_agent": 0.4}))
    out = we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": "x", "options": _OPTIONS,
        "min_confidence": 0.55, "enable_fallback": True, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["choice"] == "sales_agent"      # still reports the pick
    assert out["used_fallback"] is True        # but routes via fallback handle


def test_choice_low_confidence_without_fallback_stays(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("support_agent", 0.30))
    out = we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": "x", "options": _OPTIONS,
        "min_confidence": 0.55, "enable_fallback": False, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["choice"] == "support_agent"
    assert out["used_fallback"] is False


def test_choice_no_probabilities_never_fabricates_one_hot(ts_ready, monkeypatch):
    """Minor 5: provider omitted probabilities → no invented 1.0/0.0 numbers."""
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("support_agent", 0.9))
    out = we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": "x", "options": _OPTIONS,
        "show_probabilities": True, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert out["choice"] == "support_agent"
    assert out["probability"] is None
    assert all("probability" not in o for o in out["options"])
    assert "evidence" not in out  # never fabricate evidence either


def test_choice_hide_probabilities(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("sales_agent", 0.9,
                                                       {"sales_agent": 0.9, "support_agent": 0.1}))
    out = we._exec_jev_choice(None, {
        "choice_name": "c", "input_source": "x", "options": _OPTIONS,
        "show_probabilities": False, "engine": "typesafe_jev",
    }, {"_node_id": "n1"}, lambda m: None)
    assert all("probability" not in o for o in out["options"])
    assert out["probability"] is None  # hidden → omitted, not fabricated


def test_choice_invalid_pick_key_fails(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_choice",
                        lambda *a, **k: _choice_answer("hacker", 0.99))
    with pytest.raises(we.NodeExecutionError, match="รายการ"):
        we._exec_jev_choice(None, {"choice_name": "c", "input_source": "x",
                                   "options": _OPTIONS}, {}, lambda m: None)


# ── jev_noul (P2) ─────────────────────────────────────────────────────────

def _noul_answer(noul, model="jev-test"):
    """Wrapper-shaped return of typesafe_noul (no confidence/evidence by design)."""
    return {"noul": noul, "model": model}


def test_noul_registered():
    types = {n["type"]: n for n in we.NODE_TYPES}
    n = types.get("jev_noul")
    assert n and n["category"] == "data"
    assert "jev_noul" in we.EXECUTORS
    names = [f["name"] for f in n["config_fields"]]
    assert {"noul_name", "question", "input_source", "threshold", "engine"} <= set(names)
    # no confidence/evidence toggles — vendor does not provide them
    assert "include_confidence" not in names and "include_evidence" not in names


def test_noul_requires_name_and_question(ts_ready):
    with pytest.raises(we.NodeExecutionError, match="noul_name"):
        we._exec_jev_noul(None, {"noul_name": "", "question": "q?", "input_source": "x",
                                 "engine": "typesafe_jev"}, {"_node_id": "n1"}, lambda m: None)
    with pytest.raises(we.NodeExecutionError, match="question"):
        we._exec_jev_noul(None, {"noul_name": "n", "question": "", "input_source": "x",
                                 "engine": "typesafe_jev"}, {"_node_id": "n1"}, lambda m: None)


def test_noul_not_configured_fails_loud(monkeypatch):
    monkeypatch.setattr(we, "_jev_decision_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint=None, typesafe_api_key=None))
    for engine in ("typesafe_jev", "auto"):
        with pytest.raises(we.NodeExecutionError, match="TypeSafe"):
            we._exec_jev_noul(None, {"noul_name": "n", "question": "q?", "input_source": "x",
                                     "engine": engine}, {"_node_id": "n1"}, lambda m: None)


def test_noul_returns_probability_and_threshold(ts_ready, monkeypatch):
    captured = {}

    def fake_typesafe_noul(config, state, question, **kw):
        captured["question"] = question
        captured["state"] = state
        return _noul_answer(0.82)

    monkeypatch.setattr("app.services.typesafe.typesafe_noul", fake_typesafe_noul)
    out = we._exec_jev_noul(None, {
        "noul_name": "needs_manual_review",
        "question": "เอกสารนี้ต้องรีวิวด้วยมือหรือไม่?",
        "input_source": "ข้อมูลเอกสาร", "threshold": 0.5, "engine": "typesafe_jev",
    }, {"_node_id": "sc1"}, lambda m: None)
    assert out["noul"] == 0.82
    assert out["threshold"] == 0.5
    assert out["threshold_met"] is True
    assert out["question"] == "เอกสารนี้ต้องรีวิวด้วยมือหรือไม่?"
    assert out["noul_name"] == "needs_manual_review"
    assert out["provider"].startswith("jev:")
    assert out["input_from"] == "ข้อมูลเอกสาร"  # Minor 6: raw configured input_source, not node id
    assert captured["question"].startswith("เอกสารนี้ต้องรีวิว")
    # no fabricated fields — vendor provides neither
    assert "confidence" not in out and "evidence" not in out


def test_noul_threshold_boundary_is_inclusive(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_noul", lambda *a, **k: _noul_answer(0.5))
    out = we._exec_jev_noul(None, {"noul_name": "n", "question": "q?", "input_source": "x",
                                   "threshold": 0.5, "engine": "typesafe_jev"},
                            {"_node_id": "n1"}, lambda m: None)
    assert out["threshold_met"] is True   # >= is inclusive per USAGE


def test_noul_below_threshold(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_noul", lambda *a, **k: _noul_answer(0.31))
    out = we._exec_jev_noul(None, {"noul_name": "n", "question": "q?", "input_source": "x",
                                   "threshold": 0.5, "engine": "typesafe_jev"},
                            {"_node_id": "n1"}, lambda m: None)
    assert out["threshold_met"] is False


def test_noul_without_threshold_omits_decision(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_noul", lambda *a, **k: _noul_answer(0.44))
    out = we._exec_jev_noul(None, {"noul_name": "n", "question": "q?", "input_source": "x",
                                   "engine": "typesafe_jev"},
                            {"_node_id": "n1"}, lambda m: None)
    assert out["noul"] == 0.44
    assert out["threshold"] is None and out["threshold_met"] is None


def test_noul_missing_noul_value_fails(ts_ready, monkeypatch):
    monkeypatch.setattr("app.services.typesafe.typesafe_noul", lambda *a, **k: _noul_answer(None))
    with pytest.raises(we.NodeExecutionError, match="noul"):
        we._exec_jev_noul(None, {"noul_name": "n", "question": "q?", "input_source": "x",
                                 "engine": "typesafe_jev"}, {"_node_id": "n1"}, lambda m: None)
