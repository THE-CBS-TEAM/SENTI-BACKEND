import logging
from celery import shared_task
from django.utils import timezone
from apps.influencers.models import Influencer
from apps.scoring.services.calculator import CentiScoreCalculator
from apps.scoring.services.fake_follower import FakeFollowerDetector

logger = logging.getLogger(__name__)


@shared_task(queue='scoring')
def calculate_centi_score_task(influencer_id):
    """Calculates fake follower score first, then calculates full Centi Score."""
    logger.info(f"Triggered Centi Score recalculation task for influencer {influencer_id}")
    
    # 1. Run Fake Follower / Bot analysis
    FakeFollowerDetector.analyze_authenticity(influencer_id)
    
    # 2. Run Centi Score calculations
    score = CentiScoreCalculator.calculate_centi_score(influencer_id)
    
    # Update fetch success timestamp after scoring completes
    Influencer.objects.filter(id=influencer_id).update(
        last_successful_fetch_at=timezone.now(),
        consecutive_fetch_failures=0,
        last_fetch_error=None
    )
    return score


@shared_task(queue='scoring')
def recalculate_all_centi_scores_daily():
    """Daily job to refresh Centi Scores and historical logging across the system."""
    count = Influencer.objects.count()
    logger.info(f"Daily scoring job triggered. Recalculating {count} creator scores.")
    for inf in Influencer.objects.all().iterator(chunk_size=100):
        calculate_centi_score_task.delay(inf.id)
    return count
