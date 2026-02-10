# Softnix InsightDOC

## 1. Executive Summary
**Softnix InsightDOC** is an intelligent document processing solution designed to automate data extraction from various document types (Invoices, POs, Tax Forms, etc.) using a combination of **OCR (Optical Character Recognition)** and **LLM (Large Language Model)** technologies.

The system allows users to upload documents, define schemas for extraction, validate the extracted data, and export the results to other systems via API or file formats.

## 2. Core Features
*   **Flexible Schema Definition**: Users can define fields, data types, and validation rules for any document type.
*   **Hybrid Extraction Engine**: Combines traditional OCR for text localization with LLMs for semantic understanding and data structuring.
*   **Human-in-the-Loop Review**: A user-friendly interface for verifying and correcting extracted data with side-by-side document viewing.
*   **Automated Validation**: Built-in validation rules (regex, data types, cross-field validation) to ensure data quality.
*   **Integration Ready**: RESTful APIs and Webhooks for seamless integration with ERP, CRM, or other business systems.
*   **Compliance & Security**: Role-based access control (RBAC), audit logs, and data encryption.

## 3. System Architecture
### 3.1 High-Level Architecture
*   **Frontend**: Next.js (React) with Tailwind CSS for a responsive and modern UI.
*   **Backend**: Python (FastAPI) for high-performance API handling.
*   **OCR Engine**: Tesseract / EasyOCR / Cloud Vision API (Pluggable).
*   **LLM Integration**: OpenAI GPT-4 / Azure OpenAI / Local LLMs (via Ollama).
*   **Database**: PostgreSQL for structured data and user management.
*   **Vector DB**: (Optional) For semantic search and RAG capabilities.
*   **Queue System**: Redis + Celery for asynchronous document processing.
*   **Storage**: S3-compatible storage (MinIO / AWS S3) for document files.

## 4. Functional Requirements
### 4.1 User Management
*   **Roles**: Admin, Manager, User.
*   **Authentication**: Email/Password, SSO (OpenID Connect / SAML).
*   **Department Isolation**: Users can be assigned to departments; data is isolated by department.

### 4.2 Schema Management
*   **Create/Edit Schemas**: Define document types (e.g., "Invoice", "Contract").
*   **Field Definition**:
    *   Name (e.g., "Invoice Number")
    *   Type (Text, Number, Date, Table, Boolean)
    *   Description (Prompt for LLM)
    *   Validation Rules (Regex, Min/Max, Required)
*   **Version Control**: Track changes to schemas.

### 4.3 Document Processing
*   **Upload**: Drag & drop interface, bulk upload, API upload.
*   **Preprocessing**: Image enhancement, rotation correction, format conversion (PDF/Image to Text).
*   **Extraction**:
    *   Step 1: OCR to get raw text and layout.
    *   Step 2: LLM to parse text into JSON based on Schema.
*   **Post-processing**: Data normalization (e.g., date formats).

### 4.4 Review & Validation
*   **Dashboard**: List of processed documents with status (Pending, Reviewed, Exported, Error).
*   **Review Interface**:
    *   Left pane: Document viewer (with bounding boxes if possible).
    *   Right pane: Form with extracted data.
    *   Confidence scores displayed for each field.
    *   Visual indicators for validation errors.
*   **Correction**: Users can edit field values.
*   **Approval**: Mark document as "Verified".

### 4.5 Integration & Export
*   **Export Formats**: JSON, CSV, Excel, XML.
*   **Webhooks**: Trigger events on "Document Verified" or "Extraction Failed".
*   **API**: Full CRUD access to documents and extracted data.

## 5. Non-Functional Requirements
*   **Performance**: Support processing of 100+ pages per minute (scalable workers).
*   **Accuracy**: Target > 95% field-level accuracy for standard business documents.
*   **Scalability**: Horizontal scaling for worker nodes.
*   **Usability**: Clean, intuitive UI requiring minimal training (Cult UI / shadcn/ui).

## 6. UI/UX Design Guidelines
*   **Theme**: Professional, clean, "Enterprise SaaS" look.
*   **Framework**: Shadcn UI + Tailwind CSS.
*   **Colors**:
    *   Primary: Deep Blue / Indigo (Trust, Professionalism).
    *   Secondary: Slate / Gray (Neutral).
    *   Accents: Green (Success/Verified), Red (Error/Alert), Amber (Warning/Low Confidence).
*   **Typography**: Inter or Roboto (highly readable).

## 7. API Structure (Draft)
### 7.1 Authentication
*   `POST /api/auth/login`
*   `POST /api/auth/refresh`
*   `POST /api/auth/logout`

### 7.2 Users
*   `GET /api/users`
*   `POST /api/users`
*   `GET /api/users/{id}`
*   `PUT /api/users/{id}`

### 7.3 Schemas
*   `GET /api/schemas`
*   `POST /api/schemas`
*   `GET /api/schemas/{id}`
*   `PUT /api/schemas/{id}`

### 7.4 Jobs (Uploads)
*   `POST /api/jobs` (Upload file)
*   `GET /api/jobs`
*   `GET /api/jobs/{id}`

### 7.5 Documents (Individual Files)
*   `GET /api/documents/{id}`
*   `PUT /api/documents/{id}` (Update extracted data)
*   `POST /api/documents/{id}/verify` (Mark as verified)

## 8. User Journeys
### 8.1 Documents Admin: สร้าง Schema
1.  เข้าสู่ระบบด้วย Documents Admin role
2.  ไปที่ "จัดการ Schema"
3.  คลิก "+ สร้าง Schema ใหม่"
4.  กรอกชื่อ Schema และเลือกประเภทเอกสาร
5.  เพิ่ม Fields:
    *   กรอกชื่อ field
    *   เลือกประเภทข้อมูล
    *   เขียน extraction prompt
    *   กำหนด validation rules
6.  ตั้งค่า Compliance rules
7.  ตั้งค่า Cross-document validation (ถ้ามี)
8.  ทดสอบ Schema ด้วยเอกสารตัวอย่าง
9.  บันทึก Schema

### 8.2 User: ประมวลผลเอกสาร
1.  เข้าสู่ระบบด้วย User role
2.  ไปที่ "งาน" (Jobs)
3.  คลิก "+ สร้าง Job ใหม่"
4.  กรอกรายละเอียด
5.  คลิก "สร้าง"
6.  อัปโหลดเอกสาร (drag & drop หรือ browse)
7.  เลือกทีละเอกสารเพื่อสกัด หรือเลือกทั้งหมด รอ OCR เสร็จ
8.  เลือก schema ได้ในแต่ละไฟล์ กดทดสอบ โดยตรวจสอบกับ validation rules
9.  เลือก Review เอกสารทีละไฟล์ หรือคลิกตรวจสอบการ validation rules
10. แก้ไขข้อมูลที่ผิดพลาด (ถ้ามี)
11. บันทึกการแก้ไข
12. คลิกตรวจสอบเงื่อนไข Compliance หรือ Cross-document validation
13. ผลลัพธ์ % ความสอดคล้อง
14. Export หรือส่งข้อมูลผ่าน Integration
15. ดาวน์โหลดผลลัพธ์

### 8.3 Admin: จัดการผู้ใช้
1.  เข้าสู่ระบบด้วย Admin role
2.  ไปที่ "ผู้ใช้"
3.  คลิก "+ เพิ่มผู้ใช้"
4.  กรอกข้อมูลผู้ใช้
5.  เลือก Role
6.  เลือกแผนก
7.  บันทึก
8.  ส่ง email แจ้งผู้ใช้ใหม่

## 11. Deployment & Infrastructure
### 11.1 Development Environment
*   Local development with Docker Compose
*   Hot reload for backend and frontend
*   SQLite database

### 11.2 Staging Environment
*   Docker containers
*   PostgreSQL database
*   S3-compatible storage
*   Redis for task queue

### 11.3 Production Environment
*   Kubernetes cluster (optional) or Docker Swarm
*   PostgreSQL with replication
*   S3 for file storage
*   Redis for caching and task queue
*   Load balancer
*   SSL/TLS certificates

### 11.4 Monitoring & Logging
*   Application logs: Structured JSON logging
*   Error tracking: Sentry (optional)
*   Performance monitoring: Prometheus + Grafana (optional)
*   Uptime monitoring: UptimeRobot (optional)

## 12. Security Considerations
### 12.1 Data Protection
*   Encrypt sensitive data at rest
*   Use HTTPS for all communications
*   Sanitize user inputs
*   Validate file uploads (type, size, content)

### 12.2 Access Control
*   Role-based access control (RBAC)
*   Department-level data isolation
*   Audit logging for sensitive operations

### 12.3 API Security
*   JWT authentication
*   Rate limiting
*   CORS configuration
*   Input validation

### 12.4 File Security
*   Malware scanning
*   File type validation
*   Size limits
*   Secure file storage with signed URLs

## 13. Future Enhancements
### 13.1 Short-term (3-6 months)
*   Advanced OCR: Handwriting recognition
*   More LLM providers: Google, AWS Bedrock
*   Batch job scheduling
*   Email notifications
*   Audit trail dashboard

### 13.2 Medium-term (6-12 months)
*   Mobile application
*   Advanced analytics and reporting
*   Custom LLM fine-tuning
*   Multi-language support
*   Advanced workflow automation

### 13.3 Long-term (12+ months)
*   AI-powered document classification
*   Automatic schema generation
*   Real-time collaboration
*   Advanced data visualization
*   Integration marketplace

## 14. Success Criteria
### 14.1 Technical
*   ✅ System uptime > 99.5%
*   ✅ API response time < 200ms (p95)
*   ✅ Extraction accuracy > 95%
*   ✅ Zero security vulnerabilities

### 14.2 Business
*   ✅ 80% user adoption within 3 months
*   ✅ 70% reduction in manual processing time
*   ✅ 90% reduction in manual errors
*   ✅ Positive user feedback (NPS > 50)

### 14.3 User Experience
*   ✅ Task completion rate > 90%
*   ✅ User satisfaction score > 4/5
*   ✅ Low support ticket volume (< 5/week)

## 15. Risks & Mitigation
### 15.1 Technical Risks
*   **LLM API instability**: Implement retry logic, fallback providers.
*   **OCR accuracy issues**: Support multiple OCR engines, manual review.
*   **Large file processing**: Implement chunking, async processing.
*   **Database performance**: Add indexes, implement caching.

### 15.2 Business Risks
*   **Low user adoption**: User training, simple UX, support documentation.
*   **Data privacy concerns**: Clear privacy policy, data encryption, compliance.
*   **Integration complexity**: Standard API, comprehensive documentation.

## 16. Appendix
### 16.1 Glossary
*   **OCR**: Optical Character Recognition - เทคโนโลยีแปลงภาพเป็นข้อความ
*   **LLM**: Large Language Model - โมเดลภาษาขนาดใหญ่
*   **Schema**: โครงสร้างข้อมูลที่กำหนดไว้
*   **Extraction**: การสกัดข้อมูลจากเอกสาร
*   **Compliance**: การตรวจสอบความสอดคล้องตามกฎเกณฑ์
*   **Webhook**: การส่งข้อมูลไปยัง URL อื่นผ่าน HTTP

### 16.2 References
*   Cult UI Documentation: https://www.cult-ui.com/docs
*   FastAPI Documentation: https://fastapi.tiangolo.com
*   Next.js Documentation: https://nextjs.org/docs
*   shadcn/ui: https://ui.shadcn.com

---
**Document Version**: 1.0
**Last Updated**: 2025-01-29
**Prepared By**: Rujirapong
**Status**: Draft for Review
