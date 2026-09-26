"""
Deterministic workflow execution engine.

A workflow definition is a DAG: {"nodes": [...], "edges": [...]}.
Each node has {id, type, data: {label, config}}. Edges may carry a
sourceHandle ("true"/"false") for condition branching.

The engine executes nodes in topological order, persisting a
WorkflowNodeRun row per node (status pending → running → succeeded/
failed/skipped) so the UI can poll live activity.

Template syntax inside node config values:
    {{trigger.someField}}         — value from trigger input
    {{node_id.output.path.0.x}}   — output of an upstream node
If a string is exactly one template, the raw value (dict/list/number)
is passed through; otherwise values are interpolated as strings.
"""
import asyncio
import json
import logging
import re
import os
import socket
import time
from contextlib import ExitStack
from io import BytesIO
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse
from mimetypes import guess_type
from uuid import UUID

import requests as http_requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.workflow import Workflow, WorkflowRun, WorkflowNodeRun
from app.models.document import Document
from app.models.job import Job
from app.models.integration import Integration, IntegrationType, IntegrationStatus
from app.models.ai_settings import AISettings
from app.models.setting import Setting
from app.services.storage import get_storage_service
from app.services.typesafe import SCORE_SCALES, SCORE_SCALE_MAX, SCORE_SCALE_MIN
from app.services.llm_provider_capabilities import integration_supports_tool_calling
from app.utils.redact import redact_secrets
from app.api.v1.endpoints.integrations import _integration_api_key, _llm_base_url_for_integration

logger = logging.getLogger(__name__)

# Storage-service key prefix for write_output files. With local storage
# (base /app/uploads) this resolves to /app/uploads/workflow_outputs — the
# same shared-volume location the engine wrote to before; with MinIO/S3 the
# files land in the bucket so any replica can serve them.
WORKFLOW_OUTPUT_DIR = os.environ.get("WORKFLOW_OUTPUT_DIR", "workflow_outputs")
MAX_WORKFLOW_ARTIFACT_BYTES = 50 * 1024 * 1024

# A workflow can use an external API response in downstream nodes, but it must
# not be able to exhaust a worker by returning an unbounded response body.
try:
    WORKFLOW_API_MAX_RESPONSE_BYTES = max(
        1,
        int(os.environ.get("WORKFLOW_API_MAX_RESPONSE_BYTES", "1048576")),
    )
except ValueError:
    WORKFLOW_API_MAX_RESPONSE_BYTES = 1_048_576

# ── Node catalog (exposed to the frontend palette) ──────────────────
NODE_TYPES: List[Dict[str, Any]] = [
    {
        "type": "trigger_manual",
        "category": "trigger",
        "label": "Manual Trigger",
        "description": "เริ่ม workflow ด้วยตนเอง (กดปุ่ม Run) พร้อมส่ง input JSON ได้",
        "config_fields": [],
        "output_fields": [],  # ฟิลด์ขึ้นกับ input JSON ที่ผู้ใช้ส่งตอน Run
    },
    {
        "type": "trigger_schedule",
        "category": "trigger",
        "label": "Schedule Trigger",
        "description": "เริ่ม workflow ตามตารางเวลา (cron) ที่ตั้งไว้ใน workflow settings",
        "config_fields": [],
        "output_fields": [{"name": "scheduled_at", "label": "เวลาที่ทริกเกอร์"}],
    },
    {
        "type": "trigger_webhook",
        "category": "trigger",
        "label": "Webhook Trigger",
        "description": "เริ่ม workflow จาก webhook ภายนอก เช่น web application หรือ LINE webhook",
        "config_fields": [],
        "output_fields": [
            {"name": "body", "label": "Payload body"},
            {"name": "query", "label": "Query parameters"},
            {"name": "headers", "label": "Request headers"},
            {"name": "method", "label": "HTTP method"},
            {"name": "received_at", "label": "เวลาที่รับ webhook"},
        ],
    },
    {
        "type": "job_source",
        "category": "data",
        "label": "Jobs",
        "description": "นำข้อมูลที่ประมวลผลแล้วจาก Job (extracted/reviewed data) เข้าสู่ workflow",
        "config_fields": [
            {"name": "job_id", "label": "เลือก Job", "type": "job_select", "required": True,
             "hint": "เลือก Job ที่มีเอกสารประมวลผลแล้ว"},
            {"name": "data_source", "label": "ข้อมูลที่ใช้", "type": "select",
             "options": ["reviewed", "extracted", "ocr_text"], "default": "reviewed",
             "hint": "reviewed = ข้อมูลที่ตรวจแล้ว (แนะนำ), ocr_text = ข้อความดิบ"},
            {"name": "status", "label": "กรองตามสถานะเอกสาร", "type": "select",
             "options": ["", "extraction_completed", "reviewed"], "required": False,
             "hint": "เว้นว่าง = ไม่กรองเพิ่ม"},
            {"name": "only_completed", "label": "เฉพาะเอกสารที่ประมวลผลเสร็จ", "type": "boolean", "default": True},
            {"name": "limit", "label": "จำนวนเอกสารสูงสุด", "type": "number", "default": 50,
             "placeholder": "50"},
        ],
        "output_fields": [
            {"name": "count", "label": "จำนวนเอกสาร"},
            {"name": "records", "label": "ข้อมูลทั้งหมด (array)"},
            {"name": "documents", "label": "รายการเอกสาร"},
            {"name": "job_name", "label": "ชื่อ Job"},
            {"name": "job_status", "label": "สถานะ Job"},
        ],
    },
    {
        "type": "document_source",
        "category": "data",
        "label": "Document Source",
        "description": "ดึงเอกสาร (OCR text + extracted data) จาก Job ที่เลือก",
        "config_fields": [
            {"name": "job_id", "label": "เลือก Job", "type": "job_select", "required": True},
            {"name": "status", "label": "กรองตามสถานะเอกสาร", "type": "select",
             "options": ["", "extraction_completed", "reviewed"], "required": False,
             "hint": "เว้นว่าง = ไม่กรองเพิ่ม"},
            {"name": "only_completed", "label": "เฉพาะเอกสารที่ประมวลผลเสร็จ", "type": "boolean", "default": True},
            {"name": "limit", "label": "จำนวนเอกสารสูงสุด", "type": "number", "default": 10,
             "placeholder": "10"},
            {"name": "include_ocr_text", "label": "รวมข้อความ OCR", "type": "boolean", "default": True},
        ],
        "output_fields": [
            {"name": "count", "label": "จำนวนเอกสาร"},
            {"name": "documents", "label": "รายการเอกสาร (มีข้อความและสถานะ extraction)"},
            {"name": "job_name", "label": "ชื่อ Job"},
        ],
    },
    {
        "type": "field_mapping",
        "category": "data",
        "label": "Field Mapping (Schema)",
        "description": "ดึงค่าตามฟิลด์ใน Schema จากข้อความ OCR ของเอกสาร ใช้ระบบเดียวกับหน้า Jobs",
        "config_fields": [
            {"name": "schema_id", "label": "Schema", "type": "schema_select", "required": True,
             "hint": "เลือก Schema ที่กำหนดว่าต้องการดึงฟิลด์อะไรจากเอกสาร"},
            {"name": "engine", "label": "วิธีดึงข้อมูล", "type": "select",
             "options": ["auto", "softnix", "jev", "llm", "fixed"], "default": "auto",
             "option_labels": {"auto": "อัตโนมัติ (แนะนำ)", "softnix": "Softnix", "jev": "Jev (TypeSafe)",
                               "llm": "LLM", "fixed": "ตำแหน่งคงที่ (Fixed)"},
             "hint": "อัตโนมัติจะลอง Softnix → Jev → LLM ตามลำดับ และข้ามตัวที่ยังไม่ได้ตั้งค่า · Jev ต้องตั้งค่าที่ Settings › TypeSafe ก่อน"},
            {"name": "field_names", "label": "ดึงเฉพาะบางฟิลด์", "type": "text", "required": False,
             "placeholder": "เช่น invoice_no, total",
             "hint": "ใส่ชื่อฟิลด์คั่นด้วยจุลภาค · เว้นว่างเพื่อดึงทุกฟิลด์ใน Schema"},
            {"name": "limit", "label": "จำนวนเอกสารสูงสุดต่อรอบ", "type": "number", "default": 10,
             "placeholder": "10",
             "hint": "ยิ่งมากยิ่งใช้เวลานาน · ผลลัพธ์ “ค่าที่ดึงได้” เป็นของเอกสารแรก ส่วนผลของทุกเอกสารอยู่ใน “ผลรายเอกสาร”"},
        ],
        "output_fields": [
            {"name": "count", "label": "จำนวนเอกสารที่ดึงข้อมูล"},
            {"name": "values", "label": "ค่าที่ดึงได้ (เอกสารแรก)"},
            {"name": "status", "label": "สถานะรวมทุกเอกสาร (ยึดฉบับที่แย่ที่สุด)"},
            {"name": "first_document_status", "label": "สถานะของเอกสารแรก"},
            {"name": "incomplete_documents", "label": "เอกสารที่ดึงข้อมูลไม่ครบ"},
            {"name": "skipped_documents", "label": "เอกสารที่ยังไม่ได้ดึง (หมดเวลา)"},
            {"name": "evidence", "label": "หลักฐานของแต่ละฟิลด์ (เอกสารแรก)"},
            {"name": "review_fields", "label": "ฟิลด์ที่ควรตรวจซ้ำ (เอกสารแรก)"},
            {"name": "unresolved_fields", "label": "ฟิลด์ที่ดึงไม่ได้ (เอกสารแรก)"},
            {"name": "provider", "label": "วิธีดึงข้อมูลที่ใช้จริง"},
            {"name": "warnings", "label": "คำเตือน"},
            {"name": "documents", "label": "ผลรายเอกสาร"},
        ],
    },
    {
        "type": "jev_score",
        "category": "data",
        "label": "Score – ให้คะแนน",
        "description": "ให้ Jev ให้คะแนนข้อมูลตามเกณฑ์ที่คุณกำหนด แล้วนำคะแนนไปใช้ตัดสินใจใน Condition",
        "config_fields": [
            {"name": "score_name", "label": "สิ่งที่ต้องการให้คะแนน", "type": "text", "required": True,
             "placeholder": "เช่น ความครบถ้วนของเอกสาร",
             "hint": "ตั้งชื่อสั้นๆ ให้ Jev รู้ว่ากำลังประเมินเรื่องอะไร"},
            {"name": "input_source", "label": "ข้อมูลที่ใช้ประเมิน", "type": "textarea", "required": True,
             "placeholder": "เช่น {{documents_1.ocr_text}}",
             "hint": "กด “แทรกข้อมูล” เพื่อเลือกข้อมูลจาก node ก่อนหน้า · ถ้าเลือกรายการหลายเอกสาร Jev จะตัดสินรวมครั้งเดียว ไม่ได้แยกทีละเอกสาร"},
            {"name": "criteria", "label": "เกณฑ์การให้คะแนน", "type": "textarea", "required": True,
             "placeholder": "ความครบถ้วน|2|มีเลขที่ วันที่ และยอดรวมครบ\nความชัดเจน|1|อ่านข้อความได้ไม่ตกหล่น",
             "hint": "1 บรรทัดต่อ 1 เกณฑ์ เขียนแบบ ชื่อเกณฑ์|น้ำหนัก|คำอธิบาย · น้ำหนักใส่เป็นตัวเลขใดก็ได้ ระบบแปลงเป็นสัดส่วนให้ (ต้องใส่ทุกข้อ หรือเว้นว่างทุกข้อเพื่อให้เท่ากัน)"},
            {"name": "scale", "label": "ช่วงคะแนน", "type": "select",
             "options": ["0_100", "0_10", "1_5"], "default": "0_100",
             "option_labels": {"0_100": "0–100", "0_10": "0–10", "1_5": "1–5"}},
            {"name": "threshold", "label": "คะแนนขั้นต่ำที่ถือว่าผ่าน", "type": "number", "required": False,
             "placeholder": "เช่น 70",
             "hint": "ถ้าตั้งไว้ จะได้ผลลัพธ์ “ผ่านเกณฑ์” (จริง/เท็จ) ไว้ใช้ใน Condition · ใส่ค่าให้อยู่ในช่วงคะแนนที่เลือก"},
            {"name": "fields_to_use", "label": "ใช้เฉพาะบางฟิลด์", "type": "text", "required": False, "advanced": True,
             "placeholder": "เช่น total, vendor_name", "hint": "ใช้เมื่อข้อมูลเป็นชุดฟิลด์ (JSON) และต้องการส่งให้ Jev เฉพาะบางฟิลด์ · เว้นว่างเพื่อใช้ทั้งหมด"},
            {"name": "include_confidence", "label": "แสดงความมั่นใจของ Jev", "type": "boolean", "default": True,
             "advanced": True, "hint": "เพิ่มค่าความมั่นใจ (0–1) ไว้ในผลลัพธ์"},
            {"name": "engine", "label": "ผู้ประมวลผล", "type": "select", "advanced": True,
             "options": ["typesafe_jev", "auto"], "default": "typesafe_jev",
             "option_labels": {"typesafe_jev": "Jev (TypeSafe)", "auto": "อัตโนมัติ"},
             "hint": "ทั้งสองแบบใช้ Jev · ต้องตั้งค่าที่ Settings › TypeSafe ก่อน ไม่อย่างนั้น node จะหยุดทำงาน"},
        ],
        "output_fields": [
            {"name": "score", "label": "คะแนน"},
            {"name": "scale", "label": "ช่วงคะแนน"},
            {"name": "threshold", "label": "คะแนนขั้นต่ำที่ตั้งไว้"},
            {"name": "threshold_met", "label": "ผ่านเกณฑ์ (จริง/เท็จ)"},
            {"name": "confidence", "label": "ความมั่นใจ (0–1)"},
            {"name": "criteria", "label": "เกณฑ์ที่ใช้ (พร้อมสัดส่วน)"},
            {"name": "provider", "label": "ผู้ประมวลผล"},
        ],
    },
    {
        "type": "jev_choice",
        "category": "data",
        "label": "Choice – เลือกเส้นทาง",
        "description": "ให้ Jev เลือก 1 ตัวเลือกที่เข้ากับข้อมูลที่สุด แล้วส่งงานต่อตามเส้นทางของตัวเลือกนั้น",
        "config_fields": [
            {"name": "choice_name", "label": "เรื่องที่ต้องการให้เลือก", "type": "text", "required": True,
             "placeholder": "เช่น ส่งเอกสารให้ทีมไหนดูแล",
             "hint": "อธิบายสั้นๆ ว่ากำลังตัดสินใจเรื่องอะไร"},
            {"name": "input_source", "label": "ข้อมูลที่ใช้ตัดสิน", "type": "textarea", "required": True,
             "placeholder": "เช่น {{documents_1.ocr_text}}",
             "hint": "กด “แทรกข้อมูล” เพื่อเลือกข้อมูลจาก node ก่อนหน้า · ถ้าเลือกรายการหลายเอกสาร Jev จะตัดสินรวมครั้งเดียว ไม่ได้แยกทีละเอกสาร"},
            {"name": "options", "label": "ตัวเลือก", "type": "textarea", "required": True,
             "placeholder": "sales|ทีมขาย|ใบเสนอราคา คำสั่งซื้อ\nsupport|ทีมบริการ|คำร้อง แจ้งปัญหา",
             "hint": "2–6 บรรทัด บรรทัดละ 1 ตัวเลือก เขียนแบบ รหัส|ชื่อที่แสดง|คำอธิบาย · รหัสจะเป็นจุดต่อเส้นบน node ห้ามซ้ำกัน และห้ามใช้คำว่า fallback"},
            {"name": "pick_rule", "label": "วิธีตัดสิน", "type": "select",
             "options": ["highest", "first_above_threshold"], "default": "highest",
             "option_labels": {"highest": "เลือกตัวที่มีโอกาสสูงสุด", "first_above_threshold": "เลือกตัวแรกที่ถึงเกณฑ์"},
             "hint": "“ตัวแรกที่ถึงเกณฑ์” ไล่ตามลำดับบรรทัดในช่องตัวเลือก"},
            {"name": "probability_threshold", "label": "โอกาสขั้นต่ำ (0–1)", "type": "number", "required": False,
             "placeholder": "เช่น 0.6",
             "visible_when": {"field": "pick_rule", "equals": "first_above_threshold"},
             "hint": "ถ้าไม่มีตัวเลือกใดถึงค่านี้ งานจะไปทางสำรอง (ต้องเปิดทางสำรองไว้)"},
            {"name": "min_confidence", "label": "ความมั่นใจขั้นต่ำ (0–1)", "type": "number", "required": False,
             "placeholder": "เช่น 0.5",
             "hint": "ถ้า Jev มั่นใจน้อยกว่านี้ งานจะไปทางสำรองแทน · เว้นว่างเพื่อไม่ตรวจ"},
            {"name": "enable_fallback", "label": "มีทางสำรอง (Fallback)", "type": "boolean", "default": True,
             "hint": "เพิ่มจุดต่อ “Fallback” สีเหลืองสำหรับกรณีที่ Jev ไม่มั่นใจ · ต่อเส้นจากจุดนี้ด้วย ไม่อย่างนั้น node จะหยุดทำงานเมื่อเข้าทางสำรอง"},
            {"name": "fields_to_use", "label": "ใช้เฉพาะบางฟิลด์", "type": "text", "required": False, "advanced": True,
             "placeholder": "เช่น document_type, subject", "hint": "ใช้เมื่อข้อมูลเป็นชุดฟิลด์ (JSON) และต้องการส่งให้ Jev เฉพาะบางฟิลด์ · เว้นว่างเพื่อใช้ทั้งหมด"},
            {"name": "show_probabilities", "label": "แสดงโอกาสของทุกตัวเลือก", "type": "boolean", "default": True,
             "advanced": True, "hint": "เพิ่มโอกาสของแต่ละตัวเลือกไว้ในผลลัพธ์"},
            {"name": "engine", "label": "ผู้ประมวลผล", "type": "select", "advanced": True,
             "options": ["typesafe_jev", "auto"], "default": "typesafe_jev",
             "option_labels": {"typesafe_jev": "Jev (TypeSafe)", "auto": "อัตโนมัติ"},
             "hint": "ทั้งสองแบบใช้ Jev · ต้องตั้งค่าที่ Settings › TypeSafe ก่อน ไม่อย่างนั้น node จะหยุดทำงาน"},
        ],
        "output_fields": [
            {"name": "choice", "label": "รหัสตัวเลือกที่ได้"},
            {"name": "label", "label": "ชื่อตัวเลือกที่ได้"},
            {"name": "probability", "label": "โอกาสของตัวเลือกที่ได้ (0–1)"},
            {"name": "confidence", "label": "ความมั่นใจ (0–1)"},
            {"name": "used_fallback", "label": "ไปทางสำรอง (จริง/เท็จ)"},
            {"name": "options", "label": "โอกาสของทุกตัวเลือก"},
            {"name": "policy", "label": "กติกาที่ใช้ตัดสิน"},
            {"name": "provider", "label": "ผู้ประมวลผล"},
        ],
    },
    {
        "type": "jev_noul",
        "category": "data",
        "label": "Yes/No – ถามใช่หรือไม่",
        "description": "ถามคำถามแบบใช่/ไม่ใช่ แล้ว Jev ตอบเป็นโอกาสที่คำตอบคือ “ใช่” (0–1) เพื่อนำไปใช้ใน Condition",
        "config_fields": [
            {"name": "noul_name", "label": "ชื่อคำถาม", "type": "text", "required": True,
             "placeholder": "เช่น needs_review",
             "hint": "ชื่อสั้นๆ ไว้อ้างอิงในผลลัพธ์"},
            {"name": "question", "label": "คำถาม", "type": "textarea", "required": True,
             "placeholder": "เช่น เอกสารนี้ต้องให้คนตรวจซ้ำหรือไม่?",
             "hint": "เขียนเป็นคำถามที่ตอบได้แค่ ใช่ หรือ ไม่ใช่ และถามทีละเรื่อง"},
            {"name": "input_source", "label": "ข้อมูลที่ใช้ตอบ", "type": "textarea", "required": True,
             "placeholder": "เช่น {{documents_1.ocr_text}}",
             "hint": "กด “แทรกข้อมูล” เพื่อเลือกข้อมูลจาก node ก่อนหน้า · ถ้าเลือกรายการหลายเอกสาร Jev จะตัดสินรวมครั้งเดียว ไม่ได้แยกทีละเอกสาร"},
            {"name": "threshold", "label": "ถือว่า “ใช่” เมื่อโอกาสถึง (0–1)", "type": "number", "required": False,
             "placeholder": "เช่น 0.5",
             "hint": "ถ้าตั้งไว้ จะได้ผลลัพธ์ “ผ่านเกณฑ์” (จริง/เท็จ) · node นี้ไม่แยกเส้นทางเอง ให้ต่อ Condition เพื่อแยกทาง"},
            {"name": "fields_to_use", "label": "ใช้เฉพาะบางฟิลด์", "type": "text", "required": False, "advanced": True,
             "placeholder": "เช่น total, status", "hint": "ใช้เมื่อข้อมูลเป็นชุดฟิลด์ (JSON) และต้องการส่งให้ Jev เฉพาะบางฟิลด์ · เว้นว่างเพื่อใช้ทั้งหมด"},
            {"name": "engine", "label": "ผู้ประมวลผล", "type": "select", "advanced": True,
             "options": ["typesafe_jev", "auto"], "default": "typesafe_jev",
             "option_labels": {"typesafe_jev": "Jev (TypeSafe)", "auto": "อัตโนมัติ"},
             "hint": "ทั้งสองแบบใช้ Jev · ต้องตั้งค่าที่ Settings › TypeSafe ก่อน ไม่อย่างนั้น node จะหยุดทำงาน"},
        ],
        "output_fields": [
            {"name": "noul", "label": "โอกาสที่คำตอบคือ “ใช่” (0–1)"},
            {"name": "question", "label": "คำถาม"},
            {"name": "noul_name", "label": "ชื่อคำถาม"},
            {"name": "threshold", "label": "เกณฑ์ที่ตั้งไว้"},
            {"name": "threshold_met", "label": "ผ่านเกณฑ์ (จริง/เท็จ)"},
            {"name": "provider", "label": "ผู้ประมวลผล"},
            {"name": "input_from", "label": "ข้อมูลมาจาก"},
        ],
    },
    {
        "type": "llm",
        "category": "ai",
        "label": "LLM / Agent",
        "description": "ใช้ LLM แบบครั้งเดียว หรือ Autonomous Agent ที่ใช้ Skills และเครื่องมือหลายขั้นตอน",
        "config_fields": [
            {"name": "mode", "label": "โหมด", "type": "segmented", "options": ["llm", "agent"],
             "option_labels": {"llm": "LLM", "agent": "Agent"}, "default": "llm"},
            {"name": "agent_task", "label": "งานของ Agent", "type": "select",
             "options": ["analysis", "risk_assessment", "recommendations", "report"],
             "option_labels": {
                 "analysis": "วิเคราะห์เอกสาร",
                 "risk_assessment": "ประเมินความเสี่ยง",
                 "recommendations": "จัดทำข้อเสนอแนะ",
                 "report": "สร้างรายงาน",
             },
             "default": "analysis", "visible_when": {"field": "mode", "equals": "agent"},
             "hint": "ระบบกำหนดรูปแบบผลลัพธ์ เครื่องมือ และเวลารันให้เหมาะกับงานนี้"},
            {"name": "provider_ref", "label": "AI Provider", "type": "llm_provider_select", "required": False,
             "hint": "LLM ใช้ได้กับทุก provider ที่เปิดใช้งาน; Agent แสดงเฉพาะ provider ที่รองรับ native tool calling"},
            {"name": "system_prompt", "label": "System prompt", "type": "textarea", "required": False,
             "placeholder": "คุณเป็นผู้ช่วยสรุปข้อมูลเอกสาร ตอบเป็นภาษาไทย กระชับ",
             "hint": "กำหนดบทบาท/สไตล์การตอบของ AI", "visible_when": {"field": "mode", "equals": "llm"}},
            {"name": "prompt", "label": "Prompt", "type": "textarea", "required": True,
             "placeholder": "สรุปรายการต่อไปนี้เป็น bullet:\n\n{{job_source_xxx.records}}",
             "hint": "Agent จะได้รับสรุปที่ตรวจสอบแล้วจาก Agent ก่อนหน้าอัตโนมัติ"},
            {"name": "json_output", "label": "แปลงคำตอบเป็น JSON", "type": "boolean", "default": False,
             "hint": "เปิดเมื่อสั่งให้ AI ตอบเป็น JSON แล้วต้องการใช้ฟิลด์ data ต่อ",
             "visible_when": {"field": "mode", "equals": "llm"}},
            {"name": "job_id", "label": "Job context", "type": "job_select", "required": False,
             "hint": "เว้นว่างเพื่อใช้ Job จากโหนด Jobs หรือ Document Source ก่อนหน้า",
             "visible_when": {"field": "mode", "equals": "agent"}},
            {"name": "skill_ids", "label": "Skills ที่อนุญาต", "type": "skill_multi_select", "required": False,
             "hint": "Agent ใช้เฉพาะคำสั่งและเครื่องมือจาก Skills ที่เลือก",
             "visible_when": {"field": "mode", "equals": "agent"}},
            {"name": "output_format", "label": "ผลลัพธ์", "type": "select",
             "options": ["html", "docx", "pdf", "xlsx"], "default": "html",
             "option_labels": {"html": "HTML Report", "docx": "DOCX", "pdf": "PDF", "xlsx": "XLSX"},
             # "custom" covers legacy nodes saved before Agent task presets existed
             # (run_workflow_agent still lets them pick any output_format); only the
             # fixed-format presets (analysis/risk_assessment/recommendations) hide this.
             "visible_when": {"field": "agent_task", "equals": ["report", "custom"]}},
            {"name": "output_filename", "label": "ชื่อไฟล์ผลลัพธ์", "type": "text", "required": False,
             "placeholder": "report.html", "hint": "ระบบกำหนด path ที่ปลอดภัยให้โดยอัตโนมัติ",
             "visible_when": {"field": "agent_task", "equals": ["report", "custom"]}},
            {"name": "max_iterations", "label": "จำนวนรอบสูงสุด", "type": "number", "default": 7,
             "hint": "กำหนดได้ 3-20 รอบ", "visible_when": {"field": "mode", "equals": "agent"}, "advanced": True},
            {"name": "timeout_seconds", "label": "Timeout (วินาที)", "type": "number", "default": 300,
             "hint": "กำหนดได้ 60-900 วินาที", "visible_when": {"field": "mode", "equals": "agent"}, "advanced": True},
            {"name": "max_output_tokens", "label": "Output tokens สูงสุด (ต่อการเรียก LLM 1 ครั้ง)",
             "type": "number", "required": False,
             "hint": "เว้นว่าง = ใช้ค่าเริ่มต้นของงานนี้ ปรับลงหากเลือกโมเดลที่มี context window เล็ก "
                      "(ค่ารวม prompt + output ต้องไม่เกิน context window ของโมเดลที่เลือก) ช่วงที่กำหนดได้ 256-16000",
             "visible_when": {"field": "mode", "equals": "agent"}, "advanced": True},
        ],
        "output_fields": [
            {"name": "status", "label": "สถานะ Agent"},
            {"name": "text", "label": "ข้อความตอบกลับ"},
            {"name": "data", "label": "JSON ที่ parse แล้ว (ถ้าเปิด)"},
            {"name": "artifacts", "label": "ไฟล์ที่ Agent สร้าง"},
            {"name": "job_id", "label": "Job ที่สร้างไฟล์"},
            {"name": "warnings", "label": "คำเตือน"},
        ],
    },
    {
        "type": "condition",
        "category": "logic",
        "label": "Condition (If/Else)",
        "description": "ตรวจเงื่อนไขแล้วแยกเส้นทาง True / False",
        "config_fields": [
            {"name": "left", "label": "ค่าที่ตรวจ", "type": "text", "required": True,
             "placeholder": "{{job_source_xxx.count}}",
             "hint": "ใช้ปุ่ม “+ แทรกข้อมูล” เพื่อเลือกค่าจากโหนดก่อนหน้า"},
            {"name": "operator", "label": "เงื่อนไข", "type": "select",
             "options": ["equals", "not_equals", "contains", "not_contains", "greater_than",
                         "less_than", "is_empty", "is_not_empty"], "default": "equals"},
            {"name": "right", "label": "ค่าที่ใช้เทียบ", "type": "text", "required": False,
             "placeholder": "0",
             "hint": "ค่าที่ใช้เทียบ เช่น 0, reviewed (ไม่ต้องใส่ถ้าใช้ is_empty/is_not_empty)"},
        ],
        "output_fields": [{"name": "result", "label": "ผลลัพธ์ true/false"}],
    },
    {
        "type": "transform",
        "category": "logic",
        "label": "Transform / Mapping",
        "description": "สร้าง object ใหม่จากการ map ค่าด้วย template",
        "config_fields": [
            {"name": "mappings", "label": "การ map ฟิลด์", "type": "mappings", "required": True,
             "hint": "ตั้งชื่อฟิลด์ใหม่ทางซ้าย แล้วใช้ปุ่มแทรกข้อมูลเลือกค่าทางขวา"},
        ],
        "output_fields": [],  # ฟิลด์ขึ้นกับ target ที่ผู้ใช้กำหนด (เติมแบบไดนามิกฝั่ง UI)
    },
    {
        "type": "python_code",
        "category": "developer",
        "label": "Python Code",
        "description": "รันโค้ด Python ใน sandbox ปลอดภัย — อ่านข้อมูลจาก inputs แล้วเซ็ตตัวแปร result",
        "config_fields": [
            {"name": "code", "label": "โค้ด Python", "type": "code", "required": True,
             "hint": "อ่านข้อมูลจากตัวแปร inputs แล้วเซ็ตตัวแปร result เป็นผลลัพธ์"},
            {"name": "input", "label": "Input", "type": "textarea", "required": False,
             "placeholder": "{{transform_xxx}}",
             "hint": "ค่านี้จะกลายเป็นตัวแปร inputs ในโค้ด"},
            {"name": "timeout", "label": "Timeout (วินาที)", "type": "number", "default": 30,
             "placeholder": "30"},
        ],
        "output_fields": [
            {"name": "result", "label": "ผลลัพธ์ (ตัวแปร result)"},
            {"name": "stdout", "label": "ข้อความที่ print"},
        ],
    },
    {
        "type": "http_request",
        "category": "action",
        "label": "HTTP Request (Advanced)",
        "description": "เรียก endpoint โดยตรงจาก workflow; ใช้ API node เมื่อต้องการ Custom API ที่บันทึกไว้",
        "config_fields": [
            {"name": "method", "label": "Method", "type": "select",
             "options": ["POST", "GET", "PUT", "PATCH", "DELETE"], "default": "POST"},
            {"name": "url", "label": "URL", "type": "text", "required": True,
             "placeholder": "https://example.com/webhook"},
            {"name": "headers", "label": "Headers (JSON)", "type": "textarea", "required": False,
             "placeholder": '{ "Content-Type": "application/json" }'},
            {"name": "body", "label": "Body", "type": "textarea", "required": False,
             "placeholder": "{{transform_xxx}}",
             "hint": "ใช้ปุ่มแทรกข้อมูลเพื่อส่งผลจากโหนดก่อนหน้า"},
        ],
        "output_fields": [
            {"name": "status_code", "label": "HTTP status"},
            {"name": "body", "label": "เนื้อหาที่ตอบกลับ"},
        ],
    },
    {
        "type": "api",
        "category": "action",
        "label": "API",
        "description": "ส่งข้อมูลจากโหนดก่อนหน้าไปยัง Custom API ที่ตั้งค่าไว้ใน Integration",
        "config_fields": [
            {"name": "integration_id", "label": "Custom API", "type": "integration_select",
             "provider": "api", "required": True,
             "hint": "เลือก Custom API ที่มี endpoint, method และ headers ที่บันทึกไว้แล้ว"},
            {"name": "body", "label": "Request body", "type": "textarea", "required": False,
             "placeholder": "{{transform_xxx}}",
             "hint": "ข้อมูลนี้จะแทน Payload Template ของ Custom API; เว้นว่างเพื่อใช้ Payload Template ที่บันทึกไว้"},
            {"name": "timeout_seconds", "label": "Timeout (seconds)", "type": "number", "default": 30,
             "hint": "เวลาสูงสุดที่รอ API ตอบกลับ (1-120 วินาที)"},
        ],
        "output_fields": [
            {"name": "integration_name", "label": "Custom API ที่ใช้"},
            {"name": "status_code", "label": "HTTP status"},
            {"name": "body", "label": "เนื้อหาที่ตอบกลับ"},
        ],
    },
    {
        "type": "write_output",
        "category": "action",
        "label": "Write Output",
        "description": "เขียนผลลัพธ์เป็นไฟล์ (JSON / Text / CSV / Excel / Word) เพื่อนำไปใช้ต่อ",
        "config_fields": [
            {"name": "filename", "label": "ชื่อไฟล์", "type": "text", "default": "output.json",
             "placeholder": "report.json",
             "hint": "นามสกุลไฟล์จะปรับให้ตรงกับรูปแบบที่เลือกโดยอัตโนมัติ"},
            {"name": "format", "label": "รูปแบบไฟล์", "type": "select",
             "options": ["json", "text", "csv", "xlsx", "docx"], "default": "json",
             "hint": "xlsx/docx: ถ้าเนื้อหาเป็นรายการ object (เช่น records) จะสร้างเป็นตาราง"},
            {"name": "content", "label": "เนื้อหา", "type": "textarea", "required": True,
             "placeholder": "{{transform_xxx}}",
             "hint": "ใช้ปุ่มแทรกข้อมูลเลือกผลลัพธ์ที่ต้องการบันทึก"},
        ],
        "output_fields": [
            {"name": "filename", "label": "ชื่อไฟล์"},
            {"name": "size", "label": "ขนาด (ตัวอักษร)"},
            {"name": "preview", "label": "ตัวอย่างเนื้อหา"},
        ],
    },
    {
        "type": "publish_artifact",
        "category": "action",
        "label": "Publish Artifact",
        "description": "คัดลอกไฟล์ที่ Agent สร้างและตรวจสอบแล้วมาเก็บเป็นผลลัพธ์ถาวรของ Workflow run",
        "config_fields": [
            {"name": "auto_source", "label": "ใช้ไฟล์ที่ตรวจสอบแล้วจาก Agent ก่อนหน้า", "type": "boolean", "default": True,
             "hint": "ระบบเลือก artifact ที่ verified โดยอัตโนมัติ"},
            {"name": "source_path", "label": "ไฟล์จาก Agent", "type": "text", "required": False,
             "placeholder": "{{llm_xxx.artifacts.0.path}}",
             "hint": "ใช้เฉพาะกรณีปิดการเลือกอัตโนมัติ", "visible_when": {"field": "auto_source", "equals": False}, "advanced": True},
            {"name": "job_id", "label": "Job context", "type": "job_select", "required": False,
             "hint": "เว้นว่างเพื่อใช้ Job เดียวจากโหนดก่อนหน้า"},
            {"name": "filename", "label": "ชื่อไฟล์ที่เผยแพร่", "type": "text", "required": False,
             "placeholder": "report-contract.docx",
             "hint": "เว้นว่างเพื่อใช้ชื่อเดิมของไฟล์"},
        ],
        "output_fields": [
            {"name": "artifact", "label": "ไฟล์ที่เผยแพร่"},
            {"name": "artifacts", "label": "รายการไฟล์ที่เผยแพร่"},
        ],
    },
    {
        "type": "webhook_response",
        "category": "action",
        "label": "Webhook Response",
        "description": "กำหนด result ที่ caller จะอ่านได้จาก webhook poll endpoint",
        "config_fields": [
            {"name": "visible", "label": "ใช้เป็น result ของ webhook", "type": "boolean", "default": True},
            {"name": "status_code", "label": "HTTP status", "type": "number", "default": 200,
             "placeholder": "200"},
            {"name": "body", "label": "Result body", "type": "textarea", "required": True,
             "placeholder": "{{llm_1.text}}",
             "hint": "ใช้ template เพื่อเลือกผลจากโหนดก่อนหน้า เช่น {{trigger.body.events.0.message.text}}"},
            {"name": "condition_left", "label": "เงื่อนไข: ค่าที่ตรวจ", "type": "text", "required": False,
             "placeholder": "{{condition_1.result}}"},
            {"name": "condition_operator", "label": "เงื่อนไข", "type": "select",
             "options": ["", "equals", "not_equals", "contains", "not_contains", "greater_than",
                         "less_than", "is_empty", "is_not_empty"], "default": ""},
            {"name": "condition_right", "label": "เงื่อนไข: ค่าที่ใช้เทียบ", "type": "text", "required": False,
             "placeholder": "true"},
        ],
        "output_fields": [
            {"name": "visible", "label": "แสดงผลหรือไม่"},
            {"name": "status_code", "label": "HTTP status"},
            {"name": "body", "label": "Result body"},
        ],
    },
    {
        "type": "gdrive_upload",
        "category": "storage",
        "label": "Google Drive: อัปโหลด",
        "description": "อัปโหลดผลลัพธ์ของ workflow ขึ้นโฟลเดอร์ Google Drive",
        "config_fields": [
            {"name": "integration_id", "label": "บัญชี Google Drive", "type": "integration_select",
             "provider": "gdrive", "required": True,
             "hint": "เลือก credential ที่สร้างไว้ในเมนู Integration (ชนิด Google Drive)"},
            {"name": "folder_id", "label": "Folder ID ปลายทาง", "type": "text", "required": True,
             "placeholder": "1AbC...xyz",
             "hint": "คัดลอกจาก URL ของโฟลเดอร์ Drive และต้องแชร์โฟลเดอร์ให้อีเมล service account"},
            {"name": "filename", "label": "ชื่อไฟล์", "type": "text", "default": "result.json",
             "placeholder": "result.json"},
            {"name": "mime_type", "label": "ชนิดไฟล์ (MIME)", "type": "text", "default": "application/json",
             "placeholder": "application/json"},
            {"name": "content", "label": "เนื้อหา", "type": "textarea", "required": True,
             "placeholder": "{{transform_xxx}}",
             "hint": "ใช้ปุ่มแทรกข้อมูลเลือกผลลัพธ์ที่ต้องการอัปโหลด"},
        ],
        "output_fields": [
            {"name": "file_id", "label": "Drive file id"},
            {"name": "name", "label": "ชื่อไฟล์"},
            {"name": "link", "label": "ลิงก์เปิดไฟล์"},
        ],
    },
    {
        "type": "gdrive_import",
        "category": "storage",
        "label": "Google Drive: นำเข้า Job",
        "description": "ดึงทุกไฟล์จากโฟลเดอร์ Google Drive เข้า Job แล้วประมวลผล (OCR) ตามฟังก์ชัน Jobs",
        "config_fields": [
            {"name": "integration_id", "label": "บัญชี Google Drive", "type": "integration_select",
             "provider": "gdrive", "required": True},
            {"name": "folder_id", "label": "Folder ID ต้นทาง", "type": "text", "required": True,
             "placeholder": "1AbC...xyz",
             "hint": "ต้องแชร์โฟลเดอร์ให้อีเมล service account (สิทธิ์อ่าน)"},
            {"name": "job_id", "label": "นำเข้าไปยัง Job", "type": "job_select", "required": True},
            {"name": "schema_id", "label": "Schema สำหรับประมวลผล", "type": "schema_select", "required": False,
             "hint": "Auto = ใช้ Schema ของ Job หรือสกัดอัตโนมัติ; หรือเลือก Schema เฉพาะเพื่อกำหนดให้เอกสารที่นำเข้า"},
            {"name": "wait_for_completion", "label": "รอประมวลผลเอกสารเสร็จทั้งหมด", "type": "boolean", "default": True,
             "hint": "เปิดใช้งาน (ค่าเริ่มต้น): โหนดจะรอให้ OCR & Extraction ทุกเอกสารเสร็จสมบูรณ์ก่อนส่ง output ต่อไปยังโหนดถัดไป; ปิด: นำเข้าไฟล์เข้าคิวแล้วส่ง output ทันที"},
            {"name": "auto_review", "label": "Automatic Review", "type": "boolean", "default": False,
             "hint": "เมื่อเปิดใช้งาน: หลังสกัดข้อมูลสำเร็จ ระบบจะตั้งค่าเป็น Review อัตโนมัติและเปลี่ยนสถานะเป็น reviewed"},
            {"name": "name_filter", "label": "กรองชื่อไฟล์ (optional)", "type": "text", "required": False,
             "placeholder": ".pdf",
             "hint": "เว้นว่าง = ทุกไฟล์; ใส่นามสกุล/คำเช่น .pdf เพื่อกรอง"},
            {"name": "limit", "label": "จำนวนไฟล์สูงสุด", "type": "number", "default": 20, "placeholder": "20"},
        ],
        "output_fields": [
            {"name": "count", "label": "จำนวนไฟล์ที่นำเข้า"},
            {"name": "imported", "label": "รายการที่นำเข้า"},
            {"name": "records", "label": "ข้อมูลผลลัพธ์ (records)"},
            {"name": "documents", "label": "เอกสารพร้อมผลลัพธ์"},
            {"name": "job_id", "label": "Job ปลายทาง"},
        ],
    },
    {
        "type": "onedrive_upload",
        "category": "storage",
        "label": "OneDrive: อัปโหลด",
        "description": "อัปโหลดผลลัพธ์ของ workflow ขึ้นโฟลเดอร์ OneDrive / SharePoint",
        "config_fields": [
            {"name": "integration_id", "label": "บัญชี OneDrive", "type": "integration_select",
             "provider": "onedrive", "required": True,
             "hint": "เลือก credential ที่สร้างไว้ในเมนู Integration (ชนิด OneDrive)"},
            {"name": "folder_id", "label": "Folder item id (เว้นว่าง = root)", "type": "text", "required": False,
             "placeholder": "root",
             "hint": "ระบุ item id ของโฟลเดอร์ หรือเว้นว่างเพื่อใช้รากของ drive"},
            {"name": "filename", "label": "ชื่อไฟล์", "type": "text", "default": "result.json",
             "placeholder": "result.json"},
            {"name": "mime_type", "label": "ชนิดไฟล์ (MIME)", "type": "text", "default": "application/json",
             "placeholder": "application/json"},
            {"name": "content", "label": "เนื้อหา", "type": "textarea", "required": True,
             "placeholder": "{{transform_xxx}}",
             "hint": "ใช้ปุ่มแทรกข้อมูลเลือกผลลัพธ์ที่ต้องการอัปโหลด (ไฟล์ ≤4MB)"},
        ],
        "output_fields": [
            {"name": "file_id", "label": "OneDrive item id"},
            {"name": "name", "label": "ชื่อไฟล์"},
            {"name": "link", "label": "ลิงก์เปิดไฟล์"},
        ],
    },
    {
        "type": "onedrive_import",
        "category": "storage",
        "label": "OneDrive: นำเข้า Job",
        "description": "ดึงทุกไฟล์จากโฟลเดอร์ OneDrive / SharePoint เข้า Job แล้วประมวลผล (OCR)",
        "config_fields": [
            {"name": "integration_id", "label": "บัญชี OneDrive", "type": "integration_select",
             "provider": "onedrive", "required": True},
            {"name": "folder_id", "label": "Folder item id (เว้นว่าง = root)", "type": "text", "required": False,
             "placeholder": "root"},
            {"name": "job_id", "label": "นำเข้าไปยัง Job", "type": "job_select", "required": True},
            {"name": "schema_id", "label": "Schema สำหรับประมวลผล", "type": "schema_select", "required": False,
             "hint": "Auto = ใช้ Schema ของ Job หรือสกัดอัตโนมัติ; หรือเลือก Schema เฉพาะเพื่อกำหนดให้เอกสารที่นำเข้า"},
            {"name": "wait_for_completion", "label": "รอประมวลผลเอกสารเสร็จทั้งหมด", "type": "boolean", "default": True,
             "hint": "เปิดใช้งาน (ค่าเริ่มต้น): โหนดจะรอให้ OCR & Extraction ทุกเอกสารเสร็จสมบูรณ์ก่อนส่ง output ต่อไปยังโหนดถัดไป; ปิด: นำเข้าไฟล์เข้าคิวแล้วส่ง output ทันที"},
            {"name": "auto_review", "label": "Automatic Review", "type": "boolean", "default": False,
             "hint": "เมื่อเปิดใช้งาน: หลังสกัดข้อมูลสำเร็จ ระบบจะตั้งค่าเป็น Review อัตโนมัติและเปลี่ยนสถานะเป็น reviewed"},
            {"name": "name_filter", "label": "กรองชื่อไฟล์ (optional)", "type": "text", "required": False,
             "placeholder": ".pdf",
             "hint": "เว้นว่าง = ทุกไฟล์; ใส่นามสกุล/คำเช่น .pdf เพื่อกรอง"},
            {"name": "limit", "label": "จำนวนไฟล์สูงสุด", "type": "number", "default": 20, "placeholder": "20"},
        ],
        "output_fields": [
            {"name": "count", "label": "จำนวนไฟล์ที่นำเข้า"},
            {"name": "imported", "label": "รายการที่นำเข้า"},
            {"name": "records", "label": "ข้อมูลผลลัพธ์ (records)"},
            {"name": "documents", "label": "เอกสารพร้อมผลลัพธ์"},
            {"name": "job_id", "label": "Job ปลายทาง"},
        ],
    },
]

TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\-\.฀-๿]+)\s*\}\}")


# ── Template resolution ──────────────────────────────────────────────
def _lookup_path(context: Dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    cur: Any = context
    for part in parts:
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
                continue
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
                continue
            except (ValueError, IndexError):
                return None
        return None
    return cur


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def resolve_template(value: Any, context: Dict[str, Any]) -> Any:
    """Resolve {{path}} templates in a string / dict / list recursively."""
    if isinstance(value, str):
        match = TEMPLATE_RE.fullmatch(value.strip())
        if match:
            return _lookup_path(context, match.group(1))
        return TEMPLATE_RE.sub(lambda m: _stringify(_lookup_path(context, m.group(1))), value)
    if isinstance(value, dict):
        return {k: resolve_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_template(v, context) for v in value]
    return value


# ── Node executors ───────────────────────────────────────────────────
class NodeExecutionError(Exception):
    pass


def _exec_trigger(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    log("Workflow triggered")
    return context.get("trigger") or {}


def _workflow_document_extraction(document: Document) -> Dict[str, Any]:
    """Return compact, non-sensitive extraction provenance for workflow steps."""
    metadata = document.extraction_metadata or {}
    mapping = metadata.get("mapping")
    if isinstance(mapping, dict):
        mapping = {
            key: mapping[key]
            for key in ("status", "schema", "provider")
            if key in mapping
        }

    return {
        "pipeline": metadata.get("pipeline") or metadata.get("requested_pipeline") or "unknown",
        "source": metadata.get("source") or "document",
        "provider_counts": metadata.get("provider_counts") or {},
        "text_layer_pages": metadata.get("text_layer_pages") or [],
        "ocr_pages": metadata.get("ocr_pages") or [],
        "mapping": mapping or "not_requested",
        "legacy_fallback": bool(metadata.get("legacy_fallback")),
    }


def _workflow_document_status(status: Any) -> Any:
    """Keep saved workflows using the retired status compatible with AnyDoc."""
    return "extraction_completed" if status == "ocr_completed" else status


def _exec_document_source(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    job_id = config.get("job_id")
    if not job_id:
        raise NodeExecutionError("Document Source: job_id is required")
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise NodeExecutionError(f"Job not found: {job_id}")

    query = db.query(Document).filter(Document.job_id == job_id)
    status = _workflow_document_status(config.get("status"))
    if status:
        query = query.filter(Document.status == status)
    elif config.get("only_completed", True):
        query = query.filter(Document.status.in_(COMPLETED_DOC_STATUSES))
    limit = int(config.get("limit") or 10)
    docs = query.order_by(Document.uploaded_at.desc()).limit(limit).all()
    include_ocr = config.get("include_ocr_text", True)

    log(f"Job '{job.name or job_id}': loaded {len(docs)} document(s)")
    documents = []
    for d in docs:
        item: Dict[str, Any] = {
            "id": str(d.id),
            "filename": d.filename,
            "status": d.status,
            "extracted_data": d.reviewed_data or d.extracted_data,
            "extraction": _workflow_document_extraction(d),
        }
        if include_ocr:
            item["ocr_text"] = d.ocr_text
        documents.append(item)
    return {"job_id": str(job_id), "job_name": job.name, "count": len(documents), "documents": documents}


COMPLETED_DOC_STATUSES = {"extraction_completed", "reviewed"}


def _exec_job_source(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    """Bring processed data from a Job into the workflow.

    Output:
        {job_id, job_name, job_status, count,
         records: [<data per document>],   # convenient for downstream LLM/Transform
         documents: [{id, filename, status, data}]}
    """
    job_id = config.get("job_id")
    if not job_id:
        raise NodeExecutionError("Jobs node: job_id is required")
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise NodeExecutionError(f"Job not found: {job_id}")

    query = db.query(Document).filter(Document.job_id == job_id)
    status = _workflow_document_status(config.get("status"))
    if status:
        query = query.filter(Document.status == status)
    elif config.get("only_completed", True):
        query = query.filter(Document.status.in_(COMPLETED_DOC_STATUSES))

    limit = int(config.get("limit") or 50)
    docs = query.order_by(Document.uploaded_at.desc()).limit(limit).all()

    data_source = (config.get("data_source") or "reviewed").lower()
    log(f"Job '{job.name or job_id}' (status={job.status}): loaded {len(docs)} document(s) [data_source={data_source}]")

    documents: List[Dict[str, Any]] = []
    records: List[Any] = []
    for d in docs:
        if data_source == "ocr_text":
            data: Any = d.ocr_text
        elif data_source == "extracted":
            data = d.extracted_data
        else:  # reviewed — prefer reviewed_data, fall back to extracted_data
            data = d.reviewed_data if d.reviewed_data is not None else d.extracted_data
        records.append(data)
        documents.append({
            "id": str(d.id),
            "filename": d.filename,
            "status": d.status,
            "data": data,
            "extraction": _workflow_document_extraction(d),
        })

    return {
        "job_id": str(job_id),
        "job_name": job.name,
        "job_status": job.status,
        "count": len(documents),
        "records": records,
        "documents": documents,
    }


def _normalize_openai_base_url(base_url: Optional[str]) -> Optional[str]:
    if not base_url:
        return None
    normalized = base_url.strip().rstrip("/")
    if normalized.lower().endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return normalized


def _ai_setting_provider(setting: AISettings, model: Optional[str], source: str) -> Dict[str, Any]:
    provider_type = getattr(setting, "provider_type", None) or "completion_messages"
    resolved_model = (model or "").strip() or getattr(setting, "model", None) or "gpt-4o-mini"
    if provider_type == "openai_compatible":
        return {
            "provider": "openai_compatible",
            "apiKey": setting.api_key,
            "baseUrl": setting.api_url,
            "model": resolved_model,
            "source": source,
            "name": setting.display_name or setting.name,
            "supports_tool_calling": bool(getattr(setting, "supports_tool_calling", False)),
        }
    return {
        "provider": "completion_messages",
        "apiUrl": setting.api_url,
        "apiKey": setting.api_key,
        "model": resolved_model,
        "source": source,
        "name": setting.display_name or setting.name,
        "supports_tool_calling": False,
    }


def _ensure_integration_owner(integration: Integration, owner_user_id: Optional[str]) -> None:
    """Block a workflow from using another user's Integration credentials."""
    if owner_user_id is None:
        return  # legacy workflow without an owner — nothing to enforce
    if integration.user_id is not None and str(integration.user_id) != str(owner_user_id):
        raise NodeExecutionError(
            f"Integration '{integration.name}' belongs to another user"
        )


def _integration_type_value(integration: Integration) -> str:
    value = getattr(integration, "type", "")
    return value.value if hasattr(value, "value") else str(value)


def _workflow_provider_ref(provider_ref: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Parse the provider selected by a Workflow LLM / Agent node.

    `default` deliberately overrides legacy fields so a user can return a
    migrated node to the centrally configured provider.
    """
    raw = str(provider_ref or "").strip()
    if not raw or raw == "default":
        return None, None
    if ":" not in raw:
        raise NodeExecutionError("AI provider reference is invalid")
    source, raw_id = raw.split(":", 1)
    if source not in {"ai", "integration"}:
        raise NodeExecutionError("AI provider reference source is invalid")
    try:
        provider_id = str(UUID(raw_id))
    except (TypeError, ValueError) as exc:
        raise NodeExecutionError("AI provider reference id is invalid") from exc
    return source, provider_id


def resolve_llm_provider(
    db: Session,
    integration_id: Optional[str] = None,
    model: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
    ai_provider_id: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    provider_ref: Optional[str] = None,
    mode: str = "llm",
) -> Dict[str, Any]:
    """Resolve the provider for Workflow LLM nodes.

    Priority:
    1. Explicit provider reference selected on the node
    2. Legacy explicit AI Settings provider selected on the node
    3. Legacy explicit LLM Integration ID on the node
    3. Mode-specific system provider (Agent Provider for Agent mode; default
       AI provider for LLM mode)
    4. Relevant environment fallback
    5. Remaining default provider / OPENAI_API_KEY fallback
    6. First active LLM Integration for backward compatibility
    """

    def _log(msg: str) -> None:
        if log:
            log(msg)

    requested_model = (model or "").strip() or None

    source, selected_id = _workflow_provider_ref(provider_ref)
    if source == "ai":
        ai_provider_id = selected_id
        integration_id = None
    elif source == "integration":
        integration_id = selected_id
        ai_provider_id = None
    elif str(provider_ref or "").strip() == "default":
        ai_provider_id = None
        integration_id = None

    if ai_provider_id:
        ai_setting = db.query(AISettings).filter(AISettings.id == ai_provider_id, AISettings.is_active == True).first()
        if not ai_setting:
            raise NodeExecutionError(f"AI provider not found or inactive: {ai_provider_id}")
        if not ai_setting.api_url or not ai_setting.api_key:
            raise NodeExecutionError(f"AI provider '{ai_setting.display_name or ai_setting.name}' is missing URL or key")
        provider = _ai_setting_provider(ai_setting, requested_model, "workflow_ai_provider")
        _log(f"Using selected AI provider '{provider['name']}' ({provider['provider']}, model={provider['model']})")
        return provider

    if integration_id:
        integration = db.query(Integration).filter(Integration.id == integration_id).first()
        if not integration:
            raise NodeExecutionError(f"Integration not found: {integration_id}")
        _ensure_integration_owner(integration, owner_user_id)
        if _integration_type_value(integration) not in {
            IntegrationType.LLM.value,
            IntegrationType.SOFTNIX_GENAI.value,
        }:
            raise NodeExecutionError("Selected integration is not an LLM provider")
        status = getattr(integration, "status", "")
        status_value = status.value if hasattr(status, "value") else str(status)
        if status_value != IntegrationStatus.ACTIVE.value:
            raise NodeExecutionError(f"LLM integration '{integration.name}' is not active")
        icfg = integration.config or {}
        api_key = _integration_api_key(integration)
        if not api_key:
            raise NodeExecutionError(f"LLM integration '{integration.name}' is missing apiKey")
        provider = {
            "provider": "openai_compatible",
            "apiKey": api_key,
            "baseUrl": _llm_base_url_for_integration(integration),
            "model": requested_model or icfg.get("model") or "gpt-4o-mini",
            "source": "workflow_llm_integration",
            "name": integration.name,
            "supports_tool_calling": integration_supports_tool_calling(integration),
        }
        _log(f"Using LLM integration '{integration.name}' (model={provider['model']})")
        return provider

    if mode == "agent":
        agent_setting = (
            db.query(AISettings)
            .filter(AISettings.is_agent_provider == True, AISettings.is_active == True)
            .first()
        )
        if agent_setting and agent_setting.api_url and agent_setting.api_key:
            provider = _ai_setting_provider(agent_setting, requested_model, "ai_settings_agent_provider")
            _log(f"Using AI Settings Agent Provider '{provider['name']}' ({provider['provider']}, model={provider['model']})")
            return provider

        if settings.AGENT_PROVIDER_KEY:
            provider = {
                "provider": "openai_compatible",
                "apiKey": settings.AGENT_PROVIDER_KEY,
                "baseUrl": settings.AGENT_PROVIDER_URL,
                "model": requested_model or settings.AGENT_MODEL or "gpt-4o-mini",
                "source": "system_agent_provider",
                "name": "System Agent Provider",
                "supports_tool_calling": True,
            }
            _log(f"Using system Agent Provider (model={provider['model']})")
            return provider

    default_setting = (
        db.query(AISettings)
        .filter(AISettings.is_default == True, AISettings.is_active == True)
        .first()
    )
    if default_setting and default_setting.api_url and default_setting.api_key:
        provider = _ai_setting_provider(default_setting, requested_model, "ai_settings_default_provider")
        _log(f"Using AI Settings default provider '{provider['name']}' ({provider['provider']}, model={provider['model']})")
        return provider

    if settings.OPENAI_API_KEY:
        provider = {
            "provider": "openai_compatible",
            "apiKey": settings.OPENAI_API_KEY,
            "baseUrl": None,
            "model": requested_model or "gpt-4o-mini",
            "source": "system_openai_api_key",
            "name": "OPENAI_API_KEY",
            "supports_tool_calling": True,
        }
        _log(f"Using system OPENAI_API_KEY (model={provider['model']})")
        return provider

    fallback = (
        db.query(Integration)
        .filter(
            Integration.type.in_((IntegrationType.LLM, IntegrationType.SOFTNIX_GENAI)),
            Integration.status == IntegrationStatus.ACTIVE,
        )
        .order_by(Integration.created_at.asc())
        .first()
    )
    if fallback:
        icfg = fallback.config or {}
        api_key = _integration_api_key(fallback)
        if api_key:
            provider = {
                "provider": "openai_compatible",
                "apiKey": api_key,
                "baseUrl": _llm_base_url_for_integration(fallback),
                "model": requested_model or icfg.get("model") or "gpt-4o-mini",
                "source": "fallback_llm_integration",
                "name": fallback.name,
                "supports_tool_calling": integration_supports_tool_calling(fallback),
            }
            _log(f"Using fallback LLM integration '{fallback.name}' (model={provider['model']})")
            return provider

    raise NodeExecutionError("ยังไม่ได้ตั้งค่า LLM — ตั้งค่า Setting AI > Agent Provider หรือ Default AI provider ก่อน")


def _call_openai_compatible(provider: Dict[str, Any], messages: List[Dict[str, str]]) -> str:
    from openai import OpenAI

    client_kwargs: Dict[str, Any] = {"api_key": provider["apiKey"]}
    base_url = _normalize_openai_base_url(provider.get("baseUrl"))
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    try:
        response = client.chat.completions.create(model=provider["model"], messages=messages, temperature=0.2)
    except Exception as exc:  # noqa: BLE001 - some providers reject temperature
        if "temperature" not in str(exc).lower():
            raise
        response = client.chat.completions.create(model=provider["model"], messages=messages)
    return response.choices[0].message.content or "" if response.choices else ""


def _call_completion_messages(provider: Dict[str, Any], prompt: str, system_prompt: str) -> str:
    payload = {
        "inputs": {
            "ocr_content": prompt,
            "document_type": "workflow",
            "workflow_prompt": prompt,
            "agent_prompt": prompt,
            "system_prompt": system_prompt,
            "model": provider.get("model"),
        },
        "user": "workflow",
        "citation": False,
        "response_mode": "blocking",
    }
    response = http_requests.post(
        provider["apiUrl"],
        json=payload,
        headers={
            "Authorization": f"Bearer {provider['apiKey']}",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        return response.text
    return str(data.get("answer") or data.get("text") or data.get("output") or data.get("result") or "")


def call_llm_provider(provider: Dict[str, Any], prompt: str, system_prompt: Optional[str] = None) -> str:
    system_text = (system_prompt or "").strip()
    if provider.get("provider") == "completion_messages":
        return _call_completion_messages(provider, prompt, system_text)

    messages: List[Dict[str, str]] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": prompt})
    return _call_openai_compatible(provider, messages)


# Backward-compatible helper for callers that still expect an OpenAI client.
def resolve_llm_client(
    db: Session,
    integration_id: Optional[str] = None,
    model: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
):
    from openai import OpenAI

    provider = resolve_llm_provider(db, integration_id, model, log)
    if provider.get("provider") != "openai_compatible":
        raise NodeExecutionError("Selected AI provider is not OpenAI-compatible")
    client_kwargs: Dict[str, Any] = {"api_key": provider["apiKey"]}
    base_url = _normalize_openai_base_url(provider.get("baseUrl"))
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs), provider["model"]

def _exec_llm(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    prompt = config.get("prompt")
    if not prompt:
        raise NodeExecutionError("LLM node: prompt is required")

    provider = resolve_llm_provider(
        db,
        config.get("integration_id"),
        config.get("model"),
        log,
        config.get("ai_provider_id"),
        owner_user_id=context.get("_owner_user_id"),
        provider_ref=config.get("provider_ref"),
        mode=config.get("mode") or "llm",
    )
    if (config.get("mode") or "llm") == "agent":
        # Resolved providers explicitly carry this flag. Keep direct callers
        # that use the historical provider dict shape backward compatible.
        if provider.get("supports_tool_calling", True) is False:
            raise NodeExecutionError(
                "Selected AI provider does not support native tool calling required by Agent mode"
            )
        from uuid import UUID

        from app.services.workflow_agent import (
            WorkflowAgentConfigurationError,
            run_workflow_agent,
        )
        from app.services.workflow_agent_contracts import FILE_OUTPUT_FORMATS

        owner_user_id = context.get("_owner_user_id")
        if not owner_user_id:
            raise NodeExecutionError("Agent node requires a Workflow owner")
        job_id = config.get("job_id") or config.get("_inferred_job_id")
        output_format = str(config.get("output_format") or "text").lower()
        if output_format in FILE_OUTPUT_FORMATS and not job_id:
            raise NodeExecutionError(
                "Agent file output requires Job context; select a Job or connect a single upstream Job node"
            )
        skill_ids = config.get("skill_ids") or []
        if not isinstance(skill_ids, list):
            raise NodeExecutionError("Agent node skill_ids must be a list")
        raw_fingerprints = config.get("skill_fingerprints") or {}
        if not isinstance(raw_fingerprints, dict):
            raise NodeExecutionError("Agent node skill_fingerprints must be an object")
        prompt = _stringify(config.get("prompt"))
        dossier = config.get("_workflow_dossier")
        if isinstance(dossier, list) and dossier:
            prompt += "\n\n## Workflow dossier (authoritative source data)\n" + _stringify(dossier)
        handoffs = config.get("_upstream_agent_handoffs")
        if isinstance(handoffs, list) and handoffs:
            prompt += "\n\n## Verified upstream handoffs\n" + _stringify(handoffs)
        raw_max_output_tokens = config.get("max_output_tokens")
        try:
            result = asyncio.run(run_workflow_agent(
                db,
                user_id=UUID(str(owner_user_id)),
                job_id=UUID(str(job_id)) if job_id else None,
                provider=provider,
                prompt=prompt,
                skill_ids=[str(item) for item in skill_ids],
                skill_fingerprints={
                    str(key): str(value)
                    for key, value in raw_fingerprints.items()
                },
                output_format=output_format,
                output_filename=(str(config.get("output_filename") or "").strip() or None),
                max_iterations=int(config.get("max_iterations") or 7),
                timeout_seconds=int(config.get("timeout_seconds") or 300),
                agent_task=str(config.get("agent_task") or "custom"),
                # Lets a node using a small-context model stay under its limit
                # instead of relying solely on the task preset's fixed budget.
                max_output_tokens=(
                    int(raw_max_output_tokens) if raw_max_output_tokens not in (None, "") else None
                ),
                workflow_run_id=str(context.get("_run_id") or ""),
                workflow_node_id=str(context.get("_node_id") or ""),
            ))
        except (ValueError, WorkflowAgentConfigurationError) as exc:
            raise NodeExecutionError(f"Agent node configuration error: {exc}") from exc
        metrics = result.get("metrics") or {}
        log(
            f"Agent finished with status={result.get('status')} "
            f"iterations={result.get('iterations')} artifacts={len(result.get('artifacts') or [])} "
            f"stop_reason={metrics.get('stop_reason')}"
        )
        tools_used = result.get("tool_summary") or []
        if tools_used:
            log("Agent tools: " + ", ".join(
                f"{item.get('tool')}{'' if item.get('ok') else ' (failed)'}" for item in tools_used
            ))
        for warning in (result.get("warnings") or []):
            log(f"Warning: {warning}")
        if result.get("status") != "succeeded":
            detail = result.get("error") or "; ".join(result.get("warnings") or [])
            raise NodeExecutionError(detail or result.get("text") or "Agent did not complete successfully")
        return result

    text = call_llm_provider(provider, _stringify(prompt), config.get("system_prompt"))
    log(f"LLM responded via {provider.get('source')} ({len(text)} chars)")

    if config.get("json_output"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            return {"text": text, "data": json.loads(cleaned)}
        except json.JSONDecodeError:
            log("Warning: LLM output is not valid JSON — returning raw text")
            return {"text": text, "data": None}
    return {"text": text}


def suggest_variables(
    db: Session,
    query: str,
    candidates: List[Dict[str, Any]],
    integration_id: Optional[str] = None,
    owner_user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """AI variable finder. Given a natural-language description and a catalog
    of available variables (token/label/sample), ask the LLM to rank the best
    matches. Returns [{token, reason, confidence}] limited to known tokens.

    The LLM only *selects* from the supplied tokens — sample values are
    rendered client-side from real run data, so it can't fabricate values.
    """
    valid_tokens = {c.get("token") for c in candidates if c.get("token")}
    if not valid_tokens:
        return []

    # Compact catalog so the prompt stays small even with many fields.
    lines = []
    for c in candidates[:200]:
        token = c.get("token")
        if not token:
            continue
        label = str(c.get("label") or "").strip()
        sample = str(c.get("sample") or "").replace("\n", " ")[:80]
        ctype = c.get("type") or ""
        lines.append(f"- {token} | label: {label} | type: {ctype} | ตัวอย่าง: {sample}")
    catalog = "\n".join(lines)

    system = (
        "You are a data-field matcher for a no-code workflow builder. "
        "The user describes (in Thai or English) the data they want to insert. "
        "Choose the variable tokens from the provided catalog that best match the request. "
        "Match on meaning, label, sample values, and field naming — Thai and English are equivalent "
        "(e.g. 'เลขที่ใบแจ้งหนี้' ≈ 'invoice number' ≈ 'Invoice_No'). "
        "Return STRICT JSON only: an array of at most 5 objects "
        '{"token": <exact token string from the catalog>, '
        '"reason": <short Thai explanation>, '
        '"confidence": <"high"|"medium"|"low">}. '
        "Order by relevance, best first. Use ONLY tokens that appear verbatim in the catalog. "
        "If nothing matches, return an empty array []."
    )
    user = f"คำขอของผู้ใช้: {query}\n\nรายการตัวแปรที่มี (catalog):\n{catalog}"

    provider = resolve_llm_provider(db, integration_id, None, None, owner_user_id=owner_user_id)
    text = call_llm_provider(provider, user, system)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Some models wrap the array in an object — try to dig it out.
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not m:
            raise NodeExecutionError("AI ไม่สามารถตีความผลลัพธ์ได้ ลองพิมพ์คำอธิบายใหม่")
        parsed = json.loads(m.group(0))

    if isinstance(parsed, dict):
        # Tolerate {"results": [...]} or {"matches": [...]}
        for key in ("results", "matches", "data", "tokens"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]

    results: List[Dict[str, Any]] = []
    seen: set = set()
    for item in parsed if isinstance(parsed, list) else []:
        if not isinstance(item, dict):
            continue
        token = item.get("token")
        if token not in valid_tokens or token in seen:
            continue
        seen.add(token)
        conf = str(item.get("confidence") or "medium").lower()
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        results.append({
            "token": token,
            "reason": str(item.get("reason") or "")[:200],
            "confidence": conf,
        })
        if len(results) >= 5:
            break
    return results


def _evaluate_condition(left: Any, operator: str, right: Any) -> bool:
    def as_number(v: Any) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if operator == "is_empty":
        return left is None or left == "" or left == [] or left == {}
    if operator == "is_not_empty":
        return not (left is None or left == "" or left == [] or left == {})
    if operator == "contains":
        return _stringify(right) in _stringify(left)
    if operator == "not_contains":
        return _stringify(right) not in _stringify(left)
    if operator in ("greater_than", "less_than"):
        ln, rn = as_number(left), as_number(right)
        if ln is None or rn is None:
            raise NodeExecutionError(f"Condition: cannot compare non-numeric values ({left!r} vs {right!r})")
        return ln > rn if operator == "greater_than" else ln < rn
    if operator == "not_equals":
        return _stringify(left) != _stringify(right)
    return _stringify(left) == _stringify(right)


def _exec_condition(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    left = config.get("left")
    right = config.get("right")
    operator = config.get("operator") or "equals"
    result = _evaluate_condition(left, operator, right)

    log(f"Condition: {left!r} {operator} {right!r} → {result}")
    return {"result": result}


def _exec_transform(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    mappings = config.get("mappings") or []
    out: Dict[str, Any] = {}
    for m in mappings:
        target = (m or {}).get("target")
        if target:
            out[target] = m.get("value")
    log(f"Transform produced {len(out)} field(s)")
    return out


def _exec_python_code(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    from app.services.code_sandbox import execute_python

    code = config.get("code")
    if not code:
        raise NodeExecutionError("Python node: code is required")
    timeout = int(config.get("timeout") or 30)
    node_input = config.get("input")
    if isinstance(node_input, str) and node_input.strip():
        try:
            node_input = json.loads(node_input)
        except json.JSONDecodeError:
            node_input = {"value": node_input}
    inputs = node_input if isinstance(node_input, dict) else {"value": node_input}

    log("Executing Python code in sandbox…")
    result = asyncio.run(execute_python(code, inputs=inputs, timeout=timeout))
    stdout = result.get("stdout")
    if stdout:
        log(f"stdout:\n{stdout}")
    if result.get("error"):
        err = result["error"]
        message = err.get("message") if isinstance(err, dict) else str(err)
        raise NodeExecutionError(f"Python error: {message}")
    return {"result": result.get("result"), "stdout": stdout}


def _validate_outbound_url(url: str) -> tuple[Any, str]:
    """Validate an outbound URL and return one approved, pinned IP address.

    A request made by hostname would resolve DNS a second time inside the HTTP
    client. Returning the approved address lets Custom API requests connect to
    that exact address and prevents DNS rebinding from reaching private hosts.
    """
    import ipaddress

    parsed = urlparse(str(url))
    if parsed.scheme not in ("http", "https"):
        raise NodeExecutionError(f"HTTP node: unsupported URL scheme '{parsed.scheme}'")
    host = parsed.hostname
    if not host:
        raise NodeExecutionError("HTTP node: URL has no host")
    if parsed.username or parsed.password:
        raise NodeExecutionError("HTTP node: URL must not include credentials")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise NodeExecutionError(f"HTTP node: cannot resolve host '{host}': {exc}")
    addresses: List[str] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        raise NodeExecutionError(f"HTTP node: cannot resolve host '{host}'")

    private_networks_allowed = os.environ.get("WORKFLOW_HTTP_ALLOW_PRIVATE", "").lower() in ("1", "true", "yes")
    if not private_networks_allowed:
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise NodeExecutionError(
                    f"HTTP node: target '{host}' resolves to a private address ({ip}) — blocked. "
                    "Set WORKFLOW_HTTP_ALLOW_PRIVATE=true to allow internal targets."
                )
    return parsed, addresses[0]


class _PinnedAddressAdapter(HTTPAdapter):
    """Connect Requests to a validated IP while preserving Host and HTTPS SNI."""

    def __init__(self, hostname: str, host_header: str, address: str) -> None:
        super().__init__()
        self.hostname = hostname
        self.host_header = host_header
        self.address = address

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        if proxies:
            raise NodeExecutionError("Custom API ผ่าน proxy ไม่ได้รับอนุญาต")
        host_params, pool_kwargs = self.build_connection_pool_key_attributes(request, verify, cert)
        host_params["host"] = self.address
        if request.url.lower().startswith("https://"):
            pool_kwargs["assert_hostname"] = self.hostname
            pool_kwargs["server_hostname"] = self.hostname
        return self.poolmanager.connection_from_host(**host_params, pool_kwargs=pool_kwargs)

    def add_headers(self, request, **kwargs):
        super().add_headers(request, **kwargs)
        request.headers.setdefault("Host", self.host_header)


def _request_custom_api(method: str, url: str, **kwargs: Any) -> Any:
    """Perform a Custom API request through the validated DNS address only."""
    parsed, address = _validate_outbound_url(url)
    host_header = parsed.netloc.rsplit("@", 1)[-1]
    session = http_requests.Session()
    session.trust_env = False
    session.mount(
        f"{parsed.scheme}://",
        _PinnedAddressAdapter(parsed.hostname or "", host_header, address),
    )
    try:
        response = session.request(method, url, stream=True, **kwargs)
    except Exception:
        session.close()
        raise
    # Keep the session alive until the streamed response has been fully read.
    response._insightdoc_session = session
    return response


def _read_custom_api_response(response: Any) -> Any:
    """Read a bounded Custom API response and parse JSON when available."""
    raw_length = response.headers.get("Content-Length")
    if raw_length:
        try:
            if int(raw_length) > WORKFLOW_API_MAX_RESPONSE_BYTES:
                response.close()
                session = getattr(response, "_insightdoc_session", None)
                if session is not None:
                    session.close()
                raise NodeExecutionError(f"API node: response exceeds {WORKFLOW_API_MAX_RESPONSE_BYTES} bytes")
        except ValueError:
            pass

    chunks: List[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > WORKFLOW_API_MAX_RESPONSE_BYTES:
                raise NodeExecutionError(
                    f"API node: response exceeds {WORKFLOW_API_MAX_RESPONSE_BYTES} bytes"
                )
            chunks.append(chunk)
    finally:
        response.close()
        session = getattr(response, "_insightdoc_session", None)
        if session is not None:
            session.close()

    text = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:5000]


def _exec_http_request(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    url = config.get("url")
    if not url:
        raise NodeExecutionError("HTTP node: url is required")
    _validate_outbound_url(url)
    method = (config.get("method") or "POST").upper()

    headers: Dict[str, str] = {}
    raw_headers = config.get("headers")
    if isinstance(raw_headers, dict):
        headers = {str(k): str(v) for k, v in raw_headers.items()}
    elif isinstance(raw_headers, str) and raw_headers.strip():
        try:
            headers = json.loads(raw_headers)
        except json.JSONDecodeError:
            raise NodeExecutionError("HTTP node: headers must be valid JSON")

    body = config.get("body")
    kwargs: Dict[str, Any] = {"headers": headers, "timeout": 60}
    if body is not None and method != "GET":
        if isinstance(body, (dict, list)):
            kwargs["json"] = body
        else:
            try:
                kwargs["json"] = json.loads(str(body))
            except json.JSONDecodeError:
                kwargs["data"] = str(body)

    log(f"{method} {url}")
    resp = http_requests.request(method, url, **kwargs)
    log(f"Response: HTTP {resp.status_code}")
    try:
        payload: Any = resp.json()
    except ValueError:
        payload = resp.text[:5000]
    if resp.status_code >= 400:
        raise NodeExecutionError(f"HTTP {resp.status_code}: {_stringify(payload)[:500]}")
    return {"status_code": resp.status_code, "body": payload}


def _custom_api_headers(integration: Integration) -> Dict[str, str]:
    """Build headers from a saved Custom API integration without exposing them to the workflow."""
    config = integration.config or {}
    headers: Dict[str, str] = {"Content-Type": "application/json"}

    auth_header = config.get("authHeader")
    if auth_header:
        for line in str(auth_header).splitlines():
            name, separator, value = line.partition(":")
            if separator and name.strip():
                headers[name.strip()] = value.strip()

    raw_headers = config.get("headersJson")
    if isinstance(raw_headers, dict):
        headers.update({str(name): str(value) for name, value in raw_headers.items()})
    elif isinstance(raw_headers, str) and raw_headers.strip():
        try:
            parsed = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise NodeExecutionError(
                f"Custom API '{integration.name}' มี Headers (JSON) ไม่ถูกต้อง"
            ) from exc
        if not isinstance(parsed, dict):
            raise NodeExecutionError(f"Custom API '{integration.name}' ต้องกำหนด Headers เป็น JSON object")
        headers.update({str(name): str(value) for name, value in parsed.items()})

    return headers


def _exec_api(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    """Send templated upstream data through a saved Custom API integration."""
    integration_id = config.get("integration_id")
    if not integration_id:
        raise NodeExecutionError("API node: ต้องเลือก Custom API ก่อน")

    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        raise NodeExecutionError("API node: ไม่พบ Custom API ที่เลือก")
    _ensure_integration_owner(integration, (context or {}).get("_owner_user_id"))
    if integration.type != IntegrationType.API:
        raise NodeExecutionError(f"API node: integration '{integration.name}' ไม่ใช่ Custom API")
    if integration.status != IntegrationStatus.ACTIVE:
        raise NodeExecutionError(f"API node: Custom API '{integration.name}' ยังไม่พร้อมใช้งาน")

    integration_config = integration.config or {}
    url = str(integration_config.get("endpoint") or "").strip()
    if not url:
        raise NodeExecutionError(f"API node: Custom API '{integration.name}' ไม่มี Endpoint URL")
    method = str(integration_config.get("method") or "POST").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise NodeExecutionError(f"API node: Custom API '{integration.name}' ใช้ HTTP method ที่ไม่รองรับ")

    # A workflow body is intentionally the first choice: it is where values from
    # upstream nodes are resolved. The saved template remains a reusable default.
    body = config.get("body")
    if body is None or (isinstance(body, str) and not body.strip()):
        body = resolve_template(integration_config.get("payloadTemplate"), context)

    try:
        timeout_seconds = int(config.get("timeout_seconds") or 30)
    except (TypeError, ValueError) as exc:
        raise NodeExecutionError("API node: Timeout ต้องเป็นตัวเลข") from exc
    if not 1 <= timeout_seconds <= 120:
        raise NodeExecutionError("API node: Timeout ต้องอยู่ระหว่าง 1 ถึง 120 วินาที")

    kwargs: Dict[str, Any] = {
        "headers": _custom_api_headers(integration),
        "timeout": timeout_seconds,
        # Do not follow redirects: the target is checked above and a redirect
        # could otherwise bypass the outbound-network protection.
        "allow_redirects": False,
    }
    if body is not None and method != "GET":
        if isinstance(body, (dict, list)):
            kwargs["json"] = body
        else:
            try:
                kwargs["json"] = json.loads(str(body))
            except json.JSONDecodeError:
                kwargs["data"] = str(body)

    log(f"{method} ผ่าน Custom API '{integration.name}'")
    try:
        response = _request_custom_api(method, url, **kwargs)
    except http_requests.RequestException as exc:
        raise NodeExecutionError(f"API node: เรียก Custom API '{integration.name}' ไม่สำเร็จ: {exc}") from exc

    log(f"Response: HTTP {response.status_code}")
    payload = _read_custom_api_response(response)
    if response.status_code >= 400:
        raise NodeExecutionError(f"HTTP {response.status_code}: {_stringify(payload)[:500]}")

    return {
        "integration_id": str(integration.id),
        "integration_name": integration.name,
        "status_code": response.status_code,
        "body": payload,
    }


_WRITE_OUTPUT_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "text": "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _exec_write_output(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    content = config.get("content")
    fmt = (config.get("format") or "json").lower()
    filename = os.path.basename(str(config.get("filename") or f"output.{fmt}"))  # no path traversal
    # Ensure the extension matches the format so the file opens correctly.
    if not filename.lower().endswith(f".{fmt}"):
        filename = f"{os.path.splitext(filename)[0] or 'output'}.{fmt}"

    run_id = context.get("_run_id", "unknown")

    text_preview: str
    if fmt in ("xlsx", "docx"):
        data = _to_xlsx_bytes(content) if fmt == "xlsx" else _to_docx_bytes(content)
        text_preview = f"({fmt.upper()} binary, {len(data)} bytes)"
    else:
        if fmt == "json":
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    pass
            text = json.dumps(content, ensure_ascii=False, indent=2)
        elif fmt == "csv":
            text = _to_csv(content)
        else:
            text = _stringify(content)
        data = text.encode("utf-8")
        text_preview = text[:2000]

    # Store via the storage service (shared volume / MinIO / S3) so the API
    # container can serve the file no matter which worker wrote it.
    storage_key = f"{WORKFLOW_OUTPUT_DIR}/{run_id}/{filename}"
    get_storage_service().upload_file(
        BytesIO(data),
        storage_key,
        content_type=_WRITE_OUTPUT_CONTENT_TYPES.get(fmt, "application/octet-stream"),
    )
    log(f"Wrote {len(data)} bytes to {storage_key}")
    return {"file_path": storage_key, "filename": filename, "size": len(data),
            "preview": text_preview, "run_id": str(run_id)}


def _job_output_storage_key(job_id: str, path: str) -> tuple[str, str]:
    """Resolve an Agent artifact into its Job-scoped storage key.

    Agent tools return a job-relative ``outputs/...`` path. Accept the fully
    scoped form as well, but never let a workflow read another Job or escape the
    outputs directory.
    """
    clean_path = str(path or "").strip().replace("\\", "/").lstrip("/")
    current_prefix = f"jobs/{job_id}/"
    if clean_path.startswith(current_prefix):
        clean_path = clean_path[len(current_prefix):]
    elif clean_path.startswith("jobs/"):
        raise NodeExecutionError("Publish Artifact: cross-job paths are not allowed")

    parts = PurePosixPath(clean_path).parts
    if not parts or parts[0] != "outputs" or ".." in parts:
        raise NodeExecutionError("Publish Artifact: source_path must be a file under outputs/")
    if clean_path.endswith("/") or len(parts) < 2:
        raise NodeExecutionError("Publish Artifact: source_path must reference a file")
    return f"jobs/{job_id}/{clean_path}", clean_path


def _exec_publish_artifact(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    """Publish a verified Job artifact into the immutable Workflow-run scope."""
    source_path = config.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise NodeExecutionError("Publish Artifact: source_path is required")

    job_id = config.get("job_id") or config.get("_inferred_job_id")
    if not job_id:
        raise NodeExecutionError("Publish Artifact: select Job context or connect a single upstream Job")

    source_key, display_path = _job_output_storage_key(str(job_id), source_path)
    source_name = os.path.basename(display_path)
    filename = os.path.basename(str(config.get("filename") or source_name).strip())
    if not filename or filename in {".", ".."}:
        raise NodeExecutionError("Publish Artifact: filename is invalid")

    run_id = str(context.get("_run_id") or "")
    node_id = str(context.get("_node_id") or "artifact")
    if not run_id:
        raise NodeExecutionError("Publish Artifact: workflow run context is missing")

    storage_key = f"{WORKFLOW_OUTPUT_DIR}/{run_id}/{node_id}/{filename}"
    storage = get_storage_service()
    if not storage.exists(source_key):
        raise NodeExecutionError(f"Publish Artifact: source file not found: {display_path}")

    with storage.get_local_path(source_key) as local_path:
        source_size = os.path.getsize(local_path)
        if source_size > MAX_WORKFLOW_ARTIFACT_BYTES:
            raise NodeExecutionError(
                "Publish Artifact: source file exceeds the 50 MB workflow artifact limit"
            )
        with open(local_path, "rb") as source_file:
            if source_size == 0:
                raise NodeExecutionError(f"Publish Artifact: source file is empty: {display_path}")
            mime_type = guess_type(filename)[0] or "application/octet-stream"
            storage.upload_file(source_file, storage_key, content_type=mime_type)
    if not storage.exists(storage_key):
        raise NodeExecutionError("Publish Artifact: published file could not be verified")

    artifact = {
        "filename": filename,
        "path": display_path,
        "storage_key": storage_key,
        "source_scope": "job",
        "type": os.path.splitext(filename)[1].lstrip(".").lower() or "file",
        "mime_type": mime_type,
        "size": source_size,
        "verified": True,
        "published": True,
    }
    log(f"Published {display_path} as {storage_key} ({source_size} bytes)")
    return {"artifact": artifact, "artifacts": [artifact]}


def _exec_webhook_response(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    visible = bool(config.get("visible", True))
    operator = config.get("condition_operator") or ""
    if operator:
        left = config.get("condition_left")
        right = config.get("condition_right")
        visible = visible and _evaluate_condition(left, operator, right)
        log(f"Webhook response condition: {left!r} {operator} {right!r} → {visible}")

    status_code = int(config.get("status_code") or 200)
    if status_code < 100 or status_code > 599:
        raise NodeExecutionError("Webhook Response: status_code must be between 100 and 599")

    body = config.get("body")
    log("Webhook response prepared" if visible else "Webhook response hidden by condition")
    return {"visible": visible, "status_code": status_code, "body": body}


# ── Cloud storage (Google Drive / OneDrive) ──────────────────────────
def _load_drive_integration(db: Session, config: dict, expected_type: str, context: Optional[dict] = None):
    from app.services.cloud_drive import get_drive_client

    integration_id = config.get("integration_id")
    if not integration_id:
        raise NodeExecutionError("ต้องเลือก integration (บัญชีคลาวด์) ก่อน")
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        raise NodeExecutionError(f"ไม่พบ integration: {integration_id}")
    _ensure_integration_owner(integration, (context or {}).get("_owner_user_id"))
    if integration.type != expected_type:
        raise NodeExecutionError(
            f"integration '{integration.name}' เป็นชนิด {integration.type} ไม่ใช่ {expected_type}"
        )
    return integration, get_drive_client(integration, db=db)


def _content_to_bytes(content: Any, mime_type: str) -> bytes:
    """Serialise node content to bytes — JSON object/array → pretty JSON, else str."""
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
    if content is None:
        return b""
    if "json" in (mime_type or "").lower() and isinstance(content, str):
        # leave already-serialised JSON strings as-is
        return content.encode("utf-8")
    return _stringify(content).encode("utf-8")


def _cloud_folder_id(integration: Integration, config: dict) -> str:
    """Use the saved OAuth destination and prevent arbitrary folder access."""
    requested = config.get("folder_id")
    selected = (integration.config or {}).get("folder_id") or "root"
    if (integration.config or {}).get("auth_mode") == "oauth" and requested and requested != selected:
        raise NodeExecutionError("OAuth cloud integration ใช้งานได้เฉพาะโฟลเดอร์ปลายทางที่บันทึกไว้")
    return requested or selected


def _exec_cloud_upload(db: Session, config: dict, context: dict, log, provider: str) -> Any:
    integration, client = _load_drive_integration(db, config, provider, context)
    filename = os.path.basename(str(config.get("filename") or "result.json"))
    mime_type = config.get("mime_type") or "application/json"
    folder_id = _cloud_folder_id(integration, config)
    data = _content_to_bytes(config.get("content"), mime_type)

    log(f"อัปโหลด '{filename}' ({len(data)} bytes) ผ่าน '{integration.name}'")
    result = client.upload(folder_id, filename, data, mime_type)
    log(f"อัปโหลดสำเร็จ: {result.get('name')} (id={result.get('file_id')})")
    return result


def _exec_cloud_import(db: Session, config: dict, context: dict, log, provider: str) -> Any:
    from app.services.ingestion import (
        ingest_file_into_job,
        validate_import_file,
        DuplicateSourceFile,
        UnsupportedFile,
    )

    integration, client = _load_drive_integration(db, config, provider, context)
    folder_id = _cloud_folder_id(integration, config)
    job_id = config.get("job_id")
    if not job_id:
        raise NodeExecutionError("ต้องเลือก Job ปลายทาง")
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise NodeExecutionError(f"ไม่พบ Job: {job_id}")

    schema_id = config.get("schema_id") or None
    if schema_id:
        from app.models.schema import DocumentSchema
        schema = db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()
        if not schema:
            raise NodeExecutionError(f"ไม่พบ Schema: {schema_id}")

    name_filter = (config.get("name_filter") or "").strip().lower()
    limit = int(config.get("limit") or 20)

    files = client.list_folder(folder_id)
    if name_filter:
        files = [f for f in files if name_filter in (f.get("name") or "").lower()]

    # Dedup against files already imported into this job so a repeated /
    # scheduled import doesn't re-ingest (and re-pay for OCR of) the same files.
    already = {
        row[0]
        for row in db.query(Document.source_file_id)
        .filter(Document.job_id == job_id, Document.source_file_id.isnot(None))
        .all()
    }
    pending = [f for f in files if f.get("id") not in already]
    skipped_existing = len(files) - len(pending)
    pending = pending[:limit]
    log(
        f"พบ {len(files)} ไฟล์ในโฟลเดอร์ (นำเข้าแล้ว {skipped_existing}) — "
        f"เริ่มนำเข้า {len(pending)} ไฟล์ใหม่เข้า Job '{job.name or job_id}'"
    )

    imported: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for f in pending:
        fid, fname = f.get("id"), f.get("name") or f.get("id")
        try:
            # Pre-download guard using source metadata size: reject an oversize
            # or unsupported file BEFORE pulling its bytes into memory, so a
            # stray huge file in the folder can't OOM the worker.
            raw_size = f.get("size")
            try:
                meta_size = int(raw_size) if raw_size is not None else None
            except (TypeError, ValueError):
                meta_size = None
            validate_import_file(fname, meta_size)

            data = client.download(fid)
            auto_review = bool(config.get("auto_review", False))
            res = ingest_file_into_job(
                db,
                str(job_id),
                data,
                fname,
                f.get("mimeType"),
                schema_id=str(schema_id) if schema_id else None,
                source_file_id=fid,
                auto_review=auto_review,
            )
            imported.append({"document_id": res["document_id"], "filename": fname, "drive_file_id": fid})
            log(f"นำเข้า '{fname}' → document {res['document_id']}")
        except UnsupportedFile as exc:
            failed.append({"filename": fname, "drive_file_id": fid, "error": str(exc)})
            log(f"ข้าม '{fname}': {exc}")
        except DuplicateSourceFile:
            # Won a concurrent race; another run already imported this file.
            skipped.append({"filename": fname, "drive_file_id": fid})
            log(f"ข้าม '{fname}': นำเข้าแล้ว (ซ้ำ)")
        except Exception as exc:  # noqa: BLE001 — record a bad file, keep importing
            db.rollback()
            failed.append({"filename": fname, "drive_file_id": fid, "error": str(exc)[:500]})
            log(f"ข้าม '{fname}': {exc}")

    wait_for_completion = config.get("wait_for_completion", True)
    if isinstance(wait_for_completion, str):
        wait_for_completion = wait_for_completion.lower() not in ("false", "0", "no", "off")
    else:
        wait_for_completion = bool(wait_for_completion)

    documents_output: List[Dict[str, Any]] = []
    records_output: List[Any] = []

    if imported and wait_for_completion:
        import time
        doc_ids = [item["document_id"] for item in imported]
        log(f"กำลังรอประมวลผล OCR & Extraction ให้เสร็จสิ้นสำหรับ {len(doc_ids)} เอกสาร...")
        start_wait = time.monotonic()
        timeout_wait = 600  # 10 minutes max wait for batch
        poll_interval = 2.0

        while time.monotonic() - start_wait < timeout_wait:
            db.expire_all()
            in_flight = (
                db.query(Document.id, Document.status)
                .filter(Document.id.in_(doc_ids), Document.status.in_(["queued", "processing"]))
                .all()
            )
            if not in_flight:
                break
            time.sleep(poll_interval)
        else:
            # Loop exhausted the wait budget without a clean break: some documents
            # are still queued/processing. Surface this explicitly so the operator
            # knows the batch finished on a timeout, not on completion.
            db.expire_all()
            still_pending = (
                db.query(Document.id, Document.status)
                .filter(Document.id.in_(doc_ids), Document.status.in_(["queued", "processing"]))
                .all()
            )
            if still_pending:
                statuses = ", ".join(sorted({s for _, s in still_pending}))
                log(
                    f"⚠️ ครบเวลารอ {timeout_wait} วินาที — {len(still_pending)} เอกสารยังประมวลผล "
                    f"ไม่เสร็จ (สถานะ: {statuses}); จะส่งต่อเฉพาะสถานะปัจจุบันเท่านั้น"
                )

        # Reload final document states
        db.expire_all()
        finished_docs = (
            db.query(Document)
            .filter(Document.id.in_(doc_ids))
            .all()
        )
        doc_by_id = {str(d.id): d for d in finished_docs}

        for item in imported:
            doc = doc_by_id.get(item["document_id"])
            if doc:
                data_val = doc.reviewed_data if doc.reviewed_data is not None else doc.extracted_data
                records_output.append(data_val)
                documents_output.append({
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "status": doc.status,
                    "data": data_val,
                    "ocr_text": doc.ocr_text,
                    "extraction": _workflow_document_extraction(doc),
                    "drive_file_id": item.get("drive_file_id"),
                })
        log(f"ประมวลผลเสร็จสิ้น {len(documents_output)} เอกสาร")

    return {
        "job_id": str(job_id),
        "count": len(imported),
        "imported": imported,
        "records": records_output,
        "documents": documents_output,
        "skipped_count": skipped_existing + len(skipped),
        "skipped": skipped,
        "failed_count": len(failed),
        "failed": failed,
    }


def _exec_gdrive_upload(db, config, context, log):
    return _exec_cloud_upload(db, config, context, log, "gdrive")


def _exec_gdrive_import(db, config, context, log):
    return _exec_cloud_import(db, config, context, log, "gdrive")


def _exec_onedrive_upload(db, config, context, log):
    return _exec_cloud_upload(db, config, context, log, "onedrive")


def _exec_onedrive_import(db, config, context, log):
    return _exec_cloud_import(db, config, context, log, "onedrive")


def _tabular_rows(content: Any) -> Optional[List[dict]]:
    """Normalise content to a list-of-dicts table, or None if not tabular.

    Accepts a JSON string, a single dict (→ one row), or a list of dicts.
    Shared by the csv / xlsx / docx writers.
    """
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return None
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list) and content and all(isinstance(r, dict) for r in content):
        return content
    return None


def _fieldnames(rows: List[dict]) -> List[str]:
    names: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in names:
                names.append(k)
    return names


def _cell(value: Any) -> str:
    return _stringify(value) if isinstance(value, (dict, list)) else ("" if value is None else str(value))


def _to_csv(content: Any) -> str:
    import csv
    import io

    rows = _tabular_rows(content)
    if rows is None:
        return content if isinstance(content, str) else _stringify(content)

    fieldnames = _fieldnames(rows)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: _cell(v) for k, v in r.items()})
    return buf.getvalue()


def _to_xlsx_bytes(content: Any) -> bytes:
    """Render content as an .xlsx workbook. Tabular content → header + rows;
    non-tabular → the stringified value in a single cell."""
    import io
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Output"
    rows = _tabular_rows(content)
    if rows is not None:
        fieldnames = _fieldnames(rows)
        ws.append(fieldnames)
        for r in rows:
            ws.append([_cell(r.get(k)) for k in fieldnames])
    else:
        ws["A1"] = content if isinstance(content, str) else _stringify(content)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _to_docx_bytes(content: Any) -> bytes:
    """Render content as a .docx document. Tabular content → a table; otherwise
    the stringified value as paragraphs (one per line)."""
    import io
    from docx import Document as DocxDocument

    doc = DocxDocument()
    rows = _tabular_rows(content)
    if rows is not None:
        fieldnames = _fieldnames(rows)
        table = doc.add_table(rows=1, cols=len(fieldnames) or 1)
        try:
            table.style = "Table Grid"
        except Exception:  # style may be unavailable in a minimal template
            pass
        hdr = table.rows[0].cells
        for i, name in enumerate(fieldnames):
            hdr[i].text = str(name)
        for r in rows:
            cells = table.add_row().cells
            for i, name in enumerate(fieldnames):
                cells[i].text = _cell(r.get(name))
    else:
        text = content if isinstance(content, str) else _stringify(content)
        for line in text.split("\n"):
            doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _jev_decision_setting(db: Session):
    """Seam for tests: the mapping/TypeSafe settings row for decision nodes."""
    return db.query(Setting).first()


def _jev_decision_wanted_fields(fields_to_use) -> list:
    """Seam for tests: normalize fields_to_use (comma string, list, or chips)."""
    if fields_to_use is None:
        return []
    if isinstance(fields_to_use, str):
        return [f.strip() for f in fields_to_use.split(",") if f.strip()]
    if isinstance(fields_to_use, list):
        wanted: list = []
        for item in fields_to_use:
            if isinstance(item, str):
                wanted.extend(f.strip() for f in item.split(",") if f.strip())
            elif isinstance(item, dict) and str(item.get("key") or item.get("label") or "").strip():
                wanted.append(str(item.get("key") or item.get("label")).strip())
        return wanted
    return []


def _jev_decision_input(config: dict, context: dict) -> str:
    """Seam for tests: flatten input_source into the text Jev judges.

    Major 4: ``fields_to_use`` must never silently no-op. After template render
    ``input_source`` is usually a string, so a JSON-looking string is parsed and
    filtered; if filtering is requested but cannot be applied → fail loud.
    """
    import re as _re

    source = config.get("input_source")
    if source is None:
        raise NodeExecutionError("ต้องระบุข้อมูลที่ใช้ (input_source)")
    wanted = _jev_decision_wanted_fields(config.get("fields_to_use"))

    parsed = source
    if isinstance(source, str):
        stripped = source.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                parsed = source
    if isinstance(parsed, str):
        if wanted:
            raise NodeExecutionError(
                f"fields_to_use ใช้ไม่ได้กับ input_source ที่เป็นข้อความล้วน ({', '.join(wanted)}) — "
                "ให้ input_source อ้าง object/dict จาก node ก่อนหน้า หรือเว้นว่าง fields_to_use"
            )
        text = parsed
    elif isinstance(parsed, dict):
        if wanted:
            missing = [k for k in wanted if k not in parsed]
            if missing:
                raise NodeExecutionError(f"input_source ไม่มีฟิลด์ที่ระบุใน fields_to_use: {', '.join(missing)}")
            parsed = {k: parsed[k] for k in wanted}
        text = json.dumps(parsed, ensure_ascii=False)
    elif isinstance(parsed, list):
        if wanted:
            if all(isinstance(item, dict) for item in parsed):
                missing = sorted({k for item in parsed for k in wanted if k not in item})
                if missing:
                    raise NodeExecutionError(f"input_source (list) ไม่มีฟิลด์ที่ระบุใน fields_to_use: {', '.join(missing)}")
                parsed = [{k: item[k] for k in wanted if k in item} for item in parsed]
            else:
                raise NodeExecutionError(
                    f"fields_to_use ใช้ได้เฉพาะเมื่อ input_source เป็น object/list ของ object — ได้รับ list ธรรมดา ({', '.join(wanted)})"
                )
        text = json.dumps(parsed, ensure_ascii=False)
    else:
        text = str(parsed)
    return text


def _jev_decision_state(config: dict, context: dict, log: Callable[[str], None], node_label: str) -> dict:
    """Build the Jev state, capped so a whole batch can't blow the request.

    A list input is judged as ONE combined answer, not per item — say so in
    the log so users don't read a batch verdict as a per-document one.
    """
    from app.core.config import settings as app_settings

    text = _jev_decision_input(config, context)
    if not text.strip():
        raise NodeExecutionError(f"{node_label}: ข้อมูลที่ใช้ตัดสินว่างเปล่า — ตรวจ input_source จาก node ก่อนหน้า")
    if text.lstrip().startswith("["):
        try:
            items = json.loads(text)
        except ValueError:
            items = None
        if isinstance(items, list) and len(items) > 1:
            log(f"input เป็นรายการ {len(items)} รายการ — Jev ตัดสินรวมทั้งชุดเป็นคำตอบเดียว (ไม่ใช่รายเอกสาร)")
    cap = app_settings.JEV_DECISION_INPUT_MAX_CHARS
    if len(text) > cap:
        log(f"input ยาว {len(text)} ตัวอักษร เกินเพดาน {cap} — ตัดส่วนท้ายออก")
        text = text[:cap] + f"\n…[ตัดทอน {len(text) - cap} ตัวอักษร]"
    return {"input": text}


def _jev_decision_timeout() -> float:
    from app.core.config import settings as app_settings
    return float(app_settings.JEV_DECISION_TIMEOUT_SECONDS)


SCORE_SCALE_RANGE = {"0_100": (0.0, 100.0), "0_10": (0.0, 10.0), "1_5": (1.0, 5.0)}


def jev_threshold_issues(ntype: str, config: dict) -> List[tuple]:
    """(field, message) for thresholds outside the range the node can produce.

    A Score threshold of 80 on a 1–5 scale, or a probability of 70 instead of
    0.7, would make ``threshold_met`` always false (or always true) without any
    error. Blank values are allowed (no threshold); templated values are checked at run time.
    """
    checks: List[tuple] = []
    if ntype == "jev_score":
        scale = config.get("scale") or "0_100"
        low, high = SCORE_SCALE_RANGE.get(scale, (0.0, 100.0))
        checks.append(("threshold", low, high, f"คะแนนขั้นต่ำต้องอยู่ในช่วงคะแนน {low:g}–{high:g}"))
    elif ntype == "jev_choice":
        if (config.get("pick_rule") or "highest") == "first_above_threshold":
            checks.append(("probability_threshold", 0.0, 1.0, "โอกาสขั้นต่ำต้องอยู่ระหว่าง 0 ถึง 1 (เช่น 0.7)"))
        checks.append(("min_confidence", 0.0, 1.0, "ความมั่นใจขั้นต่ำต้องอยู่ระหว่าง 0 ถึง 1 (เช่น 0.6)"))
    elif ntype == "jev_noul":
        checks.append(("threshold", 0.0, 1.0, "เกณฑ์ต้องอยู่ระหว่าง 0 ถึง 1 (เช่น 0.7)"))
    issues: List[tuple] = []
    for name, low, high, message in checks:
        value = config.get(name)
        if value is None or (isinstance(value, str) and (not value.strip() or "{{" in value)):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            issues.append((name, "ต้องเป็นตัวเลข — " + message))
            continue
        if not (low <= number <= high):
            issues.append((name, message))
    return issues


def _check_jev_thresholds(ntype: str, label: str, config: dict) -> None:
    issues = jev_threshold_issues(ntype, config)
    if issues:
        raise NodeExecutionError(f"{label}: " + "; ".join(message for _field, message in issues))


def _jev_score_scale_index(scale: str) -> int:
    """Number of API levels backing each UI scale."""
    return len(SCORE_SCALES.get(scale) or SCORE_SCALES["0_100"])


def _map_jev_score_index(index: float, scale: str) -> float:
    """Map a TypeSafe score index s ∈ [0, n_levels-1] onto the UI scale.

    0_100 / 0_10 are zero-anchored so proportional mapping applies; 1_5 maps
    the normalized [0,1] span onto [1,5]. Kept pure for unit tests.
    """
    if index is None:
        raise NodeExecutionError("Jev ไม่ได้ส่งคะแนนกลับมา")
    levels = _jev_score_scale_index(scale)
    max_out = SCORE_SCALE_MAX.get(scale, 100.0)
    min_out = SCORE_SCALE_MIN.get(scale, 0.0)
    normalized = max(0.0, min(1.0, float(index) / max(1, levels - 1)))
    return round(min_out + normalized * (max_out - min_out), 2)


def _normalize_jev_criteria(criteria) -> list:
    """Validate UX criteria rows and normalize weights to sum to 1.0."""
    rows: list = []
    if isinstance(criteria, str):
        criteria = criteria.splitlines()
    for raw in criteria or []:
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.split("|")]
            if not parts or not parts[0]:
                continue
            row = {"label": parts[0]}
            if len(parts) > 1 and parts[1]:
                try:
                    row["weight"] = float(parts[1])
                except ValueError:
                    row["weight"] = None
            else:
                row["weight"] = None
            if len(parts) > 2 and parts[2]:
                row["guidance"] = parts[2]
            rows.append(row)
        elif isinstance(raw, dict) and str(raw.get("label") or "").strip():
            row = {"label": str(raw["label"]).strip()}
            try:
                row["weight"] = float(raw["weight"]) if raw.get("weight") is not None else None
            except (TypeError, ValueError):
                row["weight"] = None
            if str(raw.get("guidance") or "").strip():
                row["guidance"] = str(raw["guidance"]).strip()
            rows.append(row)
    if not rows:
        raise NodeExecutionError("ต้องระบุเกณฑ์ (criteria) อย่างน้อย 1 ข้อ")
    weights = [r["weight"] for r in rows if isinstance(r.get("weight"), (int, float))]
    if weights and len(weights) != len(rows):
        raise NodeExecutionError("ระบุน้ำหนัก (weight) ต้องครบทุกเกณฑ์ หรือเว้นว่างทั้งหมดเพื่อ normalize เท่ากัน")
    if weights:
        total = sum(weights)
        if total <= 0:
            raise NodeExecutionError("น้ำหนักรวมต้องมากกว่า 0")
        for r in rows:
            r["weight"] = round(r["weight"] / total, 4)
    else:
        share = round(1.0 / len(rows), 4)
        for r in rows:
            r["weight"] = share
    return rows


def _require_jev_configured(db: Session, config: dict, node_label: str):
    """Resolve TypeSafe config for a decision node; fail loud when missing.

    Both engines (typesafe_jev / auto) REQUIRE TypeSafe for decision nodes —
    unlike mapping, there is no second provider to fall back to.
    """
    from app.services.typesafe import (
        TypeSafeConfigurationError,
        resolve_typesafe_config,
        typesafe_is_configured,
    )

    engine = (config.get("engine") or "typesafe_jev").strip()
    if engine not in {"typesafe_jev", "auto"}:
        raise NodeExecutionError(f"{node_label}: engine ไม่ถูกต้อง: {engine}")
    setting = _jev_decision_setting(db)
    if not typesafe_is_configured(setting):
        raise NodeExecutionError(
            f"{node_label}: ยังไม่ได้ตั้งค่า TypeSafe (Jev) — ไปที่ Settings › OCR & Providers › TypeSafe แล้วกรอก Endpoint และ API Key"
        )
    try:
        return engine, resolve_typesafe_config(setting)
    except TypeSafeConfigurationError as exc:
        raise NodeExecutionError(
            f"{node_label}: ตั้งค่า TypeSafe (Jev) ไม่สมบูรณ์ — {exc} · ไปที่ Settings › OCR & Providers › TypeSafe"
        ) from exc
    except ValueError as exc:
        raise NodeExecutionError(
            f"{node_label}: ค่า TypeSafe ใน Settings ไม่ถูกต้อง — ไปที่ Settings › OCR & Providers › TypeSafe"
        ) from exc


def _exec_jev_score(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    """Score upstream data on a weighted rubric (Decision ≠ Generation).

    Single outbound; downstream Condition reads `score` / `threshold_met`.
    """
    from app.services import typesafe as ts_mod

    _check_jev_thresholds("jev_score", "Score", config)

    score_name = str(config.get("score_name") or "").strip()
    if not score_name:
        raise NodeExecutionError("ต้องระบุชื่อการให้คะแนน (score_name)")
    scale = config.get("scale") or "0_100"
    if scale not in SCORE_SCALES:
        raise NodeExecutionError(f"มาตราส่วนไม่ถูกต้อง: {scale}")
    criteria = _normalize_jev_criteria(config.get("criteria"))
    state = _jev_decision_state(config, context, log, "Score")

    engine, config_jev = _require_jev_configured(db, config, "Score")
    log(f"engine={engine} scale={scale} criteria={len(criteria)} ข้อ")

    result = ts_mod.typesafe_score(
        config_jev,
        state,
        score_name=score_name,
        rubric=criteria,
        scale=scale,
        timeout=_jev_decision_timeout(),
    )
    raw_index = result.get("index")
    score = _map_jev_score_index(raw_index, scale)
    threshold = config.get("threshold")
    try:
        threshold_val = float(threshold) if threshold is not None and str(threshold).strip() != "" else None
    except (TypeError, ValueError):
        threshold_val = None
    threshold_met = (score >= threshold_val) if threshold_val is not None else None
    confidence = result.get("confidence") if config.get("include_confidence", True) else None
    log(f"score={score}/{SCORE_SCALE_MAX.get(scale)} threshold_met={threshold_met} provider=jev:{result.get('model')}")

    return {
        "score": score,
        "scale": scale,
        "threshold": threshold_val,
        "threshold_met": threshold_met,
        "confidence": confidence,
        "criteria": criteria,
        "provider": f"jev:{result.get('model')}",
    }


JEV_CHOICE_FALLBACK_HANDLE = "fallback"


def jev_choice_branch(output: Any) -> str:
    """The sourceHandle a Choice output routes to."""
    out = output if isinstance(output, dict) else {}
    return JEV_CHOICE_FALLBACK_HANDLE if out.get("used_fallback") else str(out.get("choice") or "")


def _check_jev_choice_branch_wired(node_id: str, output: Any, edges: List[dict]) -> None:
    """Fail instead of silently skipping every downstream node.

    A Choice with no outgoing edges is a terminal decision (its output is the
    result); once any branch is wired, the chosen branch must be wired too.
    """
    outgoing = [e for e in edges if e.get("source") == node_id]
    if not outgoing:
        return
    branch = jev_choice_branch(output)
    if not any((e.get("sourceHandle") or "") == branch for e in outgoing):
        raise NodeExecutionError(
            f"Choice เลือกเส้นทาง '{branch}' แต่ไม่มีเส้นเชื่อมจาก handle นี้ — "
            "ต่อเส้นให้ครบทุกตัวเลือก (รวม fallback) หรือปิด fallback"
        )


def _normalize_jev_options(options_raw) -> list:
    """Validate UX option rows into {key,label,description?} with unique keys."""
    rows: list = []
    seen: set = set()
    if isinstance(options_raw, str):
        options_raw = options_raw.splitlines()
    for raw in options_raw or []:
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.split("|")]
            if not parts or not parts[0]:
                continue
            row = {"key": parts[0], "label": parts[1] if len(parts) > 1 and parts[1] else parts[0]}
            if len(parts) > 2 and parts[2]:
                row["description"] = parts[2]
        elif isinstance(raw, dict) and str(raw.get("key") or "").strip():
            row = {
                "key": str(raw["key"]).strip(),
                "label": str(raw.get("label") or raw["key"]).strip(),
            }
            if str(raw.get("description") or "").strip():
                row["description"] = str(raw["description"]).strip()
        else:
            continue
        if row["key"].casefold() == JEV_CHOICE_FALLBACK_HANDLE:
            raise NodeExecutionError("key 'fallback' สงวนไว้สำหรับเส้นทาง fallback — ตั้งชื่อ key อื่น")
        if row["key"] in seen:
            raise NodeExecutionError(f"key ของตัวเลือกซ้ำกัน: {row['key']}")
        seen.add(row["key"])
        rows.append(row)
    if len(rows) < 2:
        raise NodeExecutionError("ต้องระบุตัวเลือกอย่างน้อย 2 ตัว (รูปแบบ key|label|description ต่อบรรทัด)")
    if len(rows) > 6:
        raise NodeExecutionError("ตัวเลือกมากสุด 6 ตัว")
    return rows


def _exec_jev_choice(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    """Choose among options with probabilities (Decision ≠ Generation).

    Multi outbound: runtime walks only the edge whose sourceHandle equals the
    chosen key (or `fallback` when used_fallback).
    """
    from app.services import typesafe as ts_mod

    _check_jev_thresholds("jev_choice", "Choice", config)

    choice_name = str(config.get("choice_name") or "").strip()
    if not choice_name:
        raise NodeExecutionError("ต้องระบุชื่อการเลือก (choice_name)")
    options = _normalize_jev_options(config.get("options"))
    state = _jev_decision_state(config, context, log, "Choice")

    engine, config_jev = _require_jev_configured(db, config, "Choice")
    log(f"engine={engine} options={[o['key'] for o in options]}")

    result = ts_mod.typesafe_choice(config_jev, state, choice_name=choice_name, options=options,
                                    timeout=_jev_decision_timeout())
    api_choice = result.get("choice")
    valid_keys = [o["key"] for o in options]
    if not api_choice or api_choice not in valid_keys:
        raise NodeExecutionError(f"Jev เลือกตัวเลือกที่ไม่อยู่ในรายการ: {api_choice!r}")

    probabilities = result.get("probabilities") or {}
    pick_rule = config.get("pick_rule") or "highest"
    fallback_reason = None  # set when the configured pick cannot be satisfied

    def _prob(key: str):
        try:
            return float(probabilities.get(key))
        except (TypeError, ValueError):
            return None

    if probabilities and any(_prob(k) is not None for k in valid_keys):
        # Major 1: apply the configured pick rule locally over vendor probabilities.
        if pick_rule == "highest":
            choice_key = max(valid_keys, key=lambda k: (_prob(k) is not None, _prob(k) or 0.0))
        elif pick_rule == "first_above_threshold":
            try:
                prob_threshold = float(config.get("probability_threshold"))
            except (TypeError, ValueError):
                raise NodeExecutionError(
                    "Choice: pick_rule=first_above_threshold ต้องระบุ probability_threshold เป็นตัวเลข")
            choice_key = next((k for k in valid_keys if (_prob(k) or 0.0) >= prob_threshold), None)
            if choice_key is None:
                if bool(config.get("enable_fallback", True)):
                    choice_key = api_choice
                    fallback_reason = f"ไม่มีตัวเลือกใดมี probability ≥ {prob_threshold}"
                else:
                    raise NodeExecutionError(
                        f"Choice: ไม่มีตัวเลือกใดมี probability ≥ {prob_threshold} และไม่ได้เปิด fallback")
        else:
            raise NodeExecutionError(f"Choice: pick_rule ไม่ถูกต้อง: {pick_rule}")
    else:
        # Minor 5: no usable probabilities → keep the API choice, never invent numbers.
        choice_key = api_choice

    show_probabilities = bool(config.get("show_probabilities", True))
    options_out: list = []
    for o in options:
        row = {"key": o["key"], "label": o["label"]}
        if show_probabilities and _prob(o["key"]) is not None:
            row["probability"] = round(_prob(o["key"]), 4)
        options_out.append(row)

    chosen_probability = None
    if show_probabilities:
        chosen_probability = next((r.get("probability") for r in options_out if r["key"] == choice_key), None)
    confidence = result.get("confidence")

    min_confidence = config.get("min_confidence")
    try:
        min_confidence_val = float(min_confidence) if min_confidence is not None and str(min_confidence).strip() != "" else None
    except (TypeError, ValueError):
        min_confidence_val = None
    used_fallback = fallback_reason is not None
    if not used_fallback and min_confidence_val is not None and isinstance(confidence, (int, float)) and confidence < min_confidence_val:
        if bool(config.get("enable_fallback", True)):
            used_fallback = True
            fallback_reason = f"confidence {confidence} < min_confidence {min_confidence_val}"
    if fallback_reason:
        log(fallback_reason)

    label = next((o["label"] for o in options if o["key"] == choice_key), choice_key)
    log(f"pick_rule={pick_rule} choice={choice_key} probability={chosen_probability} used_fallback={used_fallback}")

    policy: dict = {"pick": pick_rule, "min_confidence": min_confidence_val}
    if pick_rule == "first_above_threshold":
        try:
            policy["probability_threshold"] = float(config.get("probability_threshold"))
        except (TypeError, ValueError):
            pass

    # Minor 5: omit probability when the provider did not supply one (no one-hot).
    return {
        "choice": choice_key,
        "label": label,
        "probability": chosen_probability,
        "confidence": confidence,
        "used_fallback": used_fallback,
        "policy": policy,
        "options": options_out,
        "provider": f"jev:{result.get('model')}",
    }


def _exec_jev_noul(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    """Answer a yes/no probability question via Jev Noul (Decision ≠ Generation).

    Single outbound like Score: writes noul + optional threshold/threshold_met;
    branching belongs to the downstream Condition node.
    """
    from app.services import typesafe as ts_mod

    _check_jev_thresholds("jev_noul", "Noul", config)

    noul_name = str(config.get("noul_name") or "").strip()
    if not noul_name:
        raise NodeExecutionError("ต้องระบุชื่อคำถาม (noul_name)")
    question = str(config.get("question") or "").strip()
    if not question:
        raise NodeExecutionError("ต้องระบุคำถาม Yes/No (question)")
    state = _jev_decision_state(config, context, log, "Noul")

    engine, config_jev = _require_jev_configured(db, config, "Noul")
    log(f"engine={engine} question={question[:80]}")

    result = ts_mod.typesafe_noul(config_jev, state, question=question, timeout=_jev_decision_timeout())
    noul = result.get("noul")
    if noul is None:
        raise NodeExecutionError("Jev ไม่ได้ส่งค่า noul กลับมา")
    noul = round(float(noul), 4)

    threshold = config.get("threshold")
    try:
        threshold_val = float(threshold) if threshold is not None and str(threshold).strip() != "" else None
    except (TypeError, ValueError):
        threshold_val = None
    threshold_met = (noul >= threshold_val) if threshold_val is not None else None
    log(f"noul={noul} threshold={threshold_val} threshold_met={threshold_met} provider=jev:{result.get('model')}")

    return {
        "noul": noul,
        "question": question,
        "noul_name": noul_name,
        "threshold": threshold_val,
        "threshold_met": threshold_met,
        "provider": f"jev:{result.get('model')}",
        "input_from": str(config.get("_input_source_template") or config.get("input_source") or ""),
    }


def _field_mapping_setting(db: Session):
    """Seam for tests: the mapping/TypeSafe settings row."""
    return db.query(Setting).first()


def _field_mapping_schema(db: Session, schema_id: str):
    """Seam for tests: the selected DocumentSchema."""
    from app.models.schema import DocumentSchema

    return db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()


def _field_mapping_documents(db: Session, config: dict, context: dict, limit: int) -> list:
    """Seam for tests: documents from an explicit job_id or upstream sources."""
    from app.models.document import Document

    job_id = (config.get("job_id") or "").strip()
    if job_id:
        return (
            db.query(Document)
            .filter(Document.job_id == job_id, Document.ocr_text.isnot(None))
            .order_by(Document.uploaded_at.desc())
            .limit(limit)
            .all()
        )
    docs: list = []
    seen: set[str] = set()
    for source_id in _upstream_node_ids(str(context.get("_node_id") or ""), config.get("_edges") or []):
        output = context.get(source_id)
        if not isinstance(output, dict):
            continue
        for item in output.get("documents") or []:
            doc_id = str((item or {}).get("id") or "")
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            if len(docs) >= limit:
                break
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc is not None and doc.ocr_text:
                docs.append(doc)
    return docs


def _exec_field_mapping(db: Session, config: dict, context: dict, log: Callable[[str], None]) -> Any:
    """Map schema fields from upstream documents' OCR text (same engines as Jobs).

    Reuses ``map_fields`` unchanged: bbox locators are honored first, then the
    selected engine (auto prunes unconfigured providers). Documents come from
    upstream job_source/document_source outputs (or an explicit job_id), and
    each document's stored file is resolved so fixed-position extraction works
    exactly like Jobs Processing.
    """
    from app.services.field_mapping import map_fields
    from app.services.typesafe import typesafe_is_configured
    from app.services.storage import get_storage_service

    engine = (config.get("engine") or "").strip() or "auto"
    if engine not in {"auto", "softnix", "jev", "llm", "fixed"}:
        raise NodeExecutionError(f"Field Mapping: engine ไม่ถูกต้อง: {engine}")

    schema_id = (config.get("schema_id") or "").strip()
    if not schema_id:
        raise NodeExecutionError("Field Mapping: ต้องเลือก Schema ก่อน")
    schema = _field_mapping_schema(db, schema_id)
    if not schema:
        raise NodeExecutionError(f"Field Mapping: ไม่พบ Schema {schema_id}")
    schema_fields = [f for f in (schema.fields or []) if f.get("name")]
    if not schema_fields:
        raise NodeExecutionError("Field Mapping: Schema นี้ไม่มีฟิลด์")

    raw_names = config.get("field_names")
    if isinstance(raw_names, list):
        field_names = [str(n).strip() for n in raw_names if str(n).strip()]
    else:
        field_names = [n.strip() for n in str(raw_names or "").split(",") if n.strip()]
    unknown = [n for n in field_names if n not in {f["name"] for f in schema_fields}]
    if unknown:
        raise NodeExecutionError(f"Field Mapping: Schema ไม่มีฟิลด์ {', '.join(unknown)}")
    field_names = field_names or None

    try:
        limit = max(1, min(int(config.get("limit") or 10), 50))
    except (TypeError, ValueError):
        limit = 10

    docs = _field_mapping_documents(db, config, context, limit)
    if not docs:
        raise NodeExecutionError(
            "Field Mapping: ไม่พบเอกสารที่มีข้อความ OCR — เชื่อมต่อจาก Jobs หรือ Document Source ที่ประมวลผลแล้ว"
        )

    if engine == "jev" and not typesafe_is_configured(_field_mapping_setting(db)):
        raise NodeExecutionError(
            "Field Mapping: ยังไม่ได้ตั้งค่า TypeSafe (Jev) — ไปที่ Settings › OCR & Providers › TypeSafe แล้วกรอก Endpoint และ API Key"
        )

    storage = get_storage_service()
    mapped: List[Dict[str, Any]] = []
    warnings: List[str] = []
    skipped_documents: List[str] = []
    # Each document may take up to MAPPING_TOTAL_TIMEOUT_SECONDS; without a node budget
    # 50 documents could run for hours and the whole workflow task would be killed.
    deadline = time.monotonic() + settings.WORKFLOW_FIELD_MAPPING_BUDGET_SECONDS
    for position, doc in enumerate(docs):
        remaining = deadline - time.monotonic()
        if remaining < settings.WORKFLOW_FIELD_MAPPING_MIN_DOCUMENT_SECONDS:
            skipped_documents = [d.filename for d in docs[position:]]
            warnings.append(
                f"หมดเวลาของ node ({settings.WORKFLOW_FIELD_MAPPING_BUDGET_SECONDS} วินาที) — ยังไม่ได้ดึงข้อมูล "
                f"{len(skipped_documents)} เอกสาร ลดจำนวนเอกสารต่อรอบแล้วรันใหม่"
            )
            log(f"budget exhausted; skipped {len(skipped_documents)} document(s)")
            break
        text = doc.ocr_text or ""
        if not text.strip():
            warnings.append(f"ข้าม '{doc.filename}': ไม่มีข้อความ OCR")
            continue
        with ExitStack() as stack:
            file_path = None
            if doc.file_path:
                try:
                    file_path = stack.enter_context(storage.get_local_path(doc.file_path))
                except Exception:  # noqa: BLE001 — file is optional (bbox fields only)
                    file_path = None
            values, report = map_fields(text, schema, db, file_path, engine=engine, field_names=field_names,
                                        budget_seconds=min(settings.MAPPING_TOTAL_TIMEOUT_SECONDS, remaining))
        for attempt in report.get("attempts") or []:
            if attempt.get("status") == "skipped":
                warnings.append(
                    f"ข้าม engine {attempt.get('provider')} ({attempt.get('category')}) ในโหมด auto — '{doc.filename}'"
                )
        mapped.append({
            "document_id": str(doc.id),
            "filename": doc.filename,
            "values": values,
            "status": report.get("status"),
            "provider": report.get("attempts"),
            "engine": report.get("engine"),
            "fields": report.get("fields"),
            "review_fields": report.get("review_fields"),
            "unresolved_fields": report.get("unresolved_fields"),
            "missing_fields": report.get("missing_fields"),
        })
        log(
            f"map '{doc.filename}': status={report.get('status')} "
            f"providers={[a.get('provider') for a in report.get('attempts') or []]} "
            f"review={len(report.get('review_fields') or [])} unresolved={len(report.get('unresolved_fields') or [])}"
        )

    if not mapped:
        raise NodeExecutionError("Field Mapping: ทุกเอกสารไม่มีข้อความ OCR ที่ map ได้")

    first = mapped[0]
    # Worst case across documents so a Condition on {{node.status}} can't pass
    # a batch whose later documents failed.
    severity = {"completed": 0, "partial": 1, "failed": 2}
    overall_status = max((d["status"] or "failed" for d in mapped), key=lambda s: severity.get(s, 2))
    if skipped_documents and overall_status == "completed":
        overall_status = "partial"
    incomplete = [d["filename"] for d in mapped if d["status"] != "completed"] + skipped_documents
    if len(mapped) > 1:
        warnings.append(
            f"values/evidence/review_fields เป็นของเอกสารแรก ('{first['filename']}') — ผลของทุกเอกสารอยู่ใน documents"
        )
    return {
        "count": len(mapped),
        "values": first["values"],
        "status": overall_status,
        "first_document_status": first["status"],
        "incomplete_documents": incomplete,
        "skipped_documents": skipped_documents,
        "evidence": first["fields"],
        "review_fields": first["review_fields"],
        "unresolved_fields": first["unresolved_fields"],
        "provider": [a.get("provider") for a in first["provider"] or [] if a.get("status") != "skipped"],
        "warnings": warnings,
        "documents": mapped,
    }



EXECUTORS: Dict[str, Callable] = {
    "trigger_manual": _exec_trigger,
    "trigger_schedule": _exec_trigger,
    "trigger_webhook": _exec_trigger,
    "job_source": _exec_job_source,
    "document_source": _exec_document_source,
    "field_mapping": _exec_field_mapping,
    "jev_score": _exec_jev_score,
    "jev_choice": _exec_jev_choice,
    "jev_noul": _exec_jev_noul,
    "llm": _exec_llm,
    "condition": _exec_condition,
    "transform": _exec_transform,
    "python_code": _exec_python_code,
    "http_request": _exec_http_request,
    "api": _exec_api,
    "write_output": _exec_write_output,
    "publish_artifact": _exec_publish_artifact,
    "webhook_response": _exec_webhook_response,
    "gdrive_upload": _exec_gdrive_upload,
    "gdrive_import": _exec_gdrive_import,
    "onedrive_upload": _exec_onedrive_upload,
    "onedrive_import": _exec_onedrive_import,
}


# ── Engine ───────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _topological_order(nodes: List[dict], edges: List[dict]) -> List[dict]:
    node_map = {n["id"]: n for n in nodes}
    indegree = {nid: 0 for nid in node_map}
    children: Dict[str, List[str]] = {nid: [] for nid in node_map}
    for e in edges:
        src, dst = e.get("source"), e.get("target")
        if src in node_map and dst in node_map:
            indegree[dst] += 1
            children[src].append(dst)

    queue = [nid for nid, deg in indegree.items() if deg == 0]
    ordered: List[dict] = []
    while queue:
        nid = queue.pop(0)
        ordered.append(node_map[nid])
        for child in children[nid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(ordered) != len(nodes):
        raise NodeExecutionError("Workflow contains a cycle — must be a DAG")
    return ordered


def _workflow_owner_id(db: Session, workflow_id) -> Optional[str]:
    # Best-effort: on any failure (orphaned run, non-query session), return
    # None, which disables cross-tenant enforcement rather than killing the
    # run. Real runs use a full Session and resolve the owner normally.
    try:
        owner = (
            db.query(Workflow.user_id)
            .filter(Workflow.id == workflow_id)
            .scalar()
        )
    except Exception:
        return None
    return str(owner) if owner else None


def _upstream_job_ids(
    node_id: str,
    edges: List[dict],
    context: Dict[str, Any],
    node_status: Optional[Dict[str, str]] = None,
) -> set[str]:
    """Find Job ids only in the selected node's upstream graph.

    Agent nodes must not scan the entire execution context: a workflow can have
    multiple independent Job sources, and choosing an arbitrary one can produce
    a valid but incorrect report. A set also lets the caller reject ambiguous
    graphs instead of silently choosing one source.
    """
    parents: Dict[str, List[str]] = {}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            parents.setdefault(target, []).append(source)

    queue = list(parents.get(node_id) or [])
    visited: set[str] = set()
    job_ids: set[str] = set()
    while queue:
        source = queue.pop(0)
        if source in visited:
            continue
        visited.add(source)
        if node_status is not None and node_status.get(source) != "succeeded":
            continue
        output = context.get(source)
        if isinstance(output, dict) and output.get("job_id"):
            job_ids.add(str(output["job_id"]))
        queue.extend(parents.get(source) or [])
    return job_ids


def _add_inferred_agent_job_id(
    node: dict,
    resolved_config: dict,
    edges: List[dict],
    context: Dict[str, Any],
    node_status: Optional[Dict[str, str]] = None,
) -> dict:
    if node.get("type") != "llm":
        return resolved_config
    if (resolved_config.get("mode") or "llm") != "agent" or resolved_config.get("job_id"):
        return resolved_config
    job_ids = _upstream_job_ids(node["id"], edges, context, node_status)
    if len(job_ids) > 1:
        raise NodeExecutionError(
            "Agent node has multiple upstream Job contexts; select Job context explicitly"
        )
    if not job_ids:
        return resolved_config
    return {**resolved_config, "_inferred_job_id": next(iter(job_ids))}


def _add_inferred_publish_artifact_job_id(
    node: dict,
    resolved_config: dict,
    edges: List[dict],
    context: Dict[str, Any],
    node_status: Optional[Dict[str, str]] = None,
) -> dict:
    if node.get("type") != "publish_artifact" or resolved_config.get("job_id"):
        return resolved_config
    job_ids = _upstream_job_ids(node["id"], edges, context, node_status)
    if len(job_ids) > 1:
        raise NodeExecutionError(
            "Publish Artifact has multiple upstream Job contexts; select Job context explicitly"
        )
    if not job_ids:
        return resolved_config
    return {**resolved_config, "_inferred_job_id": next(iter(job_ids))}


def _upstream_node_ids(node_id: str, edges: List[dict]) -> list[str]:
    """Return upstream nodes from oldest to newest without following cycles."""
    parents: dict[str, list[str]] = {}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            parents.setdefault(str(target), []).append(str(source))

    ordered: list[str] = []
    visited: set[str] = set()

    def visit(current: str) -> None:
        for parent in parents.get(current, []):
            if parent in visited:
                continue
            visited.add(parent)
            visit(parent)
            ordered.append(parent)

    visit(node_id)
    return ordered


def _compact_prompt_value(value: Any, limit: int) -> str:
    """Serialize workflow context within a predictable prompt-size budget."""
    serialized = _stringify(value).strip()
    if len(serialized) <= limit:
        return serialized
    return serialized[:limit].rstrip() + "\n[truncated by Workflow context limit]"


def _add_inferred_agent_handoffs(
    node: dict,
    resolved_config: dict,
    edges: List[dict],
    context: Dict[str, Any],
    node_status: Optional[Dict[str, str]] = None,
) -> dict:
    if (
        node.get("type") != "llm"
        or (resolved_config.get("mode") or "llm") != "agent"
        or str(resolved_config.get("agent_task") or "custom") == "custom"
    ):
        return resolved_config
    handoffs: list[dict[str, Any]] = []
    remaining = 36_000
    for source in _upstream_node_ids(str(node.get("id") or ""), edges):
        if node_status and node_status.get(source) != "succeeded":
            continue
        output = context.get(source)
        if not isinstance(output, dict) or "status" not in output:
            continue
        if remaining <= 0:
            break
        text = _compact_prompt_value(output.get("text") or "", min(12_000, remaining))
        remaining -= len(text)
        handoffs.append({
            "source_node": source,
            "text": text,
        })
    return {**resolved_config, "_upstream_agent_handoffs": handoffs} if handoffs else resolved_config


def _add_inferred_agent_dossier(
    node: dict,
    resolved_config: dict,
    edges: List[dict],
    context: Dict[str, Any],
    nodes: List[dict],
    node_status: Optional[Dict[str, str]] = None,
) -> dict:
    """Give the discovery stage a bounded snapshot from its upstream data node."""
    if (
        node.get("type") != "llm"
        or (resolved_config.get("mode") or "llm") != "agent"
        or str(resolved_config.get("agent_task") or "custom") != "analysis"
    ):
        return resolved_config
    node_types = {str(item.get("id")): item.get("type") for item in nodes}
    snapshots: list[dict[str, str]] = []
    remaining = 32_000
    for source in _upstream_node_ids(str(node.get("id") or ""), edges):
        if node_types.get(source) not in {"job_source", "document_source"}:
            continue
        if node_status and node_status.get(source) != "succeeded":
            continue
        output = context.get(source)
        if output is None or remaining <= 0:
            continue
        snapshot = _compact_prompt_value(output, remaining)
        remaining -= len(snapshot)
        snapshots.append({"source_node": source, "content": snapshot})
    return {**resolved_config, "_workflow_dossier": snapshots} if snapshots else resolved_config


def _add_inferred_publish_artifact_source(
    node: dict,
    resolved_config: dict,
    edges: List[dict],
    context: Dict[str, Any],
    node_status: Optional[Dict[str, str]] = None,
) -> dict:
    if node.get("type") != "publish_artifact" or resolved_config.get("auto_source") is not True:
        return resolved_config
    candidates: list[str] = []
    for edge in edges:
        if edge.get("target") != node.get("id"):
            continue
        source = edge.get("source")
        if node_status and node_status.get(source) != "succeeded":
            continue
        output = context.get(source)
        if not isinstance(output, dict):
            continue
        for artifact in output.get("artifacts") or []:
            if isinstance(artifact, dict) and artifact.get("verified") and artifact.get("path"):
                candidates.append(str(artifact["path"]))
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        raise NodeExecutionError("Publish Artifact: no verified artifact was produced by the connected Agent")
    if len(candidates) > 1:
        raise NodeExecutionError("Publish Artifact: multiple verified artifacts found; choose a source file explicitly")
    return {**resolved_config, "source_path": candidates[0]}


def _resolve_node_config(
    node: dict,
    raw_config: dict,
    edges: List[dict],
    context: Dict[str, Any],
    node_status: Optional[Dict[str, str]] = None,
    nodes: Optional[List[dict]] = None,
) -> dict:
    """Resolve templates and infer a single upstream Job in every execution path."""
    resolved_config = resolve_template(raw_config, context)
    if node.get("type") in {"field_mapping", "jev_score", "jev_choice", "jev_noul"}:
        resolved_config = {
            **resolved_config,
            "_edges": edges,
            "_node_id": node.get("id"),
            # Minor 6: keep the UNRESOLVED input_source template for input_from
            # provenance (resolved values would leak rendered payloads).
            "_input_source_template": raw_config.get("input_source"),
        }
    resolved_config = _add_inferred_agent_job_id(
        node, resolved_config, edges, context, node_status
    )
    resolved_config = _add_inferred_agent_handoffs(
        node, resolved_config, edges, context, node_status
    )
    resolved_config = _add_inferred_agent_dossier(
        node, resolved_config, edges, context, nodes or [], node_status
    )
    resolved_config = _add_inferred_publish_artifact_source(
        node, resolved_config, edges, context, node_status
    )
    return _add_inferred_publish_artifact_job_id(
        node, resolved_config, edges, context, node_status
    )


def execute_workflow_run(db: Session, run: WorkflowRun) -> None:
    """Execute one workflow run synchronously, persisting node activity."""
    definition = run.definition_snapshot or {}
    nodes: List[dict] = definition.get("nodes") or []
    edges: List[dict] = definition.get("edges") or []

    run.status = "running"
    run.started_at = _now()
    db.commit()

    # Pre-create node-run rows so the UI immediately shows pending steps
    node_run_map: Dict[str, WorkflowNodeRun] = {}
    for n in nodes:
        nr = WorkflowNodeRun(
            run_id=run.id,
            node_id=n["id"],
            node_type=n.get("type", "unknown"),
            node_label=(n.get("data") or {}).get("label"),
            status="pending",
        )
        db.add(nr)
        node_run_map[n["id"]] = nr
    db.commit()

    context: Dict[str, Any] = {
        "trigger": run.trigger_input or {},
        "_run_id": str(run.id),
        "_owner_user_id": _workflow_owner_id(db, run.workflow_id),
    }

    incoming: Dict[str, List[dict]] = {}
    for e in edges:
        incoming.setdefault(e.get("target"), []).append(e)

    trigger_types = {"trigger_manual", "trigger_schedule", "trigger_webhook"}
    node_status: Dict[str, str] = {}
    run_failed_error: Optional[str] = None
    fallback_result: Any = None
    fallback_result_node_id: Optional[str] = None
    webhook_result: Any = None
    webhook_result_node_id: Optional[str] = None

    try:
        ordered = _topological_order(nodes, edges)
    except NodeExecutionError as exc:
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = _now()
        db.commit()
        return

    for node in ordered:
        node_id = node["id"]
        node_type = node.get("type", "unknown")
        nr = node_run_map[node_id]

        # Decide whether this node should execute
        should_run = False
        if node_type in trigger_types:
            should_run = not incoming.get(node_id)
        in_edges = incoming.get(node_id) or []
        if in_edges and run_failed_error is None:
            for e in in_edges:
                src = e.get("source")
                if node_status.get(src) != "succeeded":
                    continue
                src_output = context.get(src)
                src_node = next((n for n in nodes if n["id"] == src), None)
                if src_node and src_node.get("type") == "condition":
                    branch = str((src_output or {}).get("result", False)).lower()
                    handle = (e.get("sourceHandle") or "true").lower()
                    if handle == branch:
                        should_run = True
                        break
                elif src_node and src_node.get("type") == "jev_choice":
                    branch = jev_choice_branch(src_output)
                    handle = (e.get("sourceHandle") or "")
                    if handle and handle == branch:
                        should_run = True
                        break
                else:
                    should_run = True
                    break

        if run_failed_error is not None or not should_run:
            nr.status = "skipped"
            nr.finished_at = _now()
            node_status[node_id] = "skipped"
            db.commit()
            continue

        # Execute the node
        logs: List[str] = []

        def log(msg: str) -> None:
            timestamp = _now().strftime("%H:%M:%S")
            logs.append(f"[{timestamp}] {msg}")

        raw_config = (node.get("data") or {}).get("config") or {}
        nr.status = "running"
        nr.started_at = _now()
        db.commit()

        try:
            resolved_config = _resolve_node_config(
            node, raw_config, edges, context, node_status, nodes
            )
            nr.input = _safe_json(redact_secrets(resolved_config))
            executor = EXECUTORS.get(node_type)
            if not executor:
                raise NodeExecutionError(f"Unknown node type: {node_type}")
            output = executor(db, resolved_config, {**context, "_node_id": node_id}, log)
            context[node_id] = output
            nr.output = _safe_json(redact_secrets(output))
            if node_type == "jev_choice":
                _check_jev_choice_branch_wired(node_id, output, edges)
            nr.status = "succeeded"
            node_status[node_id] = "succeeded"
            if node_type == "webhook_response":
                if isinstance(output, dict) and output.get("visible"):
                    webhook_result = output
                    webhook_result_node_id = node_id
            else:
                fallback_result = output
                fallback_result_node_id = node_id
        except Exception as exc:  # noqa: BLE001 — node failures must not kill the loop
            logger.exception("Workflow node %s failed", node_id)
            nr.status = "failed"
            nr.error = str(exc)[:4000]
            node_status[node_id] = "failed"
            run_failed_error = f"Node '{(node.get('data') or {}).get('label') or node_id}' failed: {exc}"
        finally:
            nr.logs = "\n".join(logs) if logs else None
            nr.finished_at = _now()
            db.commit()

    run.status = "failed" if run_failed_error else "succeeded"
    run.error = run_failed_error
    if not run_failed_error:
        selected_result = webhook_result if webhook_result is not None else fallback_result
        run.result = _safe_json(redact_secrets(selected_result))
        run.result_node_id = webhook_result_node_id or fallback_result_node_id
    run.finished_at = _now()
    db.commit()


def _build_context_from_last_run(db: Session, workflow_id: Any) -> Optional[Dict[str, Any]]:
    """Reconstruct an execution context from the most recent full run of a workflow.

    Returns {node_id: output, ..., "trigger": <trigger_input>} or None if there is
    no prior full run (manual/schedule) to borrow data from.
    """
    last_run = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.trigger_type.in_(["manual", "schedule"]),
        )
        .order_by(WorkflowRun.created_at.desc())
        .first()
    )
    if not last_run:
        return None

    context: Dict[str, Any] = {"trigger": last_run.trigger_input or {}}
    for nr in last_run.node_runs:
        if nr.output is not None:
            context[nr.node_id] = nr.output
    return context


def execute_single_node(db: Session, run: WorkflowRun, node_id: str) -> None:
    """Execute one node in isolation, borrowing upstream data from the last full run.

    Persists a single WorkflowNodeRun so the existing Activity panel can show it.
    """
    definition = run.definition_snapshot or {}
    nodes: List[dict] = definition.get("nodes") or []
    node = next((n for n in nodes if n["id"] == node_id), None)

    run.status = "running"
    run.started_at = _now()
    db.commit()

    if not node:
        run.status = "failed"
        run.error = f"ไม่พบโหนด {node_id} ใน workflow"
        run.finished_at = _now()
        db.commit()
        return

    node_type = node.get("type", "unknown")
    nr = WorkflowNodeRun(
        run_id=run.id,
        node_id=node_id,
        node_type=node_type,
        node_label=(node.get("data") or {}).get("label"),
        status="pending",
    )
    db.add(nr)
    db.commit()

    # Trigger nodes have no upstream — just echo the last run's trigger input
    is_trigger = node_type in ("trigger_manual", "trigger_schedule", "trigger_webhook")
    context = _build_context_from_last_run(db, run.workflow_id)
    if context is None and not is_trigger:
        nr.status = "failed"
        nr.error = "กรุณารัน workflow แบบเต็มอย่างน้อย 1 ครั้งก่อน เพื่อให้มีข้อมูลจากโหนดก่อนหน้า"
        nr.finished_at = _now()
        db.commit()
        run.status = "failed"
        run.error = nr.error
        run.finished_at = _now()
        db.commit()
        return
    if context is None:
        context = {"trigger": {}}
    context["_run_id"] = str(run.id)
    context["_owner_user_id"] = _workflow_owner_id(db, run.workflow_id)

    logs: List[str] = []

    def log(msg: str) -> None:
        logs.append(f"[{_now().strftime('%H:%M:%S')}] {msg}")

    log("ทดสอบโหนดนี้ด้วยข้อมูลจากการรันเต็มครั้งล่าสุด")
    raw_config = (node.get("data") or {}).get("config") or {}
    nr.status = "running"
    nr.started_at = _now()
    db.commit()

    error: Optional[str] = None
    try:
        resolved_config = _resolve_node_config(
            node, raw_config, definition.get("edges") or [], context
        )
        nr.input = _safe_json(redact_secrets(resolved_config))
        executor = EXECUTORS.get(node_type)
        if not executor:
            raise NodeExecutionError(f"Unknown node type: {node_type}")
        output = executor(db, resolved_config, {**context, "_node_id": node_id}, log)
        nr.output = _safe_json(redact_secrets(output))
        nr.status = "succeeded"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Single-node test %s failed", node_id)
        nr.status = "failed"
        nr.error = str(exc)[:4000]
        error = f"โหนด '{(node.get('data') or {}).get('label') or node_id}' ล้มเหลว: {exc}"
    finally:
        nr.logs = "\n".join(logs) if logs else None
        nr.finished_at = _now()
        db.commit()

    run.status = "failed" if error else "succeeded"
    run.error = error
    run.finished_at = _now()
    db.commit()


def _safe_json(value: Any) -> Any:
    """Ensure a value is JSON-serializable (truncate huge strings)."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"repr": repr(value)[:2000]}
    if len(text) > 200_000:
        # Keep verified artifact metadata usable by run downloads even when an
        # Agent's final narrative has to be truncated for database storage.
        if isinstance(value, dict):
            preserved = {
                key: value[key]
                for key in (
                    "status", "job_id", "artifact", "artifacts", "filename",
                    "path", "storage_key", "mime_type", "size", "verified",
                    "published", "warnings", "error",
                )
                if key in value
            }
            return json.loads(json.dumps({
                "truncated": True,
                "preview": text[:10_000],
                **preserved,
            }, ensure_ascii=False, default=str))
        return {"truncated": True, "preview": text[:10_000]}
    return json.loads(text)
