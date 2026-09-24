# Jev Workflow Node — Study (Phase: design only, no code)

> วันที่ศึกษา: 2026-09-23 · โดย Hermes (PM) · **ยังไม่ implement · ยังไม่ commit**
> Scope: เสนอแนวทางนำ Jev (TypeSafe) มาเป็น node ใน Workflow ของ InsightDOCv2

---

## 1) แผนภาพ flow ปัจจุบันของ Workflow

```
Trigger (manual / schedule / webhook)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│ run_workflow_task / test_node_task   (Celery queue:      │
│  backend/app/tasks/workflow_tasks.py)      "workflows")  │
│  → execute_workflow_run() / execute_single_node()        │
│    (backend/app/services/workflow_engine.py)             │
│  worker: insightocrv2-celery_workflow_worker-1           │
│          (-Q workflows, concurrency=2)                   │
└──────────────────────────────────────────────────────────┘
        │  EXECUTORS dict (workflow_engine.py ~L1984)
        ▼
┌─ data ─────────────┐  ┌─ AI ──────┐  ┌─ logic/IO ──────────────────┐
│ job_source         │  │ llm       │  │ condition · transform ·      │
│ document_source    │  │ (LLM mode │  │ python_code (sandbox) ·      │
│ gdrive_import      │  │  /Agent)  │  │ http_request · api ·         │
│ onedrive_import    │  └───────────┘  │ write_output ·               │
│                    │                 │ publish_artifact ·           │
│                    │                 │ webhook_response ·           │
│                    │                 │ gdrive_upload · onedrive_*   │
└────────────────────┘                 └──────────────────────────────┘
```

- `job_source` / `document_source` ดึงเอกสารจาก Job พร้อม `ocr_text`, `extracted_data`,
  `reviewed_data` (workflow_engine.py `_exec_job_source` L603+, `_exec_document_source` L566+)
- `transform` = remap template ใน context เท่านั้น (`_exec_transform` L1196 — วน
  `config.mappings` แล้ว `out[target] = value`) **ไม่เรียก map_fields/Jev/Softnix**
- Output ของแต่ละ node ถูกเก็บใน run context ให้ downstream อ้างด้วย `{{node_id.field}}`

## 2) Jev ถูกเรียกวันนี้ (Jobs path) vs ช่องว่างใน Workflow

### Jobs path (ใช้งานจริงแล้ว)
| ไฟล์ | บทบาท |
|---|---|
| `backend/app/services/field_mapping.py` | `map_fields(engine=...)`, `jev_mapping()`, `auto_mapping_routes()` (softnix→jev→llm + prune not_configured) |
| `backend/app/services/typesafe.py` | `resolve_typesafe_config` (Settings DB → env), `typesafe_is_configured`, `typesafe_system_one` → `POST {endpoint}/v1/systemone`, model `jev-latest` |
| `backend/app/tasks/document_tasks.py` | `process_document_task` (via `apply_schema_mapping`) + `remap_document_task` — queue `documents` |
| `backend/app/api/v1/endpoints/documents.py` | `POST /{id}/retry-mapping` — engine Literal รวม `jev` |
| Settings | `mapping_engine`, `mapping_fallback_*` (migration 0020) + `typesafe_endpoint`/`typesafe_api_key` (migration 0022) |

ผลตรวจแล้ว: `map_fields(engine=jev)` บน TPS doc → values ถูกต้อง, provider tag `jev:jev-1.13.0`,
evidence `source_matched`, low-confidence → needs_review พร้อม `jev_candidate`

### ช่องว่างใน Workflow
- **ไม่มี node ที่ทำ schema field extraction ด้วย mapping engines เลย** — 18 node types
  ที่มีอยู่ไม่มี "Field Mapping / Jev / OCR schema extract"
- `document_source`/`job_source` ให้ `ocr_text` ได้ (แต่ไม่ส่ง `file_path`) — ตัว node
  mapping ต้องอ่านไฟล์เองผ่าน `get_storage_service().get_local_path(document.file_path)`
  ถ้าต้องการ support fixed-position (bbox) fields
- worker คนละตัว (workflow_worker vs celery_worker) แต่ **image build เดียวกัน**
  (`build: ./backend`) → ถ้า deploy พร้อมกันจะไม่ drift; ความเสี่ยงคือ rebuild ไม่ครบทุก service

## 3) ทางเลือกออกแบบ

### Option A — Field Mapping node (เลือก engine ได้ รวม jev) ⭐ แนะนำ
- node type ใหม่ เช่น `field_mapping`; config: `schema_id` (schema_select มี pattern แล้ว
  ใน gdrive_import L407), `engine` (`auto|softnix|jev|llm|fixed`), `data_source`
  (`ocr_text` จาก upstream), optional `field_names`
- executor `_exec_field_mapping`: รวบรวมเอกสารจาก upstream (job/document_source),
  เรียก `map_fields(text, schema, db, file_path?, engine=...)` reuse ทั้งก้อน —
  ได้ values + evidence report + attempts + skipped routes ฟรี
- **ข้อดี:** ครบทุก engine, สอดคล้อง Jobs UX + Settings policy (auto prune
  not_configured ทำงานให้เอง), reuse โค้ดหลักไม่ duplicate, evidence/needs_review
  เดิมใช้ต่อกับ Review UI ได้
- **ข้อเสีย:** config หนากว่า (schema + engine + data source); ต้องนิยาม output
  contract ชัด (values, evidence, status)
- **ความเข้ากัน:** เรียกจาก workflow_worker ได้ทันทีเพราะ import จาก package เดียว;
  ไม่แตะ Jobs path (แค่ import ฟังก์ชันที่มีอยู่)

### Option B — node เฉพาะ Jev/TypeSafe (`jev` / `typesafe_judgment`)
- บังคับ `engine="jev"`; config บาง (schema_id + data source)
- **ข้อดี:** product story ชัด "Jev node", config ง่าย, low-confidence → needs_review
  ทำ explicit ได้ง่าย
- **ข้อเสีย:** ถ้าวันหน้าต้องการ softnix/llm ใน Workflow ต้องทำ node ซ้ำ pattern;
  ผูก Settings TypeSafe แน่น (key หาย = node ตาย ไม่มี fallback); เสีย auto chain
  ที่ prune not_configured ให้แล้ว
- **ความเข้ากัน:** เหมือน A แต่ครอบ scope แคบกว่า

### Option C — extend `transform` node (ไม่แนะนำ)
- เพิ่มโหมดใน transform ให้เรียก map_fields
- **ข้อดี:** palette ไม่โต
- **ข้อเสีย:** ชนความหมาย (template remap vs schema extract), UX สับสน,
  config schema ของ transform ไม่รองรับ schema_select/engine, refactor กว้าง
- **ความเข้ากัน:** ต้องแก้ validation + FE widgets ของ transform มากกว่า A/B

### เปรียบเทียบ worker/Settings compatibility
| | A (field_mapping) | B (jev-only) | C (transform ext) |
|---|---|---|---|
| reuse map_fields | เต็ม | บางส่วน (เรียกตรง jev_mapping) | ผ่าน wrapper |
| Auto prune not_configured | ได้ฟรี | ไม่ (ต้อง handle เอง) | กำกวม |
| Settings TypeSafe dependency | ผ่าน engine เลือกได้ | บังคับผูก | กำกวม |
| effort | กลาง | ต่ำ | สูง (refactor) |

## 4) Recommendation

**เลือก Option A — node `field_mapping`** โดย:
- type name: `field_mapping`, category `processing`, label ไทย "Field Mapping (Schema)"
- config: `schema_id` (schema_select), `engine` select ค่าเดียวกับ Jobs
  (`auto|softnix|jev|llm|fixed`, default จาก Setting.mapping_engine), `field_names` (optional)
- input: เอกสารจาก `job_source`/`document_source` upstream (อ่าน `ocr_text` +
  Document.file_path จาก DB เพื่อ support bbox) — ระบุ data flow ให้ executor ดึง
  Document ซ้ำจาก job_id แบบเดียวกับ `_exec_job_source` เพื่อได้ `file_path`
- output fields: `values` (dict), `status`, `evidence` (report.fields),
  `unresolved_fields`, `review_fields`, `provider` (เช่น `jev:jev-1.13.0`), `warnings`
- กรณี TypeSafe not configured + engine=jev → node fail พร้อม message ชัด
  (ไม่ silent skip); engine=auto → ใช้ auto prune แล้วรายงาน skipped ใน `warnings`

ไฟล์ที่คาดว่าจะแตะเมื่อ implement (ยังไม่ทำ):
- `backend/app/services/workflow_engine.py` — NODE_TYPES + `_exec_field_mapping` + EXECUTORS
- `backend/app/services/workflow_validation.py` — validate engine value + upstream data source
- `backend/app/tasks/workflow_tasks.py` — พิจารณา soft_time_limit (default ตอนนี้ไม่จำกัด
  แต่ควรกัน Jev/รวม engines กินเวลานานบน concurrency=2)
- FE: `frontend/app/(dashboard)/workflows/[id]/page.tsx` (help content ใช้ pattern
  FIELD_HELP/NODE_HELP_CONTENT เดิม), `frontend/lib/workflows-api.ts` (node type มาจาก
  `getNodeTypes` อยู่แล้ว ไม่ต้องแก้ถ้า backend เพิ่มให้)
- Tests: `backend/test/test_workflow_validation.py` + pattern จาก `test_field_mapping.py`
  (mock `map_fields` / monkeypatch `typesafe_system_one`)

## 5) ความเสี่ยง

1. **Thai candidates ไม่ครบ** — `jev_mapping.candidates_for` ใช้ space-split n-grams
   + `:`-value patterns; เอกสารไทยติดต่อกันยาวจะได้ candidate ไม่ตรง → recall ต่ำ
   → ควรแก้ candidates ก่อน/พร้อมกับ node (เช่น line-based candidates) ไม่งั้น node
   จะรายงาน missing เยอะ
2. **bbox skip Jev by design** — fixed locator fields เติมด้วย bbox ก่อน และ
   pending ไม่ส่งกลับไป Jev; Workflow node ที่เรียก `map_fields` ทั้งก้อนจะได้
   พฤติกรรมเดียวกับ Jobs โดยไม่ต้องทำอะไร (เอกสารไม่มี locator = Jev รับหมด);
   ถ้าเลือก B (jev-only) ต้องตัดสินใจว่าจะ "ข้าม fixed" หรือ "error"
3. **worker image drift** — backend / celery_worker / workflow_worker build จาก
   `./backend` เดียวกัน ต้อง rebuild+up พร้อมกันทุกครั้งที่แตะ field_mapping/typesafe
   (แผน deploy: `docker compose build backend` → `up -d backend celery_worker
   celery_workflow_worker celery_beat` + restart nginx)
4. **not_configured** — key หาย: engine=jev explicit ต้อง fail ชัด (ข้อความไทยกำกับ);
   engine=auto จะ skip jev + รายงาน skipped (พฤติกรรมเดิมจาก Jobs)
5. **timeout / worker starvation** — workflow_worker concurrency=2; map_fields มี
   MAPPING_TOTAL_TIMEOUT_SECONDS=300 และ Jev per-request 90s อยู่แล้ว; ไม่ควรรัน
   field mapping พร้อมกันเป็นสิบเอกสารใน workflow เดียวโดยไม่จำกัด limit
6. **Jobs regression** — ห้ามแก้ map_fields signature/พฤติกรรม; reuse เท่านั้น;
   regression = `test_field_mapping.py` + retry-mapping e2e ต้องผ่าน

## 6) Draft acceptance criteria (เฟส implement ถัดไป — ยังไม่ทำโค้ด)

1. `GET /workflows/node-types` มี node `field_mapping` พร้อม config schema
   (schema_select + engine รวม `jev` + optional field_names)
2. รันบน workflow_worker สำเร็จ: input OCR text + schema → output มี
   `values` + `evidence` + provider tag (`jev:…`) ตรมด้วยเอกสารจริง ≥1 ชุด
3. TypeSafe ไม่ config + engine=jev → node status=failed พร้อม message ระบุวิธีแก้
   (ไป Settings); engine=auto → skip jev พร้อม warnings ระบุ skipped routes
4. Jobs Processing เดิมผ่าน regression: `pytest test_field_mapping.py
   test_mapping_retry.py` + manual retry-mapping (engine=jev) ยังทำงาน
5. ไม่มี commit/push; ไม่แก้ Settings OCR & Providers UI ที่ค้าง uncommitted;
   ไม่เปลี่ยน live settings
6. (Optional) เพิ่ม section ใน `docs/workflow-guide-th.md` หรือสร้าง doc ใหม่
   อธิบาย node + ตัวอย่างกราฟ trigger_manual → job_source(ocr_text) →
   field_mapping(jev) → condition → write_output

---

## 7) คุณสมบัติของ Jev ที่ InsightDOC มีจริงวันนี้ (extract จากโค้ด + การทดสอบจริง)

### 7.1 ระดับ primitive (สิ่งที่โมเดล/Jev API ให้)
| คุณสมบัติ | ในโค้ด | หลักฐาน/ที่มา |
|---|---|---|
| **Choice judgment** — เลือก 1 ตัวเลือกจาก candidates ที่ code กำหนด + probability ครบทุก option + confidence 0-1 | `field_mapping.py::jev_mapping` สร้าง 1 Choice question ต่อ 1 field, options = candidates + `__none__` | ยืนยันจริง: `reference='MAP-42'`, `total=25.0` provider `jev:jev-1.13.0` |
| **Noul** — P(true) สำหรับคำถาม yes/no (ยังไม่ได้ใช้ใน mapping แต่ API รองรับ) | มีใน `settings.py::test_typesafe_configuration` (คำถาม connection test) | API docs + live test 401 ตอบกลับถูกต้อง |
| **Score** — ให้คะแนนตาม rubric ที่นิยาม levels (ยังไม่ได้ใช้) | — | API docs (`type: "score"`) |
| **Select instead of generate** — Jev เลือกจาก candidates verbatim ไม่แต่งค่า | `candidates_for()` ดึงค่าจาก text ด้วย regex ตาม type (number/date/boolean/text n-grams) | กัน hallucination โดย design |
| **Confidence + uncertainty** | `MAPPING_JEV_CONFIDENCE_FLOOR=0.7` — ต่ำกว่าเก็บไว้ `jev_candidate` ไม่รับค่า | cookbook: uncertainty band → HITL |
| **เสถียรกว่า LLM + เร็ว + ถูก** | per-question SD 0.0102, ~111ms, ~$0.00004/call (เทียบ LLM เร็วกว่า 10-125x ถูกกว่า 22-805x) | consistency cookbook (ตัวเลขอ้างอิง vendor ต้อง measure ต่อบน data จริง) |
| **ไม่ deterministic 100%** — borderline ยังแกว่ง (ตัวอย่าง 0.43-0.53) | — | cookbook + ต้องออกแบบ threshold ให้ทน |

### 7.2 ระดับแอปพลิเคชัน (สิ่งที่ InsightDOC build ทับไว้แล้ว)
| คุณสมบัติ | ที่อยู่ | สถานะ |
|---|---|---|
| **Extract ตาม JSON Schema** — 1 call ตอบหลาย field พร้อมกัน | `jev_mapping` รับ schema → properties → questions map | ✅ ใช้งานจริง (Jobs) |
| **Type normalization** — candidate ถูก normalize ตาม schema type ผ่าน `accept()` เดียวกับ engines อื่น | `field_mapping.py` (`_normalize_schema_value`) | ✅ (ยืนยัน: `"25"` → `25.0` currency) |
| **Confidence floor → needs_review** | `< 0.7` → เก็บ `jev_candidate{value,confidence}` + mark needs_review ให้ engine ถัดไปลอง | ✅ |
| **Evidence & source matching** | `source_evidence()` — quote + text_start/end, status source_matched/needs_review/missing; bbox ให้ page + locator proof | ✅ ใช้ร่วมกับ Review UI |
| **Auto chain + prune** | `auto_mapping_routes()` — softnix→jev→llm พร้อมตัด engine ที่ not_configured + รายงาน skipped | ✅ |
| **Remap / retry per engine** | `remap_document_task` + `POST /documents/{id}/retry-mapping` (engine Literal รวม jev) | ✅ |
| **Settings plumbing** | Settings DB (endpoint+key, mask/unmask) → env fallback → `resolve_typesafe_config()` error message ชัด | ✅ migration 0022 |
| **Mapping test task** | `test_mapping_providers_task` ทดสอบ softnix/jev/llm ด้วย sample มาตรฐาน | ✅ |
| **bbox locator pre-pass** | fixed-position fields เติมก่อน แล้ว pending ไม่ส่งกลับไป Jev (by design) | ✅ |
| **Thai text candidates** | space-split n-grams (1-4 คำ) + `:`-value lines | ⚠️ ยังไม่ครบ — เอกสารไทยเชื่อมยาว recall ต่ำ (ทดสอบจริง: `หนังสือรับรองผลติ` ขาด tail) |

## 8) ลำดับความสำคัญ: คุณสมบัติไหนควรเข้า Workflow process (P0/P1/P2)

> เฟรม: Workflow flow ประกอบด้วย ingest → OCR/schema extraction → mapping → ตรวจสอบ → แปลง/ส่งต่อ → รายงาน Jev เก่งเรื่อง "ตัดสินใจเชิงความหมายที่ถูก/ผิดบนข้อมูลที่มีอยู่" ไม่ใช่ "สร้างเนื้อหา"

### P0 — เอาเข้าเลยเมื่อ implement node (ช่วยขั้น extraction โดยตรง)
| คุณสมบัติ | ช่วยขั้นไหน | เหตุผล |
|---|---|---|
| **Extract ตาม schema ด้วย Choice+candidates** (node `field_mapping`) | ขั้น mapping ที่วันนี้ workflow ไม่มี | ปิดช่องว่างใหญ่สุด; reuse ของเดิมทั้งหมด; เอกสารที่ผ่าน OCR มาแล้วจะถูกดึงเป็น structured JSON ได้ใน workflow โดยไม่ต้องรัน Jobs |
| **Confidence floor → needs_review + jev_candidate** | ขั้นตรวจสอบ (routing) | เปลี่ยนความไม่แน่นอนของโมเดลเป็นเส้นทางชัด: มั่นใจ → ผ่านต่อ, ไม่แน่ใจ → ให้ engine ถัดไป/HITL — เหมาะกับ workflow ที่ต่อ condition node ทันที |
| **Auto chain + prune not_configured** | ทั้ง flow | ทำให้ workflow ไม่พังทั้งรันแค่เพราะ key หาย — engine อื่นรับช่วงต่อ + warnings ระบุ |

### P1 — เอาเข้ารอบถัดไป (เพิ่มคุณภาพ/ปิดวงจร HITL)
| คุณสมบัติ | ช่วยขั้นไหน | เหตุผล |
|---|---|---|
| **Evidence + source_matched แสดงใน node output** | ขั้นตรวจสอบ + audit | downstream (`condition`, `write_output`, artifact) เลือกได้ว่าจะใช้เฉพาะ field ที่ source_matched; ผู้รีวิวเห็น quote ประกอบ |
| **Remap/retry เฉพาะ field ที่ unresolved** (ผูกกับ condition branch) | ขั้น mapping → retry | workflow แบบ "ถ้า unresolved → เด้งกลับเข้า mapping อีกรอบด้วย engine อื่น" — reuse retry-mapping pattern |
| **Thai candidates แบบ line-based** (แก้ candidates_for) | ขั้น mapping | เอกสารหลักของระบบเป็นไทย — ไม่แก้แล้ว P0 จะโชว์ missing เยอะจน node ดูไม่น่าใช้ |
| **Noul triage rubric ก่อน Agent/LLM stage** | ขั้นก่อน AI แพง | ตัวอย่าง: `needs_manual_review`, `docs_sufficient`, `fraud_flag` — ถูก+เร็ว+เสถียรกว่าการยิง LLM Agent ทุกเอกสาร; ใช้ผลจัด route ด้วย condition node |

### P2 — มองยาว / รอ use case จริง
| คุณสมบัติ | เหตุผลที่ยังไม่เอา |
|---|---|
| **Score rubric** (ให้คะแนนคุณภาพเอกสาร/ความสะอาด OCR) | ยังไม่มี requirements จริง — รอใครขอ dashboard "คุณภาพเอกสารต่อ job" ก่อน |
| **Composite scoring / weighted views** | ต้องมี labeled outcomes + calibration ก่อน ไม่งั้นตัวเลขหลอก |
| **Speculative fan-out / parallel judgments ข้ามเวอร์ชัน** | ซับซ้อนสูง workflow_worker concurrency=2 ไม่รับ |
| **Feature discovery (judgments → ML features)** | เกิน scope ระบบงานเอกสาร ณ ปัจจุบัน |

## 9) สิ่งที่ "ไม่ควร" ดึงเข้า Workflow ตอนนี้

| ห้าม/ไม่ควร | เหตุผล |
|---|---|
| **Jev สร้างเนื้อหา/สรุปยาว** (ใช้แทน LLM node ในการ generate) | Jev ไม่ใช่ text generator — ออกแบบให้ตัดสินใจ typed สั้น ๆ; งานเขียน/สรุปให้ LLM/Agent node เดิม |
| **ตัด bbox/fixed-position ออกเพื่อ "ให้ Jev ลองหมด"** | bbox proof แม่นกว่า (มี page+locator); การส่ง field ที่มี locator ไปให้ Jev เสี่ยงค่าแย่งกัน + conflict ใน evidence |
| **ใช้ confidence เป็น "ความถูกต้อง" เด็ดขาด** (เช่น 0.9 = ถูกแน่) | confidence สะท้อน distribution concentration — typed output การันตี interface ไม่การันตี truth; ต้อง calibrate กับ labeled data ก่อนตัดสินใจอัตโนมัติระดับ risk สูง |
| **Hard-fail ทั้ง workflow เมื่อ TypeSafe key หาย + engine=auto** | auto prune มีไว้เพื่อความต่อเนื่อง — ควรรายงาน warnings + ให้ engine อื่นทำงาน (fail ชัดเฉพาะ engine=jev explicit) |
| **รัน Jev mapping คู่ขนานเป็นสิบเอกสารใน workflow เดียว** | workflow_worker concurrency=2 + MAPPING_TOTAL_TIMEOUT 300s — ควรจำกัด batch/limit ต่อ run ไม่งั้น starve agent nodes |
| **ยุบงาน Settings/Typesafe config เข้า node config** (เช่น ให้ node ใส่ key เอง) | key ต้องอยู่ server-side และจัดการกลางที่ Settings เดียว — กระจายใน node = ความเสี่ยง leak + จัดการยาก |

---

*เอกสารนี้เป็นผลศึกษาเท่านั้น — ห้ามนำไป implement โดยไม่ได้รับคำสั่ง · ห้าม commit*

---

## 10) Phase implement P0 — ดำเนินการแล้ว (2026-09-24, uncommitted)

พี่ทอมอนุมัติ Option A / P0 → implement เสร็จสิ้นตาม spec ล็อก:

### ไฟล์ที่แตะ
| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `backend/app/services/workflow_engine.py` | node `field_mapping` ใน NODE_TYPES (schema_select + engine auto\|softnix\|jev\|llm\|fixed + field_names + limit=10) · seam helpers `_field_mapping_setting/_schema/_documents` · `_exec_field_mapping` (ดึงเอกสารจาก upstream job/document source หรือ job_id, resolve file_path ต่อเอกสารให้ bbox ทำงาน, เรียก `map_fields` reuse เต็ม, รวม skipped_routes เป็น warnings, engine=jev ไม่ config → fail ข้อความไทยชัด) · register ใน EXECUTORS · inject `_edges` ใน `_resolve_node_config` · import `Setting` |
| `backend/test/test_workflow_field_mapping.py` | **ใหม่** — 7 tests: registration, requires schema, unknown engine, jev not-configured → fail, auto prune → warnings, success outputs (values/review_fields/provider jev:…), no docs → fail |
| `frontend/app/(dashboard)/workflows/[id]/page.tsx` | TYPE_ICON `field_mapping: ListFilter` + NODE_HELP_CONTENT.field_mapping (purpose/steps/example/caution) |

### ผลตรวจ
- **pytest:** `test_workflow_field_mapping.py` 7 passed · รวม regression `test_field_mapping.py + test_mapping_retry.py + test_workflow_validation.py` = **46 passed**
- **E2E บน production (workflow `jev-p0-smoke`, id `2f172e04`):**
  trigger_manual → job_source (job "ทดสอบ 3", ocr_text, limit 2) → field_mapping (schema `10355837`, engine=jev)
  → run **succeeded**; node output: `count=2`, `status=partial`,
  `values={buyer_name: มหาวิทยาลัยราชภัฏบ้านสมเด็จเจ้าพระยา, seller_name: ดีทวัน, document_type: ใบเสนอราคา, seller_tax_id: 0105564021109}`,
  evidence `source_matched` provider `jev:jev-1.13.0`, fields ที่เหลือ missing (Jev ตอบ `__none__` ถูกต้อง)
- **GET /workflows/node-types:** มี `field_mapping` ครบ config_fields, engine options ครบ 5 ค่า
- **FE:** build ผ่าน, chunk บน production มี `Field Mapping (Schema)` + help content; `/workflows` 200
- **Containers:** ทุกตัว up/healthy หลัง rebuild **backend + celery_worker + celery_workflow_worker พร้อมกัน**
  (บทเรียนจริง: compose สร้าง image แยกต่อ service แม้ build เดียวกัน — rebuild ต้องครบทั้ง 3 ไม่งั้น worker ใช้โค้ดเก่า)

### ข้อจำกัดที่รู้ (รอ P1)
- Thai candidates ยังเป็น n-grams — เอกสารไทยยาวจะ missing เยอะ (เห็นจริงใน smoke: 4/จำนวนฟิลด์ schema)
- node อ่าน `file_path` ผ่าน storage เพื่อ bbox แต่ smoke นี้ schema ไม่มี locator → ยังไม่ได้ทดสอบ bbox path ใน workflow
- workflow ทดสอบ `jev-p0-smoke` (is_active) ยังค้างในระบบ — ลบ/ปิดได้ที่หน้า Workflows

### สถานะ: **ยังไม่ commit/push** — รอพี่ทอมสั่ง

---

## 11) Phase: `jev_score` + `jev_choice` decision nodes — ดำเนินการแล้ว (2026-09-24, uncommitted)

### ไฟล์ที่แตะ
| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `backend/app/services/typesafe.py` | `SCORE_SCALES/SCORE_SCALE_MAX/MIN` (anchors 0_100/0_10/1_5) · `typesafe_score()` (1 System One call, rubric ใน instructions, levels จาก scale) · `typesafe_choice()` (criteria map จาก options) — **endpoint เดิม `/v1/systemone` เท่านั้น** |
| `backend/app/services/workflow_engine.py` | NODE_TYPES `jev_score` + `jev_choice` (category data) · `_exec_jev_score` (weight normalize, index→scale mapping, threshold_met) · `_exec_jev_choice` (min_confidence → used_fallback, probabilities/one-hot) · `_require_jev_configured` fail-loud ทั้ง typesafe_jev และ auto · N-way routing ใน run loop: jev_choice วิ่งเฉพาะ edge ที่ sourceHandle == choice (หรือ fallback เมื่อ used_fallback) · EXECUTORS + `_edges` inject |
| `backend/test/test_workflow_jev_decision.py` | **ใหม่ 16 tests**: registration, required fields, not-configured fail-loud (ทั้ง typesafe_jev + auto), scale mapping 0_100/1_5, weight normalize, threshold_met T/F, probabilities, one-hot fallback, min_confidence→fallback, invalid pick key |
| `frontend/app/(dashboard)/workflows/[id]/page.tsx` | TYPE_ICON (Gauge/Split) · NODE_HELP_CONTENT ทั้ง 2 nodes · dynamic handles สำหรับ jev_choice (id = options[].key + fallback, prune ตาม config) · edge labels (Fallback/keys) · `edgeLabel()` helper |

### ผลตรวจ
- **pytest:** test_workflow_jev_decision 16/16 · รวม suite เดิม (field_mapping/mapping_retry/workflow_validation/workflow_field_mapping) = **63 passed**
- **E2E production** (workflow `jev-score-choice-smoke`): trigger → job_source(ocr) → `jev_score` → `jev_choice` — run **succeeded**
  - Score: `score=49.25`, scale 0_100, threshold=50 → `threshold_met=false`, confidence 0.69, provider `jev:jev-1.13.0`
  - Choice: `choice=archive` (เก็บถาวร), probability 0.78, confidence 0.57 ≥ min_confidence 0.2 → `used_fallback=false`, probabilities แสดงครบ
- node-types API มี 21 types — jev_score/jev_choice พร้อม config_fields ครบ
- FE build ผ่าน · containers ทั้ง 10 up/healthy หลัง rebuild ครบ 4 images (backend/celery_worker/celery_workflow_worker/frontend)

### Engine semantics (ต่างจาก mapping โดย design)
- Decision nodes **ต้องมี TypeSafe**: ทั้ง `typesafe_jev` และ `auto` fail-loud พร้อม CTA ไทย หากไม่ config (ไม่มี provider สำรองสำหรับการตัดสินใจ)
- Score = single outbound; Condition downstream อ่าน `{{node.score}}` / `{{node.threshold_met}}`
- Choice = N handles (key ต่อ option) + `fallback`; runtime วิ่งเฉพาะเส้นที่เลือก

### Gaps (แจ้งบุ้ย)
- `pick_rule=first_above_threshold` + `probability_threshold` ยังไม่มี logic แยก (highest เป็น default และ cover กรณีทั่วไป) — เพิ่มได้เมื่อมี use case
- `include_evidence` ยังคืน `[]` (ห้าม fabricate — ต้องออกแบบ evidence จาก upstream จริง ทำใน P ถัดไป)
- jev_noul **ยังไม่เริ่ม** ตาม brief

### สถานะ: **ยังไม่ commit/push** — รอบุ้ย QA แล้วพี่ทอมสั่ง

---

## 12) Phase: `jev_noul` (P2) — ดำเนินการแล้ว (2026-09-24, uncommitted)

### ไฟล์ที่แตะ
| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `backend/app/services/typesafe.py` | `typesafe_noul()` — 1 noul question/call; return `{noul, model}` **เท่านั้น** (vendor ไม่มี confidence/evidence — ไม่ fabricate) |
| `backend/app/services/workflow_engine.py` | NODE_TYPES `jev_noul` (config: noul_name/question/input_source/fields_to_use/threshold/use_with_condition/engine) · `_exec_jev_noul` (fail-loud TypeSafe, threshold_met = noul ≥ threshold inclusive, ไม่มี confidence/evidence) · EXECUTORS + config inject |
| `backend/test/test_workflow_jev_decision.py` | +8 tests noul (รวม 24/24 ทั้งไฟล์): registration (ไม่มี confidence/evidence toggles), required fields, not-configured fail-loud 2 engines, probability+threshold, boundary ≥ inclusive, below threshold, no-threshold → null, missing noul value fail |
| `frontend/app/(dashboard)/workflows/[id]/page.tsx` | TYPE_ICON `jev_noul: ShieldQuestion` · NODE_HELP_CONTENT ไทย (single outbound + Condition note) |

### ผลตรวจ
- **pytest:** test_workflow_jev_decision **24/24** (16 score/choice + 8 noul)
- **E2E production** (workflow `jev-noul-smoke`, ตาม example graph ใน USAGE):
  `trigger_manual → job_source(ocr) → jev_noul → condition → transform ×2`
  - Noul: `noul=0.14` · threshold 0.5 → `threshold_met=false` · provider `jev:jev-1.13.0` · **ไม่มี confidence/evidence ใน output** ✓
  - Condition: result=false → **sink_false รัน (`route=auto`) · sink_true skipped** — พิสูจน์ branch routing ถูกต้อง
- node-types API มี 22 types (รวม jev_noul) · FE build ผ่าน · containers ทั้ง 10 up/healthy

### Design lock ที่ทำตาม
- **Single outbound เท่านั้น** — ไม่มี dual Yes/No handles (canvas + runtime); branching เป็นหน้าที่ของ Condition
- `threshold_met` เป็นค่าอ้างอิง (noul ≥ threshold inclusive) ไม่ใช่ branch บนตัว node
- ไม่มี confidence/evidence — vendor ไม่ให้ และไม่ fabricate

### สถานะ: **ยังไม่ commit/push**

---

## 14) Phase: Code Review fixes (Major 1–4 + Minor 5–7) — ดำเนินการแล้ว (2026-09-24, uncommitted)

| Fix | การแก้ |
|---|---|
| **Major 1** pick_rule/probability_threshold | `_exec_jev_choice` ใช้ pick จริงจาก vendor probabilities: `highest` = max prob (tie → ตัวแรกตามลำดับ options) — override API choice เมื่อไม่ตรง · `first_above_threshold` = เดินตามลำดับที่ config เจอตัวแรกที่ ≥ threshold · ไม่มีตัวผ่าน → fallback เมื่อเปิด ไม่งั้น fail loud ไทย · policy ใส่ `probability_threshold` ด้วย |
| **Major 2** Score honesty | ลบ `include_evidence` ออกจาก NODE_TYPES config_fields · score output **ไม่มี** `evidence: []` ปลอม · label `criteria` = "เกณฑ์ที่ใช้ (rubric)" (ไม่ imply คะแนนรายเกณฑ์) · `include_confidence` คงเดิม |
| **Major 3** resolve wrap | `_require_jev_configured` wrap `resolve_typesafe_config` — `TypeSafeConfigurationError`/`ValueError` → `NodeExecutionError` + CTA ไทยไป Settings |
| **Major 4** fields_to_use | `_jev_decision_input` ใหม่: string/JSON object/list · filter ได้ทั้ง dict และ JSON string · `fields_to_use` รับ list/chips · ใช้ไม่ได้/key ไม่มี → **fail loud ไทย** (ห้าม silent no-op) · seam `_jev_decision_wanted_fields` สำหรับ test |
| **Minor 5** no one-hot | ไม่มี probabilities → `probability: null` + options ไม่มี key probability (ห้ามแต่ง 1.0/0.0) · choice ยังมาจาก API/pick logic |
| **Minor 6** input_from | inject `_input_source_template` (raw ก่อน render) ใน `_resolve_node_config` → noul `input_from` = template เช่น `{{j1.records}}` **ไม่ใช่ self node id** |
| **Minor 7** FE handles | jev_choice handle builder รับ `options` เป็น array (object/string) หรือ string ก็ได้ · skip row ที่ key ว่าง · ไม่ `String(array)` |

### Tests
- `test_workflow_jev_decision.py` +12: highest overrides wrong API key · first_above picks first qualifying · none→fallback / none→fail · fields_to_use JSON-string filter · fields_to_use ไม่ parse → fail loud · missing key → fail · resolve error → NodeExecutionError wrap · noul input_from = template · score ไม่มี evidence key + ไม่มี include_evidence field · criteria label rubric
- ปรับ test เดิม: one-hot → ไม่ fabricate; hide_probabilities → probability null; noul input_from = "ข้อมูลเอกสาร"
- **pytest: decision + graph e2e + field_mapping = 74 passed, 1 skipped** · suite เต็ม (รวม webhook/mapping_retry/validation) = 86 passed

### Rebuild + live smoke
- Rebuild ครบ 4 images (backend/frontend/celery_worker/celery_workflow_worker) — containers ทั้ง 10 up/healthy
- รัน `jev-noul-smoke` ซ้ำบน production หลัง fix: succeeded · noul 0.13 · **`input_from: "{{j1.records}}"`** (Minor 6 ยืนยันบน live) · condition false → sink_false รัน ถูกต้อง

### สถานะ: **ยังไม่ commit/push** — รอบุ้ย QA

---

## 13) Phase: Graph E2E tests สำหรับ Jev decision workflows — ดำเนินการแล้ว (2026-09-24, uncommitted)

### ไฟล์ใหม่
`backend/test/test_workflow_jev_graph_e2e.py` — รัน **กราฟหลาย node เต็ม** ผ่าน `execute_workflow_run`
(ไม่ใช่ unit `_exec_*` โดด ๆ) โดย mock `app.services.typesafe.typesafe_score|choice|noul` + seam
`_jev_decision_setting` — **ไม่มี live TypeSafe call / ไม่แตะ DB / ไม่แตะ credentials** ใน default path

### Scenarios ที่ครอบ (12 tests + 1 optional live skip)
| Test | พิสูจน์ |
|---|---|
| `test_graph_score_threshold_met_propagates` | score/threshold_met ไหลผ่าน template ลง sink (`100.0 met=True`) |
| `test_graph_score_full_below_threshold` | index ต่ำ → 25 / threshold_met False |
| `test_graph_choice_routes_only_matching_handle` | **เฉพาะ** sink บน handle ของ choice ที่ถูกเลือกรัน เส้นอื่น skipped |
| `test_graph_choice_risk_key_wins` | เพิ่ม option `risk_*` → mock เปลี่ยน pick → handle ใหม่คือ choice key |
| `test_graph_choice_fallback_route` | confidence < min_confidence → `used_fallback` → เฉพาะ fallback edge รัน |
| `test_graph_noul_condition_true_path` / `_false_path` | noul 0.9/0.2 → Condition แตก true/false ถูกเส้น · **ไม่มี confidence/evidence** ใน output |
| `test_graph_score_then_noul_chain` | roadmap pattern score → noul → condition ในกราฟเดียว |
| `test_graph_jev_not_configured_fails_run[jev_score|jev_choice|jev_noul]` | run **failed** + error มีคำว่า TypeSafe |
| `test_graph_jev_auto_engine_also_fails_without_typesafe` | Decision `auto` ≠ mapping auto-prune — fail loud เหมือนกัน |
| `test_live_smoke_workflows` (skip ตาม default) | ทำงานเมื่อตั้ง `INSIGHTDOC_JEV_LIVE=1` + token — optional ตาม brief |

### ผลรวม
- E2E graph: **12 passed, 1 skipped (live mark)**
- Suite เต็ม (graph e2e + decision 24 + field_mapping workflow + field_mapping + mapping_retry + validation + webhook): **86 passed, 1 skipped**

### หมายเหตุ
- FakeSession ปิด `query()` ทิ้งเพื่อกัน DB access หลุด — Settings row เข้าถึงผ่าน seam
  `_jev_decision_setting` (patch ใน fixture) · mock control ผ่าน `calls["next_score_index"/"next_noul"]`
- Live-mark เขียนไว้แต่ default skip — ตัดสินใจเองได้ว่าจะใช้หรือไม่ (token ที่ /tmp/jev_tok.txt มีอยู่แล้ว)

### สถานะ: **ยังไม่ commit/push**
