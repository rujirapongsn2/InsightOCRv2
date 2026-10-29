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
    db.query.return_value.first.return_value = SimpleNamespace(
        mapping_engine="auto",
        mapping_fallback_enabled=False,
        api_token="token",
        api_endpoint="http://ocr.example",
        structured_output_endpoint="http://ocr.example/structured-output",
        typesafe_endpoint="https://api.typesafe.ai",
        typesafe_api_key="tsk_test",
    )
    monkeypatch.setattr(mapping, "extract_structure", fail)
    fallback = Mock()
    monkeypatch.setattr(mapping, "llm_mapping", fallback)
    monkeypatch.setattr(mapping, "jev_mapping", fail)
    _, report = mapping.map_fields("Text", schema({"name": "id", "type": "text"}), db)
    fallback.assert_not_called()
    assert len(report["attempts"]) == 2
    assert [attempt["provider"] for attempt in report["attempts"]] == ["softnix", "jev"]


def test_auto_skips_unconfigured_mapping_engines(monkeypatch):
    """Auto must not call engines that have no credentials configured."""
    db = Mock()
    db.query.return_value.first.return_value = SimpleNamespace(
        mapping_engine="auto",
        mapping_fallback_enabled=True,
        api_token="",
        api_endpoint="",
        structured_output_endpoint="",
        typesafe_endpoint="",
        typesafe_api_key="",
        mapping_fallback_provider_id=None,
    )
    # No active LLM provider either
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.filter.return_value.first.return_value = None

    softnix = Mock(side_effect=AssertionError("softnix should be skipped"))
    jev = Mock(side_effect=AssertionError("jev should be skipped"))
    llm = Mock(side_effect=AssertionError("llm should be skipped"))
    monkeypatch.setattr(mapping, "extract_structure", softnix)
    monkeypatch.setattr(mapping, "jev_mapping", jev)
    monkeypatch.setattr(mapping, "llm_mapping", llm)
    monkeypatch.setattr(mapping, "typesafe_is_configured", lambda setting: False)
    monkeypatch.setattr(mapping, "llm_mapping_configured", lambda db, setting: False)

    _, report = mapping.map_fields("Text", schema({"name": "id", "type": "text"}), db)
    softnix.assert_not_called()
    jev.assert_not_called()
    llm.assert_not_called()
    assert all(a["status"] == "skipped" for a in report["attempts"])
    assert {a["provider"] for a in report["attempts"]} == {"softnix", "jev", "lx", "llm"}


def _auto_chain_setting():
    return SimpleNamespace(
        mapping_engine="auto",
        mapping_fallback_enabled=True,
        api_token="token",
        api_endpoint="http://ocr",
        structured_output_endpoint="http://structured",
        typesafe_endpoint="",
        typesafe_api_key="",
        mapping_fallback_provider_id=None,
    )


def test_grounded_value_replaces_unverified_conflicting_incumbent(monkeypatch):
    """A span-backed value upgrades a needs_review incumbent; the old value stays as alternative."""
    db = Mock()
    setting = _auto_chain_setting()
    provider = SimpleNamespace(api_url="http://llm", api_key="k")
    db.query.return_value.first.return_value = setting
    db.query.return_value.filter.return_value.first.return_value = provider
    db.query.return_value.filter.return_value.filter.return_value.first.return_value = provider

    # softnix answers first with a normalized value that is not verbatim in the text.
    monkeypatch.setattr(mapping, "extract_structure",
                        lambda *a, **k: {"total": "2,500.00"})
    monkeypatch.setattr(mapping, "typesafe_is_configured", lambda setting: False)

    def fake_lx_mapping(text, target, db, timeout, model=None):
        return {"total": {"raw": "25", "text_start": 11, "text_end": 13}}, "lx:test-model", {}

    monkeypatch.setattr(mapping, "lx_mapping", fake_lx_mapping)
    monkeypatch.setattr(mapping, "llm_mapping", Mock(side_effect=AssertionError("llm should not run")))

    text = "Invoice No: INV-42\nTotal: 25"
    values, report = mapping.map_fields(text, schema({"name": "total", "type": "currency"}), db)
    assert values == {"total": 25}
    field = report["fields"]["total"]
    assert field["status"] == "source_matched"
    assert field["provider"] == "lx:test-model"
    assert field["upgraded_from_conflict"] is True
    assert field["alternative"] == {"value": 2500.0, "provider": "softnix"}
    # The honest association caveat from the grounded proof is retained.
    assert "not independently verified" in field["reason"]


def test_conflict_against_verified_value_keeps_incumbent_and_flags_grounded_alternative(monkeypatch):
    """A verified (source_matched) field leaves the pending queue, so later engines
    never re-extract it and it cannot be pulled into a conflict."""
    db = Mock()
    setting = _auto_chain_setting()
    provider = SimpleNamespace(api_url="http://llm", api_key="k")
    db.query.return_value.first.return_value = setting
    db.query.return_value.filter.return_value.first.return_value = provider
    db.query.return_value.filter.return_value.filter.return_value.first.return_value = provider

    monkeypatch.setattr(mapping, "extract_structure", lambda *a, **k: {"total": 25})
    monkeypatch.setattr(mapping, "typesafe_is_configured", lambda setting: False)

    def fake_lx_mapping(text, target, db, timeout, model=None):
        raise AssertionError("lx should not run: no fields pending after softnix verified")

    monkeypatch.setattr(mapping, "lx_mapping", fake_lx_mapping)
    monkeypatch.setattr(mapping, "llm_mapping", Mock(side_effect=AssertionError("llm should not run")))

    values, report = mapping.map_fields("Invoice No: INV-42\nTotal: 25",
                                        schema({"name": "total", "type": "currency"}), db)
    assert values == {"total": 25}
    field = report["fields"]["total"]
    assert field["status"] == "source_matched"
    assert field["provider"] == "softnix"
    assert "alternative" not in field


def test_jev_engine_maps_candidates_and_marks_low_confidence_for_review(monkeypatch):
    """Jev selects verbatim candidates; low-confidence picks stay needs_review."""
    db = Mock()
    db.query.return_value.first.return_value = SimpleNamespace(
        mapping_engine="auto", mapping_fallback_enabled=False,
        typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="k")
    text = "Invoice No: INV-42\nTotal: 25"

    def fake_system_one(config, state, questions, timeout):
        assert state["document_text"] == text
        answers = {}
        for key, question in questions.items():
            name = question["instructions"]["field_name"]
            if name == "id":
                answers[key] = {"type": "choice", "choice": "INV-42", "confidence": 0.9}
            else:
                answers[key] = {"type": "choice", "choice": "25", "confidence": 0.4}
        return {"model": "jev-test", "answers": answers}

    monkeypatch.setattr(mapping, "typesafe_system_one", fake_system_one)
    values, report = mapping.map_fields(text, schema(
        {"name": "id", "type": "text"}, {"name": "total", "type": "currency"}), db, engine="jev")
    assert values == {"id": "INV-42"}
    assert report["fields"]["id"]["provider"].startswith("jev")
    assert report["fields"]["total"]["jev_candidate"]["value"] == "25"
    assert report["fields"]["total"]["status"] == "needs_review"



def test_jev_date_format_uses_date_candidates_not_ngrams(monkeypatch):
    """build_schema_json emits format=date; candidates must not fall through to n-grams."""
    db = Mock()
    db.query.return_value.first.return_value = SimpleNamespace(
        mapping_engine="jev", mapping_fallback_enabled=False,
        typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="k")
    text = (
        "บริษัท ดีทวัน จำกัด (สำนักงานใหญ่)\n"
        "เลขที่ 96/122 ซอยสุวินทวงศ์ 38 แขวงลำผัก เขตหนองจอก กรุงเทพมหานคร 10530\n"
        "วันที่ ... 24 Aug 2026\n"
    )
    captured = {}

    def fake_system_one(config, state, questions, timeout=30.0, model="jev-latest"):
        captured["questions"] = questions
        answers = {}
        for key, question in questions.items():
            name = question["instructions"]["field_name"]
            cands = question["instructions"]["candidates"]
            if name == "invoice_date":
                assert "24 Aug 2026" in cands, cands[:20]
                # Date path must NOT flood with leading Thai n-grams as sole options
                assert cands[0] == "24 Aug 2026" or "24 Aug 2026" in cands[:5]
                answers[key] = {"type": "choice", "choice": "24 Aug 2026", "confidence": 0.95}
            elif name == "seller_address":
                assert any("96/122" in c and "หนองจอก" in c for c in cands), cands[:15]
                addr = next(c for c in cands if "96/122" in c and "หนองจอก" in c)
                answers[key] = {"type": "choice", "choice": addr, "confidence": 0.92}
            elif name == "seller_name":
                assert any("ดีทวัน" in c for c in cands)
                full = next((c for c in cands if "บริษัท ดีทวัน จำกัด" in c), None)
                assert full is not None, cands[:10]
                answers[key] = {"type": "choice", "choice": full, "confidence": 0.93}
            else:
                answers[key] = {"type": "choice", "choice": "__none__", "confidence": 0.9}
        return {"model": "jev-test", "answers": answers}

    monkeypatch.setattr(mapping, "typesafe_system_one", fake_system_one)
    values, report = mapping.map_fields(
        text,
        schema(
            {"name": "invoice_date", "type": "date"},
            {"name": "seller_address", "type": "text"},
            {"name": "seller_name", "type": "text"},
        ),
        db,
        engine="jev",
    )
    assert values["invoice_date"] == "2026-08-24"
    assert report["fields"]["invoice_date"]["status"] == "source_matched"
    assert report["fields"]["invoice_date"]["quote"] == "24 Aug 2026"
    assert "ดีทวัน" in values["seller_name"]
    assert "96/122" in values["seller_address"]
    assert report["fields"]["seller_address"]["status"] == "source_matched"
    assert report["fields"]["seller_name"]["status"] == "source_matched"


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


def _jev_db():
    db = Mock()
    db.query.return_value.first.return_value = SimpleNamespace(
        mapping_engine="jev", mapping_fallback_enabled=False,
        typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="k")
    return db


def test_jev_boolean_choice_is_accepted_as_bool(monkeypatch):
    def fake_system_one(config, state, questions, timeout=30.0, model="jev-latest"):
        return {"model": "jev-test", "answers": {
            key: {"type": "choice", "choice": "true", "confidence": 0.95} for key in questions}}

    monkeypatch.setattr(mapping, "typesafe_system_one", fake_system_one)
    values, report = mapping.map_fields("VAT included: yes", schema({"name": "vat_included", "type": "boolean"}),
                                        _jev_db(), engine="jev")
    assert values == {"vat_included": True}
    assert report["unresolved_fields"] == []


def test_jev_skips_table_fields_instead_of_failing_them(monkeypatch):
    asked = []

    def fake_system_one(config, state, questions, timeout=30.0, model="jev-latest"):
        asked.extend(q["instructions"]["field_name"] for q in questions.values())
        return {"model": "jev-test", "answers": {
            key: {"type": "choice", "choice": "INV-1", "confidence": 0.95} for key in questions}}

    monkeypatch.setattr(mapping, "typesafe_system_one", fake_system_one)
    values, report = mapping.map_fields("Invoice No: INV-1", schema(
        {"name": "id", "type": "text"},
        {"name": "items", "type": "array"}), _jev_db(), engine="jev")
    assert asked == ["id"]
    assert values == {"id": "INV-1"}
    assert "items" in report["unresolved_fields"]


def test_jev_candidate_budget_keeps_labelled_total_at_document_end(monkeypatch):
    body = "\n".join(f"Line {i}: {1000 + i}" for i in range(200))
    text = body + "\nGrand Total: 98,765.43"
    seen = {}

    def fake_system_one(config, state, questions, timeout=30.0, model="jev-latest"):
        (key, question), = questions.items()
        seen["candidates"] = question["instructions"]["candidates"]
        return {"model": "jev-test", "answers": {key: {"type": "choice", "choice": "98,765.43", "confidence": 0.9}}}

    monkeypatch.setattr(mapping, "typesafe_system_one", fake_system_one)
    values, _ = mapping.map_fields(text, schema({"name": "grand_total", "type": "currency"}), _jev_db(), engine="jev")
    assert "98,765.43" in seen["candidates"]
    assert len(seen["candidates"]) <= mapping.JEV_SCALAR_CANDIDATE_CAP
    assert values == {"grand_total": 98765.43}


def test_jev_none_on_truncated_candidates_needs_review_not_missing(monkeypatch):
    text = "\n".join(str(10_000 + i) for i in range(300))

    def fake_system_one(config, state, questions, timeout=30.0, model="jev-latest"):
        return {"model": "jev-test", "answers": {
            key: {"type": "choice", "choice": "__none__", "confidence": 0.8} for key in questions}}

    monkeypatch.setattr(mapping, "typesafe_system_one", fake_system_one)
    values, report = mapping.map_fields(text, schema({"name": "tip", "type": "number"}), _jev_db(), engine="jev")
    assert values == {}
    assert report["fields"]["tip"]["status"] == "needs_review"
    assert "truncated" in report["fields"]["tip"]["reason"]
    assert report["unresolved_fields"] == ["tip"]


def test_jev_candidate_extraction_stays_fast_on_large_documents(monkeypatch):
    """~20k words, short keywords matching every line, many text fields: candidate work must stay bounded."""
    import time
    # Every word unique -> ~88k distinct n-gram candidates; "no"/"id" appear on every line.
    text = "\n".join(
        f"no id ref{i} c{i}a c{i}b c{i}c c{i}d c{i}e {10000 + i} n{i}x n{i}y n{i}z v{i}" for i in range(1700))

    def fake_system_one(config, state, questions, timeout=30.0, model="jev-latest"):
        for question in questions.values():
            assert len(question["instructions"]["candidates"]) <= mapping.JEV_TEXT_CANDIDATE_CAP
        return {"model": "jev-test", "answers": {}}

    monkeypatch.setattr(mapping, "typesafe_system_one", fake_system_one)
    fields = [{"name": name, "type": "text"} for name in ("no", "id", "ref_no", "customer_name", "address", "detail")]
    started = time.monotonic()
    mapping.map_fields(text, schema(*fields, {"name": "amount", "type": "number"}), _jev_db(), engine="jev")
    # Previous per-candidate x per-line matching took ~0.6s per text field here (~3.6s total).
    assert time.monotonic() - started < 1.5


def test_keyless_local_llm_counts_as_configured():
    from types import SimpleNamespace
    from app.services import field_mapping as mapping

    provider = SimpleNamespace(api_key=None, api_url="http://ollama:11434/v1")

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return provider

    db = SimpleNamespace(query=lambda model: Query())
    setting = SimpleNamespace(mapping_fallback_provider_id=None)
    assert mapping.llm_mapping_configured(db, setting) is True
    provider.api_url = ""
    assert mapping.llm_mapping_configured(db, setting) is False


def test_lx_engine_records_grounded_span_evidence(monkeypatch):
    """Grounded extractions carry char spans into evidence, not forced review."""
    db = Mock()
    db.query.return_value.first.return_value = SimpleNamespace(
        mapping_engine="lx", mapping_fallback_enabled=False)

    def fake_lx_mapping(text, target, db, timeout, model=None):
        grounded = {
            "id": {"raw": "INV-42", "text_start": 11, "text_end": 17},
        }
        return grounded, "lx:test-model", {}

    monkeypatch.setattr(mapping, "lx_mapping", fake_lx_mapping)
    text = "Invoice No: INV-42\nTotal: 25"
    values, report = mapping.map_fields(text, schema(
        {"name": "id", "type": "text"}, {"name": "total", "type": "currency"}), db, engine="lx")
    assert values == {"id": "INV-42"}
    field = report["fields"]["id"]
    assert field["provider"] == "lx:test-model"
    assert field["status"] == "source_matched"
    assert field["quote"] == "INV-42"
    assert field["text_start"] == 11 and field["text_end"] == 17
    # No extraction for an absent field is "missing", not a provider failure.
    assert report["fields"]["total"]["status"] == "missing"
    assert report["attempts"] == [{"provider": "lx:test-model", "status": "completed"}]


def test_lx_engine_marks_ungrounded_candidate_for_review(monkeypatch):
    """Ungrounded extractions never enter values; they surface as lx_candidate."""
    db = Mock()
    db.query.return_value.first.return_value = SimpleNamespace(
        mapping_engine="lx", mapping_fallback_enabled=False)

    def fake_lx_mapping(text, target, db, timeout, model=None):
        return {}, "lx:test-model", {
            "total": {"value": "2,500.00", "confidence": None,
                      "reason": "Ungrounded extraction; value not located verbatim in source"},
        }

    monkeypatch.setattr(mapping, "lx_mapping", fake_lx_mapping)
    values, report = mapping.map_fields("Invoice No: INV-42", schema(
        {"name": "id", "type": "text"}, {"name": "total", "type": "currency"}), db, engine="lx")
    assert values == {}
    total = report["fields"]["total"]
    assert total["status"] == "needs_review"
    assert total["lx_candidate"] == {"value": "2,500.00"}
    assert "total" in report["review_fields"]


def test_lx_mapping_grounds_and_filters_via_fake_extract(monkeypatch):
    """lx_mapping keeps grounded spans, filters ungrounded values to candidates."""
    pytest.importorskip("langextract")
    import langextract as lx
    from langextract.core.data import AnnotatedDocument, Extraction, CharInterval

    captured = {}

    def fake_extract(**kwargs):
        captured.update(kwargs)
        return AnnotatedDocument(document_id="doc_0", text=kwargs["text_or_documents"], extractions=[
            Extraction(extraction_class="id", extraction_text="INV-42",
                       char_interval=CharInterval(start_pos=11, end_pos=17)),
            Extraction(extraction_class="total", extraction_text="ninety-nine",
                       char_interval=None),
        ])

    monkeypatch.setattr(lx, "extract", fake_extract)
    text = "Invoice No: INV-42\nTotal: 25"
    target = {"type": "object", "properties": {
        "id": {"type": "string"}, "total": {"type": "number"}}}
    grounded, tag, candidates = mapping.lx_mapping(text, target, None, timeout=10, model=object())
    assert tag == "lx:langextract"
    assert grounded == {"id": {"raw": "INV-42", "text_start": 11, "text_end": 17}}
    assert candidates["total"]["value"] == "ninety-nine"
    # Prompt lists every field as its own extraction class and demands verbatim text.
    assert "- id (string):" in captured["prompt_description"]
    assert "- total (number):" in captured["prompt_description"]
    assert "verbatim" in captured["prompt_description"]
    assert captured["output_schema"]["properties"], "extractions envelope schema built"


def test_annotate_span_evidence_resolves_page_and_raw_text():
    """Char spans map to the owning page and gain the surrounding line."""
    ocr_text = "Page one header\nVendor: ACME Ltd\n\nPage two starts here\nTotal: 42 baht"
    ocr_pages = [
        {"page_number": 1, "ocr_text": "Page one header\nVendor: ACME Ltd"},
        {"page_number": 2, "ocr_text": "Page two starts here\nTotal: 42 baht"},
    ]
    start = ocr_text.index("ACME Ltd")
    end = start + len("ACME Ltd")
    report = {"fields": {
        "vendor": {"status": "source_matched", "quote": "ACME Ltd", "text_start": start, "text_end": end},
    }}
    mapping.annotate_span_evidence(report, ocr_text, ocr_pages)
    item = report["fields"]["vendor"]
    assert item["page"] == 1
    assert item["raw_text"] == "Vendor: ACME Ltd"


def test_annotate_span_evidence_span_wins_over_quote_page_guess():
    """A span-derived page replaces the unique-quote heuristic page."""
    ocr_text = "First page\nRef: A-1\n\nSecond page\nRef: A-1 again"
    ocr_pages = [
        {"page_number": 1, "ocr_text": "First page\nRef: A-1"},
        {"page_number": 2, "ocr_text": "Second page\nRef: A-1 again"},
    ]
    start = ocr_text.rindex("A-1")
    report = {"fields": {"ref": {"page": 1, "quote": "A-1", "text_start": start, "text_end": start + 3}}}
    mapping.annotate_span_evidence(report, ocr_text, ocr_pages)
    assert report["fields"]["ref"]["page"] == 2


def test_annotate_span_evidence_no_pages_is_noop():
    report = {"fields": {"x": {"text_start": 0, "text_end": 1}}}
    mapping.annotate_span_evidence(report, "text", None)
    assert report["fields"]["x"] == {"text_start": 0, "text_end": 1}
