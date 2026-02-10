# Softnix InsightDOC – คุณสมบัติ

## ภาพรวม
- ระบบประมวลผลเอกสารอัตโนมัติที่ผสาน OCR + LLM สำหรับสกัดข้อมูลเชิงโครงสร้างจาก PDF/รูปภาพ
- สถาปัตยกรรม FastAPI backend + Next.js frontend เชื่อมต่อ PostgreSQL, Redis queue, และที่เก็บไฟล์ S3-compatible (MinIO)
- จัดการและรันทุกบริการผ่าน Docker Compose; รองรับตั้งค่า API/โมเดลจาก UI

## ฟีเจอร์หลัก
- **การจัดการผู้ใช้และสิทธิ์**: RBAC (Admin/Manager/User), JWT auth, แยกการเข้าถึงตามบทบาท
- **การกำหนดสคีมาเอกสาร**: สร้าง/แก้ไขสคีมาฟิลด์, ประเภทข้อมูล, คำอธิบาย prompt, validation rules (regex, required, min/max), รองรับ import จาก JSON Schema และเวอร์ชันสคีมา
- **งานประมวลผลแบบ Job**: รวมไฟล์เป็น Job เดียว, อัปโหลดแบบ drag & drop หรือผ่าน API, เลือกสคีมาต่อไฟล์, ติดตามสถานะงาน
- **การสกัดข้อความและข้อมูลโครงสร้าง**: ขั้นแรกทำ OCR ได้จาก PDF/รูปภาพ, ขั้นต่อใช้ LLM จัดโครงสร้างเป็น JSON ตามสคีมา, ปรับแต่ง OCR/LLM engine และโมเดลได้
- **หน้าตรวจทาน Human-in-the-loop**: มุมมองเอกสารคู่กับฟอร์มข้อมูล, แสดงคะแนนความเชื่อมั่น/การแจ้งเตือน validation, ผู้ใช้แก้ไขและกด Verify ได้
- **การตรวจสอบและ Compliance**: Validation แบบ cross-field, กฎ Compliance/department isolation, Audit logging (ตามสเปก), สถานะเอกสาร (Pending/Reviewed/Exported/Error)
- **การส่งออกและเชื่อมต่อ**: ส่งออก JSON/CSV/Excel/XML, Webhook เมื่อ Verify หรือผิดพลาด, REST API CRUD เอกสาร/สคีมา/ผู้ใช้ เพื่อเชื่อม ERP/CRM
- **การตั้งค่าระบบจาก UI**: กำหนด API Endpoint, Token, เลือก OCR engine/LLM model, จัดการคีย์แบบไม่ hardcode

## ขั้นตอนการใช้งานย่อ
1) ตั้งค่า API/Token/OCR engine ในหน้า Settings  
2) สร้างสคีมาฟิลด์ในหน้า Schemas หรือ import JSON Schema  
3) สร้าง Job แล้วอัปโหลดไฟล์ เลือกสคีมาต่อไฟล์  
4) รัน OCR/Structure, เข้าหน้า Review เพื่อตรวจแก้และ Verify  
5) ส่งออกไฟล์ผลลัพธ์หรือเรียกใช้ผ่าน API/Webhook

## โครงสร้างและอินฟราสตรักเชอร์
- บริการหลัก: FastAPI, Next.js, PostgreSQL, Redis (คิว), MinIO (ที่เก็บไฟล์), รองรับ optional Vector DB สำหรับ RAG
- รันด้วย `docker compose up --build`; frontend ที่ :3000, backend ที่ :8000 (มี /docs)
- มีสคริปต์ `scripts/services.sh` สำหรับ up/down/restart/logs ของบริการ web/api

## ความปลอดภัย
- ไม่ hardcode credential; ตั้งค่าจากฐานข้อมูล/ENV
- Role-based access control, JWT auth, CORS config
- แนวปฏิบัติ: เข้ารหัสข้อมูลสำคัญ, ตรวจชนิด/ขนาดไฟล์, สแกนมัลแวร์, HTTPS, audit log
