from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Softnix InsightOCR"
    API_V1_STR: str = "/api/v1"
    
    # CORS - comma-separated string
    BACKEND_CORS_ORIGINS: str = ""

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/softnix_ocr"
    
    # Redis (for Celery task queue)
    REDIS_URL: str = "redis://redis:6379/0" # Set via env var

    # Storage
    STORAGE_TYPE: str = "local" # local, minio, s3
    
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

    # JWT
    SECRET_KEY: str # Set via env var
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()

