import logging
from django.utils import timezone
from apps.campaigns.models import Campaign

logger = logging.getLogger(__name__)


class CampaignLifecycleManager:
    @classmethod
    def activate_campaign(cls, campaign_id):
        """Transitions a campaign from DRAFT to ACTIVE."""
        try:
            campaign = Campaign.objects.get(pk=campaign_id)
        except Campaign.DoesNotExist:
            return False

        if campaign.status == Campaign.Statuses.DRAFT:
            campaign.status = Campaign.Statuses.ACTIVE
            campaign.save()
            logger.info(f"Campaign {campaign.name} is now ACTIVE.")
            
            # Start tracking the posts (Celery task will start polling)
            return True
        return False

    @classmethod
    def complete_campaign(cls, campaign_id):
        """Transitions a campaign to COMPLETED and generates reports."""
        try:
            campaign = Campaign.objects.get(pk=campaign_id)
        except Campaign.DoesNotExist:
            return False

        if campaign.status == Campaign.Statuses.ACTIVE:
            campaign.status = Campaign.Statuses.COMPLETED
            campaign.save()
            logger.info(f"Campaign {campaign.name} is now COMPLETED.")

            # Trigger async post-campaign analysis report compilation
            from apps.reports.models import GeneratedReport
            # In celery tasks we will compile PDF, let's trigger it here
            return True
        return False

    @classmethod
    def check_campaign_dates(cls):
        """
        Periodic task helper. Activates campaigns whose start date is today,
        and completes campaigns whose end date is past.
        """
        today = timezone.now().date()
        
        # 1. Activate draft campaigns starting today
        drafts = Campaign.objects.filter(
            status=Campaign.Statuses.DRAFT,
            start_date__lte=today
        )
        for campaign in drafts:
            cls.activate_campaign(campaign.id)

        # 2. Complete active campaigns ending yesterday or earlier
        actives = Campaign.objects.filter(
            status=Campaign.Statuses.ACTIVE,
            end_date__lt=today
        )
        for campaign in actives:
            cls.complete_campaign(campaign.id)
