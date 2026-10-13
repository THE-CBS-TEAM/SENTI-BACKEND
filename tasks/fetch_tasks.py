import logging
from celery import shared_task
from django.utils import timezone
from apps.influencers.models import Influencer
from apps.campaigns.models import TrackedPost
from apps.influencers.services.profile_fetcher import ProfileFetcher
from apps.campaigns.services.polling_scheduler import update_post_polling_schedule
from apps.integrations.apify.client import ApifyClient
from apps.integrations.socialdata.client import SocialDataClient
from apps.integrations.router import IntegrationRouter

logger = logging.getLogger(__name__)


@shared_task(queue='fetch')
def fetch_influencer_profile_task(influencer_id):
    """Celery task to fetch influencer profile and build organic benchmarks."""
    fetcher = ProfileFetcher()
    success = fetcher.fetch_and_benchmark_influencer(influencer_id)
    if success:
        # Trigger initial Centi Score calculation synchronously
        from tasks.scoring_tasks import calculate_centi_score_task
        calculate_centi_score_task(influencer_id)
        
        # Trigger comment scraping tasks for top 15 benchmark posts per platform (up to 45 posts total)
        from apps.influencers.models import OrganicBenchmark
        from tasks.sentiment_tasks import analyze_organic_post_comments_task
        
        for platform in ['IG', 'TT', 'X']:
            benchmarks = OrganicBenchmark.objects.filter(
                influencer_id=influencer_id, platform=platform
            ).order_by('-post_created_at', '-id')[:15]
            for post in benchmarks:
                analyze_organic_post_comments_task.delay(post.id)
                
    return success


@shared_task(queue='fetch')
def fetch_tracked_post_metrics_task(tracked_post_id):
    """
    Fetches the latest metrics (likes, views, comments, shares) for a tracked post.
    Then triggers comments sentiment analysis and updates scheduling.
    """
    try:
        post = TrackedPost.objects.get(pk=tracked_post_id)
    except TrackedPost.DoesNotExist:
        logger.error(f"TrackedPost {tracked_post_id} not found.")
        return False

    logger.info(f"Ingesting metrics for tracked post: {post.post_url}")
    now = timezone.now()
    post.last_fetch_attempt_at = now
    post.save(update_fields=['last_fetch_attempt_at'])
    
    # Simple regex url parse to find target ids
    parsed = IntegrationRouter.parse_url(post.post_url)
    if not parsed:
        err_msg = f"Unable to parse URL {post.post_url}"
        logger.error(err_msg)
        post.last_fetch_error = err_msg
        post.consecutive_fetch_failures += 1
        if post.consecutive_fetch_failures >= 5:
            post.status = TrackedPost.Statuses.ERROR
        post.save()
        return False

    platform = parsed['platform']
    
    from apps.integrations.sociavault.client import sociavault_client
    from apps.influencers.models import ApiCostLog, FetchJob

    campaign = post.campaign_inf.campaign if post.campaign_inf else None
    workspace = campaign.workspace if campaign else None

    cost_kwargs = {
        'campaign': campaign,
        'workspace': workspace,
        'pipeline_stage': ApiCostLog.PipelineStages.MONITORING,
        'cost_category': ApiCostLog.CostCategories.SOCIAVAULT_POSTS,
    }

    fetch_job = FetchJob.objects.create(
        entity_type='POST',
        entity_id=post.id,
        provider=FetchJob.Providers.SOCIAVAULT,
        status=FetchJob.Statuses.RUNNING,
        cost_credits=0.0,
    )

    try:
        if platform == 'IG':
            data = sociavault_client.get_instagram_post_info(post.post_url, **cost_kwargs)
            if data:
                post.raw_api_response = data
                cur = data
                if isinstance(cur, dict) and 'data' in cur and isinstance(cur['data'], dict):
                    cur = cur['data']
                if isinstance(cur, dict) and 'data' in cur and isinstance(cur['data'], dict):
                    cur = cur['data']
                media = cur.get('xdt_shortcode_media') if isinstance(cur, dict) else None
                if not media and isinstance(cur, dict):
                    media = cur

                if isinstance(media, dict):
                    # Likes
                    edge_likes = media.get('edge_media_preview_like') or media.get('edge_liked_by')
                    if isinstance(edge_likes, dict):
                        post.likes = edge_likes.get('count', 0)
                    else:
                        post.likes = media.get('like_count') or media.get('likes') or media.get('likesCount') or 0

                    # Comments count
                    edge_comments = media.get('edge_media_to_parent_comment') or media.get('edge_media_to_comment')
                    if isinstance(edge_comments, dict):
                        post.comments_count = edge_comments.get('count', 0)
                    else:
                        post.comments_count = media.get('comment_count') or media.get('comments') or media.get('commentsCount') or 0

                    # Views / Plays
                    post.views = (media.get('video_play_count') or 
                                  media.get('video_view_count') or 
                                  media.get('play_count') or 
                                  media.get('views') or 
                                  media.get('view_count') or 0)

                    pub_date_str = (media.get('taken_at_timestamp') or 
                                    media.get('taken_at') or 
                                    media.get('timestamp') or 
                                    media.get('created_at'))
                    if pub_date_str:
                        try:
                            from dateutil import parser as date_parser
                            if isinstance(pub_date_str, (int, float)):
                                from datetime import datetime, timezone as dt_tz
                                post.published_at = datetime.fromtimestamp(pub_date_str, tz=dt_tz.utc)
                            else:
                                post.published_at = date_parser.parse(str(pub_date_str))
                        except Exception:
                            pass
            else:
                raise Exception("SociaVault Instagram post-info returned no data")
            
        elif platform == 'TT':
            data = sociavault_client.get_tiktok_video_info(post.post_url, **cost_kwargs)
            if data:
                post.raw_api_response = data
                cur = data
                if isinstance(cur, dict) and 'data' in cur and isinstance(cur['data'], dict):
                    cur = cur['data']
                aweme = cur.get('aweme_detail') if isinstance(cur, dict) else None
                stats = {}
                if isinstance(aweme, dict) and 'statistics' in aweme:
                    stats = aweme['statistics']
                elif isinstance(cur, dict) and 'statistics' in cur:
                    stats = cur['statistics']
                elif isinstance(cur, dict):
                    stats = cur

                post.views = stats.get('play_count') or stats.get('playCount') or stats.get('views') or 0
                post.likes = stats.get('digg_count') or stats.get('diggCount') or stats.get('likes') or 0
                post.comments_count = stats.get('comment_count') or stats.get('commentCount') or stats.get('comments') or 0
                post.shares = stats.get('share_count') or stats.get('shareCount') or stats.get('shares') or 0
                post.saves = stats.get('collect_count') or stats.get('collectCount') or stats.get('saves') or 0

                pub_date_str = None
                if isinstance(aweme, dict):
                    pub_date_str = aweme.get('create_time') or aweme.get('createTime')
                if not pub_date_str and isinstance(cur, dict):
                    pub_date_str = cur.get('createTimeISO') or cur.get('createTime') or cur.get('created_at')

                if pub_date_str:
                    try:
                        from dateutil import parser as date_parser
                        if isinstance(pub_date_str, (int, float)):
                            from datetime import datetime, timezone as dt_tz
                            post.published_at = datetime.fromtimestamp(pub_date_str, tz=dt_tz.utc)
                        else:
                            post.published_at = date_parser.parse(str(pub_date_str))
                    except Exception:
                        pass
            else:
                raise Exception("SociaVault TikTok video-info returned no data")

        elif platform == 'X':
            tweet = sociavault_client.get_twitter_tweet(post.post_url, **cost_kwargs)
            if not tweet:
                raise Exception(f"SociaVault returned no tweet payload for URL {post.post_url}")
            else:
                post.raw_api_response = tweet
                cur = tweet
                if isinstance(cur, dict) and 'data' in cur and isinstance(cur['data'], dict):
                    cur = cur['data']
                legacy = cur.get('legacy') if isinstance(cur, dict) else None
                if not legacy and isinstance(cur, dict):
                    legacy = cur

                views_obj = cur.get('views') if isinstance(cur, dict) else None
                if isinstance(views_obj, dict):
                    try:
                        post.views = int(views_obj.get('count', 0) or 0)
                    except (ValueError, TypeError):
                        post.views = 0
                elif isinstance(views_obj, (int, float)):
                    post.views = int(views_obj)
                elif 'views_count' in cur:
                    try:
                        post.views = int(cur.get('views_count', 0) or 0)
                    except (ValueError, TypeError):
                        post.views = 0
                else:
                    post.views = tweet.get('views_count') or tweet.get('views') or 0

                post.likes = legacy.get('favorite_count') or legacy.get('likes') or legacy.get('like_count') or 0
                post.comments_count = legacy.get('reply_count') or legacy.get('replies') or legacy.get('replyCount') or 0
                post.shares = legacy.get('retweet_count') or legacy.get('retweets') or legacy.get('retweetCount') or 0
                post.retweets = post.shares
                post.saves = legacy.get('bookmark_count') or legacy.get('bookmarks') or legacy.get('bookmarkCount') or 0

                pub_date_str = legacy.get('created_at') or cur.get('tweet_created_at') or cur.get('created_at')
                if pub_date_str:
                    try:
                        from dateutil import parser as date_parser
                        post.published_at = date_parser.parse(str(pub_date_str))
                    except Exception:
                        pass

        success_now = timezone.now()
        post.last_fetched_at = success_now
        post.last_successful_fetch_at = success_now
        post.last_fetch_error = None
        post.consecutive_fetch_failures = 0
        if post.status == TrackedPost.Statuses.ERROR:
            post.status = TrackedPost.Statuses.MONITORING
        post.save()

        fetch_job.status = FetchJob.Statuses.DONE
        fetch_job.completed_at = success_now
        fetch_job.save(update_fields=['status', 'completed_at'])

        # Trigger Sentiment analysis task for this post comments
        from tasks.sentiment_tasks import analyze_post_comments_task
        analyze_post_comments_task.delay(post.id)

        # Decay polling schedule
        update_post_polling_schedule(post)
        return True

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error fetching post metrics for {post.post_url}: {err_msg}")
        try:
            from apps.admin_panel.utils.diagnostics import format_error_summary
            formatted_err = format_error_summary(err_msg, provider='SOCIAVAULT', entity_type='POST')
        except Exception:
            formatted_err = err_msg
        post.last_fetch_error = formatted_err
        post.consecutive_fetch_failures += 1
        if post.consecutive_fetch_failures >= 5:
            post.status = TrackedPost.Statuses.ERROR
        post.save()

        if 'fetch_job' in locals():
            fetch_job.status = FetchJob.Statuses.FAIL
            fetch_job.error_message = formatted_err
            fetch_job.completed_at = timezone.now()
            fetch_job.save(update_fields=['status', 'error_message', 'completed_at'])
        return False


@shared_task(queue='fetch')
def poll_active_posts_scheduled():
    """
    Scheduled cron task (runs every 1-2 hours via Celery Beat).
    Finds all active monitored posts due for polling.
    """
    now = timezone.now()
    active_posts = TrackedPost.objects.filter(
        status=TrackedPost.Statuses.MONITORING,
        next_poll_at__lte=now
    )
    logger.info(f"Scheduled polling found {active_posts.count()} post(s) to fetch.")
    for post in active_posts:
        fetch_tracked_post_metrics_task.delay(post.id)
    return active_posts.count()
