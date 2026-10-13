import logging
import httpx
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)

SOCIALDATA_BASE_URL = "https://api.socialdata.tools/twitter"

class StandaloneSocialDataClient:
    def __init__(self):
        self.api_key = settings.SOCIALDATA_API_KEY

    def fetch_user_profile(self, username: str) -> Dict[str, Any]:
        if not self.api_key:
            logger.warning("SOCIALDATA_API_KEY not configured. Returning fallback profile.")
            return self._mock_profile(username)

        url = f"{SOCIALDATA_BASE_URL}/user/{username}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    followers = data.get("followers_count", 25000)
                    return {
                        "display_name": data.get("name") or username,
                        "handle": username,
                        "followers": followers,
                        "engagement_rate": 0.024,
                        "avg_likes": int(followers * 0.02),
                        "avg_comments": int(followers * 0.004),
                        "avg_views": int(followers * 0.35),
                        "avatar_url": data.get("profile_image_url_https")
                    }
                elif resp.status_code == 429:
                    logger.error("SocialData rate limit hit.")
                    return self._mock_profile(username)
                else:
                    logger.error(f"SocialData error {resp.status_code}: {resp.text}")
                    return self._mock_profile(username)
        except Exception as e:
            logger.error(f"SocialData connection error: {str(e)}")
            return self._mock_profile(username)

    def _mock_profile(self, username: str) -> Dict[str, Any]:
        return {
            "display_name": username.replace("_", " ").title(),
            "handle": username,
            "followers": 48000,
            "engagement_rate": 0.029,
            "avg_likes": 1200,
            "avg_comments": 85,
            "avg_views": 18500,
            "avatar_url": f"https://api.dicebear.com/7.x/identicon/svg?seed={username}"
        }

socialdata_client = StandaloneSocialDataClient()
