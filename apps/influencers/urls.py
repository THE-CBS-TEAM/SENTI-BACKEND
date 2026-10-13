from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.influencers.views import InfluencerViewSet, SystemAnalyticsViewSet

router = DefaultRouter()
router.register('system/analytics', SystemAnalyticsViewSet, basename='systemanalytics')
router.register('', InfluencerViewSet, basename='influencer')

urlpatterns = [
    path('', include(router.urls)),
]
