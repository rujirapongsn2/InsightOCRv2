# InsightDOC

A modern document processing system with OCR (Optical Character Recognition) and structured data extraction capabilities. Built with FastAPI backend and Next.js (App Router) frontend.

![Softnix InsightDOC Dashboard](assets/dashboard_preview.png)

## Key Features

### 🔐 Authentication & User Management
- JWT-based authentication with secure session handling
- Role-based access control: **Admin**, **Manager**, **User**
- User profile management and admin-managed user accounts
- Activity log tracking per user (login, logout, failed login, etc.)

### 📄 Document Schema Management
- **Simple Mode (AI-Assisted Wizard)** — Upload a sample document, AI automatically suggests extraction fields based on OCR content
- **Advanced Mode** — Manually define schema fields with full control over field names, types, and descriptions
- Import/export schemas via JSON Schema format
- Reusable **Schema Templates Library** — Pre-built templates organized by industry (Finance, Legal, Supply Chain, HR, Healthcare, Quality & Operations)
- Schema versioning with edit history

### 📋 Job-based Document Processing
- Create jobs to group and batch-process related documents
- Upload multiple PDF/image files (JPG, PNG) per job
- Per-document schema assignment within a single job
- **One-click "Process All"** to run OCR + extraction across all documents in a job
- Real-time processing progress tracking via Redis-backed status updates

### 🔍 OCR & Structured Data Extraction
- Extract text from PDF and image files via external OCR API
- Convert raw OCR text into **structured JSON** based on defined schemas
- Async background processing powered by **Celery + Redis** task queue
- Live streaming progress updates during processing (percent + stage)
- Automatic retry on transient failures (up to 3 retries)

### ✏️ Review & Edit Extracted Data
- Side-by-side document viewer (PDF/image) and extracted data editor
- Edit any extracted field inline before saving
- Separate **Reviewed Data** vs **Extracted Data** states for audit trail
- OCR quality warnings for low-confidence extractions
- Reject button to flag documents that need re-processing

### 🤖 LLM Integration & AI Validation
- **LLM Integration** — Connect any OpenAI-compatible API (GPT-4o, o1, o3, etc.)
- **Cross-document validation** — Send multiple documents to an LLM for comparison and discrepancy detection
- **Reasoning effort control** — Set low / medium / high reasoning effort for supported models (o-series)
- **Industry-specific LLM Templates** — Ready-to-use prompt templates for:
  - Finance & Accounting (Invoice ↔ PO ↔ GRN verification, tax validation)
  - Legal & Compliance (contract review, regulatory checks)
  - Supply Chain (delivery order, GRN, shipment reconciliation)
  - HR & Administration (employee onboarding, leave, payroll)
  - Healthcare (patient data, lab results, medical forms)
  - Quality & Operations (inspection reports, audit checklists)
- **Streaming LLM responses** — Results appear token-by-token in real time
- Export LLM validation results as **TXT**, **HTML/DOC**, or **PDF**

### 💬 ChatDOC — Chat with Your Documents
- Built-in chat panel per job powered by LLM integrations
- Ask questions about document content in **Thai or English**
- LLM has access to both structured extracted data and raw OCR text
- Multi-turn conversation history with persistent conversation threads
- Select which LLM integration to use per conversation

### 🔌 Integrations
- **API Integration** — Push extracted data to external endpoints (POST / PUT) with custom headers and payload templates
- **Workflow / Webhook Integration** — Trigger n8n, Zapier, or any webhook-compatible workflow
- **LLM Integration** — Connect OpenAI-compatible providers for AI-powered document analysis
- Per-integration active/paused status control
- Integration result history per document

### 📊 Dashboard & Activity Logs
- Overview dashboard with key statistics (jobs, documents, processing status)
- **Full Activity Log** — Searchable audit trail of all system actions with timestamps, user, IP address, and action details
- Paginated log viewer with action-type icons

### ⚙️ Settings & Configuration
- Configure **OCR API endpoint** and **Bearer Token** via UI (no restart required)
- **AI Field Suggestion providers** — Add, test, and manage multiple AI providers for schema wizard
- Test connection buttons for verifying API connectivity
- Settings persisted in database and overridable per environment via `.env`

### 🗄️ Storage & Infrastructure
- Pluggable file storage: **Local**, **MinIO (S3-compatible)**, or **AWS S3**
- Dockerized deployment with **8 services**: backend, frontend, nginx, gateway, PostgreSQL, Redis, MinIO, Celery worker
- **Network isolation** — Internal Docker network keeps DB/Redis/MinIO unreachable from the public internet
- Outbound-only external access via gateway proxy

## Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **PostgreSQL** - Database
- **SQLAlchemy** - ORM
- **Pydantic** - Data validation

### Frontend
- **Next.js 16** - React framework
- **TypeScript** - Type safety
- **Tailwind CSS** - Styling

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Git

### Installation (Docker, recommended)

1) Clone the repository:
```bash
git clone https://github.com/rujirapongsn2/InsightDOCv2.git
cd InsightDOCv2
```

2) Create environment files (root + backend + frontend):
```bash
# Root (docker compose)
cp .env.example .env

# Backend
cp backend/.env.dev.example backend/.env   # หรือใช้ .env.prod.example ถ้า deploy

# Frontend
cp frontend/.env.development.example frontend/.env.local
```
- แก้ค่าใน `.env`, `backend/.env`, `frontend/.env.local` ให้ครบถ้วน (ดู `ENV_SETUP.md` และไฟล์ *.example เป็นแนวทาง)
- คีย์สำคัญ: `SECRET_KEY`, `DATABASE_URL`, `BACKEND_CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`, OCR endpoints/keys

3) Start services (เลือกวิธีใดวิธีหนึ่ง):
```bash
docker compose up -d        # หรือ
./scripts/services.sh up    # helper script
```

4) Setup gateway/nginx (จำเป็นหลังขึ้น container แล้ว):
```bash
./scripts/setup/setup-nginx.sh
```

5) ตรวจสอบ services และ network isolation:
- จะมีอย่างน้อย 8 services (backend, frontend, nginx, gateway, db, redis, minio, celery_worker)  
  ตรวจสอบด้วย: `docker ps`
- ยืนยัน isolation (ตัวอย่าง):  
  `docker compose exec redis ping -c1 8.8.8.8` ➜ ควร `Network unreachable`  
  `docker compose exec backend curl -k https://<external-api>/me` ➜ ควรเข้าถึงได้ผ่าน gateway proxy

6) Access the application:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Default Credentials

- **Admin**: admin@example.com / admin

## Service Management

The project includes a helper script (`scripts/services.sh`) to manage Docker services easily:

### Quick Commands

```bash
# Start all services (with rebuild)
scripts/services.sh up

# Stop all services
scripts/services.sh down

# Restart specific service
scripts/services.sh restart web      # Restart frontend
scripts/services.sh restart api      # Restart backend
scripts/services.sh restart all      # Restart all services

# View logs (real-time)
scripts/services.sh logs web         # Frontend logs
scripts/services.sh logs api         # Backend logs

# Check service status
scripts/services.sh ps
```

### When to Use Each Command

**`restart web` / `restart api`**
- After installing new npm packages
- After code changes that need container restart
- When service is not responding
- Much faster than full rebuild

**`up`**
- First time setup
- After Dockerfile changes
- After adding new environment variables
- After docker-compose.yml changes

**`down`**
- Stop all services to free resources
- Before switching branches with major changes
- When troubleshooting Docker issues

**`logs`**
- Debug runtime errors
- Monitor application behavior
- Watch for API request/response
- Ctrl+C to stop following logs

### Service Aliases

The script accepts multiple aliases for convenience:
- `web` or `frontend` - Next.js frontend
- `api` or `backend` - FastAPI backend

### Examples

```bash
# Install new package and restart frontend
cd frontend
npm install react-pdf pdfjs-dist
cd ..
scripts/services.sh restart web

# View backend error logs
scripts/services.sh logs api

# Full restart after major changes
scripts/services.sh down
scripts/services.sh up
```

## Usage Workflow

### 1. Configure Settings

Navigate to `/settings` and configure:
- API Endpoint (OCR service URL)
- API Token (Authentication key)
- OCR Engine (optional)
- Model (optional)

### 2. Create Document Schema

1. Go to `/schemas`
2. Click "Create Schema"
3. Define fields to extract (name, type, description)
4. Optionally, import from JSON Schema

### 3. Process Documents

1. Create a new Job (`/jobs/create`)
2. Upload documents
3. Select schema for each document
4. Click "Process" or "Process All"
5. Review extracted data
6. Save changes

## UI Preview

![Dashboard preview](assets/dashboard.png)

## Project Structure

```
InsightDOCv2/
├── backend/
│   ├── app/
│   │   ├── api/          # API endpoints
│   │   ├── models/       # Database models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic (OCR, Structure)
│   │   └── core/         # Configuration
│   └── Dockerfile
├── frontend/
│   ├── app/              # Next.js pages
│   ├── components/       # React components
│   └── Dockerfile
└── docker-compose.yml
```

## External API Configuration

InsightDOC integrates with an external AI service for OCR processing and structured data extraction. The external API provides the following endpoints:

### 1. Authentication Test Endpoint
- **URL**: `https://111.223.37.41:9001/me`
- **Purpose**: Test API authentication and verify endpoint connectivity
- **Method**: GET
- **Headers**: `Authorization: Bearer <API_TOKEN>`
- **Response**: User/service information
- **Usage**: Used by the Settings page "Test Endpoint" button

### 2. OCR Extraction Endpoint
- **URL**: `https://111.223.37.41:9001/ai-process-file`
- **Purpose**: Extract text from PDF/image documents using OCR
- **Method**: POST
- **Input**: File (PDF, JPG, PNG)
- **Output**: Extracted OCR text
- **Usage**: Core OCR processing for document text extraction

### 3. Structured Output Endpoint
- **URL**: `https://111.223.37.41:9001/structured-output`
- **Purpose**: Convert OCR text to structured JSON based on a defined schema
- **Method**: POST
- **Input**:
  - OCR text content
  - JSON Schema definition (fields, types, descriptions)
- **Output**: Structured JSON data matching the schema
- **Usage**: Transform extracted text into structured data for review and export

### Configuration in Settings

Navigate to `/settings` and configure the external API endpoints:

1. **OCR Processing Endpoint**: `https://111.223.37.41:9001/ai-process-file`
   - Used for extracting text from uploaded documents
   - POST request with file upload

2. **Test Connection Endpoint**: `https://111.223.37.41:9001/me`
   - Used to verify API authentication
   - GET request to test connectivity

3. **Bearer Token**: Your API authentication token (e.g., `ocr_ai_key_987654321fedcba`)
   - Used for authenticating requests to both endpoints

4. Click **"Test Connection"** to verify connectivity
5. Click **"Save Connection Settings"** to persist configuration

**Note**: The system now uses separate endpoints for different operations:
- Test connection → `test_endpoint` (/me)
- OCR extraction → `ocr_endpoint` (/ai-process-file)
- Data structuring → `/structured-output` (called during document processing)

### AI Field Suggestion Configuration (Optional)

The system includes an **AI-Assisted Field Suggestion** feature for automatically suggesting schema fields from sample documents. This feature is **separate** from the core OCR processing and requires additional configuration.

**Important**: The AI Field Suggestion feature requires a compatible AI provider API (e.g., Dify.ai, OpenAI) that can analyze OCR content and suggest structured fields. This is NOT the same as the OCR extraction endpoint above.

To configure AI Field Suggestion:
1. Navigate to `/settings`
2. Scroll to **"AI Field Suggestion"** section (below the API Endpoint section)
3. Click **"Add Provider"**
4. Configure your AI provider:
   - **Provider Name**: Unique identifier (e.g., "dify-ai")
   - **Display Name**: Human-readable name
   - **API URL**: Your AI provider's API endpoint (e.g., `https://api.dify.ai/v1/workflows/run`)
   - **API Key**: Authentication key from your AI provider
   - **Is Active**: Enable the provider
   - **Is Default**: Set as default provider
5. Click **"Test Connection"** to verify
6. Click **"Save"**

**Usage**:
- When creating a schema via **Simple Mode** (`/schemas/new/simple`)
- Upload a sample document
- The system will extract OCR text and send it to the configured AI provider
- AI will suggest relevant fields based on the document content

**Troubleshooting**:
- If you see "OCR extraction failed: 400 Client Error", check that your AI provider URL is correct
- The AI provider endpoint must support field suggestion from OCR content
- If no AI provider is configured, use **Advanced Mode** to create schemas manually

### Common Issues and Solutions

**Error: "OCR extraction failed: 500 Internal Server Error"**
- **Cause**: OCR endpoint not configured or incorrect endpoint URL
- **Solution**:
  1. Go to `/settings`
  2. Verify **OCR Processing Endpoint** is set to `/ai-process-file` (not `/me`)
  3. Verify **Bearer Token** is correct
  4. Click "Save Connection Settings"
  5. Click "Test Connection" to verify

**Error: "API Settings not configured"**
- **Cause**: No settings saved in database
- **Solution**:
  1. Login as admin user
  2. Go to `/settings`
  3. Configure both OCR and Test endpoints
  4. Save settings

**Error: "400 Bad Request" when testing connection**
- **Cause**: Using wrong endpoint for the operation
- **Solution**:
  - Test Connection uses GET request to `/me`
  - OCR Processing uses POST request to `/ai-process-file`
  - Ensure you're using the correct endpoint for each purpose

## Environment Variables

### Quick Start
Use the provided `.env.example` templates to get started:

**Development:**
- `backend/.env.dev.example` → `backend/.env`
- `frontend/.env.development.example` → `frontend/.env.local`

**Production:**
- `backend/.env.prod.example` → `backend/.env`
- `frontend/.env.production.example` → `frontend/.env.local`

### Backend Variables

#### Required
- `SECRET_KEY` - JWT token signing key (generate with `openssl rand -hex 32`)
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string for Celery task queue
- `BACKEND_CORS_ORIGINS` - Allowed frontend origins (comma-separated)

#### Storage
- `STORAGE_TYPE` - Options: `local`, `minio`, `s3`
- `MINIO_*` - Required if `STORAGE_TYPE=minio`
- `AWS_*` - Required if `STORAGE_TYPE=s3`

#### OCR Service (New!)
- `OCR_ENDPOINT` - External OCR service endpoint for document processing
- `TEST_ENDPOINT` - OCR service health check endpoint

**Note:** These provide default values when no database setting exists. Can be overridden via UI Settings page.

#### Optional
- `BACKEND_EXTRA_CORS_ORIGINS` - Additional CORS origins
- `OPENAI_API_KEY` - OpenAI API key (optional)
- `AI_PROVIDER_URL` - Custom AI provider endpoint (optional)
- `AI_PROVIDER_KEY` - Custom AI provider API key (optional)

### Frontend Variables
- `NEXT_PUBLIC_API_URL` - Backend API URL (must include `/api/v1`)

### Detailed Configuration
See [ENV_SETUP.md](ENV_SETUP.md) for:
- Complete variable descriptions
- Environment-specific configurations
- Common issues and troubleshooting
- Testing configuration
- Security best practices

## Development

### Running Tests

Tests are not yet automated. When adding coverage, colocate:
- Backend: `backend/tests/test_*.py` with `pytest`
- Frontend: `frontend/**/*.test.tsx` with React Testing Library/Jest

### Database Migrations

Automatic schema alignment occurs on startup via guarded `ALTER TABLE` in `backend/app/main.py`. Add explicit migrations if introducing breaking schema changes.

## Security

- ✅ No hardcoded API credentials in code
- ✅ Settings stored in database
- ✅ Role-based access control
- ✅ JWT authentication (if implemented)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Add your license here]

## Support

For issues and questions, please open an issue on GitHub.

## Acknowledgments

- Built with FastAPI and Next.js
- OCR powered by external API service
