from types import SimpleNamespace

from app.tasks.document_tasks import should_attempt_ocr_fallback


def _document(status: str):
    return SimpleNamespace(status=status)


def _setting(enabled: bool = True):
    return SimpleNamespace(ocr_fallback_enabled=enabled)


def test_fallback_runs_only_while_softnix_ocr_is_eligible():
    assert should_attempt_ocr_fallback(
        fallback_eligible=True,
        document=_document("processing"),
        setting=_setting(),
        api_key="configured-key",
    )


def test_fallback_does_not_run_after_document_completion_or_unrelated_error():
    assert not should_attempt_ocr_fallback(
        fallback_eligible=False,
        document=_document("processing"),
        setting=_setting(),
        api_key="configured-key",
    )
    assert not should_attempt_ocr_fallback(
        fallback_eligible=True,
        document=_document("extraction_completed"),
        setting=_setting(),
        api_key="configured-key",
    )
