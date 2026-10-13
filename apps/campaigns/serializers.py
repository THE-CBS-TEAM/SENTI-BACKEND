from rest_framework import serializers
from apps.campaigns.models import Campaign, CampaignInfluencer, TrackedPost
from apps.influencers.serializers import InfluencerSerializer
from apps.integrations.router import IntegrationRouter


class TrackedPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackedPost
        fields = (
            'id', 'campaign_inf', 'platform', 'post_url', 
            'views', 'likes', 'comments_count', 'shares', 'saves', 'retweets', 'watch_time_avg',
            'sentiment_positive', 'sentiment_neutral', 'sentiment_negative',
            'brand_sentiment_pos', 'brand_sentiment_neg', 'status', 'polling_tier',
            'next_poll_at', 'created_at', 'last_fetched_at'
        )
        read_only_fields = ('platform', 'status', 'polling_tier', 'next_poll_at', 'last_fetched_at')


class CampaignInfluencerSerializer(serializers.ModelSerializer):
    influencer = InfluencerSerializer(read_only=True)
    influencer_id = serializers.IntegerField(write_only=True)
    tracked_posts = TrackedPostSerializer(many=True, read_only=True)

    class Meta:
        model = CampaignInfluencer
        fields = (
            'id', 'campaign', 'influencer', 'influencer_id', 'fee', 'assigned_at', 
            'estimated_engagement', 'estimated_reach', 'estimated_views',
            'estimated_aar', 'estimated_cr', 'estimated_re', 'tracked_posts',
            'llm_summary', 'llm_public_opinion', 'llm_prediction',
            'llm_top_positive_comments', 'llm_top_negative_comments',
            'llm_positive_keywords', 'llm_negative_keywords',
            'execution_llm_summary', 'execution_llm_public_opinion', 'execution_llm_next_steps',
            'execution_llm_positive_keywords', 'execution_llm_negative_keywords'
        )
        read_only_fields = ('campaign', 'assigned_at')


class CampaignSerializer(serializers.ModelSerializer):
    campaign_influencers = CampaignInfluencerSerializer(many=True, read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)

    class Meta:
        model = Campaign
        fields = (
            'id', 'workspace', 'name', 'brand', 'brand_name', 'budget', 'currency',
            'start_date', 'end_date', 'goal', 'roi_estimate', 'status', 
            'estimated_engagement', 'estimated_reach', 'estimated_views',
            'estimated_aar', 'estimated_cr', 'estimated_re', 'proposal_approved_at',
            'llm_summary', 'llm_public_opinion', 'llm_prediction',
            'llm_top_positive_comments', 'llm_top_negative_comments',
            'llm_positive_keywords', 'llm_negative_keywords', 'llm_creators_analysis',
            'execution_llm_summary', 'execution_llm_public_opinion', 'execution_llm_next_steps',
            'execution_llm_positive_keywords', 'execution_llm_negative_keywords',
            'campaign_influencers', 'created_at'
        )


class CampaignCreateSerializer(serializers.ModelSerializer):
    influencers = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)

    class Meta:
        model = Campaign
        fields = (
            'id', 'workspace', 'name', 'brand', 'budget', 'currency',
            'start_date', 'end_date', 'goal', 'status', 'influencers',
            'llm_summary', 'llm_public_opinion', 'llm_prediction',
            'llm_top_positive_comments', 'llm_top_negative_comments'
        )

    def validate(self, data):
        influencers = data.get('influencers', [])
        for item in influencers:
            post_url = item.get('post_url')
            if post_url:
                parsed = IntegrationRouter.parse_url(post_url)
                if not parsed or parsed['type'] != 'post':
                    raise serializers.ValidationError(
                        f"Invalid post URL: {post_url}. Must be a direct Instagram/TikTok/X post link."
                    )
        return data

    def create(self, validated_data):
        influencers_data = validated_data.pop('influencers', [])
        if 'status' not in validated_data:
            validated_data['status'] = Campaign.Statuses.PROPOSAL
        campaign = Campaign.objects.create(**validated_data)
        
        # Link assigned influencers
        for item in influencers_data:
            ci = CampaignInfluencer.objects.create(
                campaign=campaign,
                influencer_id=item['influencer_id'],
                fee=item.get('fee', 0.00)
            )
            
            # If post_url is provided, create TrackedPost immediately
            post_url = item.get('post_url')
            if post_url:
                parsed = IntegrationRouter.parse_url(post_url)
                if parsed and parsed['type'] == 'post':
                    post_status = 'MONITORING' if campaign.status in ['ACTIVE', 'APPROVED'] else 'PAUSED'
                    post = TrackedPost.objects.create(
                        campaign_inf=ci,
                        platform=parsed['platform'],
                        post_url=post_url,
                        status=post_status,
                        consecutive_fetch_failures=0
                    )
                    if post_status == 'MONITORING':
                        from tasks.fetch_tasks import fetch_tracked_post_metrics_task
                        fetch_tracked_post_metrics_task.delay(post.id)
            
        # Compute and attach Stage 1 proposal KPI projections
        if influencers_data:
            from apps.campaigns.services.proposal_engine import ProposalEngine
            ProposalEngine.apply_projections_to_campaign(campaign, influencers_data)
            
        return campaign



class LinkCaptureSerializer(serializers.Serializer):
    campaign_influencer_id = serializers.IntegerField()
    post_url = serializers.CharField(max_length=500)

    def validate(self, data):
        parsed = IntegrationRouter.parse_url(data['post_url'])
        if not parsed or parsed['type'] != 'post':
            raise serializers.ValidationError(
                "Invalid post URL. Must be a direct link to an Instagram post/reel, TikTok video, or Tweet/X status."
            )
        data['parsed'] = parsed
        return data

    def create(self, validated_data):
        campaign_inf_id = validated_data['campaign_influencer_id']
        post_url = validated_data['post_url']
        parsed = validated_data['parsed']

        # Create the TrackedPost
        post = TrackedPost.objects.create(
            campaign_inf_id=campaign_inf_id,
            platform=parsed['platform'],
            post_url=post_url,
            status='MONITORING',
            consecutive_fetch_failures=0
        )

        # Trigger Celery background task to pull metrics & comments
        from tasks.fetch_tasks import fetch_tracked_post_metrics_task
        fetch_tracked_post_metrics_task.delay(post.id)

        return post
