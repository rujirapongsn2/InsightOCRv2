# คู่มือเรียนรู้ Workflow แบบ Step-by-Step

> เป้าหมาย: เรียนรู้การตั้งค่า Workflow Builder ของ InsightOCR ให้ครบทุก node โดยต่อยอดจาก workflow ชื่อ **`test`** ที่มีอยู่แล้ว จนกลายเป็นกระบวนการอัตโนมัติที่สมบูรณ์
>
> เมื่อจบคู่มือนี้คุณจะใช้งานได้ครบทั้ง 9 ชนิด node, เข้าใจการส่งข้อมูลระหว่าง node ด้วย template `{{...}}`, การแตกเงื่อนไข True/False, การรันแบบ manual และตั้งเวลา (schedule) รวมถึงการดูกิจกรรม (Activity) แบบ interactive

---

## 0. ภาพรวมหน้าจอ Builder

เปิดเมนู **Workflow** ที่ sidebar → คลิกที่ workflow ชื่อ **`test`** เพื่อเข้าหน้า Builder

หน้าจอแบ่งเป็น 4 ส่วน:

| ส่วน | ตำแหน่ง | หน้าที่ |
|------|---------|---------|
| **Palette** | ซ้าย | รายการ node ทั้งหมด — ลาก (drag) ไปวางบน canvas |
| **Canvas** | กลาง | พื้นที่วาง node และลากเส้นเชื่อม |
| **Config Panel** | ขวา | ตั้งค่า node ที่เลือก (คลิกที่ node เพื่อเปิด) |
| **Top Bar** | บน | ชื่อ workflow, ปุ่ม Schedule, Activity, **Save**, **Run** |

> 💡 **กฎทอง 2 ข้อ**
> 1. **ต้อง Save ก่อน Run เสมอ** (ปุ่ม Run จะ Save ให้อัตโนมัติถ้ามีการแก้ไขค้างอยู่ — สังเกตป้าย `unsaved` สีเหลือง)
> 2. ทุก workflow ต้องเริ่มด้วย node กลุ่ม **Trigger** เพียงตัวเดียวเป็นจุดเริ่ม

---

## 1. จุดเริ่มต้น: workflow `test` ที่มีอยู่

ตอนนี้ `test` มี 3 node เรียงกันแต่ยัง**ไม่สมบูรณ์**:

```
[Manual Trigger] → [Jobs] → [Condition]   ← Condition ยังไม่ได้ตั้งค่า และไม่มีปลายทาง
```

เราจะค่อย ๆ เติมให้เป็นกระบวนการจริง:
**"ดึงข้อมูลใบจองจาก Job → ตรวจว่ามีข้อมูลไหม → ถ้ามี ให้ LLM สรุป → จัดรูปแบบ → คำนวณด้วย Python → ส่งออกเป็นไฟล์ และยิงเข้า API ภายนอก"**

---

## 2. Node #1 — Manual Trigger (มีอยู่แล้ว)

**หมวด:** Trigger · **ชนิด:** `trigger_manual`

จุดเริ่มของ workflow เวลากดปุ่ม **Run** สามารถแนบ **Trigger input (JSON)** ได้ ซึ่งจะเข้าถึงได้ด้วย `{{trigger.ชื่อฟิลด์}}`

**ลองทำ:**
1. คลิก node **Manual Trigger** — config ว่างเปล่า (ไม่ต้องตั้งค่า) ถูกต้องแล้ว
2. ภายหลังตอนกด Run เราจะใส่ input เช่น `{ "min_count": 1, "notify": true }` เพื่อทดสอบ

> ℹ️ มี Trigger อีกชนิดคือ **Schedule Trigger** (`trigger_schedule`) — ไว้ใช้ตอนตั้งเวลา ดูหัวข้อ **10. การตั้งเวลา**

---

## 3. Node #2 — Jobs (มีอยู่แล้ว)

**หมวด:** Data · **ชนิด:** `job_source`

นำข้อมูลที่ **ประมวลผลแล้ว** จากเมนู Jobs เข้าสู่ workflow

**ตั้งค่า (คลิกที่ node Jobs):**

| ฟิลด์ | ค่าที่ใช้ | ความหมาย |
|-------|----------|----------|
| **เลือก Job** | `Q1` (หรือ Job ที่มีเอกสาร review แล้ว) | เลือกจาก dropdown ไม่ต้องพิมพ์ UUID |
| **ข้อมูลที่ใช้** | `reviewed` | ใช้ข้อมูลที่ตรวจแล้ว (ถ้าไม่มีจะใช้ extracted แทน) |
| **กรองตามสถานะเอกสาร** | เว้นว่าง | ไม่กรองเพิ่ม |
| **เฉพาะเอกสารที่ประมวลผลเสร็จ** | ✅ เปิด | เอาเฉพาะ extraction_completed / reviewed |
| **จำนวนเอกสารสูงสุด** | `50` | จำกัดจำนวน |

**Output ของ node นี้** (จำโครงสร้างไว้ เพราะ node ถัดไปจะอ้างถึง):

```jsonc
{
  "job_id": "...", "job_name": "Q1", "job_status": "review",
  "count": 5,                       // จำนวนเอกสาร
  "records": [ {...}, {...} ],       // ⭐ array ข้อมูลล้วน — เหมาะส่งต่อ LLM/Transform
  "documents": [ { "id", "filename", "status", "data" } ]
}
```

> ⭐ ตัวแปรสำคัญ: `{{job_source_xxx.count}}` และ `{{job_source_xxx.records}}`
> **node id** ดูได้ที่กล่องล่างสุดของ Config Panel เช่น `job_source_mq93l7yz` — จะใช้ id นี้อ้างอิงตลอด

> 🔄 **ทางเลือก — Document Source:** ถ้าต้องการ **OCR text รายหน้า** แทนข้อมูล structured ให้ใช้ node **Document Source** (`document_source`) แทน Jobs โดยมีฟิลด์ `include_ocr_text` ให้เปิด

---

## 4. Node #3 — Condition (เติมค่าให้สมบูรณ์)

**หมวด:** Logic · **ชนิด:** `condition`

ตรวจเงื่อนไขแล้ว**แตกเป็น 2 เส้นทาง**: จุดต่อสีเขียว **T (True)** ด้านบน และสีแดง **F (False)** ด้านล่าง

**ตั้งค่า (คลิก node Condition):**

| ฟิลด์ | ค่าที่ใช้ |
|-------|----------|
| **Value** | `{{job_source_mq93l7yz.count}}` *(แก้ id ให้ตรงกับ node Jobs ของคุณ)* |
| **Operator** | `greater_than` |
| **Compare with** | `0` |

แปลว่า: "ถ้ามีเอกสารมากกว่า 0 ฉบับ → ไปเส้น True, ไม่งั้น → เส้น False"

**Operator ที่เลือกได้:** `equals`, `not_equals`, `contains`, `not_contains`, `greater_than`, `less_than`, `is_empty`, `is_not_empty`

> 💡 การลากเส้นจาก Condition: ลากจากจุด **T** ไป node ฝั่งสำเร็จ และจุด **F** ไป node ฝั่งสำรอง เส้นจะมีป้าย `True`/`False` กำกับ

---

## 5. Node #4 — LLM / Agent (เส้น True)

**หมวด:** AI · **ชนิด:** `llm`

ส่งข้อมูลให้ LLM วิเคราะห์/สรุป/แปลง

**ลากจาก Palette:** ลาก **LLM / Agent** มาวางทางขวาของ Condition แล้ว**ลากเส้นจากจุด T** ของ Condition มาเข้า node นี้

**ตั้งค่า:**

| ฟิลด์ | ค่าที่ใช้ |
|-------|----------|
| **LLM Integration** | เว้นว่าง (ใช้ค่า default ของระบบ) — หรือใส่ id จากเมนู Integration ถ้ามี |
| **Model** | `gpt-4o-mini` |
| **System prompt** | `คุณเป็นผู้ช่วยสรุปข้อมูลใบจอง ตอบเป็นภาษาไทย กระชับ` |
| **Prompt** | `สรุปรายการจองต่อไปนี้เป็น bullet สั้น ๆ:\n\n{{job_source_mq93l7yz.records}}` |
| **Parse output as JSON** | ปิด (เราต้องการข้อความ) |

**Output:** `{ "text": "...คำสรุป..." }` → อ้างด้วย `{{llm_xxx.text}}`

> 💡 ถ้าเปิด **Parse output as JSON** และให้ LLM ตอบเป็น JSON จะได้ `{{llm_xxx.data}}` เป็น object ใช้ต่อได้เลย — เหมาะกับงาน "สกัดฟิลด์" หรือ "จัดหมวด"

---

## 6. Node #5 — Transform / Mapping (เส้น True)

**หมวด:** Logic · **ชนิด:** `transform`

สร้าง object ใหม่จากการ map ค่าด้วย template — เหมาะสำหรับ "ประกอบร่าง" ข้อมูลก่อนส่งออก

**ลากเส้น:** LLM → Transform

**ตั้งค่า — กดปุ่ม `+ เพิ่ม mapping` ทีละแถว:**

| target (ชื่อฟิลด์ใหม่) | value (template) |
|------------------------|------------------|
| `job` | `{{job_source_mq93l7yz.job_name}}` |
| `total_docs` | `{{job_source_mq93l7yz.count}}` |
| `summary` | `{{llm_xxx.text}}` |
| `generated_at` | `{{trigger.run_label}}` |

**Output:** object ตาม mapping เช่น `{ "job": "Q1", "total_docs": 5, "summary": "...", ... }` → อ้างด้วย `{{transform_xxx}}`

---

## 7. Node #6 — Python Code (เส้น True)

**หมวด:** Developer · **ชนิด:** `python_code`

รันโค้ด Python ใน **Docker sandbox** ที่แยกจากระบบ — อ่านข้อมูลจากตัวแปร `inputs` แล้ว**เซ็ตตัวแปร `result`** เป็นผลลัพธ์

**ลากเส้น:** Transform → Python Code

**ตั้งค่า:**

- **Input (รองรับ {{template}}):**
  ```
  {{transform_xxx}}
  ```
  (ค่านี้จะกลายเป็นตัวแปร `inputs` ในโค้ด)

- **Python code:**
  ```python
  # inputs คือ object จาก Transform
  total = inputs.get("total_docs", 0)
  result = {
      "job": inputs.get("job"),
      "headline": f"พบเอกสาร {total} ฉบับ",
      "is_bulk": total >= 10,
      "summary": inputs.get("summary", "")[:200],
  }
  ```

- **Timeout (sec):** `30`

**Output:** `{ "result": {...}, "stdout": "..." }` → อ้างผลด้วย `{{python_code_xxx.result}}`

> ⚠️ **ข้อควรรู้:** node นี้ต้องการ Docker sandbox บนเครื่อง host ถ้าระบบขึ้น log `Failed to pull sandbox image: permission denied` แสดงว่า docker group id ยังไม่ตรง — node อื่นใช้งานได้ปกติ แต่ Python Code จะ error จนกว่าจะแก้สิทธิ์ docker.sock

---

## 8. Node #7 — Write Output (เส้น True)

**หมวด:** Action · **ชนิด:** `write_output`

เขียนผลลัพธ์เป็นไฟล์ที่ดาวน์โหลดได้จากแผง **Activity**

**ลากเส้น:** Python Code → Write Output

**ตั้งค่า:**

| ฟิลด์ | ค่าที่ใช้ |
|-------|----------|
| **File name** | `summary.json` |
| **Format** | `json` |
| **Content** | `{{python_code_xxx.result}}` |

**Format ที่เลือกได้:**
- `json` — ถ้า content เป็น object/array จะถูกจัด indent ให้อัตโนมัติ
- `csv` — ถ้า content เป็น array ของ object จะแปลงเป็นตารางให้
- `text` — ข้อความล้วน

**Output:** `{ "file_path", "filename", "size", "preview" }` — ปุ่ม **ดาวน์โหลด** จะโผล่ในแผง Activity ที่ขั้นตอนนี้

---

## 9. Node #8 — HTTP Request (เส้น True, แตกขนาน)

**หมวด:** Action · **ชนิด:** `http_request`

ส่งผลลัพธ์ต่อไปยังระบบอื่น (REST API / Webhook)

**ลากเส้น:** Python Code → HTTP Request *(node เดียวต่อออกได้หลายเส้นพร้อมกัน — Write Output และ HTTP Request จะทำงานทั้งคู่)*

**ตั้งค่า — ทดสอบด้วย echo service ฟรี:**

| ฟิลด์ | ค่าที่ใช้ |
|-------|----------|
| **Method** | `POST` |
| **URL** | `https://httpbin.org/post` |
| **Headers (JSON)** | `{ "Content-Type": "application/json" }` |
| **Body** | `{{python_code_xxx.result}}` |

**Output:** `{ "status_code": 200, "body": {...} }` → อ้างด้วย `{{http_request_xxx.body}}`

> ℹ️ การยิงออกอินเทอร์เน็ตวิ่งผ่าน gateway proxy ของระบบ ถ้าปลายทางถูกบล็อก จะเห็น error ที่ขั้นตอนนี้ในแผง Activity

---

## 10. Node #9 — Write Output ฝั่ง False (เส้นสำรอง)

ตอนนี้เติมเส้น **F (False)** ของ Condition ให้ครบ เพื่อจัดการกรณี "ไม่มีเอกสาร"

**ลาก Write Output อีกตัว** มาวาง แล้วลากเส้นจากจุด **F** ของ Condition มาเข้า

**ตั้งค่า:**

| ฟิลด์ | ค่าที่ใช้ |
|-------|----------|
| **File name** | `empty.txt` |
| **Format** | `text` |
| **Content** | `ไม่มีเอกสารใน Job {{job_source_mq93l7yz.job_name}} ที่ตรงเงื่อนไข` |

---

## ภาพรวมโครงสร้างสุดท้าย

```
[Manual Trigger]
      │
   [Jobs]  ← Q1, reviewed
      │
 [Condition]  count > 0 ?
      ├─ T ─→ [LLM] → [Transform] → [Python Code] ─┬─→ [Write Output: summary.json]
      │                                            └─→ [HTTP Request: httpbin]
      └─ F ─→ [Write Output: empty.txt]
```

ครบทั้ง 9 ชนิด node: Manual Trigger, Jobs, Condition, LLM, Transform, Python Code, Write Output (×2), HTTP Request *(+ Document Source / Schedule Trigger เป็นทางเลือกในหัวข้อถัดไป)*

---

## 11. การรัน (Manual) และดู Activity

1. กด **Save** (มุมขวาบน) — ป้าย `unsaved` ต้องหายไป
2. กด **Run** → กล่อง modal เด้งขึ้น ใส่ **Trigger input (JSON)**:
   ```json
   { "run_label": "2026-06-11 เช้า", "min_count": 1 }
   ```
3. กด **Run** — แผง **Activity** จะเปิดขึ้นด้านขวาของ canvas
4. สังเกตแบบ interactive:
   - **ขอบ node เปลี่ยนสี** ตามสถานะ: น้ำเงิน(กำลังรัน) → เขียว(สำเร็จ) / แดง(ล้มเหลว) / เทา(ข้าม)
   - เส้นทางที่ Condition ไม่เลือก จะขึ้นสถานะ **skipped**
   - คลิกแต่ละขั้นเพื่อดู **logs / input / output** และปุ่ม **ดาวน์โหลด** ไฟล์
5. ปุ่ม **Activity** บน Top Bar เปิดดู **ประวัติการรันย้อนหลัง** ได้ทุกครั้ง

---

## 12. การตั้งเวลา (Schedule) — ใช้ Schedule Trigger

ถ้าต้องการให้ workflow รันเองตามเวลา:

1. (ตัวเลือก) เปลี่ยนหรือเพิ่ม node เริ่มต้นเป็น **Schedule Trigger** (`trigger_schedule`) — ทำงานเหมือน Manual Trigger แต่สื่อความหมายว่ารันตามเวลา
2. กดปุ่ม **Schedule** (รูปปฏิทิน) บน Top Bar
3. ใส่ **Cron expression** เช่น:
   | Cron | ความหมาย |
   |------|----------|
   | `*/15 * * * *` | ทุก 15 นาที |
   | `0 9 * * 1-5` | 9 โมงเช้า จันทร์–ศุกร์ |
   | `0 0 * * *` | เที่ยงคืนทุกวัน |
   ลำดับช่อง: `นาที ชั่วโมง วัน เดือน วันในสัปดาห์`
4. ติ๊ก **เปิดใช้งาน schedule** → กด **Save**

ระบบมี **celery_beat** ตรวจทุก 30 วินาที เมื่อถึงเวลาจะสร้าง run ใหม่อัตโนมัติ (trigger_type = `schedule`) ดูได้ในประวัติ Activity

> 💡 หลาย workflow ที่ตั้งเวลาไว้ทำงานพร้อมกันได้ เพราะมี worker pool รองรับการรันขนาน

---

## 13. สรุปตัวแปร Template ที่ใช้บ่อย

| รูปแบบ | ตัวอย่าง | ได้อะไร |
|--------|----------|---------|
| `{{trigger.X}}` | `{{trigger.run_label}}` | ค่าจาก input ตอนกด Run |
| `{{nodeId.field}}` | `{{job_source_mq93l7yz.count}}` | ฟิลด์ตรง ๆ จาก output ของ node |
| `{{nodeId.field.0.sub}}` | `{{job_source_x.documents.0.filename}}` | เจาะลึก array/object ด้วยจุด |
| `{{nodeId}}` | `{{transform_x}}` | ทั้ง object ของ node นั้น |

**กฎการแทนค่า:**
- ถ้าทั้งช่องเป็น template เดี่ยว → ได้ค่า**ดิบ** (object/array/number)
- ถ้าผสมข้อความ → ได้**สตริง** (object จะถูกแปลงเป็น JSON)

---

## 14. Checklist ก่อน Run ทุกครั้ง

- [ ] มี Trigger เป็นจุดเริ่มเพียงตัวเดียว
- [ ] ทุก node (ยกเว้น Trigger) มีเส้นเข้าจาก node ก่อนหน้า
- [ ] node id ใน template `{{...}}` ตรงกับ id จริง (ดูที่ Config Panel)
- [ ] Condition ลากครบทั้งเส้น **T** และ **F** (ถ้าต้องการ)
- [ ] กด **Save** จนป้าย `unsaved` หาย
- [ ] ฟิลด์ที่มี `*` (required) กรอกครบ

---

### ภาคผนวก: ตารางอ้างอิง Node ทั้งหมด

| Node | ชนิด | หมวด | Output หลัก |
|------|------|------|-------------|
| Manual Trigger | `trigger_manual` | Trigger | input ที่แนบมา |
| Schedule Trigger | `trigger_schedule` | Trigger | input (จากตาราง) |
| Jobs | `job_source` | Data | `records`, `documents`, `count` |
| Document Source | `document_source` | Data | `documents` (มี ocr_text) |
| LLM / Agent | `llm` | AI | `text` หรือ `data` |
| Condition | `condition` | Logic | `result` (true/false) + แตกเส้น T/F |
| Transform | `transform` | Logic | object ตาม mapping |
| Python Code | `python_code` | Developer | `result`, `stdout` |
| HTTP Request | `http_request` | Action | `status_code`, `body` |
| Write Output | `write_output` | Action | ไฟล์ดาวน์โหลด + `preview` |
