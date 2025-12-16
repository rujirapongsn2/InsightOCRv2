# Softnix InsightOCR

A modern document processing system with OCR (Optical Character Recognition) and structured data extraction capabilities. Built with FastAPI backend and Next.js frontend.

![Softnix InsightOCR Dashboard](assets/dashboard_preview.png)

## Features

- 🔐 **User Management & Authentication** - Role-based access control (Admin, Manager, User)
- 📄 **Document Schema Management** - Define custom extraction schemas for different document types
- 📋 **Job-based Processing** - Organize documents into jobs for batch processing
- 🔍 **OCR Processing** - Extract text from PDF and image files
- 🎯 **Structured Data Extraction** - Convert OCR text to structured JSON based on schemas
- ✏️ **Review & Edit** - Review and correct extracted data before saving
- ⚙️ **Configurable Settings** - Manage API endpoints and credentials through UI

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

### Installation

1. Clone the repository:
```bash
git clone https://github.com/rujirapongsn2/SoftnixInsightOCR.git
cd SoftnixInsightOCR
```

2. Start the application:
```bash
docker compose up -d
```

3. Access the application:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

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
SoftnixInsightOCR/
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

## API Services

### OCR Service
- Endpoint: `/ai-process-file`
- Purpose: Extract text from PDF/images
- Input: File (PDF/Image)
- Output: OCR text with AI processing

### Structure Service
- Endpoint: `/structured-output`
- Purpose: Convert text to structured JSON
- Input: OCR text + JSON Schema
- Output: Structured data

## Environment Variables

### Backend
- `DATABASE_URL` - PostgreSQL connection string
- `BACKEND_CORS_ORIGINS` - Allowed CORS origins

### Frontend
- `NEXT_PUBLIC_API_URL` - Backend API URL

## Development

### Running Tests

See `QUICKWIN-TEST.md` for detailed testing procedures.

### Database Migrations

The application uses automatic migrations on startup. New columns are added via `ALTER TABLE IF NOT EXISTS` statements in `backend/app/main.py`.

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
