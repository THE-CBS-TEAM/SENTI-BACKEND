from django.contrib import admin
from apps.scoring.models import CentiScoreHistory


@admin.register(CentiScoreHistory)
class CentiScoreHistoryAdmin(admin.ModelAdmin):
    list_display = ('influencer', 'score', 'calculated_at')
    list_filter = ('influencer__workspace',)
    search_fields = ('influencer__display_name',)
