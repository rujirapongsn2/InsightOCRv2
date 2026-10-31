"""render_ui analytics: Metric, DataTable, Chart and RiskList values are bounded, cited ids are
job-scoped, and risk quotes are checked against the document's text by the server."""
import asyncio
import importlib
import json
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


from app.agent.a2ui import CATALOG_ID, quote_found
from app.agent.context import tool_content_for_llm
from app.agent.tools.ui_tools import _render_ui_handler
from app.models.document import Document

JOB = uuid.uuid4()
OTHER_JOB = uuid.uuid4()
CONTRACT_TEXT = ("สัญญาจ้างบริการ ข้อ 7 ค่าปรับ\nหากผู้รับจ้างส่งมอบงานล่าช้า ผู้รับจ้างต้องชำระค่าปรับ"
                 "  ในอัตราร้อยละ 0.5\nของมูลค่างานต่อวัน ข้อ 9 สัญญานี้ต่ออายุโดยอัตโนมัติทุกปี")


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Document.metadata.create_all(engine, tables=[Document.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _doc(db, job_id, filename, ocr_text=None):
    doc = Document(id=uuid.uuid4(), job_id=job_id, filename=filename, file_path="x",
                   status="extraction_completed", ocr_text=ocr_text)
    db.add(doc)
    db.commit()
    return str(doc.id)


def _render(db, components, data):
    context = SimpleNamespace(db=db, job_id=JOB, user_id=uuid.uuid4())
    return asyncio.run(_render_ui_handler({"components": components, "data": data}, context))


def _root(*children):
    return {"id": "root", "component": "Column", "children": list(children)}


def _model(result):
    return result["a2ui"][2]["updateDataModel"]["value"]


def _fails(result, expected):
    assert result["ok"] is False, result
    assert result["error"].startswith("render_ui was not shown")
    assert expected in result["error"], result["error"]


METRICS = [
    _root("tiles"),
    {"id": "tiles", "component": "Row", "children": ["total", "count"]},
    {"id": "total", "component": "Metric", "label": "ยอดรวม", "value": {"path": "/total"}, "format": "currency",
     "unit": "บาท", "delta": {"value": 12000, "direction": "up", "sentiment": "bad", "label": "เทียบเดือนก่อน"}},
    {"id": "count", "component": "Metric", "label": "จำนวนใบแจ้งหนี้", "value": 42},
]
TABLE_COLUMNS = [
    {"key": "vendor", "label": "ผู้ขาย", "type": "text"},
    {"key": "amount", "label": "ยอด", "type": "currency"},
    {"key": "share", "label": "สัดส่วน", "type": "percent"},
    {"key": "due", "label": "ครบกำหนด", "type": "date"},
    {"key": "change", "label": "เปลี่ยนแปลง", "type": "delta"},
    {"key": "risk", "label": "ความเสี่ยง", "type": "risk"},
]


def _table(rows, columns=TABLE_COLUMNS):
    return [_root("table"), {"id": "table", "component": "DataTable", "columns": columns,
                             "rows": {"path": "/rows"}, "caption": "เทียบผู้ขาย"}], {"rows": rows}


def _row(**overrides):
    row = {"vendor": "ACME", "amount": 1500.5, "share": 12.5, "due": "2026-11-30",
           "change": {"value": -3, "direction": "down", "sentiment": "good"}, "risk": "low"}
    row.update(overrides)
    return row


def _chart(points, series=None, chart_type="bar"):
    series = series or [{"key": "amount", "label": "ยอด"}]
    return [_root("chart"), {"id": "chart", "component": "Chart", "type": chart_type, "title": "ยอดตามผู้ขาย",
                             "x": "vendor", "series": series, "data": {"path": "/points"}, "format": "currency"}], \
        {"points": points}


def _risks(items):
    return [_root("risks"), {"id": "risks", "component": "RiskList", "title": "ความเสี่ยงของสัญญา",
                             "items": {"path": "/risks"}}], {"risks": items}


def _risk(doc_id, **overrides):
    item = {"title": "ค่าปรับล่าช้าสูง", "level": "high", "category": "ค่าปรับ",
            "description": "ค่าปรับรายวันไม่มีเพดาน", "quote": "ผู้รับจ้างต้องชำระค่าปรับ ในอัตราร้อยละ 0.5 ของมูลค่างานต่อวัน",
            "document_id": doc_id, "page": 3, "recommendation": "เจรจาเพดานค่าปรับไม่เกินร้อยละ 10"}
    item.update(overrides)
    return item


def test_metrics_in_a_row_yield_v09_messages(db):
    result = _render(db, METRICS, {"total": 1_250_000.75})
    assert result["ok"] is True, result
    create, update, model = result["a2ui"]
    assert all(m["version"] == "v0.9" for m in result["a2ui"])
    assert create["createSurface"]["catalogId"] == CATALOG_ID
    assert [c["component"] for c in update["updateComponents"]["components"]] == ["Column", "Row", "Metric", "Metric"]
    assert model["updateDataModel"]["value"] == {"total": 1_250_000.75}
    assert result["components"] == {"Metric": 2}


def test_table_and_chart_render_and_cited_ids_are_canonical(db):
    doc_id = _doc(db, JOB, "inv.pdf")
    components, data = _table([_row(document_id=doc_id.upper()), _row(vendor="Beta", amount=None)])
    table = _render(db, components, data)
    assert table["ok"] is True, table
    assert [row.get("document_id") for row in _model(table)["rows"]] == [doc_id, None]
    assert "quote_verified" not in json.dumps(_model(table))

    components, data = _chart([{"vendor": "ACME", "amount": 10}, {"vendor": "Beta", "amount": None}])
    chart = _render(db, components, data)
    assert chart["ok"] is True, chart
    assert chart["components"] == {"Chart": 1}


def test_risk_badge_alone_is_valid(db):
    result = _render(db, [_root("badge"), {"id": "badge", "component": "RiskBadge", "level": "critical"}], {})
    assert result["ok"] is True, result


@pytest.mark.parametrize(("build", "expected"), [
    (lambda: (METRICS[:3] + [{**METRICS[3], "format": "money"}], {"total": 1}),
     "\"format\" must be one of ['number', 'currency', 'percent']"),
    (lambda: (METRICS[:2] + [{**METRICS[2], "delta": {"value": 1, "direction": "up", "sentiment": "great"}}, METRICS[3]],
              {"total": 1}),
     "\"delta\".sentiment must be one of ['good', 'bad', 'neutral']"),
    (lambda: (METRICS[:2] + [{**METRICS[2], "delta": {"value": 5, "direction": "down", "sentiment": "good"}}, METRICS[3]],
              {"total": 1}),
     'direction "down" contradicts value 5'),
    (lambda: (METRICS, {"total": float("nan")}), 'data "/total" is shown by a Metric and must be a finite number'),
    (lambda: (METRICS, {"total": "1,200"}), 'data "/total" is shown by a Metric and must be a finite number'),
    (lambda: (METRICS[:3] + [{**METRICS[3], "value": float("inf")}], {"total": 1}),
     '"value" must be a finite number'),
    (lambda: _table([_row(amount=float("inf"))]), 'data "/rows/0/amount" must be a finite number'),
    (lambda: _table([_row(amount=True)]), 'data "/rows/0/amount" must be a finite number'),
    (lambda: _table([_row(risk="severe")]), "data \"/rows/0/risk\" must be one of ['critical', 'high', 'medium', 'low']"),
    (lambda: _table([_row(due="30/11/2026")]), 'data "/rows/0/due" must be a date "YYYY-MM-DD"'),
    (lambda: _table([_row(change={"value": 1, "direction": "sideways", "sentiment": "good"})]),
     "data \"/rows/0/change\".direction must be one of ['up', 'down', 'flat']"),
    (lambda: _table([_row(extra="x")]), "data \"/rows/0\" has keys ['extra'] that are not columns"),
    (lambda: _table([_row()] * 501), 'data "/rows" has 501 rows; the limit is 500'),
    (lambda: _table([_row()], TABLE_COLUMNS + [{"key": "x", "label": "x", "type": "money"}]),
     '"columns"[6].type must be one of'),
    (lambda: _table([_row()], [{"key": f"c{i}", "label": "c", "type": "text"} for i in range(13)]),
     '"columns" must be an array of 1 to 12 columns'),
    (lambda: _chart([{"vendor": "A", **{f"s{i}": 1 for i in range(9)}}],
                    [{"key": f"s{i}", "label": f"s{i}"} for i in range(9)]),
     '"series" must be an array of 1 to 8 series'),
    (lambda: _chart([{"vendor": str(i), "amount": i} for i in range(201)]), 'data "/points" has 201 points; the limit is 200'),
    (lambda: _chart([{"vendor": "A", "amount": float("-inf")}]), 'data "/points/0/amount" must be a finite number'),
    (lambda: _chart([{"vendor": "A", "amount": 1, "document_id": str(uuid.uuid4())}]),
     "a point holds only \"vendor\" and the series keys ['amount']"),
    (lambda: _chart([{"vendor": "A", "amount": 1}], chart_type="pie"), "\"type\" must be one of ['bar', 'line']"),
    (lambda: _risks([_risk(str(uuid.uuid4()), level="severe")]),
     "data \"/risks/0/level\" must be one of ['critical', 'high', 'medium', 'low']"),
    (lambda: _risks([_risk(str(uuid.uuid4()), quote_verified=True)]),
     'data "/risks/0/quote_verified" is set by the system'),
    (lambda: _risks([{k: v for k, v in _risk("x").items() if k != "document_id"}]),
     'data "/risks/0" has a quote but no document_id'),
    (lambda: _risks([_risk(str(uuid.uuid4()))] * 51), 'data "/risks" has 51 risk items; the limit is 50'),
    (lambda: ([_root("badge"), {"id": "badge", "component": "RiskBadge", "level": "urgent"}], {}),
     "\"level\" must be one of ['critical', 'high', 'medium', 'low']"),
])
def test_invalid_analytics_are_corrective_errors(db, build, expected):
    components, data = build()
    _fails(_render(db, components, data), expected)


def test_analytics_data_holds_only_what_components_bind_to(db):
    _fails(_render(db, METRICS, {"total": 1, "raw_rows": [1, 2, 3]}), 'data "/raw_rows" is not used by any component')
    components, data = _table([_row()])
    _fails(_render(db, components, {**data, "notes": "x"}), 'data "/notes" is not used by any component')
    bound_through_array = [_root("table"), {**components[1], "rows": {"path": "/groups/0/rows"}}]
    _fails(_render(db, bound_through_array, {"groups": [{"rows": [_row()]}]}),
           'pointer "/groups/0/rows" must lead through objects only')


def test_foreign_or_unknown_cited_document_ids_reject_the_surface(db):
    own = _doc(db, JOB, "own.pdf", CONTRACT_TEXT)
    foreign = _doc(db, OTHER_JOB, "other.pdf", CONTRACT_TEXT)
    unknown = str(uuid.uuid4())

    risks = _render(db, *_risks([_risk(own), _risk(foreign)]))
    _fails(risks, f"not documents of this job: ['{foreign}']")
    assert "other.pdf" not in json.dumps(risks)

    _fails(_render(db, *_table([_row(document_id=unknown)])), f"not documents of this job: ['{unknown}']")
    _fails(_render(db, *_table([_row(document_id="not-a-uuid")])), "not-a-uuid")


def test_quotes_are_verified_against_the_document_text(db):
    contract = _doc(db, JOB, "contract.pdf", CONTRACT_TEXT)
    no_text = _doc(db, JOB, "scan.pdf", None)
    result = _render(db, *_risks([
        _risk(contract),  # spacing and line breaks differ from the OCR text
        _risk(contract, level="critical", title="ต่ออายุอัตโนมัติ", quote="สัญญานี้ต่ออายุโดยอัตโนมัติทุกปี"),
        _risk(contract, level="medium", title="แต่งขึ้น", quote="ผู้ว่าจ้างรับผิดไม่จำกัดจำนวน"),
        _risk(no_text, level="low", title="ไม่มีข้อความ", quote="สัญญานี้ต่ออายุ"),
        {k: v for k, v in _risk(contract, level="low", title="ไม่มีข้อตกลงรักษาความลับ").items() if k != "quote"},
    ]))
    assert result["ok"] is True, result
    items = _model(result)["risks"]
    assert [item.get("quote_verified") for item in items] == [True, True, False, False, None]
    assert result["risks"] == {"critical": 1, "high": 1, "medium": 1, "low": 2}
    assert result["quotes"] == 4 and result["unverified_quotes"] == 2

    seen = json.loads(tool_content_for_llm(result))
    assert seen == {"ok": True, "surface_id": result["surface_id"], "document_count": 0,
                    "components": {"RiskList": 1}, "risks": result["risks"], "quotes": 4, "unverified_quotes": 2}


def test_quote_found_uses_the_document_search_normalization():
    assert quote_found("ร้อยละ 0.5 ของมูลค่างาน", "ในอัตราร้อยละ 0.5\nของ มูลค่างาน ต่อวัน")
    assert quote_found("ชำระภายใน 30 วัน", "ผู้ซื้อต้องชำระภายใน ๓๐ วัน นับจาก")
    assert quote_found("ชำระภายใน ๓๐ วัน", "ผู้ซื้อต้องชำระภายใน 30 วัน นับจาก")
    assert quote_found("abc def", "xx ABC\tDEF yy")
    assert quote_found("ค่าปรับร้อยละ", "ค่า ปรับ ร้อย ละ")
    assert not quote_found("ร้อยละ 5 ของมูลค่างาน", "ในอัตราร้อยละ 0.5 ของมูลค่างาน")
    assert not quote_found("ชำระภายใน 60 วัน", "ผู้ซื้อต้องชำระภายใน ๓๐ วัน")
    assert not quote_found("   ", "anything")
    assert not quote_found("abc", None)
