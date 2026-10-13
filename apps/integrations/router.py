import re

class IntegrationRouter:
    # URL patterns
    INSTAGRAM_POST_REGEX = re.compile(
        r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel)/([a-zA-Z0-9_\-]+)'
    )
    INSTAGRAM_PROFILE_REGEX = re.compile(
        r'(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9_\.]+)'
    )
    TIKTOK_POST_REGEX = re.compile(
        r'(?:https?://)?(?:www\.)?tiktok\.com/@([a-zA-Z0-9_\.]+)/video/(\d+)'
    )
    TIKTOK_PROFILE_REGEX = re.compile(
        r'(?:https?://)?(?:www\.)?tiktok\.com/@([a-zA-Z0-9_\.]+)'
    )
    TWITTER_POST_REGEX = re.compile(
        r'(?:https?://)?(?:www\.)?(?:twitter|x)\.com/[a-zA-Z0-9_\.]+/status/(\d+)'
    )
    TWITTER_PROFILE_REGEX = re.compile(
        r'(?:https?://)?(?:www\.)?(?:twitter|x)\.com/([a-zA-Z0-9_\.]+)'
    )

    @classmethod
    def parse_url(cls, url):
        """
        Parses a social media URL and returns platform, type ('post' or 'profile'), and the extracted ID.
        Returns None if no match is found.
        """
        # Clean URL
        url = url.strip().split('?')[0]

        # Instagram Post
        match = cls.INSTAGRAM_POST_REGEX.match(url)
        if match:
            return {
                'platform': 'IG',
                'type': 'post',
                'id': match.group(1),
                'url': url
            }

        # TikTok Post
        match = cls.TIKTOK_POST_REGEX.match(url)
        if match:
            return {
                'platform': 'TT',
                'type': 'post',
                'id': match.group(2),
                'username': match.group(1),
                'url': url
            }

        # Twitter/X Post
        match = cls.TWITTER_POST_REGEX.match(url)
        if match:
            return {
                'platform': 'X',
                'type': 'post',
                'id': match.group(1),
                'url': url
            }

        # Instagram Profile
        match = cls.INSTAGRAM_PROFILE_REGEX.match(url)
        if match:
            # Avoid matching paths like 'developer', 'about', etc.
            username = match.group(1)
            if username not in ['p', 'reel', 'explore', 'developer', 'about']:
                return {
                    'platform': 'IG',
                    'type': 'profile',
                    'id': username,
                    'url': url
                }

        # TikTok Profile
        match = cls.TIKTOK_PROFILE_REGEX.match(url)
        if match:
            return {
                'platform': 'TT',
                'type': 'profile',
                'id': match.group(1),
                'url': url
            }

        # Twitter/X Profile
        match = cls.TWITTER_PROFILE_REGEX.match(url)
        if match:
            return {
                'platform': 'X',
                'type': 'profile',
                'id': match.group(1),
                'url': url
            }

        return None
