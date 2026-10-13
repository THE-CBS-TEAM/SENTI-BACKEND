import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SocialDataClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'SOCIALDATA_API_KEY', '')
        self.base_url = 'https://api.socialdata.tools/twitter'  # Standard SocialData API base URL

    def is_configured(self):
        return bool(self.api_key and not self.api_key.startswith('your_'))

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

    def get_user_profile(self, username):
        """Fetches profile info for a Twitter user."""
        if not self.is_configured():
            raise ValueError("SocialData API key is not configured or invalid.")

        clean_user = username.lstrip('@').strip()
        try:
            url = f"{self.base_url}/user/{clean_user}"
            response = requests.get(url, headers=self._headers(), timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"SocialData profile fetch failed for {clean_user}: {str(e)}")
            raise e

    def get_user_tweets(self, user_id, limit=10):
        """Fetches recent tweets using user ID timeline endpoint."""
        if not self.is_configured():
            raise ValueError("SocialData API key is not configured or invalid.")

        try:
            url = f"{self.base_url}/user/{user_id}/tweets"
            response = requests.get(url, headers=self._headers(), timeout=15)
            response.raise_for_status()
            return response.json().get('tweets', [])[:limit]
        except Exception as e:
            logger.warning(f"SocialData user timeline fetch failed for user_id {user_id}: {str(e)}")
            return []

    def get_tweets_by_username(self, username, limit=10):
        """Fetches recent tweets for a user to calculate baseline benchmarks."""
        if not self.is_configured():
            raise ValueError("SocialData API key is not configured or invalid.")

        clean_user = username.lstrip('@').strip()
        try:
            url = f"{self.base_url}/search"
            response = requests.get(url, params={'query': f'from:{clean_user}'}, headers=self._headers(), timeout=15)
            response.raise_for_status()
            return response.json().get('tweets', [])[:limit]
        except Exception as e:
            logger.error(f"SocialData tweets fetch failed for {clean_user}: {str(e)}")
            return []

    def get_tweet(self, tweet_id):
        """Fetches details for a specific tweet by its ID."""
        if not self.is_configured():
            raise ValueError("SocialData API key is not configured or invalid.")

        try:
            url = f"{self.base_url}/tweets/{tweet_id}"
            response = requests.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"SocialData tweet fetch failed for {tweet_id}: {str(e)}")
            raise e

    def get_tweet_comments(self, tweet_id):
        """Fetches replies to a specific tweet for sentiment calculations."""
        if not self.is_configured():
            raise ValueError("SocialData API key is not configured or invalid.")

        try:
            url = f"{self.base_url}/tweets/{tweet_id}/comments"
            response = requests.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json().get('tweets', [])
        except Exception as e:
            logger.error(f"SocialData tweet comments fetch failed for {tweet_id}: {str(e)}")
            raise e

