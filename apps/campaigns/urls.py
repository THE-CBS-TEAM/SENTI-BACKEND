from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.campaigns.views import CampaignViewSet

router = DefaultRouter()
router.register('', CampaignViewSet, basename='campaign')

urlpatterns = [
    path('', include(router.urls)),
]
