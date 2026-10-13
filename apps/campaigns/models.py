from django.db import models
from apps.accounts.models import Workspace, Brand
from apps.influencers.models import Influencer


class Campaign(models.Model):
    class Statuses(models.TextChoices):
        PROPOSAL = 'PROPOSAL', 'Proposal'
        APPROVED = 'APPROVED', 'Approved'
        DRAFT = 'DRAFT', 'Draft'  # Legacy status
        ACTIVE = 'ACTIVE', 'Active'
        STOPPED = 'STOPPED', 'Stopped'
        COMPLETED = 'COMPLETED', 'Completed'
        ARCHIVED = 'ARCHIVED', 'Archived'

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='campaigns'
    )
    name = models.CharField(max_length=255)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name='campaigns'
    )
    budget = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    currency = models.CharField(max_length=10, default='NGN')
    goal = models.TextField(blank=True, null=True)
    roi_estimate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    status = models.CharField(
        max_length=15,
        choices=Statuses.choices,
        default=Statuses.PROPOSAL
    )
    estimated_engagement = models.IntegerField(default=0)
    estimated_reach = models.IntegerField(default=0)
    estimated_views = models.IntegerField(default=0)
    estimated_aar = models.FloatField(default=0.0)
    estimated_cr = models.FloatField(default=0.0)
    estimated_re = models.FloatField(default=0.0)
    proposal_approved_at = models.DateTimeField(blank=True, null=True)
    
    # LLM Qualitative Analysis Fields
    llm_summary = models.TextField(blank=True, null=True)
    llm_public_opinion = models.TextField(blank=True, null=True)
    llm_prediction = models.TextField(blank=True, null=True)
    llm_top_positive_comments = models.JSONField(blank=True, null=True, default=list)
    llm_top_negative_comments = models.JSONField(blank=True, null=True, default=list)
    
    # Rich CreatorIQ-style proposal fields
    llm_positive_keywords = models.JSONField(blank=True, null=True, default=list)
    llm_negative_keywords = models.JSONField(blank=True, null=True, default=list)
    llm_creators_analysis = models.JSONField(blank=True, null=True, default=list)
    
    # LLM Execution Analysis Fields
    execution_llm_summary = models.TextField(blank=True, null=True)
    execution_llm_public_opinion = models.TextField(blank=True, null=True)
    execution_llm_next_steps = models.TextField(blank=True, null=True)
    execution_llm_positive_keywords = models.JSONField(blank=True, null=True, default=list)
    execution_llm_negative_keywords = models.JSONField(blank=True, null=True, default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.status})"


class CampaignInfluencer(models.Model):
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='campaign_influencers'
    )
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.CASCADE,
        related_name='campaign_assignments'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    estimated_engagement = models.IntegerField(default=0)
    estimated_reach = models.IntegerField(default=0)
    estimated_views = models.IntegerField(default=0)
    estimated_aar = models.FloatField(default=0.0)
    estimated_cr = models.FloatField(default=0.0)
    estimated_re = models.FloatField(default=0.0)

    # LLM Qualitative Analysis Fields
    llm_summary = models.TextField(blank=True, null=True)
    llm_public_opinion = models.TextField(blank=True, null=True)
    llm_prediction = models.TextField(blank=True, null=True)
    llm_top_positive_comments = models.JSONField(blank=True, null=True, default=list)
    llm_top_negative_comments = models.JSONField(blank=True, null=True, default=list)
    llm_positive_keywords = models.JSONField(blank=True, null=True, default=list)
    llm_negative_keywords = models.JSONField(blank=True, null=True, default=list)

    # LLM Execution Analysis Fields
    execution_llm_summary = models.TextField(blank=True, null=True)
    execution_llm_public_opinion = models.TextField(blank=True, null=True)
    execution_llm_next_steps = models.TextField(blank=True, null=True)
    execution_llm_positive_keywords = models.JSONField(blank=True, null=True, default=list)
    execution_llm_negative_keywords = models.JSONField(blank=True, null=True, default=list)

    class Meta:
        unique_together = ('campaign', 'influencer')

    def __str__(self):
        return f"{self.campaign.name} - {self.influencer.display_name}"


class TrackedPost(models.Model):
    class Platforms(models.TextChoices):
        INSTAGRAM = 'IG', 'Instagram'
        TIKTOK = 'TT', 'TikTok'
        X = 'X', 'Twitter/X'

    class Statuses(models.TextChoices):
        MONITORING = 'MONITORING', 'Monitoring'
        PAUSED = 'PAUSED', 'Paused'
        ARCHIVED = 'ARCHIVED', 'Archived'
        ERROR = 'ERROR', 'Error'

    class PollingTiers(models.TextChoices):
        T1 = 'T1', 'T1 (0-24h)'
        T2 = 'T2', 'T2 (24-72h)'
        T3 = 'T3', 'T3 (3-7d)'
        T4 = 'T4', 'T4 (8d+)'

    campaign_inf = models.ForeignKey(
        CampaignInfluencer,
        on_delete=models.CASCADE,
        related_name='tracked_posts'
    )
    platform = models.CharField(max_length=2, choices=Platforms.choices)
    post_url = models.URLField(max_length=1000)
    
    # Metrics
    views = models.IntegerField(default=0)
    likes = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)
    saves = models.IntegerField(default=0)
    retweets = models.IntegerField(default=0)
    watch_time_avg = models.FloatField(default=0.0)
    
    # Sentiment Counts
    sentiment_positive = models.IntegerField(default=0)
    sentiment_neutral = models.IntegerField(default=0)
    sentiment_negative = models.IntegerField(default=0)
    
    # Brand Sentiment Counts
    brand_sentiment_pos = models.IntegerField(default=0)
    brand_sentiment_neg = models.IntegerField(default=0)
    
    raw_api_response = models.JSONField(blank=True, null=True)
    status = models.CharField(
        max_length=15,
        choices=Statuses.choices,
        default=Statuses.MONITORING
    )
    polling_tier = models.CharField(
        max_length=2,
        choices=PollingTiers.choices,
        default=PollingTiers.T1
    )
    next_poll_at = models.DateTimeField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True, help_text='Original publication date on the social platform')
    created_at = models.DateTimeField(auto_now_add=True)
    last_fetched_at = models.DateTimeField(blank=True, null=True)
    last_fetch_attempt_at = models.DateTimeField(blank=True, null=True)
    last_successful_fetch_at = models.DateTimeField(blank=True, null=True)
    last_fetch_error = models.TextField(blank=True, null=True)
    consecutive_fetch_failures = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['status'], name='idx_trackedpost_status_mon', condition=models.Q(status='MONITORING')),
            models.Index(fields=['status']),
            models.Index(fields=['polling_tier']),
            models.Index(fields=['campaign_inf', 'status']),
            models.Index(fields=['next_poll_at']),
        ]

    def __str__(self):
        return f"{self.platform} Post - {self.post_url}"
