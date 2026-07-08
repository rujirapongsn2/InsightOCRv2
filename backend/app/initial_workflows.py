from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.advisory_lock import advisory_lock
from app.models.document import Document
from app.models.job import Job
from app.models.user import User
from app.models.workflow import Workflow


RECEIPT_REVIEW_JOB_NAME = "ใบเสร็จรับเงิน review"


def _node(
    node_id: str,
    node_type: str,
    label: str,
    x: float,
    y: float,
    config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": x, "y": y},
        "data": {"label": label, "config": config or {}},
    }


def _edge(
    source: str,
    target: str,
    source_handle: str | None = None,
) -> Dict[str, Any]:
    return {
        "id": f"{source}-{source_handle + '-' if source_handle else ''}{target}",
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": None,
    }


def _ensure_receipt_review_job(db: Session, owner: User | None) -> Job:
    job = db.query(Job).filter(Job.name == RECEIPT_REVIEW_JOB_NAME).first()
    if not job:
        job = Job(
            name=RECEIPT_REVIEW_JOB_NAME,
            description="Demo job for workflow samples that use reviewed receipt data.",
            status="review",
            user_id=owner.id if owner else None,
        )
        db.add(job)
        db.flush()

    has_documents = db.query(Document).filter(Document.job_id == job.id).first() is not None
    if not has_documents:
        demo_docs = [
            {
                "filename": "receipt-review-001.pdf",
                "ocr_text": (
                    "ใบเสร็จรับเงิน REC-2026-001 ร้าน Softnix Mart วันที่ 2026-06-01 "
                    "ยอดรวม 1250.50 บาท VAT 81.81 ชำระด้วยบัตรเครดิต"
                ),
                "data": {
                    "receipt_number": "REC-2026-001",
                    "date": "2026-06-01",
                    "merchant_name": "Softnix Mart",
                    "total_amount": 1250.50,
                    "tax_amount": 81.81,
                    "payment_method": "Credit Card",
                    "review_status": "reviewed",
                },
            },
            {
                "filename": "receipt-review-002.pdf",
                "ocr_text": (
                    "ใบเสร็จรับเงิน REC-2026-002 ร้าน Cloud Office Supply วันที่ 2026-06-03 "
                    "ยอดรวม 845.00 บาท VAT 55.28 ชำระด้วยเงินสด"
                ),
                "data": {
                    "receipt_number": "REC-2026-002",
                    "date": "2026-06-03",
                    "merchant_name": "Cloud Office Supply",
                    "total_amount": 845.00,
                    "tax_amount": 55.28,
                    "payment_method": "Cash",
                    "review_status": "reviewed",
                },
            },
            {
                "filename": "receipt-review-003.pdf",
                "ocr_text": (
                    "ใบเสร็จรับเงิน REC-2026-003 ร้าน Delivery Hub วันที่ 2026-06-05 "
                    "ยอดรวม 420.75 บาท VAT 27.52 ชำระด้วย QR Payment"
                ),
                "data": {
                    "receipt_number": "REC-2026-003",
                    "date": "2026-06-05",
                    "merchant_name": "Delivery Hub",
                    "total_amount": 420.75,
                    "tax_amount": 27.52,
                    "payment_method": "QR Payment",
                    "review_status": "reviewed",
                },
            },
        ]
        for item in demo_docs:
            db.add(
                Document(
                    job_id=job.id,
                    filename=item["filename"],
                    file_path=f"demo/workflow/{item['filename']}",
                    file_size=len(item["ocr_text"].encode("utf-8")),
                    mime_type="application/pdf",
                    status="reviewed",
                    ocr_text=item["ocr_text"],
                    ocr_confidence=0.96,
                    page_count=1,
                    extracted_data=item["data"],
                    reviewed_data=item["data"],
                    review_decision="approved",
                    extraction_confidence=0.94,
                )
            )

    return job


def _workflow_1(job_id: str) -> Dict[str, Any]:
    return {
        "nodes": [
            _node("trigger_manual_receipt", "trigger_manual", "Manual Trigger", 60, 220),
            _node(
                "job_receipt_review",
                "job_source",
                "Jobs: ใบเสร็จรับเงิน review",
                300,
                220,
                {
                    "job_id": job_id,
                    "data_source": "reviewed",
                    "status": "reviewed",
                    "only_completed": True,
                    "limit": 50,
                },
            ),
            _node(
                "condition_receipt_has_records",
                "condition",
                "Condition: มีข้อมูลใบเสร็จ",
                560,
                220,
                {
                    "left": "{{job_receipt_review.count}}",
                    "operator": "greater_than",
                    "right": "0",
                },
            ),
            _node(
                "transform_manual_receipt_summary",
                "transform",
                "Transform: จัดชุดข้อมูล",
                820,
                160,
                {
                    "mappings": [
                        {"target": "workflow", "value": "manual_receipt_review"},
                        {"target": "job_name", "value": "{{job_receipt_review.job_name}}"},
                        {"target": "document_count", "value": "{{job_receipt_review.count}}"},
                        {"target": "records", "value": "{{job_receipt_review.records}}"},
                        {"target": "run_label", "value": "{{trigger.run_label}}"},
                    ]
                },
            ),
            _node(
                "python_manual_receipt_metrics",
                "python_code",
                "Python Code: คำนวณยอด",
                1080,
                160,
                {
                    "input": "{{transform_manual_receipt_summary}}",
                    "timeout": 30,
                    "code": (
                        "records = inputs.get('records') or []\n"
                        "\n"
                        "def to_amount(value):\n"
                        "    try:\n"
                        "        return float(str(value).replace(',', '').strip())\n"
                        "    except Exception:\n"
                        "        return 0.0\n"
                        "\n"
                        "total_amount = sum(to_amount(row.get('total_amount')) for row in records if isinstance(row, dict))\n"
                        "result = {\n"
                        "    'workflow': inputs.get('workflow'),\n"
                        "    'job_name': inputs.get('job_name'),\n"
                        "    'document_count': len(records),\n"
                        "    'total_amount': round(total_amount, 2),\n"
                        "    'average_amount': round(total_amount / len(records), 2) if records else 0,\n"
                        "    'run_label': inputs.get('run_label') or 'manual-demo'\n"
                        "}\n"
                    ),
                },
            ),
            _node(
                "output_manual_receipt_review",
                "write_output",
                "Write Output: manual summary",
                1340,
                160,
                {
                    "filename": "workflow-1-manual-receipt-summary.json",
                    "format": "json",
                    "content": "{{python_manual_receipt_metrics.result}}",
                },
            ),
        ],
        "edges": [
            _edge("trigger_manual_receipt", "job_receipt_review"),
            _edge("job_receipt_review", "condition_receipt_has_records"),
            _edge("condition_receipt_has_records", "transform_manual_receipt_summary", "true"),
            _edge("transform_manual_receipt_summary", "python_manual_receipt_metrics"),
            _edge("python_manual_receipt_metrics", "output_manual_receipt_review"),
        ],
    }


def _workflow_2(job_id: str) -> Dict[str, Any]:
    return {
        "nodes": [
            _node("trigger_webhook_receipt", "trigger_webhook", "Webhook Trigger", 60, 220),
            _node(
                "job_receipt_review_webhook",
                "job_source",
                "Jobs: ใบเสร็จรับเงิน review",
                300,
                220,
                {
                    "job_id": job_id,
                    "data_source": "reviewed",
                    "status": "reviewed",
                    "only_completed": True,
                    "limit": 50,
                },
            ),
            _node(
                "condition_webhook_has_records",
                "condition",
                "Condition: มีใบเสร็จให้สรุป",
                560,
                220,
                {
                    "left": "{{job_receipt_review_webhook.count}}",
                    "operator": "greater_than",
                    "right": "0",
                },
            ),
            _node(
                "llm_webhook_receipt",
                "llm",
                "LLM: สรุปคำขอจาก webhook",
                820,
                160,
                {
                    "ai_provider_id": "",
                    "system_prompt": "คุณเป็นผู้ช่วยตรวจทานใบเสร็จ ตอบเป็นภาษาไทย กระชับ และเน้นประเด็นที่ตรวจได้จากข้อมูล",
                    "prompt": (
                        "สรุปข้อมูลใบเสร็จที่ review แล้วจาก job นี้ และอ้างอิง context จาก webhook ถ้ามี\n\n"
                        "Webhook body:\n{{trigger.body}}\n\n"
                        "Receipt records:\n{{job_receipt_review_webhook.records}}\n\n"
                        "ตอบเป็นหัวข้อ: จำนวนเอกสาร, ยอดรวมโดยประมาณ, ร้านค้า, และข้อสังเกต"
                    ),
                    "json_output": False,
                },
            ),
            _node(
                "transform_webhook_receipt_summary",
                "transform",
                "Transform: รวมผล LLM",
                1080,
                160,
                {
                    "mappings": [
                        {"target": "workflow", "value": "webhook_receipt_review"},
                        {"target": "request_id", "value": "{{trigger.body.request_id}}"},
                        {"target": "received_at", "value": "{{trigger.received_at}}"},
                        {"target": "job_name", "value": "{{job_receipt_review_webhook.job_name}}"},
                        {"target": "document_count", "value": "{{job_receipt_review_webhook.count}}"},
                        {"target": "llm_summary", "value": "{{llm_webhook_receipt.text}}"},
                    ]
                },
            ),
            _node(
                "output_webhook_receipt_review",
                "write_output",
                "Write Output: webhook summary",
                1340,
                160,
                {
                    "filename": "workflow-2-webhook-receipt-summary.json",
                    "format": "json",
                    "content": "{{transform_webhook_receipt_summary}}",
                },
            ),
        ],
        "edges": [
            _edge("trigger_webhook_receipt", "job_receipt_review_webhook"),
            _edge("job_receipt_review_webhook", "condition_webhook_has_records"),
            _edge("condition_webhook_has_records", "llm_webhook_receipt", "true"),
            _edge("llm_webhook_receipt", "transform_webhook_receipt_summary"),
            _edge("transform_webhook_receipt_summary", "output_webhook_receipt_review"),
        ],
    }


def _workflow_3(job_id: str) -> Dict[str, Any]:
    return {
        "nodes": [
            _node(
                "trigger_schedule_receipt_docs",
                "trigger_schedule",
                "Schedule Trigger",
                60,
                220,
                {
                    "schedule_enabled": False,
                    "schedule_preset": "weekdays",
                    "schedule_time": "09:00",
                    "schedule_weekday": "1",
                    "schedule_day": 1,
                    "custom_cron": "",
                },
            ),
            _node(
                "document_source_receipts",
                "document_source",
                "Document Source: ใบเสร็จรับเงิน",
                300,
                220,
                {
                    "job_id": job_id,
                    "status": "reviewed",
                    "limit": 10,
                    "include_ocr_text": True,
                },
            ),
            _node(
                "condition_schedule_has_documents",
                "condition",
                "Condition: มีเอกสาร OCR",
                560,
                220,
                {
                    "left": "{{document_source_receipts.count}}",
                    "operator": "greater_than",
                    "right": "0",
                },
            ),
            _node(
                "llm_schedule_receipt_docs",
                "llm",
                "LLM: วิเคราะห์ OCR รายวัน",
                820,
                160,
                {
                    "ai_provider_id": "",
                    "system_prompt": "คุณเป็นผู้ช่วยวิเคราะห์ OCR ใบเสร็จ ตรวจความครบถ้วนและสรุปเป็นภาษาไทย",
                    "prompt": (
                        "ตรวจ OCR text และข้อมูลที่ extract แล้วจากเอกสารต่อไปนี้\n\n"
                        "{{document_source_receipts.documents}}\n\n"
                        "สรุปเป็นภาษาไทยว่ามีเอกสารกี่รายการ, มี field ใดน่าตรวจซ้ำ, "
                        "และเสนอ next action สำหรับทีม review"
                    ),
                    "json_output": False,
                },
            ),
            _node(
                "transform_schedule_receipt_report",
                "transform",
                "Transform: รายงานตามรอบเวลา",
                1080,
                160,
                {
                    "mappings": [
                        {"target": "workflow", "value": "schedule_document_source_review"},
                        {"target": "scheduled_at", "value": "{{trigger.scheduled_at}}"},
                        {"target": "job_name", "value": "{{document_source_receipts.job_name}}"},
                        {"target": "document_count", "value": "{{document_source_receipts.count}}"},
                        {"target": "documents", "value": "{{document_source_receipts.documents}}"},
                        {"target": "llm_summary", "value": "{{llm_schedule_receipt_docs.text}}"},
                    ]
                },
            ),
            _node(
                "output_schedule_receipt_report",
                "write_output",
                "Write Output: schedule report",
                1340,
                160,
                {
                    "filename": "workflow-3-schedule-document-source-report.json",
                    "format": "json",
                    "content": "{{transform_schedule_receipt_report}}",
                },
            ),
        ],
        "edges": [
            _edge("trigger_schedule_receipt_docs", "document_source_receipts"),
            _edge("document_source_receipts", "condition_schedule_has_documents"),
            _edge("condition_schedule_has_documents", "llm_schedule_receipt_docs", "true"),
            _edge("llm_schedule_receipt_docs", "transform_schedule_receipt_report"),
            _edge("transform_schedule_receipt_report", "output_schedule_receipt_report"),
        ],
    }


def _sample_workflows(job_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "name": "ตัวอย่าง 1 - Manual ใบเสร็จ review + Python",
            "description": (
                "Manual Trigger -> Jobs (ใบเสร็จรับเงิน review) -> Condition -> "
                "Transform -> Python Code -> Write Output"
            ),
            "definition": _workflow_1(job_id),
            "schedule_cron": None,
            "schedule_enabled": False,
        },
        {
            "name": "ตัวอย่าง 2 - Webhook ใบเสร็จ review + LLM",
            "description": (
                "Webhook Trigger -> Jobs (ใบเสร็จรับเงิน review) -> Condition -> "
                "LLM -> Transform -> Write Output"
            ),
            "definition": _workflow_2(job_id),
            "schedule_cron": None,
            "schedule_enabled": False,
        },
        {
            "name": "ตัวอย่าง 3 - Schedule Document Source + LLM",
            "description": (
                "Schedule Trigger -> Document Source -> Condition -> LLM -> "
                "Transform -> Write Output"
            ),
            "definition": _workflow_3(job_id),
            "schedule_cron": None,
            "schedule_enabled": False,
        },
    ]


def ensure_sample_workflows(db: Session) -> None:
    with advisory_lock(2026063001):
        try:
            owner = db.query(User).filter(User.is_superuser.is_(True)).order_by(User.created_at.asc()).first()
            job = _ensure_receipt_review_job(db, owner)
            job_id = str(job.id)

            for sample in _sample_workflows(job_id):
                exists = (
                    db.query(Workflow)
                    .filter(Workflow.name == sample["name"], Workflow.user_id == (owner.id if owner else None))
                    .first()
                )
                if exists:
                    # Never overwrite an existing sample — the user may have
                    # edited it. Seeding only creates what is missing.
                    continue
                db.add(
                    Workflow(
                        name=sample["name"],
                        description=sample["description"],
                        definition=sample["definition"],
                        schedule_cron=sample["schedule_cron"],
                        schedule_enabled=sample["schedule_enabled"],
                        is_active=True,
                        user_id=owner.id if owner else None,
                    )
                )

            db.commit()
        except Exception:
            db.rollback()
            raise
