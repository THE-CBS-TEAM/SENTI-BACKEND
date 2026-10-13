import logging
from datetime import datetime, timezone
from app.core.celery_app import celery_app
from app.database import SessionLocal
from app.models.job import Job
from app.services.sentiment_analyzer import analyzer
from app.services.deepseek_client import deepseek_client
from app.services.webhook_dispatcher import dispatch_webhook

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=2, default_retry_delay=15)
def task_analyze_sentiment(self, job_id: str):
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        db.close()
        return

    try:
        job.status = "PROCESSING"
        db.commit()

        payload = job.payload or {}
        comments = payload.get("comments", [])
        brand_name = payload.get("brand_name")
        use_llm = payload.get("use_llm", True)

        # 1. High-speed local sentiment, Pidgin, and emotion analysis
        batch_results = analyzer.analyze_batch(comments, brand_name=brand_name)

        # 2. Qualitative LLM insights via DeepSeek if requested
        llm_insights = {}
        if use_llm and comments:
            raw_texts = [c.get("text", "") for c in comments if c.get("text")]
            creator_name = payload.get("creator_name", "Creator")
            llm_insights = deepseek_client.generate_qualitative_insights(
                creator_name=creator_name,
                comments=raw_texts,
                brand_name=brand_name
            )

        final_result = {
            **batch_results,
            "qualitative_insights": llm_insights
        }

        job.status = "SUCCESS"
        job.result = final_result
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "SUCCESS", final_result)

    except Exception as exc:
        logger.error(f"Error in task_analyze_sentiment {job_id}: {str(exc)}")
        job.status = "FAILED"
        job.error_message = str(exc)
        db.commit()
        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "FAILED", {}, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
