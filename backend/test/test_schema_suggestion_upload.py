from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.api.v1.endpoints import schemas
from app.api.v1.endpoints.schemas import _ensure_can_create_schema, _validate_suggestion_upload
from app.core.config import settings


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


def test_schema_suggestion_rejects_disallowed_file_type():
    with pytest.raises(HTTPException) as exc:
        _validate_suggestion_upload(_upload("malware.exe", b"x"))

    assert exc.value.status_code == 415


def test_schema_suggestion_rejects_files_over_upload_limit(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

    with pytest.raises(HTTPException) as exc:
        _validate_suggestion_upload(_upload("invoice.pdf", b"x" * (1024 * 1024 + 1)))

    assert exc.value.status_code == 413


def test_schema_suggestion_requires_schema_management_permission():
    user = type("User", (), {"role": "user", "is_superuser": False})()

    with pytest.raises(HTTPException) as exc:
        _ensure_can_create_schema(user)

    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["admin", "manager", "documents_admin"])
def test_schema_suggestion_allows_schema_managers(role):
    user = type("User", (), {"role": role, "is_superuser": False})()

    _ensure_can_create_schema(user)


def test_schema_sample_worker_owns_and_closes_its_database_session(monkeypatch):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    session = FakeSession()
    extracted = object()
    observed = []
    monkeypatch.setattr(schemas, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        schemas,
        "extract_schema_sample",
        lambda file_path, worker_db: observed.append((file_path, worker_db)) or extracted,
    )

    assert schemas._extract_schema_sample_in_worker("/tmp/sample.pdf") is extracted
    assert observed == [("/tmp/sample.pdf", session)]
    assert session.closed
