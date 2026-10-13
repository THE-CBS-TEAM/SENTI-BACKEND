from django.contrib import admin
from apps.sentiment.models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('author_handle', 'tracked_post', 'sentiment', 'emotion_category', 'brand_mentioned', 'brand_sentiment', 'created_at')
    list_filter = ('sentiment', 'emotion_category', 'brand_mentioned', 'brand_sentiment')
    search_fields = ('author_handle', 'text')
