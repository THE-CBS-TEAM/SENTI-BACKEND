import logging
from datetime import datetime, timezone
from app.core.celery_app import celery_app
from app.database import SessionLocal
from app.models.job import Job
from app.services.scoring_engine import scoring_engine
from app.services.webhook_dispatcher import dispatch_webhook

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def task_calculate_score(self, job_id: str):
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        db.close()
        return

    try:
        job.status = "PROCESSING"
        db.commit()

        payload = job.payload or {}
        platform_metrics = payload.get("platform_metrics", [])

        # Calculate composite Centi/Senti score
        score_data = scoring_engine.calculate_centi_score(platform_metrics)

        job.status = "SUCCESS"
        job.result = score_data
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "SUCCESS", score_data)

    except Exception as exc:
        logger.error(f"Error in task_calculate_score {job_id}: {str(exc)}")
        job.status = "FAILED"
        job.error_message = str(exc)
        db.commit()
        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "FAILED", {}, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
