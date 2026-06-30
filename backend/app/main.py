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
from app.models.integration import Integration
from app.models.integration_result import IntegrationResult
from app.models.api_access_token import APIAccessToken
from app.models.agent_conversation import AgentConversation
from app.models.agent_message import AgentMessage
from app.models.agent_memory import AgentMemory
from app.models.agent_skill import AgentSkill
from app.models.agent_pending_action import AgentPendingAction
from app.models.workflow import Workflow, WorkflowRun, WorkflowNodeRun
from app.initial_data import init_db
from app.initial_templates import init_system_templates
from app.initial_ai_settings import init_ai_settings
from app.initial_agent_skills import ensure_system_agent_skills
from app.initial_workflows import ensure_sample_workflows
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
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS ocr_endpoint varchar DEFAULT 'https://111.223.37.41:9001/v3/ai-process-file'"))
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS structured_output_endpoint varchar DEFAULT 'https://111.223.37.41:9001/structured-output'"))
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS schema_suggestion_endpoint varchar DEFAULT 'https://111.223.37.41:9001/suggest-schema'"))
    conn.execute(text("ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS test_endpoint varchar DEFAULT 'https://111.223.37.41:9001/me'"))

    # Add schema_id to documents table for per-document schema selection
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS schema_id uuid NULL"))
    # Add task_id for async processing correlation
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS task_id varchar NULL"))
    # Add template_id to document_schemas table for template reference
    conn.execute(text("ALTER TABLE IF EXISTS document_schemas ADD COLUMN IF NOT EXISTS template_id uuid NULL"))
    # Add multi-page OCR support fields
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS page_count integer NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS ocr_pages jsonb NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_error varchar NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS review_decision varchar NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS reviewed_at timestamptz NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS reviewed_by uuid NULL"))
    # Ensure job ownership column exists for dashboard queries
    conn.execute(text("ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS user_id uuid NULL"))
    # Integration results: add type and name columns for generic history
    conn.execute(text("ALTER TABLE IF EXISTS integration_results ADD COLUMN IF NOT EXISTS integration_type varchar(20) NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS integration_results ADD COLUMN IF NOT EXISTS integration_name varchar(255) NULL"))

    # Workflow webhook trigger/result fields
    conn.execute(text("ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_enabled boolean DEFAULT false"))
    conn.execute(text("ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_secret_hash text NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_secret_created_at timestamptz NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_last_triggered_at timestamptz NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS workflow_runs ADD COLUMN IF NOT EXISTS result jsonb NULL"))
    conn.execute(text("ALTER TABLE IF EXISTS workflow_runs ADD COLUMN IF NOT EXISTS result_node_id varchar(100) NULL"))

    # Agent skills: agentskills.io spec fields
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS scope varchar(20) DEFAULT 'user'"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS license varchar(100)"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS compatibility varchar(500)"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS metadata jsonb"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS allowed_tools text"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS source varchar(20) DEFAULT 'db'"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS file_path varchar(500)"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS version varchar(20)"))
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS user_id uuid NULL"))  # make nullable for system skills
    conn.execute(text("ALTER TABLE IF EXISTS agent_skills ALTER COLUMN name TYPE varchar(64)"))

    # AI Settings: agent provider fields
    conn.execute(text("ALTER TABLE IF EXISTS ai_settings ADD COLUMN IF NOT EXISTS model varchar DEFAULT 'gpt-4o-mini'"))
    conn.execute(text("ALTER TABLE IF EXISTS ai_settings ADD COLUMN IF NOT EXISTS is_agent_provider boolean DEFAULT false"))
    conn.execute(text("ALTER TABLE IF EXISTS ai_settings ADD COLUMN IF NOT EXISTS provider_type varchar DEFAULT 'completion_messages'"))

    # Migrate existing data: if api_endpoint exists but ocr_endpoint doesn't, copy it
    conn.execute(text("""
        UPDATE settings
        SET ocr_endpoint = api_endpoint
        WHERE ocr_endpoint IS NULL
          AND api_endpoint IS NOT NULL
          AND api_endpoint != ''
    """))

    conn.commit()

# Add new cloud-storage values to the integrationtype enum (Postgres ENUM).
# ALTER TYPE ... ADD VALUE must run outside a transaction → use AUTOCOMMIT.
with engine.connect() as conn:
    autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
    # SQLAlchemy SQLEnum persists the member NAME (uppercase), e.g. API/WORKFLOW/LLM
    for label in ("GDRIVE", "ONEDRIVE"):
        try:
            autocommit.execute(text(f"ALTER TYPE integrationtype ADD VALUE IF NOT EXISTS '{label}'"))
        except Exception as exc:  # pragma: no cover — enum/table may not exist yet
            print(f"Skip enum migration for {label}: {exc}")

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

def ensure_agent_skills():
    try:
        ensure_system_agent_skills()
    except Exception:
        pass  # Skills are optional; the API should still start if discovery fails.

def ensure_workflow_samples():
    db = SessionLocal()
    try:
        ensure_sample_workflows(db)
    finally:
        db.close()

def ensure_sandbox_ready():
    """Warm up the Docker sandbox image without blocking API startup."""
    import threading

    def _warm_sandbox_image():
        try:
            from app.services.code_sandbox import ensure_sandbox_image
            ensure_sandbox_image()
        except Exception:
            pass  # Sandbox is optional; agent handles missing image gracefully.

    threading.Thread(
        target=_warm_sandbox_image,
        name="sandbox-image-warmup",
        daemon=True,
    ).start()

ensure_seed_user()
ensure_system_templates()
ensure_ai_settings()
ensure_agent_skills()
ensure_workflow_samples()
ensure_sandbox_ready()

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
    return {"message": "Welcome to Softnix InsightDOC API"}


@app.get("/health", include_in_schema=False)
def health_check():
    # Return minimal info to avoid leaking version/config details
    return {"status": "ok"}
