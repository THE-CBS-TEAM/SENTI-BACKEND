from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.reports.views import GeneratedReportViewSet

router = DefaultRouter()
router.register('', GeneratedReportViewSet, basename='report')

urlpatterns = [
    path('', include(router.urls)),
]
