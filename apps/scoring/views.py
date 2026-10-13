from django.db.models import Q
from rest_framework import viewsets, permissions
from apps.scoring.models import CentiScoreHistory
from apps.scoring.serializers import CentiScoreHistorySerializer


class CentiScoreHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CentiScoreHistorySerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return CentiScoreHistory.objects.filter(
            Q(influencer__workspace__owner=self.request.user) | Q(influencer__workspace__memberships__user=self.request.user)
        ).distinct()

