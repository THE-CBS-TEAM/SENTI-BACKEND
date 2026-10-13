from django.contrib import admin
from apps.influencers.models import Influencer, PlatformMetrics, OrganicBenchmark, FetchJob


class PlatformMetricsInline(admin.TabularInline):
    model = PlatformMetrics
    extra = 0


class OrganicBenchmarkInline(admin.TabularInline):
    model = OrganicBenchmark
    extra = 0


@admin.register(Influencer)
class InfluencerAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'workspace', 'centi_score', 'sentiment_rating', 'fake_follower_score', 'created_at')
    list_filter = ('sentiment_rating', 'workspace')
    search_fields = ('display_name', 'ig_handle', 'tiktok_handle', 'x_handle')
    inlines = [PlatformMetricsInline, OrganicBenchmarkInline]


@admin.register(FetchJob)
class FetchJobAdmin(admin.ModelAdmin):
    list_display = ('provider', 'entity_type', 'entity_id', 'status', 'cost_credits', 'created_at')
    list_filter = ('provider', 'status', 'entity_type')
    search_fields = ('entity_id', 'error_message')
