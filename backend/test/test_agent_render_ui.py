"""render_ui: A2UI surfaces are validated at the tool boundary and show only job documents."""
import asyncio
import importlib
import pkgutil
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models

for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(element, compiler, **kw):
    return "JSON"


from app.agent.a2ui import CATALOG_ID
from app.agent.tools.registry import tool_registry
from app.agent.tools.ui_tools import _render_ui_handler
from app.models.document import Document

JOB = uuid.uuid4()
OTHER_JOB = uuid.uuid4()


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Document.metadata.create_all(engine, tables=[Document.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _doc(db, job_id, filename, status="extraction_completed"):
    doc = Document(id=uuid.uuid4(), job_id=job_id, filename=filename, file_path="x", status=status)
    db.add(doc)
    db.commit()
    return str(doc.id)


def _render(db, components, data):
    context = SimpleNamespace(db=db, job_id=JOB, user_id=uuid.uuid4())
    return asyncio.run(_render_ui_handler({"components": components, "data": data}, context))


def _surface(**overrides):
    components = {
        "root": {"id": "root", "component": "Column", "children": ["title", "list", "approve"]},
        "title": {"id": "title", "component": "Text", "text": "เอกสารรออนุมัติ", "variant": "heading"},
        "list": {"id": "list", "component": "DocumentList", "documents": {"path": "/documents"},
                 "selectable": True, "selection": "/selected"},
        "approve": {"id": "approve", "component": "Button", "label": "อนุมัติ", "variant": "primary",
                    "action": {"event": {"name": "approve_documents",
                                         "context": {"document_ids": {"path": "/selected"}}}}},
    }
    components.update(overrides)
    return [c for c in components.values() if c is not None]


def test_valid_surface_yields_v09_messages_with_database_rows(db):
    doc_id = _doc(db, JOB, "invoice-01.pdf")
    result = _render(db, _surface(), {"documents": [{"document_id": doc_id, "note": "ยอดไม่ตรง"}]})

    assert result["ok"] is True
    create, update, model = result["a2ui"]
    assert all(message["version"] == "v0.9" for message in result["a2ui"])
    assert create["createSurface"] == {"surfaceId": result["surface_id"], "catalogId": CATALOG_ID}
    assert {c["id"] for c in update["updateComponents"]["components"]} == {"root", "title", "list", "approve"}
    assert model["updateDataModel"]["path"] == "/"
    assert model["updateDataModel"]["value"] == {
        "documents": [{"document_id": doc_id, "filename": "invoice-01.pdf",
                       "status": "extraction_completed", "note": "ยอดไม่ตรง"}],
        "selected": [],
    }


def test_foreign_job_and_unknown_ids_are_not_displayed(db):
    own = _doc(db, JOB, "own.pdf")
    foreign = _doc(db, OTHER_JOB, "secret-other-job.pdf")
    unknown = str(uuid.uuid4())
    result = _render(db, _surface(), {"documents": [
        {"document_id": own.upper()}, {"document_id": foreign}, {"document_id": unknown}]})

    rows = result["a2ui"][2]["updateDataModel"]["value"]["documents"]
    assert [row["document_id"] for row in rows] == [own]
    assert "secret-other-job.pdf" not in str(result["a2ui"])
    assert result["dropped_document_ids"] == [foreign, unknown]
    assert result["document_count"] == 1


def test_one_malformed_id_rejects_the_whole_surface(db):
    own = _doc(db, JOB, "own.pdf")
    result = _render(db, _surface(), {"documents": [{"document_id": own}, {"document_id": "not-a-uuid"}]})
    assert result["ok"] is False
    assert "not-a-uuid" in result["error"] and "list_documents" in result["error"]


def test_only_foreign_ids_is_a_corrective_error(db):
    foreign = _doc(db, OTHER_JOB, "x.pdf")
    result = _render(db, _surface(), {"documents": [{"document_id": foreign}]})
    assert result["ok"] is False
    assert "list_documents" in result["error"]


def test_model_supplied_filename_is_rejected(db):
    doc_id = _doc(db, JOB, "real.pdf")
    result = _render(db, _surface(), {"documents": [{"document_id": doc_id, "filename": "fake.pdf"}]})
    assert result["ok"] is False
    assert "filled in by the system" in result["error"]


@pytest.mark.parametrize(("overrides", "expected"), [
    ({"title": {"id": "title", "component": "Chart", "series": []}}, "unknown type 'Chart'"),
    ({"root": None, "box": {"id": "box", "component": "Column", "children": ["title", "list", "approve"]}},
     'id "root"'),
    ({"root": {"id": "root", "component": "Column", "children": ["title", "ghost"]}},
     'references child "ghost", which is not defined'),
    ({"root": {"id": "root", "component": "Column", "children": ["title"]},
      "a": {"id": "a", "component": "Column", "children": ["b"]},
      "b": {"id": "b", "component": "Column", "children": ["a"]}}, "cycle"),
    ({"approve": {"id": "approve", "component": "Button", "label": "ลบ",
                  "action": {"event": {"name": "delete_documents"}}}},
     "'delete_documents' is not allowed; use one of ['approve_documents', 'reject_documents', 'ask_agent']"),
])
def test_invalid_surface_returns_a_corrective_error(db, overrides, expected):
    doc_id = _doc(db, JOB, "a.pdf")
    result = _render(db, _surface(**overrides), {"documents": [{"document_id": doc_id}]})
    assert result["ok"] is False
    assert result["error"].startswith("render_ui was not shown. Fix these problems")
    assert expected in result["error"]


def test_duplicate_ids_and_size_caps_are_rejected(db):
    duplicate = _surface() + [{"id": "title", "component": "Text", "text": "again"}]
    assert "used twice" in _render(db, duplicate, {"documents": []})["error"]
    too_many = [{"id": "root", "component": "Column", "children": [f"t{i}" for i in range(60)]}] + [
        {"id": f"t{i}", "component": "Text", "text": "x"} for i in range(60)]
    assert "the limit is 50" in _render(db, too_many, {})["error"]
    rows = [{"document_id": str(uuid.uuid4())} for _ in range(201)]
    assert "the limit is 200" in _render(db, _surface(), {"documents": rows})["error"]


def test_render_ui_is_offered_to_the_jobs_agent_without_confirmation():
    from app.agent.confirmations import requires_confirmation
    import app.agent.loop  # noqa: F401 — registers every agent tool

    names = {schema["function"]["name"] for schema in tool_registry.get_openai_schemas(allowed_names=None)}
    assert "render_ui" in names
    assert requires_confirmation("render_ui", {}) is False


