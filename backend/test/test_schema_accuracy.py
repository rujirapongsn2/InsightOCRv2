"""Accuracy from reviewer corrections, review suggestions and test-run history."""
import importlib
import pkgutil
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models

for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")

from app.models.document import Document
from app.models.schema import DocumentSchema, SchemaVersion
from app.services import schema_accuracy, schema_versions
from app.services.field_mapping import label_value


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    tables = [DocumentSchema.__table__, SchemaVersion.__table__, Document.__table__]
    DocumentSchema.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


FIELDS = [
    {"name": "invoice_no", "type": "text", "required": True,
     "validation_rules": {"pattern": r"INV-\d{4}"}},
    {"name": "total", "type": "number", "required": True},
    {"name": "po_number", "type": "text", "required": True},
]


def make_schema(db, fields=FIELDS):
    schema = DocumentSchema(id=uuid4(), name="Invoice", document_type="invoice", fields=fields)
    db.add(schema)
    db.flush()
    schema_versions.ensure_current_version(db, schema)
    return schema


_clock = [datetime(2026, 9, 1, tzinfo=timezone.utc)]


def add_document(db, schema, extracted, reviewed, *, text="", reviewer=True, evidence=None, decision="confirmed"):
    _clock[0] += timedelta(minutes=1)
    document = Document(
        id=uuid4(), job_id=uuid4(), filename=f"doc-{len(db.query(Document).all())}.pdf", file_path="x",
        schema_id=schema.id, schema_version_id=schema_versions.latest_version(db, schema.id).id,
        extracted_data=extracted, reviewed_data=reviewed, review_decision=decision,
        reviewed_by=uuid4() if reviewer else None, reviewed_at=_clock[0], ocr_text=text,
        extraction_metadata={"field_evidence": evidence or {}},
    )
    db.add(document)
    db.flush()
    return document


def field(report, name):
    return next(item for item in report["fields"] if item["name"] == name)


def test_classify_outcomes():
    assert schema_accuracy.classify("INV-1", "inv-1") == "correct"
    assert schema_accuracy.classify("1,250.00", 1250) == "correct"
    assert schema_accuracy.classify("INV-1", "INV-2") == "corrected"
    assert schema_accuracy.classify(None, "INV-2") == "missed"
    assert schema_accuracy.classify("INV-1", "") == "cleared"
    assert schema_accuracy.classify("", None) is None


def test_accuracy_counts_only_human_reviews_and_groups_by_provider(db):
    schema = make_schema(db)
    add_document(db, schema, {"invoice_no": "INV-0001", "total": 10}, {"invoice_no": "INV-0001", "total": 10},
                 evidence={"invoice_no": {"provider": "llm:OpenAI:gpt"}, "total": {"provider": "label"}})
    add_document(db, schema, {"invoice_no": "INV-0002", "total": 10}, {"invoice_no": "INV-0003", "total": 12},
                 evidence={"invoice_no": {"provider": "jev"}, "total": {"provider": "label"}})
    add_document(db, schema, {"total": 5}, {"invoice_no": "INV-0004", "total": 5})
    # Auto-confirmed (no reviewer) and rejected documents are left out.
    add_document(db, schema, {"invoice_no": "X"}, {"invoice_no": "X"}, reviewer=False)
    add_document(db, schema, {"invoice_no": "X"}, {"invoice_no": "Y"}, decision="rejected")

    report = schema_accuracy.schema_accuracy(db, schema)

    assert report["reviewed_documents"] == 3
    invoice = field(report, "invoice_no")
    assert (invoice["checked"], invoice["correct"], invoice["corrected"], invoice["missed"]) == (3, 1, 1, 1)
    assert invoice["accuracy"] == pytest.approx(1 / 3, abs=1e-3)
    providers = {item["provider"]: item for item in invoice["by_provider"]}
    assert providers["llm"]["correct"] == 1 and providers["jev"]["correct"] == 0
    assert providers["not_found"]["checked"] == 1
    assert [example["outcome"] for example in invoice["examples"]] == ["missed", "corrected"]
    total = field(report, "total")
    assert (total["checked"], total["correct"], total["corrected"]) == (3, 2, 1)
    assert field(report, "po_number")["checked"] == 0  # empty in both: nothing to measure
    assert report["overall"] == {"checked": 6, "correct": 3, "accuracy": 0.5}
    assert report["versions"][0]["version"] == 1


def test_accuracy_is_split_by_schema_version(db):
    schema = make_schema(db)
    add_document(db, schema, {"total": 1}, {"total": 2})
    schema.fields = FIELDS + [{"name": "vendor", "type": "text"}]
    schema_versions.ensure_current_version(db, schema)
    add_document(db, schema, {"total": 3}, {"total": 3})

    by_version = {item["version"]: item for item in field(schema_accuracy.schema_accuracy(db, schema), "total")["by_version"]}
    assert (by_version[1]["correct"], by_version[2]["correct"]) == (0, 1)


def test_label_value_needs_exactly_one_line():
    assert label_value("PO No: 12345\nTotal: 10", ["PO No"]) == "12345"
    assert label_value("PO No: 1\nPO No: 2", ["PO No"]) is None
    assert label_value("PO No: 1", []) is None


def test_suggests_labels_that_would_have_found_missed_values(db):
    schema = make_schema(db)
    for number in ("PO-7781", "PO-7782"):
        add_document(db, schema, {"po_number": None}, {"po_number": number},
                     text=f"Invoice INV-0001\nเลขที่ใบสั่งซื้อ : {number}\nTotal: 10")
    # A label seen only once is not enough evidence.
    add_document(db, schema, {"po_number": None}, {"po_number": "PO-1"}, text="Order ref: PO-1")

    result = schema_accuracy.suggest_improvements(db, schema)
    labels = [item for item in result["suggestions"] if item["kind"] == "add_labels"]
    assert labels == [{
        "field": "po_number", "kind": "add_labels", "labels": ["เลขที่ใบสั่งซื้อ"], "documents_fixed": 2,
        "reason": labels[0]["reason"], "examples": labels[0]["examples"],
    }]
    assert {example["line"] for example in labels[0]["examples"]} == {"เลขที่ใบสั่งซื้อ : PO-7781",
                                                                       "เลขที่ใบสั่งซื้อ : PO-7782"}


def test_label_that_would_break_a_correct_document_is_not_suggested(db):
    schema = make_schema(db)
    for number in ("PO-1", "PO-2"):
        add_document(db, schema, {"po_number": None}, {"po_number": number}, text=f"Ref: {number}")
    # "Ref" here labels something else, and the engine got this one right.
    add_document(db, schema, {"po_number": "PO-3"}, {"po_number": "PO-3"}, text="Ref: Q-9\nPO: PO-3")

    result = schema_accuracy.suggest_improvements(db, schema)
    assert not [item for item in result["suggestions"] if item["kind"] == "add_labels"]


def test_suggests_a_wider_pattern_when_confirmed_values_are_rejected(db):
    schema = make_schema(db)
    add_document(db, schema, {"invoice_no": None}, {"invoice_no": "INV-00123"})
    add_document(db, schema, {"invoice_no": "INV-0001"}, {"invoice_no": "INV-0001"})

    suggestion = next(item for item in schema_accuracy.suggest_improvements(db, schema)["suggestions"]
                      if item["field"] == "invoice_no")
    assert suggestion["kind"] == "replace_pattern"
    assert suggestion["pattern"] == r"INV\-\d{4,5}"
    assert suggestion["documents_rejected"] == 1


def test_mixed_shapes_suggest_removing_the_pattern():
    assert schema_accuracy.generalize_pattern(["INV-0001", "2026/15"]) is None
    assert schema_accuracy.generalize_pattern(["AB12", "CD345"]) == r"[A-Za-z]{2}\d{2,3}"


def test_required_field_left_empty_by_reviewers_is_suggested_optional(db):
    schema = make_schema(db)
    for _ in range(3):
        add_document(db, schema, {"total": 1}, {"total": 1, "po_number": ""})
    kinds = {(item["field"], item["kind"]) for item in schema_accuracy.suggest_improvements(db, schema)["suggestions"]}
    assert ("po_number", "make_optional") in kinds
    assert ("total", "make_optional") not in kinds


def test_documents_processed_before_a_field_existed_do_not_count(db):
    schema = make_schema(db, FIELDS[:2])
    for _ in range(5):  # v1 had no po_number
        add_document(db, schema, {"total": 1}, {"total": 1})
    schema.fields = FIELDS
    schema_versions.ensure_current_version(db, schema)
    kinds = {(item["field"], item["kind"]) for item in schema_accuracy.suggest_improvements(db, schema)["suggestions"]}
    assert ("po_number", "make_optional") not in kinds
    for _ in range(3):  # on v2 reviewers really leave it empty
        add_document(db, schema, {"total": 1}, {"total": 1})
    kinds = {(item["field"], item["kind"]) for item in schema_accuracy.suggest_improvements(db, schema)["suggestions"]}
    assert ("po_number", "make_optional") in kinds


def test_reviews_saved_as_a_one_item_list_are_counted(db):
    schema = make_schema(db)
    add_document(db, schema, {"total": 1}, [{"total": 2}])
    assert field(schema_accuracy.schema_accuracy(db, schema), "total")["corrected"] == 1


def test_label_candidates_skip_lines_without_the_value():
    helper = schema_accuracy._FieldValues({"name": "total", "type": "number"})
    text = "Date: 2026-01-01\nGrand total: 1,250.00\nVAT: 81.78"
    assert list(helper.label_candidates(text, 1250)) == [("Grand total", "Grand total: 1,250.00")]
    assert not helper.may_contain("Date: 2026-01-01", 1250)


def test_apply_improvements_updates_a_copy():
    changes = [
        {"field": "po_number", "kind": "add_labels", "labels": ["PO No", "po no", " Ref  "]},
        {"field": "invoice_no", "kind": "replace_pattern", "pattern": r"INV-\d+"},
        {"field": "po_number", "kind": "make_optional"},
    ]
    updated = schema_accuracy.apply_improvements(FIELDS, changes)
    po = next(item for item in updated if item["name"] == "po_number")
    assert po["validation_rules"]["source_labels"] == ["PO No", "Ref"]
    assert po["required"] is False
    assert next(item for item in updated if item["name"] == "invoice_no")["validation_rules"]["pattern"] == r"INV-\d+"
    assert FIELDS[2]["required"] is True
    with pytest.raises(ValueError):
        schema_accuracy.apply_improvements(FIELDS, [{"field": "gone", "kind": "make_optional"}])
    with pytest.raises(ValueError):
        schema_accuracy.apply_improvements(FIELDS, [{"field": "invoice_no", "kind": "replace_pattern", "pattern": "("}])


def run_entry(fields, error=None):
    return {"error": error, "comparison": {"checked": len(fields), "matched": sum(fields.values()),
                                           "fields": {name: {"match": bool(ok)} for name, ok in fields.items()}}}


def test_test_run_history_compares_with_the_previous_run(db):
    schema = make_schema(db)
    first = schema_versions.summarize_test_run([run_entry({"total": 1, "invoice_no": 0}), run_entry({}, "Timeout")],
                                               engine="auto", trigger="samples_added", run_at="2026-09-01T00:00:00")
    assert (first["checked"], first["matched"], first["errors"]) == (2, 1, 1)
    schema_versions.append_test_run(db, schema.id, 1, first)
    schema.fields = FIELDS + [{"name": "vendor", "type": "text"}]
    schema_versions.ensure_current_version(db, schema)
    second = schema_versions.summarize_test_run([run_entry({"total": 0, "invoice_no": 1})],
                                                engine="llm", trigger="schema_change", run_at="2026-09-02T00:00:00")
    schema_versions.append_test_run(db, schema.id, 2, second)
    db.flush()

    history = schema_versions.version_test_history(db.query(SchemaVersion).all())
    assert history[1]["comparison"] is None
    assert history[2]["compared_with_version"] == 1
    assert history[2]["comparison"]["improved"] == ["invoice_no"]
    assert history[2]["comparison"]["regressed"] == ["total"]
    assert history[2]["latest"]["trigger"] == "schema_change"


def test_test_runs_are_capped(db):
    schema = make_schema(db)
    for index in range(schema_versions.MAX_TEST_RUNS + 3):
        schema_versions.append_test_run(db, schema.id, 1, {"run_at": str(index), "fields": {}})
    runs = schema_versions.latest_version(db, schema.id).test_runs
    assert len(runs) == schema_versions.MAX_TEST_RUNS and runs[-1]["run_at"] == str(schema_versions.MAX_TEST_RUNS + 2)
