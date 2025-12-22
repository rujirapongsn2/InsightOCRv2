from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api import api_router
from app.middleware.proxy import ProxyHeaderMiddleware
from app.db.base_class import Base
from app.db.session import engine, SessionLocal
from app.models.schema import DocumentSchema
from app.models.job import Job
from app.models.document import Document
from app.models.user import User
from app.models.setting import Setting
from app.models.template import SchemaTemplate
from app.models.ai_settings import AISettings
from app.models.activity_log import ActivityLog
from app.initial_data import init_db
from app.initial_templates import init_system_templates
from app.initial_ai_settings import init_ai_settings
from sqlalchemy import text

# Create tables on startup
Base.metadata.create_all(bind=engine)

# Ensure new columns exist without full migrations for development environments
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE IF EXISTS document_schemas ADD COLUMN IF NOT EXISTS created_by uuid NULL"))

    # Settings table columns
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS api_endpoint varchar"))
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS api_token varchar"))
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS verify_ssl boolean DEFAULT false"))

    # New separate endpoint columns
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS ocr_endpoint varchar DEFAULT 'https://111.223.37.41:9001/ai-process-file'"))
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS test_endpoint varchar DEFAULT 'https://111.223.37.41:9001/me'"))

    # Add schema_id to documents table for per-document schema selection
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS schema_id uuid NULL"))
    # Add template_id to document_schemas table for template reference
    conn.execute(text("ALTER TABLE IF EXISTS document_schemas ADD COLUMN IF NOT EXISTS template_id uuid NULL"))
    # Add multi-page OCR support fields
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS page_count integer NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS ocr_pages jsonb NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_error varchar NULL"))
    # Ensure job ownership column exists for dashboard queries
    conn.execute(text("ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS user_id uuid NULL"))

    # Migrate existing data: if api_endpoint exists but ocr_endpoint doesn't, copy it
    conn.execute(text("""
        UPDATE settings
        SET ocr_endpoint = api_endpoint
        WHERE ocr_endpoint IS NULL
          AND api_endpoint IS NOT NULL
          AND api_endpoint != ''
    """))

    conn.commit()

# Seed an initial admin user if none exists
def ensure_seed_user():
    db = SessionLocal()
    try:
        init_db(db)
    finally:
        db.close()

# Seed system templates if none exist
def ensure_system_templates():
    db = SessionLocal()
    try:
        init_system_templates(db)
    finally:
        db.close()

# Seed AI settings if none exist
def ensure_ai_settings():
    db = SessionLocal()
    try:
        init_ai_settings(db)
    finally:
        db.close()

ensure_seed_user()
ensure_system_templates()
ensure_ai_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set all CORS enabled origins
raw_origins = [origin.strip() for origin in settings.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]
extra_origins = [origin.strip() for origin in settings.BACKEND_EXTRA_CORS_ORIGINS.split(",") if origin.strip()]

# Always allow common local origins to avoid CORS failures when switching between localhost and 127.0.0.1 during dev
# Include HTTPS origins for Nginx reverse proxy
default_local_origins = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://localhost",
    "https://127.0.0.1",
}

if raw_origins:
    origins = list(set(raw_origins) | default_local_origins)
else:
    origins = list(default_local_origins)

if extra_origins:
    origins = list(set(origins) | set(extra_origins))

# Add proxy header middleware BEFORE CORS
app.add_middleware(ProxyHeaderMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
def root():
    return {"message": "Welcome to Softnix InsightOCR API"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
