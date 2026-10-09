from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.api import deps
from app.api.v1.endpoints import agent


class FakeStorage:
    def __init__(self, tmp_path, files):
        self.tmp_path = tmp_path
        self.files = files
        self.requested_keys = []

    def exists(self, key):
        self.requested_keys.append(key)
        return key in self.files

    @contextmanager
    def get_local_path(self, key):
        local_path = self.tmp_path / "download.xlsx"
        local_path.write_bytes(self.files[key])
        yield local_path


@pytest.fixture
def download_context(monkeypatch, tmp_path):
    user = SimpleNamespace(id=uuid4())
    conversation = SimpleNamespace(id=uuid4(), user_id=user.id, job_id=uuid4())
    workbook = Workbook()
    workbook.active.append(["Document", "Summary"])
    workbook.active.append(["bank.pdf", "Document summary"])
    buffer = BytesIO()
    workbook.save(buffer)
    content = buffer.getvalue()
    path = "outputs/document_summary_all.xlsx"
    scoped_key = f"jobs/{conversation.job_id}/{path}"
    storage = FakeStorage(tmp_path, {scoped_key: content})
    monkeypatch.setattr(agent.crud_conv, "get", lambda db, conv_id: conversation if conv_id == conversation.id else None)
    monkeypatch.setattr(agent, "get_storage_service", lambda: storage)
    app = FastAPI()
    app.include_router(agent.router, prefix="/api/v1/agent")
    app.dependency_overrides[deps.get_db] = lambda: object()
    app.dependency_overrides[deps.get_current_user] = lambda: user
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, conversation=conversation, storage=storage,
                              path=path, content=content, scoped_key=scoped_key)


def _download(context, path=None):
    return context.client.get("/api/v1/agent/files/download", params={
        "conversation_id": str(context.conversation.id),
        "path": path if path is not None else context.path,
    })


def test_owner_downloads_xlsx_with_exact_bytes_and_headers(download_context):
    response = _download(download_context)
    assert response.status_code == 200
    assert response.content == download_context.content
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''document_summary_all.xlsx"
    assert response.headers["content-length"] == str(len(download_context.content))
    assert download_context.storage.requested_keys == [download_context.scoped_key]


def test_download_preserves_unicode_filename(download_context):
    path = "outputs/รายงานสรุป.xlsx"
    download_context.storage.files[f"jobs/{download_context.conversation.job_id}/{path}"] = download_context.content
    response = _download(download_context, path)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f"attachment; filename*=UTF-8''{quote('รายงานสรุป.xlsx')}"


def test_missing_file_returns_404(download_context):
    assert _download(download_context, "outputs/missing.xlsx").status_code == 404


def test_other_users_conversation_returns_404_without_storage_access(download_context):
    download_context.conversation.user_id = uuid4()
    assert _download(download_context).status_code == 404
    assert download_context.storage.requested_keys == []


@pytest.mark.parametrize("path", ["../secret.xlsx", "outputs/../../secret.xlsx"])
def test_path_traversal_returns_400_without_storage_access(download_context, path):
    assert _download(download_context, path).status_code == 400
    assert download_context.storage.requested_keys == []
