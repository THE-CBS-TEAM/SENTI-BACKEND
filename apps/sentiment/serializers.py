from rest_framework import serializers
from apps.sentiment.models import Comment


class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = (
            'id', 'tracked_post', 'platform_comment_id', 'author_handle', 
            'text', 'sentiment', 'emotion_category', 
            'brand_mentioned', 'brand_sentiment', 'processed_at', 'created_at'
        )
