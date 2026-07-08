from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api import api_router
from app.middleware.proxy import ProxyHeaderMiddleware
from app.db.session import SessionLocal
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

# Apply schema migrations (Alembic), serialized across workers by a
# Postgres advisory lock. See backend/alembic/versions/.
from app.db.migrate import run_startup_migrations
run_startup_migrations()

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
