"""
E2E test fixtures — Quotation Workflow.

Shared fixtures for both Level 1 (tool integration) and Level 2 (agent loop) tests.
"""
import os
import uuid
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Constants matching the test scenario (Section 13)
# ═══════════════════════════════════════════════════════════════════════════════

MOCK_SERVER_PORT = int(os.environ.get("MOCK_SERVER_PORT", "8765"))
MOCK_SERVER_URL = f"http://127.0.0.1:{MOCK_SERVER_PORT}"

QUOTATION_EXTRACTED_DATA = {
    "customer": {
        "name": "บริษัท ทดสอบ จำกัด",
        "address": "123 ถนนทดสอบ แขวงทดสอบ เขตทดสอบ กรุงเทพฯ 10110",
        "tax_id": "1234567890123",
        "contact_email": "contact@testco.example.com",
    },
    "line_items": [
        {"sku": "PRD-001", "name": "สินค้า A", "qty": 10, "unit_price": 500},
        {"sku": "PRD-002", "name": "สินค้า B", "qty": 5, "unit_price": 1200},
        {"sku": "PRD-003", "name": "สินค้า C", "qty": 8, "unit_price": 800},
    ],
    "total_amount": 11400.0,
    "currency": "THB",
}

EXPECTED_STOCK_RESULTS = {
    "PRD-001": {"available_qty": 50, "in_stock": True},
    "PRD-002": {"available_qty": 0, "in_stock": False},
    "PRD-003": {"available_qty": 20, "in_stock": True},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Mock server lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def mock_server():
    """Start mock ERP/CRM server for the test session."""
    proc = subprocess.Popen(
        ["uvicorn", "test.mock_external_api:app", "--port", str(MOCK_SERVER_PORT), "--host", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server to be ready
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{MOCK_SERVER_URL}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("Mock server did not start")

    yield MOCK_SERVER_URL

    # Reset and shutdown
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"{MOCK_SERVER_URL}/__reset", method="POST"),
            timeout=2,
        )
    except Exception:
        pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(autouse=True)
def reset_mock_server(mock_server):
    """Reset mock server state before each test."""
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"{mock_server}/__reset", method="POST"),
            timeout=2,
        )
    except Exception:
        pass
    yield


# ═══════════════════════════════════════════════════════════════════════════════
# Test IDs — stable across tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def test_ids():
    return {
        "user_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "job_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "doc_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "conv_id": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "llm_integration_id": uuid.UUID("55555555-5555-5555-5555-555555555555"),
        "erp_integration_id": uuid.UUID("66666666-6666-6666-6666-666666666666"),
        "crm_integration_id": uuid.UUID("77777777-7777-7777-7777-777777777777"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Data fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def extracted_data():
    return dict(QUOTATION_EXTRACTED_DATA)


@pytest.fixture
def expected_stock():
    return dict(EXPECTED_STOCK_RESULTS)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration configs (for Level 1 tool tests)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def erp_integration_config(mock_server):
    return {
        "baseUrl": mock_server,
        "authHeader": "",
    }


@pytest.fixture
def crm_integration_config(mock_server):
    return {
        "baseUrl": mock_server,
        "authHeader": "",
    }
