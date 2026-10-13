import logging
import requests
import time
from django.conf import settings

logger = logging.getLogger(__name__)


class ApifyClient:
    def __init__(self, token=None):
        self.token = token or getattr(settings, 'APIFY_API_TOKEN', '')
        self.base_url = 'https://api.apify.com/v2'

    def is_configured(self):
        return bool(self.token and not self.token.startswith('your_'))

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

    def run_actor_and_get_dataset(self, actor_id, input_data, timeout_secs=180):
        """
        Triggers an actor run, polls until it's finished, and returns the dataset results.
        Enforces real API execution and raises exceptions on failure.
        """
        if not self.is_configured():
            raise ValueError("Apify API token is not configured or invalid.")

        # URL-encode / sanitize actor ID (Apify expects username~actor-name for standard actors)
        actor_id_clean = actor_id.replace('/', '~')

        try:
            # Trigger run
            url = f"{self.base_url}/acts/{actor_id_clean}/runs"
            response = requests.post(url, json=input_data, headers=self._headers(), timeout=30)
            response.raise_for_status()
            run_data = response.json().get('data', {})
            run_id = run_data.get('id')
            dataset_id = run_data.get('defaultDatasetId')

            # Poll run status
            start_time = time.time()
            while time.time() - start_time < timeout_secs:
                status_url = f"{self.base_url}/acts/{actor_id_clean}/runs/{run_id}"
                status_resp = requests.get(status_url, headers=self._headers(), timeout=30)
                status_resp.raise_for_status()
                status = status_resp.json().get('data', {}).get('status')
                
                if status == 'SUCCEEDED':
                    break
                elif status in ['FAILED', 'ABORTED', 'TIMED-OUT']:
                    raise Exception(f"Apify actor run {run_id} failed with status: {status}")
                
                time.sleep(5)
            else:
                raise Exception(f"Apify actor run timed out after {timeout_secs} seconds")

            # Get dataset items
            dataset_url = f"{self.base_url}/datasets/{dataset_id}/items"
            items_resp = requests.get(dataset_url, headers=self._headers(), timeout=30)
            items_resp.raise_for_status()

            return items_resp.json()

        except Exception as e:
            logger.error(f"Apify API error: {str(e)}")
            raise e

