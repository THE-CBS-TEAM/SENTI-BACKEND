from django.db import models
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import Workspace


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL INFLUENCER CATALOG
# ─────────────────────────────────────────────────────────────────────────────

class GlobalInfluencer(models.Model):
    """
    Platform-wide influencer catalog — shared across ALL workspaces.

    When a user searches for an influencer and it exists here, no new API call
    is made. The workspace simply gets a WorkspaceInfluencer link.

    Data freshness:
      - data_expires_at = last_scraped_at + 24 hours.
      - If stale: return cached data immediately for UX, then queue background
        refresh via refresh_global_influencer_task.
      - Background refresh also re-runs DeepSeek analysis and updates the cache.
    """
    display_name = models.CharField(max_length=255)
    niche = models.CharField(max_length=100, blank=True, null=True)
    avatar_url = models.URLField(max_length=1000, blank=True, null=True)

    # Platform handles — unique constraints enforce one global record per handle
    ig_handle = models.CharField(max_length=100, blank=True, null=True, unique=True)
    tiktok_handle = models.CharField(max_length=100, blank=True, null=True, unique=True)
    x_handle = models.CharField(max_length=100, blank=True, null=True, unique=True)

    # Aggregated Senti scores
    centi_score = models.IntegerField(default=0)      # Deprecated alias, kept for compat
    senti_score = models.IntegerField(default=0)
    sentiment_rating = models.CharField(max_length=20, default='NEUTRAL')  # Deprecated alias
    senti_label = models.CharField(max_length=30, default='AVERAGE')       # ELITE, STRONG, AVERAGE, BELOW_AVG, POOR
    fake_follower_score = models.IntegerField(default=0)
    consistency_score = models.IntegerField(default=0)
    reach_score = models.IntegerField(default=0)
    authenticity_confidence = models.CharField(max_length=10, default='LOW')
    authenticity_risk_flags = models.JSONField(default=list, blank=True)

    # DeepSeek analysis cache — avoids rerunning expensive LLM calls
    # when multiple workspaces use the same influencer.
    deepseek_summary = models.JSONField(blank=True, null=True)
    deepseek_analysis = models.JSONField(blank=True, null=True)
    deepseek_analyzed_at = models.DateTimeField(blank=True, null=True)

    # Data freshness tracking
    last_scraped_at = models.DateTimeField(blank=True, null=True)
    data_expires_at = models.DateTimeField(blank=True, null=True)   # last_scraped + 24h
    scrape_in_progress = models.BooleanField(default=False)

    # Sync tracking
    next_poll_at = models.DateTimeField(blank=True, null=True)
    last_fetch_attempt_at = models.DateTimeField(blank=True, null=True)
    last_successful_fetch_at = models.DateTimeField(blank=True, null=True)
    last_fetch_error = models.TextField(blank=True, null=True)
    consecutive_fetch_failures = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.display_name

    @property
    def age_hours(self):
        """Hours elapsed since last scraped, or None if never scraped."""
        if not self.last_scraped_at:
            return None
        return round((timezone.now() - self.last_scraped_at).total_seconds() / 3600.0, 1)

    @property
    def age_display(self):
        """Human-readable age string, e.g. '3 hours old', '2 days old'."""
        from apps.influencers.utils import format_age_display
        return format_age_display(self.last_scraped_at)

    @property
    def is_data_stale(self):
        """True if data is older than the configured staleness threshold in hours."""
        if not self.last_scraped_at:
            return True
        from apps.influencers.utils import get_influencer_staleness_hours
        threshold_hours = get_influencer_staleness_hours()
        return timezone.now() > (self.last_scraped_at + timedelta(hours=threshold_hours))

    @property
    def data_freshness(self):
        """Human-readable data freshness label for API responses."""
        if not self.last_scraped_at:
            return 'never_scraped'
        if self.is_data_stale:
            return 'stale'
        return 'fresh'

    def mark_scraped(self):
        """Call after a successful SociaVault fetch to reset freshness window using configured threshold."""
        from apps.influencers.utils import get_influencer_staleness_hours
        threshold_hours = get_influencer_staleness_hours()
        now = timezone.now()
        self.last_scraped_at = now
        self.data_expires_at = now + timedelta(hours=threshold_hours)
        self.last_successful_fetch_at = now
        self.scrape_in_progress = False
        self.consecutive_fetch_failures = 0
        self.save(update_fields=[
            'last_scraped_at', 'data_expires_at', 'last_successful_fetch_at',
            'scrape_in_progress', 'consecutive_fetch_failures',
        ])

    def clean_handles(self):
        """Sanitizes all social handles by stripping full URLs, query params, @, and invalid symbols."""
        from apps.influencers.utils import sanitize_social_handle
        if self.ig_handle:
            self.ig_handle = sanitize_social_handle(self.ig_handle) or None
        if self.tiktok_handle:
            self.tiktok_handle = sanitize_social_handle(self.tiktok_handle) or None
        if self.x_handle:
            self.x_handle = sanitize_social_handle(self.x_handle) or None

    def save(self, *args, **kwargs):
        self.clean_handles()
        super().save(*args, **kwargs)


class WorkspaceInfluencer(models.Model):
    """
    Junction table linking a GlobalInfluencer to a specific Workspace.

    When a user adds an influencer, we create this record pointing to the
    shared GlobalInfluencer — no data is duplicated, no extra API call needed.
    """
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='workspace_influencers'
    )
    global_influencer = models.ForeignKey(
        GlobalInfluencer,
        on_delete=models.CASCADE,
        related_name='workspace_links'
    )
    added_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('workspace', 'global_influencer')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.global_influencer.display_name} in {self.workspace.name}"


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY WORKSPACE-SCOPED INFLUENCER
# Kept for backward compatibility during the migration period.
# New code should use GlobalInfluencer + WorkspaceInfluencer.
# ─────────────────────────────────────────────────────────────────────────────

class Influencer(models.Model):
    """
    DEPRECATED — workspace-scoped influencer record.
    Replaced by GlobalInfluencer + WorkspaceInfluencer.
    Retained to avoid breaking existing campaign FKs during migration.
    """
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='influencers'
    )
    # FK to the global record — set during migration, None for old records
    global_influencer = models.ForeignKey(
        GlobalInfluencer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='legacy_records',
        help_text='Points to the GlobalInfluencer record created during migration.'
    )
    display_name = models.CharField(max_length=255)
    niche = models.CharField(max_length=100, blank=True, null=True)
    avatar_url = models.URLField(max_length=1000, blank=True, null=True)
    ig_handle = models.CharField(max_length=100, blank=True, null=True)
    tiktok_handle = models.CharField(max_length=100, blank=True, null=True)
    x_handle = models.CharField(max_length=100, blank=True, null=True)

    # Aggregated metrics
    centi_score = models.IntegerField(default=0)  # Deprecated alias
    senti_score = models.IntegerField(default=0)
    sentiment_rating = models.CharField(max_length=20, default='NEUTRAL')  # Deprecated alias
    senti_label = models.CharField(max_length=30, default='AVERAGE')
    fake_follower_score = models.IntegerField(default=0)
    consistency_score = models.IntegerField(default=0)
    reach_score = models.IntegerField(default=0)
    authenticity_confidence = models.CharField(max_length=10, default='LOW')
    authenticity_risk_flags = models.JSONField(default=list, blank=True)

    # Sync tracking fields
    next_poll_at = models.DateTimeField(blank=True, null=True)
    last_fetch_attempt_at = models.DateTimeField(blank=True, null=True)
    last_successful_fetch_at = models.DateTimeField(blank=True, null=True)
    last_fetch_error = models.TextField(blank=True, null=True)
    consecutive_fetch_failures = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean_handles(self):
        """Sanitizes all social handles by stripping full URLs, query params, @, and invalid symbols."""
        from apps.influencers.utils import sanitize_social_handle
        if self.ig_handle:
            self.ig_handle = sanitize_social_handle(self.ig_handle) or None
        if self.tiktok_handle:
            self.tiktok_handle = sanitize_social_handle(self.tiktok_handle) or None
        if self.x_handle:
            self.x_handle = sanitize_social_handle(self.x_handle) or None

    def save(self, *args, **kwargs):
        self.clean_handles()
        super().save(*args, **kwargs)
        # If linked to a GlobalInfluencer, synchronize the sanitized handles to the GlobalInfluencer as well
        if self.global_influencer_id:
            gi = self.global_influencer
            updated_fields = []
            if self.ig_handle and gi.ig_handle != self.ig_handle:
                gi.ig_handle = self.ig_handle
                updated_fields.append('ig_handle')
            if self.tiktok_handle and gi.tiktok_handle != self.tiktok_handle:
                gi.tiktok_handle = self.tiktok_handle
                updated_fields.append('tiktok_handle')
            if self.x_handle and gi.x_handle != self.x_handle:
                gi.x_handle = self.x_handle
                updated_fields.append('x_handle')
            if updated_fields:
                gi.clean_handles()
                gi.save(update_fields=updated_fields)

    def __str__(self):
        return self.display_name


# ─────────────────────────────────────────────────────────────────────────────
# PLATFORM METRICS
# ─────────────────────────────────────────────────────────────────────────────

class PlatformMetrics(models.Model):
    class Platforms(models.TextChoices):
        INSTAGRAM = 'IG', 'Instagram'
        TIKTOK = 'TT', 'TikTok'
        X = 'X', 'Twitter/X'

    # FK to GlobalInfluencer (preferred) — legacy Influencer FK kept for migration
    global_influencer = models.ForeignKey(
        GlobalInfluencer,
        on_delete=models.CASCADE,
        related_name='platform_metrics',
        null=True,
        blank=True,
    )
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.CASCADE,
        related_name='platform_metrics',
        null=True,
        blank=True,
    )
    platform = models.CharField(max_length=2, choices=Platforms.choices)
    followers = models.IntegerField(default=0)
    engagement_rate = models.FloatField(default=0.0)
    avg_views = models.IntegerField(default=0)
    avg_likes = models.IntegerField(default=0)
    avg_comments = models.IntegerField(default=0)
    avg_shares = models.IntegerField(default=0)
    avg_saves = models.IntegerField(default=0)
    avg_reposts = models.IntegerField(default=0)
    aar = models.FloatField(default=0.0)             # Audience Activity Rate
    cr = models.FloatField(default=0.0)              # Content Resonance
    resonance_efficiency = models.FloatField(default=0.0)
    raw_api_response = models.JSONField(blank=True, null=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Allow one metrics row per influencer per platform (using global FK)
        constraints = [
            models.UniqueConstraint(
                fields=['global_influencer', 'platform'],
                condition=models.Q(global_influencer__isnull=False),
                name='unique_global_influencer_platform'
            ),
        ]

    def __str__(self):
        name = (
            self.global_influencer.display_name
            if self.global_influencer
            else (self.influencer.display_name if self.influencer else '?')
        )
        return f"{name} - {self.platform} Metrics"


class OrganicBenchmark(models.Model):
    class Platforms(models.TextChoices):
        INSTAGRAM = 'IG', 'Instagram'
        TIKTOK = 'TT', 'TikTok'
        X = 'X', 'Twitter/X'

    # FK to GlobalInfluencer (preferred) — legacy Influencer FK kept for migration
    global_influencer = models.ForeignKey(
        GlobalInfluencer,
        on_delete=models.CASCADE,
        related_name='organic_benchmarks',
        null=True,
        blank=True,
    )
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.CASCADE,
        related_name='organic_benchmarks',
        null=True,
        blank=True,
    )
    platform = models.CharField(max_length=2, choices=Platforms.choices)
    post_url = models.URLField(max_length=1000)
    views = models.IntegerField(default=0)
    likes = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)
    saves = models.IntegerField(default=0)
    reposts = models.IntegerField(default=0)
    engagement_total = models.FloatField(default=0.0)
    sentiment_positive = models.IntegerField(default=0)
    sentiment_neutral = models.IntegerField(default=0)
    sentiment_negative = models.IntegerField(default=0)
    post_text = models.TextField(blank=True, null=True)
    post_created_at = models.DateTimeField(blank=True, null=True)
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        name = (
            self.global_influencer.display_name
            if self.global_influencer
            else (self.influencer.display_name if self.influencer else '?')
        )
        return f"{name} - {self.platform} Organic Benchmark"


# ─────────────────────────────────────────────────────────────────────────────
# FETCH JOB (Legacy job tracker — now supplemented by ApiCostLog)
# ─────────────────────────────────────────────────────────────────────────────

class FetchJob(models.Model):
    class Providers(models.TextChoices):
        APIFY = 'APIFY', 'Apify'
        SOCIALDATA = 'SOCIALDATA', 'SocialData'
        SOCIAVAULT = 'SOCIAVAULT', 'SociaVault'

    class Statuses(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        RUNNING = 'RUNNING', 'Running'
        DONE = 'DONE', 'Done'
        FAIL = 'FAIL', 'Failed'

    entity_type = models.CharField(max_length=50)   # e.g., 'GLOBAL_INFLUENCER', 'POST'
    entity_id = models.IntegerField()               # PK of the target entity
    provider = models.CharField(max_length=15, choices=Providers.choices)
    status = models.CharField(
        max_length=15,
        choices=Statuses.choices,
        default=Statuses.PENDING
    )
    cost_credits = models.DecimalField(max_digits=8, decimal_places=4, default=0.0000)
    raw_response = models.JSONField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.provider} Job ({self.entity_type} {self.entity_id}) - {self.status}"

    @classmethod
    def is_daily_cap_exceeded(cls, estimate_cost=0.0):
        from django.conf import settings
        from django.db.models import Sum

        cap = float(getattr(settings, 'DAILY_CREDIT_BUDGET_CAP', 50.00))
        cutoff = timezone.now() - timedelta(hours=24)
        total_used = cls.objects.filter(
            created_at__gte=cutoff
        ).aggregate(total=Sum('cost_credits'))['total'] or 0.0
        return (float(total_used) + float(estimate_cost)) > cap


# ─────────────────────────────────────────────────────────────────────────────
# API COST LOG — Unified external API call accounting
# ─────────────────────────────────────────────────────────────────────────────

class ApiCostLog(models.Model):
    """
    Records every external API call for full admin visibility and billing prep.

    Every SociaVault, DeepSeek, and Worker call writes a row here.
    Tagged with workspace, global_influencer, campaign, pipeline_stage, and
    cost_category so the admin can see exact per-campaign pipeline costs from
    proposal → active monitoring → final executive report.
    """

    class Providers(models.TextChoices):
        SOCIAVAULT = 'SOCIAVAULT', 'SociaVault'
        DEEPSEEK = 'DEEPSEEK', 'DeepSeek'
        APIFY = 'APIFY', 'Apify (Legacy)'
        SOCIALDATA = 'SOCIALDATA', 'SocialData (Legacy)'
        WORKER = 'WORKER', 'Internal Worker'

    class PipelineStages(models.TextChoices):
        PROPOSAL = 'PROPOSAL', 'Proposal Generation'
        MONITORING = 'MONITORING', 'Active Campaign Monitoring'
        EXECUTIVE_REPORT = 'EXECUTIVE_REPORT', 'Final Executive Report'
        STANDALONE = 'STANDALONE', 'Standalone / Ad-Hoc'

    class CostCategories(models.TextChoices):
        SOCIAVAULT_PROFILE = 'SOCIAVAULT_PROFILE', 'SociaVault Profile Scrape'
        SOCIAVAULT_POSTS = 'SOCIAVAULT_POSTS', 'SociaVault Benchmark / Post Fetch'
        SOCIAVAULT_COMMENTS = 'SOCIAVAULT_COMMENTS', 'SociaVault Comments Scrape'
        DEEPSEEK_PROPOSAL = 'DEEPSEEK_PROPOSAL', 'DeepSeek Proposal Insights'
        DEEPSEEK_SENTIMENT = 'DEEPSEEK_SENTIMENT', 'DeepSeek Comments Sentiment'
        DEEPSEEK_AUDIT = 'DEEPSEEK_AUDIT', 'DeepSeek Executive Audit'
        PDF_GENERATION = 'PDF_GENERATION', 'PDF Report Generation'
        OTHER = 'OTHER', 'Other External Call'

    provider = models.CharField(max_length=20, choices=Providers.choices)
    endpoint = models.CharField(max_length=255)
    credits_used = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    # Tenancy & entity associations (all nullable — not every call has all context)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='api_cost_logs'
    )
    global_influencer = models.ForeignKey(
        GlobalInfluencer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='api_cost_logs'
    )
    campaign = models.ForeignKey(
        'campaigns.Campaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cost_logs'
    )

    # Pipeline tracking — what stage of the campaign lifecycle triggered this call?
    pipeline_stage = models.CharField(
        max_length=30,
        choices=PipelineStages.choices,
        default=PipelineStages.STANDALONE
    )
    cost_category = models.CharField(
        max_length=40,
        choices=CostCategories.choices,
        default=CostCategories.OTHER
    )

    response_time_ms = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['campaign', 'pipeline_stage']),
            models.Index(fields=['workspace', 'created_at']),
            models.Index(fields=['provider', 'created_at']),
        ]

    def __str__(self):
        return f"{self.provider} / {self.endpoint} — ${self.cost_usd} [{self.pipeline_stage}]"
