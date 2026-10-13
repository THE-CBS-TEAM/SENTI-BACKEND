from celery import Celery
from app.config import settings

celery_app = Celery(
    "sentimentri_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.fetch_tasks",
        "app.tasks.sentiment_tasks",
        "app.tasks.scoring_tasks",
        "app.tasks.report_tasks",
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_routes={
        "app.tasks.fetch_tasks.*": {"queue": "worker_fetch"},
        "app.tasks.sentiment_tasks.*": {"queue": "worker_sentiment"},
        "app.tasks.scoring_tasks.*": {"queue": "worker_scoring"},
        "app.tasks.report_tasks.*": {"queue": "worker_reports"},
    },
    beat_schedule={
        # Periodic tasks like scheduled polling can be configured here
    }
)
