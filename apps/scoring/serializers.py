from rest_framework import serializers
from apps.scoring.models import CentiScoreHistory


class CentiScoreHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CentiScoreHistory
        fields = ('id', 'influencer', 'score', 'components', 'calculated_at')
