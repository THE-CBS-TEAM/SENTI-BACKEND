from django.contrib import admin
from apps.campaigns.models import Campaign, CampaignInfluencer, TrackedPost


class CampaignInfluencerInline(admin.TabularInline):
    model = CampaignInfluencer
    extra = 0


class TrackedPostInline(admin.TabularInline):
    model = TrackedPost
    extra = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'brand', 'workspace', 'budget', 'status', 'start_date', 'end_date')
    list_filter = ('status', 'brand', 'workspace')
    search_fields = ('name', 'brand__name')
    inlines = [CampaignInfluencerInline]


@admin.register(CampaignInfluencer)
class CampaignInfluencerAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'influencer', 'fee', 'assigned_at')
    list_filter = ('campaign__brand',)
    inlines = [TrackedPostInline]


@admin.register(TrackedPost)
class TrackedPostAdmin(admin.ModelAdmin):
    list_display = ('post_url', 'platform', 'campaign_inf', 'status', 'polling_tier', 'likes', 'comments_count')
    list_filter = ('platform', 'status', 'polling_tier')
    search_fields = ('post_url',)
