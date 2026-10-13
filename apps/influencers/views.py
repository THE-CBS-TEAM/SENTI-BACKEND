from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.influencers.models import Influencer, OrganicBenchmark
from apps.scoring.models import CentiScoreHistory
from apps.accounts.permissions import IsWorkspaceAdmin
from apps.influencers.serializers import (
    InfluencerSerializer,
    AddInfluencerSerializer,
    OrganicBenchmarkSerializer,
)


class InfluencerViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin)


    def get_serializer_class(self):
        if self.action == 'create':
            return AddInfluencerSerializer
        return InfluencerSerializer

    def get_queryset(self):
        if self.action == 'avatar':
            return Influencer.objects.all()

        from django.db.models import Q
        workspace_id = self.request.query_params.get('workspace_id')
        # Filter influencers that belong to workspaces owned or membered by the user
        qs = Influencer.objects.filter(
            Q(workspace__owner=self.request.user) | Q(workspace__memberships__user=self.request.user)
        ).distinct()
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)
        return qs


    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        influencer = serializer.save()
        
        response_serializer = InfluencerSerializer(influencer, context={'request': request})
        global_inf = influencer.global_influencer
        is_pending = bool(global_inf and global_inf.scrape_in_progress)
        
        is_stale = False
        age_display = ""
        stale_message = ""
        refresh_queued = False

        if global_inf:
            is_stale = global_inf.is_data_stale
            age_display = global_inf.age_display
            if is_stale:
                stale_message = (
                    f"The current details for {influencer.display_name} are {age_display}. "
                    f"A background task is running to refresh comments, sentiment, and Senti score. "
                    f"You can proceed with the current details in the meantime."
                )
                refresh_queued = True

        status_code = status.HTTP_202_ACCEPTED if is_pending and not influencer.senti_score else status.HTTP_201_CREATED
        message = (
            "Creator profiling queued. Polling data from social platforms..."
            if (is_pending and not influencer.senti_score)
            else "Influencer profile successfully created."
        )
        return Response({
            "message": message,
            "influencer": response_serializer.data,
            "status": "processing" if (is_pending and not influencer.senti_score) else "completed",
            "is_stale": is_stale,
            "age_display": age_display,
            "stale_message": stale_message,
            "refresh_queued": refresh_queued,
        }, status=status_code)

    @action(detail=False, methods=['get'], url_path='search')
    def search(self, request):
        """
        Search the Global Influencer catalog by handle or display name.
        Allows instant reuse of existing scraped influencers across workspaces.
        """
        from django.db.models import Q
        from apps.influencers.models import GlobalInfluencer
        from apps.influencers.serializers import GlobalInfluencerSearchResultSerializer

        q = request.query_params.get('q', '').strip()
        workspace_id = request.query_params.get('workspace_id')

        if not q or len(q) < 2:
            return Response([])

        clean_handle = q.lstrip('@').lower()

        qs = GlobalInfluencer.objects.filter(
            Q(display_name__icontains=q) |
            Q(ig_handle__icontains=clean_handle) |
            Q(tiktok_handle__icontains=clean_handle) |
            Q(x_handle__icontains=clean_handle)
        ).prefetch_related('platform_metrics')[:20]

        serializer = GlobalInfluencerSearchResultSerializer(
            qs, many=True, context={'workspace_id': workspace_id}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='add-from-catalog')
    def add_from_catalog(self, request):
        """
        Add an existing influencer from the Global Catalog to the user's workspace.
        Enforces configured staleness logic:
        - Serves cached data immediately so user never waits.
        - If data is older than configured threshold, dispatches background refresh task
          and returns staleness metadata for UI toast notification.
        """
        from apps.influencers.models import GlobalInfluencer, WorkspaceInfluencer
        from apps.influencers.serializers import AddFromCatalogSerializer

        serializer = AddFromCatalogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        global_id = serializer.validated_data['global_influencer_id']
        workspace_id = serializer.validated_data['workspace_id']

        global_inf = GlobalInfluencer.objects.filter(id=global_id).first()
        if not global_inf:
            return Response({"error": "Influencer not found in global catalog."}, status=status.HTTP_404_NOT_FOUND)

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
                'niche': global_inf.niche,
                'ig_handle': global_inf.ig_handle,
                'tiktok_handle': global_inf.tiktok_handle,
                'x_handle': global_inf.x_handle,
                'avatar_url': global_inf.avatar_url,
                'senti_score': global_inf.senti_score,
                'senti_label': global_inf.senti_label,
            }
        )

        # Freshness check against dynamic threshold
        is_stale = global_inf.is_data_stale
        age_display = global_inf.age_display
        refresh_queued = False
        stale_message = ""

        if is_stale:
            stale_message = (
                f"The current details for {global_inf.display_name} are {age_display}. "
                f"A background update has been started to refresh comments, sentiment, and Senti score. "
                f"You can proceed with the current details in the meantime."
            )
            if not global_inf.scrape_in_progress:
                global_inf.scrape_in_progress = True
                global_inf.save(update_fields=['scrape_in_progress'])
                from tasks.influencer_tasks import refresh_global_influencer_task
                refresh_global_influencer_task.delay(global_inf.id)
                refresh_queued = True

        resp_serializer = InfluencerSerializer(influencer, context={'request': request})
        return Response({
            "message": "Influencer successfully added from database.",
            "data_freshness": global_inf.data_freshness,
            "is_stale": is_stale,
            "age_display": age_display,
            "refresh_queued": refresh_queued,
            "stale_message": stale_message,
            "influencer": resp_serializer.data,
        }, status=status.HTTP_200_OK)

    def perform_update(self, serializer):
        old_instance = self.get_object()
        old_handles = (old_instance.ig_handle, old_instance.tiktok_handle, old_instance.x_handle)
        instance = serializer.save()
        # Ensure clean handles on update
        instance.clean_handles()
        instance.last_fetch_error = None
        instance.consecutive_fetch_failures = 0
        instance.save(update_fields=['ig_handle', 'tiktok_handle', 'x_handle', 'last_fetch_error', 'consecutive_fetch_failures'])

        new_handles = (instance.ig_handle, instance.tiktok_handle, instance.x_handle)

        if old_handles != new_handles:
            if instance.global_influencer_id:
                gi = instance.global_influencer
                gi.last_fetch_error = None
                gi.consecutive_fetch_failures = 0
                gi.save(update_fields=['last_fetch_error', 'consecutive_fetch_failures'])
                from tasks.influencer_tasks import refresh_global_influencer_task
                refresh_global_influencer_task.delay(instance.global_influencer_id)
            else:
                from tasks.fetch_tasks import fetch_influencer_profile_task
                fetch_influencer_profile_task.delay(instance.id)

    @action(detail=True, methods=['post'])
    def refresh(self, request, pk=None):
        influencer = self.get_object()
        
        from django.utils import timezone
        influencer.last_fetch_attempt_at = timezone.now()
        influencer.consecutive_fetch_failures = 0
        influencer.save(update_fields=['last_fetch_attempt_at', 'consecutive_fetch_failures'])

        if influencer.global_influencer_id:
            from tasks.influencer_tasks import refresh_global_influencer_task
            refresh_global_influencer_task.delay(influencer.global_influencer_id)
        else:
            from tasks.fetch_tasks import fetch_influencer_profile_task
            fetch_influencer_profile_task.delay(influencer.id)
        
        return Response({'status': 'refresh_started'})

    @action(detail=True, methods=['get'], permission_classes=[permissions.AllowAny])
    def avatar(self, request, pk=None):
        influencer = self.get_object()
        if not influencer.avatar_url or 'default_profile_images/default_profile' in influencer.avatar_url:
            from django.http import Http404
            raise Http404("No custom avatar set")
        
        import requests
        import urllib.parse
        import socket
        import ipaddress
        from django.http import HttpResponse, HttpResponseRedirect, HttpResponseForbidden
        
        parsed = urllib.parse.urlparse(influencer.avatar_url)
        hostname = parsed.hostname
        if not hostname:
            return HttpResponseForbidden("Invalid URL")
        
        allowed_domains = ['cdninstagram.com', 'fbcdn.net', 'twimg.com', 'tiktokcdn.com', 'pbs.twimg.com', 'instagram.com']
        if not any(hostname == domain or hostname.endswith('.' + domain) for domain in allowed_domains):
            return HttpResponseForbidden("Domain not in allowlist")

        try:
            ip = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback or str(ip_obj).startswith('169.254.'):
                return HttpResponseForbidden("Blocked private IP")
        except socket.error:
            return HttpResponseForbidden("DNS resolution failed")

        try:
            # Bypass referrer blocks by sending a generic desktop User-Agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.instagram.com/' if 'instagram' in influencer.avatar_url else ''
            }
            response = requests.get(influencer.avatar_url, headers=headers, timeout=5)
            response.raise_for_status()
            
            django_response = HttpResponse(response.content, content_type=response.headers.get('Content-Type', 'image/jpeg'))
            django_response['Cache-Control'] = 'public, max-age=86400'
            return django_response
        except Exception as e:
            # Redirect to fallback ui-avatars if fetching from CDN fails (e.g. expired link)
            return HttpResponseRedirect(f"https://ui-avatars.com/api/?name={influencer.display_name}&background=1e1e2d&color=fff&size=150")



    @action(detail=True, methods=['get'])
    def benchmarks(self, request, pk=None):
        influencer = self.get_object()
        from django.db.models import Q
        benchmarks = OrganicBenchmark.objects.filter(
            Q(influencer=influencer) |
            (Q(global_influencer=influencer.global_influencer) if influencer.global_influencer else Q())
        ).order_by('-engagement_total', '-likes', '-views')
        serializer = OrganicBenchmarkSerializer(benchmarks, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def centi_history(self, request, pk=None):
        influencer = self.get_object()
        from django.db.models import Q
        history = CentiScoreHistory.objects.filter(
            Q(influencer=influencer) |
            (Q(influencer__global_influencer=influencer.global_influencer) if influencer.global_influencer else Q())
        ).order_by('calculated_at')
        
        data = [
            {
                'score': h.score,
                'calculated_at': h.calculated_at,
                'components': h.components
            } for h in history
        ]
        return Response(data)

    @action(detail=True, methods=['get'])
    def authenticity_history(self, request, pk=None):
        influencer = self.get_object()
        from apps.scoring.models import AuthenticityScoreHistory
        history = AuthenticityScoreHistory.objects.filter(influencer=influencer).order_by('calculated_at')
        data = [
            {
                'overall_score': h.overall_score,
                'confidence': h.confidence,
                'platform_scores': h.platform_scores,
                'signal_breakdown': h.signal_breakdown,
                'risk_flags': h.risk_flags,
                'calculated_at': h.calculated_at,
            } for h in history
        ]
        return Response(data)

    @action(detail=False, methods=['get', 'post'], url_path='workspace-settings')
    def workspace_settings(self, request):
        from apps.accounts.models import Workspace
        workspace_id = request.query_params.get('workspace_id') or request.data.get('workspace_id')
        if not workspace_id:
            return Response({'error': 'workspace_id required'}, status=400)
        try:
            workspace = Workspace.objects.get(pk=workspace_id, owner=request.user)
        except Workspace.DoesNotExist:
            return Response({'error': 'Workspace not found'}, status=404)
        
        if request.method == 'POST':
            show = request.data.get('show_authenticity_scores')
            if show is not None:
                workspace.show_authenticity_scores = bool(show)
                workspace.save(update_fields=['show_authenticity_scores'])
        
        return Response({
            'show_authenticity_scores': workspace.show_authenticity_scores,
        })


class SystemAnalyticsViewSet(viewsets.ViewSet):
    permission_classes = (permissions.IsAuthenticated,)

    def list(self, request):
        from django.db.models import Sum
        from datetime import timedelta
        from django.utils import timezone
        from django.conf import settings
        from apps.influencers.models import FetchJob, Influencer
        from apps.campaigns.models import TrackedPost

        now = timezone.now()
        cutoff_24h = now - timedelta(hours=24)
        
        # 1. Budget Stats
        cap = float(getattr(settings, 'DAILY_CREDIT_BUDGET_CAP', 50.00))
        total_used = FetchJob.objects.filter(
            created_at__gte=cutoff_24h
        ).aggregate(total=Sum('cost_credits'))['total'] or 0.0
        
        budget_pct = round((float(total_used) / cap) * 100, 2) if cap > 0 else 0.0

        # 2. Scraper logs (recent jobs)
        recent_jobs = FetchJob.objects.all().order_by('-created_at')[:50]
        jobs_list = []
        for job in recent_jobs:
            entity_name = "Unknown"
            if job.entity_type == 'INFLUENCER':
                inf = Influencer.objects.filter(pk=job.entity_id).first()
                if inf:
                    entity_name = f"Creator: {inf.display_name}"
            elif job.entity_type == 'POST':
                post = TrackedPost.objects.filter(pk=job.entity_id).first()
                if post:
                    entity_name = f"Post: {post.campaign_inf.influencer.display_name} ({post.campaign_inf.campaign.name})"

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

        # 3. Active schedules (monitoring posts)
        monitoring_posts = TrackedPost.objects.filter(
            status=TrackedPost.Statuses.MONITORING
        ).order_by('next_poll_at')[:50]
        
        schedules_list = []
        for post in monitoring_posts:
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
                'campaign': post.campaign_inf.campaign.name,
                'platform': platform,
                'post_url': post.post_url,
                'last_fetched_at': post.last_fetched_at.isoformat() if post.last_fetched_at else None,
                'next_poll_at': post.next_poll_at.isoformat() if post.next_poll_at else None,
            })

        # 4. Overall stats
        overall_stats = {
            'total_influencers': Influencer.objects.count(),
            'total_monitoring_posts': TrackedPost.objects.filter(status=TrackedPost.Statuses.MONITORING).count(),
            'total_completed_jobs': FetchJob.objects.filter(status='DONE').count(),
            'total_failed_jobs': FetchJob.objects.filter(status='FAIL').count(),
        }

        return Response({
            'budget_cap': cap,
            'budget_used_24h': float(total_used),
            'budget_pct': budget_pct,
            'overall_stats': overall_stats,
            'jobs_logs': jobs_list,
            'active_schedules': schedules_list
        })
