import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Sentimentri Autonomous Worker & Intelligence Service"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Internal & External API Key Protection
    WORKER_API_KEY: str = os.getenv("WORKER_API_KEY", "")
    
    # Dedicated Standalone Database (PostgreSQL / SQLite fallback for testing)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./worker_service.db")
    
    # Redis Broker & Celery
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # External Data & LLM Providers
    APIFY_TOKEN: str = os.getenv("APIFY_TOKEN", "")
    SOCIALDATA_API_KEY: str = os.getenv("SOCIALDATA_API_KEY", "")
    DEEP_SEEK_SECRET: str = os.getenv("DEEP_SEEK_SECRET", "")
    
    # Object Storage (S3 / Cloudflare R2 / MinIO)
    S3_ENABLED: bool = os.getenv("S3_ENABLED", "false").lower() == "true"
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "sentimentri-reports")
    S3_ACCESS_KEY_ID: str = os.getenv("S3_ACCESS_KEY_ID", "")
    S3_SECRET_ACCESS_KEY: str = os.getenv("S3_SECRET_ACCESS_KEY", "")
    S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", "")
    S3_REGION: str = os.getenv("S3_REGION", "auto")

    # Webhook signature secret for callbacks
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()
