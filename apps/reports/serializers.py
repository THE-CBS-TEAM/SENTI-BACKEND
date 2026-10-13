from rest_framework import serializers
from apps.reports.models import GeneratedReport


class GeneratedReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedReport
        fields = ('id', 'campaign', 'report_type', 'status', 'file_path', 'generated_at', 'generated_by')
        read_only_fields = ('status', 'file_path', 'generated_by')


from apps.reports.models import ReportDraft

class ReportDraftSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportDraft
        fields = (
            'id', 'campaign',
            'executive_summary_insight',
            'platform_performance_insight',
            'sentiment_analysis_insight',
            'positive_comments_summary',
            'negative_comments_summary',
            'brand_mentions_insight',
            'brand_positive_qualitative',
            'brand_negative_qualitative',
            'creator_performance_insight',
            'creator_native_vs_campaign_insight',
            'campaign_intelligence_insight',
            'campaign_intelligence_answers',
            'recommendations',
            'updated_at', 'created_at'
        )
        read_only_fields = ('id', 'campaign', 'updated_at', 'created_at')

