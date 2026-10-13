import os
import django

db_url = os.environ.get('DATABASE_URL', '')
if '@db:' in db_url:
    os.environ['DATABASE_URL'] = db_url.replace('@db:', '@172.18.0.2:')
elif not db_url:
    os.environ['DATABASE_URL'] = 'postgres://sentimentri:sentimentri_pass@172.18.0.2:5432/sentimentri_db'

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sentimentri.settings')
django.setup()

from apps.campaigns.models import Campaign
from apps.reports.models import GeneratedReport
from apps.reports.services.pdf_generator import PDFReportGenerator

campaign = Campaign.objects.get(id=5)
report, created = GeneratedReport.objects.get_or_create(
    campaign=campaign,
    report_type=GeneratedReport.ReportTypes.CAMPAIGN_PROPOSAL,
    defaults={
        'status': GeneratedReport.ReportStatus.PENDING
    }
)

print(f"Compiling Proposal PDF for Campaign {campaign.id} (Report ID: {report.id})...", flush=True)
success = PDFReportGenerator.generate_proposal_pdf_report(report)
report.refresh_from_db()

print(f"Compilation success: {success}", flush=True)
print(f"Report file_path: {report.file_path}", flush=True)
print(f"Report status: {report.status}", flush=True)
