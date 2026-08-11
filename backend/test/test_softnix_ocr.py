from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import ocr


class FakeQuery:
    def __init__(self, setting):
        self.setting = setting

    def first(self):
        return self.setting


class FakeDb:
    def __init__(self, setting):
        self.setting = setting

    def query(self, _model):
        return FakeQuery(self.setting)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


@pytest.fixture
def setting():
    return SimpleNamespace(
        ocr_endpoint="https://ocr.example.test/v3/ai-process-file",
        api_endpoint=None,
        api_token="test-token",
        verify_ssl=False,
        ocr_engine="default",
        model="default",
    )


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "receipt.png"
    path.write_bytes(b"fake image")
    return str(path)


def test_process_ocr_waits_for_async_result(monkeypatch, setting, document):
    get_urls = []
    monkeypatch.setattr(
        ocr.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse({
            "status": "success",
            "job_id": "job-1",
            "get_result": "/v3/ai-process-file/job-1/result",
        }),
    )

    def get(url, **_kwargs):
        get_urls.append(url)
        return FakeResponse({"status": "success", "results": {"pages": [{"ocr_text": "receipt text"}]}})

    monkeypatch.setattr(ocr.requests, "get", get)

    result = ocr.process_ocr(document, FakeDb(setting), filename="receipt.png", timeout=10)

    assert result["results"]["pages"][0]["ocr_text"] == "receipt text"
    assert get_urls == ["https://ocr.example.test/v3/ai-process-file/job-1/result"]


def test_process_ocr_raises_timeout_when_async_job_never_completes(monkeypatch, setting, document):
    monkeypatch.setattr(
        ocr.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse({
            "status": "success",
            "job_id": "job-2",
            "get_result": "/v3/ai-process-file/job-2/result",
        }),
    )

    with pytest.raises(TimeoutError, match="did not complete"):
        ocr.process_ocr(document, FakeDb(setting), filename="receipt.png", timeout=0)


def test_process_ocr_returns_immediate_provider_result_without_polling(monkeypatch, setting, document):
    monkeypatch.setattr(
        ocr.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse({"status": "success", "results": {"pages": [{"ocr_text": "ready"}]}}),
    )
    monkeypatch.setattr(
        ocr.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not poll")),
    )

    result = ocr.process_ocr(document, FakeDb(setting), filename="receipt.png", timeout=10)

    assert result["results"]["pages"][0]["ocr_text"] == "ready"
