# UAT: AI Agent ใน Jobs (A2UI v2)

ทดสอบการแสดงผลแบบ interactive ของ AI Agent ในหน้า Job หลัง redesign เป็น A2UI v2
เวอร์ชันที่ทดสอบ: `main` @ `5515c01` (A2UI v2 panels, structured panel clicks, confirmation expiry, same-origin pdf.js worker), DB migration `0031_agent_ui_actions`, build ด้วย docker compose

รอบ 2 (2026-11-01, `main` @ `ad33512` หลังรอบแก้ B1-B4, M1-M4) อยู่ในหัวข้อ "ผลรอบ 2" ท้ายไฟล์ ตารางด้านล่างเป็นผลรอบ 1 คงไว้ตามเดิม

บันทึกผลในคอลัมน์ "ผล" เป็น ✅ ผ่าน / ❌ ไม่ผ่าน / ⚠️ ผ่านบางส่วน หมายเหตุจดสิ่งที่เห็นจริง (ข้อความใน UI, ค่าจาก API/DB) และ path ภาพหน้าจอ

ผลรอบก่อน (v1, `main` @ `4e01714`, 2026-10-31): ✅ 19 / ⚠️ 5 / ❌ 1 ปัญหาหลักคือหน้าเลื่อนแนวนอนที่ 360px, delta ของ Metric ผิดหน่วย, title บทสนทนาเก็บ JSON ดิบ, API คืนแค่ 50 ข้อความ, pdf.js worker โหลดจาก unpkg และกล่องยืนยันค้างหลังหมดเวลา ทุกข้อถูกออกแบบใหม่ใน v2 และทดสอบซ้ำด้านล่าง ภาพและ log ของรอบก่อนอยู่ที่ `<scratchpad>/uat/shots/` และ `logs/`

## สิ่งที่เปลี่ยนใน v2 (ตรวจกับโค้ดบน main แล้ว)

- แผงเป็นเครื่องมือระดับงาน 5 ตัวแทน `render_ui`: `show_documents`, `show_metrics`, `show_table`, `show_chart`, `show_risks` (`backend/app/agent/a2ui.py`, `backend/app/agent/tools/ui_tools.py`)
- backend กำหนดชนิดค่า (kind) และคำนวณการเปลี่ยนแปลงใน `compare()` (`a2ui.py:329`) frontend จัดรูปแบบที่เดียว (`frontend/lib/a2uiFormat.ts`): วันที่ พ.ศ., เงิน THB เป็น "บาท", การเปลี่ยนแปลงของค่า % เป็น "จุด", ลูกศร ▲/▼/▬ และสีตาม sentiment (good = `#216e4e` เขียว, bad = `#ae2e24` แดง, neutral = `#6b6e76` เทา)
- "AI คำนวณจาก N เอกสาร" แสดงเฉพาะแผงตัวเลข (metrics, table, chart) แผงรายการเอกสารและแผงความเสี่ยงไม่มี เพราะส่ง `sources=False` (`a2ui.py:417`, `a2ui.py:492`) ส่วน "ข้อมูล ณ …" แสดงทุกแผง (`A2uiSurface.tsx:174`)
- คลิกปุ่มในแผงส่ง `ui_action` ผ่าน `POST /agent/conversations/{id}/ui-actions` ข้อความฝั่งผู้ใช้และ title เป็นข้อความอ่านได้ ("อนุมัติเอกสาร N รายการที่เลือก") ปุ่มชื่อ "อนุมัติที่เลือก" / "ปฏิเสธที่เลือก"
- สถานะแผงเก็บที่ server ในตาราง `agent_surfaces` (active / answered / superseded) แผงที่มีปุ่มใหม่ทำให้แผงที่มีปุ่มเก่า superseded แผง metrics/chart/table ไม่ทำ แผงที่ถูกคลิกกลับมาใช้ได้ถ้า run ที่คลิกเริ่มจบโดยไม่มีการยืนยัน (ล้มเหลว, ถูกหยุด, reject, หมดเวลา) (`crud_agent_surface.py:13`)
- คำขอยืนยันที่ไม่มีคำตอบใน 300 วินาที หรือ run ถูกหยุด ได้สถานะ `expired` UI แสดง "คำขอยืนยันหมดเวลา … ไม่มีการเปลี่ยนแปลงใดๆ ขอให้ Agent ถามใหม่ได้" ยืนยันคำขอที่ไม่ pending ได้ 409
- บทสนทนาโหลดเป็นหน้าละ 50 ข้อความ มีปุ่ม "โหลดข้อความก่อนหน้า"
- root ของแผงเป็น layout boundary (`relative min-w-0 overflow-x-clip`, `A2uiSurface.tsx:171`)
- pdf.js worker มาจาก bundle ของแอป (`frontend/lib/pdf-worker.ts`)
- แผง v1 ในบทสนทนาเก่า (`catalogs/jobs/v1`) ไม่ถูกวาดแล้ว เหลือแค่ชิป `render_ui tool` ตามที่ออกแบบ (`frontend/lib/a2ui.ts:5`, `:397`)

## เตรียมก่อนทดสอบ

- [x] เปิด `http://localhost:3000` (nginx → API `/api/v1`) ด้วย Playwright headless profile ใหม่ ภาษา th-TH, เดสก์ท็อป 1440×1000 และมือถือ 360×800
- [x] ผู้ใช้ทดสอบ `uat-a2ui@example.com` (role `user`), Job `UAT A2UI 2026-10-31` (`37c33f02-c29a-4812-8179-12bb6954e335`), เอกสาร 9 ใบ (ใบแจ้งหนี้/ใบเสนอราคา/ใบเสร็จ 8 ใบ + สัญญา `Contract_V2_SRG-IT-2026-001.pdf`)
- [x] ตั้งเอกสาร 8 ใบกลับเป็น **Extraction Completed** ด้วย API ของแอป `PUT /api/v1/documents/{id}` `{"status":"extraction_completed","review_decision":null}` สัญญาคงเป็น reviewed
- [x] ตรวจ DB แบบอ่านอย่างเดียว: `docker compose exec -T db psql -U insightocr_user -d softnix_ocr -c "select surface_id,tool_name,status,answered_by_run_id from agent_surfaces where conversation_id='<conv>'"`

บทสนทนาหลักของรอบนี้: `d7dac20a-1138-4bc0-9f0d-66cd0dd2e0e7` ภาพหน้าจออยู่ที่ `/private/tmp/claude-501/-Volumes-Seagate-myapp-InsightOCRv2/a951485d-b519-44ab-b7cb-10447e108694/scratchpad/uat/shots2/` (ในตารางเขียนย่อเป็น `shots2/`) log อยู่ที่ `.../uat/logs2/`

## กรณีทดสอบ: รายการเอกสารและการกดปุ่ม

| # | ขั้นตอน | ผลที่คาดหวัง | ผล | หมายเหตุ / หลักฐาน |
|---|---|---|---|---|
| 1 | แท็บ **AI Agent** พิมพ์ "หาเอกสารที่ยังไม่อนุมัติ" | agent เรียก `show_documents` พร้อม actions แผงมีหัวข้อ, "เลือกทั้งหมด (0/N)", แต่ละแถวมี checkbox ชื่อไฟล์ ป้าย "รอตรวจ" หมายเหตุ (ถ้ามี) และ "เปิดดู" ปุ่ม "อนุมัติที่เลือก" / "ปฏิเสธที่เลือก" และ "ข้อมูล ณ …" ไม่มี "AI คำนวณจาก" ข้อความตอบสั้น ไม่ทวนรายการ | ⚠️ | แผง `jobs-3bfbd5eca495` 8 แถว "รอตรวจ" + "เปิดดู", "เลือกทั้งหมด (0/8)", "ข้อมูล ณ 1 พ.ย. 2569 07:30" ถูกต้อง แต่ agent ใส่ `note` เป็นชื่อไฟล์ซ้ำทุกแถว (เช่น `{"document_id":"b30eba00…","note":"1_0.png"}`) และข้อความตอบทวนชื่อไฟล์ 8 ไฟล์ พร้อมเขียนว่า "กดปุ่ม **approve** หรือ **reject**" ไม่ใช่ชื่อปุ่มจริง สาเหตุ: คำอธิบาย `show_documents` ไม่ห้ามซ้ำชื่อไฟล์ใน note และไม่ได้ต่อ `_SHOWN` ("do not restate") เหมือนแผงอื่น (`ui_tools.py:115-119`) — `shots2/01.png` |
| 2 | ดูชื่อไฟล์และสถานะในรายการ | ตรงกับเอกสารจริงใน Job ไม่มีเอกสารจาก Job อื่น | ✅ | 8 แถวตรงกับ `select filename from documents where job_id=… and status='extraction_completed'` ครบ 8 ชื่อ — `shots2/01.png` |
| 3 | กด "เปิดดู" ที่ `02_Tax_Invoice_INV-2026-0425.pdf` | เปิด Preview ของเอกสารนั้น PDF วาดขึ้น | ✅ | modal "Preview: 02_Tax_Invoice_INV-2026-0425.pdf" canvas 2 อัน ไม่มี "Failed to load PDF" worker `GET http://localhost:3000/_next/static/media/pdf.worker.min.2th4soq4xwzz7.mjs` 200 ไม่มี request ไป unpkg ไม่มี console error — `shots2/03.png` |
| 4 | ยังไม่เลือกเอกสาร ดูปุ่ม | ปุ่มทั้งสองกดไม่ได้ เลือกแล้วกดได้ | ✅ | DOM: "อนุมัติที่เลือก:disabled", "ปฏิเสธที่เลือก:disabled" หลังเลือก 2 ใบเป็น enabled — `shots2/01.png`, `shots2/05.png` |
| 5 | เลือก `Google-inv.png` + `Invoice_1.jpg` กด "อนุมัติที่เลือก" | `POST …/ui-actions` ได้ 202 bubble ผู้ใช้ "อนุมัติเอกสาร 2 รายการที่เลือก" ไม่มี JSON ข้อความเก็บเป็น kind `ui_action` ระหว่าง run ปุ่มกดไม่ได้ | ❌ | `POST /api/v1/agent/conversations/d7dac20a…/ui-actions` ได้ **500 Internal Server Error** UI ขึ้นกล่องแดง "Server error: 500" ไม่มี bubble ผู้ใช้ ไม่มี run ใหม่ แผงยัง active (DB) เกิดซ้ำทุกครั้ง (UI 2 ครั้ง, API 2 ครั้ง) สาเหตุ B1 ในสรุปผล — `shots2/05.png` |
| 6 | (เพราะข้อ 5 ใช้ไม่ได้ จึงพิมพ์ "อนุมัติเอกสาร Google-inv.png และ Invoice_1.jpg" แทน) ดูกล่องยืนยัน | กล่องยืนยัน **ครั้งเดียว** "อนุมัติเอกสารที่รอตรวจ 2 รายการ" มีชื่อไฟล์ 2 ใบ + สถานะไทย JSON ดิบอยู่ใต้ "Show arguments" | ✅ | กล่องเดียว "Confirmation Required / อนุมัติเอกสารที่รอตรวจ 2 รายการ / bulk_approve / เอกสาร 2 รายการ: Google-inv.png รอตรวจ, Invoice_1.jpg รอตรวจ" `doc_ids` อยู่ใต้ Show arguments — `shots2/06.png`, `shots2/06-args.png` |
| 7 | กด Confirm | เฉพาะ 2 ใบเปลี่ยนเป็น reviewed | ✅ | DB หลัง Confirm: Google-inv.png และ Invoice_1.jpg = reviewed/confirmed อีก 6 ใบยัง extraction_completed pending action `b32da81a…` = confirmed — `shots2/07.png` |
| 8 | ดูแผงเดิมหลังกดปุ่มในแผง | ขึ้น "ส่งคำสั่งแล้ว" ปุ่มกดไม่ได้ DB `agent_surfaces.status = answered` | ❌ | ทดสอบไม่ได้: คลิกปุ่มได้ 500 (B1) แผงจึงไม่เคยเป็น answered ทั้ง Job มี 0 แถวที่ answered |
| 9 | รีโหลดหน้า เปิดบทสนทนาเดิม | แผงที่ส่งแล้วยังขึ้น "ส่งคำสั่งแล้ว" | ❌ | ส่วน answered ทดสอบไม่ได้ (B1) หลังรีโหลดสถานะที่มีอยู่คงเดิม: แผงเก่ายังขึ้น "แผงนี้ไม่ใช่แผงล่าสุด สถานะเอกสารอาจไม่เป็นปัจจุบัน" และ "ข้อมูล ณ" เดิม |
| 10 | พิมพ์ "อนุมัติเอกสาร Q25100034-8.pdf" แล้วกด **Reject** | ไม่มีเอกสารเปลี่ยนสถานะ agent ตอบว่าไม่ได้ทำ | ✅ | pending `852d58be…` = rejected tool result `{"error": "User rejected action"}` Q25100034-8.pdf ยัง extraction_completed ข้อสังเกต: กล่องยืนยันของ `approve_document` เขียน "อนุมัติเอกสาร 1078db78-0155-…" เป็น UUID (`confirmations.py:37`) แต่รายการด้านล่างมีชื่อไฟล์ และหลัง Reject ขึ้นกล่องแดง "approve_document: User rejected action" (ดู B3) — `shots2/10-confirm.png`, `shots2/10.png` |
| 11 | เลือก 2 ใบ (`1_0.png`, `567_Generated_Image.png`) กด "ปฏิเสธที่เลือก" | กล่องยืนยันครั้งเดียวสำหรับทั้ง 2 ใบ | ❌ | กดปุ่มได้ "Server error: 500" (B1) ในแผงใหม่ `jobs-8544d727614b` — `shots2/11-click-reject.png` ทางพิมพ์ "ปฏิเสธเอกสาร 1_0.png และ 567_Generated_Image.png" ผ่าน: กล่องเดียว "ปฏิเสธเอกสารที่รอตรวจ 2 รายการ" ชื่อไฟล์ครบ กด Reject แล้วไม่มีอะไรเปลี่ยน — `shots2/11.png` |
| 12 | ขอรายการใหม่ ("ขอรายการเอกสารที่ยังไม่อนุมัติอีกครั้ง") แล้วดูแผงเก่า | แผงเก่าปุ่มกดไม่ได้ ขึ้น "แผงนี้ไม่ใช่แผงล่าสุด สถานะเอกสารอาจไม่เป็นปัจจุบัน" DB = superseded | ✅ | แผงใหม่ `jobs-a76d2909139d` active แผงเก่า `jobs-3bfbd5eca495` = superseded ใน DB ปุ่ม disabled และขึ้นข้อความนั้น — `shots2/12.png` |
| 13 | **ตรึงรายการ:** บทสนทนาใหม่ พิมพ์ "อนุมัติเอกสารที่รอตรวจทั้งหมด" ระหว่างกล่องยืนยันเปิด ทำให้เอกสารอื่นกลายเป็นรอตรวจ แล้วกด Confirm | อนุมัติเฉพาะเอกสารในกล่อง เอกสารที่เพิ่งรอตรวจไม่ถูกอนุมัติ | ✅ | กล่อง "อนุมัติเอกสารที่รอตรวจ 6 รายการ" ระหว่างเปิดตั้ง `Google-inv.png` กลับเป็น extraction_completed ด้วย API (แทนการอัปโหลดใหม่) Confirm แล้ว 6 ใบเป็น reviewed, Google-inv.png ยัง extraction_completed conv `fd3b52f8…`, pending `795e8d6e…` agent ส่ง `doc_ids` ครบ 6 ตัวเอง จึงยังไม่ได้ทดสอบ bulk_approve แบบไม่ส่ง doc_ids — `shots2/13-confirm.png`, `shots2/13.png` |
| 14 | ไม่มีเอกสารรอตรวจ พิมพ์ "อนุมัติเอกสารที่รอตรวจทั้งหมด" | ไม่มีกล่องยืนยัน agent ตอบว่าไม่มีเอกสารให้อนุมัติ | ✅ | (อนุมัติ Google-inv.png ผ่าน `POST /documents/{id}/decision` ก่อน) `list_documents` ได้ count 0 ไม่มี pending action ใน conv `aebbf884…` agent ตอบ "ขณะนี้ไม่มีเอกสารที่รอตรวจ" — `shots2/14.png` |

## กรณีทดสอบ: สถานะแผง การยืนยัน การหยุด และ layout (ใหม่ใน v2)

| # | ขั้นตอน | ผลที่คาดหวัง | ผล | หมายเหตุ / หลักฐาน |
|---|---|---|---|---|
| N1 | มีรายการเอกสารที่มีปุ่ม แล้วถามตัวเลข/กราฟ ("สรุปยอดรวมของเอกสารใน job นี้ เทียบกับเดือนก่อน") | แผง chart/metrics ใหม่ไม่ทำให้รายการ superseded ปุ่มรายการยังใช้ได้และคลิกแล้วทำงาน | ⚠️ | กฎ superseded ถูก: หลัง `show_chart` `jobs-092557eb2927` และ `show_metrics` `jobs-225cbe1c3aa6` รายการ `jobs-a76d2909139d` ยัง active ใน DB ไม่มีโน้ต เลือก Q25100034-8.pdf แล้วปุ่มเป็น enabled แต่คลิกได้ 500 (B1) — `shots2/N1-list-after-metrics.png` |
| N2 | ส่งคลิกไปยังแผงเก่าที่ถูก superseded ตรงๆ (`POST …/ui-actions` surface `jobs-3bfbd5eca495`) | ถูกปฏิเสธ 409 ไม่มี run ใหม่ ใน UI ปุ่มแผงเก่ากดไม่ได้ | ✅ | `409 {"detail":"แผงนี้ไม่ใช่แผงล่าสุด ใช้ปุ่มในแผงล่าสุดแทน"}` surface ที่ไม่มีจริงได้ `404 "ไม่พบแผงนี้ในบทสนทนานี้"` ปุ่มแผงเก่า disabled — `shots2/12.png`, `logs2/api.log` |
| N3 | คลิกปุ่มในแผง แล้วกด Reject ในกล่องยืนยัน | แผงกลับเป็น active ปุ่มใช้ได้อีก โน้ต "ส่งคำสั่งแล้ว" หายไป | ❌ | ทดสอบไม่ได้: คลิกได้ 500 (B1) จึงไม่มี run ที่ผูกกับแผง ทางพิมพ์ Reject ทำงานถูก (ข้อ 10) แต่ไม่เกี่ยวกับแผง |
| N4 | ระหว่างกล่องยืนยันรออยู่ ("อนุมัติเอกสาร starbuck.pdf") กด "หยุด" | กล่องเปลี่ยนเป็น "คำขอยืนยันหมดเวลา … ขอให้ Agent ถามใหม่ได้" pending = expired run = cancelled ยืนยันซ้ำได้ 409 แผงที่คลิกกลับมาใช้ได้ | ⚠️ | UI: "คำขอยืนยันหมดเวลา / อนุมัติเอกสาร 4dd62db4-f192-… / ไม่มีการเปลี่ยนแปลงใดๆ ขอให้ Agent ถามใหม่ได้" pending `19274c1c…` = expired, run `6f2ae067…` = cancelled "Stopped by the user" `POST /agent/confirm/19274c1c…` ได้ `409 "คำขอยืนยันนี้หมดเวลาแล้ว ไม่มีการเปลี่ยนแปลงใดๆ ขอให้ Agent ถามใหม่ได้"` starbuck.pdf ไม่เปลี่ยน ส่วนแผงกลับมาใช้ได้ทดสอบไม่ได้ (B1) ข้อสังเกต: ชิป `approve_document` ค้างเป็นวงหมุนถาวรหลังหยุด และ run ถัดไปขออนุมัติ starbuck.pdf ซ้ำ (B2) — `shots2/N4-confirm.png`, `shots2/N4-stopped.png` |
| N5 | ปล่อยกล่องยืนยันไว้เกิน 300 วินาที ("อนุมัติเอกสาร 567_Generated_Image.png") | pending = expired หลัง ~300 วิ UI แสดงโน้ตหมดเวลา ไม่มีเอกสารเปลี่ยน ยืนยันได้ 409 แผงที่คลิกกลับมาใช้ได้ | ⚠️ | pending `b9855679…` สร้าง 00:51:57Z หมดเวลา 00:57:01Z (304 วิ) UI เปลี่ยนเป็นโน้ต "คำขอยืนยันหมดเวลา" กล่อง Confirm หายไป `POST /agent/confirm/b9855679…` ได้ 409 ข้อความเดียวกับ N4 แต่ (1) กล่องยืนยันนี้เป็นของ **starbuck.pdf** ไม่ใช่ 567_Generated_Image.png เพราะ agent ทำคำขอที่ถูกหยุดใน N4 ซ้ำ (B2) (2) run ถูกบันทึกเป็น failed และ UI ขึ้นกล่องแดงภาษาอังกฤษ "approve_document: The confirmation request expired: the user did not answer in time, so nothing was done." ทั้งที่ agent ตอบต่อจนจบ (B3) ส่วนแผงกลับมาใช้ได้ทดสอบไม่ได้ (B1) — `shots2/N5-confirm.png`, `shots2/N5-expired.png` |
| N6 | หลังคลิกปุ่มในแผง ดูรายการสนทนา | title เป็นข้อความอ่านได้ เช่น "อนุมัติเอกสาร 2 รายการที่เลือก" ไม่มี JSON | ❌ | ทดสอบไม่ได้: ไม่มีคลิกที่ผ่าน (B1) สำหรับข้อความพิมพ์ title อ่านได้และตามข้อความผู้ใช้ล่าสุด (`crud_agent_message.py:38`) เช่น "อนุมัติเอกสาร 567_Generated_Image.png" แต่รายการสนทนาไม่อัปเดตจนกว่าจะรีโหลด บทสนทนาใหม่ขึ้น "New conversation" (รายการโหลดตอน mount เท่านั้น `AgentPanel.tsx:159`) — `shots2/N6-convlist.png`, `shots2/N6-convlist-reload.png` |
| N7 | บทสนทนาที่มีมากกว่า 50 ข้อความ เปิดใหม่ แล้วกด "โหลดข้อความก่อนหน้า" | หน้าแรกได้ 50 ข้อความล่าสุด กดแล้วได้ข้อความเก่ากว่าต่อด้านบน แผงในหน้าเก่าวาดพร้อมสถานะถูก ปุ่มหายเมื่อหมด | ✅ | ไม่ได้ seed: บทสนทนาหลักมี 94 ข้อความจากการแชตจริง เปิดใหม่เห็น 7 แผงและปุ่ม "โหลดข้อความก่อนหน้า" กดแล้ว `GET …/conversations/d7dac20a…?before=af7d2c33-…` ได้แผงเพิ่มเป็น 11 แผง แผงแรก `jobs-3bfbd5eca495` ขึ้น superseded ถูก `jobs-a76d2909139d` active ปุ่มหายไปเมื่อ `has_more=false` — `shots2/P1-before-older.png`, `shots2/P1-after-older.png` |
| N8 | viewport 360px เปิดบทสนทนาที่มีทุกชนิดแผง (รวมตารางคอลัมน์ change) โหลดข้อความเก่าให้ครบ | หน้าไม่เลื่อนแนวนอน ตารางเลื่อนในกรอบ | ✅ | `html.scrollWidth/clientWidth` = 360/360 ทั้งก่อนและหลังโหลดครบ 11 แผง `window.scrollTo(500,…)` แล้ว `scrollX` = 0 ทุกแผงกว้าง 286 ขอบขวา 323 ตาราง 1242/258, 828/258 เลื่อนในกรอบ (`overflow-x:auto`) — `shots2/A10-*.png` |
| N9 | เปิด PDF ของเอกสารใน Job (ข้อ 3 และ A9) ดู network และ console | worker โหลดจาก `localhost:3000` ไม่มี CORS error PDF วาดขึ้น | ✅ | 2 ครั้ง: `RESP 200 http://localhost:3000/_next/static/media/pdf.worker.min.2th4soq4xwzz7.mjs` ไม่มี request ไป unpkg ไม่มี requestfailed ไม่มี console error PDF วาดขึ้นทั้ง 2 ไฟล์ — `shots2/03.png`, `shots2/A9.png` |

## กรณีทดสอบ: แผงวิเคราะห์ (ตัวเลข ตาราง กราฟ ความเสี่ยง)

| # | ขั้นตอน | ผลที่คาดหวัง | ผล | หมายเหตุ / หลักฐาน |
|---|---|---|---|---|
| A1 | ถาม "สรุปยอดรวมของเอกสารใน job นี้ เทียบกับเดือนก่อน" | `show_metrics` การ์ดตัวเลขเป็นบาท แต่ละใบที่มี previous มีลูกศรจาก backend +/− "(แย่ลง)/(ดีขึ้น)" ตาม higher_is "เทียบ <เดือน>: …" "AI คำนวณจาก N เอกสาร" "ข้อมูล ณ …" ข้อความตอบสั้น | ⚠️ | การ์ดเดียว "ยอดรวม ก.ย. 2569 321,000.00 บาท ▲ +500% +267,500.00 บาท เทียบ เม.ย. 2569 (เดือนที่มีเอกสารก่อนหน้า): 53,500.00 บาท" สีเทา (agent ตั้ง `higher_is: neutral` จึงไม่มีคำ แย่ลง/ดีขึ้น) "AI คำนวณจาก 2 เอกสาร" "ข้อมูล ณ 1 พ.ย. 2569 07:36" เทียบ ก.ย. กับ เม.ย. ไม่ใช่เดือนก่อนจริง (agent บอกไว้ในข้อความ) และข้อความตอบมีตารางรายเดือนซ้ำกับกราฟ `show_chart` ที่แสดงเพิ่ม — `shots2/A1.png`, `shots2/A1-chart.png` |
| A1b | ถาม "แสดงการ์ดตัวเลขค่าใช้จ่าย (ค่าใช้จ่ายเพิ่มถือว่าแย่): ยอด ก.พ. 2569 เทียบ ม.ค. 2569, ยอด เม.ย. 2569 เทียบ มี.ค. 2569 และสัดส่วนภาษีต่อยอดรวม (%) ของ ก.ย. 2569 เทียบ ก.พ. 2569" | ลดลง = ▼ เขียว "(ดีขึ้น)" เพิ่มขึ้น = ▲ แดง "(แย่ลง)" ค่า % ใช้ "จุด" | ✅ | "▼ -87% (ดีขึ้น) -2,323,622.65 บาท" สี rgb(33,110,78); "▲ +409.5% (แย่ลง) +43,000.00 บาท" สี rgb(174,46,36); "▬ 0 จุด" สี rgb(107,110,118) ข้อความ sr-only "ลดลง/เพิ่มขึ้น/คงที่" ตรงทิศ — `shots2/A1b-arrows.png` |
| A2 | ตรวจตัวเลขเทียบข้อมูลที่สกัดได้ | ตรงกับผลรวมจาก extracted_data รูปแบบ 1,234.56 บาท | ✅ | ม.ค. 2,671,265.65 = 2,671,255 (Q25100034-8) + 10.65 (Google-inv); ก.พ. 347,643 (02_Tax, ตรงกับ TOTAL ในตัว PDF); มี.ค. 10,500; เม.ย. 53,500; ก.ย. 321,000 ตรงทุกค่า คำนวณด้วย `get_document_detail` ทั้ง 8 ใบ ข้อสังเกต: Google-inv 10.65 ถูกนับเป็นบาท |
| A3 | ถาม "เปรียบเทียบยอดตามผู้ขายเป็นตาราง พร้อมสัดส่วนและวันครบกำหนด" | `show_table` คอลัมน์ตัวเลขชิดขวา สัดส่วนเป็น % วันที่ พ.ศ. คอลัมน์เอกสารมี "เปิดดู" ตารางเลื่อนในกรอบ | ⚠️ | ยอด/สัดส่วนชิดขวา ("53,500.00 บาท", "1.6%") คอลัมน์เอกสารมีชื่อไฟล์ + "เปิดดู" กรอบเลื่อน 1242/1082 `overflow:auto` "AI คำนวณจาก 7 เอกสาร" แต่วันครบกำหนดเป็นคอลัมน์ `kind: text` ค่า "2026-03-20 (เครดิต 30 วัน…)" เป็น ค.ศ. เพราะ agent รวมหมายเหตุไว้ในช่องวันที่ (ส่วนใหญ่ไม่มีวันครบกำหนด) — `shots2/A3.png` |
| A3b | ถาม "ทำตาราง: อัตราภาษีจริง … เทียบกับอัตรามาตรฐาน 7% พร้อมคอลัมน์ผลต่าง (อัตราสูงกว่าถือว่าแย่)" | คอลัมน์ `change` คำนวณโดย backend ค่า % แสดงเป็น "จุด" ลูกศร/สีตรงกับตัวเลข | ⚠️ | agent ใช้ `{kind:"change", of:"actual_rate", vs:"standard_rate", higher_is:"bad"}` ถูก 4 แถว "▬ คงที่ 0 จุด" ถูก แต่ 2 แถว (7.0352 vs 7, 7.0022 vs 7) ขึ้น "**▲ +0 จุด (แย่ลง)**" สีแดง ลูกศรขึ้นแต่ตัวเลขเป็น 0 สาเหตุ: `PERCENT` ปัดเหลือทศนิยม 1 ตำแหน่ง (`a2uiFormat.ts:9`) แล้วใช้กับ delta จุด (`a2uiFormat.ts:72`) ขณะที่ทิศคำนวณจาก delta 6 ตำแหน่ง (`a2ui.py:335`) — `shots2/A3b-change.png` |
| A4 | ถาม "ทำกราฟแท่งยอดรวมตามผู้ขาย เทียบไตรมาสนี้กับไตรมาสก่อน" | กราฟแท่งแนวนอน legend 2 ชุด ตัวเลขท้ายแท่งเป็นบาท "ดูข้อมูลเป็นตาราง" ครบ tooltip | ✅ | legend "Q3/2569 (ก.ค.-ก.ย.)" / "Q2/2569 (เม.ย.-มิ.ย.)" ตัวเลขท้ายแท่ง "321,000.00 บาท" ฯลฯ ตารางสำรองครบ 4 ค่า SVG `<title>` "Softnix Technology Co., Ltd. · Q3/2569 (ก.ค.-ก.ย.): 321,000.00 บาท" ข้อสังเกต: "ไตรมาสนี้" agent ตีเป็น Q3 ทั้งที่วันนี้อยู่ Q4 2569 — `shots2/A4.png` |
| A5 | ถาม "แสดงแนวโน้มยอดรายเดือนเป็นกราฟเส้น" | กราฟเส้น แกน Y ย่อ (1M) มีหน่วย "บาท" แกน X เป็นเดือนไทย มีจุด ไม่มี legend มีตารางสำรอง | ✅ | แกน Y "0 / 1M / 2M / 3M" หัวแกน "บาท" แกน X "ม.ค. 69 … ก.ย. 69" ครบ 5 จุด ไม่มี legend มี "ดูข้อมูลเป็นตาราง" "AI คำนวณจาก 6 เอกสาร" ข้อสังเกต: เดือนที่ไม่มีข้อมูล (พ.ค.-ส.ค.) ไม่มีช่อง จุด เม.ย. กับ ก.ย. วางห่างเท่าเดือนติดกัน — `shots2/A5.png` |
| A6 | ถาม "วิเคราะห์ความเสี่ยงของสัญญา Contract_V2_SRG-IT-2026-001.pdf" | `show_risks` จำนวนตามระดับ เรียงจากรุนแรง ป้ายระดับ (ไอคอน+ข้อความ+สี) คำอธิบาย ข้อความอ้างอิง ข้อเสนอแนะ ครอบคลุมการชำระเงิน ค่าปรับ การบอกเลิก ความรับผิด การต่ออายุอัตโนมัติ และข้อที่ขาดหาย | ⚠️ | "วิกฤต 0 / สูง 4 / ปานกลาง 4 / ต่ำ 0" เรียงสูงก่อนปานกลาง ป้ายมีไอคอน+ข้อความ+สีพื้น (สูง rgb(254,222,200)) ครอบคลุมสถานะร่าง, บอกเลิก, ค่าปรับ 50%, เพดานความรับผิด, ต่ออายุอัตโนมัติ, ขึ้นราคา 5%, SLA credit, ดอกเบี้ยผิดนัด 15% แต่ไม่มีรายการเรื่องข้อที่ขาดหาย แผงมีชื่อไฟล์ + "เปิดดู" "ข้อมูล ณ" ไม่มี "AI คำนวณจาก" (ตามที่ออกแบบ) — `shots2/A6.png` |
| A7 | ดูข้อความอ้างอิงใน A6 | คำพูดในเครื่องหมายคำพูด ✓ "พบในเอกสาร" ต่อรายการ และสรุปผลตรวจ | ✅ | 8/8 รายการ "พบในเอกสาร" สรุป "ข้อความอ้างอิงตรวจพบในเอกสารครบทั้ง 8 รายการ" tool result `quotes_found: 8, quotes_total: 8` — `shots2/A6.png` |
| A8 | สั่งให้ agent แสดงแผงใหม่ที่มีข้อความอ้างอิงแก้ไข ("…within 60 (sixty) calendar days…") | รายการนั้นขึ้น ⚠ "ไม่พบข้อความนี้ในเอกสาร ควรตรวจสอบ" สรุประบุชื่อรายการ ข้อความตอบอ้างรายการถูก | ✅ | แผง `jobs-db5e63ff1b99`: รายการ 2 "ไม่พบข้อความนี้ในเอกสาร ควรตรวจสอบ" สรุป "ข้อความอ้างอิงตรวจพบในเอกสาร 1 จาก 2 รายการ · ไม่พบ: QA Test 2: …" tool result แยกต่อรายการ `r2 quote: not_found` ข้อความตอบ agent ระบุ QA Test 2 ถูกรายการ (ต่างจากรอบก่อนที่ระบุผิด) ข้อสังเกต: title ที่ agent เขียนมีคำสะกดผิด ("ทสสอบ", "จรง") — `shots2/A8.png` |
| A9 | กด "เปิดดู" ในแผงความเสี่ยง | เปิด Preview ของสัญญาถูกฉบับ PDF วาดขึ้น | ✅ | modal "ตรวจเอกสาร Contract_V2_SRG-IT-2026-001.pdf" "Page 1 of 14" canvas วาดขึ้น — `shots2/A9.png` |
| A10 | viewport 360px ดูแผงจาก A1b, A3b, A4, A6 | การ์ดขึ้นบรรทัดใหม่ ตารางเลื่อนในกรอบ กราฟแท่งเห็นตัวเลข หน้าไม่เลื่อนแนวนอน | ✅ | การ์ด A1b top -9782/-9682/-9582 (ใบละแถว) ตาราง A3b 828/258 เลื่อนในกรอบ กราฟแท่งชื่อผู้ขายตัด "…" ตัวเลข "321,000.00 บาท" อยู่ในกรอบ หน้า 360/360 — `shots2/A10-92574942335d.png`, `shots2/A10-b0a075158df5.png`, `shots2/A10-c1834c23f5d9.png`, `shots2/A10-9eb9d1572eac.png` |
| A11 | emulate `prefers-color-scheme: dark` เปิดแผง A4 และ A6 | แอปยังเป็นธีมสว่าง แผงอ่านชัด สีป้าย/กราฟไม่เพี้ยน | ✅ | matchMedia dark = true, body และแผง rgb(255,255,255) แท่ง rgb(24,104,219)/rgb(235,104,52) ป้าย วิกฤต rgb(255,213,210)/rgb(147,37,29) สูง rgb(254,222,200)/rgb(158,76,0) — `shots2/A11-c1834c23f5d9.png`, `shots2/A11-9eb9d1572eac.png` |

ข้อจำกัดที่รู้แล้ว: การตรวจข้อความอ้างอิงค้นทั้งเอกสาร ไม่ได้ตรวจเลขหน้า ตัวเลขดิบมาจากการคำนวณของ agent (ระบบตรวจชนิดค่าและ document_id และคำนวณเฉพาะการเปลี่ยนแปลง)

## วัดผลกับโมเดลจริง

นับจาก `agent_messages` (role=tool, `show_*`) ของ Job UAT ตั้งแต่ 2026-11-01 ทั้งหมด 16 การเรียก

| คำสั่งตัวอย่าง | ครั้งที่ควรเรียก show_* / เรียกจริง | สำเร็จครั้งแรก | หมายเหตุ |
|---|---|---|---|
| หาเอกสารที่ยังไม่อนุมัติ (และ "ขอรายการ…อีกครั้ง") | 5 / 5 `show_documents` | 5 / 5 | ทุกครั้งมี actions approve+reject ครั้งแรกใส่ note = ชื่อไฟล์ |
| แสดงใบเสร็จทั้งหมดใน job นี้ | 1 / 1 `show_table` | 0 / 1 | ผิด validation 1 ครั้งแล้วแก้เองผ่าน (ข้อความด้านล่าง) |
| เอกสารไหนมีปัญหาบ้าง | 1 / 0 | – | ตอบเป็นข้อความ ทั้งที่คำอธิบาย `show_documents` ยกตัวอย่าง "documents … with problems" (`ui_tools.py:116`) |
| เอกสารที่ความมั่นใจต่ำกว่า 80% | ไม่นับ | – | `extraction_confidence` เป็น null ทุกใบ agent ตอบว่ากรองไม่ได้ ถือว่าถูก |
| A1, A1b, A3, A3b, A4, A5, A6, A8 | 8 / 8 (`show_metrics` 2, `show_chart` 2+1 ที่ agent แถมใน A1, `show_table` 2, `show_risks` 2) | 8 / 8 (9 / 9 การเรียก) | ไม่มี validation error |
| อนุมัติ/ปฏิเสธ ตามชื่อไฟล์, อนุมัติทั้งหมด (ข้อ 6, 10, 11, 13, 14, N4, N5) | ไม่ควรเรียก / ไม่เรียก | – | ข้อ 13 ส่ง doc_ids ครบ 6 ตัว ข้อ 14 ไม่สร้างกล่องยืนยัน N5 ขอ starbuck.pdf แทน 567 (B2) |
| คลิกปุ่มในแผง | – | – | ไม่มีคลิกถึง agent เลย ทุกคลิกได้ 500 (B1) |

Validation error ที่เจอ (ตามตัวอักษร):

```
show_table was not shown: these are not document ids: ['1_0.png', '567_Generated_Image.png', '02_Tax_Invoice_INV-2026-0425.pdf', 'Google-inv.png', 'Invoice_1.jpg']. Use the "id" values from list_documents and call again; nothing was done.
```

สรุป: show_* ถูกเรียกเมื่อควรเรียก 14 / 15 คำสั่ง สำเร็จครั้งแรก 13 / 14 คำสั่ง (15 / 16 การเรียก) ทำงานหลังกดปุ่มในแผง 0 ครั้ง เพราะ B1

## ถ้าเจอปัญหา

- agent ตอบเป็นข้อความธรรมดาแทนแผง: จดคำสั่งและเวลา แล้วดู tool calls ของ run นั้นใน `agent_messages`
- แผงไม่ขึ้นหรือหน้าแตก: เปิด DevTools (Console) แล้วจับภาพ error
- ปุ่มในแผงขึ้น "Server error: 500": ดู B1 ด้านล่าง
- ข้อมูลเทคนิคเพิ่มเติม: `QUICKWIN-TEST.md` หัวข้อ A2UI

---

# สรุปผล UAT รอบ 2026-11-01 (Playwright headless, เดสก์ท็อป 1440px และ 360px)

- สภาพแวดล้อม: `main` @ `5515c01`, migration `0031_agent_ui_actions`, `http://localhost:3000`, ผู้ใช้ `uat-a2ui@example.com`, Job `37c33f02-c29a-4812-8179-12bb6954e335`
- ผลรวม 36 กรณี: **✅ 22, ⚠️ 8, ❌ 6**
  - ❌: 5, 8, 9, 11, N3, N6 (ทั้งหมดมาจาก B1)
  - ⚠️: 1, N1, N4, N5, A1, A3, A3b, A6

ปัญหาที่พบ เรียงตามความรุนแรง (หลักฐานและสาเหตุเท่านั้น ยังไม่ได้แก้):

1. **B1 (วิกฤต) ทุกคลิกปุ่มในแผงได้ 500** `POST /agent/conversations/{id}/ui-actions` ตอบ `500 Internal Server Error` UI ขึ้น "Server error: 500" ฟีเจอร์คลิกแบบ structured, สถานะ answered, การเปิดแผงกลับ และ title จากคลิก ใช้ไม่ได้ทั้งหมด จำลองใน container แล้วได้
   `sqlalchemy.exc.IntegrityError: (psycopg2.errors.ForeignKeyViolation) insert or update on table "agent_surfaces" violates foreign key constraint "agent_surfaces_answered_by_run_id_fkey" DETAIL: Key (answered_by_run_id)=(…) is not present in table "agent_runs".`
   สาเหตุ: endpoint สร้าง `run_id = uuid4()` (`backend/app/api/v1/endpoints/agent.py:436`) แล้วเรียก `ui_actions.accept` (`agent.py:438`) ซึ่ง `agent_surface.claim` สั่ง `UPDATE agent_surfaces SET answered_by_run_id=<run_id>` ทันที (`backend/app/crud/crud_agent_surface.py:79`, เรียกจาก `backend/app/agent/ui_actions.py:78`) ก่อนที่ `_start_run` จะสร้างแถว `agent_runs` (`agent.py:444`) FK `answered_by_run_id → agent_runs.id` ไม่ได้เป็น DEFERRABLE (`backend/app/models/agent_surface.py:40`, `backend/alembic/versions/0031_agent_ui_actions.py:233`) จึงล้มทุกครั้ง เข้ามาใน commit `d6f5b3b`
2. **B2 (สูง) หลังกด "หยุด" ระหว่างรอยืนยัน คำขอถัดไปทำคำขอเดิมซ้ำกับเอกสารผิดใบ** ผู้ใช้สั่ง "อนุมัติเอกสาร 567_Generated_Image.png" แต่ agent เรียก `approve_document` กับ `starbuck.pdf` (`4dd62db4…`, คำขอที่ถูกหยุดใน N4) กล่องยืนยันขึ้น starbuck.pdf ผู้ใช้ที่กด Confirm โดยไม่อ่านจะอนุมัติผิดใบ สาเหตุ (อนุมาน): `load_history` ทิ้ง tool call ที่ไม่มีผลลัพธ์ทั้งชุดโดยไม่บอกโมเดลว่าถูกหยุด/หมดเวลา (`backend/app/agent/context.py:244-246`) โมเดลจึงเห็นคำขอ "อนุมัติเอกสาร starbuck.pdf" ที่ยังไม่มีผล และการหยุดไม่บันทึก tool result ใดๆ — `shots2/N5-confirm.png`
3. **B3 (กลาง) Reject หรือหมดเวลา ทำให้ run เป็น failed และขึ้นกล่องแดงภาษาอังกฤษ** เช่น "approve_document: User rejected action" และ "approve_document: The confirmation request expired: …" ทั้งที่ agent ตอบผู้ใช้จนจบ สาเหตุ: `_aggregate_success` นับ tool result ที่มี `error` เป็น failed step (`backend/app/agent/loop.py:390-423`) → `run.status = "failed"` (`backend/app/tasks/agent_tasks.py:154-156`) → `setError(run.error)` (`frontend/components/agent/AgentPanel.tsx:211-212`) และ metrics ของ agent จะนับ run เหล่านี้เป็นล้มเหลว — `shots2/10.png`, `shots2/N5-expired.png`
4. **B4 (กลาง-ต่ำ) การเปลี่ยนแปลงของค่า % ที่น้อยกว่า 0.05 จุด แสดง "▲ +0 จุด (แย่ลง)" สีแดง** ทิศจาก delta 6 ตำแหน่ง (`a2ui.py:335`) แต่ตัวเลขปัดด้วย `PERCENT` ทศนิยม 1 ตำแหน่ง (`frontend/lib/a2uiFormat.ts:9`, `:72`) — `shots2/A3b-change.png`
5. ต่ำ: รายการสนทนาไม่อัปเดต title หลังส่งข้อความ (บทสนทนาใหม่เป็น "New conversation" จนกว่าจะรีโหลด) เพราะโหลดตอน mount เท่านั้น (`AgentPanel.tsx:159`)
6. ต่ำ: กล่องยืนยันของ `approve_document` เขียน UUID ("อนุมัติเอกสาร 1078db78-…") (`backend/app/agent/confirmations.py:37`) ทั้งในกล่อง pending และโน้ตหมดเวลา
7. ต่ำ: ชิป tool call ที่ถูกหยุด (`approve_document`) หมุนค้างตลอดไป แม้รีโหลด — `shots2/N4-stopped.png`
8. ต่ำ (พฤติกรรมโมเดล): `show_documents` ใส่ note ซ้ำชื่อไฟล์และข้อความตอบทวนรายการ (`ui_tools.py:115-119` ไม่มีคำสั่ง `_SHOWN`), "เอกสารไหนมีปัญหาบ้าง" ไม่เรียก `show_documents`, A3 ใส่วันครบกำหนดเป็นข้อความ ค.ศ., A1 เลือก `higher_is: neutral`

ทดสอบไม่ได้หรือไม่ครบ:

- ทุกอย่างที่ต้องคลิกปุ่มในแผงสำเร็จ (B1): bubble ผู้ใช้จากคลิก, ข้อความ kind `ui_action`, ปุ่มกดไม่ได้ระหว่าง run ของคลิก, "ส่งคำสั่งแล้ว" ก่อนและหลังรีโหลด, แผงเปิดกลับเมื่อ reject / หยุด / หมดเวลา / run ล้มเหลว, title จากคลิก, 409 "แผงนี้ส่งคำสั่งไปแล้ว" ข้อ 6, 7, 10, 11 ทดสอบผ่านทางพิมพ์คำสั่งแทน
- bulk_approve แบบไม่ส่ง doc_ids (ข้อ 13 agent ส่งเอง)
- tooltip ด้วยเมาส์จริง (headless ตรวจได้เฉพาะ SVG `<title>`)
- เกณฑ์ความมั่นใจ 80% (ไม่มีค่า confidence ในเอกสาร)
- ข้อ 13 ใช้การตั้งสถานะผ่าน API แทนการอัปโหลดเอกสารใหม่

ข้อมูลที่สร้างหรือเปลี่ยนในรอบนี้ (คงไว้ทั้งหมด):

- บทสนทนา: `d7dac20a-1138-4bc0-9f0d-66cd0dd2e0e7` (หลัก, 109 ข้อความ), `fd3b52f8-bc54-4990-9c98-7bdc0e53805c`, `aebbf884-3b0e-4845-a084-cd7d76543d52`, `b7c3be0c-4c94-481f-b8b8-c85bcaf9e573`, `40cc19de-eede-411b-ae83-210e140365fe`, `b732b417-b6f2-4394-9868-b64674627e0d`, `5e22d4b4-aa79-4582-925f-d27543ab1c4a`, `d07a3e40-5623-436a-8d6d-412711e66c85`, `eeb72c5a-e5bc-4edd-892b-437090a9908e`
- แผง (`agent_surfaces`): `jobs-3bfbd5eca495` (superseded), `jobs-a76d2909139d`, `jobs-092557eb2927`, `jobs-225cbe1c3aa6`, `jobs-92574942335d`, `jobs-00f2f54cd87b`, `jobs-b0a075158df5`, `jobs-c1834c23f5d9`, `jobs-c707382d3c40`, `jobs-9eb9d1572eac`, `jobs-db5e63ff1b99`, `jobs-b7de36d1d08b`, `jobs-8f4f38dc1142`, `jobs-8544d727614b`, `jobs-810d07cfedc1` (active)
- คำขอยืนยัน: `b32da81a-b53c-495d-a81d-d02f58539045` confirmed, `852d58be-c355-483f-bfa4-dc3e43089790` rejected, `1cdf8ab1-0110-4c1a-93e0-a6c8cf19af5a` rejected, `19274c1c-697a-4039-8ea3-ad7db7713bb2` expired (หยุด), `b9855679-568d-436f-a290-ad2d9bdda00b` expired (300 วิ), `795e8d6e-7ed8-48f7-a483-804b9a3690b3` confirmed
- สถานะเอกสาร: จบรอบด้วยเอกสาร 8 ใบเป็น extraction_completed (`review_decision` null) และสัญญาเป็น reviewed ระหว่างรอบอนุมัติผ่าน agent และผ่าน `POST /documents/{id}/decision` (Google-inv.png) แล้วตั้งกลับด้วย `PUT /documents/{id}`
- ไม่ได้ insert ข้อมูลใดลง DB โดยตรง (ข้อ N7 ใช้บทสนทนาจริง 94 ข้อความ)

---

# ผลรอบ 2: 2026-11-01 (round 2) หลังรอบแก้ UAT

- สภาพแวดล้อม: `main` @ `ad33512` (container สร้างใหม่ 09:15 +07), `http://localhost:3000`, ผู้ใช้ `uat-a2ui@example.com`, Job `37c33f02-c29a-4812-8179-12bb6954e335`, Playwright headless profile ใหม่ (`chrome-profile3`) 1440×1000 และ 360×800
- ภาพหน้าจอ: `/private/tmp/claude-501/-Volumes-Seagate-myapp-InsightOCRv2/a951485d-b519-44ab-b7cb-10447e108694/scratchpad/uat/shots3/` (ในตารางย่อเป็น `shots3/`) log: `.../uat/logs3/` (`driver.log`, `api.log`)
- คลิกทุกครั้งในรอบนี้เป็นคลิกจริงใน UI (`page.click`) ไม่ใช่ API ยกเว้นการทดสอบ 409 ที่ส่งตรงด้วย `click_api.py`
- ตรวจ DB แบบอ่านอย่างเดียวผ่าน `q` (psql) ไม่มีการเขียน DB ตรง

## ผลรอบ 2 รายกรณี

| # | ผลรอบ 1 | ผลรอบ 2 | หมายเหตุ / หลักฐานรอบ 2 |
|---|---|---|---|
| 1 | ⚠️ | ⚠️ | รัน 3 ครั้งในบทสนทนาใหม่ทุกครั้ง รัน 1 (`b1eff6ab…`, แผง `jobs-8806a4bf6001` 8 แถว) และรัน 2 (`a9a467f6…`, `jobs-a021e7c41318` 6 แถว): ไม่มี `note` ในแผง ข้อความตอบไม่ทวนชื่อไฟล์ และใช้ชื่อปุ่มจริง เช่น "กดปุ่ม "อนุมัติที่เลือก" หรือ "ปฏิเสธที่เลือก" ได้ทันที" รัน 3 (`a9512160…`, `jobs-5a3937dbff4c`): ทุกแถวมี `note` เป็นสรุปเอกสาร (ไม่ใช่ชื่อไฟล์ เช่น "ใบเสนอราคา Q25100034-8 จาก Softnix Technology ถึง Pro Inside ยอดรวม 2,671,255 บาท") แต่ข้อความตอบทวนเนื้อหา note เป็น bullet พร้อมชื่อไฟล์ ("**[ควรตรวจสอบ]** ไฟล์ `1_0.png` (SW-20260401-A): ตัวเลข VAT…", "เอกสารอื่นๆ (Q25100034-8, INV-2026-0425, starbuck.pdf) ข้อมูลดูสอดคล้อง") ชื่อปุ่มถูก ดู M1 ในสรุป — `shots3/r2-01-run1.png`, `r2-01-run2.png`, `r2-01-run3.png` |
| 5 | ❌ | ✅ | เลือก Google-inv.png + Invoice_1.jpg ในแผง `jobs-8806a4bf6001` กด "อนุมัติที่เลือก": `RESP 202 …/conversations/b1eff6ab…/ui-actions` bubble ผู้ใช้ "อนุมัติเอกสาร 2 รายการที่เลือก" ไม่มี JSON DB `agent_messages` kind `ui_action`, `ui_action = {"name": "approve_documents", "surface_id": "jobs-8806a4bf6001", "document_ids": ["bf19f3ae…", "c7f9c192…"], "source_component_id": "approve"}` 1.2 วิหลังคลิกขณะ "Agent กำลังทำงาน": "อนุมัติที่เลือก:disabled", "ปฏิเสธที่เลือก:disabled" + โน้ต "ส่งคำสั่งแล้ว" — `shots3/r2-05-selected.png`, `shots3/r2-05-running.png` |
| 6 | ✅ (พิมพ์) | ✅ (คลิก) | จากคลิกข้อ 5 กล่องยืนยันเดียว: "Confirmation Required / อนุมัติเอกสารที่รอตรวจ 2 รายการ / bulk_approve / เอกสาร 2 รายการ / Google-inv.png รอตรวจ / Invoice_1.jpg รอตรวจ / Show arguments / Confirm / Reject" pending `e2591925…` — `shots3/r2-06-confirm.png`, `shots3/r2-06-confirm-box.png` |
| 7 | ✅ (พิมพ์) | ✅ (คลิก) | กด Confirm: `RESP 200 …/agent/confirm/e2591925…` tool result `{"ok": true, "verified": true, "approved_count": 2}` DB: Google-inv.png และ Invoice_1.jpg = reviewed/confirmed อีก 6 ใบยัง extraction_completed run `05909614…` = succeeded — `shots3/r2-07-after-confirm.png` |
| 8 | ❌ | ✅ | หลัง Confirm แผงยังขึ้น "ส่งคำสั่งแล้ว" ปุ่ม disabled DB `agent_surfaces`: `jobs-8806a4bf6001` answered, `answered_by_run_id = 05909614…` (= run ของคลิก) |
| 9 | ❌ | ✅ | รีโหลดหน้าแล้วเปิดแท็บ AI Agent: แผงยังขึ้น "ข้อมูล ณ 1 พ.ย. 2569 09:19" + "ส่งคำสั่งแล้ว" ปุ่ม disabled bubble ผู้ใช้หลังรีโหลด "อนุมัติเอกสาร 2 รายการที่เลือก" ไม่มี JSON คลิกซ้ำที่แผงนี้ผ่าน API ได้ `409 {"detail":"แผงนี้ส่งคำสั่งไปแล้ว"}` (`logs3/api.log`) — `shots3/r2-09-reload.png` |
| 10 | ✅ | ✅ | บทสนทนาใหม่ `5f9801e8…` พิมพ์ "อนุมัติเอกสาร Q25100034-8.pdf" กล่อง: "อนุมัติเอกสาร Q25100034-8.pdf / approve_document / เอกสาร 1 รายการ / Q25100034-8.pdf รอตรวจ" (ชื่อไฟล์ ไม่ใช่ UUID แล้ว, M4) กด Reject ในกล่อง: pending `1e2043a5…` = rejected, run `d7f68f1a…` = **succeeded** ไม่มีกล่องแดง ("NO RED BOX") เอกสารยัง extraction_completed agent ตอบ "การอนุมัติเอกสาร **Q25100034-8.pdf** ไม่ได้ถูกดำเนินการ — ระบบแจ้งว่าการยืนยันถูกปฏิเสธ" — `shots3/r2-10-confirm.png`, `shots3/r2-10-after-reject.png` |
| 11 | ❌ | ✅ | แผง `jobs-a021e7c41318` เลือก 1_0.png + 567_Generated_Image.png กด "ปฏิเสธที่เลือก": กล่องเดียว "ปฏิเสธเอกสารที่รอตรวจ 2 รายการ / bulk_reject / เอกสาร 2 รายการ / 1_0.png รอตรวจ / 567_Generated_Image.png รอตรวจ" (นับ "Confirmation Required" ได้ 1) — `shots3/r2-11-confirm.png` |
| N1 | ⚠️ | ✅ | บทสนทนา `a9512160…`: หลัง `show_chart` `jobs-e661a8902fec` และ `show_metrics` `jobs-63a8d9371bbd` รายการ `jobs-5a3937dbff4c` ยัง active ใน DB เลือก Q25100034-8.pdf กด "อนุมัติที่เลือก" ทำงาน: bubble "อนุมัติเอกสาร 1 รายการที่เลือก" kind `ui_action` กล่อง "อนุมัติเอกสารที่รอตรวจ 1 รายการ / bulk_approve / Q25100034-8.pdf" กด Reject แล้วแผงกลับมาใช้ได้ run `45fa373a…` succeeded — `shots3/r2-N1-list-after-metrics.png`, `shots3/r2-N1-confirm.png` |
| N3 | ❌ | ✅ | ต่อจากข้อ 11 กด Reject ในกล่อง: ปุ่มกลับเป็น "อนุมัติที่เลือก:enabled", "ปฏิเสธที่เลือก:enabled" โน้ต "ส่งคำสั่งแล้ว" หายไป ไม่มีกล่องแดง pending `2977a15b…` = rejected run `33175dcd…` = succeeded (ไม่ใช่ failed) API `GET /agent/conversations/a9a467f6…` → `surfaces.jobs-a021e7c41318.status = "active"` (ตาราง `agent_surfaces` ยังเก็บ answered ตามออกแบบ สถานะคำนวณตอนอ่านใน `panel_status`, `crud_agent_surface.py:13`) ทั้งสองเอกสารยัง extraction_completed — `shots3/r2-N3-after-reject.png` |
| N4 | ⚠️ | ⚠️ | ใช้แผงเดียวกันที่เพิ่งเปิดกลับ (พิสูจน์ว่าคลิกซ้ำได้) เลือก starbuck.pdf กด "อนุมัติที่เลือก" กล่อง "อนุมัติเอกสารที่รอตรวจ 1 รายการ / starbuck.pdf" แล้วกด "หยุด": โน้ต "คำขอยืนยันหมดเวลา / อนุมัติเอกสารที่รอตรวจ 1 รายการ / ไม่มีการเปลี่ยนแปลงใดๆ ขอให้ Agent ถามใหม่ได้" ปุ่มแผง enabled ไม่มีกล่องแดง pending `c62e5003…` = expired, run `270db3e8…` = cancelled "Stopped by the user" `POST /agent/confirm/c62e5003…` ได้ `409 "คำขอยืนยันนี้หมดเวลาแล้ว ไม่มีการเปลี่ยนแปลงใดๆ ขอให้ Agent ถามใหม่ได้"` **แต่ชิป `bulk_approve` ยังหมุน** (`<span role="status" aria-label="Loading" class="astryx-spinner">`) ทั้งก่อนและหลังรีโหลด (known open item) และหลังรีโหลดโน้ตหมดเวลาหายไป — `shots3/r2-N4-confirm.png`, `shots3/r2-N4-stopped.png`, `shots3/r2-N4-reload-chip.png` |
| N5 | ⚠️ | ⚠️ | B2 แก้แล้ว 3/3 และ B3 แก้แล้ว แต่พบปัญหาใหม่หลังหมดเวลา ดูตารางย่อย N5 ด้านล่าง |
| N6 | ❌ | ✅ | ระหว่าง run ของคลิกข้อ 5 (ยังไม่รีโหลด) เปิดรายการสนทนา: `["อนุมัติเอกสาร 2 รายการที่เลือก [active]", "เอกสารที่ความมั่นใจต่ำกว่า 80%", …]` บทสนทนาที่เพิ่งสร้างไม่ขึ้น "New conversation" แล้ว (M3) DB title = "อนุมัติเอกสาร 2 รายการที่เลือก" — `shots3/r2-N6-convlist-running.png`, `shots3/r2-N6-convlist.png` |
| A3 | ⚠️ | ✅ | บทสนทนา `90b97edb…` คำสั่งเดิม `show_table` ครั้งเดียว สำเร็จครั้งแรก ไม่มี validation error คอลัมน์ "วันครบกำหนด" `kind: date` ค่า ISO `"2026-03-20"`, `"2013-12-01"`, `"2026-01-31"` แสดง "20 มี.ค. 2569", "1 ธ.ค. 2556", "31 ม.ค. 2569" แถวไม่มีวันครบกำหนดเป็น "–" หมายเหตุแยกคอลัมน์ text ข้อสังเกต: ช่องหมายเหตุยังมีวันที่แบบ ค.ศ. ในข้อความ ("ยืนราคาถึง 31/01/2026") ซึ่งไม่ใช่ ISO จึงไม่ถูกตรวจ หลังวาดแผง run **failed** เพราะ provider: UI กล่องแดง "The AI provider could not complete the request (APIStatusError). Try again or check the provider in Settings." log worker `Error code: 402 - This request requires more credits, or fewer max_tokens. You requested up to 65536 tokens, but can only afford 51552` (เครดิต OpenRouter หมด ไม่เกี่ยวกับรอบแก้) จึงไม่ได้ข้อความตอบ — `shots3/r2-A3.png`, `shots3/r2-A3-full.png` |
| A3b | ⚠️ | ✅ | บทสนทนา `2a51f0d0…` คำสั่งเดิม agent ส่ง `actual_rate` 7.0352 และ 7.0022 เทียบ 7.0 (คู่เดิมที่รอบ 1 ขึ้น "▲ +0 จุด (แย่ลง)") ตอนนี้ทั้ง 6 แถว "▬ คงที่ 0 จุด" sr-only "คงที่" สี rgb(107,110,118) `text-viz-neutral` ไม่มีคำ แย่ลง/ดีขึ้น (B4) ข้อสังเกต M1: ข้อความตอบทำตาราง markdown ซ้ำทั้งตาราง ("\| starbuck.pdf \| 233.64 \| 16.36 \| 7.002% \| 7% \| +0.002 \|" ฯลฯ) — `shots3/r2-A3b-change.png` |
| N8 | ✅ | ✅ | 360×800: บทสนทนา A3 หน้า 360/360 ตาราง 1356/258 `overflow-x:auto`, A3b 360/360 ตาราง 790/258, รายการเอกสาร 360/360, N1 (รายการ+กราฟ+การ์ด) 360/360 ทุกแผงกว้าง 286 ขอบขวา 323 `window.scrollTo(500,…)` แล้ว `scrollX = 0` ทุกหน้า — `shots3/r2-360-A3.png`, `r2-360-A3b.png`, `r2-360-list.png`, `r2-360-N1.png` |
| N9 | ✅ | ✅ | กด "เปิดดู" 02_Tax_Invoice_INV-2026-0425.pdf ในแผง: dialog "Preview: 02_Tax_Invoice_INV-2026-0425.pdf" canvas 1 ไม่มี "Failed to load PDF" `RESP 200 http://localhost:3000/_next/static/media/pdf.worker.min.2th4soq4xwzz7.mjs` ไม่มี request ไป unpkg ไม่มี console error ตลอดรอบ (ไม่มีไฟล์ `logs3/console.log`) — `shots3/r2-pdf.png` |

M4 (กล่องยืนยันเอกสารเดียวแสดงชื่อไฟล์): ✅ ทุกกล่อง `approve_document` ในรอบนี้ 7 กล่อง เขียน "อนุมัติเอกสาร <ชื่อไฟล์>" ทั้งใน DB `description` และในกล่อง เช่น "อนุมัติเอกสาร starbuck.pdf", "อนุมัติเอกสาร 02_Tax_Invoice_INV-2026-0425.pdf" และโน้ตหมดเวลา "อนุมัติเอกสาร Q25100034-8.pdf"

### N5: หยุดแล้วขอเอกสารใหม่ (B2) 3 ครั้ง บทสนทนาใหม่ทุกครั้ง

| ครั้ง | บทสนทนา | A (หยุด) | B (คำขอถัดไป) | กล่องยืนยันของ B | ผล |
|---|---|---|---|---|---|
| 1 | `dd25118e…` | "อนุมัติเอกสาร starbuck.pdf" pending `c3b30af0…` expired, run `1ec16270…` cancelled | "อนุมัติเอกสาร 567_Generated_Image.png" | "อนุมัติเอกสาร 567_Generated_Image.png / approve_document / 567_Generated_Image.png รอตรวจ" `approve_document {"doc_id": "839caa5f…"}` (pending `62933cfe…` → Reject → run succeeded) | ✅ ชื่อ B — `shots3/r2-N5-t1-stopped.png`, `r2-N5-t1-confirmB.png` |
| 2 | `d5c109ee…` | "อนุมัติเอกสาร 02_Tax_Invoice_INV-2026-0425.pdf" pending `00c211c0…` expired, run `85faf096…` cancelled | "อนุมัติเอกสาร Quotation-Q2026090009.pdf" | "อนุมัติเอกสาร Quotation-Q2026090009.pdf / approve_document / Quotation-Q2026090009.pdf รอตรวจ" `doc_id efbedbd6…` (pending `1602f271…` → Reject → run succeeded) | ✅ ชื่อ B — `shots3/r2-N5-t2-stopped.png`, `r2-N5-t2-confirmB.png` |
| 3 | `efe4c644…` | "อนุมัติเอกสาร 1_0.png" pending `6e345ecb…` expired, run `fa528249…` cancelled | "อนุมัติเอกสาร Q25100034-8.pdf" | "อนุมัติเอกสาร Q25100034-8.pdf / approve_document / Q25100034-8.pdf รอตรวจ" `doc_id 1078db78…` ปล่อยให้หมดเวลาจริง | ✅ ชื่อ B, ⚠️ หลังหมดเวลา (ด้านล่าง) — `shots3/r2-N5-t3-stopped.png`, `r2-N5-t3-confirmB.png` |

ทุกครั้งหลังกด "หยุด" ไม่มีกล่องแดง

การหมดเวลาจริง 300 วินาที (ครั้งที่ 3): pending `f47e0439…` สร้าง 02:32:44Z หมดเวลา 02:37:48Z (304 วิ) UI ขึ้นโน้ต "คำขอยืนยันหมดเวลา" ที่ 02:37:49Z แต่ **agent เรียก `approve_document` เอกสารเดิมซ้ำเองใน run เดิมทันที** (02:38:03Z, pending ใหม่ `ba05d886…`) โดยผู้ใช้ไม่ได้สั่ง กล่อง Confirm ขึ้นใหม่แทนโน้ต (`shots3/r2-N5-t3-expired.png`) และ run ทำงานต่ออีก 300 วิ จนหมดเวลารอบสอง 02:43:07Z แล้วจึงตอบ run `c2232e51…` = **succeeded** (B3 แก้แล้ว) ไม่มีกล่องแดง ข้อความตอบท้าย "**[สำคัญ]** … การอนุมัติเอกสารยังไม่สำเร็จ เนื่องจาก**คำขอยืนยันการอนุมัติหมดเวลา** … — ไม่ใช่การปฏิเสธ" โน้ต "คำขอยืนยันหมดเวลา / อนุมัติเอกสาร Q25100034-8.pdf / ไม่มีการเปลี่ยนแปลงใดๆ ขอให้ Agent ถามใหม่ได้" ชิปที่มีคำขอที่ถูกหยุดยังหมุน ("approve_document 3") และชิปของคำขอที่หมดเวลาเป็นไอคอน X สีแดง — `shots3/r2-N5-t3-end.png`, `shots3/r2-N5-t3-spinner.png`

## วัดผลกับโมเดลจริง รอบ 2

นับจาก `agent_messages` (role=tool, `show_*`) ของ Job UAT ตั้งแต่ 02:15Z: 7 การเรียก (`show_documents` 3, `show_table` 2, `show_chart` 1, `show_metrics` 1) สำเร็จครั้งแรก 7 / 7 **ไม่มี validation error** ในรอบนี้ ไม่มีข้อความ error ของ show_* ให้บันทึก

คลิกปุ่มในแผงถึง agent: 5 คลิก (ข้อ 5, 11, N4, N1 และ 409 ทดสอบผ่าน API) ทุกคลิกใน UI ได้ 202 และ agent เรียก `bulk_approve` / `bulk_reject` ด้วย `doc_ids` ตรงกับที่เลือกทุกครั้ง

run ในรอบนี้: succeeded 12, cancelled 4 (กดหยุดทั้งหมด), failed 2 (ทั้งคู่เป็น 402 เครดิต OpenRouter หมด ในบทสนทนา `90b97edb…`)

## สรุปผลรอบ 2

- ทดสอบซ้ำ 17 กรณี (1, 5, 6, 7, 8, 9, 10, 11, N1, N3, N4, N5, N6, A3, A3b, N8, N9) + M4: **✅ 14, ⚠️ 3 (1, N4, N5), ❌ 0**
- ผลรวม 36 กรณีหลังรอบ 2 (กรณีที่ไม่ได้ทดสอบซ้ำใช้ผลรอบ 1): **✅ 31, ⚠️ 5 (1, N4, N5, A1, A6), ❌ 0**
- B1, B2, B3, B4, M2, M3, M4 แก้แล้วตามที่สังเกตได้ M1 ดีขึ้นแต่ยังไม่หมด

ปัญหาที่เหลือ เรียงตามความรุนแรง (หลักฐานและสาเหตุ ยังไม่ได้แก้):

1. **R2-1 (กลาง) หลังคำขอยืนยันหมดเวลา agent ขอยืนยันซ้ำเองใน run เดิม** (N5 ครั้งที่ 3) ผู้ใช้ที่ไม่อยู่หน้าจอจะเจอกล่องยืนยันใหม่แทนโน้ตหมดเวลา และ run ค้างอีก 300 วิต่อครั้ง สาเหตุ: เมื่อคำตอบไม่ใช่ confirmed loop ใส่ `declined_result` แล้ววนต่อตามปกติ (`backend/app/agent/loop.py:2553-2555`, ข้อความผล `backend/app/agent/confirmations.py:13`) ไม่มีอะไรกันการเรียกเครื่องมือเดิมซ้ำใน run เดียวกัน มีแค่คำสั่งใน system prompt "Say that it expired … and offer to ask again" (`backend/app/agent/context.py:490`) ซึ่งโมเดลไม่ทำตามในครั้งนี้ (เกิด 1 ใน 1 ครั้งที่ปล่อยหมดเวลาจริง)
2. **R2-2 (ต่ำ-กลาง) ชิปของ tool call ที่ถูกหยุดหมุนค้างถาวร** ทั้งก่อนและหลังรีโหลด และชิปกลุ่มที่รวม call นั้น ("approve_document 3") ก็หมุน สาเหตุ: `getStatus` คืน `"running"` เมื่อไม่มีผลลัพธ์ (`frontend/components/agent/AgentToolCalls.tsx:100`) การหยุดไม่บันทึก tool result ผลลัพธ์ "unfinished" ที่เพิ่มใน a725ec3 สร้างเฉพาะในประวัติที่ส่งให้โมเดล (`backend/app/agent/context.py:170`, `:258`) ไม่ถึง UI
3. **R2-3 (ต่ำ) M1 ยังเกิดบางครั้ง** รัน 3 ของข้อ 1 ทวนเนื้อหา note พร้อมชื่อไฟล์ และ A3b ทำตาราง markdown ซ้ำทั้งแผง สาเหตุ (อนุมาน): คำสั่ง "do not restate" อยู่ในคำอธิบายเครื่องมือ (`backend/app/agent/tools/ui_tools.py:109`) แต่ system prompt ยังสั่งตรงข้าม "include filename evidence" (`context.py:494`), "Cite the source filename … for every material finding" (`context.py:501`), "For totals/items, use clear bullets or a compact table" (`context.py:503`)
4. ต่ำ: ชิปของคำขอที่ถูก Reject หรือหมดเวลาแสดงไอคอน X สีแดงเหมือน error แม้ run สำเร็จ เพราะ `getErrorMessage` ดูแค่ `result.error` ไม่ดู `declined` (`frontend/components/agent/AgentToolCalls.tsx:50-56`) — `shots3/r2-N5-t3-end.png`
5. ต่ำ: โน้ต "คำขอยืนยันหมดเวลา" หายหลังรีโหลด เพราะโน้ตมาจาก `activeRun.pending_action` (`AgentPanel.tsx:307`, `lib/agentConversation.ts:31`) และหลังรีโหลด `restoreActiveRun` ดึงเฉพาะ run ที่ยังทำงาน (`AgentPanel.tsx:240-249`) — `shots3/r2-N4-reload.png`
6. สภาพแวดล้อม: เครดิต OpenRouter หมด (402) ตั้งแต่ ~02:50Z ทุก run ใหม่ล้ม UI แสดงข้อความทั่วไป "(APIStatusError)" เพราะ `_user_facing_llm_error` ไม่มีกรณี 402 (`backend/app/agent/loop.py:100-126`)

ทดสอบไม่ได้หรือไม่ครบในรอบ 2:

- ข้อความตอบของ A3 (run ล้มด้วย 402 หลังวาดแผง) และงาน LLM ใดๆ หลัง 02:50Z
- ข้อ 1 สำหรับ M1 ทดสอบ 3 ครั้ง (2 ผ่าน 1 ไม่ผ่าน) จำนวนน้อย อัตราจริงยังไม่รู้
- การหมดเวลา 300 วิ กับแผงที่ถูกคลิก (ปล่อยหมดเวลาจริงเฉพาะคำขอที่พิมพ์) การเปิดแผงกลับหลังหยุดทดสอบด้วยแผงที่ถูกคลิก (N4) แล้ว
- กรณีที่ไม่ได้อยู่ในขอบเขตรอบนี้ (2, 3, 4, 12, 13, 14, N2, N7, A1, A1b, A2, A4-A11) ใช้ผลรอบ 1

ข้อมูลที่สร้างหรือเปลี่ยนในรอบ 2 (คงไว้ทั้งหมด):

- บทสนทนา: `b1eff6ab-af0a-4a75-aaa1-9557314d7bc8`, `a9a467f6-bf69-4aa7-8ced-6c4ede65bd15`, `5f9801e8-fe51-4c31-9dde-11106899544f`, `a9512160-207d-4c54-828b-fd93c9061bf4`, `dd25118e-3f1c-4f13-be7b-f1856cd9d447`, `d5c109ee-4e0a-41de-9b96-b4a289c12a99`, `efe4c644-24ab-472e-b5f4-43dcb7dc6165`, `2a51f0d0-6385-4337-af33-af0958597666`, `90b97edb-9ebf-4aa7-a3f0-e31095bb57fa`
- แผง: `jobs-8806a4bf6001`, `jobs-a021e7c41318`, `jobs-5a3937dbff4c` (show_documents), `jobs-e661a8902fec` (show_chart), `jobs-63a8d9371bbd` (show_metrics), `jobs-4c3c9c8623dd`, `jobs-cef00df89f1e` (show_table)
- คำขอยืนยัน: `e2591925-0293-42e4-85d9-564722908830` confirmed, `2977a15b-6a61-480a-b2da-c011747f2bd2` rejected, `c62e5003-c147-424f-a529-de644e4c4c34` expired (หยุด), `1e2043a5-b9cb-4d11-b649-0df9e83a0877` rejected, `e49ba13a-ba75-4ed5-bacf-ead0fdde64bf` rejected, `c3b30af0-5077-4f3a-8b4f-afaa1154686d` expired (หยุด), `62933cfe-791a-478c-a64f-6c346c483db6` rejected, `00c211c0-1f07-4c83-9d0d-9f39fb11c92b` expired (หยุด), `1602f271-5eea-48e6-82c7-8edb9ec4ad05` rejected, `6e345ecb-0413-4223-94ab-5cb3a43ce10d` expired (หยุด), `f47e0439-c99c-4745-9cd2-bb5b66407e03` expired (300 วิ), `ba05d886-7de9-4e32-8009-a1a0d7cdcc1c` expired (300 วิ, agent ขอซ้ำเอง)
- สถานะเอกสาร: ข้อ 7 อนุมัติ Google-inv.png และ Invoice_1.jpg จริง แล้วตั้งกลับด้วย `reset.py` (`PUT /documents/{id}`) จบรอบด้วย 8 ใบ extraction_completed (`review_decision` null) และสัญญา reviewed เหมือนตอนเริ่ม
- ไม่ได้เขียน DB โดยตรง
