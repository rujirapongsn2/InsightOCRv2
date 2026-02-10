# Integration Configuration Storage

## 📍 ที่เก็บข้อมูล Integration Configuration

### **ตอบสั้นๆ:**
ค่า config ของ Integration ถูกบันทึกใน **Browser localStorage** ของผู้ใช้แต่ละคน

---

## 🔍 รายละเอียดการจัดเก็บข้อมูล

### 1. **Storage Location: Browser localStorage**

**Key:** `"integrations"`

**ไฟล์ที่เกี่ยวข้อง:**
- `frontend/app/(dashboard)/integrations/page.tsx` (จัดการ CRUD)
- `frontend/app/(dashboard)/jobs/[id]/page.tsx` (อ่านค่าเพื่อส่งข้อมูล)

**โครงสร้างข้อมูล:**
```typescript
interface Integration {
    id: string                      // Unique ID (เช่น "int-api-1")
    name: string                    // ชื่อ Integration
    type: "api" | "workflow" | "llm"  // ประเภท
    description: string             // คำอธิบาย
    status: "active" | "paused"     // สถานะ
    updatedAt: string               // วันที่อัพเดทล่าสุด
    config: IntegrationConfig       // Configuration (ดูรายละเอียดด้านล่าง)
}

interface IntegrationConfig {
    // สำหรับ type: "api"
    method?: "POST" | "PUT"
    endpoint?: string
    authHeader?: string
    headersJson?: string
    payloadTemplate?: string

    // สำหรับ type: "workflow"
    webhookUrl?: string
    parameters?: string

    // สำหรับ type: "llm"
    model?: string
    apiKey?: string
    baseUrl?: string
    instructions?: string
    reasoningEffort?: "low" | "medium" | "high"
}
```

---

## 📂 การทำงานของระบบ

### **1. การบันทึกข้อมูล (Create/Update)**

**ไฟล์:** `frontend/app/(dashboard)/integrations/page.tsx`

```typescript
// บรรทัด 154-159
const persistIntegrations = (items: Integration[]) => {
    setIntegrations(items)
    if (typeof window !== "undefined") {
        localStorage.setItem("integrations", JSON.stringify(items))
    }
}
```

**ขั้นตอน:**
1. ผู้ใช้สร้างหรือแก้ไข Integration ผ่านหน้า Integrations
2. กด Save
3. ข้อมูลถูกแปลงเป็น JSON
4. บันทึกลง localStorage ด้วย key `"integrations"`

---

### **2. การอ่านข้อมูล (Read)**

**ไฟล์:** `frontend/app/(dashboard)/integrations/page.tsx`

```typescript
// บรรทัด 140-152
useEffect(() => {
    if (typeof window === "undefined") return
    const stored = localStorage.getItem("integrations")
    if (stored) {
        try {
            setIntegrations(JSON.parse(stored))
            return
        } catch {
            // ignore parse error and fall back to seeds
        }
    }
    setIntegrations(seedIntegrations)  // ใช้ค่า default ถ้าไม่มี
}, [])
```

**ขั้นตอน:**
1. เมื่อโหลดหน้า Integrations หรือ Job Detail
2. อ่านค่าจาก localStorage key `"integrations"`
3. Parse JSON เป็น object
4. ถ้าไม่มีข้อมูล → ใช้ `seedIntegrations` (ค่า default)

---

### **3. การใช้งานในหน้า Job Detail**

**ไฟล์:** `frontend/app/(dashboard)/jobs/[id]/page.tsx`

```typescript
// บรรทัด 112-149
const loadIntegrations = () => {
    if (typeof window === "undefined") return
    const stored = localStorage.getItem("integrations")
    if (stored) {
        try {
            const parsed = JSON.parse(stored) as Integration[]
            // โหลดเฉพาะ integration ที่ status = "active"
            setIntegrations(parsed.filter(int => int.status === "active"))
            return
        } catch {
            // fall through to seeds
        }
    }
    setIntegrations(seeds.filter(int => int.status === "active"))
}
```

**ขั้นตอน:**
1. โหลดเฉพาะ integrations ที่มีสถานะ `active`
2. แสดงใน dropdown เพื่อให้ผู้ใช้เลือก
3. เมื่อเลือกแล้วกด "Send" → ใช้ config จาก localStorage ส่งไปยัง API

---

## 💾 ข้อมูลที่เก็บใน localStorage

### **ตัวอย่างข้อมูลจริง:**

```json
[
  {
    "id": "int-api-1",
    "name": "Core API",
    "type": "api",
    "description": "Push OCR results into the internal ERP via API",
    "status": "active",
    "updatedAt": "2025-01-10T10:00:00Z",
    "config": {
      "method": "POST",
      "endpoint": "https://api.internal.example.com/erp/import",
      "authHeader": "Bearer <service-token>",
      "payloadTemplate": "{\"document_id\":\"<uuid>\",\"file_url\":\"<signed-url>\"}"
    }
  },
  {
    "id": "int-workflow-1",
    "name": "N8N Automation",
    "type": "workflow",
    "description": "Trigger a webhook to N8N",
    "status": "active",
    "updatedAt": "2025-01-08T08:30:00Z",
    "config": {
      "webhookUrl": "https://n8n.example.com/webhook/ocr-finish",
      "parameters": "jobId, status, fileUrl, payload, confidence"
    }
  },
  {
    "id": "int-llm-1",
    "name": "LLM Validation",
    "type": "llm",
    "description": "Send extracted text to an LLM",
    "status": "active",
    "updatedAt": "2025-01-05T12:15:00Z",
    "config": {
      "model": "gpt-4.1-mini",
      "apiKey": "sk-xxxxxxxxxxxxx",
      "baseUrl": "https://api.openai.com/v1",
      "instructions": "Validate extracted fields",
      "reasoningEffort": "low"
    }
  }
]
```

---

## 🔐 ข้อควรระวังด้านความปลอดภัย

### ⚠️ **ปัญหาความปลอดภัย**

1. **API Keys/Tokens ถูกเก็บใน localStorage**
   - localStorage ไม่มีการ encrypt
   - สามารถอ่านได้ง่ายผ่าน Browser DevTools
   - ถ้ามี XSS vulnerability → API keys อาจถูกขโมย

2. **ข้อมูลเป็นแบบ Per-User**
   - แต่ละผู้ใช้ต้องตั้งค่า Integration เอง
   - ไม่มีการแชร์ config ระหว่างผู้ใช้
   - Admin ตั้งค่าแล้ว → User คนอื่นไม่เห็น

3. **ไม่มี Backup**
   - ถ้าลบ browser cache → ข้อมูลหายหมด
   - ไม่มีการ sync กับ server

---

## ✅ แนะนำการปรับปรุงความปลอดภัย

### **Option 1: เก็บใน Database (แนะนำสูงสุด)**

**สร้าง Backend Model:**

```python
# backend/app/models/integration.py
from sqlalchemy import Column, String, JSON, Enum
from app.db.base_class import Base
import uuid

class Integration(Base):
    __tablename__ = "integrations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    type = Column(Enum("api", "workflow", "llm"), nullable=False)
    description = Column(String)
    status = Column(Enum("active", "paused"), default="active")
    config = Column(JSON)  # เก็บ config เป็น JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="integrations")
```

**ข้อดี:**
- ✅ API keys ถูกเก็บในฝั่ง server (ปลอดภัยกว่า)
- ✅ สามารถ encrypt sensitive fields ได้
- ✅ มี backup และ recovery
- ✅ Admin สามารถสร้าง shared integrations ได้

**ข้อเสีย:**
- ❌ ต้องเขียน API endpoints เพิ่ม (CRUD)
- ❌ ต้องทำ database migration

---

### **Option 2: Encrypt ใน localStorage**

**ใช้ Web Crypto API:**

```typescript
// utils/encryption.ts
async function encryptData(data: any, key: string): Promise<string> {
    const encoder = new TextEncoder()
    const data_encoded = encoder.encode(JSON.stringify(data))

    const keyMaterial = await window.crypto.subtle.importKey(
        "raw",
        encoder.encode(key),
        { name: "AES-GCM" },
        false,
        ["encrypt"]
    )

    const iv = window.crypto.getRandomValues(new Uint8Array(12))
    const encrypted = await window.crypto.subtle.encrypt(
        { name: "AES-GCM", iv },
        keyMaterial,
        data_encoded
    )

    return btoa(String.fromCharCode(...new Uint8Array(encrypted)))
}

// การใช้งาน
const encryptedData = await encryptData(integrations, userPassword)
localStorage.setItem("integrations", encryptedData)
```

**ข้อดี:**
- ✅ ปลอดภัยกว่า plain text
- ✅ ไม่ต้องแก้ backend

**ข้อเสีย:**
- ❌ ยังคงมีความเสี่ยงจาก XSS
- ❌ ต้องจัดการ encryption key

---

### **Option 3: ใช้ Backend Secret Store**

**เก็บเฉพาะ sensitive data ใน backend:**

```typescript
// Frontend - เก็บเฉพาะ non-sensitive
const integrationPublic = {
    id: integration.id,
    name: integration.name,
    type: integration.type,
    config: {
        endpoint: integration.config.endpoint,
        // ไม่เก็บ apiKey, authHeader
    }
}

// Backend - เก็บ secrets
POST /api/v1/integration-secrets
{
    "integration_id": "int-llm-1",
    "apiKey": "sk-xxxxx",
    "authHeader": "Bearer token"
}
```

**ข้อดี:**
- ✅ Sensitive data ไม่ถูกเก็บใน browser
- ✅ ปลอดภัยสูง
- ✅ ยังคงใช้ localStorage สำหรับ UI config

**ข้อเสีย:**
- ❌ ต้องแก้ทั้ง frontend และ backend

---

## 🎯 สรุป

### **ปัจจุบัน:**
- ✅ เก็บใน **Browser localStorage** (key: `"integrations"`)
- ✅ Format: JSON array of Integration objects
- ✅ Per-user storage (ไม่ share ระหว่างผู้ใช้)
- ⚠️ ไม่มีการ encrypt (ความเสี่ยงด้านความปลอดภัย)
- ⚠️ ไม่มี backup (ถ้าลบ cache → หาย)

### **แนะนำสำหรับ Production:**
1. **เก็บใน Database** พร้อม encrypt sensitive fields
2. **ใช้ Backend Secret Store** สำหรับ API keys
3. **เพิ่ม Audit Log** สำหรับ integration configuration changes
4. **Implement Backup/Restore** mechanism

---

## 📍 ดูข้อมูลจริงใน Browser

### **วิธีตรวจสอบ:**

1. เปิด Browser DevTools (F12)
2. ไปที่ tab **Application** (Chrome) หรือ **Storage** (Firefox)
3. เลือก **Local Storage** → `https://localhost`
4. หา key `"integrations"`
5. จะเห็นข้อมูล JSON ทั้งหมด

### **วิธีแก้ไข (Manual):**

```javascript
// อ่านข้อมูล
const integrations = JSON.parse(localStorage.getItem("integrations"))

// แก้ไข
integrations[0].config.apiKey = "new-api-key"

// บันทึก
localStorage.setItem("integrations", JSON.stringify(integrations))
```

---

**Last Updated:** 2025-12-22
