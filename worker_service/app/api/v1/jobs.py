from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.core.security import verify_api_key
from app.models.job import Job
from app.schemas.job import (
    FetchProfileRequest,
    AnalyzeSentimentRequest,
    CalculateScoreRequest,
    GenerateReportRequest,
    JobResponse,
    JobDetailResponse
)
from app.tasks.fetch_tasks import task_fetch_profile
from app.tasks.sentiment_tasks import task_analyze_sentiment
from app.tasks.scoring_tasks import task_calculate_score
from app.tasks.report_tasks import task_generate_report

router = APIRouter(prefix="/jobs", tags=["Jobs & Intelligence Tasks"], dependencies=[Depends(verify_api_key)])

@router.post("/fetch-creator", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def queue_fetch_creator(payload: FetchProfileRequest, db: Session = Depends(get_db)):
    job = Job(
        client_id=payload.client_id,
        job_type="FETCH_PROFILE",
        payload=payload.dict(),
        callback_url=payload.callback_url,
        status="QUEUED"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue Celery task
    task_fetch_profile.delay(job.id)

    return JobResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        created_at=job.created_at
    )

@router.post("/analyze-sentiment", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def queue_analyze_sentiment(payload: AnalyzeSentimentRequest, db: Session = Depends(get_db)):
    job = Job(
        client_id=payload.client_id,
        job_type="ANALYZE_SENTIMENT",
        payload=payload.dict(),
        callback_url=payload.callback_url,
        status="QUEUED"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task_analyze_sentiment.delay(job.id)

    return JobResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        created_at=job.created_at
    )

@router.post("/calculate-score", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def queue_calculate_score(payload: CalculateScoreRequest, db: Session = Depends(get_db)):
    job = Job(
        client_id=payload.client_id,
        job_type="CALCULATE_SCORE",
        payload=payload.dict(),
        callback_url=payload.callback_url,
        status="QUEUED"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task_calculate_score.delay(job.id)

    return JobResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        created_at=job.created_at
    )

@router.post("/generate-report", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def queue_generate_report(payload: GenerateReportRequest, db: Session = Depends(get_db)):
    job = Job(
        client_id=payload.client_id,
        job_type="GENERATE_REPORT",
        payload=payload.dict(),
        callback_url=payload.callback_url,
        status="QUEUED"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task_generate_report.delay(job.id)

    return JobResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        created_at=job.created_at
    )

@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.get("", response_model=List[JobDetailResponse])
def list_jobs(limit: int = 50, skip: int = 0, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).offset(skip).limit(limit).all()
    return jobs
