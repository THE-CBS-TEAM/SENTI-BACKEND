from datetime import datetime, timedelta
from django.utils import timezone


def get_workspace_polling_tiers(workspace):
    t1_max = getattr(workspace, 't1_max_age_hours', 24)
    t1_int = getattr(workspace, 't1_interval_hours', 2)
    t2_max = getattr(workspace, 't2_max_age_hours', 72)
    t2_int = getattr(workspace, 't2_interval_hours', 6)
    t3_max = getattr(workspace, 't3_max_age_hours', 168)
    t3_int = getattr(workspace, 't3_interval_hours', 24)
    
    return {
        'T1': {'max_age_hours': t1_max, 'interval': timedelta(hours=t1_int)},
        'T2': {'max_age_hours': t2_max, 'interval': timedelta(hours=t2_int)},
        'T3': {'max_age_hours': t3_max, 'interval': timedelta(hours=t3_int)},
        'T4': {'max_age_hours': None, 'interval': None},
    }


def get_polling_tier_for_post(post_created_at: datetime, workspace) -> str:
    age_hours = (timezone.now() - post_created_at).total_seconds() / 3600
    t1_max = getattr(workspace, 't1_max_age_hours', 24)
    t2_max = getattr(workspace, 't2_max_age_hours', 72)
    t3_max = getattr(workspace, 't3_max_age_hours', 168)
    
    if age_hours <= t1_max:
        return 'T1'
    elif age_hours <= t2_max:
        return 'T2'
    elif age_hours <= t3_max:
        return 'T3'
    return 'T4'


def update_post_polling_schedule(tracked_post):
    """
    Updates the polling tier and sets the next poll timestamp for a tracked post
    based on the post creation date and workspace-specific settings.
    """
    try:
        workspace = tracked_post.campaign_inf.campaign.workspace
    except Exception:
        workspace = None

    tier = get_polling_tier_for_post(tracked_post.published_at or tracked_post.created_at, workspace)
    tracked_post.polling_tier = tier
    
    config = get_workspace_polling_tiers(workspace)
    tier_config = config[tier]
    interval = tier_config['interval']
    
    if interval:
        tracked_post.next_poll_at = timezone.now() + interval
    else:
        tracked_post.next_poll_at = None
        tracked_post.status = 'ARCHIVED'
        
    tracked_post.save()
    return tracked_post

