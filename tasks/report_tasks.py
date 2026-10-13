import logging
from celery import shared_task
from django.contrib.auth import get_user_model
from apps.reports.services.pdf_generator import PDFReportGenerator

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(queue='reports', soft_time_limit=120, time_limit=180)
def generate_pdf_report_task(report_id):
    """Asynchronously generates comprehensive WeasyPrint PDF reports and updates status."""
    from apps.reports.models import GeneratedReport
    from apps.reports.services.pdf_generator import PDFReportGenerator
    
    logger.info(f"Triggered PDF report generation task for report {report_id}")
    try:
        report = GeneratedReport.objects.get(pk=report_id)
        report.status = GeneratedReport.ReportStatus.PROCESSING
        report.save()
        
        logger.info(f"Report {report_id}: Status set to PROCESSING. Beginning data aggregation and chart generation...")
        
        if report.report_type == GeneratedReport.ReportTypes.CAMPAIGN_PROPOSAL:
            success = PDFReportGenerator.generate_proposal_pdf_report(report)
        else:
            success = PDFReportGenerator.generate_campaign_pdf_report(report)
        if success:
            report.status = GeneratedReport.ReportStatus.COMPLETED
            logger.info(f"Report {report_id}: Successfully generated. File: {report.file_path}")
        else:
            report.status = GeneratedReport.ReportStatus.FAILED
            logger.error(f"Report {report_id}: PDFReportGenerator returned False.")
        report.save()
        return success
    except Exception as e:
        logger.error(f"Report {report_id}: Generation failed with exception: {str(e)}", exc_info=True)
        GeneratedReport.objects.filter(pk=report_id).update(status=GeneratedReport.ReportStatus.FAILED)
        return False
