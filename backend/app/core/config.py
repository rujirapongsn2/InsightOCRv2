from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Softnix InsightDOC"
    API_V1_STR: str = "/api/v1"
    
    # CORS - comma-separated string
    BACKEND_CORS_ORIGINS: str = ""

    # Database
    DB_USER: Optional[str] = "postgres"
    DB_PASSWORD: Optional[str] = "postgres"
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/softnix_ocr"

    # Redis (for Celery task queue)
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL: str = "redis://redis:6379/0" # Set via env var

    # Storage
    STORAGE_TYPE: str = "local" # local, minio, s3

    # Upload validation
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_UPLOAD_EXTENSIONS: str = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.heic"

    # Data retention (workflow run history, output files, job logs)
    RETENTION_DAYS: int = 30
    
    # MinIO / S3 Common
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "insightocr"
    MINIO_SECURE: bool = False # Use HTTPS
    
    # AWS S3 Specific
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    AWS_BUCKET_NAME: Optional[str] = None
    # AI
    OPENAI_API_KEY: str = "" # Set via env var
    AI_PROVIDER_URL: Optional[str] = None
    AI_PROVIDER_KEY: Optional[str] = None
    AGENT_PROVIDER_URL: Optional[str] = None
    AGENT_PROVIDER_KEY: Optional[str] = None
    AGENT_MODEL: str = "gpt-4o-mini"
    OCR_ENDPOINT: Optional[str] = None
    TEST_ENDPOINT: Optional[str] = None
    MISTRAL_API_KEY: Optional[str] = None
    OCR_SSE_IDLE_TIMEOUT_SECONDS: int = 180
    # The external OCR service can accept a job and keep its event stream open
    # indefinitely. Keep an explicit wall-clock deadline so a single document
    # never holds a Celery worker until the global task limit is reached.
    OCR_EXTERNAL_JOB_TIMEOUT_SECONDS: int = 300
    OCR_EXTERNAL_QUEUE_TIMEOUT_SECONDS: int = 60
    OCR_STATUS_POLL_INTERVAL_SECONDS: int = 2
    OCR_STATUS_REQUEST_TIMEOUT_SECONDS: int = 20
    ANYDOC_MAX_PAGES: int = 100
    ANYDOC_MAX_OCR_PAGES: int = 50
    # Image inputs use the same AnyDoc hybrid orchestration, but are routed
    # straight to the configured OCR providers. Keep their decoded size bounded
    # before Pillow loads them to avoid expensive or malicious image payloads.
    ANYDOC_MAX_IMAGE_PIXELS: int = 40_000_000
    ANYDOC_MAX_IMAGE_DIMENSION: int = 10_000
    # Keep AnyDoc work well inside the Celery 30-minute soft limit so a stuck
    # provider cannot leave a worker blocked until the task is killed.
    ANYDOC_DOCUMENT_TIMEOUT_SECONDS: int = 1200
    TESSERACT_OCR_LANGUAGE: str = "tha+eng"
    TESSERACT_OCR_TIMEOUT_SECONDS: int = 30
    # Softnix OCR is asynchronous. Do not let one stalled provider job delay
    # the configured OCR fallback for a whole document page.
    ANYDOC_PRIMARY_OCR_TIMEOUT_SECONDS: int = 30
    ANYDOC_FALLBACK_REQUEST_TIMEOUT_SECONDS: int = 120

    # Cloud storage OAuth. Keep provider secrets server-side; users connect
    # their own accounts through the integrations UI.
    PUBLIC_APP_URL: str = "http://localhost:3000"
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = None
    GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = None
    # Full Drive access is required only because the current UX browses
    # existing folders and supports both import and export. The application
    # enforces the saved destination folder for OAuth workflow operations.
    GOOGLE_OAUTH_SCOPE: Optional[str] = None
    MICROSOFT_OAUTH_CLIENT_ID: Optional[str] = None
    MICROSOFT_OAUTH_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_OAUTH_TENANT: str = "common"
    MICROSOFT_OAUTH_REDIRECT_URI: Optional[str] = None
    # Files.ReadWrite is the delegated scope needed for existing-folder
    # import/export; AppFolder is a narrower alternative for app-only storage.
    MICROSOFT_OAUTH_SCOPE: Optional[str] = None

    # JWT
    SECRET_KEY: str # Set via env var
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    # Keep refresh sessions independent from the short-lived access token.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # MCP accepts JSON-RPC, so uploaded binary files are base64 encoded. Keep
    # this lower than the regular UI upload limit to bound request memory.
    MCP_MAX_UPLOAD_SIZE_MB: int = 10
    # Avoid a database write on every authenticated MCP/API request while
    # keeping token usage information reasonably current.
    API_TOKEN_LAST_USED_UPDATE_SECONDS: int = 300

    # Extra CORS origins (comma-separated) to append beyond BACKEND_CORS_ORIGINS
    BACKEND_EXTRA_CORS_ORIGINS: str = ""

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"

settings = Settings()
