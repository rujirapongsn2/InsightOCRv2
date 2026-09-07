from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import field_mapping as mapping


def schema(*fields):
    return SimpleNamespace(name="test", fields=list(fields))


def fail(*args, **kwargs):
    raise TimeoutError("provider timeout")


def test_partial_failure_only_retries_invalid_field(monkeypatch):
    monkeypatch.setattr(mapping, "extract_structure", lambda *a, **k: {"name": "Alice", "total": "invalid"})
    fallback = Mock(return_value=({"total": 25}, "llm:test"))
    monkeypatch.setattr(mapping, "llm_mapping", fallback)
    values, report = mapping.map_fields("Alice owes 25", schema(
        {"name": "name", "type": "text"}, {"name": "total", "type": "currency"}), None)
    assert values == {"name": "Alice", "total": 25}
    assert set(fallback.call_args.args[1]["properties"]) == {"total"}
    assert report["fields"]["name"]["status"] == "source_matched"


def test_fixed_values_survive_all_provider_failures(monkeypatch):
    monkeypatch.setattr(mapping, "extract_fixed_position_fields", lambda *a: (
        {"id": "A1"}, {"id": {"page": 1, "cleaned_value": "A1"}}))
    monkeypatch.setattr(mapping, "extract_structure", fail)
    monkeypatch.setattr(mapping, "llm_mapping", fail)
    values, report = mapping.map_fields("", schema(
        {"name": "id", "type": "text", "locator": {"page": 1}},
        {"name": "total", "type": "number"}), None, "source.pdf")
    assert values == {"id": "A1"}
    assert report["status"] == "partial"
    assert report["fields"]["id"]["page"] == 1


def test_provider_conflict_never_silently_replaces_first_candidate(monkeypatch):
    monkeypatch.setattr(mapping, "extract_structure", lambda *a, **k: {"id": "A"})
    monkeypatch.setattr(mapping, "llm_mapping", lambda *a: ({"id": "B"}, "llm:test"))
    values, report = mapping.map_fields("unclear", schema({"name": "id", "type": "text"}), None)
    assert values == {"id": "A"}
    assert report["fields"]["id"]["alternative"]["value"] == "B"
    assert report["fields"]["id"]["status"] == "needs_review"


def test_no_empty_fallback_overwrites_existing_candidate(monkeypatch):
    monkeypatch.setattr(mapping, "extract_structure", lambda *a, **k: {"id": "A"})
    monkeypatch.setattr(mapping, "llm_mapping", lambda *a: ({"id": None}, "llm:test"))
    values, report = mapping.map_fields("unclear", schema({"name": "id", "type": "text"}), None)
    assert values == {"id": "A"}
    assert report["fields"]["id"]["status"] == "needs_review"


def test_numeric_substring_is_not_source_support():
    assert mapping.source_evidence(25, "Amount 1250")["status"] == "needs_review"
    assert mapping.source_evidence(25, "Amount 25.99")["status"] == "needs_review"
    assert mapping.source_evidence(1250.5, "Amount 1,250.50")["quote"] == "1,250.50"


def test_absent_optional_field_is_not_a_processing_failure(monkeypatch):
    monkeypatch.setattr(mapping, "extract_structure", lambda *a, **k: {"note": None})
    values, report = mapping.map_fields("No notes", schema({"name": "note", "type": "text"}), None, engine="softnix")
    assert values == {}
    assert report["status"] == "completed"
    assert report["missing_fields"] == ["note"]
    assert report["unresolved_fields"] == []


def test_schema_field_named_answer_is_not_unwrapped():
    assert mapping.parse_mapping_result({"answer": "yes"}, {"answer"}) == {"answer": "yes"}


def test_explicit_label_rule_avoids_provider_call(monkeypatch):
    remote = Mock()
    monkeypatch.setattr(mapping, "extract_structure", remote)
    values, _ = mapping.map_fields("Invoice No: INV-42", schema(
        {"name": "id", "type": "text", "validation_rules": {"source_labels": ["Invoice No"]}}), None)
    assert values == {"id": "INV-42"}
    remote.assert_not_called()


def test_admin_can_disable_automatic_fallback(monkeypatch):
    db = Mock()
    db.query.return_value.first.return_value = SimpleNamespace(mapping_engine="auto", mapping_fallback_enabled=False)
    monkeypatch.setattr(mapping, "extract_structure", fail)
    fallback = Mock()
    monkeypatch.setattr(mapping, "llm_mapping", fallback)
    _, report = mapping.map_fields("Text", schema({"name": "id", "type": "text"}), db)
    fallback.assert_not_called()
    assert len(report["attempts"]) == 1


def test_arithmetic_conflict_does_not_correct_document():
    values = {"quantity": 2, "unit_price": 10, "amount": 25}
    evidence = {"amount": {"status": "source_matched"}}
    mapping.validate_relationships(values, [{"name": "amount", "validation_rules": {
        "equals_product_of": ["quantity", "unit_price"]}}], evidence)
    assert values["amount"] == 25
    assert evidence["amount"]["status"] == "needs_review"
    assert evidence["amount"]["arithmetic"]["expected"] == "20"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "NaN"])
def test_non_finite_values_are_not_persisted(monkeypatch, value):
    monkeypatch.setattr(mapping, "extract_structure", lambda *a, **k: {"total": value})
    values, report = mapping.map_fields("Total unknown", schema({"name": "total", "type": "number"}), None, engine="softnix")
    assert values == {}
    assert report["unresolved_fields"] == ["total"]


def test_fixed_only_never_calls_remote_provider(monkeypatch):
    remote = Mock(side_effect=AssertionError("unexpected remote call"))
    monkeypatch.setattr(mapping, "extract_structure", remote)
    mapping.map_fields("text", schema({"name": "id", "type": "text"}), None, engine="fixed")
    remote.assert_not_called()


def test_total_budget_prevents_next_provider(monkeypatch):
    clock = iter([0, 301, 302])
    monkeypatch.setattr(mapping.time, "monotonic", lambda: next(clock))
    remote = Mock()
    monkeypatch.setattr(mapping, "extract_structure", remote)
    _, report = mapping.map_fields("text", schema({"name": "id", "type": "text"}), None)
    remote.assert_not_called()
    assert report["attempts"][0]["status"] == "timeout"


def test_provider_request_timeouts_are_independent(monkeypatch):
    softnix = Mock(return_value={"id": "A"})
    monkeypatch.setattr(mapping, "extract_structure", softnix)
    mapping.map_fields("id A", schema({"name": "id", "type": "text"}), None, engine="softnix")
    assert softnix.call_args.kwargs["timeout"] == 240

    llm = Mock(return_value=({"id": "A"}, "llm:test"))
    monkeypatch.setattr(mapping, "llm_mapping", llm)
    mapping.map_fields("id A", schema({"name": "id", "type": "text"}), None, engine="llm")
    assert llm.call_args.args[3] == 120


def test_sample_uses_job_type_conversion(monkeypatch):
    from app.api.v1.endpoints.schemas import _extract_bbox_preview_in_worker
    monkeypatch.setattr(mapping, "extract_fixed_position_fields", lambda *a: (
        {"total": "1,250.50"}, {"total": {"page": 1, "cleaned_value": "1,250.50"}}))
    values, evidence = _extract_bbox_preview_in_worker("sample.pdf", [
        {"name": "total", "type": "currency", "locator": {"page": 1}}])
    assert values["total"] == 1250.5
    assert evidence["total"]["page"] == 1
