"""Schema Studio: evidence-backed suggestions, verification, and sample dry run."""
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.schemas.schema import SchemaField
from app.services import schema_studio as studio
from app.services.schema_studio import EvidenceProposal, FieldProposal

SAMPLE = (
    "บริษัท ตัวอย่าง จำกัด\n"
    "Invoice No: INV-202609\n"
    "Date: 24 Aug 2026\n"
    "\n"
    "| Item | Qty | Amount |\n"
    "| Pen | 2 | 50.00 |\n"
    "| Book | 1 | 1,200.00 |\n"
    "Total: 1,250.00\n"
)


def proposal(name, quote, type_="text", **extra):
    return FieldProposal(name=name, type=type_, description=extra.pop("description", f"The {name} printed on the invoice"),
                         evidence=EvidenceProposal(quote=quote), **extra)


def by_name(fields):
    return {field["name"]: field for field in fields}


def test_number_document_skips_blank_lines_and_reports_truncation():
    numbered, line_map, truncated = studio.number_document(SAMPLE)
    assert numbered.splitlines()[1] == "L2: Invoice No: INV-202609"
    assert line_map["L4"] == 5  # blank line 4 is skipped
    assert truncated is False
    _, _, truncated = studio.number_document(SAMPLE, budget=40)
    assert truncated is True


def test_verified_field_keeps_only_labels_and_pattern_that_reproduce_the_value():
    fields, dropped = studio.verify_proposals([
        proposal("invoice_no", "INV-202609", source_labels=["Invoice No", "Ref"], pattern=r"^INV-\d{6}$"),
    ], SAMPLE)
    field = fields[0]
    assert dropped == []
    assert field["studio"]["status"] == "verified"
    assert field["validation_rules"] == {"source_labels": ["Invoice No"], "pattern": r"^INV-\d{6}$"}
    assert field["studio"]["evidence"]["line_no"] == 2
    assert field["studio"]["confidence"] == 1.0


def test_value_not_in_document_is_not_found_with_low_confidence():
    fields, _ = studio.verify_proposals([proposal("po_number", "PO-999", source_labels=["PO"])], SAMPLE)
    field = fields[0]
    assert field["studio"]["status"] == "not_found"
    assert "validation_rules" not in field
    assert field["studio"]["confidence"] < 0.5


def test_type_mismatch_needs_review_and_bad_patterns_are_removed():
    fields, _ = studio.verify_proposals([
        proposal("quantity", "Pen", "number"),
        proposal("invoice_no", "INV-202609", pattern="(["),
        proposal("total", "1,250.00", "currency", pattern=r"^[\d,.]+$"),
    ], SAMPLE)
    named = by_name(fields)
    assert named["quantity"]["studio"]["status"] == "review"
    assert named["invoice_no"]["studio"]["status"] == "verified"
    assert "validation_rules" not in named["invoice_no"]
    assert any(c["key"] == "pattern" and c["ok"] is False for c in named["invoice_no"]["studio"]["checks"])
    # Mapping checks patterns on text values only, so a number field never keeps one.
    assert "validation_rules" not in named["total"]


def test_currency_with_symbol_reads_as_number():
    fields, _ = studio.verify_proposals([proposal("total", "1,250.00", "currency", source_labels=["Total"])], SAMPLE)
    assert fields[0]["studio"]["status"] == "verified"
    assert fields[0]["validation_rules"]["source_labels"] == ["Total"]


def test_repeated_value_needs_review():
    text = "Buyer: ACME\nShip to: ACME\n"
    fields, _ = studio.verify_proposals([proposal("buyer", "ACME", source_labels=["Buyer"])], text)
    assert fields[0]["studio"]["status"] == "review"
    assert fields[0]["studio"]["evidence"]["count"] == 2


def test_names_are_sanitised_and_deduplicated():
    fields, dropped = studio.verify_proposals([
        proposal("Invoice Number", "INV-202609"),
        proposal("invoice number", "24 Aug 2026", "date"),
    ], SAMPLE)
    assert [f["name"] for f in fields] == ["invoice_number", "invoice_number_2"]
    assert dropped == []


def test_fields_sharing_a_value_are_both_kept_for_review():
    text = "Subtotal: 1,000.00\nVAT: 0.00\nTotal due now 1,000.00 THB\n"
    fields, dropped = studio.verify_proposals([
        proposal("subtotal", "1,000.00", "currency"),
        proposal("total", "1,000.00", "currency"),
    ], text)
    assert dropped == [] and [f["name"] for f in fields] == ["subtotal", "total"]
    for field, other in zip(fields, ["total", "subtotal"]):
        assert field["studio"]["status"] == "review"
        assert any(c["key"] == "duplicate" and other in c["message"] for c in field["studio"]["checks"])


def test_table_becomes_text_mapped_array_config():
    fields, _ = studio.verify_proposals([
        proposal("line_items", "Pen | 2 | 50.00", "array",
                 columns=[{"name": "Item", "type": "text"}, {"name": "qty", "type": "number"},
                          {"name": "amount", "type": "currency"}, {"name": "qty", "type": "number"}]),
    ], SAMPLE)
    field = fields[0]
    assert field["studio"]["status"] in {"verified", "review"}
    assert field["array_config"]["columns"] == [
        {"name": "item", "type": "text"}, {"name": "qty", "type": "number"}, {"name": "amount", "type": "currency"}]
    SchemaField.model_validate(field)  # a text-mapped table is a valid schema field


def test_table_row_evidence_tolerates_reformatted_rows():
    fields, _ = studio.verify_proposals([
        proposal("line_items", "Book  1  1,200.00", "array", columns=[{"name": "item", "type": "text"}]),
    ], SAMPLE)
    assert fields[0]["studio"]["status"] == "review"
    assert fields[0]["studio"]["evidence"]["line_no"] == 7


def test_confidence_orders_statuses():
    fields, _ = studio.verify_proposals([
        proposal("invoice_no", "INV-202609", source_labels=["Invoice No"]),
        proposal("quantity", "Pen", "number"),
        proposal("po_number", "PO-999"),
    ], SAMPLE)
    scores = [f["studio"]["confidence"] for f in fields]
    assert scores == sorted(scores, reverse=True) and len(set(scores)) == 3
    assert studio.summarize(fields) == {"total": 3, "verified": 1, "review": 1, "not_found": 1}


def test_parse_proposals_drops_invalid_fields_and_rejects_bad_envelope():
    proposals, dropped = studio.parse_proposals(
        '```json\n{"fields": [{"name": "a", "evidence": {"quote": "x"}}, {"label": "no name"}]}\n```')
    assert [p.name for p in proposals] == ["a"] and len(dropped) == 1
    with pytest.raises(ValueError):
        studio.parse_proposals('{"items": []}')


def test_array_columns_without_positions_are_valid_but_locator_arrays_need_them():
    SchemaField.model_validate({"name": "rows", "type": "array",
                                "array_config": {"row_detection": "line", "columns": [{"name": "qty", "type": "number"}]}})
    with pytest.raises(ValidationError):
        SchemaField.model_validate({"name": "rows", "type": "array", "array_config": {
            "row_detection": "line", "columns": [{"name": "qty", "x": 0, "width": 50}, {"name": "item"}]}})
    with pytest.raises(ValidationError):
        SchemaField.model_validate({
            "name": "rows", "type": "array",
            "locator": {"page": 1, "x": 1, "y": 1, "width": 50, "height": 20},
            "array_config": {"row_detection": "line", "columns": [{"name": "qty"}]}})


class _FakeClient:
    """AsyncOpenAI double: rejects strict json_schema like many local servers do."""

    calls: list = []
    replies: list = []

    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def create(self, **kwargs):
        import openai
        _FakeClient.calls.append(kwargs.get("response_format"))
        if (kwargs.get("response_format") or {}).get("type") == "json_schema":
            request = httpx.Request("POST", "http://llm.test/v1/chat/completions")
            raise openai.BadRequestError("response_format not supported",
                                         response=httpx.Response(400, request=request), body=None)
        content = _FakeClient.replies.pop(0)
        finish = "length" if content == "<truncated>" else "stop"
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))])


@pytest.fixture
def fake_openai(monkeypatch):
    import openai
    _FakeClient.calls, _FakeClient.replies = [], []
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)
    return _FakeClient


PROVIDER = SimpleNamespace(api_key="k", api_url="http://llm.test/v1", model="m")


@pytest.mark.asyncio
async def test_request_falls_back_from_strict_schema_to_json_mode(fake_openai):
    fake_openai.replies = ['{"fields": [{"name": "invoice_no", "evidence": {"quote": "INV-202609"}}]}']
    proposals, meta = await studio.request_proposals(PROVIDER, "L1: x", "invoice", False)
    assert [p.name for p in proposals] == ["invoice_no"]
    assert meta["structured_output"] == "json_object"
    assert fake_openai.calls[0]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_request_repairs_invalid_json_once_then_fails_clearly(fake_openai):
    fake_openai.replies = ["not json", '{"fields": [{"name": "total"}]}']
    proposals, meta = await studio.request_proposals(PROVIDER, "L1: x", None, False)
    assert meta["repaired"] is True and proposals[0].name == "total"

    fake_openai.replies = ["not json", "still not json"]
    with pytest.raises(ValueError, match="did not return valid field suggestions"):
        await studio.request_proposals(PROVIDER, "L1: x", None, False)


ADMIN = SimpleNamespace(id="u1", role="admin", is_superuser=True)
DRAFT_FIELDS = [
    {"name": "invoice_no", "type": "text", "validation_rules": {"source_labels": ["Invoice No"]}},
    {"name": "total", "type": "currency"},
]


def test_dry_run_queues_a_background_run_for_every_cached_sample(monkeypatch):
    from app.api.v1.endpoints import schemas as ep
    from app.tasks import schema_studio_tasks as tasks

    monkeypatch.setattr(studio, "load_samples", lambda user_id, session_id: [
        {"filename": "a.pdf", "text": SAMPLE}, {"filename": "b.pdf", "text": "Invoice No: INV-2"}])
    queued = {}
    monkeypatch.setattr(tasks.run_schema_samples_task, "delay", lambda *args: queued.update(args=args))
    fake = _FakeRedis()
    monkeypatch.setattr(studio, "_redis_client", lambda: fake)
    out = ep.dry_run_schema_on_samples(
        payload=ep.SampleDryRunRequest(session_id="a" * 32, fields=DRAFT_FIELDS), current_user=ADMIN)
    user_id, run_id, samples, fields, engine, schema_id, schema_version = queued["args"]
    assert out == {"run_id": run_id, "total": 2}
    # The run is visible as queued before a worker picks it up.
    assert ep.read_sample_run(run_id, current_user=ADMIN)["status"] == "queued"
    assert [s["filename"] for s in samples] == ["a.pdf", "b.pdf"] and samples[1]["index"] == 1
    assert fields[0]["validation_rules"] == {"source_labels": ["Invoice No"]}
    assert (user_id, engine, schema_id) == ("u1", None, None)


def test_dry_run_reports_expired_samples(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import schemas as ep

    monkeypatch.setattr(studio, "load_samples", lambda user_id, session_id: None)
    with pytest.raises(HTTPException) as exc:
        ep.dry_run_schema_on_samples(
            payload=ep.SampleDryRunRequest(session_id="b" * 32, fields=[{"name": "x", "type": "text"}]),
            current_user=ADMIN)
    assert exc.value.status_code == 404 and "expired" in exc.value.detail


def test_session_ids_are_validated_before_redis_lookup():
    assert studio.load_samples("u1", "../../etc") is None


class _FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, ex=None):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def close(self):
        pass


def test_background_run_maps_each_sample_and_scores_confirmed_values(monkeypatch):
    import json
    import redis
    from app.tasks import schema_studio_tasks as tasks

    fake = _FakeRedis()
    monkeypatch.setattr(redis, "from_url", lambda *a, **k: fake)

    def fake_map_one(text, fields, engine):
        value = "INV-202609" if "INV-202609" in text else None
        return {"values": {"invoice_no": value} if value else {},
                "report": {"status": "completed" if value else "failed", "fields": {}}}

    monkeypatch.setattr(tasks, "_map_one", fake_map_one)
    tasks.run_schema_samples_task.run("u1", "r1", [
        {"index": 0, "filename": "a.pdf", "text": SAMPLE, "expected": {"invoice_no": "inv-202609 "}},
        {"index": 1, "filename": "b.pdf", "text": "nothing here", "expected": {"invoice_no": "INV-9"}},
    ], DRAFT_FIELDS, None)
    state = json.loads(fake.data[tasks.run_key("u1", "r1")])
    assert state["status"] == "completed" and state["done"] == 2
    assert [s["comparison"]["matched"] for s in state["samples"]] == [1, 0]


def test_values_match_compares_numbers_text_and_tables():
    assert studio.values_match(9319998.82, "9,319,998.82")
    assert studio.values_match("  ACME  Co ", "acme co")
    assert not studio.values_match("100", "1000")
    assert studio.values_match([{"qty": 1}], [{"qty": 1}])
    assert not studio.values_match("x", None)


MULTI = [
    "Invoice No: INV-1\nTotal: 100.00\nPO: PO-7\n",
    "Invoice No: INV-2\nTotal: 250.00\n",
    "Invoice No: INV-3\nTotal: 90.00\n",
]


def test_multi_sample_presence_sets_required_and_optional():
    fields, _ = studio.verify_proposals([
        FieldProposal(name="invoice_no", description="Invoice number after 'Invoice No'",
                      source_labels=["Invoice No"], pattern=r"^INV-\d+$",
                      evidence=[{"sample": "S1", "quote": "INV-1"}, {"sample": "S2", "quote": "INV-2"},
                                {"sample": "S3", "quote": "INV-3"}]),
        FieldProposal(name="po_number", description="Purchase order number after 'PO'",
                      source_labels=["PO"], evidence=[{"sample": "S1", "quote": "PO-7"}]),
    ], MULTI)
    named = by_name(fields)
    assert named["invoice_no"]["studio"]["status"] == "verified"
    assert named["invoice_no"]["studio"]["presence"] == {"found": 3, "total": 3}
    assert named["invoice_no"]["required"] is True
    assert named["invoice_no"]["validation_rules"] == {"source_labels": ["Invoice No"], "pattern": r"^INV-\d+$"}
    assert named["po_number"]["studio"]["status"] == "review"
    assert named["po_number"]["required"] is False
    assert "Found in 1 of 3 samples" in named["po_number"]["studio"]["checks"][0]["message"]
    assert named["invoice_no"]["studio"]["confidence"] > named["po_number"]["studio"]["confidence"]


def test_label_is_kept_only_when_it_works_in_every_sample():
    texts = ["Total: 100.00\n", "Grand Total 250.00\n"]
    fields, _ = studio.verify_proposals([
        FieldProposal(name="total", type="currency", source_labels=["Total"],
                      evidence=[{"sample": "S1", "quote": "100.00"}, {"sample": "S2", "quote": "250.00"}]),
    ], texts)
    assert "validation_rules" not in fields[0]


def test_number_samples_splits_budget_and_labels_each_sample():
    prompt, truncated = studio.number_samples(
        [{"filename": "a.pdf", "text": "x\n" * 5}, {"filename": "b.pdf", "text": "long line\n" * 5000}], budget=8000)
    assert "=== Sample S1: a.pdf ===" in prompt and "=== Sample S2: b.pdf ===" in prompt
    assert truncated == [False, True]


def test_table_row_matches_when_pdf_merges_a_column_into_one_cell():
    text = "|ข้อ ๑ ๒|รายการ ระบบแพลตฟอร์ม Data Lakehouse ระบบฝึก|หน่วย ระบบ ชุด|จำนวน 1 2|ราคา 429,176.00 12.00|\n"
    fields, _ = studio.verify_proposals([
        proposal("line_items", "๑ ระบบแพลตฟอร์ม Data Lakehouse ระบบ 1 429,176.00", "array",
                 columns=[{"name": "item_no", "type": "text"}, {"name": "amount", "type": "currency"}]),
    ], text)
    assert fields[0]["studio"]["status"] == "review"
    assert fields[0]["studio"]["evidence"]["partial"] is True


@pytest.mark.asyncio
async def test_truncated_answer_reports_output_limit_instead_of_repairing(fake_openai):
    fake_openai.replies = ["<truncated>"]
    with pytest.raises(ValueError, match="ran out of output space"):
        await studio.request_proposals(PROVIDER, "L1: x", None, False)
    assert fake_openai.calls[-1]["type"] == "json_object"


def test_invalid_format_rule_is_rejected_on_save_and_degrades_one_field_in_mapping(monkeypatch):
    from app.schemas.schema import DocumentSchemaCreate
    from app.services import field_mapping as mapping

    with pytest.raises(ValidationError, match="not a valid regular expression"):
        DocumentSchemaCreate(name="s", document_type="invoice", fields=[
            {"name": "invoice_no", "type": "text", "validation_rules": {"pattern": r"^INV-(\d+"}}])

    # Schemas saved before this check (or imported) must not abort mapping.
    fields = [{"name": "invoice_no", "type": "text",
               "validation_rules": {"source_labels": ["Invoice No"], "pattern": r"^INV-(\d+"}},
              {"name": "total", "type": "text", "validation_rules": {"source_labels": ["Total"]}}]
    def offline(*args, **kwargs):
        raise TimeoutError("remote engines are not used in this test")

    for provider in ("extract_structure", "jev_mapping", "llm_mapping"):
        monkeypatch.setattr(mapping, provider, offline)
    values, report = mapping.map_fields(SAMPLE, SimpleNamespace(name="s", fields=fields), None, engine="auto")
    assert values == {"total": "1,250.00"}
    assert report["fields"]["invoice_no"]["status"] == "needs_review"
    assert "invalid format rule" in report["fields"]["invoice_no"]["reason"]


def test_dry_run_request_rejects_invalid_format_rule():
    from app.api.v1.endpoints import schemas as ep
    with pytest.raises(ValidationError, match="not a valid regular expression"):
        ep.SampleDryRunRequest(session_id="a" * 32, fields=[
            {"name": "invoice_no", "type": "text", "validation_rules": {"pattern": "(["}}])


def test_unknown_or_expired_run_is_not_reported_as_queued(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import schemas as ep

    monkeypatch.setattr(studio, "_redis_client", lambda: _FakeRedis())
    with pytest.raises(HTTPException) as exc:
        ep.read_sample_run("c" * 32, current_user=ADMIN)
    assert exc.value.status_code == 404 and "expired" in exc.value.detail


@pytest.mark.parametrize("quote,text,found", [
    ("100", "Total 1000", False),
    ("100", "Ref INV-1005", False),
    ("100", "Paid 100.50", False),
    ("100", "Qty: 100.", True),
    ("1,250.00", "Total: 11,250.00", False),
    ("ดีทวิน", "บริษัทดีทวินจำกัด", True),
    ("(สำนักงานใหญ่)", "จำกัด (สำนักงานใหญ่)", True),
    ("1,250.00", "Total 1,250.00THB", True),
    ("1,250.00", "THB1,250.00", True),
    ("12", "weight 12kg", True),
    ("INV-20", "XINV-20", False),
])
def test_quote_must_not_be_part_of_a_longer_token(quote, text, found):
    assert (studio.locate_quote(quote, text)["match"] != "none") is found


@pytest.mark.parametrize("quote,field_type,ok", [
    ("INV-001", "number", False),
    ("12/08/2026", "number", False),
    ("฿1,250.00", "currency", True),
    ("1,250.00 บาท", "currency", True),
    ("7.0%", "number", True),
    ("๑๐๐,๐๐๐ บาท", "currency", True),
    ("THB1,250.00", "currency", True),
    ("1,250.00THB", "currency", True),
    ("1,250.-", "currency", True),
    ("(1,250.00)", "currency", True),
    ("1,250.00-", "currency", True),
    ("1 250.00", "number", True),
])
def test_number_check_accepts_currency_marks_but_not_other_text(quote, field_type, ok):
    assert studio._type_check(quote, field_type, "f")[0] is ok


def test_confirmed_values_for_removed_fields_are_ignored_not_failed():
    result = studio.compare_with_expected({"invoice_no": "INV-1", "old_name": "x"}, {"invoice_no": "INV-1"},
                                          {"invoice_no"})
    assert (result["checked"], result["matched"], result["ignored"]) == (1, 1, ["old_name"])


def test_accounting_negatives_read_as_negative_numbers():
    assert studio._normalize_amount("(1,250.00)") == "-1,250.00"
    assert studio._normalize_amount("1,250.00-") == "-1,250.00"
    assert studio._type_check("(1,250.00)", "currency", "total") == (True, "Reads as currency: -1250.0")


def test_suggestion_task_stores_result_or_readable_error(monkeypatch):
    import json
    import redis
    from app.tasks import schema_studio_tasks as tasks

    fake = _FakeRedis()
    monkeypatch.setattr(redis, "from_url", lambda *a, **k: fake)
    monkeypatch.setattr(studio, "load_samples", lambda user_id, session_id: [{"filename": "a.pdf", "text": SAMPLE}])
    monkeypatch.setattr(tasks, "SessionLocal", lambda: SimpleNamespace(__enter__=None))

    class Session:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(tasks, "SessionLocal", Session)

    async def ok(db, samples, document_type):
        return {"suggested_fields": [{"name": "invoice_no"}], "summary": {"total": 1}, "raw_result": {}}

    monkeypatch.setattr(studio, "suggest_fields", ok)
    tasks.suggest_schema_task.run("u1", "r1", "s" * 32, "invoice", [{"filename": "a.pdf"}])
    state = json.loads(fake.data[tasks.run_key("u1", "r1")])
    assert state["status"] == "completed" and state["result"]["suggested_fields"][0]["name"] == "invoice_no"
    assert state["result"]["raw_result"]["extraction"] == [{"filename": "a.pdf"}]

    async def no_provider(db, samples, document_type):
        raise ValueError("No active AI provider configured.")

    monkeypatch.setattr(studio, "suggest_fields", no_provider)
    tasks.suggest_schema_task.run("u1", "r2", "s" * 32)
    assert json.loads(fake.data[tasks.run_key("u1", "r2")])["error"] == "No active AI provider configured."

    async def crash(db, samples, document_type):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(studio, "suggest_fields", crash)
    tasks.suggest_schema_task.run("u1", "r3", "s" * 32)
    state = json.loads(fake.data[tasks.run_key("u1", "r3")])
    assert state["status"] == "failed" and "socket" not in state["error"]


def test_suggest_endpoint_only_stores_the_files_and_queues_reading(monkeypatch):
    import asyncio
    from io import BytesIO
    from fastapi import UploadFile
    from starlette.datastructures import Headers
    from app.api.v1.endpoints import schemas as ep
    from app.tasks import schema_studio_tasks as tasks

    class Storage:
        def __init__(self):
            self.files = {}

        def upload_file(self, file_obj, path, content_type=None):
            self.files[path] = file_obj.read()

    storage = Storage()
    monkeypatch.setattr("app.services.storage.get_storage_service", lambda: storage)
    fake = _FakeRedis()
    monkeypatch.setattr(studio, "_redis_client", lambda: fake)
    queued = {}
    monkeypatch.setattr(tasks.extract_and_suggest_task, "delay", lambda *args: queued.update(args=args))
    upload = UploadFile(file=BytesIO(b"%PDF-1.4"), filename="a.pdf", headers=Headers({"content-type": "application/pdf"}))
    out = asyncio.run(ep.suggest_schema_from_file(files=[upload], file=None, document_type="invoice", current_user=ADMIN))

    path = f"schema-suggest-tmp/{out['run_id']}/0.pdf"
    assert storage.files == {path: b"%PDF-1.4"}
    assert queued["args"][1:] == (out["run_id"], [{"path": path, "filename": "a.pdf"}], "invoice")
    state = ep.read_sample_run(out["run_id"], current_user=ADMIN)
    assert (state["status"], state["stage"], state["total"]) == ("queued", "reading", 1)


def test_reading_task_caches_samples_then_runs_the_ai_step(monkeypatch):
    import json
    import redis
    from contextlib import contextmanager
    from app.tasks import schema_studio_tasks as tasks
    from app.tasks import maintenance_tasks

    fake = _FakeRedis()
    monkeypatch.setattr(redis, "from_url", lambda *a, **k: fake)

    class Storage:
        @contextmanager
        def get_local_path(self, path):
            yield "/tmp/" + path.rsplit("/", 1)[-1]

    monkeypatch.setattr("app.services.storage.get_storage_service", lambda: Storage())
    deleted = []
    monkeypatch.setattr(maintenance_tasks, "delete_schema_sample_files", lambda paths: deleted.extend(paths))
    monkeypatch.setattr(tasks, "_extract_file", lambda storage, item: SimpleNamespace(
        markdown=SAMPLE, metadata={"pipeline": "anydoc_hybrid", "text_layer_thai_suspect_pages": [1]}))
    monkeypatch.setattr(studio, "store_samples", lambda user_id, samples: "d" * 32)
    handed_over = {}
    monkeypatch.setattr(tasks.suggest_schema_task, "delay", lambda *args: handed_over.update(args=args))

    tasks.extract_and_suggest_task.run("u1", "r1", [{"path": "schema-suggest-tmp/r1/0.pdf", "filename": "a.pdf"}], "invoice")

    state = json.loads(fake.data[tasks.run_key("u1", "r1")])
    assert (state["stage"], state["session_id"], state["done"]) == ("suggesting", "d" * 32, 1)
    assert state["samples"][0]["filename"] == "a.pdf" and state["samples"][0]["garbled_pages"] == [1]
    assert handed_over["args"][:4] == ("u1", "r1", "d" * 32, "invoice")
    assert deleted == ["schema-suggest-tmp/r1/0.pdf"]

    monkeypatch.setattr(tasks, "_extract_file", lambda storage, item: SimpleNamespace(markdown=" ", metadata={}))
    tasks.extract_and_suggest_task.run("u1", "r2", [{"path": "p/0.pdf", "filename": "scan.pdf"}], None)
    failed = json.loads(fake.data[tasks.run_key("u1", "r2")])
    assert failed["status"] == "failed" and "scan.pdf" in failed["error"]
    assert "p/0.pdf" in deleted


GARBLED = ("บร ิษัท ดีทวิน จํากัด ภาษีมูลค่าเพิMม รวมทัeงสิeน เงืdอนไขการชําระเงิน ค่าใช้จ่ายอืMนๆ "
           "เพืAอช่วยในการทํางาน และเชืAอมต่อกับระบบอืAนๆ ข ้อมูลขนาดใหญ่ ") * 2
CLEAN = ("บริษัท ดีทวิน จำกัด ภาษีมูลค่าเพิ่ม รวมทั้งสิ้น เงื่อนไขการชำระเงิน ค่าใช้จ่ายอื่นๆ "
         "เพื่อช่วยในการทำงาน และเชื่อมต่อกับระบบ AI ของ Softnix OCR ขนาดใหญ่ ") * 2


def test_thai_font_mapping_is_reported_without_rerouting_by_default(monkeypatch):
    from app.core.config import settings
    from app.services.anydoc_pipeline import _text_layer_quality

    monkeypatch.setattr(settings, "TEXT_LAYER_THAI_REPAIR", False)
    garbled = _text_layer_quality(GARBLED)
    assert garbled["thai"]["suspect"] is True
    assert garbled["warnings"] == ["thai_font_mapping"] and garbled["reasons"] == [] and garbled["usable"] is True
    clean = _text_layer_quality(CLEAN)
    assert clean["thai"]["suspect"] is False and clean["warnings"] == []

    monkeypatch.setattr(settings, "TEXT_LAYER_THAI_REPAIR", True)
    repaired = _text_layer_quality(GARBLED)
    assert repaired["reasons"] == ["thai_font_mapping"] and repaired["usable"] is False
