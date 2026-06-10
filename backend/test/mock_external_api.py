"""
Mock ERP/CRM server for E2E agent workflow tests.

Run: uvicorn test.mock_external_api:app --port 8765

Endpoints match the Quotation Workflow test case (Section 13):
  - ERP Stock: GET /api/stock/{sku}
  - CRM Quotations: POST /api/quotations
  - ERP Products: GET /api/products/{sku} (alternate path)
"""
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="InsightOCR Mock ERP/CRM")

# ── Stock database matching test scenario ─────────────────────────────────────
STOCK_DB: dict[str, dict[str, Any]] = {
    "PRD-001": {"sku": "PRD-001", "name": "สินค้า A", "available_qty": 50, "price": 500.0},
    "PRD-002": {"sku": "PRD-002", "name": "สินค้า B", "available_qty": 0, "price": 1200.0},
    "PRD-003": {"sku": "PRD-003", "name": "สินค้า C", "available_qty": 20, "price": 800.0},
    "PRD-004": {"sku": "PRD-004", "name": "สินค้า D", "available_qty": 5, "price": 300.0},
}

QUOTATIONS: list[dict[str, Any]] = []
EVENTS: list[dict[str, Any]] = []


class QuotationCreate(BaseModel):
    customer_name: str = ""
    customer_address: str = ""
    items: list[dict[str, Any]] = []
    total: float = 0.0
    currency: str = "THB"


class WorkflowEvent(BaseModel):
    event: str
    payload: dict[str, Any] = {}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── ERP: Stock check ──────────────────────────────────────────────────────────

@app.get("/api/stock/{sku}")
def get_stock(sku: str) -> dict[str, Any]:
    """Check stock for a single SKU. Used by call_api_integration."""
    product = STOCK_DB.get(sku.upper())
    if not product:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku}")
    return {
        "sku": product["sku"],
        "name": product["name"],
        "available_qty": product["available_qty"],
        "price": product["price"],
    }


@app.get("/api/products/{sku}")
def get_product(sku: str) -> dict[str, Any]:
    """Alternate path for stock check."""
    return get_stock(sku)


# ── CRM: Quotations ───────────────────────────────────────────────────────────

@app.post("/api/quotations")
def create_quotation(q: QuotationCreate) -> dict[str, Any]:
    """Create a quotation in CRM. Used by call_api_integration (POST)."""
    if not q.customer_name:
        raise HTTPException(status_code=400, detail="customer_name is required")
    if not q.items:
        raise HTTPException(status_code=400, detail="items is required")

    quotation_id = f"Q-{len(QUOTATIONS) + 1:04d}"
    record = {
        "quotation_id": quotation_id,
        "customer_name": q.customer_name,
        "customer_address": q.customer_address,
        "items": q.items,
        "total": q.total,
        "currency": q.currency,
        "status": "pending_approval",
    }
    QUOTATIONS.append(record)
    return record


@app.get("/api/quotations")
def list_quotations() -> dict[str, Any]:
    return {"count": len(QUOTATIONS), "quotations": QUOTATIONS}


# ── Workflow / Webhook ────────────────────────────────────────────────────────

@app.post("/api/workflow/{event_name}")
def trigger_workflow(event_name: str, payload: dict[str, Any] = None) -> dict[str, Any]:
    event = {"id": len(EVENTS) + 1, "event": event_name, "payload": payload or {}}
    EVENTS.append(event)
    return {"ok": True, "event_id": event["id"]}


# ── Admin: Reset state between tests ──────────────────────────────────────────

@app.post("/__reset")
def reset_state() -> dict[str, str]:
    QUOTATIONS.clear()
    EVENTS.clear()
    return {"ok": True, "message": "State reset"}
