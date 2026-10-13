from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field

class BaseJobRequest(BaseModel):
    client_id: str = Field(default="sentimentri_core", description="Identifier of the calling platform")
    callback_url: Optional[str] = Field(None, description="Optional webhook URL to notify upon completion")

class FetchProfileRequest(BaseJobRequest):
    platform: str = Field(..., description="Platform code: IG, TT, or X")
    handle: str = Field(..., description="Creator social handle / username")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict)

class PollPostRequest(BaseJobRequest):
    platform: str = Field(..., description="Platform code: IG, TT, or X")
    post_url: str = Field(..., description="URL of the social media post")
    campaign_id: Optional[str] = None
    options: Optional[Dict[str, Any]] = Field(default_factory=dict)

class AnalyzeSentimentRequest(BaseJobRequest):
    comments: List[Dict[str, Any]] = Field(..., description="List of comments with 'text' and optional 'id'")
    brand_name: Optional[str] = None
    use_llm: bool = True

class CalculateScoreRequest(BaseJobRequest):
    platform_metrics: List[Dict[str, Any]] = Field(..., description="List of metrics per platform")
    comments: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    recent_posts: Optional[List[Dict[str, Any]]] = Field(default_factory=list)

class GenerateReportRequest(BaseJobRequest):
    report_type: str = Field(..., description="CAMPAIGN_PERFORMANCE, INFLUENCER_BENCHMARK, or CAMPAIGN_PROPOSAL")
    report_data: Dict[str, Any] = Field(..., description="All structured data for rendering charts and report HTML")
    theme: Optional[str] = "dark"
    primary_color: Optional[str] = "#3B82F6"

class JobResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: datetime
    message: str = "Job accepted and queued for processing"

class JobDetailResponse(BaseModel):
    id: str
    client_id: str
    job_type: str
    status: str
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    callback_url: Optional[str] = None
    cost_credits: float = 0.0
    error_message: Optional[str] = None
    diagnostic_code: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
