import os
import logging
from datetime import datetime, timezone
from app.core.celery_app import celery_app
from app.database import SessionLocal
from app.models.job import Job
from app.config import settings
from app.services.webhook_dispatcher import dispatch_webhook

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=1)
def task_generate_report(self, job_id: str):
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        db.close()
        return

    try:
        job.status = "PROCESSING"
        db.commit()

        payload = job.payload or {}
        report_type = payload.get("report_type", "CAMPAIGN_PERFORMANCE")
        report_data = payload.get("report_data", {})

        # Generates a report key / path
        filename = f"report_{job_id}.pdf"
        output_dir = "/tmp/reports"
        os.makedirs(output_dir, exist_ok=True)
        local_path = os.path.join(output_dir, filename)

        # Basic HTML template generation for testing / fallback
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Sentimentri Report</title></head>
        <body style="font-family: Arial, sans-serif; padding: 40px; background: #0F172A; color: #F8FAFC;">
            <h1 style="color: #38BDF8;">Sentimentri Intelligence Report</h1>
            <p><strong>Type:</strong> {report_type}</p>
            <p><strong>Generated At:</strong> {datetime.now(timezone.utc).isoformat()}</p>
            <hr style="border-color: #334155;"/>
            <h3>Summary</h3>
            <pre style="background: #1E293B; padding: 15px; border-radius: 8px;">{report_data.get('summary', 'No summary provided')}</pre>
        </body>
        </html>
        """

        try:
            import weasyprint
            weasyprint.HTML(string=html_content).write_pdf(local_path)
            file_url = f"/media/reports/{filename}"
        except Exception as wp_err:
            logger.warning(f"WeasyPrint fallback to dummy write: {wp_err}")
            with open(local_path, "w") as f:
                f.write(html_content)
            file_url = f"/media/reports/{filename}"

        # If S3 is enabled, upload to bucket
        if settings.S3_ENABLED and settings.S3_ACCESS_KEY_ID:
            try:
                import boto3
                s3 = boto3.client(
                    "s3",
                    aws_access_key_id=settings.S3_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
                    endpoint_url=settings.S3_ENDPOINT_URL or None,
                    region_name=settings.S3_REGION
                )
                s3.upload_file(local_path, settings.S3_BUCKET_NAME, f"reports/{filename}")
                file_url = f"https://{settings.S3_BUCKET_NAME}.s3.amazonaws.com/reports/{filename}"
            except Exception as s3_err:
                logger.error(f"S3 upload failed: {s3_err}")

        result_data = {
            "report_url": file_url,
            "filename": filename,
            "report_type": report_type
        }

        job.status = "SUCCESS"
        job.result = result_data
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "SUCCESS", result_data)

    except Exception as exc:
        logger.error(f"Error in task_generate_report {job_id}: {str(exc)}")
        job.status = "FAILED"
        job.error_message = str(exc)
        db.commit()
        if job.callback_url:
            dispatch_webhook(job.callback_url, job.id, "FAILED", {}, error=str(exc))
        raise
    finally:
        db.close()
