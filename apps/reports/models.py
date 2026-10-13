from django.db import models
from apps.accounts.models import User
from apps.campaigns.models import Campaign


class GeneratedReport(models.Model):
    class ReportTypes(models.TextChoices):
        CAMPAIGN_PERFORMANCE = 'CAMPAIGN_PERFORMANCE', 'Campaign Performance'
        INFLUENCER_BENCHMARK = 'INFLUENCER_BENCHMARK', 'Influencer Benchmark'
        SENTIMENT_ANALYSIS = 'SENTIMENT_ANALYSIS', 'Sentiment Analysis'
        CAMPAIGN_PROPOSAL = 'CAMPAIGN_PROPOSAL', 'Campaign Proposal'

    class ReportStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='reports',
        blank=True,
        null=True
    )
    report_type = models.CharField(
        max_length=30,
        choices=ReportTypes.choices,
        default=ReportTypes.CAMPAIGN_PERFORMANCE
    )
    status = models.CharField(
        max_length=15,
        choices=ReportStatus.choices,
        default=ReportStatus.PENDING,
    )
    file_path = models.CharField(max_length=1000, blank=True, default='')
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='generated_reports',
        null=True
    )

    def __str__(self):
        return f"{self.report_type} - {self.file_path}"


class ReportDraft(models.Model):
    """
    Stores user-edited overrides for campaign report sections.
    When a user edits content in the Report Preview, changes are saved here.
    The PDF generator checks for a draft and uses any non-empty overrides
    instead of the auto-generated LLM content.
    """
    campaign = models.OneToOneField(
        Campaign,
        on_delete=models.CASCADE,
        related_name='report_draft'
    )

    # Section 1: Executive Summary
    executive_summary_insight = models.TextField(blank=True, default='')

    # Section 2: Platform Performance
    platform_performance_insight = models.TextField(blank=True, default='')

    # Section 3: Sentiment Analysis
    sentiment_analysis_insight = models.TextField(blank=True, default='')
    positive_comments_summary = models.TextField(blank=True, default='')
    negative_comments_summary = models.TextField(blank=True, default='')

    # Section 4: Brand Mentions
    brand_mentions_insight = models.TextField(blank=True, default='')
    brand_positive_qualitative = models.TextField(blank=True, default='')
    brand_negative_qualitative = models.TextField(blank=True, default='')

    # Section 5: Creator Performance
    creator_performance_insight = models.TextField(blank=True, default='')

    # Section 6: Creator Insights (Native vs Campaign)
    creator_native_vs_campaign_insight = models.TextField(blank=True, default='')

    # Section 7: Campaign Intelligence
    campaign_intelligence_insight = models.TextField(blank=True, default='')
    campaign_intelligence_answers = models.JSONField(default=dict, blank=True)

    # Section 8: Recommendations
    recommendations = models.JSONField(default=list, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Report Draft'
        verbose_name_plural = 'Report Drafts'

    def __str__(self):
        return f"Report Draft - {self.campaign.name}"
