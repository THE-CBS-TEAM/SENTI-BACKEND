import os
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from django.conf import settings

class StandaloneWorkerClient:
    """
    Client for interacting with the autonomous Sentimentri Worker Microservice.
    Reads WORKER_SERVICE_URL dynamically from settings or environment variables,
    ensuring zero hardcoding for production domains.
    """
    @property
    def base_url(self) -> str:
        url = getattr(settings, 'WORKER_SERVICE_URL', None) or os.getenv("WORKER_SERVICE_URL", "http://worker_api:8001/api/v1")
        return url.rstrip('/')

    @property
    def headers(self) -> Dict[str, str]:
        api_key = getattr(settings, 'WORKER_API_KEY', None) or os.getenv("WORKER_API_KEY", "")
        return {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.post(url, json=payload, headers=self.headers, timeout=10.0)
            if resp.status_code in [200, 201, 202]:
                return {"success": True, "data": resp.json()}
            else:
                logger.error(f"Worker service error {resp.status_code}: {resp.text}")
                return {"success": False, "error": resp.text, "status_code": resp.status_code}
        except Exception as e:
            logger.error(f"Failed to communicate with worker service at {url}: {str(e)}")
            return {"success": False, "error": str(e)}

    def _get(self, endpoint: str) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10.0)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            else:
                return {"success": False, "error": resp.text, "status_code": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def trigger_fetch_creator(self, platform: str, handle: str, callback_url: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "client_id": "sentimentri_core",
            "platform": platform,
            "handle": handle,
            "callback_url": callback_url
        }
        return self._post("/jobs/fetch-creator", payload)

    def trigger_analyze_sentiment(self, comments: list, brand_name: Optional[str] = None, callback_url: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "client_id": "sentimentri_core",
            "comments": comments,
            "brand_name": brand_name,
            "callback_url": callback_url
        }
        return self._post("/jobs/analyze-sentiment", payload)

    def trigger_calculate_score(self, platform_metrics: list, callback_url: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "client_id": "sentimentri_core",
            "platform_metrics": platform_metrics,
            "callback_url": callback_url
        }
        return self._post("/jobs/calculate-score", payload)

    def trigger_generate_report(self, report_type: str, report_data: dict, callback_url: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "client_id": "sentimentri_core",
            "report_type": report_type,
            "report_data": report_data,
            "callback_url": callback_url
        }
        return self._post("/jobs/generate-report", payload)

    def check_job_status(self, job_id: str) -> Dict[str, Any]:
        return self._get(f"/jobs/{job_id}")

worker_client = StandaloneWorkerClient()
