import logging
from celery import shared_task
from django.utils import timezone
from apps.influencers.models import GlobalInfluencer
from apps.influencers.services.profile_fetcher import ProfileFetcher

logger = logging.getLogger(__name__)


@shared_task(queue='fetch')
def fetch_global_influencer_task(global_influencer_id):
    """
    Celery task to fetch, benchmark, and score a GlobalInfluencer from SociaVault.
    Called asynchronously when synchronous fetch exceeded 5s or was delayed.
    """
    logger.info(f"Running fetch_global_influencer_task for ID {global_influencer_id}")
    fetcher = ProfileFetcher()
    success = fetcher.fetch_and_benchmark_global_influencer(global_influencer_id)
    return success


@shared_task(queue='fetch')
def refresh_global_influencer_task(global_influencer_id):
    """
    Background refresh task for an influencer whose data is older than 24 hours.
    Fetches latest metrics from SociaVault and re-triggers DeepSeek analysis in the background
    without blocking user workflows.
    """
    logger.info(f"Running background refresh for stale GlobalInfluencer ID {global_influencer_id}")
    fetcher = ProfileFetcher()
    success = fetcher.fetch_and_benchmark_global_influencer(global_influencer_id)
    return success


@shared_task(queue='fetch')
def check_stale_influencers_scheduled():
    """
    Periodic job: identifies GlobalInfluencers with data older than 24 hours
    and queues refresh tasks.
    """
    now = timezone.now()
    stale_influencers = GlobalInfluencer.objects.filter(
        data_expires_at__lt=now,
        scrape_in_progress=False
    ).exclude(
        consecutive_fetch_failures__gte=5
    )[:25]

    queued_count = 0
    for inf in stale_influencers:
        inf.scrape_in_progress = True
        inf.save(update_fields=['scrape_in_progress'])
        refresh_global_influencer_task.delay(inf.id)
        queued_count += 1

    logger.info(f"Scheduled freshness check: queued {queued_count} stale influencers for background update.")
    return queued_count
