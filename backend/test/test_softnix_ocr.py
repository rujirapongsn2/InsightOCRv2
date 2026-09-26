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


def test_v3_submit_disables_structure_and_follows_status_before_result(monkeypatch, setting, document):
    calls = []

    def post(url, **kwargs):
        assert kwargs["data"]["disable_structure"] == "true"
        assert kwargs["data"]["pages"] == "1"
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"
        return FakeResponse({
            "status": "success", "job_id": "v3-job",
            "check_status": "/v3/ai-process-file/v3-job/status",
            "get_result": "/v3/ai-process-file/v3-job/result",
            "results": {"pages": []},
        })

    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        if url.endswith("/status"):
            return FakeResponse({"status": "completed"})
        return FakeResponse({"status": "success", "results": {"combined_markdown": "# Verified"}})

    monkeypatch.setattr(ocr.requests, "post", post)
    monkeypatch.setattr(ocr.requests, "get", get)
    result = ocr.process_ocr(document, FakeDb(setting), timeout=10)
    assert result["results"]["combined_markdown"] == "# Verified"
    assert [url.rsplit("/", 1)[-1] for url in calls] == ["status", "result"]


def test_failed_response_with_text_is_not_success(monkeypatch, setting, document):
    monkeypatch.setattr(ocr.requests, "post", lambda *a, **kw: FakeResponse({
        "status": "failed", "ocr_text": "partial text",
    }))
    with pytest.raises(RuntimeError, match="submission failed"):
        ocr.process_ocr(document, FakeDb(setting))


@pytest.mark.parametrize("path", ["https://other.test/result", "//other.test/result"])
def test_result_reference_cannot_receive_token_on_other_origin(path):
    with pytest.raises(ValueError, match="provider origin"):
        ocr._result_url("https://ocr.example.test/v3/ai-process-file", path)


def test_submit_time_is_deducted_from_polling_budget(monkeypatch, setting, document):
    now = [100.0]
    monkeypatch.setattr(ocr.time, "monotonic", lambda: now[0])

    def post(*args, **kwargs):
        now[0] += 8
        return FakeResponse({"job_id": "slow"})

    def wait(payload, **kwargs):
        assert kwargs["timeout"] == 2
        return {"ocr_text": "ready"}

    monkeypatch.setattr(ocr.requests, "post", post)
    monkeypatch.setattr(ocr, "_wait_for_ocr_result", wait)
    ocr.process_ocr(document, FakeDb(setting), timeout=10)


def test_v3_retries_transient_result_get_without_resubmitting(monkeypatch, setting, document):
    submissions = []
    responses = iter([FakeResponse({}, 503), FakeResponse({"ocr_text": "ready"})])

    def post(*args, **kwargs):
        submissions.append(1)
        return FakeResponse({"job_id": "job"})

    monkeypatch.setattr(ocr.requests, "post", post)
    monkeypatch.setattr(ocr.requests, "get", lambda *a, **kw: next(responses))
    monkeypatch.setattr(ocr.time, "sleep", lambda seconds: None)
    assert ocr.process_ocr(document, FakeDb(setting))["ocr_text"] == "ready"
    assert len(submissions) == 1


def test_legacy_route_polls_status_reports_progress_and_times_out_in_queue(monkeypatch):
    """The legacy whole-file route shares the AnyDoc waiter: status polling, progress and queue timeout."""
    from app.services import ocr as ocr_module

    monkeypatch.setattr(ocr_module.settings, "OCR_STATUS_POLL_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(ocr_module.time, "sleep", lambda _seconds: None)
    responses = iter([
        {"status": "processing", "progress": {"percent": 40, "stage": "ocr"}},
        {"status": "started"},  # unknown to us: keep waiting, as the legacy route always did
        {"status": "completed"},
        {"status": "completed", "results": {"pages": [{"page_number": 1, "ocr_text": "done"}]}},
    ])
    urls, progress, statuses = [], [], []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, **_kwargs):
        urls.append(url)
        return Response(next(responses))

    monkeypatch.setattr(ocr_module.requests, "get", fake_get)
    result = ocr_module._wait_for_ocr_result(
        {"data": {"job_id": "j1", "status": "queued"}}, ocr_api_url="https://ocr.example.test/v1/ocr",
        headers={}, verify_ssl=True, timeout=60, on_progress=progress.append, on_status=statuses.append,
        poll_status=True)
    assert result["results"]["pages"][0]["ocr_text"] == "done"
    assert urls == ["https://ocr.example.test/v1/ocr/j1/status"] * 3 + ["https://ocr.example.test/v1/ocr/j1/result"]
    assert progress == [{"percent": 40, "stage": "ocr"}]
    assert statuses == ["processing", "started", "completed", "completed"]

    clock = {"now": 0.0}
    monkeypatch.setattr(ocr_module.time, "monotonic", lambda: clock.__setitem__("now", clock["now"] + 5) or clock["now"])
    monkeypatch.setattr(ocr_module.requests, "get", lambda url, **_k: Response({"status": "queued"}))
    with pytest.raises(TimeoutError, match="stayed queued"):
        ocr_module._wait_for_ocr_result({"job_id": "j2", "status": "queued"}, ocr_api_url="https://ocr.example.test/v1/ocr",
                                        headers={}, verify_ssl=True, timeout=600, queue_timeout=20, poll_status=True)
