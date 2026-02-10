# API Integration Test Script

Webhook receiver สำหรับทดสอบ Integration Type API

## 📋 Installation

```bash
# ติดตั้ง dependencies
pip3 install -r requirements.txt

# หรือติดตั้งแบบ manual
pip3 install Flask Flask-CORS
```

## 🚀 Usage

### 1. เริ่ม Webhook Server

```bash
# เริ่ม server (default: localhost:5000)
python3 api-test.py

# กำหนด port
python3 api-test.py --port 8080

# เปิดให้เข้าถึงจาก network อื่นได้
python3 api-test.py --host 0.0.0.0 --port 8080

# เปิด debug mode
python3 api-test.py --debug
```

### 2. ตั้งค่า Integration ใน InsightDOC

1. เปิด InsightDOC → ไปที่หน้า **Integration**
2. คลิก **Add Integration**
3. กรอกข้อมูล:
   - **Name**: Test API Integration
   - **Type**: API
   - **Status**: Active
   - **HTTP Method**: POST
   - **Endpoint URL**: `http://localhost:5000/webhook`
   - **Authorization / Headers** (Optional):
     ```
     Authorization: Bearer test-token-123
     X-Custom-Header: custom-value
     ```
   - **Headers (JSON)** (Optional):
     ```json
     {
       "X-API-Key": "test-key-456"
     }
     ```
4. คลิก **Save changes**

### 3. ทดสอบการส่งข้อมูล

1. ไปที่หน้า **Jobs**
2. เลือก Job ที่มี documents ที่ reviewed แล้ว
3. คลิก **Send to Integration**
4. เลือก integration ที่สร้างไว้
5. คลิก **Send**

### 4. ตรวจสอบผลลัพธ์

ดูที่ Terminal ที่รัน `api-test.py` จะเห็น:
- Headers ที่ได้รับ
- Payload (job data และ documents)
- Response status

## 📍 Available Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST/PUT | `/webhook` | รับข้อมูลจาก Integration |
| GET | `/webhook/test` | ทดสอบว่า server ทำงาน |
| GET | `/webhook/history` | ดู history ของ requests ที่ได้รับ |
| POST | `/webhook/clear` | ลบ history |

## 📦 Payload Structure

ระบบจะส่งข้อมูลในรูปแบบ:

```json
{
  "job_id": "job-uuid",
  "job_name": "Invoice Processing",
  "documents": [
    {
      "id": "doc-uuid",
      "filename": "invoice.pdf",
      "schema_id": "schema-uuid",
      "status": "reviewed",
      "data": {
        "invoice_no": "INV-001",
        "date": "2025-12-20",
        "total": 1250.50
      }
    }
  ]
}
```

## 🔧 Examples

### ดู History ของ requests ที่ได้รับ

```bash
curl http://localhost:5000/webhook/history
```

### ทดสอบว่า server ทำงาน

```bash
curl http://localhost:5000/webhook/test
```

### ลบ history

```bash
curl -X POST http://localhost:5000/webhook/clear
```

### ทดสอบส่งข้อมูลด้วย curl

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-token" \
  -d '{
    "job_id": "test-001",
    "job_name": "Test Job",
    "documents": [
      {
        "id": "doc-001",
        "filename": "test.pdf",
        "status": "reviewed",
        "data": {"test": "data"}
      }
    ]
  }'
```

## 💡 Tips

- เปิด Terminal แยกหน้าต่างเพื่อดู output ได้ชัดเจน
- ใช้ `--debug` เพื่อดู detailed logs
- กด `Ctrl+C` เพื่อหยุด server
- ใช้ `/webhook/history` เพื่อ review requests ที่ได้รับทั้งหมด

## 🐛 Troubleshooting

### Port already in use
```bash
# เปลี่ยน port
python3 api-test.py --port 8080
```

### Cannot access from Docker
```bash
# ใช้ host 0.0.0.0 แทน 127.0.0.1
python3 api-test.py --host 0.0.0.0
```

### Flask not installed
```bash
pip3 install -r requirements.txt
```
