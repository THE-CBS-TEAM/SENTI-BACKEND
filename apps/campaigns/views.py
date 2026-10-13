from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from django.db.models import Q, Sum
from apps.campaigns.models import Campaign, CampaignInfluencer, TrackedPost
from apps.accounts.permissions import IsWorkspaceAdmin
from apps.campaigns.serializers import (
    CampaignSerializer,
    CampaignCreateSerializer,
    CampaignInfluencerSerializer,
    LinkCaptureSerializer,
    TrackedPostSerializer,
)
from apps.influencers.services.benchmark_engine import BenchmarkEngine
from apps.campaigns.services.proposal_engine import ProposalEngine
from apps.scoring.services.metrics_engine import MetricsEngine


class CampaignPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'results': data
        })


class CampaignViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin)
    pagination_class = CampaignPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CampaignCreateSerializer
        return CampaignSerializer

    def get_queryset(self):
        workspace_id = self.request.query_params.get('workspace_id')
        search = self.request.query_params.get('search') or self.request.query_params.get('q')
        status_param = self.request.query_params.get('status')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        # Filter campaigns that belong to workspaces owned or membered by the user
        qs = Campaign.objects.filter(
            Q(workspace__owner=self.request.user) | Q(workspace__memberships__user=self.request.user)
        ).distinct()

        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)

        if search:
            search_stripped = search.strip()
            qs = qs.filter(
                Q(name__icontains=search_stripped) |
                Q(brand__name__icontains=search_stripped) |
                Q(goal__icontains=search_stripped)
            )

        if status_param and status_param != 'ALL':
            qs = qs.filter(status=status_param)

        if start_date:
            qs = qs.filter(start_date__gte=start_date)

        if end_date:
            qs = qs.filter(end_date__lte=end_date)

        return qs.order_by('-created_at')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save()
        
        response_serializer = CampaignSerializer(campaign)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Stops/Pauses a campaign and revokes active monitoring on its tracked posts."""
        from django.db import transaction
        with transaction.atomic():
            campaign = self.get_object()
            campaign.status = Campaign.Statuses.STOPPED
            campaign.save()
    
            # Pause all associated tracked posts and clear next_poll_at to stop Celery tasks
            posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
            posts.update(
                status=TrackedPost.Statuses.PAUSED,
                next_poll_at=None
            )

        return Response({
            'status': campaign.status,
            'message': 'Campaign stopped successfully. Background monitoring paused.',
            'campaign': CampaignSerializer(campaign).data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def estimate_proposal(self, request):
        """Calculates real-time projected KPIs for selected influencers and budgets in the creation wizard."""
        influencers_data = request.data.get('influencers', [])
        projections = ProposalEngine.estimate_campaign_kpis(influencers_data)
        return Response(projections, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Transitions campaign from Stage 1 (Proposal) to Stage 2 (Execution / Active)."""
        from django.db import transaction
        with transaction.atomic():
            campaign = self.get_object()
            campaign.status = Campaign.Statuses.ACTIVE
            campaign.proposal_approved_at = timezone.now()
            campaign.save()
    
            # Switch any pre-captured posts to active monitoring
            now = timezone.now()
            posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign, status=TrackedPost.Statuses.PAUSED)
            posts.update(status=TrackedPost.Statuses.MONITORING, next_poll_at=now)
    
        from tasks.fetch_tasks import fetch_tracked_post_metrics_task
        for post in posts:
            fetch_tracked_post_metrics_task.delay(post.id)

        return Response({
            'status': campaign.status,
            'message': 'Campaign proposal approved! Moved to execution stage.',
            'campaign': CampaignSerializer(campaign).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def proposal_summary(self, request, pk=None):
        """Returns structured proposal projections and context for UI preview and PDF rendering."""
        campaign = self.get_object()
        payload = ProposalEngine.generate_proposal_report_payload(campaign)
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def generate_insights(self, request, pk=None):
        """Triggers the DeepSeek LLM service to generate qualitative insights for this proposal."""
        campaign = self.get_object()
        from apps.sentiment.services.llm_service import LLMService
        
        # 1. Generate overall campaign summary insights
        insights = LLMService.generate_proposal_insights(campaign)
        campaign.llm_summary = insights.get('summary', '')
        campaign.llm_public_opinion = insights.get('public_opinion', '')
        campaign.llm_prediction = insights.get('prediction', '')
        campaign.llm_top_positive_comments = insights.get('top_positive_comments', [])
        campaign.llm_top_negative_comments = insights.get('top_negative_comments', [])
        campaign.llm_positive_keywords = insights.get('positive_keywords', [])
        campaign.llm_negative_keywords = insights.get('negative_keywords', [])
        campaign.llm_creators_analysis = insights.get('creators_analysis', [])
        campaign.save()
        
        # 2. Generate creator-specific insights for each influencer in the lineup
        for ci in campaign.campaign_influencers.all():
            inf_insights = LLMService.generate_influencer_proposal_insights(ci)
            ci.llm_summary = inf_insights.get('summary', '')
            ci.llm_public_opinion = inf_insights.get('public_opinion', '')
            ci.llm_prediction = inf_insights.get('prediction', '')
            ci.llm_top_positive_comments = inf_insights.get('top_positive_comments', [])
            ci.llm_top_negative_comments = inf_insights.get('top_negative_comments', [])
            ci.llm_positive_keywords = inf_insights.get('positive_keywords', [])
            ci.llm_negative_keywords = inf_insights.get('negative_keywords', [])
            ci.save()
            
        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def update_influencer_insights(self, request, pk=None):
        """Updates LLM insights and qualitative adjustments for a specific CampaignInfluencer in this campaign."""
        campaign = self.get_object()
        campaign_influencer_id = request.data.get('campaign_influencer_id')
        
        try:
            ci = CampaignInfluencer.objects.get(id=campaign_influencer_id, campaign=campaign)
        except CampaignInfluencer.DoesNotExist:
            return Response({"detail": "Campaign influencer not found."}, status=status.HTTP_404_NOT_FOUND)
            
        ci.llm_summary = request.data.get('llm_summary', ci.llm_summary)
        ci.llm_public_opinion = request.data.get('llm_public_opinion', ci.llm_public_opinion)
        ci.llm_prediction = request.data.get('llm_prediction', ci.llm_prediction)
        ci.llm_top_positive_comments = request.data.get('llm_top_positive_comments', ci.llm_top_positive_comments)
        ci.llm_top_negative_comments = request.data.get('llm_top_negative_comments', ci.llm_top_negative_comments)
        ci.llm_positive_keywords = request.data.get('llm_positive_keywords', ci.llm_positive_keywords)
        ci.llm_negative_keywords = request.data.get('llm_negative_keywords', ci.llm_negative_keywords)
        ci.save()
        
        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def generate_execution_insights(self, request, pk=None):
        """Triggers the DeepSeek LLM service to generate qualitative execution insights for this campaign."""
        campaign = self.get_object()
        from apps.sentiment.services.llm_service import LLMService
        
        # 1. Generate overall campaign execution insights
        insights = LLMService.generate_execution_insights(campaign)
        campaign.execution_llm_summary = insights.get('summary', '')
        campaign.execution_llm_public_opinion = insights.get('public_opinion', '')
        campaign.execution_llm_next_steps = insights.get('next_steps', '')
        campaign.execution_llm_positive_keywords = insights.get('positive_keywords', [])
        campaign.execution_llm_negative_keywords = insights.get('negative_keywords', [])
        campaign.save()
        
        # 2. Generate creator-specific execution insights
        for ci in campaign.campaign_influencers.all():
            inf_insights = LLMService.generate_influencer_execution_insights(ci)
            ci.execution_llm_summary = inf_insights.get('summary', '')
            ci.execution_llm_public_opinion = inf_insights.get('public_opinion', '')
            ci.execution_llm_next_steps = inf_insights.get('next_steps', '')
            ci.execution_llm_positive_keywords = inf_insights.get('positive_keywords', [])
            ci.execution_llm_negative_keywords = inf_insights.get('negative_keywords', [])
            ci.save()
            
        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def update_influencer_execution_insights(self, request, pk=None):
        """Updates execution insights and qualitative adjustments for a specific CampaignInfluencer in this campaign."""
        campaign = self.get_object()
        campaign_influencer_id = request.data.get('campaign_influencer_id')
        
        try:
            ci = CampaignInfluencer.objects.get(id=campaign_influencer_id, campaign=campaign)
        except CampaignInfluencer.DoesNotExist:
            return Response({"detail": "Campaign influencer not found."}, status=status.HTTP_404_NOT_FOUND)
            
        ci.execution_llm_summary = request.data.get('execution_llm_summary', ci.execution_llm_summary)
        ci.execution_llm_public_opinion = request.data.get('execution_llm_public_opinion', ci.execution_llm_public_opinion)
        ci.execution_llm_next_steps = request.data.get('execution_llm_next_steps', ci.execution_llm_next_steps)
        ci.execution_llm_positive_keywords = request.data.get('execution_llm_positive_keywords', ci.execution_llm_positive_keywords)
        ci.execution_llm_negative_keywords = request.data.get('execution_llm_negative_keywords', ci.execution_llm_negative_keywords)
        ci.save()
        
        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        """Restarts a campaign, setting posts back to MONITORING and triggering polling."""
        from django.db import transaction
        with transaction.atomic():
            campaign = self.get_object()
            campaign.status = Campaign.Statuses.ACTIVE
            campaign.save()
    
            # Resume tracked posts and schedule immediate polling
            now = timezone.now()
            posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
            posts.update(
                status=TrackedPost.Statuses.MONITORING,
                next_poll_at=now
            )
    
        from tasks.fetch_tasks import fetch_tracked_post_metrics_task
        for post in posts:
            fetch_tracked_post_metrics_task.delay(post.id)

        return Response({
            'status': campaign.status,
            'message': 'Campaign restarted successfully. Background monitoring resumed.',
            'campaign': CampaignSerializer(campaign).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def add_influencer(self, request, pk=None):
        pass

    @action(detail=True, methods=['post'])
    def add_influencer(self, request, pk=None):
        campaign = self.get_object()
        influencer_id = request.data.get('influencer_id')
        fee = request.data.get('fee', 0.00)

        if not influencer_id:
            return Response({'error': 'influencer_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        ci, created = CampaignInfluencer.objects.get_or_create(
            campaign=campaign,
            influencer_id=influencer_id,
            defaults={'fee': fee}
        )
        if not created:
            ci.fee = fee
            ci.save()

        return Response(CampaignInfluencerSerializer(ci).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_influencer(self, request, pk=None):
        campaign = self.get_object()
        influencer_id = request.data.get('influencer_id')

        if not influencer_id:
            return Response({'error': 'influencer_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        CampaignInfluencer.objects.filter(campaign=campaign, influencer_id=influencer_id).delete()
        return Response({'success': True}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def capture_link(self, request, pk=None):
        campaign = self.get_object()
        serializer = LinkCaptureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = serializer.save()
        
        return Response(TrackedPostSerializer(post).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='compare-post/(?P<post_id>[^/.]+)')
    def post_comparison(self, request, post_id=None):
        """Compares a specific post metrics against organic benchmarks."""
        try:
            post = TrackedPost.objects.get(pk=post_id, campaign_inf__campaign__workspace__owner=request.user)
        except TrackedPost.DoesNotExist:
            return Response({'error': 'Tracked post not found'}, status=status.HTTP_404_NOT_FOUND)

        comparison = BenchmarkEngine.compare_post_to_benchmark(post)
        return Response(comparison, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def sentiment_breakdown(self, request, pk=None):
        campaign = self.get_object()
        posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
        
        from django.db.models import Sum
        aggregates = posts.aggregate(
            total_positive=Sum('sentiment_positive', default=0),
            total_neutral=Sum('sentiment_neutral', default=0),
            total_negative=Sum('sentiment_negative', default=0),
            total_brand_pos=Sum('brand_sentiment_pos', default=0),
            total_brand_neg=Sum('brand_sentiment_neg', default=0),
        )
        pos = aggregates['total_positive']
        neu = aggregates['total_neutral']
        neg = aggregates['total_negative']
        
        brand_pos = aggregates['total_brand_pos']
        brand_neg = aggregates['total_brand_neg']

        return Response({
            'overall_sentiment': {
                'positive': pos,
                'neutral': neu,
                'negative': neg,
                'total': pos + neu + neg
            },
            'brand_perception': {
                'positive': brand_pos,
                'negative': brand_neg
            }
        })

    @action(detail=True, methods=['get'])
    def recent_comments(self, request, pk=None):
        """Returns recent comments for all posts in this campaign with creator context."""
        campaign = self.get_object()
        from apps.sentiment.models import Comment

        comments = Comment.objects.filter(
            tracked_post__campaign_inf__campaign=campaign
        ).select_related('tracked_post__campaign_inf__influencer').order_by('-created_at')[:50]

        data = []
        for c in comments:
            inf = c.tracked_post.campaign_inf.influencer
            data.append({
                'id': c.id,
                'author_handle': c.author_handle or 'Anonymous',
                'text': c.text,
                'sentiment': c.sentiment,
                'emotion_category': c.emotion_category,
                'brand_mentioned': c.brand_mentioned,
                'brand_sentiment': c.brand_sentiment,
                'created_at': c.created_at.isoformat() if c.created_at else None,
                'post_id': c.tracked_post.id,
                'post_url': c.tracked_post.post_url,
                'platform': c.tracked_post.platform,
                'influencer_name': inf.display_name,
                'influencer_id': inf.id,
                'influencer_avatar': inf.avatar_url,
            })
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def influencer_sentiment_comments(self, request, pk=None):
        """Returns top 20 comments per platform (IG, X, TT) for a specific influencer/sentiment in this campaign."""
        try:
            campaign = self.get_object()
            influencer_id = request.query_params.get('influencer_id')
            sentiment_param = request.query_params.get('sentiment', 'POS').upper()
            
            # map sentiment input
            sentiment = 'POS' if 'POS' in sentiment_param or sentiment_param == 'POSITIVE' else 'NEG'
            
            from apps.sentiment.models import Comment
            
            qs = Comment.objects.filter(
                tracked_post__campaign_inf__campaign=campaign,
                sentiment=sentiment
            )
            
            if influencer_id and influencer_id != 'all' and influencer_id != '':
                try:
                    qs = qs.filter(tracked_post__campaign_inf__influencer_id=int(influencer_id))
                except ValueError:
                    pass
                
            qs = qs.select_related('tracked_post__campaign_inf__influencer').order_by('-created_at')
            
            # Group by platform with robust alias support (IG, TT, X)
            platform_map = {
                'IG': ['IG', 'INSTAGRAM', 'Instagram'],
                'TT': ['TT', 'TIKTOK', 'TikTok'],
                'X': ['X', 'TWITTER', 'Twitter']
            }
            result = {'IG': [], 'TT': [], 'X': []}
            
            for p, aliases in platform_map.items():
                p_comments = qs.filter(tracked_post__platform__in=aliases)[:20]
                for c in p_comments:
                    post = getattr(c, 'tracked_post', None)
                    camp_inf = getattr(post, 'campaign_inf', None) if post else None
                    inf = getattr(camp_inf, 'influencer', None) if camp_inf else None
                    result[p].append({
                        'id': c.id,
                        'author_handle': c.author_handle or 'Anonymous',
                        'text': c.text,
                        'sentiment': c.sentiment,
                        'emotion_category': c.emotion_category,
                        'brand_mentioned': c.brand_mentioned,
                        'brand_sentiment': c.brand_sentiment,
                        'created_at': c.created_at.isoformat() if c.created_at else None,
                        'post_id': getattr(post, 'id', None),
                        'post_url': getattr(post, 'post_url', ''),
                        'platform': getattr(post, 'platform', p),
                        'influencer_name': getattr(inf, 'display_name', 'Creator') if inf else 'Creator',
                        'influencer_id': getattr(inf, 'id', None) if inf else None,
                    })
                    
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error in influencer_sentiment_comments: {str(e)}", exc_info=True)
            return Response({'IG': [], 'TT': [], 'X': [], 'error': str(e)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        """Returns campaign-specific performance, scraper logs, budget, and active schedules."""
        from django.conf import settings
        from apps.influencers.models import FetchJob

        campaign = self.get_queryset().prefetch_related(
            'campaign_influencers__tracked_posts',
            'campaign_influencers__influencer'
        ).get(pk=pk)
        posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
        post_ids = list(posts.values_list('id', flat=True))

        # 1. Budget & Credit Spend for this campaign
        cap = float(getattr(settings, 'DAILY_CREDIT_BUDGET_CAP', 50.00))
        campaign_budget = float(campaign.budget or 0.0)

        # Scraper jobs for posts in this campaign
        jobs = FetchJob.objects.filter(
            entity_type='POST',
            entity_id__in=post_ids
        ).order_by('-created_at')

        total_used = float(jobs.aggregate(total=Sum('cost_credits'))['total'] or 0.0)
        budget_pct = round((total_used / campaign_budget) * 100, 2) if campaign_budget > 0 else 0.0

        # 2. Scraper logs
        recent_jobs = jobs[:50]
        entity_ids = [job.entity_id for job in recent_jobs]
        posts_dict = {p.id: p for p in posts.filter(id__in=entity_ids).select_related('campaign_inf__influencer')}
        
        jobs_list = []
        for job in recent_jobs:
            post = posts_dict.get(job.entity_id)
            entity_name = f"Post: {post.campaign_inf.influencer.display_name}" if post else "Unknown Post"

            jobs_list.append({
                'id': job.id,
                'entity_type': job.entity_type,
                'entity_name': entity_name,
                'provider': job.provider,
                'status': job.status,
                'cost_credits': float(job.cost_credits),
                'error_message': job.error_message,
                'created_at': job.created_at.isoformat() if job.created_at else None,
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            })

        # 3. Active schedules
        schedules_list = []
        for post in posts.filter(status=TrackedPost.Statuses.MONITORING):
            platform = 'Unknown'
            if 'instagram.com' in post.post_url:
                platform = 'Instagram'
            elif 'tiktok.com' in post.post_url:
                platform = 'TikTok'
            elif 'x.com' in post.post_url or 'twitter.com' in post.post_url:
                platform = 'Twitter/X'

            schedules_list.append({
                'id': post.id,
                'creator': post.campaign_inf.influencer.display_name,
                'campaign': campaign.name,
                'platform': platform,
                'post_url': post.post_url,
                'last_fetched_at': post.last_fetched_at.isoformat() if post.last_fetched_at else None,
                'next_poll_at': post.next_poll_at.isoformat() if post.next_poll_at else None,
            })

        # 4. Overall campaign stats
        completed_jobs = jobs.filter(status='DONE').count()
        failed_jobs = jobs.filter(status='FAIL').count()
        monitoring_posts_count = posts.filter(status=TrackedPost.Statuses.MONITORING).count()

        pos = sum(p.sentiment_positive for p in posts)
        neu = sum(p.sentiment_neutral for p in posts)
        neg = sum(p.sentiment_negative for p in posts)
        brand_pos = sum(p.brand_sentiment_pos for p in posts)
        brand_neg = sum(p.brand_sentiment_neg for p in posts)

        # 5. Creator breakdown
        creators_stats = []
        for ci in campaign.campaign_influencers.all():
            ci_posts = ci.tracked_posts.all()
            ci_views = sum(p.views for p in ci_posts)
            ci_likes = sum(p.likes for p in ci_posts)
            ci_comments = sum(p.comments_count for p in ci_posts)
            ci_pos = sum(p.sentiment_positive for p in ci_posts)
            ci_neg = sum(p.sentiment_negative for p in ci_posts)

            creators_stats.append({
                'id': ci.influencer.id,
                'display_name': ci.influencer.display_name,
                'avatar_url': ci.influencer.avatar_url,
                'fee': float(ci.fee),
                'posts_count': ci_posts.count(),
                'total_views': ci_views,
                'total_likes': ci_likes,
                'total_comments': ci_comments,
                'positive_sentiment_count': ci_pos,
                'negative_sentiment_count': ci_neg,
            })

        return Response({
            'campaign_id': campaign.id,
            'campaign_name': campaign.name,
            'campaign_status': campaign.status,
            'budget_cap': campaign_budget,
            'budget_used_24h': total_used,
            'budget_pct': budget_pct,
            'overall_stats': {
                'total_influencers': campaign.campaign_influencers.count(),
                'total_monitoring_posts': monitoring_posts_count,
                'total_completed_jobs': completed_jobs,
                'total_failed_jobs': failed_jobs,
                'total_posts': posts.count(),
                'sentiment': {
                    'positive': pos,
                    'neutral': neu,
                    'negative': neg,
                    'total': pos + neu + neg,
                    'net_sentiment': MetricsEngine.net_sentiment(pos, neg)
                },
                'brand_perception': {
                    'positive': brand_pos,
                    'negative': brand_neg,
                    'net_brand_sentiment': MetricsEngine.net_sentiment(brand_pos, brand_neg)
                },
                'projections': {
                    'estimated_reach': campaign.estimated_reach,
                    'estimated_views': campaign.estimated_views,
                    'estimated_engagement': campaign.estimated_engagement,
                    'estimated_aar': campaign.estimated_aar,
                    'estimated_cr': campaign.estimated_cr,
                    'estimated_re': campaign.estimated_re,
                }
            },
            'jobs_logs': jobs_list,
            'active_schedules': schedules_list,
            'creators_stats': creators_stats
        }, status=status.HTTP_200_OK)

