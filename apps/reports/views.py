import os
from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse, Http404
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.reports.models import GeneratedReport
from apps.accounts.permissions import IsWorkspaceAdmin
from apps.reports.serializers import GeneratedReportSerializer
from apps.campaigns.models import Campaign
from apps.reports.services.csv_exporter import CSVReportExporter


class GeneratedReportViewSet(viewsets.ModelViewSet):
    serializer_class = GeneratedReportSerializer
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin)

    def get_permissions(self):
        # The preview action does its own Campaign-level access check internally,
        # so we only require IsAuthenticated (not IsWorkspaceAdmin) for it.
        if self.action == 'preview':
            return [permissions.IsAuthenticated()]

        # Allow token query parameter authentication for download and export_csv actions
        if self.action in ['download', 'export_csv']:
            token = self.request.query_params.get('token')
            if token:
                from rest_framework_simplejwt.authentication import JWTAuthentication
                try:
                    jwt_auth = JWTAuthentication()
                    validated_token = jwt_auth.get_validated_token(token)
                    user = jwt_auth.get_user(validated_token)
                    if user:
                        self.request.user = user
                except Exception:
                    pass
        return super().get_permissions()



    def get_queryset(self):
        return GeneratedReport.objects.filter(
            Q(campaign__workspace__owner=self.request.user) |
            Q(campaign__workspace__memberships__user=self.request.user)
        ).distinct()

    def create(self, request, *args, **kwargs):
        campaign_id = request.data.get('campaign_id')
        if not campaign_id:
            return Response({'error': 'campaign_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Check campaign exists and is owned or membered by user
        try:
            campaign = Campaign.objects.filter(
                Q(workspace__owner=request.user) | Q(workspace__memberships__user=request.user)
            ).distinct().get(pk=campaign_id)
        except Campaign.DoesNotExist:
            return Response({'error': 'Campaign not found'}, status=status.HTTP_404_NOT_FOUND)

        report_type = request.data.get('report_type', GeneratedReport.ReportTypes.CAMPAIGN_PERFORMANCE)

        # Create a placeholder report record for the frontend to track
        report = GeneratedReport.objects.create(
            campaign=campaign,
            report_type=report_type,
            status=GeneratedReport.ReportStatus.PENDING,
            generated_by=request.user,
        )

        # Dispatch the heavy PDF work to a Celery worker, passing the report ID
        from tasks.report_tasks import generate_pdf_report_task
        generate_pdf_report_task.delay(report.id)

        return Response(GeneratedReportSerializer(report).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        """Return the current generation status of a report (for frontend polling)."""
        report = self.get_object()
        return Response({
            'id': report.id,
            'status': report.status,
            'file_path': report.file_path or None,
        })

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        report = self.get_object()
        
        if not report.file_path or report.status != GeneratedReport.ReportStatus.COMPLETED:
            if report.status == GeneratedReport.ReportStatus.PROCESSING:
                return Response({'error': 'Report generation is still processing'}, status=status.HTTP_202_ACCEPTED)
            elif report.status == GeneratedReport.ReportStatus.FAILED:
                return Response({'error': 'Report generation failed. Please try re-compiling.'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'error': 'Report file not ready or not found'}, status=status.HTTP_404_NOT_FOUND)

        filepath = os.path.join(settings.MEDIA_ROOT, report.file_path)

        if not os.path.exists(filepath) or os.path.isdir(filepath):
            raise Http404("Report file does not exist")

        with open(filepath, 'rb') as f:
            response = HttpResponse(f.read(), content_type='application/pdf')
            # Check if it was HTML fallback
            if filepath.endswith('.html'):
                response['Content-Type'] = 'text/html'
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(filepath)}"'
            return response

    @action(detail=False, methods=['get', 'patch'], url_path='preview/(?P<campaign_id>[^/.]+)')
    def preview(self, request, campaign_id=None):
        try:
            campaign = Campaign.objects.filter(
                Q(workspace__owner=request.user) | Q(workspace__memberships__user=request.user)
            ).distinct().get(pk=campaign_id)
        except Campaign.DoesNotExist:
            return Response({'error': 'Campaign not found'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'GET':
            try:
                from apps.reports.services.pdf_generator import PDFReportGenerator
                context = PDFReportGenerator.generate_campaign_report_context(campaign, include_charts=False)
                
                # Serialize model instances
                context['campaign'] = {
                    'id': campaign.id,
                    'name': campaign.name,
                    'goal': campaign.goal,
                    'budget': float(campaign.budget or 0.0),
                    'currency': campaign.currency,
                    'start_date': campaign.start_date.strftime('%Y-%m-%d') if campaign.start_date else None,
                    'end_date': campaign.end_date.strftime('%Y-%m-%d') if campaign.end_date else None,
                    'brand': {
                        'id': campaign.brand.id if campaign.brand else None,
                        'name': campaign.brand.name if campaign.brand else None
                    }
                }
                
                from apps.reports.models import ReportDraft
                from apps.reports.serializers import ReportDraftSerializer
                draft = ReportDraft.objects.filter(campaign=campaign).first()
                context['draft'] = ReportDraftSerializer(draft).data if draft else None
                
                return Response(context)
            except Exception as e:
                logger.error(f"Error generating campaign report preview: {str(e)}", exc_info=True)
                return Response({'error': f"Failed to generate report preview: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        elif request.method == 'PATCH':
            from apps.reports.models import ReportDraft
            from apps.reports.serializers import ReportDraftSerializer
            
            draft, created = ReportDraft.objects.get_or_create(campaign=campaign)
            serializer = ReportDraftSerializer(draft, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='export-csv/(?P<campaign_id>[^/.]+)')
    def export_csv(self, request, campaign_id=None):
        try:
            campaign = Campaign.objects.filter(
                Q(workspace__owner=request.user) | Q(workspace__memberships__user=request.user)
            ).distinct().get(pk=campaign_id)
        except Campaign.DoesNotExist:
            return Response({'error': 'Campaign not found'}, status=status.HTTP_404_NOT_FOUND)

        csv_data = CSVReportExporter.export_campaign_posts_csv(campaign)
        response = HttpResponse(csv_data, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="campaign_{campaign.id}_raw_metrics.csv"'
        return response

