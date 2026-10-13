import math
from datetime import timedelta
from django.utils import timezone


DEFAULT_STALENESS_HOURS = 24


def get_influencer_staleness_hours() -> int:
    """
    Fetches the configured influencer staleness threshold from SystemConfig.
    Falls back to DEFAULT_STALENESS_HOURS (24) if not defined or invalid.
    """
    try:
        from apps.admin_panel.models import SystemConfig
        config = SystemConfig.objects.filter(key='INFLUENCER_STALENESS_HOURS').first()
        if config and config.value:
            val = int(config.value)
            if val > 0:
                return val
    except Exception:
        pass
    return DEFAULT_STALENESS_HOURS


def set_influencer_staleness_hours(hours: int, user=None) -> int:
    """
    Updates or creates the INFLUENCER_STALENESS_HOURS in SystemConfig.
    """
    from apps.admin_panel.models import SystemConfig, AdminAuditLog
    hours = max(1, int(hours))
    config, created = SystemConfig.objects.update_or_create(
        key='INFLUENCER_STALENESS_HOURS',
        defaults={
            'value': str(hours),
            'value_type': 'int',
            'description': 'Hours before an influencer profile is considered stale and automatically refreshed in background on access.',
            'updated_by': user if user and getattr(user, 'is_authenticated', False) else None,
        }
    )
    if user and getattr(user, 'is_authenticated', False):
        AdminAuditLog.log_action(
            admin_user=user,
            action=AdminAuditLog.Actions.CONFIG_CHANGE,
            entity_type='SystemConfig',
            entity_id=config.id,
            description=f"Set influencer staleness threshold to {hours} hours",
        )
    return hours


def format_age_display(dt) -> str:
    """
    Returns a human-readable age string for a timestamp, e.g.
    'Just now', '45m ago' / '45 minutes old', '3h ago' / '3 hours old', '2 days old', '3 weeks old'.
    """
    if not dt:
        return "Never scraped"
    
    now = timezone.now()
    diff = now - dt
    total_seconds = max(0, diff.total_seconds())

    if total_seconds < 60:
        return "Just now"
    minutes = int(total_seconds // 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} old"
    hours = int(total_seconds // 3600)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} old"
    days = int(total_seconds // 86400)
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''} old"
    weeks = int(days // 7)
    if weeks < 4:
        return f"{weeks} week{'s' if weeks != 1 else ''} old"
    months = int(days // 30)
    return f"{months} month{'s' if months != 1 else ''} old"


def sanitize_social_handle(raw_handle: str) -> str:
    """
    Cleans a social media handle or URL string into a pure username.
    Handles:
      - Full URLs: 'https://instagram.com/cecewinans?utm_source=chatgpt.com' -> 'cecewinans'
      - Query params: 'cecewinans?utm_source=chatgpt.com' -> 'cecewinans'
      - Fragments: 'cecewinans#profile' -> 'cecewinans'
      - Prefixes: '@cecewinans' -> 'cecewinans'
      - Slashes & whitespace
    """
    if not raw_handle:
        return ""

    val = str(raw_handle).strip()

    # Strip query parameters (?...) and hash fragments (#...)
    if '?' in val:
        val = val.split('?', 1)[0]
    if '#' in val:
        val = val.split('#', 1)[0]

    val = val.strip().rstrip('/')

    # If it's a full URL or contains a domain
    if '/' in val:
        parts = [p.strip() for p in val.split('/') if p.strip()]
        if parts:
            # The last non-empty segment is typically the username
            last = parts[-1]
            if last in ('instagram.com', 'tiktok.com', 'x.com', 'twitter.com'):
                val = ""
            else:
                val = last

    # Remove leading @ symbols
    val = val.lstrip('@').strip()

    # Retain only valid characters for handles (letters, digits, underscores, periods)
    import re
    # Remove any characters not allowed in usernames
    val = re.sub(r'[^a-zA-Z0-9_.]', '', val)

    return val.strip()
