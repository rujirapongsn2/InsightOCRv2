from unittest.mock import Mock, patch

import pytest

from app.services.ocr_fallback import process_fallback_ocr, resolve_fallback_api_key


def _response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.side_effect = (
        None if status_code < 400 else RuntimeError("request failed")
    )
    return response


def test_process_fallback_ocr_uploads_ocr_and_cleans_up(tmp_path):
    document = tmp_path / "receipt.pdf"
    document.write_bytes(b"pdf")

    upload = _response({"id": "file-123"})
    signed_url = _response({"url": "https://signed.example/receipt.pdf"})
    ocr = _response({
        "model": "mistral-ocr-latest",
        "pages": [{"index": 0, "markdown": "# Receipt\nTotal: 100"}],
    })

    with patch("app.services.ocr_fallback.requests.post", side_effect=[upload, ocr]) as post, \
         patch("app.services.ocr_fallback.requests.get", return_value=signed_url), \
         patch("app.services.ocr_fallback.requests.delete") as delete:
        result = process_fallback_ocr(
            str(document),
            api_key="test-key",
            filename="receipt.pdf",
            mime_type="application/pdf",
        )

    assert result["results"]["pages"][0]["page_number"] == 1
    assert result["results"]["pages"][0]["ocr_text"] == "# Receipt\nTotal: 100"
    assert post.call_count == 2
    assert delete.call_count == 1
    assert delete.call_args.args[0].endswith("/files/file-123")


def test_process_fallback_ocr_rejects_empty_pages_and_cleans_up(tmp_path):
    document = tmp_path / "receipt.png"
    document.write_bytes(b"image")

    with patch(
        "app.services.ocr_fallback.requests.post",
        side_effect=[_response({"id": "file-456"}), _response({"pages": []})],
    ), patch(
        "app.services.ocr_fallback.requests.get",
        return_value=_response({"url": "https://signed.example/receipt.png"}),
    ), patch("app.services.ocr_fallback.requests.delete") as delete:
        with pytest.raises(ValueError, match="no pages"):
            process_fallback_ocr(
                str(document),
                api_key="test-key",
                filename="receipt.png",
                mime_type="image/png",
            )

    assert delete.call_count == 1


def test_resolve_fallback_api_key_prefers_ui_override(monkeypatch):
    setting = Mock(ocr_fallback_api_key="ui-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "environment-key")

    assert resolve_fallback_api_key(setting) == ("ui-key", "ui")


def test_resolve_fallback_api_key_uses_environment_when_ui_is_empty(monkeypatch):
    setting = Mock(ocr_fallback_api_key=None)
    monkeypatch.setenv("MISTRAL_API_KEY", "environment-key")

    assert resolve_fallback_api_key(setting) == ("environment-key", "environment")
