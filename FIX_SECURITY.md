# 🔒 แผนการแก้ไขปัญหาความปลอดภัย - InsightOCR v2

> **สร้างเมื่อ:** 23 ธันวาคม 2568
> **อัปเดตล่าสุด:** 23 ธันวาคม 2568 เวลา 20:35 น.
> **สถานะ:** ✅ Phase 1 เสร็จสมบูรณ์ (5/10 ข้อ) | 🚧 Phase 2-4 รอดำเนินการ
> **วัตถุประสงค์:** แก้ไขช่องโหว่ด้านความปลอดภัยตามลำดับความง่ายและผลกระทบ

---

## 🎉 สรุปผลการดำเนินการ

### ✅ Phase 1: สำเร็จครบ 100% (23 ธันวาคม 2568)

**เวลาที่ใช้:** ~25 นาที | **ข้อที่แก้ไข:** 5 ข้อ (รวม Bonus จาก Phase 2)

#### ผลลัพธ์:
1. ✅ **Fix #1**: .env Files ได้รับการป้องกัน (อยู่ใน .gitignore แล้ว)
2. ✅ **Fix #2**: MinIO Credentials เปลี่ยนเป็น strong random credentials
3. ✅ **Fix #3**: PostgreSQL Password เปลี่ยนเป็น strong credentials + user ใหม่ (`insightocr_user`)
4. ✅ **Fix #4**: SECRET_KEY สร้างใหม่ (⚠️ ผู้ใช้ต้อง login ใหม่)
5. ✅ **Fix #5 (Bonus)**: Redis Authentication เพิ่ม password protection

#### ไฟล์ที่ถูกแก้ไข:
- ✅ `docker-compose.yml` - ใช้ environment variables
- ✅ `backend/.env` - อัปเดต credentials ทั้งหมด
- ✅ `backend/app/core/config.py` - เพิ่ม fields ใหม่
- ✅ `.env` (root) - สร้างใหม่สำหรับ docker-compose

#### ไฟล์ Backup:
- ✅ `docker-compose.yml.backup`
- ✅ `backend/.env.backup`
- ✅ `backup_db_*.sql`

#### ผลการทดสอบ:
| Service | Status | Result |
|---------|--------|--------|
| PostgreSQL | 🟢 | Connected as `insightocr_user` |
| Redis | 🟢 | Authentication working (PONG) |
| MinIO | 🟢 | New credentials working |
| Backend | 🟢 | Application startup complete |
| Celery | 🟢 | Worker ready |

---

## 📊 เกณฑ์การประเมิน

| เกณฑ์ | คำอธิบาย |
|-------|----------|
| **ระดับความง่าย** | 1 (ง่ายมาก) ถึง 5 (ยากมาก) |
| **ผลกระทบ** | 1 (น้อย) ถึง 5 (สูงมาก) |
| **Priority Score** | ผลกระทบ × (6 - ความง่าย) = คะแนนลำดับความสำคัญ |

---

## 🎯 สรุปภาพรวม

| # | หัวข้อ | ความง่าย | ผลกระทบ | Priority | เวลาใช้จริง | สถานะ |
|---|--------|---------|---------|----------|-------------|--------|
| 1 | เพิ่ม .env ลง .gitignore | ⭐ (1) | 🔥🔥🔥🔥🔥 (5) | 25 | - | ✅ เสร็จแล้ว (อยู่ใน .gitignore แล้ว) |
| 2 | เปลี่ยน MinIO Credentials | ⭐ (1) | 🔥🔥🔥🔥🔥 (5) | 25 | 5 นาที | ✅ เสร็จแล้ว (23 ธ.ค. 68) |
| 3 | เปลี่ยน PostgreSQL Password | ⭐ (1) | 🔥🔥🔥🔥🔥 (5) | 25 | 5 นาที | ✅ เสร็จแล้ว (23 ธ.ค. 68) |
| 4 | สร้าง SECRET_KEY ใหม่ | ⭐ (1) | 🔥🔥🔥🔥 (4) | 20 | 3 นาที | ✅ เสร็จแล้ว (23 ธ.ค. 68) |
| 5 | เพิ่ม Redis Authentication | ⭐⭐ (2) | 🔥🔥🔥🔥🔥 (5) | 20 | 10 นาที | ✅ เสร็จแล้ว (23 ธ.ค. 68) |
| 6 | ตั้งค่า Network Isolation | ⭐⭐ (2) | 🔥🔥🔥 (3) | 12 | - | ⏳ รอดำเนินการ |
| 7 | จำกัด Healthcheck Information | ⭐⭐ (2) | 🔥🔥 (2) | 8 | - | ⏳ รอดำเนินการ |
| 8 | เพิ่ม Container Security Options | ⭐⭐⭐ (3) | 🔥🔥🔥 (3) | 9 | - | ⏳ รอดำเนินการ |
| 9 | ตั้งค่า Rate Limiting ใน Nginx | ⭐⭐⭐ (3) | 🔥🔥🔥🔥 (4) | 12 | - | ⏳ รอดำเนินการ |
| 10 | แก้ไข Volume Mounting (Production) | ⭐⭐⭐⭐ (4) | 🔥🔥🔥🔥 (4) | 8 | - | ⏳ รอดำเนินการ |

**ความคืบหน้า:** 5/10 ข้อเสร็จสมบูรณ์ (50%)
**เวลาที่ใช้ไป:** ~25 นาที | **เวลาที่เหลือโดยประมาณ:** 1.5-2 ชั่วโมง

---

# 🔧 แผนการแก้ไขแบบละเอียด

---

## ✅ Phase 1: Quick Wins (15 นาที) - ✅ เสร็จสมบูรณ์

### ✅ Fix #1: เพิ่ม .env ลงใน .gitignore (เสร็จแล้ว)

**ระดับความง่าย:** ⭐ (1/5)
**ผลกระทบ:** 🔥🔥🔥🔥🔥 (5/5) - ป้องกันการรั่วไหลของ credentials
**Priority Score:** 25
**เวลา:** - (อยู่ใน .gitignore แล้ว)
**สถานะ:** ✅ เสร็จสมบูรณ์
**ดำเนินการเมื่อ:** 23 ธันวาคม 2568

#### 🔍 ปัญหา
ไฟล์ `.env` มี sensitive data แต่อาจถูก commit ลง git repository

#### 📝 ขั้นตอน

1. **ตรวจสอบว่า .env ถูก ignore หรือยัง:**
```bash
git check-ignore backend/.env frontend/.env.local
```

2. **เพิ่มลงใน .gitignore:**
```bash
# เพิ่มที่ท้ายไฟล์ .gitignore
cat >> .gitignore << 'EOF'

# Environment files with secrets
backend/.env
frontend/.env.local
.env
*.env
!.env.example
EOF
```

3. **ลบ .env ออกจาก git history (ถ้ามีอยู่แล้ว):**
```bash
# ⚠️ ระวัง: คำสั่งนี้จะ rewrite history
git rm --cached backend/.env frontend/.env.local
git commit -m "security: Remove .env files from repository"
```

4. **สร้าง .env.example แทน:**
```bash
# Copy and remove sensitive values
cp backend/.env backend/.env.example
cp frontend/.env.local frontend/.env.local.example

# แก้ไข .env.example ให้มีแต่ template
# เช่น: SECRET_KEY=<generate-your-secret-key>
```

#### ✅ การตรวจสอบ
```bash
# ควรได้ผลลัพธ์ว่า ignored
git check-ignore backend/.env
```

---

### ✅ Fix #2: เปลี่ยน MinIO Credentials (เสร็จแล้ว)

**ระดับความง่าย:** ⭐ (1/5)
**ผลกระทบ:** 🔥🔥🔥🔥🔥 (5/5) - ป้องกันการเข้าถึงไฟล์เอกสารทั้งหมด
**Priority Score:** 25
**เวลา:** 5 นาที
**สถานะ:** ✅ เสร็จสมบูรณ์
**ดำเนินการเมื่อ:** 23 ธันวาคม 2568

**Credentials ใหม่:**
```bash
MINIO_ROOT_USER=38a5f852b5171765a2ab
MINIO_ROOT_PASSWORD=61f46460a80ae4e321e4583392e26912a33743c5
```

**ผลการทดสอบ:** ✅ MinIO เชื่อมต่อสำเร็จด้วย credentials ใหม่

#### 🔍 ปัญหา
MinIO ใช้ credentials เริ่มต้น `minioadmin/minioadmin`

#### 📝 ขั้นตอน

1. **สร้าง Strong Credentials:**
```bash
# สร้าง random access key (20 chars)
MINIO_ROOT_USER=$(openssl rand -hex 10)

# สร้าง random secret key (40 chars)
MINIO_ROOT_PASSWORD=$(openssl rand -hex 20)

echo "MINIO_ROOT_USER=${MINIO_ROOT_USER}"
echo "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}"
```

2. **อัปเดต docker-compose.yml:**
```yaml
# docker-compose.yml
minio:
  image: minio/minio
  container_name: softnix_ocr_minio
  environment:
    # ❌ ลบบรรทัดเก่า:
    # - MINIO_ROOT_USER=minioadmin
    # - MINIO_ROOT_PASSWORD=minioadmin

    # ✅ ใช้ environment variables:
    - MINIO_ROOT_USER=${MINIO_ROOT_USER}
    - MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
  # ... rest of config
```

3. **อัปเดต backend/.env:**
```bash
# backend/.env
STORAGE_TYPE=minio
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=${MINIO_ROOT_USER}      # ใช้ค่าเดียวกับ MINIO_ROOT_USER
MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD}  # ใช้ค่าเดียวกับ MINIO_ROOT_PASSWORD
MINIO_BUCKET=insightocr
MINIO_SECURE=False
```

4. **สร้าง .env หลักสำหรับ docker-compose:**
```bash
# สร้าง .env ในระดับ root (ถ้ายังไม่มี)
cat > .env << EOF
# MinIO Credentials
MINIO_ROOT_USER=${MINIO_ROOT_USER}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
EOF

# เพิ่มลงใน .gitignore
echo ".env" >> .gitignore
```

5. **Restart MinIO:**
```bash
docker compose down minio
docker compose up -d minio

# รอ MinIO startup
sleep 5
```

6. **Restart Backend และ Celery:**
```bash
docker compose restart backend celery_worker
```

#### ✅ การตรวจสอบ
```bash
# ทดสอบ connection
docker compose exec backend python -c "
from app.services.storage import get_storage_service
storage = get_storage_service()
print('✅ MinIO connection successful!' if storage.exists('documents/test/first-file.txt') else '❌ Connection failed')
"
```

---

### ✅ Fix #3: เปลี่ยน PostgreSQL Password (เสร็จแล้ว)

**ระดับความง่าย:** ⭐ (1/5)
**ผลกระทบ:** 🔥🔥🔥🔥🔥 (5/5) - ป้องกันการเข้าถึง database
**Priority Score:** 25
**เวลา:** 5 นาที
**สถานะ:** ✅ เสร็จสมบูรณ์
**ดำเนินการเมื่อ:** 23 ธันวาคม 2568

**Credentials ใหม่:**
```bash
DB_USER=insightocr_user
DB_PASSWORD=QpcoGzeKPksquFiJ5PuSRSmdpb7XiNCa
```

**ผลการทดสอบ:** ✅ Database เชื่อมต่อสำเร็จในฐานะ `insightocr_user`
**Database Backup:** ✅ สำรองและ restore สำเร็จ

#### 🔍 ปัญหา
PostgreSQL ใช้ password เริ่มต้น `postgres/postgres`

#### 📝 ขั้นตอน

1. **สร้าง Strong Password:**
```bash
# สร้าง random password (32 chars)
DB_PASSWORD=$(openssl rand -base64 32 | tr -d '=+/')
DB_USER="insightocr_user"

echo "DB_USER=${DB_USER}"
echo "DB_PASSWORD=${DB_PASSWORD}"
```

2. **อัปเดต docker-compose.yml:**
```yaml
# docker-compose.yml
db:
  image: postgres:15-alpine
  container_name: softnix_ocr_db
  environment:
    # ✅ ใช้ environment variables:
    - POSTGRES_USER=${DB_USER:-postgres}
    - POSTGRES_PASSWORD=${DB_PASSWORD}
    - POSTGRES_DB=softnix_ocr
  # ... rest of config
```

3. **อัปเดต .env (root level):**
```bash
# เพิ่มใน .env
cat >> .env << EOF

# PostgreSQL Credentials
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
EOF
```

4. **อัปเดต backend/.env:**
```bash
# backend/.env
# ❌ ลบบรรทัดเก่า:
# DATABASE_URL=postgresql://postgres:postgres@db:5432/softnix_ocr

# ✅ ใช้ environment variables:
# เพิ่ม DB_USER และ DB_PASSWORD ใน backend/.env
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@db:5432/softnix_ocr
```

5. **⚠️ สำคัญ: Backup Database ก่อน:**
```bash
docker compose exec db pg_dump -U postgres softnix_ocr > backup_$(date +%Y%m%d_%H%M%S).sql
```

6. **Recreate Database Container:**
```bash
# หยุดทุก service
docker compose down

# ลบ volume เก่า (⚠️ ข้อมูลจะหายไปหมด!)
# ถ้าต้องการเก็บข้อมูล ให้ restore จาก backup หลังจากนี้
docker volume rm insightocr_postgres_data

# Start ใหม่
docker compose up -d db

# รอ database พร้อม
sleep 10

# Restore จาก backup (ถ้ามี)
cat backup_*.sql | docker compose exec -T db psql -U ${DB_USER} -d softnix_ocr
```

7. **Start Services ทั้งหมด:**
```bash
docker compose up -d
```

#### ✅ การตรวจสอบ
```bash
# ทดสอบ connection
docker compose exec backend python -c "
from app.db.session import SessionLocal
db = SessionLocal()
try:
    db.execute('SELECT 1')
    print('✅ Database connection successful!')
except Exception as e:
    print(f'❌ Connection failed: {e}')
finally:
    db.close()
"
```

---

### ✅ Fix #4: สร้าง SECRET_KEY ใหม่ (เสร็จแล้ว)

**ระดับความง่าย:** ⭐ (1/5)
**ผลกระทบ:** 🔥🔥🔥🔥 (4/5) - ป้องกัน JWT token forgery
**Priority Score:** 20
**เวลา:** 3 นาที
**สถานะ:** ✅ เสร็จสมบูรณ์
**ดำเนินการเมื่อ:** 23 ธันวาคม 2568

**SECRET_KEY ใหม่:**
```bash
SECRET_KEY=yh77Io1WzjzvvVKd6PCWWcJyZw1nOqa_14vnLlgaVGc
```

**ผลกระทบ:**
- ⚠️ JWT tokens เดิมทั้งหมด invalid
- 👤 ผู้ใช้ทุกคนต้อง login ใหม่

**ผลการทดสอบ:** ✅ Backend เริ่มต้นสำเร็จด้วย SECRET_KEY ใหม่

#### 🔍 ปัญหา
SECRET_KEY ถูก hardcode และอาจถูกเปิดเผยใน repository

#### 📝 ขั้นตอน

1. **สร้าง SECRET_KEY ใหม่:**
```bash
# วิธีที่ 1: ใช้ Python secrets (แนะนำ)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# วิธีที่ 2: ใช้ OpenSSL
openssl rand -base64 32

# เก็บผลลัพธ์ไว้
NEW_SECRET_KEY="<paste-result-here>"
```

2. **อัปเดต backend/.env:**
```bash
# แก้ไขไฟล์ backend/.env
# ❌ ลบบรรทัดเก่า:
# SECRET_KEY=e03oPvNjGWnO-2PoPSkOB5GQvSjMunE2DiAUvlja6a0

# ✅ ใช้ค่าใหม่:
SECRET_KEY=<paste-your-new-secret-key>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

3. **⚠️ หมายเหตุสำคัญ:**
```
การเปลี่ยน SECRET_KEY จะทำให้:
- JWT tokens ทั้งหมดที่ออกไปแล้ว invalid
- ผู้ใช้ทุกคนต้อง login ใหม่

แนะนำให้ทำในช่วงที่มีผู้ใช้น้อย
```

4. **Restart Backend:**
```bash
docker compose restart backend celery_worker
```

#### ✅ การตรวจสอบ
```bash
# ตรวจสอบว่า backend start ได้
docker compose logs backend --tail 20

# ควรเห็น "Application startup complete"
```

---

## ⚡ Phase 2: Critical Fixes (30 นาที) - ✅ Fix #5 เสร็จแล้ว | ⏳ Fix #6 รอดำเนินการ

### ✅ Fix #5: เพิ่ม Redis Authentication (เสร็จแล้ว)

**ระดับความง่าย:** ⭐⭐ (2/5)
**ผลกระทบ:** 🔥🔥🔥🔥🔥 (5/5) - ป้องกัน unauthorized access
**Priority Score:** 20
**เวลา:** 10 นาที
**สถานะ:** ✅ เสร็จสมบูรณ์ (Bonus จาก Phase 1!)
**ดำเนินการเมื่อ:** 23 ธันวาคม 2568

**Redis Password:**
```bash
REDIS_PASSWORD=NWDcfgfn1zZs6VQnBEKnL601mDSncKf5
```

**การอัปเดต:**
- ✅ เพิ่ม `command: redis-server --requirepass ${REDIS_PASSWORD}` ใน docker-compose.yml
- ✅ อัปเดต `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0` ใน backend/.env
- ✅ เพิ่ม `REDIS_PASSWORD` field ใน config.py

**ผลการทดสอบ:** ✅ Redis ตอบกลับ PONG ด้วย authentication

#### 🔍 ปัญหา
Redis ไม่มีการตั้งรหัสผ่าน

#### 📝 ขั้นตอน

1. **สร้าง Redis Password:**
```bash
REDIS_PASSWORD=$(openssl rand -base64 32 | tr -d '=+/')
echo "REDIS_PASSWORD=${REDIS_PASSWORD}"
```

2. **อัปเดต docker-compose.yml:**
```yaml
# docker-compose.yml
redis:
  image: redis:7-alpine
  container_name: softnix_ocr_redis
  # ✅ เพิ่ม command และ environment:
  command: redis-server --requirepass ${REDIS_PASSWORD}
  environment:
    - REDIS_PASSWORD=${REDIS_PASSWORD}
  expose:
    - "6379"
  # ... rest of config
```

3. **อัปเดต .env (root level):**
```bash
# เพิ่มใน .env
cat >> .env << EOF

# Redis Password
REDIS_PASSWORD=${REDIS_PASSWORD}
EOF
```

4. **อัปเดต backend/.env:**
```bash
# backend/.env
# ❌ ลบบรรทัดเก่า:
# REDIS_URL=redis://redis:6379/0

# ✅ เพิ่ม password ใน URL:
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
```

5. **Restart Redis และ Services:**
```bash
docker compose down redis celery_worker backend
docker compose up -d redis
sleep 5
docker compose up -d backend celery_worker
```

#### ✅ การตรวจสอบ
```bash
# ทดสอบว่าต้องใช้ password
docker compose exec redis redis-cli ping
# ควรได้ "NOAUTH Authentication required"

# ทดสอบด้วย password
docker compose exec redis redis-cli -a ${REDIS_PASSWORD} ping
# ควรได้ "PONG"

# ตรวจสอบ Celery worker
docker compose logs celery_worker --tail 20
# ควรเห็น "celery@<hostname> ready"
```

---

### 🎯 Fix #6: ตั้งค่า Network Isolation

**ระดับความง่าย:** ⭐⭐ (2/5)
**ผลกระทบ:** 🔥🔥🔥 (3/5) - จำกัดการเข้าถึงจาก external
**Priority Score:** 12
**เวลา:** 5 นาที

#### 🔍 ปัญหา
Internal network อนุญาตให้ containers เชื่อมต่อ internet ได้

#### 📝 ขั้นตอน

1. **อัปเดต docker-compose.yml:**
```yaml
# docker-compose.yml
networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    # ✅ เปลี่ยนเป็น true สำหรับ production:
    internal: true  # ป้องกันการเชื่อมต่อ external network
```

2. **⚠️ หมายเหตุสำคัญ:**
```
การตั้ง internal: true จะทำให้:
- Services ใน internal network ไม่สามารถ download packages จาก internet ได้
- ไม่สามารถเรียก external APIs ได้ (เช่น OCR service)

✅ แนะนำ:
- Development: ใช้ internal: false
- Production: ใช้ internal: true และย้าย external API calls ไปที่ proxy/gateway
```

3. **สำหรับ Production - สร้าง API Gateway:**
```yaml
# เพิ่ม gateway service สำหรับเรียก external APIs
gateway:
  image: nginx:alpine
  container_name: api_gateway
  networks:
    - public    # เชื่อมต่อ internet ได้
    - internal  # เชื่อมต่อกับ backend services
  # Configure as reverse proxy to external APIs
```

4. **Restart Network:**
```bash
# Development mode - ไม่ต้องเปลี่ยน
# Production mode - recreate network
docker compose down
docker compose up -d
```

#### ✅ การตรวจสอบ
```bash
# ทดสอบว่า internal network ถูก isolate
docker compose exec backend ping -c 3 8.8.8.8
# ถ้า internal: true -> ควรได้ "Network unreachable"
# ถ้า internal: false -> ควรได้ response ปกติ
```

---

## 🔐 Phase 3: Enhanced Security (1 ชั่วโมง)

### 🎯 Fix #7: จำกัด Healthcheck Information Disclosure

**ระดับความง่าย:** ⭐⭐ (2/5)
**ผลกระทบ:** 🔥🔥 (2/5) - ป้องกัน information leakage
**Priority Score:** 8
**เวลา:** 15 นาที

#### 🔍 ปัญหา
Healthcheck endpoint อาจเปิดเผยข้อมูล version และ dependencies

#### 📝 ขั้นตอน

1. **สร้าง Simple Health Endpoint:**

สร้างไฟล์ `backend/app/api/v1/endpoints/health.py`:
```python
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/health", include_in_schema=False)
async def health_check():
    """
    Simple health check endpoint.
    Returns minimal information for security.
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok"}  # ไม่เปิดเผยข้อมูลอื่น
    )

@router.get("/health/detailed")
async def detailed_health_check(
    # TODO: เพิ่ม authentication dependency
):
    """
    Detailed health check with authentication required.
    """
    from app.db.session import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    finally:
        db.close()

    return {
        "status": "ok",
        "database": db_status,
        "version": "2.0.0",  # อาจเปิดเผยได้ถ้ามี auth
    }
```

2. **Register Router:**

แก้ไข `backend/app/main.py`:
```python
# เพิ่มใน main.py
from app.api.v1.endpoints import health

# Register health router (ไม่อยู่ใน /api/v1 prefix)
app.include_router(health.router, tags=["health"])
```

3. **อัปเดต docker-compose.yml healthcheck:**
```yaml
# docker-compose.yml - backend service
backend:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    # ใช้ /health แทน /health/detailed
    interval: 30s
    timeout: 10s
    retries: 3
```

4. **Restart Backend:**
```bash
docker compose restart backend
```

#### ✅ การตรวจสอบ
```bash
# ทดสอบ public health endpoint
curl http://localhost/health
# ควรได้: {"status":"ok"}

# ทดสอบ detailed endpoint (ต้องมี auth)
curl http://localhost/health/detailed
# ควรได้ 401 Unauthorized (ถ้าเพิ่ม auth แล้ว)
```

---

### 🎯 Fix #8: เพิ่ม Container Security Options

**ระดับความง่าย:** ⭐⭐⭐ (3/5)
**ผลกระทบ:** 🔥🔥🔥 (3/5) - ลด attack surface
**Priority Score:** 9
**เวลา:** 20 นาที

#### 🔍 ปัญหา
Containers ไม่มีการจำกัด privileges และ capabilities

#### 📝 ขั้นตอน

1. **อัปเดต docker-compose.yml - เพิ่ม Security Options:**

```yaml
# docker-compose.yml

# Backend Service
backend:
  build: ./backend
  container_name: softnix_ocr_backend

  # ✅ เพิ่ม security options:
  security_opt:
    - no-new-privileges:true  # ป้องกัน privilege escalation
  cap_drop:
    - ALL  # ลบ capabilities ทั้งหมด
  cap_add:
    - NET_BIND_SERVICE  # เพิ่มเฉพาะที่จำเป็น

  # ✅ เพิ่ม resource limits:
  deploy:
    resources:
      limits:
        cpus: '1'
        memory: 1G
      reservations:
        cpus: '0.5'
        memory: 512M

  # ถ้าไม่ต้องเขียนไฟล์ (ใช้ได้เฉพาะบางกรณี):
  # read_only: true
  # tmpfs:
  #   - /tmp
  #   - /app/uploads  # อนุญาตเฉพาะ temp directories

  expose:
    - "8000"
  # ... rest of config

# Frontend Service
frontend:
  build: ./frontend
  container_name: softnix_ocr_frontend

  security_opt:
    - no-new-privileges:true
  cap_drop:
    - ALL
  cap_add:
    - NET_BIND_SERVICE

  deploy:
    resources:
      limits:
        cpus: '0.5'
        memory: 512M

  expose:
    - "3000"
  # ... rest of config

# Nginx
nginx:
  image: nginx:1.25-alpine
  container_name: softnix_ocr_nginx

  security_opt:
    - no-new-privileges:true
  cap_drop:
    - ALL
  cap_add:
    - NET_BIND_SERVICE  # จำเป็นสำหรับ port 80/443
    - CHOWN
    - SETGID
    - SETUID

  user: "nginx:nginx"  # ไม่ run เป็น root

  ports:
    - "80:80"
    - "443:443"
  # ... rest of config

# Database
db:
  image: postgres:15-alpine
  container_name: softnix_ocr_db

  security_opt:
    - no-new-privileges:true

  deploy:
    resources:
      limits:
        cpus: '1'
        memory: 1G

  # ... rest of config
```

2. **ทดสอบการทำงาน:**
```bash
# Recreate containers
docker compose down
docker compose up -d

# ตรวจสอบว่าทุก service ทำงานได้
docker compose ps
```

3. **ตรวจสอบ Security Settings:**
```bash
# ตรวจสอบ security options
docker inspect softnix_ocr_backend | jq '.[0].HostConfig.SecurityOpt'

# ตรวจสอบ capabilities
docker inspect softnix_ocr_backend | jq '.[0].HostConfig.CapDrop'
docker inspect softnix_ocr_backend | jq '.[0].HostConfig.CapAdd'
```

#### ✅ การตรวจสอบ
```bash
# ทดสอบว่า application ยังทำงานได้
curl http://localhost/health

# ตรวจสอบ resource usage
docker stats --no-stream
```

---

### 🎯 Fix #9: ตั้งค่า Rate Limiting ใน Nginx

**ระดับความง่าย:** ⭐⭐⭐ (3/5)
**ผลกระทบ:** 🔥🔥🔥🔥 (4/5) - ป้องกัน brute force และ DDoS
**Priority Score:** 12
**เวลา:** 30 นาที

#### 🔍 ปัญหา
ไม่มี rate limiting ทำให้ถูก brute force attack ได้

#### 📝 ขั้นตอน

1. **สร้าง Rate Limiting Configuration:**

สร้างไฟล์ `nginx/conf.d/rate-limit.conf`:
```nginx
# Rate Limiting Zones
# จำกัดตาม IP address

# Zone สำหรับ API endpoints ทั่วไป
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

# Zone สำหรับ login endpoint (เข้มงวดกว่า)
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;

# Zone สำหรับ upload endpoint
limit_req_zone $binary_remote_addr zone=upload_limit:10m rate=5r/m;

# Connection limit per IP
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

# Log format สำหรับ rate limiting
log_format rate_limited '$remote_addr - $remote_user [$time_local] '
                       '"$request" $status $body_bytes_sent '
                       '"$http_referer" "$http_user_agent" '
                       'rate_limited';
```

2. **อัปเดต Nginx Config หลัก:**

แก้ไข `nginx/conf.d/default.conf` (หรือไฟล์ที่มีอยู่):
```nginx
# Backend API Proxy
location /api/ {
    # ✅ เพิ่ม rate limiting
    limit_req zone=api_limit burst=20 nodelay;
    limit_conn conn_limit 10;

    # Log requests ที่ถูก rate limit
    error_log /var/log/nginx/rate_limit.log warn;

    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Login endpoint - เข้มงวดกว่า
location /api/v1/login {
    # ✅ จำกัดเข้มงวดกว่า
    limit_req zone=login_limit burst=3 nodelay;
    limit_req_status 429;  # Return 429 Too Many Requests

    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

# Upload endpoint
location /api/v1/documents/upload {
    # ✅ จำกัด upload rate
    limit_req zone=upload_limit burst=2 nodelay;

    # เพิ่ม upload size limit
    client_max_body_size 10M;

    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    # ✅ เพิ่ม timeouts สำหรับ upload
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
}

# Frontend
location / {
    # Rate limiting น้อยกว่า API
    limit_req zone=api_limit burst=50 nodelay;

    proxy_pass http://frontend:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

3. **เพิ่ม Custom Error Page สำหรับ 429:**

สร้าง `nginx/html/429.html`:
```html
<!DOCTYPE html>
<html>
<head>
    <title>Too Many Requests</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
        h1 { color: #f44336; }
    </style>
</head>
<body>
    <h1>429 - Too Many Requests</h1>
    <p>You have exceeded the rate limit. Please try again later.</p>
    <p>กรุณารอสักครู่ก่อนลองใหม่อีกครั้ง</p>
</body>
</html>
```

อัปเดต nginx config:
```nginx
# เพิ่มใน server block
error_page 429 /429.html;
location = /429.html {
    root /usr/share/nginx/html;
    internal;
}
```

4. **อัปเดต docker-compose.yml - mount ไฟล์ใหม่:**
```yaml
nginx:
  volumes:
    - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - ./nginx/conf.d:/etc/nginx/conf.d:ro
    - ./nginx/html:/usr/share/nginx/html:ro  # ✅ เพิ่มบรรทัดนี้
    - ./nginx/ssl:/etc/nginx/ssl:ro
    - ./nginx/logs:/var/log/nginx
```

5. **ทดสอบ Nginx Config:**
```bash
# ทดสอบว่า config ถูกต้อง
docker compose exec nginx nginx -t

# ควรได้: syntax is ok, test is successful
```

6. **Reload Nginx:**
```bash
docker compose exec nginx nginx -s reload

# หรือ restart
docker compose restart nginx
```

#### ✅ การตรวจสอบ

1. **ทดสอบ Rate Limiting:**
```bash
# ทดสอบ API rate limit (ควรถูก block หลังจาก 10 requests/วินาที)
for i in {1..15}; do
  curl -w "%{http_code}\n" -o /dev/null http://localhost/api/v1/health
  sleep 0.1
done
# ควรเห็น 200 ก่อน แล้วตามด้วย 429

# ทดสอบ Login rate limit (ควรถูก block หลังจาก 5 requests/นาที)
for i in {1..7}; do
  curl -X POST -w "%{http_code}\n" -o /dev/null \
    -H "Content-Type: application/json" \
    -d '{"username":"test","password":"test"}' \
    http://localhost/api/v1/login
done
# ควรเห็น 200 หรือ 401 ก่อน 5 ครั้ง แล้วตามด้วย 429
```

2. **ตรวจสอบ Logs:**
```bash
# ดู rate limit logs
docker compose exec nginx cat /var/log/nginx/rate_limit.log

# ดู error logs
docker compose logs nginx --tail 50 | grep limiting
```

---

## 🏗️ Phase 4: Production Hardening (1-2 ชั่วโมง)

### 🎯 Fix #10: แก้ไข Volume Mounting สำหรับ Production

**ระดับความง่าย:** ⭐⭐⭐⭐ (4/5)
**ผลกระทบ:** 🔥🔥🔥🔥 (4/5) - ป้องกัน code injection
**Priority Score:** 8
**เวลา:** 1-2 ชั่วโมง

#### 🔍 ปัญหา
Volume mounting ทั้ง code directory ทำให้สามารถแก้ไขโค้ดได้ถ้า container ถูก compromise

#### 📝 ขั้นตอน

#### สำหรับ Development (ปัจจุบัน):
```yaml
# ไม่ต้องเปลี่ยน - ใช้ volume mounting เพื่อ hot reload
backend:
  volumes:
    - ./backend:/app
```

#### สำหรับ Production:

**1. สร้าง Production Dockerfile:**

สร้าง `backend/Dockerfile.prod`:
```dockerfile
# Multi-stage build for production
FROM python:3.11-slim as builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

สร้าง `frontend/Dockerfile.prod`:
```dockerfile
# Build stage
FROM node:18-alpine as builder

WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm ci --only=production

# Copy source code
COPY . .

# Build application
RUN npm run build

# Production stage
FROM node:18-alpine

WORKDIR /app

# Copy built files
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/public ./public

# Create non-root user
RUN addgroup -g 1000 appuser && \
    adduser -D -u 1000 -G appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 3000

CMD ["npm", "start"]
```

**2. สร้าง docker-compose.prod.yml:**

```yaml
# docker-compose.prod.yml
services:
  nginx:
    image: nginx:1.25-alpine
    container_name: softnix_ocr_nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      # ✅ ใช้ read-only volumes
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./nginx/html:/usr/share/nginx/html:ro
      # ✅ เฉพาะ logs เขียนได้
      - nginx_logs:/var/log/nginx
    depends_on:
      - backend
      - frontend
    networks:
      - public
      - internal
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
      - CHOWN
      - SETGID
      - SETUID

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile.prod  # ✅ ใช้ production dockerfile
    container_name: softnix_ocr_backend
    expose:
      - "8000"
    volumes:
      # ✅ ไม่ mount code directory
      # ✅ mount เฉพาะ uploads directory
      - uploads:/app/uploads
    env_file:
      - ./backend/.env.prod  # ✅ ใช้ production env
    depends_on:
      - db
      - redis
    networks:
      - internal
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G

  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile.prod
    container_name: softnix_ocr_celery
    command: celery -A app.celery_app worker --loglevel=info --concurrency=4
    volumes:
      # ✅ shared uploads directory
      - uploads:/app/uploads
    env_file:
      - ./backend/.env.prod
    depends_on:
      - db
      - redis
      - backend
    networks:
      - internal
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.prod  # ✅ ใช้ production dockerfile
    container_name: softnix_ocr_frontend
    expose:
      - "3000"
    # ✅ ไม่มี volume mounting
    env_file:
      - ./frontend/.env.prod
    depends_on:
      - backend
    networks:
      - internal
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1G

  db:
    image: postgres:15-alpine
    container_name: softnix_ocr_db
    expose:
      - "5432"
    environment:
      - POSTGRES_USER=${DB_USER}
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=softnix_ocr
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - internal
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G

  redis:
    image: redis:7-alpine
    container_name: softnix_ocr_redis
    command: redis-server --requirepass ${REDIS_PASSWORD}
    environment:
      - REDIS_PASSWORD=${REDIS_PASSWORD}
    expose:
      - "6379"
    volumes:
      - redis_data:/data
    networks:
      - internal
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true

  minio:
    image: minio/minio
    container_name: softnix_ocr_minio
    expose:
      - "9000"
      - "9001"
    environment:
      - MINIO_ROOT_USER=${MINIO_ROOT_USER}
      - MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data
    networks:
      - internal
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true  # ✅ Production ต้องเป็น true

volumes:
  postgres_data:
  minio_data:
  redis_data:  # ✅ เพิ่ม redis persistence
  uploads:     # ✅ shared uploads
  nginx_logs:  # ✅ nginx logs
```

**3. Deploy Production:**
```bash
# Build production images
docker compose -f docker-compose.prod.yml build

# Start production stack
docker compose -f docker-compose.prod.yml up -d

# ตรวจสอบสถานะ
docker compose -f docker-compose.prod.yml ps
```

#### ✅ การตรวจสอบ
```bash
# ตรวจสอบว่า volumes ไม่มี code mounting
docker compose -f docker-compose.prod.yml config | grep -A 5 volumes

# ทดสอบ application
curl http://localhost/health
```

---

## 📋 Checklist การดำเนินการ

### Phase 1: Quick Wins ✅ (เสร็จสมบูรณ์)
- [x] เพิ่ม `.env` ลง `.gitignore` ✅ (อยู่แล้ว)
- [x] เปลี่ยน MinIO credentials ✅ (23 ธ.ค. 68)
- [x] เปลี่ยน PostgreSQL password ✅ (23 ธ.ค. 68)
- [x] สร้าง SECRET_KEY ใหม่ ✅ (23 ธ.ค. 68)
- [x] Backup ข้อมูลก่อนเปลี่ยนแปลง ✅ (23 ธ.ค. 68)

### Phase 2: Critical Fixes (1/2 เสร็จ)
- [x] เพิ่ม Redis authentication ✅ (23 ธ.ค. 68 - Bonus!)
- [ ] ตั้งค่า network isolation (ระวังผลกระทบต่อ external APIs)
- [ ] ทดสอบว่า services ยังทำงานได้

### Phase 3: Enhanced Security ⏳
- [ ] จำกัด healthcheck information
- [ ] เพิ่ม container security options
- [ ] ตั้งค่า rate limiting
- [ ] ทดสอบ rate limiting ทำงาน

### Phase 4: Production Hardening ⏳
- [ ] สร้าง production Dockerfiles
- [ ] สร้าง docker-compose.prod.yml
- [ ] ทดสอบ production build
- [ ] วางแผน deployment

---

## 🔄 Rollback Plan

ถ้ามีปัญหาหลังจากแก้ไข:

### 1. Backup ก่อนเริ่ม:
```bash
# Backup docker-compose.yml
cp docker-compose.yml docker-compose.yml.backup

# Backup .env files
cp backend/.env backend/.env.backup
cp .env .env.backup

# Backup database
docker compose exec db pg_dump -U postgres softnix_ocr > backup_$(date +%Y%m%d_%H%M%S).sql
```

### 2. Restore ถ้ามีปัญหา:
```bash
# Restore configs
cp docker-compose.yml.backup docker-compose.yml
cp backend/.env.backup backend/.env
cp .env.backup .env

# Restart services
docker compose down
docker compose up -d
```

---

## 📊 ตารางติดตามความคืบหน้า

| Fix # | หัวข้อ | วันที่เริ่ม | วันที่เสร็จ | ผู้ทำ | สถานะ | หมายเหตุ |
|-------|--------|-------------|-------------|-------|--------|----------|
| 1 | .gitignore | 23/12/68 | 23/12/68 | Claude | ✅ Completed | อยู่ใน .gitignore แล้ว |
| 2 | MinIO Credentials | 23/12/68 | 23/12/68 | Claude | ✅ Completed | ทดสอบสำเร็จ |
| 3 | PostgreSQL Password | 23/12/68 | 23/12/68 | Claude | ✅ Completed | Backup & Restore สำเร็จ |
| 4 | SECRET_KEY | 23/12/68 | 23/12/68 | Claude | ✅ Completed | ผู้ใช้ต้อง login ใหม่ |
| 5 | Redis Auth | 23/12/68 | 23/12/68 | Claude | ✅ Completed | Bonus จาก Phase 1 |
| 6 | Network Isolation | - | - | - | ⏳ Pending | รอดำเนินการ |
| 7 | Healthcheck | - | - | - | ⏳ Pending | รอดำเนินการ |
| 8 | Container Security | - | - | - | ⏳ Pending | รอดำเนินการ |
| 9 | Rate Limiting | - | - | - | ⏳ Pending | รอดำเนินการ |
| 10 | Volume Mounting | - | - | - | ⏳ Pending | รอดำเนินการ |

**สัญลักษณ์:**
- ⏳ Pending = รอดำเนินการ
- 🚧 In Progress = กำลังดำเนินการ
- ✅ Completed = เสร็จสมบูรณ์
- ❌ Failed = ล้มเหลว
- ⚠️ Issue = พบปัญหา

---

## 📞 ติดต่อสอบถาม

หากมีคำถามหรือปัญหาในการดำเนินการ กรุณาติดต่อ:
- Security Team
- DevOps Team

---

**สร้างโดย:** Claude Code Security Audit
**ปรับปรุงล่าสุด:** 23 ธันวาคม 2568
**เวอร์ชัน:** 1.0
