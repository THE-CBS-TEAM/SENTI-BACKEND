import hmac
import hashlib
import json
import logging
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from apps.influencers.models import Influencer, PlatformMetrics
from apps.campaigns.models import TrackedPost
from apps.reports.models import GeneratedReport

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = getattr(settings, 'WEBHOOK_SECRET', '')

def verify_signature(payload_bytes: bytes, received_signature: str) -> bool:
    if not WEBHOOK_SECRET or not received_signature:
        return False
    # Format: sha256=<hash>
    expected_hash = received_signature.replace('sha256=', '')
    computed_hash = hmac.new(WEBHOOK_SECRET.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hash, computed_hash)

@csrf_exempt
def worker_callback_view(request):
    """
    Webhook endpoint called by the Standalone Worker Microservice upon job completion.
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    signature = request.headers.get('X-Worker-Signature', '')
    if not verify_signature(request.body, signature):
        logger.warning("Worker webhook received with invalid signature.")
        return JsonResponse({"error": "Invalid signature"}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
        job_id = data.get('job_id')
        job_status = data.get('status')
        result = data.get('result', {})

        logger.info(f"Worker callback received for job {job_id} with status {job_status}")

        # Handle report generation callbacks
        if 'report_url' in result:
            report_id = result.get('report_id')
            if report_id:
                GeneratedReport.objects.filter(id=report_id).update(
                    file_path=result['report_url'],
                    status='COMPLETED'
                )

        # Handle post sentiment updates
        if 'positive_count' in result and 'post_id' in result:
            post_id = result['post_id']
            TrackedPost.objects.filter(id=post_id).update(
                sentiment_positive=result.get('positive_count', 0),
                sentiment_neutral=result.get('neutral_count', 0),
                sentiment_negative=result.get('negative_count', 0),
            )

        return JsonResponse({"status": "received", "job_id": job_id})
    except Exception as e:
        logger.error(f"Error processing worker callback: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)
