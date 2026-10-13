from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.scoring.views import CentiScoreHistoryViewSet

router = DefaultRouter()
router.register('history', CentiScoreHistoryViewSet, basename='centi-history')

# Empty router urls for placeholder scoring endpoints
urlpatterns = [
    path('', include(router.urls)),
]
