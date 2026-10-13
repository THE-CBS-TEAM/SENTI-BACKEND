import logging
from django.utils import timezone
from dateutil import parser as date_parser

from apps.influencers.models import (
    GlobalInfluencer,
    Influencer,
    PlatformMetrics,
    OrganicBenchmark,
    FetchJob,
    ApiCostLog,
)
from apps.integrations.sociavault.client import sociavault_client
from apps.scoring.services.calculator import SentiScoreCalculator
from apps.sentiment.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def _safe_int(val, default=0):
    """Safely coerces any value (int, float, string with commas/whitespace) to integer."""
    if val is None or val == '':
        return default
    try:
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str):
            cleaned = val.replace(',', '').strip()
            return int(float(cleaned))
    except (ValueError, TypeError):
        pass
    return default


def _extract_items(container):
    """Safely extracts a list of dictionary items from either a dict of string indices or a list."""
    if isinstance(container, dict):
        return [v for v in container.values() if isinstance(v, dict)]
    if isinstance(container, list):
        return [v for v in container if isinstance(v, dict)]
    return []


class ProfileFetcher:
    """
    Unified creator data ingestion service powered by SociaVault.
    Replaces Apify (Instagram, TikTok) and SocialData (X/Twitter).

    Flow:
      1. Fetches profiles and benchmark posts from SociaVault across IG, TikTok, and X.
      2. Computes audience reach, engagement rate, average views/likes/comments.
      3. Saves PlatformMetrics and OrganicBenchmark rows on GlobalInfluencer.
      4. Calculates the 4-component proprietary Senti Score.
      5. Runs DeepSeek creator intelligence analysis directly in Django and caches it.
      6. Resets 24-hour freshness tracking via mark_scraped().
    """

    def fetch_and_benchmark_global_influencer(self, global_influencer_id: int) -> bool:
        """
        Primary entry point for fetching and benchmarking a GlobalInfluencer.
        """
        try:
            global_inf = GlobalInfluencer.objects.get(pk=global_influencer_id)
        except GlobalInfluencer.DoesNotExist:
            logger.error(f"GlobalInfluencer {global_influencer_id} not found.")
            return False

        logger.info(f"Starting SociaVault fetch for GlobalInfluencer: {global_inf.display_name}")
        global_inf.last_fetch_attempt_at = timezone.now()
        global_inf.scrape_in_progress = True
        global_inf.save(update_fields=['last_fetch_attempt_at', 'scrape_in_progress'])

        fetch_job = FetchJob.objects.create(
            entity_type='GLOBAL_INFLUENCER',
            entity_id=global_inf.id,
            provider=FetchJob.Providers.SOCIAVAULT,
            status=FetchJob.Statuses.RUNNING,
            cost_credits=0.0,
        )

        try:
            # 1. Instagram
            if global_inf.ig_handle:
                self._fetch_instagram(global_inf)

            # 2. TikTok
            if global_inf.tiktok_handle:
                self._fetch_tiktok(global_inf)

            # 3. Twitter / X
            if global_inf.x_handle:
                self._fetch_twitter(global_inf)

            # 4. Calculate Senti Score
            SentiScoreCalculator.calculate_global_influencer_senti_score(global_inf.id)

            # 4.5. Run Audience Authenticity Audit
            try:
                from apps.scoring.services.fake_follower import FakeFollowerDetector
                FakeFollowerDetector.analyze_authenticity_for_global(global_inf.id)
            except Exception as auth_err:
                logger.warning(f"Authenticity audit error for GlobalInfluencer {global_inf.id}: {auth_err}")

            # 5. DeepSeek Creator Analysis & Cache
            try:
                LLMService.generate_global_influencer_analysis(global_inf)
            except Exception as llm_err:
                logger.warning(f"DeepSeek analysis error for GlobalInfluencer {global_inf.id}: {llm_err}")

            # 6. Mark data fresh (expires in 24h)
            global_inf.mark_scraped()

            # 7. Mirror scores to linked legacy records if any exist
            Influencer.objects.filter(global_influencer=global_inf).update(
                senti_score=global_inf.senti_score,
                senti_label=global_inf.senti_label,
                centi_score=global_inf.senti_score,
                fake_follower_score=global_inf.fake_follower_score,
                avatar_url=global_inf.avatar_url or '',
                last_successful_fetch_at=timezone.now(),
                consecutive_fetch_failures=0,
                last_fetch_error=None,
            )

            # Finalize FetchJob
            try:
                from django.db.models import Sum
                recent_cost = ApiCostLog.objects.filter(
                    global_influencer=global_inf,
                    created_at__gte=fetch_job.created_at
                ).aggregate(total=Sum('cost_usd'))['total'] or 0.0
                fetch_job.cost_credits = recent_cost
            except Exception:
                pass
            fetch_job.status = FetchJob.Statuses.DONE
            fetch_job.completed_at = timezone.now()
            fetch_job.save(update_fields=['status', 'cost_credits', 'completed_at'])

            logger.info(f"Successfully scraped & benchmarked GlobalInfluencer {global_inf.display_name}")
            return True

        except Exception as exc:
            err_msg = str(exc)
            logger.error(f"Error fetching GlobalInfluencer {global_inf.id}: {err_msg}")
            global_inf.last_fetch_error = err_msg
            global_inf.scrape_in_progress = False
            global_inf.consecutive_fetch_failures = (global_inf.consecutive_fetch_failures or 0) + 1
            global_inf.save(update_fields=['last_fetch_error', 'scrape_in_progress', 'consecutive_fetch_failures'])

            if 'fetch_job' in locals():
                fetch_job.status = FetchJob.Statuses.FAIL
                fetch_job.error_message = err_msg
                fetch_job.completed_at = timezone.now()
                fetch_job.save(update_fields=['status', 'error_message', 'completed_at'])
            return False

    def fetch_and_benchmark_influencer(self, influencer_id: int) -> bool:
        """
        Backwards-compatibility wrapper for legacy Influencer model calls.
        Routes to GlobalInfluencer.
        """
        try:
            inf = Influencer.objects.select_related('global_influencer').get(pk=influencer_id)
        except Influencer.DoesNotExist:
            logger.error(f"Legacy Influencer {influencer_id} not found.")
            return False

        if inf.global_influencer:
            success = self.fetch_and_benchmark_global_influencer(inf.global_influencer_id)
            inf.refresh_from_db()
            return success

        # Bridge if not linked to global influencer yet
        global_inf, _ = GlobalInfluencer.objects.get_or_create(
            ig_handle=inf.ig_handle if inf.ig_handle else None,
            tiktok_handle=inf.tiktok_handle if inf.tiktok_handle else None,
            x_handle=inf.x_handle if inf.x_handle else None,
            defaults={
                'display_name': inf.display_name,
                'niche': inf.niche,
                'avatar_url': inf.avatar_url,
            }
        )
        inf.global_influencer = global_inf
        inf.save(update_fields=['global_influencer'])

        return self.fetch_and_benchmark_global_influencer(global_inf.id)

    # ─────────────────────────────────────────────────────────────────────────
    # INSTAGRAM (SociaVault)
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_instagram(self, global_inf: GlobalInfluencer):
        from apps.influencers.utils import sanitize_social_handle
        raw_handle = global_inf.ig_handle or ''
        handle = sanitize_social_handle(raw_handle)
        if not handle:
            logger.warning(f"Skipping Instagram fetch: Invalid or empty handle '{raw_handle}'")
            return
        try:
            profile_data = None
            try:
                profile_data = sociavault_client.get_instagram_profile(
                    handle,
                    global_influencer=global_inf,
                    cost_category=ApiCostLog.CostCategories.SOCIAVAULT_PROFILE
                )
            except Exception as api_err:
                err_text = str(api_err)
                logger.warning(f"SociaVault IG live fetch failed for @{handle}: {api_err}")
                global_inf.last_fetch_error = f"Instagram (@{handle}): {err_text}"
                global_inf.save(update_fields=['last_fetch_error'])
                Influencer.objects.filter(global_influencer=global_inf).update(last_fetch_error=f"Instagram (@{handle}): {err_text}")
                existing_pm = PlatformMetrics.objects.filter(global_influencer=global_inf, platform='IG').first()
                if existing_pm and existing_pm.raw_api_response:
                    logger.info(f"Using stored raw_api_response for @{handle} Instagram")
                    profile_data = existing_pm.raw_api_response

            if not profile_data:
                logger.warning(f"No Instagram profile returned for @{handle}")
                return

            # Robust extraction of user dictionary
            user = profile_data
            if isinstance(profile_data.get('data'), dict):
                sub = profile_data['data']
                if isinstance(sub.get('data'), dict) and 'user' in sub['data']:
                    user = sub['data']['user']
                elif 'user' in sub and isinstance(sub['user'], dict):
                    user = sub['user']
                else:
                    user = sub
            elif 'user' in profile_data and isinstance(profile_data['user'], dict):
                user = profile_data['user']

            # Extract followers count
            followers = (
                user.get('edge_followed_by', {}).get('count') or
                user.get('follower_count') or
                user.get('followers_count') or
                user.get('followers') or
                user.get('edge_follow', {}).get('count') or 0
            )

            # Extract avatar if not set
            avatar = (
                user.get('profile_pic_url_hd') or
                user.get('profile_pic_url') or
                user.get('avatar')
            )
            if avatar and (not global_inf.avatar_url or 'default_profile' in global_inf.avatar_url):
                global_inf.avatar_url = avatar
                global_inf.save(update_fields=['avatar_url'])

            # Extract posts from profile response
            posts = []
            timeline_media = user.get('edge_owner_to_timeline_media') or {}
            edges = timeline_media.get('edges') if isinstance(timeline_media, dict) else None
            if edges:
                for item in _extract_items(edges):
                    posts.append(item.get('node', item))

            if not posts:
                for item in _extract_items(user.get('posts') or user.get('recent_posts') or profile_data.get('posts')):
                    posts.append(item.get('node', item))

            # If still no posts, try calling get_instagram_posts
            if not posts:
                try:
                    posts_resp = sociavault_client.get_instagram_posts(
                        handle,
                        global_influencer=global_inf,
                        cost_category=ApiCostLog.CostCategories.SOCIAVAULT_POSTS
                    )
                    if posts_resp:
                        resp_data = posts_resp.get('data') if isinstance(posts_resp, dict) else posts_resp
                        raw_edges = (resp_data.get('edges') or resp_data.get('posts') or resp_data) if isinstance(resp_data, dict) else resp_data
                        for item in _extract_items(raw_edges):
                            posts.append(item.get('node', item))
                except Exception as p_err:
                    logger.warning(f"Could not fetch separate IG posts for @{handle}: {p_err}")

            posts_count = len(posts)
            likes_total = 0
            comments_total = 0
            shares_total = 0
            saves_total = 0
            views_total = 0

            for p in posts:
                likes_total += _safe_int(p.get('edge_media_preview_like', {}).get('count') or p.get('like_count') or p.get('likes'))
                comments_total += _safe_int(p.get('edge_media_to_comment', {}).get('count') or p.get('comment_count') or p.get('comments'))
                shares_total += _safe_int(p.get('shares') or p.get('share_count'))
                saves_total += _safe_int(p.get('saves') or p.get('saved_count'))
                p_views = _safe_int(p.get('video_play_count') or p.get('video_view_count') or p.get('views') or p.get('play_count'))
                if p_views == 0 and (likes_total + comments_total) > 0:
                    p_views = int((_safe_int(p.get('edge_media_preview_like', {}).get('count')) + _safe_int(p.get('edge_media_to_comment', {}).get('count'))) * 5)
                views_total += p_views

            avg_likes = int(likes_total / posts_count) if posts_count > 0 else 0
            avg_comments = int(comments_total / posts_count) if posts_count > 0 else 0
            avg_shares = int(shares_total / posts_count) if posts_count > 0 else 0
            avg_saves = int(saves_total / posts_count) if posts_count > 0 else 0
            avg_views = int(views_total / posts_count) if posts_count > 0 else 0

            total_avg_interactions = avg_likes + avg_comments + avg_shares + avg_saves
            if avg_views == 0 and total_avg_interactions > 0:
                avg_views = int(total_avg_interactions * 5)

            engagement_rate = (total_avg_interactions / followers * 100) if followers > 0 else 0.0

            # Calculate AAR, CR, RE using MetricsEngine
            from apps.scoring.services.metrics_engine import MetricsEngine
            c2_metrics = MetricsEngine.c2_resonance_efficiency(avg_views, followers, total_avg_interactions)

            # Save PlatformMetrics
            PlatformMetrics.objects.update_or_create(
                global_influencer=global_inf,
                platform='IG',
                defaults={
                    'followers': followers,
                    'engagement_rate': round(engagement_rate, 4),
                    'avg_views': avg_views,
                    'avg_likes': avg_likes,
                    'avg_comments': avg_comments,
                    'avg_shares': avg_shares,
                    'avg_saves': avg_saves,
                    'avg_reposts': 0,
                    'aar': c2_metrics['aar'],
                    'cr': c2_metrics['cr'],
                    'resonance_efficiency': c2_metrics['re'],
                    'raw_api_response': profile_data,
                    'fetched_at': timezone.now()
                }
            )

            # Store OrganicBenchmark (top 10 posts)
            OrganicBenchmark.objects.filter(global_influencer=global_inf, platform='IG').delete()
            for p in posts[:10]:
                likes = p.get('edge_media_preview_like', {}).get('count') or p.get('like_count') or p.get('likes') or 0
                comments = p.get('edge_media_to_comment', {}).get('count') or p.get('comment_count') or p.get('comments') or 0
                shares = p.get('shares') or p.get('share_count') or 0
                saves = p.get('saves') or p.get('saved_count') or 0
                views = p.get('video_play_count') or p.get('video_view_count') or p.get('views') or 0
                if views == 0 and (likes + comments) > 0:
                    views = int((likes + comments) * 5)

                shortcode = p.get('shortcode')
                p_url = f"https://www.instagram.com/p/{shortcode}/" if shortcode else (p.get('url') or p.get('post_url') or f"https://www.instagram.com/{handle}/")
                p_date = None
                ts = p.get('taken_at_timestamp')
                if ts:
                    try:
                        from datetime import datetime
                        p_date = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    except Exception:
                        pass
                if not p_date:
                    date_val = p.get('taken_at') or p.get('timestamp') or p.get('created_at')
                    if date_val:
                        try:
                            p_date = date_parser.parse(str(date_val))
                        except Exception:
                            pass

                # Extract caption text
                caption_edges = p.get('edge_media_to_caption')
                caption_text = ''
                if isinstance(caption_edges, dict):
                    edges_list = _extract_items(caption_edges.get('edges') or caption_edges)
                    if edges_list:
                        caption_text = edges_list[0].get('node', {}).get('text') or ''
                elif isinstance(caption_edges, list) and caption_edges:
                    caption_text = caption_edges[0].get('node', {}).get('text') or ''
                if not caption_text:
                    caption_text = p.get('caption') or p.get('text') or ''

                OrganicBenchmark.objects.create(
                    global_influencer=global_inf,
                    platform='IG',
                    post_url=p_url,
                    views=views,
                    likes=likes,
                    comments_count=comments,
                    shares=shares,
                    saves=saves,
                    reposts=0,
                    engagement_total=likes + comments + shares + saves,
                    post_text=caption_text,
                    post_created_at=p_date
                )

        except Exception as e:
            logger.error(f"SociaVault IG error for @{handle}: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # TIKTOK (SociaVault)
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_tiktok(self, global_inf: GlobalInfluencer):
        from apps.influencers.utils import sanitize_social_handle
        raw_handle = global_inf.tiktok_handle or ''
        handle = sanitize_social_handle(raw_handle)
        if not handle:
            logger.warning(f"Skipping TikTok fetch: Invalid or empty handle '{raw_handle}'")
            return
        try:
            profile_data = None
            try:
                profile_data = sociavault_client.get_tiktok_profile(
                    handle,
                    global_influencer=global_inf,
                    cost_category=ApiCostLog.CostCategories.SOCIAVAULT_PROFILE
                )
            except Exception as api_err:
                err_text = str(api_err)
                logger.warning(f"SociaVault TikTok live fetch failed for @{handle}: {api_err}")
                global_inf.last_fetch_error = f"TikTok (@{handle}): {err_text}"
                global_inf.save(update_fields=['last_fetch_error'])
                Influencer.objects.filter(global_influencer=global_inf).update(last_fetch_error=f"TikTok (@{handle}): {err_text}")
                existing_pm = PlatformMetrics.objects.filter(global_influencer=global_inf, platform='TT').first()
                if existing_pm and existing_pm.raw_api_response:
                    logger.info(f"Using stored raw_api_response for @{handle} TikTok")
                    profile_data = existing_pm.raw_api_response

            if not profile_data:
                logger.warning(f"No TikTok profile returned for @{handle}")
                return

            d = profile_data.get('data') if isinstance(profile_data.get('data'), dict) else profile_data
            stats = d.get('stats') or d.get('statsV2') or {}
            followers = (
                stats.get('followerCount') or
                d.get('followerCount') or
                d.get('followers') or 0
            )

            avatar = (
                d.get('user', {}).get('avatarLarger') or
                d.get('user', {}).get('avatarThumb') or
                d.get('avatar') or
                d.get('avatarLarger') or
                d.get('avatarMedium')
            )
            if avatar and (not global_inf.avatar_url or 'default_profile' in global_inf.avatar_url):
                global_inf.avatar_url = avatar
                global_inf.save(update_fields=['avatar_url'])

            # Fetch videos
            videos = []
            try:
                videos_resp = sociavault_client.get_tiktok_videos(
                    handle,
                    global_influencer=global_inf,
                    cost_category=ApiCostLog.CostCategories.SOCIAVAULT_POSTS
                )
                if videos_resp:
                    v_data = videos_resp.get('data') if isinstance(videos_resp, dict) else videos_resp
                    raw_vids = (v_data.get('aweme_list') or v_data.get('itemList') or v_data) if isinstance(v_data, dict) else v_data
                    videos = _extract_items(raw_vids)
            except Exception as v_err:
                logger.warning(f"Could not fetch TikTok videos for @{handle}: {v_err}")

            if not videos:
                raw_items = d.get('itemList') or d.get('aweme_list') or d.get('videos')
                videos = _extract_items(raw_items)

            posts_count = len(videos)
            likes_total = 0
            comments_total = 0
            views_total = 0
            shares_total = 0
            saves_total = 0

            for v in videos:
                st = v.get('statistics') or v.get('stats') or v
                likes_total += _safe_int(st.get('digg_count') or st.get('diggCount') or st.get('likes'))
                comments_total += _safe_int(st.get('comment_count') or st.get('commentCount') or st.get('comments'))
                views_total += _safe_int(st.get('play_count') or st.get('playCount') or st.get('views'))
                shares_total += _safe_int(st.get('share_count') or st.get('shareCount') or st.get('shares'))
                saves_total += _safe_int(st.get('collect_count') or st.get('collectCount') or st.get('saves'))

            avg_likes = int(likes_total / posts_count) if posts_count > 0 else 0
            avg_comments = int(comments_total / posts_count) if posts_count > 0 else 0
            avg_views = int(views_total / posts_count) if posts_count > 0 else 0
            avg_shares = int(shares_total / posts_count) if posts_count > 0 else 0
            avg_saves = int(saves_total / posts_count) if posts_count > 0 else 0

            total_avg_eng = avg_likes + avg_comments + avg_shares + avg_saves
            if avg_views == 0 and total_avg_eng > 0:
                avg_views = int(total_avg_eng * 4.5)

            engagement_rate = (total_avg_eng / followers * 100) if followers > 0 else 0.0

            from apps.scoring.services.metrics_engine import MetricsEngine
            c2_metrics = MetricsEngine.c2_resonance_efficiency(avg_views, followers, total_avg_eng)

            PlatformMetrics.objects.update_or_create(
                global_influencer=global_inf,
                platform='TT',
                defaults={
                    'followers': followers,
                    'engagement_rate': round(engagement_rate, 4),
                    'avg_views': avg_views,
                    'avg_likes': avg_likes,
                    'avg_comments': avg_comments,
                    'avg_shares': avg_shares,
                    'avg_saves': avg_saves,
                    'avg_reposts': 0,
                    'aar': c2_metrics['aar'],
                    'cr': c2_metrics['cr'],
                    'resonance_efficiency': c2_metrics['re'],
                    'raw_api_response': profile_data,
                    'fetched_at': timezone.now()
                }
            )

            OrganicBenchmark.objects.filter(global_influencer=global_inf, platform='TT').delete()
            for v in videos[:10]:
                st = v.get('statistics') or v.get('stats') or v
                likes = st.get('digg_count') or st.get('diggCount') or st.get('likes') or 0
                comments = st.get('comment_count') or st.get('commentCount') or st.get('comments') or 0
                shares = st.get('share_count') or st.get('shareCount') or st.get('shares') or 0
                saves = st.get('collect_count') or st.get('collectCount') or st.get('saves') or 0
                views = st.get('play_count') or st.get('playCount') or st.get('views') or 0
                if views == 0 and (likes + comments) > 0:
                    views = int((likes + comments) * 4.5)

                v_id = v.get('aweme_id') or v.get('id')
                v_url = v.get('share_url') or v.get('url') or (f"https://www.tiktok.com/@{handle}/video/{v_id}" if v_id else f"https://www.tiktok.com/@{handle}")
                v_date = None
                ct = v.get('create_time')
                if ct:
                    try:
                        from datetime import datetime
                        v_date = datetime.fromtimestamp(int(ct), tz=timezone.utc)
                    except Exception:
                        pass
                if not v_date:
                    date_val = v.get('createTimeISO') or v.get('createTime') or v.get('created_at')
                    if date_val:
                        try:
                            v_date = date_parser.parse(str(date_val))
                        except Exception:
                            pass

                OrganicBenchmark.objects.create(
                    global_influencer=global_inf,
                    platform='TT',
                    post_url=v_url,
                    views=views,
                    likes=likes,
                    comments_count=comments,
                    shares=shares,
                    saves=saves,
                    reposts=0,
                    engagement_total=likes + comments + shares + saves,
                    post_text=v.get('desc') or v.get('title') or v.get('text') or '',
                    post_created_at=v_date
                )

        except Exception as e:
            logger.error(f"SociaVault TikTok error for @{handle}: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # TWITTER / X (SociaVault)
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_twitter(self, global_inf: GlobalInfluencer):
        from apps.influencers.utils import sanitize_social_handle
        raw_handle = global_inf.x_handle or ''
        handle = sanitize_social_handle(raw_handle)
        if not handle:
            logger.warning(f"Skipping Twitter fetch: Invalid or empty handle '{raw_handle}'")
            return
        try:
            profile_data = None
            existing_pm = PlatformMetrics.objects.filter(global_influencer=global_inf, platform='X').first()
            if existing_pm and existing_pm.raw_api_response:
                logger.info(f"Using stored raw_api_response for @{handle} Twitter")
                profile_data = existing_pm.raw_api_response

            # 1. Fetch user tweets (1 credit) - provides tweets, engagement metrics, and embedded author profile
            tweets = []
            tweets_resp = None
            try:
                tweets_resp = sociavault_client.get_twitter_user_tweets(
                    handle,
                    global_influencer=global_inf,
                    cost_category=ApiCostLog.CostCategories.SOCIAVAULT_POSTS
                )
                if tweets_resp:
                    t_data = tweets_resp.get('data') if isinstance(tweets_resp, dict) else tweets_resp
                    raw_items = None
                    if isinstance(t_data, dict):
                        raw_items = t_data.get('tweets') or t_data.get('timeline') or t_data.get('items')
                        if raw_items is None and isinstance(t_data.get('data'), (dict, list)):
                            raw_items = t_data['data']
                    elif isinstance(t_data, list):
                        raw_items = t_data

                    candidate_list = _extract_items(raw_items) if raw_items else []
                    for t in candidate_list:
                        leg = t.get('legacy') or t
                        # Only accept if it looks like an actual tweet
                        if (leg.get('id_str') or leg.get('id') or t.get('id_str') or t.get('id') or t.get('rest_id') or leg.get('full_text') or leg.get('text')):
                            tweets.append(t)
            except Exception as t_err:
                err_text = str(t_err)
                logger.warning(f"Could not fetch Twitter tweets for @{handle}: {t_err}")
                global_inf.last_fetch_error = f"Twitter (@{handle}): {err_text}"
                global_inf.save(update_fields=['last_fetch_error'])
                Influencer.objects.filter(global_influencer=global_inf).update(last_fetch_error=f"Twitter (@{handle}): {err_text}")

            # 2. Extract followers and avatar from tweets or profile endpoint fallback
            followers = 0
            avatar = None

            if tweets:
                first_t = tweets[0]
                user_res = first_t.get('core', {}).get('user_results', {}).get('result', {})
                user_leg = user_res.get('legacy') or first_t.get('user') or {}
                followers = _safe_int(user_leg.get('followers_count') or user_res.get('followers_count'))
                avatar = user_leg.get('profile_image_url_https') or user_res.get('avatar', {}).get('image_url')

            # Only fallback to get_twitter_profile if no followers were extracted and no cached profile exists
            if followers == 0 and not profile_data:
                try:
                    profile_data = sociavault_client.get_twitter_profile(
                        handle,
                        global_influencer=global_inf,
                        cost_category=ApiCostLog.CostCategories.SOCIAVAULT_PROFILE
                    )
                except Exception as api_err:
                    err_text = str(api_err)
                    logger.warning(f"SociaVault Twitter profile fetch failed for @{handle}: {api_err}")
                    global_inf.last_fetch_error = f"Twitter Profile (@{handle}): {err_text}"
                    global_inf.save(update_fields=['last_fetch_error'])
                    Influencer.objects.filter(global_influencer=global_inf).update(last_fetch_error=f"Twitter Profile (@{handle}): {err_text}")

            if profile_data:
                d = profile_data.get('data') if isinstance(profile_data.get('data'), dict) else profile_data
                if isinstance(d, dict):
                    leg = d.get('legacy') or {}
                    if followers == 0:
                        followers = _safe_int(
                            leg.get('followers_count') or
                            d.get('followers_count') or
                            d.get('followers') or
                            d.get('normal_followers_count') or 0
                        )
                    if not avatar:
                        avatar = (
                            d.get('avatar', {}).get('image_url') or
                            leg.get('profile_image_url_https') or
                            d.get('profile_image_url_https') or
                            d.get('profile_image_url')
                        )

            if avatar:
                avatar = avatar.replace('_normal', '_400x400')
                if not global_inf.avatar_url or 'default_profile' in global_inf.avatar_url:
                    global_inf.avatar_url = avatar
                    global_inf.save(update_fields=['avatar_url'])

            tweets_count = len(tweets)
            likes_total = 0
            comments_total = 0
            retweets_total = 0
            saves_total = 0
            views_total = 0

            for t in tweets:
                leg = t.get('legacy') or t
                likes_total += _safe_int(leg.get('favorite_count') or leg.get('likes'))
                comments_total += _safe_int(leg.get('reply_count') or leg.get('replies'))
                retweets_total += _safe_int(leg.get('retweet_count') or leg.get('retweets'))
                saves_total += _safe_int(leg.get('bookmark_count') or leg.get('bookmarks'))
                views_val = leg.get('views_count') or (t.get('views', {}).get('count') if isinstance(t.get('views'), dict) else t.get('views'))
                views_total += _safe_int(views_val)

            avg_likes = int(likes_total / tweets_count) if tweets_count > 0 else 0
            avg_comments = int(comments_total / tweets_count) if tweets_count > 0 else 0
            avg_retweets = int(retweets_total / tweets_count) if tweets_count > 0 else 0
            avg_saves = int(saves_total / tweets_count) if tweets_count > 0 else 0
            avg_views = int(views_total / tweets_count) if tweets_count > 0 else 0

            avg_eng = avg_likes + avg_retweets + avg_comments + avg_saves
            if avg_views == 0 and avg_eng > 0:
                avg_views = int(avg_eng * 5)
            elif avg_views == 0 and followers > 0:
                avg_views = max(10, int(followers * 0.15))

            engagement_rate = (avg_eng / followers * 100) if followers > 0 else 0.0

            from apps.scoring.services.metrics_engine import MetricsEngine
            c2_metrics = MetricsEngine.c2_resonance_efficiency(avg_views, followers, avg_eng)

            PlatformMetrics.objects.update_or_create(
                global_influencer=global_inf,
                platform='X',
                defaults={
                    'followers': followers,
                    'engagement_rate': round(engagement_rate, 4),
                    'avg_views': avg_views,
                    'avg_likes': avg_likes,
                    'avg_comments': avg_comments,
                    'avg_shares': 0,
                    'avg_saves': avg_saves,
                    'avg_reposts': avg_retweets,
                    'aar': c2_metrics['aar'],
                    'cr': c2_metrics['cr'],
                    'resonance_efficiency': c2_metrics['re'],
                    'raw_api_response': profile_data,
                    'fetched_at': timezone.now()
                }
            )

            OrganicBenchmark.objects.filter(global_influencer=global_inf, platform='X').delete()
            created_benchmarks = []
            for t in tweets[:10]:
                leg = t.get('legacy') or t
                t_id = leg.get('id_str') or leg.get('id') or t.get('id_str') or t.get('id') or t.get('rest_id')
                if not t_id:
                    continue

                likes = _safe_int(leg.get('favorite_count') or leg.get('likes'))
                replies = _safe_int(leg.get('reply_count') or leg.get('replies'))
                retweets = _safe_int(leg.get('retweet_count') or leg.get('retweets'))
                bookmarks = _safe_int(leg.get('bookmark_count') or leg.get('bookmarks'))
                views_val = leg.get('views_count') or (t.get('views', {}).get('count') if isinstance(t.get('views'), dict) else t.get('views'))
                views = _safe_int(views_val)
                if views == 0 and (likes + replies + retweets) > 0:
                    views = int((likes + replies + retweets) * 5)

                t_url = f"https://x.com/{handle}/status/{t_id}"
                t_date = None
                date_val = leg.get('created_at') or t.get('created_at')
                if date_val:
                    try:
                        t_date = date_parser.parse(str(date_val))
                    except Exception:
                        pass

                bench = OrganicBenchmark.objects.create(
                    global_influencer=global_inf,
                    platform='X',
                    post_url=t_url,
                    views=views,
                    likes=likes,
                    comments_count=replies,
                    shares=0,
                    saves=bookmarks,
                    reposts=retweets,
                    engagement_total=likes + replies + retweets + bookmarks,
                    post_text=leg.get('full_text') or leg.get('text') or '',
                    post_created_at=t_date
                )
                created_benchmarks.append(bench)

            if created_benchmarks:
                latest_with_comments = next((b for b in created_benchmarks if b.comments_count > 0), created_benchmarks[0])
                from tasks.sentiment_tasks import analyze_organic_post_comments_task
                analyze_organic_post_comments_task.delay(latest_with_comments.id)

        except Exception as e:
            logger.error(f"SociaVault Twitter error for @{handle}: {e}")
