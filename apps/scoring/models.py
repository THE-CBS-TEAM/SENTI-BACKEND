from django.db import models
from apps.influencers.models import Influencer


class CentiScoreHistory(models.Model):
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.CASCADE,
        related_name='centi_score_history'
    )
    score = models.IntegerField()
    components = models.JSONField()  # Break down of inputs: engagement_authenticity, sentiment_quality, fake_follower_rating, content_consistency, audience_relevance, brand_alignment, historical_campaign_performance
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-calculated_at']

    def __str__(self):
        return f"{self.influencer.display_name} - {self.score} at {self.calculated_at.date()}"


class SentiScoreHistory(models.Model):
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.CASCADE,
        related_name='senti_score_history'
    )
    score = models.IntegerField()
    senti_label = models.CharField(max_length=30, default='AVERAGE')
    components = models.JSONField()  # Breakdown: c1_net_sentiment, c2_resonance_efficiency, c3_comment_quality, c4_posting_consistency
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-calculated_at']

    def __str__(self):
        return f"{self.influencer.display_name} - {self.score} ({self.senti_label}) at {self.calculated_at.date()}"


class AuthenticityScoreHistory(models.Model):
    influencer = models.ForeignKey(
        'influencers.Influencer',
        on_delete=models.CASCADE,
        related_name='authenticity_history'
    )
    overall_score = models.IntegerField()
    confidence = models.CharField(max_length=10, default='LOW')  # LOW, MEDIUM, HIGH
    platform_scores = models.JSONField(default=dict)  # {"IG": 85, "TT": 42, "X": 91}
    signal_breakdown = models.JSONField(default=dict)  # {s1: {score, weight, label, detail, grade}, ...}
    risk_flags = models.JSONField(default=list)  # [{severity, code, message, platform}]
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-calculated_at']

    def __str__(self):
        return f"{self.influencer.display_name} - Authenticity {self.overall_score}% at {self.calculated_at.date()}"
