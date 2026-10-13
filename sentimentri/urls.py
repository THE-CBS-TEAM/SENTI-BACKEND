from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from apps.integrations import webhooks

api_patterns = [
    # Auth
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/', include('apps.accounts.urls')),
    # Apps
    path('influencers/', include('apps.influencers.urls')),
    path('campaigns/', include('apps.campaigns.urls')),
    path('sentiment/', include('apps.sentiment.urls')),
    path('scoring/', include('apps.scoring.urls')),
    path('reports/', include('apps.reports.urls')),
    path('admin/', include('apps.admin_panel.urls')),
    # Autonomous Worker Microservice Webhook
    path('webhooks/worker-callback/', webhooks.worker_callback_view, name='worker_callback'),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include(api_patterns)),
]
