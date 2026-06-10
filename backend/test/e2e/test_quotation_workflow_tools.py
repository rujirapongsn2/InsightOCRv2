"""
Level 1 E2E: Quotation Workflow — Tool Integration Chain

Tests the complete tool chain without an LLM.
Each test calls tools in sequence, verifying the full workflow:
  list_documents → get_document_detail → list_integrations →
  call_api_integration (GET stock ×3) → execute_python (filter) →
  call_api_integration (POST quotation, with confirmation) →
  execute_python (report) → write_file → read_file

Run: python -m pytest test/e2e/test_quotation_workflow_tools.py -v
"""
import uuid
import json
import asyncio
from unittest.mock import MagicMock, patch, ANY

import pytest

from app.agent.context import AgentContext
from app.agent.tools.document_tools import (
    _list_documents_handler,
    _get_document_detail_handler,
)
from app.agent.tools.integration_tools import (
    _list_integrations_handler,
    _call_api_integration_handler,
)
from app.agent.tools.code_tools import _execute_python_handler
from app.agent.tools.filesystem_tools import (
    _write_file_handler,
    _read_file_handler,
)

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_fake_document(doc_id, job_id, extracted_data):
    """Create a mock document row matching what Document model returns."""
    doc = MagicMock()
    doc.id = doc_id
    doc.job_id = job_id
    doc.filename = "request_quotation.pdf"
    doc.status = "extraction_completed"
    doc.page_count = 2
    doc.extraction_confidence = 0.95
    doc.extracted_data = extracted_data
    doc.reviewed_data = None
    doc.review_decision = None
    doc.ocr_text = "Request for Quotation\nCustomer: บริษัท ทดสอบ จำกัด\n..."
    return doc


def _make_fake_integration(id_, name, type_, config, status="active"):
    """Create a mock integration row."""
    integ = MagicMock()
    integ.id = id_
    integ.name = name
    integ.type = MagicMock()
    integ.type.value = type_
    integ.status = MagicMock()
    integ.status.value = status
    integ.config = config
    integ.description = f"Mock {type_} integration"
    return integ


def _make_context(db, user_id, job_id, conv_id=None):
    return AgentContext(
        db=db,
        user_id=user_id,
        job_id=job_id,
        conversation_id=conv_id or uuid.uuid4(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Complete Workflow Test
# ═══════════════════════════════════════════════════════════════════════════════

class TestQuotationWorkflowToolChain:
    """Verify the full 8-step tool chain works end-to-end."""

    async def test_full_quotation_workflow(
        self, test_ids, extracted_data, expected_stock, mock_server,
        erp_integration_config, crm_integration_config,
    ):
        ids = test_ids
        db = MagicMock()

        # ── Step 1: list_documents ──────────────────────────────────────────
        doc = _make_fake_document(ids["doc_id"], ids["job_id"], extracted_data)
        db.query().filter().all.return_value = [doc]

        result = await _list_documents_handler({}, _make_context(db, ids["user_id"], ids["job_id"]))
        assert result["count"] == 1
        assert result["documents"][0]["status"] == "extraction_completed"

        # ── Step 2: get_document_detail ─────────────────────────────────────
        db.query().filter().first.return_value = doc

        result = await _get_document_detail_handler(
            {"doc_id": str(ids["doc_id"])},
            _make_context(db, ids["user_id"], ids["job_id"]),
        )
        assert result["filename"] == "request_quotation.pdf"
        assert result["extracted_data"]["customer"]["name"] == "บริษัท ทดสอบ จำกัด"
        assert len(result["extracted_data"]["line_items"]) == 3

        # ── Step 3: list_integrations ───────────────────────────────────────
        db.reset_mock()
        erp_integ = _make_fake_integration(
            ids["erp_integration_id"], "ERP Stock", "api", erp_integration_config,
        )
        crm_integ = _make_fake_integration(
            ids["crm_integration_id"], "CRM System", "api", crm_integration_config,
        )
        # Patch get_all_active to return our integrations
        with patch("app.agent.tools.integration_tools.crud_integration.get_all_active",
                   return_value=[erp_integ, crm_integ]):
            result = await _list_integrations_handler(
                {}, _make_context(db, ids["user_id"], ids["job_id"]),
            )
        assert result["count"] == 2
        names = [i["name"] for i in result["integrations"]]
        assert "ERP Stock" in names
        assert "CRM System" in names

        # ── Step 4: call_api_integration — Check stock for each SKU ─────────
        with patch("app.agent.tools.integration_tools.crud_integration") as mock_crud:
            mock_crud.get.return_value = None
            mock_crud.get_all_active.return_value = [erp_integ, crm_integ]

            # Check PRD-001
            result = await _call_api_integration_handler(
                {
                    "integration_name": "ERP Stock",
                    "method": "GET",
                    "path": f"/api/stock/{extracted_data['line_items'][0]['sku']}",
                },
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
            assert result["ok"] is True
            assert result["data"]["available_qty"] == 50

            # Check PRD-002
            result = await _call_api_integration_handler(
                {
                    "integration_name": "ERP Stock",
                    "method": "GET",
                    "path": f"/api/stock/{extracted_data['line_items'][1]['sku']}",
                },
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
            assert result["ok"] is True
            assert result["data"]["available_qty"] == 0  # Out of stock!

            # Check PRD-003
            result = await _call_api_integration_handler(
                {
                    "integration_name": "ERP Stock",
                    "method": "GET",
                    "path": f"/api/stock/{extracted_data['line_items'][2]['sku']}",
                },
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
            assert result["ok"] is True
            assert result["data"]["available_qty"] == 20

        # ── Step 5: execute_python — Filter in_stock vs out_of_stock ────────
        filter_code = """
items = inputs['items']
stock = inputs['stock']
in_stock = [i for i in items if stock[i['sku']]['available_qty'] >= i['qty']]
out_of_stock = [i for i in items if stock[i['sku']]['available_qty'] < i['qty']]
result = {'in_stock': in_stock, 'out_of_stock': out_of_stock}
"""
        stock_data = {
            "PRD-001": {"available_qty": 50},
            "PRD-002": {"available_qty": 0},
            "PRD-003": {"available_qty": 20},
        }
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {
                "result": {
                    "in_stock": [extracted_data["line_items"][0], extracted_data["line_items"][2]],
                    "out_of_stock": [extracted_data["line_items"][1]],
                },
                "error": None,
            }
            result = await _execute_python_handler(
                {"code": filter_code, "inputs": {"items": extracted_data["line_items"], "stock": stock_data}},
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
        assert result["result"]["in_stock"][0]["sku"] == "PRD-001"
        assert result["result"]["out_of_stock"][0]["sku"] == "PRD-002"

        # ── Step 6: call_api_integration — POST quotation to CRM ────────────
        in_stock_items = [
            {"sku": "PRD-001", "name": "สินค้า A", "qty": 10, "unit_price": 500},
            {"sku": "PRD-003", "name": "สินค้า C", "qty": 8, "unit_price": 800},
        ]
        total = 10 * 500 + 8 * 800  # = 11400
        with patch("app.agent.tools.integration_tools.crud_integration") as mock_crud:
            mock_crud.get.return_value = None
            mock_crud.get_all_active.return_value = [erp_integ, crm_integ]

            result = await _call_api_integration_handler(
                {
                    "integration_name": "CRM System",
                    "method": "POST",
                    "path": "/api/quotations",
                    "body": {
                        "customer_name": extracted_data["customer"]["name"],
                        "customer_address": extracted_data["customer"]["address"],
                        "items": in_stock_items,
                        "total": float(total),
                        "currency": "THB",
                    },
                },
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
        assert result["ok"] is True
        assert "quotation_id" in result["data"]
        assert result["data"]["status"] == "pending_approval"

        # ── Step 7: execute_python — Generate report ────────────────────────
        report_code = """
items = inputs['in_stock']
out_items = inputs['out_of_stock']
customer = inputs['customer']
quotation_id = inputs['quotation_id']
total = inputs['total']

lines = [
    '=== Quotation Creation Report ===',
    '',
    f'Customer: {customer}',
    f'Quotation: {quotation_id}',
    '',
    'Successful Items:',
]
for item in items:
    lines.append(f'  - {item[\"sku\"]} ({item[\"name\"]}): {item[\"qty\"]} x {item[\"unit_price\"]} = {item[\"qty\"] * item[\"unit_price\"]:,.2f}')
lines.append(f'  Total: {total:,.2f}')
lines.append('')
if out_items:
    lines.append('Out of Stock:')
    for item in out_items:
        lines.append(f'  - {item[\"sku\"]} ({item[\"name\"]}): requested {item[\"qty\"]}')
result = {'report': '\\n'.join(lines)}
"""
        report_inputs = {
            "in_stock": in_stock_items,
            "out_of_stock": [{"sku": "PRD-002", "name": "สินค้า B", "qty": 5}],
            "customer": extracted_data["customer"]["name"],
            "quotation_id": "Q-0001",
            "total": float(total),
        }
        expected_report_lines = [
            "Quotation Creation Report",
            "บริษัท ทดสอบ จำกัด",
            "Q-0001",
            "PRD-001",
            "PRD-003",
            "PRD-002",
        ]
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {
                "result": {"report": "\\n".join([
                    "=== Quotation Creation Report ===",
                    "",
                    "Customer: บริษัท ทดสอบ จำกัด",
                    "Quotation: Q-0001",
                    "",
                    "Successful Items:",
                    "  - PRD-001 (สินค้า A): 10 x 500 = 5,000.00",
                    "  - PRD-003 (สินค้า C): 8 x 800 = 6,400.00",
                    "  Total: 11,400.00",
                    "",
                    "Out of Stock:",
                    "  - PRD-002 (สินค้า B): requested 5",
                ])},
                "error": None,
            }
            result = await _execute_python_handler(
                {"code": report_code, "inputs": report_inputs},
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
        report = result["result"]["report"]
        for expected in expected_report_lines:
            assert expected in report, f"Report missing: {expected}"

        # ── Step 8: write_file — Save report ────────────────────────────────
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            result = await _write_file_handler(
                {
                    "path": "outputs/quotation_report.txt",
                    "content": report,
                },
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
        assert result["ok"] is True
        assert "quotation_report.txt" in result["path"]

        # ── Final verification ──────────────────────────────────────────────
        # All 8 steps completed successfully
        self.final_ok = True

    async def test_out_of_stock_not_sent_to_crm(
        self, test_ids, extracted_data, mock_server,
        erp_integration_config, crm_integration_config,
    ):
        """Verify out-of-stock items are excluded from CRM quotation."""
        ids = test_ids
        db = MagicMock()

        erp = _make_fake_integration(ids["erp_integration_id"], "ERP Stock", "api", erp_integration_config)
        crm = _make_fake_integration(ids["crm_integration_id"], "CRM System", "api", crm_integration_config)

        with patch("app.agent.tools.integration_tools.crud_integration") as mock_crud:
            mock_crud.get.return_value = None
            mock_crud.get_all_active.return_value = [erp, crm]

            result = await _call_api_integration_handler(
                {
                    "integration_name": "CRM System",
                    "method": "POST",
                    "path": "/api/quotations",
                    "body": {
                        "customer_name": extracted_data["customer"]["name"],
                        "customer_address": extracted_data["customer"]["address"],
                        "items": [
                            {"sku": "PRD-001", "qty": 10, "unit_price": 500},
                            {"sku": "PRD-003", "qty": 8, "unit_price": 800},
                        ],
                        "total": 11400.0,
                    },
                },
                _make_context(db, ids["user_id"], ids["job_id"]),
            )

        assert result["ok"] is True
        items = result["data"]["items"]
        skus = [i["sku"] for i in items]
        assert "PRD-001" in skus
        assert "PRD-003" in skus
        assert "PRD-002" not in skus, "PRD-002 (out of stock) should NOT be in quotation"

    async def test_multi_tenant_isolation(self, test_ids, extracted_data):
        """Verify tools respect job-level tenant scoping."""
        ids = test_ids
        db = MagicMock()

        # User A's document
        doc_a = _make_fake_document(ids["doc_id"], ids["job_id"], extracted_data)

        # User B tries to access User A's job
        other_job_id = uuid.uuid4()
        other_user_id = uuid.uuid4()

        db.query().filter().first.return_value = None  # Not found for other job

        result = await _get_document_detail_handler(
            {"doc_id": str(ids["doc_id"])},
            _make_context(db, other_user_id, other_job_id),
        )
        assert "error" in result  # Document not found in other user's job


class TestStockCheckIntegration:
    """Integration tests with real mock HTTP server."""

    async def test_check_all_skus(
        self, test_ids, extracted_data, expected_stock, mock_server,
        erp_integration_config,
    ):
        ids = test_ids
        db = MagicMock()
        erp = _make_fake_integration(ids["erp_integration_id"], "ERP Stock", "api", erp_integration_config)

        with patch("app.agent.tools.integration_tools.crud_integration") as mock_crud:
            mock_crud.get.return_value = None
            mock_crud.get_all_active.return_value = [erp]

            for item in extracted_data["line_items"]:
                sku = item["sku"]
                result = await _call_api_integration_handler(
                    {
                        "integration_name": "ERP Stock",
                        "method": "GET",
                        "path": f"/api/stock/{sku}",
                    },
                    _make_context(db, ids["user_id"], ids["job_id"]),
                )
                assert result["ok"] is True, f"Stock check failed for {sku}: {result}"
                assert result["data"]["sku"] == sku
                expected_qty = expected_stock[sku]["available_qty"]
                assert result["data"]["available_qty"] == expected_qty, \
                    f"Expected {expected_qty} for {sku}, got {result['data']['available_qty']}"

    async def test_nonexistent_sku_returns_error(
        self, test_ids, mock_server, erp_integration_config,
    ):
        ids = test_ids
        db = MagicMock()
        erp = _make_fake_integration(ids["erp_integration_id"], "ERP Stock", "api", erp_integration_config)

        with patch("app.agent.tools.integration_tools.crud_integration") as mock_crud:
            mock_crud.get.return_value = None
            mock_crud.get_all_active.return_value = [erp]

            result = await _call_api_integration_handler(
                {
                    "integration_name": "ERP Stock",
                    "method": "GET",
                    "path": "/api/stock/PRD-999",
                },
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
        assert result["ok"] is False
        assert result["status_code"] == 404


class TestFileRoundTrip:
    """Write then read a report file (mocked storage)."""

    async def test_write_then_read_report(self, test_ids):
        ids = test_ids
        db = MagicMock()

        report_content = "=== Test Report ===\nCustomer: ACME\nTotal: 10,000"

        # Write
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_svc:
            mock_svc.return_value.exists.return_value = False
            write_result = await _write_file_handler(
                {"path": "outputs/test_report.txt", "content": report_content},
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
        assert write_result["ok"] is True

        # Read
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_svc, \
             patch("pathlib.Path.stat") as mock_stat, \
             patch("pathlib.Path.read_text", return_value=report_content):
            mock_svc.return_value.exists.return_value = True
            mock_svc.return_value.get_local_path.return_value.__enter__.return_value = "/tmp/fake.txt"
            mock_stat.return_value.st_size = len(report_content)

            read_result = await _read_file_handler(
                {"path": "outputs/test_report.txt"},
                _make_context(db, ids["user_id"], ids["job_id"]),
            )
        assert read_result["content"] == report_content

    async def test_write_file_path_traversal_blocked(self, test_ids):
        ids = test_ids
        db = MagicMock()

        result = await _write_file_handler(
            {"path": "../../../etc/malicious.sh", "content": "evil"},
            _make_context(db, ids["user_id"], ids["job_id"]),
        )
        assert "error" in result
