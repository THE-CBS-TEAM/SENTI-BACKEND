from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.admin_panel.views import (
    AdminRegisterView,
    AdminAcceptInviteView,
    AdminLoginView,
    AdminMeView,
    AdminDashboardOverviewView,
    AdminNotificationView,
    AdminUserViewSet,
    AdminInvitationViewSet,
    AdminWorkspaceViewSet,
    AdminCampaignViewSet,
    AdminInfluencerViewSet,
    AdminReportViewSet,
    SystemHealthView,
    ScraperJobsView,
    RetryJobView,
    ErrorPostsView,
    RetryPostView,
    PollingQueueView,
    DatabaseStatsView,
    SystemConfigViewSet,
    EnvironmentConfigView,
    AuditLogsView,
    ApiSpendView,
    TestApiKeysView,
    CampaignPipelineCostsOverviewView,
    CampaignPipelineCostDetailView,
)

router = DefaultRouter()
router.register('users', AdminUserViewSet, basename='admin-users')
router.register('invitations', AdminInvitationViewSet, basename='admin-invitations')
router.register('workspaces', AdminWorkspaceViewSet, basename='admin-workspaces')
router.register('campaigns', AdminCampaignViewSet, basename='admin-campaigns')
router.register('influencers', AdminInfluencerViewSet, basename='admin-influencers')
router.register('reports', AdminReportViewSet, basename='admin-reports')
router.register('configs', SystemConfigViewSet, basename='admin-configs')

urlpatterns = [
    # Auth & Invitations
    path('auth/register/', AdminRegisterView.as_view(), name='admin-register'),
    path('auth/accept-invite/', AdminAcceptInviteView.as_view(), name='admin-accept-invite'),
    path('auth/login/', AdminLoginView.as_view(), name='admin-login'),
    path('auth/me/', AdminMeView.as_view(), name='admin-me'),

    # Overview & Notifications
    path('dashboard/overview/', AdminDashboardOverviewView.as_view(), name='admin-dashboard-overview'),
    path('notifications/', AdminNotificationView.as_view(), name='admin-notifications'),

    # Developer Tools & Monitoring
    path('system/health/', SystemHealthView.as_view(), name='admin-system-health'),
    path('system/scraper-jobs/', ScraperJobsView.as_view(), name='admin-scraper-jobs'),
    path('system/retry-job/<int:pk>/', RetryJobView.as_view(), name='admin-retry-job'),
    path('system/error-posts/', ErrorPostsView.as_view(), name='admin-error-posts'),
    path('system/retry-post/<int:pk>/', RetryPostView.as_view(), name='admin-retry-post'),
    path('system/polling-queue/', PollingQueueView.as_view(), name='admin-polling-queue'),
    path('system/db-stats/', DatabaseStatsView.as_view(), name='admin-db-stats'),
    path('system/api-spend/', ApiSpendView.as_view(), name='admin-api-spend'),
    path('system/test-keys/', TestApiKeysView.as_view(), name='admin-test-keys'),

    # Campaign Pipeline Lifecycle Accounting
    path('campaigns/pipeline-costs/', CampaignPipelineCostsOverviewView.as_view(), name='admin-campaigns-pipeline-costs'),
    path('campaigns/<int:pk>/pipeline-costs/', CampaignPipelineCostDetailView.as_view(), name='admin-campaign-pipeline-cost-detail'),

    # Configurations & Audit
    path('system/environment/', EnvironmentConfigView.as_view(), name='admin-environment'),
    path('audit-logs/', AuditLogsView.as_view(), name='admin-audit-logs'),

    # Router CRUD endpoints
    path('', include(router.urls)),
]
