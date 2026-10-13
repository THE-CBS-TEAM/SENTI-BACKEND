from django.contrib import admin
from apps.reports.models import GeneratedReport


@admin.register(GeneratedReport)
class GeneratedReportAdmin(admin.ModelAdmin):
    list_display = ('report_type', 'campaign', 'file_path', 'generated_at', 'generated_by')
    list_filter = ('report_type', 'generated_at')
    search_fields = ('file_path', 'campaign__name')
