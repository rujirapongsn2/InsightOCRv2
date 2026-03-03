# 10 เหตุผลด้านเทคนิคที่ควรเลือก InsightDOC

---

## 1. ⚡ Async Processing Pipeline ด้วย Celery + Redis
การประมวลผล OCR และ Structured Extraction ทำงานเป็น Background Task ผ่าน **Celery** โดยมี **Redis** เป็น Broker และ Backend สำหรับ Task State ทำให้ HTTP request ตอบกลับทันที ไม่บล็อก API server และรองรับการประมวลผลพร้อมกันหลายเอกสารด้วย Worker Pool ที่ขยายได้

---

## 2. 📡 Real-time Progress Streaming ด้วย Server-Sent Events (SSE)
สถานะการประมวลผลเอกสาร (percent + stage) ถูก Push มาแบบ Real-time จาก Backend ผ่าน SSE โดยไม่ต้อง Polling ทุกฝ่าย Frontend อ่านค่าจาก Redis Key `doc_progress:{id}` ผ่าน Endpoint `/task-status` และแสดงแถบ Progress พร้อม Label เช่น `queuing → ocr_extraction → structured_extraction → done` ทำให้ UX ราบรื่นแม้งานใช้เวลานาน

---

## 3. 🔄 LLM Streaming Response ด้วย OpenAI-compatible API
ผลลัพธ์จาก LLM Validation แสดงแบบ Token-by-token ผ่าน SSE Streaming ฝั่ง Backend ใช้ `openai.stream=True` และ `yield` event ทีละ chunk Frontend รับและต่อข้อความสะสมจนครบ ทำให้ผู้ใช้เห็นผลทันทีโดยไม่ต้องรอ response ทั้งหมด รองรับทั้ง Chat completions API และ Responses API (o-series) พร้อม `reasoning_effort` parameter

---

## 4. 🔐 JWT Authentication พร้อม Role-based Authorization Middleware
ระบบ Auth ใช้ **JWT Bearer Token** ที่ตรวจสอบผ่าน FastAPI Dependency (`deps.get_current_user`) ทุก Endpoint ที่ต้องการสิทธิ์จะถูก Guard ด้วย Role Check (`admin`, `manager`, `user`, `documents_admin`) เพื่อป้องกัน Privilege Escalation ตั้งแต่ชั้น API โดยไม่ต้องเขียน Guard ซ้ำในแต่ละ Route

---

## 5. 🗃️ Pluggable Storage Backend (Local / MinIO / S3)
การจัดการไฟล์เอกสารถูก Abstract ออกจาก Business Logic ผ่าน Storage Layer ที่เลือกได้ด้วย Environment Variable `STORAGE_TYPE=local|minio|s3` โดยไม่ต้องแก้ Code ทำให้ Deploy ในสภาพแวดล้อม Development ด้วย Local Storage และเปลี่ยนเป็น MinIO หรือ AWS S3 สำหรับ Production ได้โดยไม่กระทบ Application Layer

---

## 6. 🏗️ Clean Architecture ด้วย FastAPI + SQLAlchemy + Pydantic
Backend แยก Layer ชัดเจนตาม Clean Architecture:
- `api/v1/endpoints/` — HTTP routing และ Request/Response handling
- `crud/` — Database operations (Create, Read, Update, Delete)
- `models/` — SQLAlchemy ORM models (Source of truth ของ DB schema)
- `schemas/` — Pydantic models สำหรับ Validation และ Serialization
- `services/` — Business logic (OCR, Structured Extraction)

ทำให้ Unit Test, Swap Dependencies, และ Extend features ทำได้โดยไม่ side-effect กัน

---

## 7. 🐳 Dockerized Microservices พร้อม Network Isolation
ระบบประกอบด้วย 8 Services บน Docker Compose โดย DB, Redis, และ MinIO อยู่ใน **Internal Network** ที่ไม่เปิดให้ Internet เข้าถึงโดยตรง การเชื่อมต่อออกนอกองค์กรผ่าน **Gateway Proxy** เพียงจุดเดียว ลดพื้นที่โจมตี (Attack Surface) และบังคับให้ Traffic ผ่าน Egress Control เสมอ

---

## 8. 🔌 Integration Engine ที่รองรับ 3 รูปแบบผ่าน Config เดียว
ระบบ Integration ออกแบบให้รองรับ 3 Integration Type (`api`, `workflow`, `llm`) ผ่าน Schema เดียวที่มี `config` เป็น JSONB ใน PostgreSQL ทำให้เพิ่ม Integration Type ใหม่ได้โดยไม่ต้องเพิ่ม Column ในฐานข้อมูล Backend ใช้ Type discriminator เพื่อ Route logic ไปยัง Handler ที่เหมาะสม รองรับ Custom Headers, Payload Template, Webhook, และ OpenAI Responses API

---

## 9. 📊 Activity Logging ด้วย Middleware-level Instrumentation
ทุก Action ที่สำคัญ (Login, CRUD บน Job/Document/Schema/Integration, Process Document) ถูกบันทึกผ่าน `activity_logger` utility ที่เรียกใช้ได้จากทุก Endpoint โดยบันทึก `user_id`, `action`, `resource_type`, `resource_id`, `ip_address`, และ `details` เป็น JSONB ทำให้ Query และ Filter Log ด้วย SQL ได้ยืดหยุ่น รองรับ Pagination สำหรับ Log จำนวนมาก

---

## 10. 🧩 Next.js App Router พร้อม Dynamic Import และ SSE Client
Frontend ใช้ **Next.js App Router** (Server + Client Components แยกกันชัดเจน) พร้อม:
- **Dynamic Import** สำหรับ `PDFViewer` เพื่อหลีกเลี่ยง SSR บน Browser-only library
- **SSE Client** (`EventSource` / `ReadableStream`) สำหรับรับ Streaming ทั้งจาก OCR Progress และ LLM Output
- **Memoized PDF URL** ป้องกัน Blob URL ถูก Revoke ขณะ Re-render
- **Context API** (SchemaWizardContext) สำหรับ Multi-step Wizard State Management
- **Tailwind CSS** พร้อม Utility-first approach ที่ทำให้ UI Consistent โดยไม่ต้องเขียน Custom CSS
