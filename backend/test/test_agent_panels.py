"""Panel tools (A2UI catalog v2): typed arguments, system-computed values, job-scoped
sources, per-item quote verification, and golden fixtures shared with the frontend.

Regenerate the fixtures after an intended change:
    cd backend && A2UI_WRITE_FIXTURES=1 SECRET_KEY=test python -m pytest test/test_agent_panels.py -k golden
"""
import asyncio
import importlib
import json
import os
import pkgutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models

for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(element, compiler, **kw):
    return "JSON"


import app.agent.loop as loop_mod  # noqa: E402 — registers every agent tool
from app.agent.a2ui import CATALOG_ID, DECIMALS, PANEL_TOOLS, ShowTable, compare, quote_found  # noqa: E402
from app.agent.context import tool_content_for_llm  # noqa: E402
from app.agent.tools import ui_tools  # noqa: E402
from app.agent.tools.registry import tool_registry  # noqa: E402
from app.models.agent_surface import AgentSurface  # noqa: E402
from app.models.document import Document  # noqa: E402

JOB = uuid.UUID("6f1c2d3e-0000-4000-8000-000000000001")
OTHER_JOB = uuid.UUID("6f1c2d3e-0000-4000-8000-000000000002")
CONVERSATION = uuid.UUID("6f1c2d3e-0000-4000-8000-0000000000c1")
FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "test" / "fixtures" / "a2ui"
CONTRACT_TEXT = ("สัญญาจ้างบริการทำความสะอาด ข้อ 5 การชำระเงิน ผู้ว่าจ้างจะชำระค่าจ้างภายใน ๓๐ วัน นับจากวันที่ได้รับ"
                 "ใบแจ้งหนี้\nข้อ 7 ค่าปรับ หากผู้รับจ้างส่งมอบงานล่าช้า ผู้รับจ้างต้องชำระค่าปรับ  ในอัตราร้อยละ 0.5\n"
                 "ของมูลค่างานต่อวัน ข้อ 9 สัญญานี้ต่ออายุโดยอัตโนมัติทุกปี เว้นแต่คู่สัญญาฝ่ายใดแจ้งเป็นหนังสือ")


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Document.metadata.create_all(engine, tables=[Document.__table__, AgentSurface.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _doc(db, filename, *, job_id=JOB, ocr_text=None, status="extraction_completed", key=None):
    doc_id = uuid.uuid5(JOB, key or filename)
    if db.get(Document, doc_id) is not None:
        return str(doc_id)
    db.add(Document(id=doc_id, job_id=job_id, filename=filename, file_path="x", status=status, ocr_text=ocr_text))
    db.commit()
    return str(doc_id)


def _call(db, tool, args):
    context = SimpleNamespace(db=db, job_id=JOB, user_id=uuid.uuid4(), conversation_id=CONVERSATION)
    return asyncio.run(tool_registry.execute(tool, args, context))


def _data(result):
    return result["a2ui"][2]["updateDataModel"]["value"]


def _components(result):
    return {c["id"]: c for c in result["a2ui"][1]["updateComponents"]["components"]}


def _fails(result, *expected):
    assert result["ok"] is False, result
    for text in expected:
        assert text in result["error"], result["error"]


def _metric(**overrides):
    return {"label": "ค่าใช้จ่ายรวม", "kind": "money", "value": 3685.5, **overrides}


def _walk(node):
    yield node
    for child in (node.values() if isinstance(node, dict) else node if isinstance(node, list) else []):
        yield from _walk(child)


# ── Schemas ────────────────────────────────────────────────────────────────

def test_panel_tool_schemas_are_closed_and_inline():
    schemas = {s["function"]["name"]: s["function"]["parameters"] for s in tool_registry.get_openai_schemas()}
    assert "render_ui" not in schemas
    for tool in PANEL_TOOLS:
        schema = schemas[tool]
        nodes = list(_walk(schema))
        assert not [n for n in nodes if isinstance(n, dict) and ({"$ref", "$defs", "oneOf", "discriminator"} & set(n))], tool
        objects = [n for n in nodes if isinstance(n, dict) and "properties" in n]
        assert objects and all(n["additionalProperties"] is False for n in objects), tool
        json.dumps(schema)
    assert schemas["show_table"]["properties"]["rows"]["type"] == "array"
    assert schemas["show_table"]["properties"]["rows"]["items"]["type"] == "object"
    assert schemas["show_table"]["required"] == ["columns", "rows", "sources"]
    # An optional field is its plain type, not anyOf [type, null].
    assert schemas["show_table"]["properties"]["title"] == {"type": "string", "minLength": 1, "maxLength": 120}
    assert schemas["show_metrics"]["properties"]["metrics"]["items"]["properties"]["previous"]["type"] == "number"


def test_data_sent_as_a_json_string_cannot_be_expressed(db):
    rows = json.dumps([{"vendor": "ก"}])
    with pytest.raises(ValidationError):
        ShowTable.model_validate({"columns": [{"key": "vendor", "label": "ผู้ขาย", "kind": "text"}],
                                  "rows": rows, "sources": [str(uuid.uuid4())]})
    _fails(_call(db, "show_metrics", {"metrics": json.dumps([_metric()]), "sources": ["x"]}),
           "show_metrics was not shown", "metrics: Input should be a valid list")
    _fails(_call(db, "show_metrics", {"metrics": [_metric(value="3,685.50")], "sources": ["x"]}),
           "metrics.0.value: Input should be a valid number")
    _fails(_call(db, "show_metrics", {"metrics": [_metric(unit="THB")], "sources": ["x"]}),
           "metrics.0.unit: Extra inputs are not permitted")
    _fails(_call(db, "show_metrics", {"metrics": [_metric(delta=409.5)], "sources": ["x"]}), "delta")


# ── Comparisons ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, previous, kind, higher_is, expected", [
    (3685.5, 3276, "money", "bad", {"delta": 409.5, "percent": 12.5, "direction": "up", "sentiment": "bad"}),
    (3276, 3685.5, "money", "bad", {"delta": -409.5, "percent": -11.1, "direction": "down", "sentiment": "good"}),
    (90, 80, "count", "good", {"delta": 10, "percent": 12.5, "direction": "up", "sentiment": "good"}),
    (12, 12, "count", "good", {"delta": 0, "percent": 0.0, "direction": "flat", "sentiment": "neutral"}),
    (5, 0, "number", "neutral", {"delta": 5, "percent": None, "direction": "up", "sentiment": "neutral"}),
    (4.5, 6.0, "percent", "good", {"delta": -1.5, "percent": None, "direction": "down", "sentiment": "bad"}),
    (0.3, 0.1 + 0.2, "number", "good", {"delta": 0, "percent": 0.0, "direction": "flat", "sentiment": "neutral"}),
])
def test_compare_computes_direction_sentiment_and_relative_change(value, previous, kind, higher_is, expected):
    assert compare(value, previous, kind, higher_is) == expected


@pytest.mark.parametrize("value, previous, kind, expected", [
    # UAT A3b: 0.04 points used to read "▲ +0 จุด (แย่ลง)"; the chat shows a percent to 1 decimal.
    (12.54, 12.5, "percent", {"delta": 0.0, "percent": None, "direction": "flat", "sentiment": "neutral"}),
    (12.56, 12.5, "percent", {"delta": 0.1, "percent": None, "direction": "up", "sentiment": "bad"}),
    (100.004, 100, "money", {"delta": 0.0, "percent": 0.0, "direction": "flat", "sentiment": "neutral"}),
    (12.4, 12, "count", {"delta": 0, "percent": 0.0, "direction": "flat", "sentiment": "neutral"}),
    # The amount moved but the relative change would read +0%: the headline is the amount instead.
    (1_000_000.5, 1_000_000, "money", {"delta": 0.5, "percent": None, "direction": "up", "sentiment": "bad"}),
])
def test_a_change_too_small_to_show_is_flat(value, previous, kind, expected):
    assert compare(value, previous, kind, "bad") == expected


def test_metrics_carry_system_computed_changes(db):
    source = _doc(db, "invoice-2569-01.pdf")
    result = _call(db, "show_metrics", {"metrics": [
        _metric(previous=3276, previous_label="ธ.ค. 2568", higher_is="bad"),
        {"label": "อัตราส่วนลด", "kind": "percent", "value": 4.5, "previous": 6, "higher_is": "good"},
        {"label": "จำนวนใบแจ้งหนี้", "kind": "count", "value": 12},
    ], "sources": [source, source]})
    assert result["ok"] is True, result
    tiles = [c for c in _components(result).values() if c["component"] == "Metric"]
    assert [t.get("currency") for t in tiles] == ["THB", None, None]
    assert tiles[0]["previous_label"] == "ธ.ค. 2568"
    metrics = _data(result)["metrics"]
    assert metrics[0]["change"] == {"delta": 409.5, "percent": 12.5, "direction": "up", "sentiment": "bad"}
    assert metrics[1]["change"] == {"delta": -1.5, "percent": None, "direction": "down", "sentiment": "bad"}
    assert metrics[2] == {"value": 12}
    assert _data(result)["sources"] == [{"document_id": source, "filename": "invoice-2569-01.pdf"}]
    seen = json.loads(tool_content_for_llm(result))
    assert seen["metrics"][0] == {"label": "ค่าใช้จ่ายรวม", "change": metrics[0]["change"]}
    assert seen["sources"] == 1 and "a2ui" not in seen


@pytest.mark.parametrize("metric, expected", [
    ({"kind": "count", "value": 2.5}, "whole number"),
    ({"kind": "percent", "currency": "THB"}, '"currency" is only for kind "money"'),
    ({"currency": "บาท"}, "currency"),
    ({"previous_label": "เดือนก่อน"}, '"previous_label" needs "previous"'),
    ({"higher_is": "up"}, "higher_is"),
])
def test_invalid_metrics_are_corrective_errors(db, metric, expected):
    _fails(_call(db, "show_metrics", {"metrics": [_metric(**metric)], "sources": [_doc(db, "a.pdf")]}), expected)


# ── Tables ─────────────────────────────────────────────────────────────────

TABLE_COLUMNS = [
    {"key": "vendor", "label": "ผู้ขาย", "kind": "text"},
    {"key": "amount", "label": "ยอดเดือนนี้", "kind": "money"},
    {"key": "last", "label": "ยอดเดือนก่อน", "kind": "money"},
    {"key": "change", "label": "เปลี่ยนแปลง", "kind": "change", "of": "amount", "vs": "last", "higher_is": "bad"},
]


def _table(db, rows, columns=TABLE_COLUMNS, **extra):
    return _call(db, "show_table", {"columns": columns, "rows": rows, "sources": [_doc(db, "a.pdf")], **extra})


def test_change_columns_are_computed_per_row(db):
    result = _table(db, [{"vendor": "ก", "amount": 1200, "last": 1000},
                         {"vendor": "ข", "amount": 900, "last": 1000},
                         {"vendor": "ค", "amount": 500, "last": None}])
    assert result["ok"] is True, result
    assert [row["change"] for row in _data(result)["rows"]] == [
        {"delta": 200, "percent": 20.0, "direction": "up", "sentiment": "bad"},
        {"delta": -100, "percent": -10.0, "direction": "down", "sentiment": "good"},
        None,
    ]
    change = _components(result)["table"]["columns"][3]
    assert change == {**TABLE_COLUMNS[3], "value_kind": "money", "currency": "THB"}
    assert json.loads(tool_content_for_llm(result)) == {"ok": True, "panel_id": result["panel_id"],
                                                        "rows": 3, "columns": 4, "sources": 1}


@pytest.mark.parametrize("rows, columns, expected", [
    ([{"vendor": "ก", "amount": 1, "last": 1, "change": 0}], TABLE_COLUMNS, "change columns are computed by the system"),
    ([{"vendor": "ก", "amount": 1, "document_id": "x"}], TABLE_COLUMNS, "not columns"),
    ([{"vendor": "ก", "amount": "1,200"}], TABLE_COLUMNS, "must be a number (not a string)"),
    ([{"vendor": "ก"}], [*TABLE_COLUMNS[:3], {**TABLE_COLUMNS[3], "vs": "vendor"}], "numeric columns of the same kind"),
    ([{"vendor": "ก"}], [*TABLE_COLUMNS[:3], {**TABLE_COLUMNS[3], "vs": "missing"}], "two different value columns"),
    ([{"vendor": "ก"}], [*TABLE_COLUMNS[:2], {"key": "last", "label": "ส่วนลด", "kind": "percent"}, TABLE_COLUMNS[3]],
     "same kind"),
    ([{"vendor": "ก"}], [TABLE_COLUMNS[0], TABLE_COLUMNS[0]], "column keys must be unique"),
    ([{"day": "2026-02-30"}], [{"key": "day", "label": "วันที่", "kind": "date"}], 'ISO date like "2026-01-31"'),
    ([{"day": "31/01/2026"}], [{"key": "day", "label": "วันที่", "kind": "date"}], "ISO date"),
    ([{"m": "2026-13"}], [{"key": "m", "label": "เดือน", "kind": "month"}], 'ISO month like "2026-01"'),
    ([{"m": "Jan 2026"}], [{"key": "m", "label": "เดือน", "kind": "month"}], "ISO month"),
    ([{"n": 1.5}], [{"key": "n", "label": "จำนวน", "kind": "count"}], "whole number"),
])
def test_invalid_tables_are_corrective_errors(db, rows, columns, expected):
    _fails(_table(db, rows, columns), "show_table was not shown", expected)


DUE = [{"key": "vendor", "label": "ผู้ขาย", "kind": "text"}, {"key": "due", "label": "วันครบกำหนด/หมายเหตุ", "kind": "text"}]


@pytest.mark.parametrize("cell, kind, iso", [
    # UAT A3: the agent folded a remark into a due-date text column, so the date showed as 2026-03-20.
    ("2026-03-20 (เครดิต 30 วันจากวันที่ออกใบแจ้งหนี้ 2026-02-18)", "date", "2026-03-20"),
    ("ครบกำหนด 2026-03-20", "date", "2026-03-20"),
    ("2026-03", "month", "2026-03"),
])
def test_a_date_in_a_text_column_is_sent_back_to_its_own_column(db, cell, kind, iso):
    result = _table(db, [{"vendor": "Thai Golden Foods", "due": cell}], DUE)
    _fails(result, "show_table was not shown", f'rows[0].due is text holding the {kind} "{iso}"',
           f'a column of kind "{kind}"', "separate text column")


@pytest.mark.parametrize("cell", ["ไม่ระบุในเอกสาร", "INV-2026-01-15", "230906-01-04641", "Valid until 31/01/2026",
                                  "2026-02-30 ไม่ใช่วันที่", "รอบ 2026-01 ถึง 2026-03"])
def test_text_that_is_not_a_date_stays_text(db, cell):
    assert _table(db, [{"vendor": "ก", "due": cell}], DUE)["ok"] is True


def test_the_table_schema_says_where_dates_go():
    schema = next(s["function"]["parameters"] for s in tool_registry.get_openai_schemas()
                  if s["function"]["name"] == "show_table")
    kinds = [branch["properties"]["kind"] for branch in schema["properties"]["columns"]["items"]["anyOf"]
             if "currency" in branch["properties"]]
    assert "text never holds a date" in kinds[0]["description"]


def test_valid_iso_dates_and_months_are_kept_raw(db):
    result = _table(db, [{"day": "2026-01-31", "m": "2026-01"}],
                    [{"key": "day", "label": "วันที่", "kind": "date"}, {"key": "m", "label": "เดือน", "kind": "month"}])
    assert _data(result)["rows"] == [{"day": "2026-01-31", "m": "2026-01"}]


def test_document_columns_resolve_job_documents(db):
    doc = _doc(db, "invoice-01.pdf")
    foreign = _doc(db, "other.pdf", job_id=OTHER_JOB)
    columns = [{"key": "doc", "label": "เอกสาร", "kind": "document"}, {"key": "amount", "label": "ยอด", "kind": "money"}]
    result = _table(db, [{"doc": doc.upper(), "amount": 10}, {"doc": None, "amount": 5}], columns)
    assert _data(result)["rows"] == [{"doc": {"document_id": doc, "filename": "invoice-01.pdf"}, "amount": 10},
                                     {"doc": None, "amount": 5}]
    _fails(_table(db, [{"doc": foreign, "amount": 1}], columns), "document column values", foreign)


# ── Sources ────────────────────────────────────────────────────────────────

def test_sources_are_required_and_job_scoped(db):
    rows = [{"vendor": "ก", "amount": 1, "last": 1}]
    _fails(_call(db, "show_table", {"columns": TABLE_COLUMNS, "rows": rows}), "sources: Field required")
    _fails(_call(db, "show_table", {"columns": TABLE_COLUMNS, "rows": rows, "sources": []}), "sources")
    foreign = _doc(db, "other.pdf", job_id=OTHER_JOB)
    unknown = str(uuid.uuid4())
    _fails(_call(db, "show_table", {"columns": TABLE_COLUMNS, "rows": rows, "sources": [_doc(db, "a.pdf"), foreign, unknown]}),
           "sources are not documents of this job", foreign, unknown)
    _fails(_call(db, "show_chart", {"title": "t", "type": "bar", "x": {"key": "v", "label": "ผู้ขาย", "kind": "text"},
                                    "series": [{"key": "a", "label": "ยอด"}], "value_kind": "money",
                                    "points": [{"v": "ก", "a": 1}], "sources": ["not-an-id"]}),
           "show_chart was not shown", "not document ids")


# ── Charts ─────────────────────────────────────────────────────────────────

def _chart(db, **overrides):
    args = {"title": "ค่าใช้จ่ายรายเดือน", "type": "line", "x": {"key": "month", "label": "เดือน", "kind": "month"},
            "series": [{"key": "total", "label": "ค่าใช้จ่าย"}], "value_kind": "money",
            "points": [{"month": "2026-02", "total": 30}, {"month": "2025-12", "total": 10}, {"month": "2026-01", "total": None}],
            "sources": [_doc(db, "a.pdf")], **overrides}
    return _call(db, "show_chart", args)


def test_line_points_are_sorted_by_the_system(db):
    result = _chart(db)
    assert [p["month"] for p in _data(result)["points"]] == ["2025-12", "2026-01", "2026-02"]
    assert _components(result)["chart"]["currency"] == "THB"
    assert json.loads(tool_content_for_llm(result))["points"] == 3


@pytest.mark.parametrize("overrides, expected", [
    ({"x": {"key": "month", "label": "เดือน", "kind": "text"}}, 'a line chart needs x kind "date" or "month"'),
    ({"points": [{"month": "2026-1", "total": 1}]}, "ISO month"),
    ({"points": [{"month": "2026-01", "total": 1}, {"month": "2026-01", "total": 2}]}, '"month" values must be unique'),
    ({"points": [{"month": "2026-01", "total": 1, "note": "x"}]}, "a point holds only"),
    ({"points": [{"month": "2026-01", "total": None}]}, "the chart has no values"),
    ({"points": [{"total": 1}]}, "points[0].month is required"),
    ({"series": [{"key": "month", "label": "x"}]}, "keys must be unique"),
    ({"value_kind": "text"}, "value_kind"),
])
def test_invalid_charts_are_corrective_errors(db, overrides, expected):
    _fails(_chart(db, **overrides), expected)


# ── Risks ──────────────────────────────────────────────────────────────────

def _risk(**overrides):
    return {"title": "ค่าปรับส่งมอบล่าช้า", "level": "high", "category": "ค่าปรับ",
            "description": "ค่าปรับคิดต่อวันโดยไม่มีเพดาน", "quote": "ร้อยละ 0.5 ของมูลค่างานต่อวัน",
            "recommendation": "เจรจาเพดานค่าปรับไม่เกินร้อยละ 10", **overrides}


def test_each_risk_quote_is_verified_and_reported_by_item(db):
    contract = _doc(db, "contract.pdf", ocr_text=CONTRACT_TEXT)
    result = _call(db, "show_risks", {"document_id": contract, "risks": [
        _risk(),
        _risk(title="ชำระเงินภายใน 30 วัน", level="low", quote="ชำระค่าจ้างภายใน 30 วัน"),  # Thai digits in the OCR text
        _risk(title="ผู้ว่าจ้างรับผิดไม่จำกัด", level="critical", quote="ผู้ว่าจ้างรับผิดไม่จำกัดจำนวน"),
    ]})
    assert result["ok"] is True, result
    assert [(r["id"], r["quote_verified"]) for r in _data(result)["risks"]] == [("r1", True), ("r2", True), ("r3", False)]
    seen = json.loads(tool_content_for_llm(result))
    assert seen == {"ok": True, "panel_id": result["panel_id"], "document": "contract.pdf",
                    "quotes_found": 2, "quotes_total": 3, "risks": [
                        {"id": "r1", "title": "ค่าปรับส่งมอบล่าช้า", "level": "high", "quote": "found"},
                        {"id": "r2", "title": "ชำระเงินภายใน 30 วัน", "level": "low", "quote": "found"},
                        {"id": "r3", "title": "ผู้ว่าจ้างรับผิดไม่จำกัด", "level": "critical", "quote": "not_found"},
                    ]}


def test_risks_read_ocr_text_for_their_one_document(db):
    contract = _doc(db, "contract.pdf", ocr_text=CONTRACT_TEXT)
    other = _doc(db, "other-contract.pdf", ocr_text=CONTRACT_TEXT)
    seen: list = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda conn, cursor, statement, params, *_: seen.append((statement, params)))
    assert _call(db, "show_risks", {"document_id": contract, "risks": [_risk()]})["ok"] is True
    reads = [(s, p) for s, p in seen if "ocr_text" in s]
    assert len(reads) == 1
    params = str(reads[0][1])
    assert uuid.UUID(contract).hex in params and uuid.UUID(other).hex not in params


def test_risks_need_a_quote_and_a_job_document(db):
    _fails(_call(db, "show_risks", {"document_id": _doc(db, "c.pdf"), "risks": [{**_risk(), "quote": " "}]}), "quote")
    no_quote = {k: v for k, v in _risk().items() if k != "quote"}
    _fails(_call(db, "show_risks", {"document_id": _doc(db, "c.pdf"), "risks": [no_quote]}), "quote: Field required")
    _fails(_call(db, "show_risks", {"document_id": _doc(db, "c.pdf"), "risks": [{**_risk(), "quote_verified": True}]}),
           "quote_verified: Extra inputs are not permitted")
    foreign = _doc(db, "x.pdf", job_id=OTHER_JOB)
    _fails(_call(db, "show_risks", {"document_id": foreign, "risks": [_risk()]}), "not documents of this job")


def test_quote_found_uses_the_document_search_normalization():
    assert quote_found("ร้อยละ 0.5 ของมูลค่างาน", "ในอัตราร้อยละ 0.5\nของ มูลค่างาน ต่อวัน")
    assert quote_found("ชำระภายใน 30 วัน", "ผู้ซื้อต้องชำระภายใน ๓๐ วัน นับจาก")
    assert not quote_found("ร้อยละ 5 ของมูลค่างาน", "ในอัตราร้อยละ 0.5 ของมูลค่างาน")
    assert not quote_found("abc", None)


# ── Documents ──────────────────────────────────────────────────────────────

def test_documents_panel_shows_job_rows_and_reports_dropped_ids(db):
    doc = _doc(db, "invoice-01.pdf")
    foreign = _doc(db, "other.pdf", job_id=OTHER_JOB)
    result = _call(db, "show_documents", {"title": "เอกสารรออนุมัติ", "actions": ["approve", "reject"], "documents": [
        {"document_id": doc, "note": "ยอดไม่ตรง"}, {"document_id": doc.upper()}, {"document_id": foreign}]})
    assert result["ok"] is True, result
    assert result["a2ui"][0]["createSurface"] == {"surfaceId": result["panel_id"], "catalogId": CATALOG_ID}
    assert _data(result) == {"documents": [{"document_id": doc, "filename": "invoice-01.pdf",
                                            "status": "extraction_completed", "note": "ยอดไม่ตรง"}], "selected": []}
    components = _components(result)
    assert components["list"]["selectable"] is True and components["list"]["selection"] == "/selected"
    assert components["approve"]["action"]["event"] == {"name": "approve_documents",
                                                        "context": {"document_ids": {"path": "/selected"}}}
    assert components["reject"]["action"]["event"]["name"] == "reject_documents"
    assert json.loads(tool_content_for_llm(result)) == {
        "ok": True, "panel_id": result["panel_id"], "shown": [doc], "buttons": ["อนุมัติที่เลือก", "ปฏิเสธที่เลือก"],
        "dropped": [foreign], "note": result["note"]}
    batch = json.loads(tool_content_for_llm([{"tool": "show_documents", "arguments": {}, "result": result}]))
    assert "a2ui" not in batch[0]["result"]


def test_documents_panel_without_actions_is_read_only_and_needs_job_documents(db):
    result = _call(db, "show_documents", {"documents": [{"document_id": _doc(db, "a.pdf")}]})
    assert _components(result)["list"]["selectable"] is False and "selected" not in _data(result)
    _fails(_call(db, "show_documents", {"documents": [{"document_id": _doc(db, "b.pdf", job_id=OTHER_JOB)}]}),
           "none of these documents belong to this job")
    _fails(_call(db, "show_documents", {"documents": [{"document_id": "doc-1"}]}), "not document ids")
    _fails(_call(db, "show_documents", {"documents": [{"document_id": _doc(db, "c.pdf"), "filename": "x"}]}),
           "Extra inputs")


def test_panel_tools_are_offered_without_confirmation():
    from app.agent.confirmations import requires_confirmation

    names = {schema["function"]["name"] for schema in tool_registry.get_openai_schemas()}
    assert set(PANEL_TOOLS) <= names
    assert not any(requires_confirmation(tool, {}) for tool in PANEL_TOOLS)


@pytest.mark.parametrize("tool", PANEL_TOOLS)
def test_every_panel_tool_tells_the_model_not_to_restate_the_panel(tool):
    """UAT 1: after show_documents the agent listed all 8 filenames and named buttons "approve/reject"."""
    description = next(s["function"]["description"] for s in tool_registry.get_openai_schemas()
                       if s["function"]["name"] == tool)
    assert description.endswith(ui_tools.SHOWN)
    assert "do not restate" in ui_tools.SHOWN and "filenames" in ui_tools.SHOWN


def test_a_document_panel_tells_the_model_its_button_labels(db):
    ids = [_doc(db, "a.pdf"), _doc(db, "b.pdf")]
    result = _call(db, "show_documents", {"documents": [{"document_id": i} for i in ids], "actions": ["approve", "reject"]})
    assert json.loads(tool_content_for_llm(result))["buttons"] == ["อนุมัติที่เลือก", "ปฏิเสธที่เลือก"]
    listing = _call(db, "show_documents", {"documents": [{"document_id": ids[0]}]})
    assert "buttons" not in listing


@pytest.mark.parametrize("tool", PANEL_TOOLS)
def test_a_panel_failure_the_model_fixes_is_not_a_run_failure(tool):
    critical = [{"tool": tool, "error": "not shown"}, {"tool": "bulk_approve", "error": "x"}]
    unresolved = [{"tool": tool, "result": {"ok": False}}]
    loop_mod._settle_corrected_failures(tool, critical, unresolved)
    assert critical == [{"tool": "bulk_approve", "error": "x"}] and unresolved == []

    kept = [{"tool": "bulk_approve", "error": "x"}]
    loop_mod._settle_corrected_failures("bulk_approve", kept)
    assert kept == [{"tool": "bulk_approve", "error": "x"}]


# ── Golden fixtures shared with the frontend ───────────────────────────────

def _golden_calls(db):
    jan = _doc(db, "ใบแจ้งหนี้-บริษัทสยามคลีน-ม.ค.69.pdf")
    dec = _doc(db, "ใบแจ้งหนี้-บริษัทสยามคลีน-ธ.ค.68.pdf")
    office = _doc(db, "ใบแจ้งหนี้-ออฟฟิศเมท-ม.ค.69.pdf")
    contract = _doc(db, "สัญญาจ้างบริการทำความสะอาด-2569.pdf", ocr_text=CONTRACT_TEXT, status="reviewed")
    return {
        "show_documents": {"title": "เอกสารรออนุมัติ 3 รายการ", "actions": ["approve", "reject"], "documents": [
            {"document_id": jan, "note": "ยอดรวมสูงกว่าเดือนก่อน 12.5%"}, {"document_id": dec},
            {"document_id": office, "note": "ไม่พบเลขประจำตัวผู้เสียภาษีผู้ขาย"}]},
        "show_metrics": {"title": "สรุปค่าใช้จ่าย ม.ค. 2569", "sources": [jan, dec, office], "metrics": [
            {"label": "ค่าใช้จ่ายรวม", "kind": "money", "value": 3685.5, "previous": 3276,
             "previous_label": "ธ.ค. 2568", "higher_is": "bad"},
            {"label": "จำนวนใบแจ้งหนี้", "kind": "count", "value": 12, "previous": 12, "previous_label": "ธ.ค. 2568"},
            {"label": "ส่วนลดเฉลี่ย", "kind": "percent", "value": 4.5, "previous": 6, "previous_label": "ธ.ค. 2568",
             "higher_is": "good"},
            {"label": "อัตราเอกสารถูกปฏิเสธ", "kind": "percent", "value": 2.04, "previous": 2, "previous_label": "ธ.ค. 2568",
             "higher_is": "bad"}]},
        "show_table": {"title": "เทียบยอดตามผู้ขาย", "sources": [jan, dec, office], "columns": [
            {"key": "vendor", "label": "ผู้ขาย", "kind": "text"},
            {"key": "doc", "label": "เอกสาร", "kind": "document"},
            {"key": "issued", "label": "วันที่ออก", "kind": "date"},
            {"key": "amount", "label": "ยอดเดือนนี้", "kind": "money"},
            {"key": "budget", "label": "งบประมาณ", "kind": "money"},
            {"key": "change", "label": "เทียบงบ", "kind": "change", "of": "amount", "vs": "budget", "higher_is": "bad"}],
            "rows": [
                {"vendor": "บริษัท สยามคลีน จำกัด", "doc": jan, "issued": "2026-01-31", "amount": 2450.5, "budget": 2000},
                {"vendor": "ออฟฟิศเมท", "doc": office, "issued": "2026-01-15", "amount": 1235, "budget": 1500}]},
        "show_chart": {"title": "ค่าใช้จ่ายรายเดือน", "type": "line", "value_kind": "money", "sources": [jan, dec, office],
                       "x": {"key": "month", "label": "เดือน", "kind": "month"},
                       "series": [{"key": "cleaning", "label": "ทำความสะอาด"}, {"key": "office", "label": "เครื่องเขียน"}],
                       "points": [{"month": "2026-01", "cleaning": 2450.5, "office": 1235},
                                  {"month": "2025-09", "cleaning": 1980, "office": 1120},
                                  {"month": "2025-10", "cleaning": 2010, "office": 980},
                                  {"month": "2025-11", "cleaning": 2105, "office": None},
                                  {"month": "2025-12", "cleaning": 2156, "office": 1120}]},
        "show_risks": {"document_id": contract, "title": "ความเสี่ยงในสัญญาจ้างบริการทำความสะอาด", "risks": [
            _risk(page=2),
            {"title": "ต่ออายุอัตโนมัติ", "level": "critical", "category": "การต่ออายุ",
             "description": "สัญญาต่ออายุเองทุกปีหากไม่แจ้งเป็นหนังสือ", "quote": "สัญญานี้ต่ออายุโดยอัตโนมัติทุกปี",
             "page": 3, "recommendation": "ตั้งการแจ้งเตือนก่อนครบรอบสัญญา 60 วัน"},
            {"title": "ผู้ว่าจ้างรับผิดไม่จำกัด", "level": "medium", "category": "ความรับผิด",
             "description": "ไม่มีเพดานความรับผิดของผู้ว่าจ้าง", "quote": "ผู้ว่าจ้างรับผิดไม่จำกัดจำนวน",
             "recommendation": "เพิ่มเพดานความรับผิดเท่ากับมูลค่าสัญญา"},
            {"title": "ชำระเงินภายใน 30 วัน", "level": "low", "category": "การชำระเงิน",
             "description": "ระยะเวลาชำระเงินมาตรฐาน", "quote": "ชำระค่าจ้างภายใน 30 วัน",
             "recommendation": "ไม่ต้องแก้ไข"}]},
    }


def test_golden_fixtures_match(db, monkeypatch):
    """Each panel tool's real output, written where the frontend tests render it."""
    write = os.environ.get("A2UI_WRITE_FIXTURES") == "1"
    for tool, args in _golden_calls(db).items():
        monkeypatch.setattr(ui_tools, "new_panel_id", lambda tool=tool: f"jobs-{tool.replace('_', '-')}")
        result = _call(db, tool, args)
        assert result["ok"] is True, result
        fixture = {"tool": tool, "arguments": args, "result": result, "model_sees": json.loads(tool_content_for_llm(result))}
        text = json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
        path = FIXTURES / f"{tool}.json"
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        assert path.exists() and path.read_text(encoding="utf-8") == text, (
            f"{path.name} is out of date; regenerate with A2UI_WRITE_FIXTURES=1 (see this module's docstring)")
    # The decimals compare() rounds a change to; the frontend formats with the same ones.
    text = json.dumps(DECIMALS, indent=2) + "\n"
    path = FIXTURES / "decimals.json"
    if write:
        path.write_text(text, encoding="utf-8")
    assert path.exists() and path.read_text(encoding="utf-8") == text, (
        f"{path.name} is out of date; regenerate with A2UI_WRITE_FIXTURES=1 (see this module's docstring)")
