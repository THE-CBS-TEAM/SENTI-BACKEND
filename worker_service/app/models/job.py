import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Float, DateTime, JSON, Integer, Index
from app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Job(Base):
    __tablename__ = "worker_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(100), default="default_client", index=True)
    job_type = Column(String(50), nullable=False, index=True)  # FETCH_PROFILE, POLL_POST, ANALYZE_SENTIMENT, etc.
    status = Column(String(30), default="QUEUED", index=True)  # QUEUED, PROCESSING, SUCCESS, FAILED, RETRYING
    
    payload = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    callback_url = Column(String(500), nullable=True)
    
    cost_credits = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    diagnostic_code = Column(String(100), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

class RawCache(Base):
    __tablename__ = "raw_api_cache"

    cache_key = Column(String(255), primary_key=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

class ProviderLog(Base):
    __tablename__ = "provider_spend_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), nullable=False, index=True)  # APIFY, SOCIALDATA, DEEPSEEK
    action = Column(String(100), nullable=False)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    status_code = Column(Integer, default=200)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
