import logging
import requests
import time
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sociavault.com/v1/scrape"


class SociaVaultClient:
    """
    Unified client for the SociaVault API.
    Replaces the Apify client (Instagram, TikTok) and SocialData client (X/Twitter).

    Authentication: X-API-Key header.
    All methods raise on unexpected API errors so callers can decide
    whether to surface the error or fall back gracefully.

    Every call logs an ApiCostLog entry (via _log_cost) for full admin visibility.
    """

    # ---------- SociaVault per-call credit costs (approximate) ----------
    # These match SociaVault's credit table. Update when pricing changes.
    COSTS = {
        "instagram_profile": 1,
        "instagram_posts": 1,
        "instagram_post_info": 1,
        "instagram_comments": 1,
        "tiktok_profile": 1,
        "tiktok_videos": 1,
        "tiktok_video_info": 1,
        "tiktok_comments": 1,
        "twitter_profile": 1,
        "twitter_user_tweets": 1,
        "twitter_tweet": 1,
        "twitter_comments": 1,
    }

    # Approximate USD cost per credit (update when plan changes)
    USD_PER_CREDIT = 0.001

    def __init__(self):
        self.api_key = getattr(settings, "SOCIAL_VAULT_API_KEY", "")
        self.base_url = BASE_URL

    def is_configured(self):
        return bool(self.api_key and not self.api_key.startswith("your_"))

    def _headers(self):
        return {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    def _get(self, path, params=None):
        """
        Internal GET helper. Returns parsed JSON dict.
        Records response time for cost log.
        Raises requests.HTTPError on non-2xx responses.
        """
        if not self.is_configured():
            raise ValueError(
                "SOCIAL_VAULT_API_KEY is not configured. "
                "Add it to your .env file."
            )
        url = f"{self.base_url}{path}"
        start = time.monotonic()
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            resp.raise_for_status()
            return resp.json(), elapsed_ms
        except requests.HTTPError as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.error("SociaVault %s error %s: %s", path, e.response.status_code, e.response.text)
            raise

    def _log_cost(
        self,
        endpoint_key,
        elapsed_ms,
        success,
        error_message=None,
        workspace=None,
        global_influencer=None,
        campaign=None,
        pipeline_stage="STANDALONE",
        cost_category=None,
        **extra,
    ):
        """
        Write an ApiCostLog row after every SociaVault call.
        Silently swallows errors so a logging failure never breaks the main flow.
        """
        try:
            from apps.influencers.models import ApiCostLog

            credits = self.COSTS.get(endpoint_key, 1)
            cost_usd = credits * self.USD_PER_CREDIT

            ApiCostLog.objects.create(
                provider=ApiCostLog.Providers.SOCIAVAULT,
                endpoint=endpoint_key,
                credits_used=credits,
                cost_usd=cost_usd,
                workspace=workspace,
                global_influencer=global_influencer,
                campaign=campaign,
                pipeline_stage=pipeline_stage,
                cost_category=cost_category or ApiCostLog.CostCategories.SOCIAVAULT_PROFILE,
                response_time_ms=elapsed_ms,
                success=success,
                error_message=error_message or "",
            )
        except Exception as exc:
            logger.warning("Failed to write ApiCostLog for %s: %s", endpoint_key, exc)

    # ─────────────────────────────────────────────
    # INSTAGRAM
    # ─────────────────────────────────────────────

    def get_instagram_profile(self, username, **cost_kwargs):
        """
        GET /instagram/profile
        Returns public Instagram profile data including recent posts and bio.
        """
        handle = username.lstrip("@").strip()
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_PROFILE")
        try:
            data, elapsed = self._get("/instagram/profile", params={"handle": handle})
            self._log_cost(
                "instagram_profile", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "instagram_profile", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_instagram_posts(self, username, cursor=None, **cost_kwargs):
        """
        GET /instagram/posts
        Returns recent posts from a public Instagram profile.
        Pass cursor from previous response to paginate.
        """
        handle = username.lstrip("@").strip()
        params = {"handle": handle}
        if cursor:
            params["cursor"] = cursor
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_POSTS")
        try:
            data, elapsed = self._get("/instagram/posts", params=params)
            self._log_cost(
                "instagram_posts", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "instagram_posts", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_instagram_post_info(self, url, **cost_kwargs):
        """
        GET /instagram/post-info
        Detailed data for a specific IG post/reel — likes, comments count, views, caption.
        """
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_POSTS")
        try:
            data, elapsed = self._get("/instagram/post-info", params={"url": url})
            self._log_cost(
                "instagram_post_info", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "instagram_post_info", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_instagram_comments(self, url, cursor=None, **cost_kwargs):
        """
        GET /instagram/comments
        Returns comments from an Instagram post or reel (~15 per page).
        Use cursor to paginate.
        """
        params = {"url": url}
        if cursor:
            params["cursor"] = cursor
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_COMMENTS")
        try:
            data, elapsed = self._get("/instagram/comments", params=params)
            self._log_cost(
                "instagram_comments", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "instagram_comments", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    # ─────────────────────────────────────────────
    # TIKTOK
    # ─────────────────────────────────────────────

    def get_tiktok_profile(self, username, **cost_kwargs):
        """
        GET /tiktok/profile
        Scrapes a public TikTok profile — followers, bio, video count, etc.
        """
        handle = username.lstrip("@").strip()
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_PROFILE")
        try:
            data, elapsed = self._get("/tiktok/profile", params={"handle": handle})
            self._log_cost(
                "tiktok_profile", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "tiktok_profile", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_tiktok_videos(self, username, cursor=None, **cost_kwargs):
        """
        GET /tiktok/videos
        Returns videos from a TikTok profile with engagement metrics.
        Pass cursor to paginate.
        """
        handle = username.lstrip("@").strip()
        params = {"handle": handle}
        if cursor:
            params["cursor"] = cursor
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_POSTS")
        try:
            data, elapsed = self._get("/tiktok/videos", params=params)
            self._log_cost(
                "tiktok_videos", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "tiktok_videos", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_tiktok_video_info(self, url, **cost_kwargs):
        """
        GET /tiktok/video-info
        Detailed data for a specific TikTok video — plays, likes, comments, shares.
        """
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_POSTS")
        try:
            data, elapsed = self._get("/tiktok/video-info", params={"url": url})
            self._log_cost(
                "tiktok_video_info", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "tiktok_video_info", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_tiktok_comments(self, url, cursor=None, **cost_kwargs):
        """
        GET /tiktok/comments
        Returns comments from a TikTok video. Use cursor to paginate.
        """
        params = {"url": url}
        if cursor:
            params["cursor"] = cursor
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_COMMENTS")
        try:
            data, elapsed = self._get("/tiktok/comments", params=params)
            self._log_cost(
                "tiktok_comments", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "tiktok_comments", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    # ─────────────────────────────────────────────
    # TWITTER / X
    # ─────────────────────────────────────────────

    def get_twitter_profile(self, username, **cost_kwargs):
        """
        GET /twitter/profile
        Returns Twitter/X profile info — followers, description, verified, etc.
        """
        handle = username.lstrip("@").strip()
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_PROFILE")
        try:
            data, elapsed = self._get("/twitter/profile", params={"handle": handle})
            self._log_cost(
                "twitter_profile", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "twitter_profile", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_twitter_user_tweets(self, username, **cost_kwargs):
        """
        GET /twitter/user-tweets
        Returns the user's ~100 most popular public tweets with engagement metrics.
        Note: SociaVault surfaces popular tweets, not necessarily most recent.
        """
        handle = username.lstrip("@").strip()
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_POSTS")
        try:
            data, elapsed = self._get("/twitter/user-tweets", params={"handle": handle})
            self._log_cost(
                "twitter_user_tweets", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "twitter_user_tweets", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_twitter_tweet(self, tweet_url, **cost_kwargs):
        """
        GET /twitter/tweet
        Detailed info about a specific tweet — likes, replies, retweets, views.
        Accepts full tweet URL or numeric tweet ID.
        """
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_POSTS")
        try:
            data, elapsed = self._get("/twitter/tweet", params={"url": tweet_url})
            self._log_cost(
                "twitter_tweet", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "twitter_tweet", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise

    def get_twitter_comments(self, tweet_url, cursor=None, **cost_kwargs):
        """
        GET /twitter/comments
        Returns replies on a specific tweet. Use cursor to paginate.
        """
        tweet_id = tweet_url.split('/status/')[-1].split('?')[0].strip('/') if '/status/' in str(tweet_url) else str(tweet_url)
        params = {"pid": tweet_id, "url": tweet_url}
        if cursor:
            params["cursor"] = cursor
        cat = cost_kwargs.pop("cost_category", "SOCIAVAULT_COMMENTS")
        try:
            data, elapsed = self._get("/twitter/comments", params=params)
            self._log_cost(
                "twitter_comments", elapsed, True,
                cost_category=cat, **cost_kwargs
            )
            return data
        except Exception as exc:
            self._log_cost(
                "twitter_comments", 0, False, error_message=str(exc),
                cost_category=cat, **cost_kwargs
            )
            raise


# Module-level singleton — import this instead of instantiating manually
sociavault_client = SociaVaultClient()
