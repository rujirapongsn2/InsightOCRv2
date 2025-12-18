# Environment Configuration Guide

คู่มือการตั้งค่า Environment Variables สำหรับ InsightOCR v2

## 📋 Quick Start

### Development Environment (localhost)

1. **Backend Configuration**
   ```bash
   cd backend
   cp .env.dev.example .env
   # แก้ไข OCR_ENDPOINT และ TEST_ENDPOINT ตามที่ต้องการ
   ```

2. **Frontend Configuration**
   ```bash
   cd frontend
   cp .env.development.example .env.local
   ```

3. **Start Docker Compose**
   ```bash
   docker compose up --build
   ```

4. **Access Application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

---

### Production Environment

1. **Backend Configuration**
   ```bash
   cd backend
   cp .env.prod.example .env
   ```

   **แก้ไขค่าต่อไปนี้:**
   - `SECRET_KEY` - Generate ด้วย `openssl rand -hex 32`
   - `DATABASE_URL` - Production database connection string
   - `REDIS_URL` - Production Redis connection string
   - `BACKEND_CORS_ORIGINS` - Frontend domain ของคุณ
   - `OCR_ENDPOINT` - Production OCR service endpoint
   - `TEST_ENDPOINT` - Production OCR test endpoint
   - `STORAGE_TYPE` - แนะนำ `minio` หรือ `s3`
   - MinIO/S3 credentials

2. **Frontend Configuration**
   ```bash
   cd frontend
   cp .env.production.example .env.local
   ```

   **แก้ไขค่าต่อไปนี้:**
   - `NEXT_PUBLIC_API_URL` - Production backend URL

3. **Start Docker Compose**
   ```bash
   docker compose up -d --build
   ```

---

## 📁 Environment Files Overview

### Backend Files

| File | Purpose | Git Tracked? |
|------|---------|--------------|
| `.env.example` | General template with all variables | ✅ Yes |
| `.env.dev.example` | Development-specific template | ✅ Yes |
| `.env.prod.example` | Production-specific template | ✅ Yes |
| `.env` | **Your actual configuration** | ❌ No (gitignored) |

### Frontend Files

| File | Purpose | Git Tracked? |
|------|---------|--------------|
| `.env.example` | General template | ✅ Yes |
| `.env.development.example` | Development template | ✅ Yes |
| `.env.production.example` | Production template | ✅ Yes |
| `.env.local` | **Your actual configuration** | ❌ No (gitignored) |

---

## 🔧 Configuration Variables

### Backend Variables

#### Security
- `SECRET_KEY` - JWT token signing key (generate with `openssl rand -hex 32`)
- `ALGORITHM` - JWT algorithm (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES` - Token expiration time

#### Database & Cache
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string for Celery task queue

#### CORS
- `BACKEND_CORS_ORIGINS` - Allowed frontend origins (comma-separated)
- `BACKEND_EXTRA_CORS_ORIGINS` - Additional origins without overwriting defaults

#### Storage
- `STORAGE_TYPE` - Options: `local`, `minio`, `s3`
- MinIO Configuration (if `STORAGE_TYPE=minio`):
  - `MINIO_ENDPOINT`
  - `MINIO_ACCESS_KEY`
  - `MINIO_SECRET_KEY`
  - `MINIO_BUCKET`
  - `MINIO_SECURE`
- AWS S3 Configuration (if `STORAGE_TYPE=s3`):
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION`
  - `AWS_BUCKET_NAME`

#### OCR Service
- `OCR_ENDPOINT` - External OCR service endpoint for document processing
- `TEST_ENDPOINT` - OCR service health check endpoint

**Note:** These are default values when no database setting exists. Can be overridden via UI Settings page.

#### AI Provider (Optional)
- `OPENAI_API_KEY` - OpenAI API key
- `AI_PROVIDER_URL` - Custom AI provider endpoint
- `AI_PROVIDER_KEY` - Custom AI provider API key

### Frontend Variables

- `NEXT_PUBLIC_API_URL` - Backend API base URL (must include `/api/v1`)

---

## 🔐 Security Best Practices

### 1. Never Commit Sensitive Data
```bash
# .env files with actual credentials should NEVER be committed
# Check .gitignore includes:
.env
.env.local
.env.*.local
```

### 2. Generate Strong Secret Keys
```bash
# Generate a secure SECRET_KEY for production
openssl rand -hex 32
```

### 3. Use Environment-Specific Configurations
- Development: Use `.env.dev.example` as base
- Production: Use `.env.prod.example` as base

### 4. Rotate Credentials Regularly
- Change `SECRET_KEY` periodically
- Rotate database passwords
- Update API keys when compromised

---

## 🚀 Deployment Scenarios

### Scenario 1: Local Development (localhost)
```bash
# Backend .env
DATABASE_URL=postgresql://postgres:postgres@db:5432/softnix_ocr
REDIS_URL=redis://redis:6379/0
BACKEND_CORS_ORIGINS=http://localhost:3000,http://localhost:8000
OCR_ENDPOINT=https://111.223.37.41:9001/ai-process-file

# Frontend .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

### Scenario 2: Production (env-1805534.th2.proen.cloud)
```bash
# Backend .env
DATABASE_URL=postgresql://postgres:postgres@db:5432/softnix_ocr
REDIS_URL=redis://redis:6379/0
BACKEND_CORS_ORIGINS=http://env-1805534.th2.proen.cloud:3000
OCR_ENDPOINT=https://your-production-ocr.com:9001/ai-process-file
STORAGE_TYPE=minio
MINIO_ENDPOINT=minio:9000
MINIO_SECURE=True

# Frontend .env.local
NEXT_PUBLIC_API_URL=http://env-1805534.th2.proen.cloud:8000/api/v1
```

### Scenario 3: Multi-Environment with Same Codebase
Use environment-specific config files and Docker Compose override:

```bash
# docker-compose.prod.yml
version: '3.8'
services:
  backend:
    env_file:
      - ./backend/.env.prod
  frontend:
    env_file:
      - ./frontend/.env.prod
```

Then deploy with:
```bash
# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Development (default)
docker compose up
```

---

## ⚠️ Common Issues

### Issue 1: CORS Errors
**Symptom:** Frontend can't connect to backend, CORS errors in browser console

**Solution:**
1. Check `BACKEND_CORS_ORIGINS` includes your frontend URL
2. Restart backend after changing CORS settings
3. Verify frontend `NEXT_PUBLIC_API_URL` matches backend host

### Issue 2: OCR Endpoint Not Working
**Symptom:** Document processing fails with connection errors

**Solution:**
1. Verify `OCR_ENDPOINT` is accessible from backend container
2. Check OCR service is running: `curl -k https://your-ocr-endpoint/me`
3. Go to Settings page in UI and update endpoints manually

### Issue 3: Database Connection Failed
**Symptom:** Backend crashes with "connection refused" or "unknown host"

**Solution:**
1. In Docker Compose: Use service name `db` not `localhost`
2. External database: Use actual host/IP address
3. Check database is running: `docker compose ps db`

### Issue 4: Environment Variables Not Updating
**Symptom:** Changes to .env don't take effect

**Solution:**
1. Rebuild containers: `docker compose up --build`
2. Remove old containers: `docker compose down && docker compose up`
3. For Next.js: Clear `.next` cache and rebuild

---

## 🧪 Testing Configuration

### Test Backend Configuration
```bash
# Check if backend can connect to database
docker compose exec backend python -c "from app.db.session import engine; print(engine.url)"

# Check CORS settings
docker compose exec backend python -c "from app.core.config import settings; print(settings.BACKEND_CORS_ORIGINS)"
```

### Test Frontend Configuration
```bash
# Check API URL
docker compose exec frontend printenv NEXT_PUBLIC_API_URL
```

### Test OCR Endpoint
```bash
# From your machine or backend container
curl -k https://your-ocr-endpoint:9001/me
```

---

## 📚 Additional Resources

- [Docker Compose Environment Variables](https://docs.docker.com/compose/environment-variables/)
- [Next.js Environment Variables](https://nextjs.org/docs/basic-features/environment-variables)
- [PostgreSQL Connection Strings](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING)

---

## 🆘 Need Help?

1. Check this guide first
2. Review `.env.example` templates for variable descriptions
3. Check application logs: `docker compose logs -f backend`
4. Verify all required variables are set
5. Compare your `.env` with example templates
