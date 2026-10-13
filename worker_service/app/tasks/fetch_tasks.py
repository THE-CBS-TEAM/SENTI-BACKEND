import logging
from datetime import datetime, timezone
from app.core.celery_app import celery_app
from app.database import SessionLocal
from app.models.job import Job
from app.services.apify_client import apify_client
from app.services.socialdata_client import socialdata_client
from app.services.webhook_dispatcher import dispatch_webhook

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def task_fetch_profile(self, job_id: str):
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        db.close()
        return

    try:
        job.status = "PROCESSING"
        db.commit()

        payload = job.payload or {}
        platform = payload.get("platform", "").upper()
        handle = payload.get("handle", "")

        if platform == "X":
            data = socialdata_client.fetch_user_profile(handle)
        else:
            data = apify_client.fetch_instagram_profile(handle)

        job.status = "SUCCESS"
        job.result = data
        job.cost_credits = 0.05
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        # Webhook callback
        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "SUCCESS", data)

    except Exception as exc:
        logger.error(f"Error in task_fetch_profile {job_id}: {str(exc)}")
        job.status = "FAILED"
        job.error_message = str(exc)
        db.commit()
        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "FAILED", {}, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
