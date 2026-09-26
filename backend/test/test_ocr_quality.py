"""OCR quality: Tesseract confidence verdicts, Jev on borderline pages, routing, Thai normalization."""
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import anydoc_pipeline, ocr_quality
from app.services.anydoc_pipeline import extract_anydoc_document


def words(conf, count=20, text="word"):
    return [{"text": text, "x": 1, "y": 1, "width": 1, "height": 1, "conf": conf} for _ in range(count)]


@pytest.mark.parametrize("conf,count,thai,verdict,reason", [
    (90, 20, False, "good", "confident"),
    (40, 20, False, "poor", "low_confidence"),
    (65, 20, False, "uncertain", "borderline_confidence"),
    (90, 20, True, "poor", "thai_font_mapping"),
    (20, 3, False, "good", "too_few_words"),
])
def test_layer0_verdicts(conf, count, thai, verdict, reason):
    result = ocr_quality.assess_tesseract_page(words(conf, count), thai)
    assert (result["verdict"], result["reason"]) == (verdict, reason)


def test_confidence_is_weighted_by_characters_and_ignores_non_words():
    stats = ocr_quality.tesseract_confidence(
        [{"text": "abcdefghij", "conf": 90}, {"text": "x", "conf": 10}, {"text": "", "conf": -1}])
    assert stats["mean_confidence"] == round((90 * 10 + 10) / 11, 1)
    assert stats["low_confidence_share"] == round(1 / 11, 3) and stats["word_count"] == 2


def test_normalize_thai_fixes_only_unambiguous_artefacts():
    text, changes = ocr_quality.normalize_thai("บร ิษัท ดีทวิน จํากัด ข ้อมูล เพิMม")
    assert text == "บริษัท ดีทวิน จำกัด ข้อมูล เพิMม"  # tone marks replaced by Latin letters are not guessed
    assert changes == 3
    assert ocr_quality.normalize_thai("Invoice 1,250.00  total") == ("Invoice 1,250.00  total", 0)


class FakeDb:
    def __init__(self, setting):
        self.setting = setting

    def query(self, _model):
        return SimpleNamespace(first=lambda: self.setting)


def _setting():
    return SimpleNamespace(ocr_fallback_enabled=False, ocr_fallback_api_key=None, verify_ssl=True,
                           ocr_endpoint="https://softnix-ocr.invalid", api_token="t")


def _image(tmp_path):
    path = tmp_path / "scan.png"
    Image.new("RGB", (24, 16), "white").save(path)
    return str(path)


def _tesseract(conf):
    def run(*_args, words_out=None, **_kwargs):
        words_out.extend(words(conf))
        return "Tesseract text with some words"
    return run


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setattr(anydoc_pipeline, "process_fallback_ocr",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fallback must be stubbed")))


def test_report_only_keeps_poor_tesseract_text(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline.settings, "OCR_QUALITY_ROUTING", False)
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", _tesseract(30))
    monkeypatch.setattr(anydoc_pipeline, "process_ocr", lambda *a, **k: pytest.fail("no escalation in report-only"))

    result = extract_anydoc_document(_image(tmp_path), FakeDb(_setting()), None)

    page = result.pages[0]
    assert page["provider"] == "tesseract_ocr" and page["quality"]["action"] == "would_escalate"
    assert result.metadata["ocr_low_quality_pages"] == [1] and result.metadata["ocr_escalated_pages"] == []


def test_routing_replaces_poor_tesseract_with_softnix(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline.settings, "OCR_QUALITY_ROUTING", True)
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", _tesseract(30))
    monkeypatch.setattr(anydoc_pipeline, "process_ocr",
                        lambda *a, **k: {"results": {"pages": [{"ocr_text": "Softnix clean text"}]}})

    result = extract_anydoc_document(_image(tmp_path), FakeDb(_setting()), None)

    page = result.pages[0]
    assert page["provider"] == "softnix_ocr" and result.markdown == "Softnix clean text"
    assert page["replaced"] == {"provider": "tesseract_ocr", "mean_confidence": 30.0, "reason": "low_confidence"}
    assert result.metadata["ocr_escalated_pages"] == [1]


def test_poor_text_is_kept_when_the_better_ocr_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline.settings, "OCR_QUALITY_ROUTING", True)
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", _tesseract(30))
    monkeypatch.setattr(anydoc_pipeline, "process_ocr", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

    result = extract_anydoc_document(_image(tmp_path), FakeDb(_setting()), None)

    assert result.pages[0]["provider"] == "tesseract_ocr"
    assert result.pages[0]["quality"]["action"] == "kept_no_better_ocr"


@pytest.mark.parametrize("jev_enabled,noul,provider", [(True, 0.2, "softnix_ocr"), (True, 0.9, "tesseract_ocr"),
                                                      (False, None, "tesseract_ocr")])
def test_borderline_pages_ask_jev_only_when_enabled(monkeypatch, tmp_path, jev_enabled, noul, provider):
    import app.services.typesafe as typesafe

    monkeypatch.setattr(anydoc_pipeline.settings, "OCR_QUALITY_ROUTING", True)
    monkeypatch.setattr(ocr_quality.settings, "OCR_QUALITY_JEV", jev_enabled)
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", _tesseract(65))
    monkeypatch.setattr(anydoc_pipeline, "process_ocr",
                        lambda *a, **k: {"results": {"pages": [{"ocr_text": "Softnix clean text"}]}})
    monkeypatch.setattr(typesafe, "typesafe_is_configured", lambda setting: True)
    monkeypatch.setattr(typesafe, "resolve_typesafe_config", lambda setting: object())
    asked = []
    monkeypatch.setattr(typesafe, "typesafe_noul",
                        lambda config, state, question, timeout: asked.append(state) or {"noul": noul, "model": "jev"})

    result = extract_anydoc_document(_image(tmp_path), FakeDb(_setting()), None)

    assert result.pages[0]["provider"] == provider
    assert len(asked) == (1 if jev_enabled else 0)


def test_a_few_bad_lines_make_a_high_mean_page_poor():
    good = [{"text": "clear", "conf": 95, "line": f"1.1.{i}"} for i in range(40)]
    bad = [{"text": "6นร1", "conf": 34, "line": f"2.1.{i}"} for i in range(3)] + \
          [{"text": "ok", "conf": 95, "line": f"2.1.{i}"} for i in range(3)]
    result = ocr_quality.assess_tesseract_page(good + bad, False)
    assert result["mean_confidence"] > 85
    assert (result["low_confidence_lines"], result["verdict"], result["reason"]) == (3, "poor", "low_confidence_lines")


def test_thai_id_checksum():
    assert ocr_quality.thai_id_checksum_ok("0105558076541")
    assert not ocr_quality.thai_id_checksum_ok("0105558076542")


def _pages():
    return [{"page_number": 1, "words": [
        {"text": "Tax", "conf": 96}, {"text": "ID:", "conf": 96},
        {"text": "0105558076541", "conf": 93},
        {"text": "Total", "conf": 95}, {"text": "1,250.00", "conf": 41},
        {"text": "ลูกค้า", "conf": 90}, {"text": "บริษัท", "conf": 92}, {"text": "ดี", "conf": 38}, {"text": "ทวิน", "conf": 91},
    ]}]


def test_values_read_from_uncertain_words_go_to_review():
    fields = [{"name": "tax_id", "type": "text"}, {"name": "total", "type": "number"},
              {"name": "customer", "type": "text"}, {"name": "note", "type": "text"}]
    values = {"tax_id": "0105558076541", "total": 1250.0, "customer": "บริษัท ดีทวิน", "note": "not on page"}
    report = {"fields": {"tax_id": {"status": "source_matched"}}, "review_fields": []}

    ocr_quality.review_uncertain_values(values, report, _pages(), fields)

    assert report["fields"]["tax_id"]["status"] == "source_matched"  # confident and checksum valid
    assert report["fields"]["tax_id"]["ocr_confidence"]["min_confidence"] == 93
    assert report["fields"]["total"]["check"] == "ocr_confidence"  # "1,250.00" was read at 41
    assert report["fields"]["customer"]["ocr_confidence"]["min_confidence"] == 38  # words split, Thai joined
    assert "note" not in report["fields"]  # not found in OCR words: nothing to judge
    assert report["review_fields"] == ["total", "customer"]


def test_misread_thai_tax_id_is_flagged_by_checksum():
    report = {"fields": {}, "review_fields": []}
    ocr_quality.review_uncertain_values({"seller_tax_id": "0105558076542"}, report, [],
                                        [{"name": "seller_tax_id", "type": "text"}])
    assert report["fields"]["seller_tax_id"]["check"] == "thai_id_checksum"
    assert report["review_fields"] == ["seller_tax_id"]


def test_saved_admin_setting_overrides_the_environment(monkeypatch):
    monkeypatch.setattr(ocr_quality.settings, "OCR_QUALITY_ROUTING", False)
    assert ocr_quality.routing_enabled(SimpleNamespace(ocr_quality_routing=None)) is False  # not saved yet
    assert ocr_quality.routing_enabled(SimpleNamespace(ocr_quality_routing=True)) is True
    monkeypatch.setattr(ocr_quality.settings, "OCR_QUALITY_JEV", True)
    assert ocr_quality.jev_enabled(SimpleNamespace(ocr_quality_jev=False)) is False


def test_routing_follows_the_saved_setting(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline.settings, "OCR_QUALITY_ROUTING", False)
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", _tesseract(30))
    monkeypatch.setattr(anydoc_pipeline, "process_ocr",
                        lambda *a, **k: {"results": {"pages": [{"ocr_text": "Softnix clean text"}]}})
    setting = _setting()
    setting.ocr_quality_routing = True

    result = extract_anydoc_document(_image(tmp_path), FakeDb(setting), None)

    assert result.pages[0]["provider"] == "softnix_ocr"


@pytest.mark.parametrize("metadata,blocked", [
    ({"mapping": {"review_fields": ["total"], "unresolved_fields": []}}, True),
    ({"mapping": {"review_fields": [], "unresolved_fields": ["tax_id"]}}, True),
    ({"mapping": {"review_fields": [], "unresolved_fields": []}, "ocr_low_quality_pages": [2]}, True),
    ({"mapping": {"review_fields": [], "unresolved_fields": []}, "ocr_low_quality_pages": []}, False),
    ({"mapping": "not_requested"}, False),
])
def test_auto_confirm_waits_for_a_person_when_the_pipeline_flagged_something(metadata, blocked):
    assert bool(ocr_quality.auto_review_blockers(SimpleNamespace(extraction_metadata=metadata))) is blocked


def test_finalize_keeps_flagged_documents_for_review(monkeypatch):
    from app.tasks import document_tasks

    monkeypatch.setattr(document_tasks, "log_activity", lambda **kwargs: None)
    document = SimpleNamespace(id="d1", filename="a.pdf", status="processing", review_decision=None, reviewed_at=None,
                               reviewed_data=None, extracted_data={"total": 1}, processed_at=None, job=None,
                               extraction_metadata={"mapping": {"review_fields": ["total"]}})
    db = SimpleNamespace(add=lambda obj: None, commit=lambda: None)
    logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)

    document_tasks._finalize_document_success(document, db, None, "auto", "anydoc_hybrid", logger, auto_review=True)

    assert document.status == "extraction_completed" and document.reviewed_data is None
    assert document.extraction_metadata["auto_review_skipped"] == ["fields need review: total"]


def test_a_failing_quality_check_keeps_the_tesseract_text(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", _tesseract(90))
    monkeypatch.setattr(anydoc_pipeline, "_judge_tesseract_page",
                        lambda *a, **k: (_ for _ in ()).throw(ImportError("broken")))
    monkeypatch.setattr(anydoc_pipeline, "process_ocr", lambda *a, **k: pytest.fail("must not re-OCR"))

    result = extract_anydoc_document(_image(tmp_path), FakeDb(_setting()), None)

    assert result.pages[0]["provider"] == "tesseract_ocr"
    assert result.pages[0]["quality"] == {"decision": "unknown", "error": "ImportError"}


def test_jev_is_skipped_when_the_document_has_no_time_left(monkeypatch):
    import app.services.typesafe as typesafe

    monkeypatch.setattr(ocr_quality.settings, "OCR_QUALITY_JEV", True)
    monkeypatch.setattr(typesafe, "typesafe_is_configured", lambda setting: True)
    monkeypatch.setattr(typesafe, "typesafe_noul", lambda *a, **k: pytest.fail("must not call Jev"))
    assert ocr_quality.jev_readable("text", SimpleNamespace(ocr_quality_jev=None), 0.5) == {"error": "no_time_left"}


def test_blank_words_do_not_count_towards_the_minimum():
    blank = [{"text": " ", "conf": 95} for _ in range(20)]
    assert ocr_quality.tesseract_confidence(blank + [{"text": "real", "conf": 30}])["word_count"] == 1


def test_normalized_values_are_still_found_in_ocr_words():
    pages = [{"page_number": 1, "words": [{"text": "บริษัท", "conf": 95}, {"text": "จํากัด", "conf": 30}]}]
    confidence = ocr_quality.value_word_confidence("บริษัท จำกัด", pages)  # value holds the fixed SARA AM
    assert confidence and confidence["min_confidence"] == 30
