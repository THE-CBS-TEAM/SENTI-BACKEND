import hmac
import hashlib
import json
import logging
import httpx
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)

def generate_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

def dispatch_webhook(callback_url: str, job_id: str, status: str, result: Dict[str, Any], error: Optional[str] = None):
    if not callback_url:
        return
    
    payload = {
        "job_id": job_id,
        "status": status,
        "result": result,
        "error": error
    }
    
    payload_str = json.dumps(payload, default=str)
    signature = generate_signature(payload_str.encode("utf-8"), settings.WEBHOOK_SECRET)
    
    headers = {
        "Content-Type": "application/json",
        "X-Worker-Signature": f"sha256={signature}"
    }
    
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(callback_url, data=payload_str, headers=headers)
            logger.info(f"Webhook dispatched to {callback_url} for job {job_id}. Status: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to dispatch webhook to {callback_url} for job {job_id}: {str(e)}")
