import logging
import datetime
from django.db import connection
from django.db.models import Count, Sum, Q
from django.utils import timezone
from django.conf import settings
from rest_framework import generics, viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User, Workspace, Brand, WorkspaceMembership
from apps.campaigns.models import Campaign, CampaignInfluencer, TrackedPost
from apps.influencers.models import Influencer, GlobalInfluencer, OrganicBenchmark, FetchJob, PlatformMetrics
from apps.sentiment.models import Comment, OrganicComment
from apps.scoring.models import SentiScoreHistory, AuthenticityScoreHistory
from apps.reports.models import GeneratedReport
from apps.admin_panel.models import AdminAuditLog, SystemConfig, AdminNotification, AdminInvitation
from apps.admin_panel.permissions import (
    IsPlatformAdmin,
    RequireSuperAdmin,
    RequireDeveloperOrAbove,
    RequireSupportOrAbove,
)
from apps.admin_panel.serializers import (
    AdminRegisterSerializer,
    AdminLoginSerializer,
    AdminUserSerializer,
    AdminUserUpdateSerializer,
    AdminWorkspaceSerializer,
    AdminCampaignSerializer,
    AdminInfluencerSerializer,
    AdminGlobalInfluencerSerializer,
    AdminCreateInfluencerSerializer,
    AdminReportSerializer,
    AdminFetchJobSerializer,
    AdminTrackedPostErrorSerializer,
    AdminNotificationSerializer,
    AdminAuditLogSerializer,
    SystemConfigSerializer,
    AdminInvitationSerializer,
    SendAdminInvitationSerializer,
    AcceptAdminInvitationSerializer,
)
from apps.core.services.email import send_admin_invitation
from apps.admin_panel.pagination import StandardAdminPagination
from apps.admin_panel.utils.diagnostics import classify_scraper_error
import requests
import time
import uuid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AUTHENTICATION VIEWS
# ---------------------------------------------------------------------------

class AdminRegisterView(APIView):
    """
    Register a new platform administrator using a role-specific secret key.
    The account role (SUPER_ADMIN, DEVELOPER, SUPPORT) is determined solely by the key presented.
    """
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = AdminRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)

        AdminAuditLog.log_action(
            admin_user=user,
            action=AdminAuditLog.Actions.CREATE,
            entity_type='AdminUser',
            entity_id=user.id,
            description=f"Admin account registered ({user.admin_role}) for {user.email}",
            request=request
        )

        return Response({
            'message': f"Admin account created successfully with role [{user.admin_role}].",
            'user': AdminUserSerializer(user).data,
            'access': access,
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)


class AdminAcceptInviteView(APIView):
    """
    Accepts a platform administrator invitation via one-time token.
    The invitee sets their password and is granted access based on the role assigned by Super Admin.
    """
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = AcceptAdminInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_token = serializer.validated_data['token']
        password = serializer.validated_data['password']
        full_name = serializer.validated_data.get('full_name', '')

        # Clean token for any quoted-printable or copy-paste artifacts
        token = str(raw_token).strip().strip("'\"")
        if token.startswith('=3D') or token.startswith('=3d'):
            token = token[3:]
        elif token.startswith('3D') or token.startswith('3d'):
            token = token[2:]
        token = token.rstrip('=')

        invitation = AdminInvitation.objects.select_related('invited_by').filter(token=token).first()
        if not invitation and len(token) >= 12:
            candidates = list(AdminInvitation.objects.select_related('invited_by').filter(
                token__startswith=token,
                status=AdminInvitation.Statuses.PENDING
            )[:2])
            if len(candidates) == 1:
                invitation = candidates[0]

        if not invitation:
            return Response({"detail": "Admin invitation token is invalid."}, status=status.HTTP_404_NOT_FOUND)

        if not invitation.is_valid:
            return Response(
                {"detail": "This admin invitation has expired or has already been used."},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = invitation.email.strip().lower()
        user = User.objects.filter(email__iexact=email).first()

        if user:
            # Upgrade existing user to designated admin role
            user.is_platform_admin = True
            user.admin_role = invitation.admin_role
            user.is_staff = True
            user.set_password(password)
            user.save()
        else:
            base_username = email.split('@')[0]
            username = base_username
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{uuid.uuid4().hex[:6]}"

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=full_name.split(' ')[0] if full_name else '',
                last_name=' '.join(full_name.split(' ')[1:]) if (full_name and len(full_name.split(' ')) > 1) else '',
                role=User.Roles.ADMIN,
                is_platform_admin=True,
                admin_role=invitation.admin_role,
                is_staff=True,
            )

            # Ensure user has access to primary operations workspace
            primary_ws = Workspace.objects.first()
            if primary_ws:
                WorkspaceMembership.objects.get_or_create(
                    workspace=primary_ws,
                    user=user,
                    defaults={'role': WorkspaceMembership.Roles.ADMIN}
                )

        invitation.status = AdminInvitation.Statuses.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=['status', 'accepted_at'])

        AdminAuditLog.log_action(
            admin_user=user,
            action=AdminAuditLog.Actions.CREATE,
            entity_type='AdminUser',
            entity_id=user.id,
            description=f"Admin account activated via invitation with role [{invitation.admin_role}] by {invitation.invited_by.email}",
            request=request
        )

        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)

        return Response({
            'message': f"Admin account activated with role [{invitation.admin_role}].",
            'user': AdminUserSerializer(user).data,
            'access': access,
            'refresh': str(refresh),
        }, status=status.HTTP_200_OK)


class AdminLoginView(APIView):
    """Authenticate a platform administrator and return JWT tokens and role bundle."""
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)

        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        AdminAuditLog.log_action(
            admin_user=user,
            action=AdminAuditLog.Actions.LOGIN,
            entity_type='Auth',
            entity_id=user.id,
            description=f"Admin login ({user.admin_role}) from {user.email}",
            request=request
        )

        return Response({
            'user': AdminUserSerializer(user).data,
            'access': access,
            'refresh': str(refresh),
        })


class AdminMeView(APIView):
    """Returns the current authenticated admin's profile and assigned role."""
    permission_classes = (IsPlatformAdmin,)

    def get(self, request):
        return Response(AdminUserSerializer(request.user).data)


# ---------------------------------------------------------------------------
# DASHBOARD OVERVIEW VIEW
# ---------------------------------------------------------------------------

class AdminDashboardOverviewView(APIView):
    """Aggregates high-level platform KPIs for the admin command center."""
    permission_classes = (IsPlatformAdmin,)

    def get(self, request):
        now = timezone.now()
        day_ago = now - datetime.timedelta(hours=24)
        week_ago = now - datetime.timedelta(days=7)

        total_users = User.objects.count()
        new_users_week = User.objects.filter(date_joined__gte=week_ago).count()
        total_workspaces = Workspace.objects.count()

        campaigns_qs = Campaign.objects.all()
        campaign_counts = campaigns_qs.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(status__in=[Campaign.Statuses.ACTIVE, Campaign.Statuses.APPROVED])),
            proposal=Count('id', filter=Q(status__in=[Campaign.Statuses.PROPOSAL, Campaign.Statuses.DRAFT])),
            stopped=Count('id', filter=Q(status=Campaign.Statuses.STOPPED)),
            completed=Count('id', filter=Q(status=Campaign.Statuses.COMPLETED)),
        )

        total_influencers = Influencer.objects.count()

        monitoring_posts = TrackedPost.objects.filter(status=TrackedPost.Statuses.MONITORING).count()
        error_posts = TrackedPost.objects.filter(
            Q(status=TrackedPost.Statuses.ERROR) | Q(consecutive_fetch_failures__gte=5)
        ).count()

        # Scraper budget
        cap = float(getattr(settings, 'DAILY_CREDIT_BUDGET_CAP', 50.00))
        used_24h = FetchJob.objects.filter(
            created_at__gte=day_ago
        ).aggregate(total=Sum('cost_credits'))['total'] or 0.0
        used_24h = float(used_24h)
        budget_pct = round((used_24h / cap) * 100, 2) if cap > 0 else 0.0

        jobs_24h = FetchJob.objects.filter(created_at__gte=day_ago)
        jobs_stats = jobs_24h.aggregate(
            total=Count('id'),
            done=Count('id', filter=Q(status=FetchJob.Statuses.DONE)),
            fail=Count('id', filter=Q(status=FetchJob.Statuses.FAIL)),
            running=Count('id', filter=Q(status=FetchJob.Statuses.RUNNING)),
        )

        # 7-day scraper trend
        trend_7d = []
        for i in range(6, -1, -1):
            date_start = (now - datetime.timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            date_end = date_start + datetime.timedelta(days=1)
            day_jobs = FetchJob.objects.filter(created_at__gte=date_start, created_at__lt=date_end)
            day_stats = day_jobs.aggregate(
                done=Count('id', filter=Q(status=FetchJob.Statuses.DONE)),
                fail=Count('id', filter=Q(status=FetchJob.Statuses.FAIL)),
                cost=Sum('cost_credits')
            )
            trend_7d.append({
                'date': date_start.strftime('%b %d'),
                'success': day_stats['done'] or 0,
                'failed': day_stats['fail'] or 0,
                'cost': round(float(day_stats['cost'] or 0), 4)
            })

        recent_failed_jobs = FetchJob.objects.filter(status=FetchJob.Statuses.FAIL).order_by('-created_at')[:5]
        recent_audits = AdminAuditLog.objects.order_by('-created_at')[:8]

        # Role-filtered notifications
        user_role = getattr(request.user, 'admin_role', 'SUPPORT')
        notifs_qs = AdminNotification.objects.filter(is_read=False)
        if user_role == 'DEVELOPER':
            notifs_qs = notifs_qs.filter(category=AdminNotification.Categories.DEV_ALERT)
        elif user_role == 'SUPPORT':
            notifs_qs = notifs_qs.filter(category=AdminNotification.Categories.SUPPORT_ALERT)
        unread_notifications = notifs_qs[:5]

        return Response({
            'kpis': {
                'total_users': total_users,
                'new_users_week': new_users_week,
                'total_workspaces': total_workspaces,
                'total_campaigns': campaign_counts['total'],
                'active_campaigns': campaign_counts['active'],
                'proposal_campaigns': campaign_counts['proposal'],
                'stopped_campaigns': campaign_counts['stopped'],
                'completed_campaigns': campaign_counts['completed'],
                'total_influencers': total_influencers,
                'monitoring_posts': monitoring_posts,
                'error_posts': error_posts,
                'total_reports': GeneratedReport.objects.count(),
                'total_comments': Comment.objects.count(),
                'budget': {
                    'used_24h': used_24h,
                    'cap': cap,
                    'pct': budget_pct,
                },
                'jobs_24h': jobs_stats,
            },
            'scraper_trend_7d': trend_7d,
            'recent_failed_jobs': AdminFetchJobSerializer(recent_failed_jobs, many=True).data,
            'recent_audits': AdminAuditLogSerializer(recent_audits, many=True).data,
            'unread_notifications': AdminNotificationSerializer(unread_notifications, many=True).data,
        })


# ---------------------------------------------------------------------------
# ROLE-BASED NOTIFICATION VIEWS
# ---------------------------------------------------------------------------

class AdminNotificationView(APIView):
    """Fetches role-filtered in-app notifications and manages read status."""
    permission_classes = (IsPlatformAdmin,)

    def get(self, request):
        user_role = getattr(request.user, 'admin_role', 'SUPPORT')
        qs = AdminNotification.objects.all().order_by('-created_at')

        if user_role == 'DEVELOPER':
            qs = qs.filter(category=AdminNotification.Categories.DEV_ALERT)
        elif user_role == 'SUPPORT':
            qs = qs.filter(category=AdminNotification.Categories.SUPPORT_ALERT)
        # SUPER_ADMIN sees all

        unread_count = qs.filter(is_read=False).count()
        results = AdminNotificationSerializer(qs[:30], many=True).data
        return Response({
            'unread_count': unread_count,
            'results': results
        })

    def post(self, request):
        """Mark notification(s) as read."""
        notif_id = request.data.get('id')
        if notif_id:
            AdminNotification.objects.filter(pk=notif_id).update(
                is_read=True,
                read_by=request.user,
                read_at=timezone.now()
            )
        else:
            # Mark all as read
            AdminNotification.objects.filter(is_read=False).update(
                is_read=True,
                read_by=request.user,
                read_at=timezone.now()
            )
        return Response({'message': 'Notifications updated.'})


# ---------------------------------------------------------------------------
# CMS ENTITY VIEWSETS
# ---------------------------------------------------------------------------

class AdminUserViewSet(viewsets.ModelViewSet):
    """User management CMS. Mutating operations require Super Admin."""
    permission_classes = (IsPlatformAdmin,)
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = AdminUserSerializer
    pagination_class = StandardAdminPagination

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'toggle_active', 'set_admin_role']:
            return [RequireSuperAdmin()]
        return [IsPlatformAdmin()]

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return AdminUserUpdateSerializer
        return AdminUserSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search')
        role = self.request.query_params.get('role')
        admin_role = self.request.query_params.get('admin_role')
        is_admin = self.request.query_params.get('is_platform_admin')

        if search:
            qs = qs.filter(Q(email__icontains=search) | Q(username__icontains=search))
        if role:
            qs = qs.filter(role=role)
        if admin_role:
            qs = qs.filter(admin_role=admin_role)
        if is_admin is not None:
            qs = qs.filter(is_platform_admin=is_admin.lower() in ('true', '1'))

        return qs

    def perform_destroy(self, instance):
        # SUPER ADMIN PROTECTION: No admin can delete the Super Admin account
        if instance.is_superuser or instance.admin_role == User.AdminRoles.SUPER_ADMIN:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("The Super Admin account cannot be deleted.")

        AdminAuditLog.log_action(
            admin_user=self.request.user,
            action=AdminAuditLog.Actions.DELETE,
            entity_type='User',
            entity_id=instance.id,
            description=f"Deleted user account {instance.email}",
            request=self.request
        )
        instance.delete()

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        # SUPER ADMIN PROTECTION: Super Admin cannot be deactivated
        if user.is_superuser or user.admin_role == User.AdminRoles.SUPER_ADMIN:
            return Response({'error': "The Super Admin account cannot be deactivated."}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.UPDATE,
            entity_type='User',
            entity_id=user.id,
            description=f"{'Activated' if user.is_active else 'Deactivated'} user account {user.email}",
            request=request
        )
        return Response({'is_active': user.is_active})

    @action(detail=True, methods=['post'], url_path='set-admin-role')
    def set_admin_role(self, request, pk=None):
        user = self.get_object()
        new_role = request.data.get('admin_role')
        if new_role not in dict(User.AdminRoles.choices):
            return Response({'error': f"Invalid admin role '{new_role}'."}, status=status.HTTP_400_BAD_REQUEST)

        # SUPER ADMIN PROTECTION: Super Admin cannot be demoted
        if (user.is_superuser or user.admin_role == User.AdminRoles.SUPER_ADMIN) and new_role != User.AdminRoles.SUPER_ADMIN:
            return Response({'error': "The Super Admin account cannot be demoted."}, status=status.HTTP_400_BAD_REQUEST)

        user.is_platform_admin = True
        user.admin_role = new_role
        user.save(update_fields=['is_platform_admin', 'admin_role'])

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.UPDATE,
            entity_type='User',
            entity_id=user.id,
            description=f"Assigned platform admin role [{new_role}] to {user.email}",
            request=request
        )
        return Response({'is_platform_admin': user.is_platform_admin, 'admin_role': user.admin_role})


class AdminInvitationViewSet(viewsets.ModelViewSet):
    """
    Super Admin management of platform administrator invitations.
    Super Admins can invite new administrators, specify their role (SUPER_ADMIN, DEVELOPER, SUPPORT),
    list all pending invites, and revoke invites.
    """
    permission_classes = (RequireSuperAdmin,)
    serializer_class = AdminInvitationSerializer
    pagination_class = StandardAdminPagination

    def get_queryset(self):
        qs = AdminInvitation.objects.select_related('invited_by').all().order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = SendAdminInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        admin_role = serializer.validated_data['admin_role']

        # If a pending invite exists, resend
        existing_invite = AdminInvitation.objects.filter(
            email__iexact=email,
            status=AdminInvitation.Statuses.PENDING
        ).first()

        if existing_invite and not existing_invite.is_expired:
            send_admin_invitation(existing_invite)
            return Response(AdminInvitationSerializer(existing_invite).data, status=status.HTTP_200_OK)

        invitation = AdminInvitation.objects.create(
            invited_by=request.user,
            email=email,
            admin_role=admin_role,
        )

        send_admin_invitation(invitation)

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.CREATE,
            entity_type='AdminInvitation',
            entity_id=invitation.id,
            description=f"Sent admin invitation to {email} with role [{admin_role}]",
            request=request
        )

        return Response(AdminInvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='resend')
    def resend(self, request, pk=None):
        invitation = self.get_object()
        if not invitation.is_valid:
            return Response({"error": "Cannot resend an expired or already used invitation."}, status=status.HTTP_400_BAD_REQUEST)

        send_admin_invitation(invitation)
        return Response({"message": f"Invitation resent to {invitation.email}."})

    def perform_destroy(self, instance):
        instance.status = AdminInvitation.Statuses.REVOKED
        instance.save(update_fields=['status'])
        AdminAuditLog.log_action(
            admin_user=self.request.user,
            action=AdminAuditLog.Actions.DELETE,
            entity_type='AdminInvitation',
            entity_id=instance.id,
            description=f"Revoked admin invitation for {instance.email}",
            request=self.request
        )


class AdminWorkspaceViewSet(viewsets.ModelViewSet):
    """CRUD management for all Workspaces."""
    permission_classes = (RequireSupportOrAbove,)
    queryset = Workspace.objects.all().select_related('owner').order_by('-created_at')
    serializer_class = AdminWorkspaceSerializer
    pagination_class = StandardAdminPagination

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search')
        ws_type = self.request.query_params.get('type')

        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(owner__email__icontains=search))
        if ws_type:
            qs = qs.filter(type=ws_type)
        return qs


class AdminCampaignViewSet(viewsets.ModelViewSet):
    """CRUD management for all Campaigns with force-stop and force-restart actions."""
    permission_classes = (RequireSupportOrAbove,)
    queryset = Campaign.objects.all().select_related('workspace', 'brand').order_by('-created_at')
    serializer_class = AdminCampaignSerializer
    pagination_class = StandardAdminPagination

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search')
        c_status = self.request.query_params.get('status')
        workspace_id = self.request.query_params.get('workspace_id')

        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(brand__name__icontains=search))
        if c_status:
            qs = qs.filter(status=c_status)
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)
        return qs

    @action(detail=True, methods=['post'], url_path='force-stop')
    def force_stop(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = Campaign.Statuses.STOPPED
        campaign.save(update_fields=['status'])

        TrackedPost.objects.filter(campaign_inf__campaign=campaign).update(
            status=TrackedPost.Statuses.PAUSED,
            next_poll_at=None
        )

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.UPDATE,
            entity_type='Campaign',
            entity_id=campaign.id,
            description=f"Force-stopped campaign '{campaign.name}' and paused all associated posts",
            request=request
        )
        return Response({'status': campaign.status})

    @action(detail=True, methods=['post'], url_path='force-restart')
    def force_restart(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = Campaign.Statuses.ACTIVE
        campaign.save(update_fields=['status'])

        posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
        posts.update(status=TrackedPost.Statuses.MONITORING, next_poll_at=timezone.now())

        from tasks.fetch_tasks import fetch_tracked_post_metrics_task
        for post in posts:
            fetch_tracked_post_metrics_task.delay(post.id)

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.UPDATE,
            entity_type='Campaign',
            entity_id=campaign.id,
            description=f"Force-restarted campaign '{campaign.name}' and triggered immediate post polling",
            request=request
        )
        return Response({'status': campaign.status})


class AdminInfluencerViewSet(viewsets.ModelViewSet):
    """Platform-wide CRUD management for Global Influencers catalog with staleness threshold, bulk & singular refresh."""
    permission_classes = (RequireSupportOrAbove,)
    queryset = GlobalInfluencer.objects.all().prefetch_related('platform_metrics', 'workspace_links').order_by('-created_at')
    serializer_class = AdminGlobalInfluencerSerializer
    pagination_class = StandardAdminPagination

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search')
        niche = self.request.query_params.get('niche')
        freshness = self.request.query_params.get('freshness')
        ordering = self.request.query_params.get('ordering')

        if search:
            clean_s = search.strip().lstrip('@')
            qs = qs.filter(
                Q(display_name__icontains=search) |
                Q(ig_handle__icontains=clean_s) |
                Q(tiktok_handle__icontains=clean_s) |
                Q(x_handle__icontains=clean_s) |
                Q(niche__icontains=search)
            )
        if niche:
            qs = qs.filter(niche__icontains=niche)

        now = timezone.now()
        if freshness == 'stale':
            qs = qs.filter(Q(data_expires_at__lt=now) | Q(last_scraped_at__isnull=True))
        elif freshness == 'fresh':
            qs = qs.filter(data_expires_at__gte=now)
        elif freshness == 'never_scraped':
            qs = qs.filter(last_scraped_at__isnull=True)

        valid_orderings = {
            'created_at': 'created_at',
            '-created_at': '-created_at',
            'last_scraped_at': 'last_scraped_at',
            '-last_scraped_at': '-last_scraped_at',
            'display_name': 'display_name',
            '-display_name': '-display_name',
            'senti_score': 'senti_score',
            '-senti_score': '-senti_score',
            'fake_follower_score': 'fake_follower_score',
            '-fake_follower_score': '-fake_follower_score',
            'updated_at': 'updated_at',
            '-updated_at': '-updated_at',
        }
        if ordering and ordering in valid_orderings:
            qs = qs.order_by(valid_orderings[ordering])
        else:
            qs = qs.order_by('-created_at')

        return qs

    def create(self, request, *args, **kwargs):
        serializer = AdminCreateInfluencerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ig_handle = data.get('ig_handle')
        tiktok_handle = data.get('tiktok_handle')
        x_handle = data.get('x_handle')
        display_name = data.get('display_name') or ig_handle or tiktok_handle or x_handle or 'Unknown'
        niche = data.get('niche', '')

        # Check existing
        q = Q()
        if ig_handle:
            q |= Q(ig_handle__iexact=ig_handle)
        if tiktok_handle:
            q |= Q(tiktok_handle__iexact=tiktok_handle)
        if x_handle:
            q |= Q(x_handle__iexact=x_handle)

        existing = GlobalInfluencer.objects.filter(q).first() if q else None
        if existing:
            return Response(
                {"error": f"An influencer with matching handle already exists: {existing.display_name}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        global_inf = GlobalInfluencer.objects.create(
            display_name=display_name,
            niche=niche,
            ig_handle=ig_handle,
            tiktok_handle=tiktok_handle,
            x_handle=x_handle,
            avatar_url='https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png',
            scrape_in_progress=True,
        )

        from tasks.influencer_tasks import fetch_global_influencer_task
        fetch_global_influencer_task.delay(global_inf.id)

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.CREATE,
            entity_type='GlobalInfluencer',
            entity_id=global_inf.id,
            description=f"Admin created new creator catalog entry: {global_inf.display_name}",
            request=request
        )

        out_serializer = AdminGlobalInfluencerSerializer(global_inf)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        global_inf = self.get_object()
        name = global_inf.display_name
        inf_id = global_inf.id

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.DELETE,
            entity_type='GlobalInfluencer',
            entity_id=inf_id,
            description=f"Admin deleted creator {name} from platform catalog",
            request=request
        )

        global_inf.delete()
        return Response({'message': f"Creator {name} successfully deleted."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='force-refresh')
    def force_refresh(self, request, pk=None):
        global_inf = self.get_object()
        global_inf.scrape_in_progress = True
        global_inf.consecutive_fetch_failures = 0
        global_inf.save(update_fields=['scrape_in_progress', 'consecutive_fetch_failures'])

        from tasks.influencer_tasks import refresh_global_influencer_task
        refresh_global_influencer_task.delay(global_inf.id)

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.RETRY,
            entity_type='GlobalInfluencer',
            entity_id=global_inf.id,
            description=f"Dispatched background scrape refresh for creator {global_inf.display_name}",
            request=request
        )
        return Response({'message': f"Refresh task queued for {global_inf.display_name}."})

    @action(detail=False, methods=['post'], url_path='refetch-all')
    def refetch_all(self, request):
        only_stale = request.data.get('only_stale', False)
        qs = GlobalInfluencer.objects.filter(scrape_in_progress=False)
        if only_stale:
            now = timezone.now()
            qs = qs.filter(Q(data_expires_at__lt=now) | Q(last_scraped_at__isnull=True))

        target_ids = list(qs.values_list('id', flat=True)[:100])
        from tasks.influencer_tasks import refresh_global_influencer_task

        for inf_id in target_ids:
            refresh_global_influencer_task.delay(inf_id)
        
        GlobalInfluencer.objects.filter(id__in=target_ids).update(scrape_in_progress=True)

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.RETRY,
            entity_type='GlobalInfluencer',
            description=f"Admin triggered bulk background refresh for {len(target_ids)} creators",
            request=request
        )

        return Response({
            'message': f"Queued {len(target_ids)} creators for background refresh.",
            'count': len(target_ids)
        })

    @action(detail=False, methods=['get', 'post'], url_path='staleness-config')
    def staleness_config(self, request):
        from apps.influencers.utils import get_influencer_staleness_hours, set_influencer_staleness_hours

        if request.method == 'GET':
            hours = get_influencer_staleness_hours()
            return Response({'threshold_hours': hours})

        # POST
        hours = request.data.get('threshold_hours')
        try:
            hours = int(hours)
            if hours < 1:
                return Response({'error': "Threshold must be at least 1 hour."}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'error': "Invalid threshold value."}, status=status.HTTP_400_BAD_REQUEST)

        saved_hours = set_influencer_staleness_hours(hours, user=request.user)
        return Response({
            'threshold_hours': saved_hours,
            'message': f"Influencer staleness threshold successfully updated to {saved_hours} hours."
        })

    @action(detail=True, methods=['post'], url_path='reset-failures')
    def reset_failures(self, request, pk=None):
        global_inf = self.get_object()
        global_inf.consecutive_fetch_failures = 0
        global_inf.last_fetch_error = None
        global_inf.save(update_fields=['consecutive_fetch_failures', 'last_fetch_error'])

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.UPDATE,
            entity_type='GlobalInfluencer',
            entity_id=global_inf.id,
            description=f"Reset fetch failures counter for {global_inf.display_name}",
            request=request
        )
        return Response({'message': 'Failure counter reset to 0.'})


class AdminReportViewSet(viewsets.ReadOnlyModelViewSet):
    """View and manage generated PDF reports."""
    permission_classes = (RequireSupportOrAbove,)
    queryset = GeneratedReport.objects.all().select_related('campaign', 'generated_by').order_by('-generated_at')
    serializer_class = AdminReportSerializer
    pagination_class = StandardAdminPagination

    def get_queryset(self):
        qs = super().get_queryset()
        report_type = self.request.query_params.get('report_type')
        status_filter = self.request.query_params.get('status')
        if report_type:
            qs = qs.filter(report_type=report_type)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def destroy(self, request, *args, **kwargs):
        report = self.get_object()
        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.DELETE,
            entity_type='GeneratedReport',
            entity_id=report.id,
            description=f"Deleted report #{report.id} ({report.report_type})",
            request=request
        )
        report.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='retry')
    def retry_generation(self, request, pk=None):
        report = self.get_object()
        from tasks.report_tasks import generate_pdf_report_task
        report.status = GeneratedReport.ReportStatus.PENDING
        report.save(update_fields=['status'])
        generate_pdf_report_task.delay(report.id)

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.RETRY,
            entity_type='GeneratedReport',
            entity_id=report.id,
            description=f"Re-queued PDF compilation task for report #{report.id}",
            request=request
        )
        return Response({'message': f"Report #{report.id} compilation re-queued."})


# ---------------------------------------------------------------------------
# DEVELOPER TOOLS & INFRASTRUCTURE MONITORING
# ---------------------------------------------------------------------------

class SystemHealthView(APIView):
    """Checks live status of PostgreSQL, Redis, and Celery workers."""
    permission_classes = (RequireDeveloperOrAbove,)

    def get(self, request):
        health_status = {
            'database': {'status': 'UNKNOWN'},
            'redis': {'status': 'UNKNOWN'},
            'celery': {'status': 'UNKNOWN'},
            'timestamp': timezone.now().isoformat(),
        }

        # PostgreSQL check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
            health_status['database'] = {
                'status': 'HEALTHY',
                'vendor': connection.vendor,
                'host': connection.settings_dict.get('HOST', 'localhost'),
                'name': connection.settings_dict.get('NAME', 'sentimentri_db'),
            }
        except Exception as e:
            health_status['database'] = {'status': 'UNHEALTHY', 'error': str(e)}

        # Redis check
        try:
            import redis
            redis_url = getattr(settings, 'REDIS_URL', 'redis://redis:6379/0')
            r = redis.Redis.from_url(redis_url, socket_timeout=2.0)
            if r.ping():
                info = r.info('memory')
                health_status['redis'] = {
                    'status': 'HEALTHY',
                    'url': redis_url.split('@')[-1] if '@' in redis_url else redis_url,
                    'used_memory_human': info.get('used_memory_human', 'N/A'),
                }
            else:
                health_status['redis'] = {'status': 'UNHEALTHY', 'error': 'Ping failed'}
        except Exception as e:
            health_status['redis'] = {'status': 'UNHEALTHY', 'error': str(e)}

        # Celery inspector
        try:
            from sentimentri.celery import app as celery_app
            insp = celery_app.control.inspect(timeout=1.5)
            active_workers = insp.ping() or {}
            queues_by_worker = insp.active_queues() or {}

            if active_workers:
                worker_list = []
                for w_name in active_workers.keys():
                    w_queues = [q['name'] for q in queues_by_worker.get(w_name, [])]
                    worker_list.append({'name': w_name, 'queues': w_queues})

                health_status['celery'] = {
                    'status': 'HEALTHY',
                    'worker_count': len(worker_list),
                    'workers': worker_list,
                }
            else:
                health_status['celery'] = {
                    'status': 'WARNING',
                    'message': 'No responsive Celery workers discovered on ping.',
                    'worker_count': 0
                }
        except Exception as e:
            health_status['celery'] = {'status': 'UNHEALTHY', 'error': str(e)}

        components = [health_status['database']['status'], health_status['redis']['status']]
        if 'UNHEALTHY' in components:
            overall = 'CRITICAL'
        elif health_status['celery']['status'] == 'WARNING':
            overall = 'DEGRADED'
        else:
            overall = 'HEALTHY'

        health_status['overall'] = overall
        return Response(health_status)


class ScraperJobsView(APIView):
    """Audit log of all FetchJob scraper runs with search and provider/status filtering."""
    permission_classes = (RequireDeveloperOrAbove,)

    def get(self, request):
        qs = FetchJob.objects.all().order_by('-created_at')
        provider = request.query_params.get('provider')
        job_status = request.query_params.get('status')
        search = request.query_params.get('search')

        if provider and provider != 'ALL':
            qs = qs.filter(provider=provider)
        if job_status and job_status != 'ALL':
            qs = qs.filter(status=job_status)
        if search:
            qs = qs.filter(Q(error_message__icontains=search) | Q(entity_type__icontains=search))

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        total_count = qs.count()

        start = (page - 1) * page_size
        jobs = qs[start:start + page_size]

        serializer = AdminFetchJobSerializer(jobs, many=True)
        return Response({
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size if total_count > 0 else 1,
            'results': serializer.data
        })


class RetryJobView(APIView):
    """Retries a failed FetchJob by re-dispatching its underlying Celery task."""
    permission_classes = (RequireDeveloperOrAbove,)

    def post(self, request, pk=None):
        try:
            job = FetchJob.objects.get(pk=pk)
        except FetchJob.DoesNotExist:
            return Response({'error': 'FetchJob not found.'}, status=status.HTTP_404_NOT_FOUND)

        if job.entity_type == 'INFLUENCER':
            from tasks.fetch_tasks import fetch_influencer_profile_task
            fetch_influencer_profile_task.delay(job.entity_id)
        elif job.entity_type == 'POST':
            from tasks.fetch_tasks import fetch_tracked_post_metrics_task
            fetch_tracked_post_metrics_task.delay(job.entity_id)

        job.status = FetchJob.Statuses.PENDING
        job.error_message = None
        job.save(update_fields=['status', 'error_message'])

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.RETRY,
            entity_type='FetchJob',
            entity_id=job.id,
            description=f"Retried {job.provider} FetchJob for {job.entity_type} #{job.entity_id}",
            request=request
        )
        return Response({'message': f"Job #{job.id} re-enqueued successfully."})


class ErrorPostsView(APIView):
    """Surfaces all TrackedPosts currently in ERROR state or having consecutive fetch failures with server-side pagination."""
    permission_classes = (RequireSupportOrAbove,)

    def get(self, request):
        qs = TrackedPost.objects.filter(
            Q(status=TrackedPost.Statuses.ERROR) | Q(consecutive_fetch_failures__gt=0)
        ).select_related('campaign_inf__campaign', 'campaign_inf__influencer').order_by('-consecutive_fetch_failures', '-last_fetch_attempt_at')

        search = request.query_params.get('search')
        platform = request.query_params.get('platform')

        if search:
            qs = qs.filter(
                Q(post_url__icontains=search) |
                Q(last_fetch_error__icontains=search) |
                Q(campaign_inf__campaign__name__icontains=search) |
                Q(campaign_inf__influencer__display_name__icontains=search)
            )
        if platform and platform != 'ALL':
            qs = qs.filter(platform=platform)

        paginator = StandardAdminPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminTrackedPostErrorSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class RetryPostView(APIView):
    """Resets error state for a post and re-queues immediate fetch."""
    permission_classes = (RequireSupportOrAbove,)

    def post(self, request, pk=None):
        try:
            post = TrackedPost.objects.get(pk=pk)
        except TrackedPost.DoesNotExist:
            return Response({'error': 'TrackedPost not found.'}, status=status.HTTP_404_NOT_FOUND)

        post.status = TrackedPost.Statuses.MONITORING
        post.consecutive_fetch_failures = 0
        post.last_fetch_error = None
        post.next_poll_at = timezone.now()
        post.save()

        from tasks.fetch_tasks import fetch_tracked_post_metrics_task
        fetch_tracked_post_metrics_task.delay(post.id)

        AdminAuditLog.log_action(
            admin_user=request.user,
            action=AdminAuditLog.Actions.RETRY,
            entity_type='TrackedPost',
            entity_id=post.id,
            description=f"Reset failures and dispatched immediate poll for post {post.post_url}",
            request=request
        )
        return Response({'message': f"Post #{post.id} scheduled for immediate re-fetch."})


class PollingQueueView(APIView):
    """View all monitored posts and their upcoming scheduled poll times with server-side pagination."""
    permission_classes = (RequireDeveloperOrAbove,)

    def get(self, request):
        qs = TrackedPost.objects.filter(
            status=TrackedPost.Statuses.MONITORING
        ).select_related(
            'campaign_inf__campaign',
            'campaign_inf__influencer'
        ).order_by('next_poll_at')

        platform = request.query_params.get('platform')
        tier = request.query_params.get('tier')
        search = request.query_params.get('search')

        if platform and platform != 'ALL':
            qs = qs.filter(platform=platform)
        if tier and tier != 'ALL':
            qs = qs.filter(polling_tier=tier)
        if search:
            qs = qs.filter(
                Q(post_url__icontains=search) |
                Q(campaign_inf__campaign__name__icontains=search) |
                Q(campaign_inf__influencer__display_name__icontains=search)
            )

        paginator = StandardAdminPagination()
        page = paginator.paginate_queryset(qs, request)
        data = []
        for p in page:
            data.append({
                'id': p.id,
                'creator': p.campaign_inf.influencer.display_name if p.campaign_inf else 'Unknown',
                'campaign': p.campaign_inf.campaign.name if p.campaign_inf and p.campaign_inf.campaign else 'Unknown',
                'platform': p.platform,
                'post_url': p.post_url,
                'tier': p.polling_tier,
                'last_fetched_at': p.last_fetched_at,
                'next_poll_at': p.next_poll_at,
                'failures': p.consecutive_fetch_failures,
            })
        return paginator.get_paginated_response(data)


class DatabaseStatsView(APIView):
    """Returns row counts and storage insights across all application tables."""
    permission_classes = (RequireDeveloperOrAbove,)

    def get(self, request):
        stats = {
            'accounts': {
                'users': User.objects.count(),
                'platform_admins': User.objects.filter(is_platform_admin=True).count(),
                'workspaces': Workspace.objects.count(),
                'brands': Brand.objects.count(),
                'memberships': WorkspaceMembership.objects.count(),
            },
            'campaigns': {
                'campaigns': Campaign.objects.count(),
                'campaign_creators': CampaignInfluencer.objects.count(),
                'tracked_posts': TrackedPost.objects.count(),
            },
            'influencers': {
                'influencers': Influencer.objects.count(),
                'platform_metrics': PlatformMetrics.objects.count(),
                'organic_benchmarks': OrganicBenchmark.objects.count(),
                'scraper_jobs': FetchJob.objects.count(),
            },
            'sentiment': {
                'campaign_comments': Comment.objects.count(),
                'organic_comments': OrganicComment.objects.count(),
            },
            'scoring': {
                'senti_score_history': SentiScoreHistory.objects.count(),
                'authenticity_history': AuthenticityScoreHistory.objects.count(),
            },
            'reports': {
                'generated_reports': GeneratedReport.objects.count(),
            },
            'admin': {
                'audit_logs': AdminAuditLog.objects.count(),
                'system_configs': SystemConfig.objects.count(),
                'notifications': AdminNotification.objects.count(),
            }
        }
        return Response(stats)


# ---------------------------------------------------------------------------
# CONFIGURATION & AUDIT LOG VIEWS
# ---------------------------------------------------------------------------

class SystemConfigViewSet(viewsets.ModelViewSet):
    """Read and update runtime system settings. Super Admin only."""
    permission_classes = (RequireSuperAdmin,)
    queryset = SystemConfig.objects.all().order_by('key')
    serializer_class = SystemConfigSerializer

    def perform_create(self, serializer):
        config = serializer.save(updated_by=self.request.user)
        AdminAuditLog.log_action(
            admin_user=self.request.user,
            action=AdminAuditLog.Actions.CONFIG_CHANGE,
            entity_type='SystemConfig',
            entity_id=config.id,
            description=f"Created system configuration '{config.key}'",
            request=self.request
        )

    def perform_update(self, serializer):
        config = serializer.save(updated_by=self.request.user)
        AdminAuditLog.log_action(
            admin_user=self.request.user,
            action=AdminAuditLog.Actions.CONFIG_CHANGE,
            entity_type='SystemConfig',
            entity_id=config.id,
            description=f"Updated system configuration '{config.key}'",
            request=self.request
        )


class EnvironmentConfigView(APIView):
    """Provides non-secret runtime environment flags and API provider configurations."""
    permission_classes = (RequireDeveloperOrAbove,)

    def get(self, request):
        sv_key = getattr(settings, 'SOCIAL_VAULT_API_KEY', '')
        sociavault_set = bool(sv_key and not sv_key.startswith('your_'))
        apify_set = bool(getattr(settings, 'APIFY_API_TOKEN', ''))
        socialdata_set = bool(getattr(settings, 'SOCIALDATA_API_KEY', ''))
        deepseek_set = bool(getattr(settings, 'DEEP_SEEK_SECRET', ''))

        return Response({
            'debug': getattr(settings, 'DEBUG', False),
            'allowed_hosts': getattr(settings, 'ALLOWED_HOSTS', []),
            'time_zone': getattr(settings, 'TIME_ZONE', 'UTC'),
            'daily_credit_budget_cap': getattr(settings, 'DAILY_CREDIT_BUDGET_CAP', 50.0),
            'keys_configured': {
                'super_admin_key_set': bool(getattr(settings, 'SUPER_ADMIN_ACCESS_KEY', '')),
                'developer_key_set': bool(getattr(settings, 'DEVELOPER_ACCESS_KEY', '')),
                'support_key_set': bool(getattr(settings, 'SUPPORT_ACCESS_KEY', '')),
            },
            'integrations': {
                'sociavault_configured': sociavault_set,
                'deepseek_configured': deepseek_set,
                'apify_configured': apify_set,
                'socialdata_configured': socialdata_set,
            }
        })


class AuditLogsView(APIView):
    """Chronological queryable log of all administrative actions."""
    permission_classes = (RequireDeveloperOrAbove,)

    def get(self, request):
        qs = AdminAuditLog.objects.all().select_related('admin_user').order_by('-created_at')
        action_filter = request.query_params.get('action')
        entity_filter = request.query_params.get('entity_type')
        search = request.query_params.get('search')

        if action_filter and action_filter != 'ALL':
            qs = qs.filter(action=action_filter)
        if entity_filter and entity_filter != 'ALL':
            qs = qs.filter(entity_type=entity_filter)
        if search:
            qs = qs.filter(
                Q(description__icontains=search) |
                Q(admin_user__email__icontains=search) |
                Q(ip_address__icontains=search)
            )

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 25))
        total_count = qs.count()

        start = (page - 1) * page_size
        logs = qs[start:start + page_size]

        serializer = AdminAuditLogSerializer(logs, many=True)
        return Response({
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size if total_count > 0 else 1,
            'results': serializer.data
        })


# ---------------------------------------------------------------------------
# API SPEND TELEMETRY & KEY HEALTH VIEWS
# ---------------------------------------------------------------------------

class ApiSpendView(APIView):
    """
    Detailed spend telemetry for scraping and AI providers (SociaVault, DeepSeek, and legacy Apify/SocialData).
    Returns lifetime spend, 24h spend vs budget cap, 30-day time series,
    spend by entity type, top consuming campaigns & creators, and paginated ledger.
    """
    permission_classes = (RequireDeveloperOrAbove,)

    def get(self, request):
        from apps.influencers.models import ApiCostLog
        now = timezone.now()
        day_ago = now - datetime.timedelta(hours=24)
        cap = float(getattr(settings, 'DAILY_CREDIT_BUDGET_CAP', 50.0))

        # Lifetime aggregates from ApiCostLog
        sociavault_lifetime = float(ApiCostLog.objects.filter(provider=ApiCostLog.Providers.SOCIAVAULT).aggregate(s=Sum('cost_usd'))['s'] or 0.0)
        deepseek_lifetime = float(ApiCostLog.objects.filter(provider=ApiCostLog.Providers.DEEPSEEK).aggregate(s=Sum('cost_usd'))['s'] or 0.0)

        # Legacy FetchJob aggregates for Apify and SocialData
        legacy_stats = FetchJob.objects.aggregate(
            apify=Sum('cost_credits', filter=Q(provider=FetchJob.Providers.APIFY)),
            socialdata=Sum('cost_credits', filter=Q(provider=FetchJob.Providers.SOCIALDATA)),
            total_fetch_jobs=Count('id')
        )
        apify_lifetime = float(legacy_stats['apify'] or 0.0)
        socialdata_lifetime = float(legacy_stats['socialdata'] or 0.0)

        total_lifetime = sociavault_lifetime + deepseek_lifetime + apify_lifetime + socialdata_lifetime
        total_calls_lifetime = ApiCostLog.objects.count() + (legacy_stats['total_fetch_jobs'] or 0)

        # 24h aggregates
        sv_24h = float(ApiCostLog.objects.filter(provider=ApiCostLog.Providers.SOCIAVAULT, created_at__gte=day_ago).aggregate(s=Sum('cost_usd'))['s'] or 0.0)
        ds_24h = float(ApiCostLog.objects.filter(provider=ApiCostLog.Providers.DEEPSEEK, created_at__gte=day_ago).aggregate(s=Sum('cost_usd'))['s'] or 0.0)

        legacy_24h = FetchJob.objects.filter(created_at__gte=day_ago).aggregate(
            apify=Sum('cost_credits', filter=Q(provider=FetchJob.Providers.APIFY)),
            socialdata=Sum('cost_credits', filter=Q(provider=FetchJob.Providers.SOCIALDATA)),
            count=Count('id')
        )
        apify_24h = float(legacy_24h['apify'] or 0.0)
        socialdata_24h = float(legacy_24h['socialdata'] or 0.0)

        total_24h = sv_24h + ds_24h + apify_24h + socialdata_24h
        calls_24h = ApiCostLog.objects.filter(created_at__gte=day_ago).count() + (legacy_24h['count'] or 0)
        budget_pct = round((total_24h / cap) * 100, 2) if cap > 0 else 0.0

        # By Category / Entity Type
        by_entity = {
            'POST': {
                'cost': round(float(ApiCostLog.objects.filter(cost_category__in=[ApiCostLog.CostCategories.SOCIAVAULT_POSTS, ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS]).aggregate(s=Sum('cost_usd'))['s'] or 0.0), 4),
                'count': ApiCostLog.objects.filter(cost_category__in=[ApiCostLog.CostCategories.SOCIAVAULT_POSTS, ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS]).count()
            },
            'INFLUENCER': {
                'cost': round(float(ApiCostLog.objects.filter(cost_category=ApiCostLog.CostCategories.SOCIAVAULT_PROFILE).aggregate(s=Sum('cost_usd'))['s'] or 0.0), 4),
                'count': ApiCostLog.objects.filter(cost_category=ApiCostLog.CostCategories.SOCIAVAULT_PROFILE).count()
            },
            'AI_AUDIT': {
                'cost': round(deepseek_lifetime, 4),
                'count': ApiCostLog.objects.filter(provider=ApiCostLog.Providers.DEEPSEEK).count()
            }
        }

        # 30-day time series daily breakdown
        timeseries_30d = []
        for i in range(29, -1, -1):
            date_start = (now - datetime.timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            date_end = date_start + datetime.timedelta(days=1)
            
            d_log_stats = ApiCostLog.objects.filter(created_at__gte=date_start, created_at__lt=date_end).aggregate(
                sociavault=Sum('cost_usd', filter=Q(provider=ApiCostLog.Providers.SOCIAVAULT)),
                deepseek=Sum('cost_usd', filter=Q(provider=ApiCostLog.Providers.DEEPSEEK)),
                total=Sum('cost_usd'),
                count=Count('id')
            )
            d_job_stats = FetchJob.objects.filter(created_at__gte=date_start, created_at__lt=date_end).aggregate(
                apify=Sum('cost_credits', filter=Q(provider=FetchJob.Providers.APIFY)),
                socialdata=Sum('cost_credits', filter=Q(provider=FetchJob.Providers.SOCIALDATA)),
                total=Sum('cost_credits'),
                count=Count('id')
            )

            sv_val = float(d_log_stats['sociavault'] or 0.0)
            ds_val = float(d_log_stats['deepseek'] or 0.0)
            apify_val = float(d_job_stats['apify'] or 0.0)
            sd_val = float(d_job_stats['socialdata'] or 0.0)
            day_total = sv_val + ds_val + apify_val + sd_val
            day_count = (d_log_stats['count'] or 0) + (d_job_stats['count'] or 0)

            timeseries_30d.append({
                'date': date_start.strftime('%Y-%m-%d'),
                'label': date_start.strftime('%b %d'),
                'sociavault': round(sv_val, 4),
                'deepseek': round(ds_val, 4),
                'apify': round(apify_val, 4),
                'socialdata': round(sd_val, 4),
                'total': round(day_total, 4),
                'jobs': day_count
            })

        # Top consuming campaigns
        top_campaigns_data = []
        try:
            camp_logs = ApiCostLog.objects.filter(campaign__isnull=False).values('campaign_id', 'campaign__name').annotate(
                spend=Sum('cost_usd'), calls=Count('id')
            ).order_by('-spend')[:5]
            for cl in camp_logs:
                top_campaigns_data.append({
                    'id': cl['campaign_id'],
                    'name': cl['campaign__name'] or f"Campaign #{cl['campaign_id']}",
                    'spend': round(float(cl['spend'] or 0.0), 4),
                    'posts_count': cl['calls']
                })
        except Exception as e:
            logger.warning(f"Error computing top campaigns spend: {e}")

        # Top consuming influencers
        top_influencers_data = []
        try:
            inf_logs = ApiCostLog.objects.filter(global_influencer__isnull=False).values('global_influencer_id', 'global_influencer__display_name').annotate(
                spend=Sum('cost_usd'), fetch_count=Count('id')
            ).order_by('-spend')[:5]
            for il in inf_logs:
                top_influencers_data.append({
                    'id': il['global_influencer_id'],
                    'name': il['global_influencer__display_name'] or f"Creator #{il['global_influencer_id']}",
                    'spend': round(float(il['spend'] or 0.0), 4),
                    'fetch_count': il['fetch_count']
                })
        except Exception as e:
            logger.warning(f"Error computing top influencers spend: {e}")

        # Recent Spend Ledger (Paginated)
        provider_filter = request.query_params.get('provider')
        entity_filter = request.query_params.get('entity_type')

        ledger_qs = ApiCostLog.objects.all().select_related('workspace', 'campaign', 'global_influencer').order_by('-created_at')
        if provider_filter and provider_filter != 'ALL':
            ledger_qs = ledger_qs.filter(provider=provider_filter)
        if entity_filter and entity_filter != 'ALL':
            ledger_qs = ledger_qs.filter(cost_category=entity_filter)

        page_num = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 25))
        total_ledger_count = ledger_qs.count()

        if total_ledger_count == 0:
            fetch_job_qs = FetchJob.objects.all().order_by('-created_at')
            if provider_filter and provider_filter != 'ALL':
                fetch_job_qs = fetch_job_qs.filter(provider=provider_filter)
            paginator = StandardAdminPagination()
            ledger_page = paginator.paginate_queryset(fetch_job_qs, request)
            ledger_data = AdminFetchJobSerializer(ledger_page, many=True).data
            paginated_ledger = paginator.get_paginated_response(ledger_data).data
        else:
            start = (page_num - 1) * page_size
            page_logs = ledger_qs[start:start + page_size]
            serialized_ledger = []
            for item in page_logs:
                target_name = (
                    item.global_influencer.display_name if item.global_influencer
                    else (item.campaign.name if item.campaign else 'System')
                )
                serialized_ledger.append({
                    'id': item.id,
                    'created_at': item.created_at.isoformat(),
                    'provider': item.provider,
                    'endpoint': item.endpoint,
                    'entity_type': item.pipeline_stage,
                    'entity_id': item.global_influencer_id or item.campaign_id or 0,
                    'target_name': target_name,
                    'status': 'DONE' if item.success else 'FAIL',
                    'cost_credits': float(item.cost_usd),
                    'credits_used': float(item.credits_used),
                    'response_time_ms': item.response_time_ms,
                    'error_message': item.error_message,
                })
            total_pages = (total_ledger_count + page_size - 1) // page_size if total_ledger_count > 0 else 1
            paginated_ledger = {
                'count': total_ledger_count,
                'total_pages': total_pages,
                'current_page': page_num,
                'results': serialized_ledger
            }

        return Response({
            'summary': {
                'lifetime_total_usd': round(total_lifetime, 4),
                'lifetime_sociavault_usd': round(sociavault_lifetime, 4),
                'lifetime_deepseek_usd': round(deepseek_lifetime, 4),
                'lifetime_apify_usd': round(apify_lifetime, 4),
                'lifetime_socialdata_usd': round(socialdata_lifetime, 4),
                'lifetime_jobs_count': total_calls_lifetime,
                'spend_24h': round(total_24h, 4),
                'sociavault_spend_24h': round(sv_24h, 4),
                'deepseek_spend_24h': round(ds_24h, 4),
                'apify_spend_24h': round(apify_24h, 4),
                'socialdata_spend_24h': round(socialdata_24h, 4),
                'jobs_count_24h': calls_24h,
                'daily_budget_cap': cap,
                'budget_utilization_pct': budget_pct,
                'avg_cost_per_job': round(total_lifetime / total_calls_lifetime, 4) if total_calls_lifetime > 0 else 0.0
            },
            'by_entity_type': by_entity,
            'timeseries_30d': timeseries_30d,
            'top_campaigns': top_campaigns_data,
            'top_influencers': top_influencers_data,
            'ledger': paginated_ledger
        })


class TestApiKeysView(APIView):
    """
    Live real-time probe to test configured scraping API keys (SociaVault, DeepSeek, and legacy Apify/SocialData).
    Returns connection status, response latency, account info, and credit balance diagnosis.
    """
    permission_classes = (RequireDeveloperOrAbove,)

    def post(self, request):
        target_provider = request.data.get('provider', 'ALL').upper()
        results = {}

        # 1. SociaVault Probe
        if target_provider in ['ALL', 'SOCIAVAULT']:
            sv_key = getattr(settings, 'SOCIAL_VAULT_API_KEY', '')
            if not sv_key or sv_key.startswith('your_'):
                results['sociavault'] = {
                    'provider': 'SOCIAVAULT',
                    'status': 'NOT_CONFIGURED',
                    'badge': 'Not Configured',
                    'severity': 'warning',
                    'latency_ms': 0,
                    'message': 'SOCIAL_VAULT_API_KEY is missing from server environment.'
                }
            else:
                t0 = time.time()
                try:
                    resp = requests.get(
                        'https://api.sociavault.com/v1/scrape/instagram/profile',
                        headers={'X-API-Key': sv_key, 'Accept': 'application/json'},
                        params={'handle': 'instagram'},
                        timeout=10
                    )
                    latency = int((time.time() - t0) * 1000)
                    if resp.status_code == 200:
                        results['sociavault'] = {
                            'provider': 'SOCIAVAULT',
                            'status': 'HEALTHY',
                            'badge': 'Active & Operational',
                            'severity': 'success',
                            'http_code': 200,
                            'latency_ms': latency,
                            'message': f"Key verified successfully. Unified Instagram, TikTok, and X scraping operational ({latency}ms)."
                        }
                    elif resp.status_code in [401, 403]:
                        results['sociavault'] = {
                            'provider': 'SOCIAVAULT',
                            'status': 'EXPIRED_OR_INVALID',
                            'badge': 'Auth Expired (401/403)',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': 'SociaVault rejected the API key. Please verify SOCIAL_VAULT_API_KEY in .env.'
                        }
                    elif resp.status_code == 402:
                        results['sociavault'] = {
                            'provider': 'SOCIAVAULT',
                            'status': 'PAYMENT_REQUIRED',
                            'badge': 'Credits Depleted (402)',
                            'severity': 'critical',
                            'http_code': 402,
                            'latency_ms': latency,
                            'message': 'SociaVault credit balance exhausted. Top up credits at https://sociavault.com to resume polling.'
                        }
                    else:
                        results['sociavault'] = {
                            'provider': 'SOCIAVAULT',
                            'status': 'ERROR',
                            'badge': f'Error {resp.status_code}',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': f'SociaVault API responded with HTTP {resp.status_code}: {resp.text[:120]}'
                        }
                except Exception as exc:
                    results['sociavault'] = {
                        'provider': 'SOCIAVAULT',
                        'status': 'UNREACHABLE',
                        'badge': 'Connection Failed',
                        'severity': 'critical',
                        'latency_ms': 0,
                        'message': f'Could not connect to SociaVault: {str(exc)}'
                    }

        # 2. DeepSeek Probe
        if target_provider in ['ALL', 'DEEPSEEK']:
            ds_key = getattr(settings, 'DEEP_SEEK_SECRET', '')
            if not ds_key or ds_key.startswith('your_'):
                results['deepseek'] = {
                    'provider': 'DEEPSEEK',
                    'status': 'NOT_CONFIGURED',
                    'badge': 'Not Configured',
                    'severity': 'warning',
                    'latency_ms': 0,
                    'message': 'DEEP_SEEK_SECRET is missing from server environment.'
                }
            else:
                t0 = time.time()
                try:
                    resp = requests.get(
                        'https://api.deepseek.com/models',
                        headers={'Authorization': f'Bearer {ds_key}', 'Accept': 'application/json'},
                        timeout=8
                    )
                    latency = int((time.time() - t0) * 1000)
                    if resp.status_code == 200:
                        results['deepseek'] = {
                            'provider': 'DEEPSEEK',
                            'status': 'HEALTHY',
                            'badge': 'Active & Operational',
                            'severity': 'success',
                            'http_code': 200,
                            'latency_ms': latency,
                            'message': f"DeepSeek AI key verified. Creator Intelligence & Sentiment operational ({latency}ms)."
                        }
                    elif resp.status_code in [401, 403]:
                        results['deepseek'] = {
                            'provider': 'DEEPSEEK',
                            'status': 'EXPIRED_OR_INVALID',
                            'badge': 'Auth Expired (401/403)',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': 'DeepSeek rejected the secret key. Verify DEEP_SEEK_SECRET in .env.'
                        }
                    else:
                        results['deepseek'] = {
                            'provider': 'DEEPSEEK',
                            'status': 'ERROR',
                            'badge': f'Error {resp.status_code}',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': f"DeepSeek returned HTTP {resp.status_code}."
                        }
                except Exception as exc:
                    results['deepseek'] = {
                        'provider': 'DEEPSEEK',
                        'status': 'UNREACHABLE',
                        'badge': 'Connection Failed',
                        'severity': 'critical',
                        'latency_ms': 0,
                        'message': f"Could not connect to DeepSeek API: {str(exc)}"
                    }

        # 3. Apify Probe (Legacy)
        if target_provider in ['ALL', 'APIFY']:
            token = getattr(settings, 'APIFY_API_TOKEN', '')
            if not token:
                results['apify'] = {
                    'provider': 'APIFY',
                    'status': 'NOT_CONFIGURED',
                    'badge': 'Not Configured',
                    'severity': 'warning',
                    'latency_ms': 0,
                    'message': 'APIFY_API_TOKEN is missing from server environment.'
                }
            else:
                t0 = time.time()
                try:
                    resp = requests.get(
                        'https://api.apify.com/v2/users/me',
                        headers={'Authorization': f'Bearer {token}'},
                        timeout=8
                    )
                    latency = int((time.time() - t0) * 1000)
                    if resp.status_code == 200:
                        data = resp.json().get('data', {})
                        plan_info = data.get('plan', {})
                        plan_id = plan_info.get('id') if isinstance(plan_info, dict) else str(plan_info)
                        results['apify'] = {
                            'provider': 'APIFY',
                            'status': 'HEALTHY',
                            'badge': 'Active & Operational',
                            'severity': 'success',
                            'http_code': 200,
                            'latency_ms': latency,
                            'username': data.get('username'),
                            'plan': plan_id or 'Active Plan',
                            'message': f"Key verified successfully. Authenticated as '{data.get('username')}'."
                        }
                    elif resp.status_code in [401, 403]:
                        results['apify'] = {
                            'provider': 'APIFY',
                            'status': 'EXPIRED_OR_INVALID',
                            'badge': 'Auth Expired (401/403)',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': 'Apify rejected the API token.'
                        }
                    else:
                        results['apify'] = {
                            'provider': 'APIFY',
                            'status': 'ERROR',
                            'badge': f'Error {resp.status_code}',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': f'Apify API responded with HTTP {resp.status_code}.'
                        }
                except Exception as exc:
                    results['apify'] = {
                        'provider': 'APIFY',
                        'status': 'UNREACHABLE',
                        'badge': 'Connection Failed',
                        'severity': 'critical',
                        'latency_ms': 0,
                        'message': f'Could not connect to Apify servers: {str(exc)}'
                    }

        # 4. SocialData Probe (Legacy)
        if target_provider in ['ALL', 'SOCIALDATA']:
            sd_key = getattr(settings, 'SOCIALDATA_API_KEY', '')
            if not sd_key:
                results['socialdata'] = {
                    'provider': 'SOCIALDATA',
                    'status': 'NOT_CONFIGURED',
                    'badge': 'Not Configured',
                    'severity': 'warning',
                    'latency_ms': 0,
                    'message': 'SOCIALDATA_API_KEY is missing from server environment.'
                }
            else:
                t0 = time.time()
                try:
                    resp = requests.get(
                        'https://api.socialdata.tools/twitter/user/elonmusk',
                        headers={'Authorization': f'Bearer {sd_key}', 'Accept': 'application/json'},
                        timeout=8
                    )
                    latency = int((time.time() - t0) * 1000)
                    if resp.status_code == 200:
                        results['socialdata'] = {
                            'provider': 'SOCIALDATA',
                            'status': 'HEALTHY',
                            'badge': 'Active & Operational',
                            'severity': 'success',
                            'http_code': 200,
                            'latency_ms': latency,
                            'message': 'SocialData API key is valid.'
                        }
                    elif resp.status_code == 402:
                        results['socialdata'] = {
                            'provider': 'SOCIALDATA',
                            'status': 'PAYMENT_REQUIRED',
                            'badge': 'Credits Depleted (402)',
                            'severity': 'critical',
                            'http_code': 402,
                            'latency_ms': latency,
                            'message': 'SocialData balance exhausted.',
                            'billing_url': 'https://socialdata.tools/billing'
                        }
                    elif resp.status_code in [401, 403]:
                        results['socialdata'] = {
                            'provider': 'SOCIALDATA',
                            'status': 'EXPIRED_OR_INVALID',
                            'badge': 'Auth Expired (401/403)',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': 'SocialData rejected the API token.'
                        }
                    else:
                        results['socialdata'] = {
                            'provider': 'SOCIALDATA',
                            'status': 'ERROR',
                            'badge': f'Error {resp.status_code}',
                            'severity': 'critical',
                            'http_code': resp.status_code,
                            'latency_ms': latency,
                            'message': f'SocialData API responded with HTTP {resp.status_code}.'
                        }
                except Exception as exc:
                    results['socialdata'] = {
                        'provider': 'SOCIALDATA',
                        'status': 'UNREACHABLE',
                        'badge': 'Connection Failed',
                        'severity': 'critical',
                        'latency_ms': 0,
                        'message': f'Could not connect to SocialData servers: {str(exc)}'
                    }

        return Response({
            'tested_at': timezone.now().isoformat(),
            'results': results
        })


# ---------------------------------------------------------------------------
# CAMPAIGN PIPELINE COST TRACKING & ACCOUNTING
# ---------------------------------------------------------------------------

class CampaignPipelineCostsOverviewView(APIView):
    """
    Overview of all campaigns with their total pipeline costs from proposal to final executive report.
    Allows platform administrators to audit spend across lifecycle stages.
    """
    permission_classes = (RequireSupportOrAbove,)

    def get(self, request):
        from apps.influencers.models import ApiCostLog
        from apps.campaigns.models import Campaign

        campaigns = Campaign.objects.select_related('workspace').all().order_by('-created_at')

        # Aggregate costs by campaign and stage
        cost_aggregates = ApiCostLog.objects.filter(campaign__isnull=False).values(
            'campaign_id', 'pipeline_stage'
        ).annotate(
            total_usd=Sum('cost_usd'),
            total_credits=Sum('credits_used')
        )

        cost_map = {}
        for row in cost_aggregates:
            cid = row['campaign_id']
            stage = row['pipeline_stage']
            if cid not in cost_map:
                cost_map[cid] = {
                    'total_usd': 0.0,
                    'total_credits': 0.0,
                    'stages': {
                        'PROPOSAL': 0.0,
                        'MONITORING': 0.0,
                        'EXECUTIVE_REPORT': 0.0,
                        'STANDALONE': 0.0,
                    }
                }
            usd = float(row['total_usd'] or 0.0)
            credits = float(row['total_credits'] or 0.0)
            cost_map[cid]['total_usd'] += usd
            cost_map[cid]['total_credits'] += credits
            cost_map[cid]['stages'][stage] = cost_map[cid]['stages'].get(stage, 0.0) + usd

        data = []
        for c in campaigns:
            c_cost = cost_map.get(c.id, {
                'total_usd': 0.0,
                'total_credits': 0.0,
                'stages': {'PROPOSAL': 0.0, 'MONITORING': 0.0, 'EXECUTIVE_REPORT': 0.0}
            })
            creators_count = c.campaign_influencers.count() if hasattr(c, 'campaign_influencers') else 0
            data.append({
                'id': c.id,
                'name': c.name,
                'status': c.status,
                'workspace_name': c.workspace.name if c.workspace else 'None',
                'workspace_id': c.workspace_id,
                'creators_count': creators_count,
                'created_at': c.created_at,
                'total_cost_usd': round(c_cost['total_usd'], 4),
                'total_credits_used': round(c_cost['total_credits'], 2),
                'stage_breakdown': {
                    'proposal_usd': round(c_cost['stages'].get('PROPOSAL', 0.0), 4),
                    'monitoring_usd': round(c_cost['stages'].get('MONITORING', 0.0), 4),
                    'executive_report_usd': round(c_cost['stages'].get('EXECUTIVE_REPORT', 0.0), 4),
                }
            })

        return Response({
            'campaigns': data,
            'summary': {
                'total_campaigns': len(data),
                'total_pipeline_spend_usd': round(sum(d['total_cost_usd'] for d in data), 4),
            }
        })


class CampaignPipelineCostDetailView(APIView):
    """
    Detailed lifecycle financial audit for a specific campaign:
    Breaks down spend by:
      1. Lifecycle Stage (Proposal Creation, Active Monitoring, Executive Report)
      2. Functional Category (SociaVault Profiles/Posts/Comments, DeepSeek NLP/Insights, PDF Rendering)
      3. Service Provider (SociaVault vs DeepSeek vs Worker)
    """
    permission_classes = (RequireSupportOrAbove,)

    def get(self, request, pk=None):
        from apps.influencers.models import ApiCostLog
        from apps.campaigns.models import Campaign

        try:
            campaign = Campaign.objects.select_related('workspace').get(pk=pk)
        except Campaign.DoesNotExist:
            return Response({"error": "Campaign not found."}, status=status.HTTP_404_NOT_FOUND)

        logs = ApiCostLog.objects.filter(campaign=campaign).order_by('-created_at')

        # Totals
        totals = logs.aggregate(
            total_usd=Sum('cost_usd'),
            total_credits=Sum('credits_used')
        )
        total_usd = float(totals['total_usd'] or 0.0)
        total_credits = float(totals['total_credits'] or 0.0)

        # Stage & category breakdown
        stage_data = {
            'PROPOSAL': {'total_usd': 0.0, 'categories': {}},
            'MONITORING': {'total_usd': 0.0, 'categories': {}},
            'EXECUTIVE_REPORT': {'total_usd': 0.0, 'categories': {}},
            'STANDALONE': {'total_usd': 0.0, 'categories': {}},
        }
        provider_data = {}

        for log in logs:
            stg = log.pipeline_stage or 'STANDALONE'
            cat = log.cost_category or 'OTHER'
            prov = log.provider
            usd = float(log.cost_usd or 0.0)

            if stg not in stage_data:
                stage_data[stg] = {'total_usd': 0.0, 'categories': {}}
            stage_data[stg]['total_usd'] += usd
            stage_data[stg]['categories'][cat] = round(stage_data[stg]['categories'].get(cat, 0.0) + usd, 4)

            if prov not in provider_data:
                provider_data[prov] = {'total_usd': 0.0, 'call_count': 0}
            provider_data[prov]['total_usd'] += usd
            provider_data[prov]['call_count'] += 1

        for stg in stage_data:
            stage_data[stg]['total_usd'] = round(stage_data[stg]['total_usd'], 4)
        for prov in provider_data:
            provider_data[prov]['total_usd'] = round(provider_data[prov]['total_usd'], 4)

        # Paginated recent ledger
        recent_logs = []
        for log in logs[:50]:
            recent_logs.append({
                'id': log.id,
                'provider': log.provider,
                'endpoint': log.endpoint,
                'pipeline_stage': log.pipeline_stage,
                'cost_category': log.cost_category,
                'cost_usd': round(float(log.cost_usd), 4),
                'credits_used': round(float(log.credits_used), 2),
                'response_time_ms': log.response_time_ms,
                'success': log.success,
                'created_at': log.created_at,
            })

        return Response({
            'campaign_id': campaign.id,
            'campaign_name': campaign.name,
            'workspace_name': campaign.workspace.name if campaign.workspace else '',
            'workspace_id': campaign.workspace_id,
            'created_at': campaign.created_at,
            'total_cost_usd': round(total_usd, 4),
            'total_credits_used': round(total_credits, 2),
            'stage_breakdown': {
                'proposal': stage_data.get('PROPOSAL', {}),
                'monitoring': stage_data.get('MONITORING', {}),
                'executive_report': stage_data.get('EXECUTIVE_REPORT', {}),
            },
            'provider_breakdown': provider_data,
            'recent_logs': recent_logs,
        })
