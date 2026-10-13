from rest_framework import serializers
from django.db.models import Q
from apps.influencers.models import (
    GlobalInfluencer,
    WorkspaceInfluencer,
    Influencer,
    PlatformMetrics,
    OrganicBenchmark,
)
from apps.integrations.router import IntegrationRouter


class PlatformMetricsSerializer(serializers.ModelSerializer):
    platform_display = serializers.CharField(source='get_platform_display', read_only=True)

    class Meta:
        model = PlatformMetrics
        fields = (
            'id', 'platform', 'platform_display', 'followers', 'engagement_rate', 
            'avg_views', 'avg_likes', 'avg_comments', 'avg_shares', 'avg_saves', 'avg_reposts',
            'aar', 'cr', 'resonance_efficiency', 'raw_api_response', 'fetched_at'
        )


class OrganicBenchmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganicBenchmark
        fields = (
            'id', 'platform', 'post_url', 'views', 'likes', 
            'comments_count', 'shares', 'engagement_total', 'post_text', 'post_created_at', 'fetched_at'
        )


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL INFLUENCER SERIALIZERS
# ─────────────────────────────────────────────────────────────────────────────

class GlobalInfluencerSerializer(serializers.ModelSerializer):
    platform_metrics = PlatformMetricsSerializer(many=True, read_only=True)
    total_followers = serializers.SerializerMethodField()
    data_freshness = serializers.ReadOnlyField()
    is_data_stale = serializers.ReadOnlyField()
    age_hours = serializers.ReadOnlyField()
    age_display = serializers.ReadOnlyField()

    class Meta:
        model = GlobalInfluencer
        fields = (
            'id', 'display_name', 'niche', 'avatar_url',
            'ig_handle', 'tiktok_handle', 'x_handle',
            'senti_score', 'senti_label', 'fake_follower_score',
            'consistency_score', 'reach_score',
            'deepseek_summary', 'deepseek_analysis', 'deepseek_analyzed_at',
            'data_freshness', 'is_data_stale', 'age_hours', 'age_display',
            'last_scraped_at', 'scrape_in_progress',
            'platform_metrics', 'total_followers', 'created_at', 'updated_at',
        )

    def get_total_followers(self, obj):
        return sum(m.followers for m in obj.platform_metrics.all())


class GlobalInfluencerSearchResultSerializer(serializers.ModelSerializer):
    total_followers = serializers.SerializerMethodField()
    is_in_workspace = serializers.SerializerMethodField()
    data_freshness = serializers.ReadOnlyField()
    is_data_stale = serializers.ReadOnlyField()
    age_hours = serializers.ReadOnlyField()
    age_display = serializers.ReadOnlyField()

    class Meta:
        model = GlobalInfluencer
        fields = (
            'id', 'display_name', 'niche', 'avatar_url',
            'ig_handle', 'tiktok_handle', 'x_handle',
            'senti_score', 'senti_label', 'total_followers',
            'data_freshness', 'is_data_stale', 'age_hours', 'age_display', 'is_in_workspace',
        )

    def get_total_followers(self, obj):
        return sum(m.followers for m in obj.platform_metrics.all())

    def get_is_in_workspace(self, obj):
        workspace_id = self.context.get('workspace_id')
        if not workspace_id:
            return False
        return WorkspaceInfluencer.objects.filter(workspace_id=workspace_id, global_influencer=obj).exists()


class AddFromCatalogSerializer(serializers.Serializer):
    global_influencer_id = serializers.IntegerField()
    workspace_id = serializers.IntegerField()


# ─────────────────────────────────────────────────────────────────────────────
# WORKSPACE INFLUENCER SERIALIZERS (Legacy & Current Views)
# ─────────────────────────────────────────────────────────────────────────────

class InfluencerSerializer(serializers.ModelSerializer):
    platform_metrics = serializers.SerializerMethodField()
    total_followers = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    senti_score = serializers.SerializerMethodField()
    senti_label = serializers.SerializerMethodField()
    centi_score = serializers.SerializerMethodField()
    sentiment_rating = serializers.SerializerMethodField()
    fake_follower_score = serializers.SerializerMethodField()
    consistency_score = serializers.SerializerMethodField()
    reach_score = serializers.SerializerMethodField()
    senti_components = serializers.SerializerMethodField()
    authenticity_breakdown = serializers.SerializerMethodField()
    global_influencer_id = serializers.IntegerField(source='global_influencer.id', read_only=True)
    data_freshness = serializers.SerializerMethodField()
    is_data_stale = serializers.SerializerMethodField()
    age_hours = serializers.SerializerMethodField()
    age_display = serializers.SerializerMethodField()

    class Meta:
        model = Influencer
        fields = (
            'id', 'global_influencer_id', 'workspace', 'display_name', 'niche', 'avatar_url',
            'ig_handle', 'tiktok_handle', 'x_handle',
            'centi_score', 'sentiment_rating', 'fake_follower_score',
            'authenticity_confidence', 'authenticity_risk_flags', 'authenticity_breakdown',
            'consistency_score', 'reach_score',
            'senti_score', 'senti_label', 'senti_components',
            'data_freshness', 'is_data_stale', 'age_hours', 'age_display',
            'platform_metrics', 'total_followers', 'created_at', 'updated_at',
            'next_poll_at', 'last_fetch_attempt_at', 'last_successful_fetch_at',
            'last_fetch_error', 'consecutive_fetch_failures'
        )
        read_only_fields = (
            'workspace', 'centi_score', 'sentiment_rating', 'fake_follower_score',
            'authenticity_confidence', 'authenticity_risk_flags', 'authenticity_breakdown',
            'consistency_score', 'reach_score',
            'senti_score', 'senti_label',
            'next_poll_at', 'last_fetch_attempt_at', 'last_successful_fetch_at',
            'last_fetch_error', 'consecutive_fetch_failures'
        )

    def get_platform_metrics(self, obj):
        if obj.global_influencer:
            metrics = obj.global_influencer.platform_metrics.all()
            if metrics.exists():
                return PlatformMetricsSerializer(metrics, many=True).data
        return PlatformMetricsSerializer(obj.platform_metrics.all(), many=True).data

    def get_total_followers(self, obj):
        # Prefer metrics from global influencer if linked
        if obj.global_influencer:
            return sum(m.followers for m in obj.global_influencer.platform_metrics.all())
        return sum(m.followers for m in obj.platform_metrics.all())

    def get_avatar_url(self, obj):
        # Prefer global avatar
        avatar = obj.global_influencer.avatar_url if (obj.global_influencer and obj.global_influencer.avatar_url) else obj.avatar_url
        if not avatar or 'default_profile_images/default_profile' in avatar:
            return 'https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png'
        
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/v1/influencers/{obj.id}/avatar/')
        return f'/api/v1/influencers/{obj.id}/avatar/'

    def get_data_freshness(self, obj):
        if obj.global_influencer:
            return obj.global_influencer.data_freshness
        return 'fresh'

    def get_is_data_stale(self, obj):
        if obj.global_influencer:
            return obj.global_influencer.is_data_stale
        return False

    def get_age_hours(self, obj):
        if obj.global_influencer:
            return obj.global_influencer.age_hours
        return None

    def get_age_display(self, obj):
        if obj.global_influencer:
            return obj.global_influencer.age_display
        return 'Fresh'

    def get_senti_score(self, obj):
        if obj.senti_score:
            return obj.senti_score
        if obj.global_influencer and obj.global_influencer.senti_score:
            return obj.global_influencer.senti_score
        return 0

    def get_senti_label(self, obj):
        if obj.senti_score and obj.senti_label:
            return obj.senti_label
        if obj.global_influencer and obj.global_influencer.senti_label:
            return obj.global_influencer.senti_label
        return obj.senti_label or 'AVERAGE'

    def get_centi_score(self, obj):
        return self.get_senti_score(obj)

    def get_sentiment_rating(self, obj):
        score = self.get_senti_score(obj)
        if score >= 70:
            return 'POSITIVE'
        elif score >= 50:
            return 'NEUTRAL'
        elif score > 0:
            return 'NEGATIVE'
        return obj.sentiment_rating or 'NEUTRAL'

    def get_fake_follower_score(self, obj):
        if obj.fake_follower_score:
            return obj.fake_follower_score
        if obj.global_influencer and obj.global_influencer.fake_follower_score:
            return obj.global_influencer.fake_follower_score
        return 0

    def get_consistency_score(self, obj):
        if obj.consistency_score:
            return obj.consistency_score
        if obj.global_influencer and obj.global_influencer.consistency_score:
            return obj.global_influencer.consistency_score
        return 0

    def get_reach_score(self, obj):
        if obj.reach_score:
            return obj.reach_score
        if obj.global_influencer and obj.global_influencer.reach_score:
            return obj.global_influencer.reach_score
        return 0

    def get_senti_components(self, obj):
        from apps.scoring.models import SentiScoreHistory
        latest = SentiScoreHistory.objects.filter(influencer=obj).order_by('-calculated_at').first()
        if not latest and obj.global_influencer:
            latest = SentiScoreHistory.objects.filter(influencer__global_influencer=obj.global_influencer).order_by('-calculated_at').first()
        if latest:
            return latest.components
        return None

    def get_authenticity_breakdown(self, obj):
        from apps.scoring.models import AuthenticityScoreHistory
        latest = AuthenticityScoreHistory.objects.filter(influencer=obj).order_by('-calculated_at').first()
        if not latest and obj.global_influencer:
            latest = AuthenticityScoreHistory.objects.filter(influencer__global_influencer=obj.global_influencer).order_by('-calculated_at').first()

        if not latest and obj.id:
            try:
                from apps.scoring.services.fake_follower import FakeFollowerDetector
                res = FakeFollowerDetector.analyze_authenticity(obj.id)
                if res:
                    return res
            except Exception:
                pass

        if latest:
            return {
                'overall_score': latest.overall_score,
                'confidence': latest.confidence,
                'platform_scores': latest.platform_scores,
                'signal_breakdown': latest.signal_breakdown,
                'risk_flags': latest.risk_flags,
                'calculated_at': latest.calculated_at
            }
        return None


class AddInfluencerSerializer(serializers.Serializer):
    """
    Onboard Influencer Handler:
    1. Extracts handles from user input.
    2. Checks if creator already exists in GlobalInfluencer catalog.
       - If YES: links to workspace, returns immediately (triggers background refresh if >24h old).
       - If NO: creates GlobalInfluencer + links to workspace, then attempts SociaVault scrape.
    """
    workspace_id = serializers.IntegerField()
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    niche = serializers.CharField(max_length=100, required=False, allow_blank=True)
    ig_url = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    tiktok_url = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    x_url = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')

    def _extract_handle(self, url_or_handle):
        if not url_or_handle:
            return None
        val = url_or_handle.strip().rstrip('/')
        if val.startswith('@'):
            return val[1:]
        if '/' in val:
            parts = [p for p in val.split('/') if p]
            if parts:
                return parts[-1].lstrip('@')
        return val

    def validate(self, data):
        ig = data.get('ig_url', '')
        tt = data.get('tiktok_url', '')
        x = data.get('x_url', '')
        if not ig and not tt and not x:
            raise serializers.ValidationError(
                "Please provide at least one platform profile link or handle (Instagram, TikTok, or X)."
            )
        return data

    def create(self, validated_data):
        workspace_id = validated_data['workspace_id']
        display_name = validated_data.get('display_name', '')
        niche = validated_data.get('niche', '')

        ig_handle = self._extract_handle(validated_data.get('ig_url', ''))
        tiktok_handle = self._extract_handle(validated_data.get('tiktok_url', ''))
        x_handle = self._extract_handle(validated_data.get('x_url', ''))

        # 1. Search Global Catalog for matching handle
        q = Q()
        if ig_handle:
            q |= Q(ig_handle__iexact=ig_handle)
        if tiktok_handle:
            q |= Q(tiktok_handle__iexact=tiktok_handle)
        if x_handle:
            q |= Q(x_handle__iexact=x_handle)

        global_inf = None
        if q:
            global_inf = GlobalInfluencer.objects.filter(q).first()

        if global_inf:
            # Found in global catalog!
            # Link to workspace
            WorkspaceInfluencer.objects.get_or_create(
                workspace_id=workspace_id,
                global_influencer=global_inf
            )
            influencer, _ = Influencer.objects.get_or_create(
                workspace_id=workspace_id,
                global_influencer=global_inf,
                defaults={
                    'display_name': global_inf.display_name,
                    'niche': global_inf.niche or niche,
                    'ig_handle': global_inf.ig_handle,
                    'tiktok_handle': global_inf.tiktok_handle,
                    'x_handle': global_inf.x_handle,
                    'avatar_url': global_inf.avatar_url,
                    'senti_score': global_inf.senti_score,
                    'senti_label': global_inf.senti_label,
                }
            )

            # Check 24h freshness logic:
            if global_inf.is_data_stale:
                from tasks.influencer_tasks import refresh_global_influencer_task
                refresh_global_influencer_task.delay(global_inf.id)

            return influencer

        # 2. Not found in catalog — create new GlobalInfluencer
        resolved_name = display_name or ig_handle or tiktok_handle or x_handle or 'Unknown'
        global_inf = GlobalInfluencer.objects.create(
            display_name=resolved_name,
            niche=niche,
            ig_handle=ig_handle,
            tiktok_handle=tiktok_handle,
            x_handle=x_handle,
            avatar_url='https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png',
            scrape_in_progress=True,
        )

        WorkspaceInfluencer.objects.create(
            workspace_id=workspace_id,
            global_influencer=global_inf
        )

        influencer = Influencer.objects.create(
            workspace_id=workspace_id,
            global_influencer=global_inf,
            display_name=resolved_name,
            niche=niche,
            ig_handle=ig_handle,
            tiktok_handle=tiktok_handle,
            x_handle=x_handle,
            avatar_url=global_inf.avatar_url,
        )

        # 3. Synchronous fast-poll attempt via SociaVault (near-instant)
        from apps.influencers.services.profile_fetcher import ProfileFetcher
        try:
            fetcher = ProfileFetcher()
            success = fetcher.fetch_and_benchmark_global_influencer(global_inf.id)
            if success:
                influencer.refresh_from_db()
                return influencer
        except Exception:
            pass

        # If synchronous call didn't finish or failed, queue in Celery
        from tasks.influencer_tasks import fetch_global_influencer_task
        fetch_global_influencer_task.delay(global_inf.id)

        return influencer
