from types import SimpleNamespace

from app.services import ocr_configuration_test as health


def _setting(*, fallback_enabled: bool = True):
    return SimpleNamespace(
        ocr_endpoint="https://ocr.example.test/v3/ai-process-file",
        api_endpoint=None,
        api_token="softnix-token",
        ocr_engine="default",
        model="default",
        verify_ssl=True,
        ocr_fallback_enabled=fallback_enabled,
        ocr_fallback_api_key="fallback-token",
    )


def _ocr_payload(text: str):
    return {"results": {"pages": [{"ocr_text": text}]}}


def test_configuration_check_exercises_both_file_processors(monkeypatch):
    calls = []

    def primary(path, db, **kwargs):
        calls.append(("primary", path, kwargs["filename"], kwargs["setting_override"].ocr_endpoint))
        return _ocr_payload(health.OCR_TEST_MARKER)

    def fallback(path, **kwargs):
        calls.append(("fallback", path, kwargs["filename"], kwargs["api_key"]))
        return _ocr_payload(f"# Result\n{health.OCR_TEST_MARKER}")

    monkeypatch.setattr(health, "process_ocr", primary)
    monkeypatch.setattr(health, "process_fallback_ocr", fallback)

    result = health.run_ocr_configuration_test(_setting())

    assert result["overall_status"] == "passed"
    assert [check["status"] for check in result["checks"]] == ["passed", "passed"]
    assert calls[0][0] == "primary"
    assert calls[0][2] == "insightdoc-ocr-test.png"
    assert calls[0][3].endswith("/v3/ai-process-file")
    assert calls[1][0] == "fallback"
    assert calls[1][3] == "fallback-token"


def test_configuration_check_rejects_empty_or_unverified_output(monkeypatch):
    monkeypatch.setattr(health, "process_ocr", lambda *_args, **_kwargs: _ocr_payload(""))
    monkeypatch.setattr(health, "process_fallback_ocr", lambda *_args, **_kwargs: _ocr_payload("some unrelated text"))

    result = health.run_ocr_configuration_test(_setting())

    assert result["overall_status"] == "failed"
    assert result["checks"][0]["message"].endswith("returned no readable text")
    assert "did not preserve" in result["checks"][1]["message"]


def test_configuration_check_keeps_provider_failures_independent(monkeypatch):
    def fail_primary(*_args, **_kwargs):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr(health, "process_ocr", fail_primary)
    monkeypatch.setattr(
        health,
        "process_fallback_ocr",
        lambda *_args, **_kwargs: _ocr_payload(health.OCR_TEST_MARKER),
    )

    result = health.run_ocr_configuration_test(_setting())

    assert [check["status"] for check in result["checks"]] == ["failed", "passed"]
    assert "timed out" in result["checks"][0]["message"]


def test_configuration_check_marks_disabled_fallback_as_partial(monkeypatch):
    monkeypatch.setattr(
        health,
        "process_ocr",
        lambda *_args, **_kwargs: _ocr_payload(health.OCR_TEST_MARKER),
    )
    monkeypatch.setattr(
        health,
        "process_fallback_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    result = health.run_ocr_configuration_test(_setting(fallback_enabled=False))

    assert result["overall_status"] == "partial"
    assert result["checks"][1]["status"] == "skipped"
    assert result["checks"][1]["message"] == "OCR fallback is disabled"
