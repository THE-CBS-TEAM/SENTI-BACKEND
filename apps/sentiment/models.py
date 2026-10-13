from django.db import models
from apps.campaigns.models import TrackedPost


class Comment(models.Model):
    class Sentiments(models.TextChoices):
        POSITIVE = 'POS', 'Positive'
        NEUTRAL = 'NEU', 'Neutral'
        NEGATIVE = 'NEG', 'Negative'

    class Emotions(models.TextChoices):
        EXCITED = 'EXCITED', 'Excited'
        HAPPY = 'HAPPY', 'Happy'
        CURIOUS = 'CURIOUS', 'Curious'
        DISAPPOINTED = 'DISAPPOINTED', 'Disappointed'
        ANGRY = 'ANGRY', 'Angry'
        INSPIRED = 'INSPIRED', 'Inspired'
        NEUTRAL = 'NEUTRAL', 'Neutral'

    tracked_post = models.ForeignKey(
        TrackedPost,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    platform_comment_id = models.CharField(max_length=255)
    author_handle = models.CharField(max_length=255, blank=True, null=True)
    text = models.TextField()
    
    # NLP Outcomes
    sentiment = models.CharField(
        max_length=3,
        choices=Sentiments.choices,
        default=Sentiments.NEUTRAL
    )
    emotion_category = models.CharField(
        max_length=15,
        choices=Emotions.choices,
        default=Emotions.NEUTRAL
    )
    
    brand_mentioned = models.BooleanField(default=False)
    brand_sentiment = models.CharField(
        max_length=3,
        choices=Sentiments.choices,
        blank=True,
        null=True
    )
    
    # C3 Comment Quality & Pod Detection Flags
    is_substantive = models.BooleanField(default=True)
    is_pod_flagged = models.BooleanField(default=False)
    
    processed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField()  # Ingested platform comment created date

    class Meta:
        ordering = ['-created_at']
        # We can add standard Django indexes, GIN index will be added in migration
        indexes = [
            models.Index(fields=['sentiment'], name='idx_comment_sentiment'),
            models.Index(fields=['brand_mentioned'], name='idx_comment_brand_ment'),
            models.Index(fields=['tracked_post', '-created_at']),
            models.Index(fields=['platform_comment_id']),
        ]

    def __str__(self):
        return f"{self.author_handle or 'Anon'}: {self.text[:30]}"


class OrganicComment(models.Model):
    """Sentiment-analyzed comments from organic (non-campaign) posts."""
    organic_post = models.ForeignKey(
        'influencers.OrganicBenchmark',
        on_delete=models.CASCADE,
        related_name='organic_comments'
    )
    platform_comment_id = models.CharField(max_length=255)
    author_handle = models.CharField(max_length=255, blank=True, null=True)
    text = models.TextField()
    
    sentiment = models.CharField(
        max_length=3,
        choices=Comment.Sentiments.choices,
        default=Comment.Sentiments.NEUTRAL
    )
    emotion_category = models.CharField(
        max_length=15,
        choices=Comment.Emotions.choices,
        default=Comment.Emotions.NEUTRAL
    )
    
    is_substantive = models.BooleanField(default=True)
    is_pod_flagged = models.BooleanField(default=False)
    
    processed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sentiment'], name='idx_orgcomment_sentiment'),
            models.Index(fields=['organic_post', '-created_at']),
            models.Index(fields=['platform_comment_id']),
        ]

    def __str__(self):
        return f"Organic: {self.author_handle or 'Anon'}: {self.text[:30]}"
