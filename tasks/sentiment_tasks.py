import logging
from celery import shared_task
from django.utils import timezone
from apps.campaigns.models import TrackedPost
from apps.sentiment.models import Comment
from apps.sentiment.services.analyzer import SentimentAnalyzer
from apps.sentiment.services.brand_extractor import BrandExtractor
from apps.sentiment.services.emotion_classifier import EmotionClassifier
from apps.sentiment.services.quality_classifier import CommentQualityClassifier
from apps.integrations.apify.client import ApifyClient
from apps.integrations.socialdata.client import SocialDataClient
from apps.integrations.router import IntegrationRouter

logger = logging.getLogger(__name__)


def extract_comment_author_and_text(comment_data, default_id=None):
    """
    Extracts author username and comment text across Instagram, TikTok, and Twitter/X
    from diverse API response payload schemas (SociaVault, Apify, SocialData).
    """
    comment_id = comment_data.get('id') or comment_data.get('id_str') or comment_data.get('cid') or default_id
    
    author = None
    # 1. Instagram & general nested user dicts
    if isinstance(comment_data.get('user'), dict):
        u = comment_data['user']
        author = u.get('username') or u.get('screen_name') or u.get('unique_id') or u.get('uniqueId') or u.get('nickname')
    elif isinstance(comment_data.get('owner'), dict):
        o = comment_data['owner']
        author = o.get('username') or o.get('screen_name')
    elif isinstance(comment_data.get('author'), dict):
        a = comment_data['author']
        author = a.get('uniqueId') or a.get('unique_id') or a.get('username') or a.get('nickname') or a.get('screen_name')

    # 2. Direct top-level fields
    if not author:
        author = (comment_data.get('ownerUsername') or 
                  comment_data.get('author_handle') or 
                  comment_data.get('username') or 
                  comment_data.get('screen_name') or 
                  comment_data.get('user_name'))

    if author:
        author = str(author).lstrip('@').strip()
    if not author or author.lower() in ['anonymous', 'unknown', 'none', '', 'null']:
        suffix = str(comment_id)[-4:] if comment_id else 'user'
        author = f"user_{suffix}"

    text = (comment_data.get('text') or 
            comment_data.get('full_text') or 
            comment_data.get('comment_text') or 
            comment_data.get('content') or 
            '')

    return str(comment_id) if comment_id else None, author, text


@shared_task(queue='sentiment')
def analyze_post_comments_task(tracked_post_id):
    """
    Fetches comments for a tracked post, runs VADER-first sentiment pipeline,
    extracts brand sentiment and emotion categories, and aggregates totals on the post.
    """
    try:
        post = TrackedPost.objects.get(pk=tracked_post_id)
    except TrackedPost.DoesNotExist:
        logger.error(f"TrackedPost {tracked_post_id} not found for comments analysis.")
        return False

    influencer = post.campaign_inf.influencer
    brand_name = post.campaign_inf.campaign.brand.name
    
    # 1. Fetch comments from platform API
    parsed = IntegrationRouter.parse_url(post.post_url)
    if not parsed:
        return False

    platform = parsed['platform']
    raw_comments = []

    try:
        from apps.integrations.sociavault.client import sociavault_client
        from apps.influencers.models import ApiCostLog

        if platform == 'IG':
            resp = sociavault_client.get_instagram_comments(
                post.post_url,
                cost_category=ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS
            )
            if resp:
                d = resp.get('data') if isinstance(resp, dict) else resp
                raw = (d.get('comments') or d.get('edge_media_to_comment') or d) if isinstance(d, dict) else d
                raw_comments = [c for c in (raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])) if isinstance(c, dict)]
        elif platform == 'TT':
            resp = sociavault_client.get_tiktok_comments(
                post.post_url,
                cost_category=ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS
            )
            if resp:
                d = resp.get('data') if isinstance(resp, dict) else resp
                raw = (d.get('comments') or d.get('itemList') or d) if isinstance(d, dict) else d
                raw_comments = [c for c in (raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])) if isinstance(c, dict)]
        elif platform == 'X':
            resp = sociavault_client.get_twitter_comments(
                post.post_url,
                cost_category=ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS
            )
            if resp:
                d = resp.get('data') if isinstance(resp, dict) else resp
                raw = (d.get('comments') or d.get('replies') or d.get('items') or d) if isinstance(d, dict) else d
                raw_comments = [c for c in (raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])) if isinstance(c, dict)]
    except Exception as e:
        logger.error(f"Error fetching tracked comments via SociaVault for {post.post_url}: {e}")
        raw_comments = []

    # If no comments returned, do not generate mock fallback data
    if not raw_comments:
        raw_comments = []
        
    # Limit to max 100 comments to save CPU and RAM resources
    if len(raw_comments) > 100:
        raw_comments = raw_comments[:100]


    # Initialize analyzer services
    analyzer = SentimentAnalyzer()
    brand_extractor = BrandExtractor()
    emotion_classifier = EmotionClassifier()
    quality_classifier = CommentQualityClassifier()

    # Batch LLM sentiment analysis if enabled on workspace
    workspace = post.campaign_inf.campaign.workspace if post.campaign_inf and post.campaign_inf.campaign else None
    from apps.sentiment.services.llm_service import LLMService
    llm_classifications = {}
    if workspace and workspace.use_llm_sentiment_analysis:
        comments_payload = [{'id': idx, 'text': c.get('text') or c.get('full_text') or ''} for idx, c in enumerate(raw_comments)]
        llm_classifications = LLMService.classify_comments_batch(comments_payload, workspace=workspace, brand_name=brand_name)

    pos_count = 0
    neu_count = 0
    neg_count = 0
    brand_pos_count = 0
    brand_neg_count = 0

    existing_ids = set(Comment.objects.filter(tracked_post=post).values_list('platform_comment_id', flat=True))
    new_comments = []

    for idx, comment_data in enumerate(raw_comments):
        # Normalize fields across platforms
        comment_id, author, text = extract_comment_author_and_text(comment_data, default_id=f"c_{post.id}_{idx}")
        
        # Parse timestamp
        timestamp_str = comment_data.get('timestamp') or comment_data.get('created_at')
        created_date = timezone.now()  # Default fallback
        if timestamp_str:
            try:
                from dateutil.parser import parse as dateutil_parse
                created_date = dateutil_parse(timestamp_str)
                if timezone.is_naive(created_date):
                    created_date = timezone.make_aware(created_date, timezone=timezone.utc)
            except (ValueError, TypeError, ImportError):
                # If dateutil not available or parsing fails, try ISO format
                try:
                    from datetime import datetime as dt
                    created_date = dt.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    created_date = timezone.now()

        # Run NLP Pipelines: LLM if available, otherwise high-precision Lexicon + Pidgin
        llm_item = llm_classifications.get(idx)
        if llm_item:
            sentiment = llm_item['sentiment']
            emotion = llm_item['emotion']
        else:
            sentiment, _ = analyzer.analyze_comment(text)
            emotion = emotion_classifier.classify_emotion(text)

        brand_mentioned, brand_sent = brand_extractor.extract_brand_sentiment(text, brand_name)
        is_substantive = quality_classifier.is_substantive(text)
        is_pod = quality_classifier.is_pod_signature(text, author)

        # Increment counts
        if sentiment == 'POS':
            pos_count += 1
        elif sentiment == 'NEG':
            neg_count += 1
        else:
            neu_count += 1

        if brand_mentioned:
            if brand_sent == 'POS':
                brand_pos_count += 1
            elif brand_sent == 'NEG':
                brand_neg_count += 1

        # Save Comment
        if comment_id and comment_id not in existing_ids:
            new_comments.append(Comment(
                tracked_post=post,
                platform_comment_id=comment_id,
                author_handle=author,
                text=text,
                sentiment=sentiment,
                emotion_category=emotion,
                brand_mentioned=brand_mentioned,
                brand_sentiment=brand_sent,
                is_substantive=is_substantive,
                is_pod_flagged=is_pod,
                processed_at=timezone.now(),
                created_at=created_date
            ))
            existing_ids.add(comment_id)
            
    if new_comments:
        Comment.objects.bulk_create(new_comments, ignore_conflicts=True)

    # 3. Update tracked post counts
    TrackedPost.objects.filter(pk=post.pk).update(
        sentiment_positive=pos_count,
        sentiment_neutral=neu_count,
        sentiment_negative=neg_count,
        brand_sentiment_pos=brand_pos_count,
        brand_sentiment_neg=brand_neg_count
    )

    logger.info(f"Analyzed {len(raw_comments)} comments for post {post.id}. POS: {pos_count}, NEG: {neg_count}")

    # 4. Re-calculate Centi Score
    from tasks.scoring_tasks import calculate_centi_score_task
    calculate_centi_score_task.delay(influencer.id)
    
    return True


@shared_task(queue='sentiment')
def analyze_organic_post_comments_task(organic_post_id):
    """
    Fetches comments for an organic benchmark post, runs VADER-first sentiment pipeline,
    extracts emotion categories, and saves comments as OrganicComment.
    """
    from apps.influencers.models import OrganicBenchmark
    from apps.sentiment.models import OrganicComment
    
    try:
        post = OrganicBenchmark.objects.get(pk=organic_post_id)
    except OrganicBenchmark.DoesNotExist:
        logger.error(f"OrganicBenchmark {organic_post_id} not found for comments analysis.")
        return False

    influencer = post.influencer
    
    # 1. Fetch comments from platform API
    parsed = IntegrationRouter.parse_url(post.post_url)
    if not parsed:
        return False

    platform = parsed['platform']
    raw_comments = []

    try:
        from apps.integrations.sociavault.client import sociavault_client
        from apps.influencers.models import ApiCostLog

        if platform == 'IG':
            resp = sociavault_client.get_instagram_comments(
                post.post_url,
                cost_category=ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS
            )
            if resp:
                d = resp.get('data') if isinstance(resp, dict) else resp
                raw = (d.get('comments') or d.get('edge_media_to_comment') or d) if isinstance(d, dict) else d
                raw_comments = [c for c in (raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])) if isinstance(c, dict)]
        elif platform == 'TT':
            resp = sociavault_client.get_tiktok_comments(
                post.post_url,
                cost_category=ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS
            )
            if resp:
                d = resp.get('data') if isinstance(resp, dict) else resp
                raw = (d.get('comments') or d.get('itemList') or d) if isinstance(d, dict) else d
                raw_comments = [c for c in (raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])) if isinstance(c, dict)]
        elif platform == 'X':
            resp = sociavault_client.get_twitter_comments(
                post.post_url,
                cost_category=ApiCostLog.CostCategories.SOCIAVAULT_COMMENTS
            )
            if resp:
                d = resp.get('data') if isinstance(resp, dict) else resp
                raw = (d.get('comments') or d.get('replies') or d.get('items') or d) if isinstance(d, dict) else d
                raw_comments = [c for c in (raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])) if isinstance(c, dict)]
    except Exception as e:
        logger.error(f"Error fetching organic comments via SociaVault for {post.post_url}: {str(e)}")
        raw_comments = []

    if not raw_comments:
        logger.info(f"No organic comments fetched for benchmark post {post.id}.")
        return True
        
    # Limit to max 50 comments per post
    if len(raw_comments) > 50:
        raw_comments = raw_comments[:50]

    # Initialize analyzer services
    analyzer = SentimentAnalyzer()
    emotion_classifier = EmotionClassifier()
    quality_classifier = CommentQualityClassifier()

    workspace = influencer.workspace if influencer else None
    from apps.sentiment.services.llm_service import LLMService
    llm_classifications = {}
    if workspace and workspace.use_llm_sentiment_analysis:
        comments_payload = [{'id': idx, 'text': c.get('text') or c.get('full_text') or ''} for idx, c in enumerate(raw_comments)]
        llm_classifications = LLMService.classify_comments_batch(comments_payload, workspace=workspace)

    pos_count = 0
    neu_count = 0
    neg_count = 0

    for idx, comment_data in enumerate(raw_comments):
        comment_id, author, text = extract_comment_author_and_text(comment_data, default_id=f"org_{post.id}_{idx}")
        
        # Parse timestamp
        timestamp_str = comment_data.get('timestamp') or comment_data.get('created_at')
        created_date = timezone.now()
        if timestamp_str:
            try:
                from dateutil.parser import parse as dateutil_parse
                created_date = dateutil_parse(timestamp_str)
                if timezone.is_naive(created_date):
                    created_date = timezone.make_aware(created_date, timezone=timezone.utc)
            except (ValueError, TypeError, ImportError):
                try:
                    from datetime import datetime as dt
                    created_date = dt.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    created_date = timezone.now()

        # Run NLP Pipelines: LLM if available, otherwise high-precision Lexicon + Pidgin
        llm_item = llm_classifications.get(idx)
        if llm_item:
            sentiment = llm_item['sentiment']
            emotion = llm_item['emotion']
        else:
            sentiment, _ = analyzer.analyze_comment(text)
            emotion = emotion_classifier.classify_emotion(text)

        if sentiment == 'POS':
            pos_count += 1
        elif sentiment == 'NEG':
            neg_count += 1
        else:
            neu_count += 1

        is_substantive = quality_classifier.is_substantive(text)
        is_pod = quality_classifier.is_pod_signature(text, author)

        # Save Comment
        OrganicComment.objects.update_or_create(
            organic_post=post,
            platform_comment_id=comment_id,
            defaults={
                'author_handle': author,
                'text': text,
                'sentiment': sentiment,
                'emotion_category': emotion,
                'is_substantive': is_substantive,
                'is_pod_flagged': is_pod,
                'processed_at': timezone.now(),
                'created_at': created_date
            }
        )

    post.sentiment_positive = pos_count
    post.sentiment_neutral = neu_count
    post.sentiment_negative = neg_count
    post.save(update_fields=['sentiment_positive', 'sentiment_neutral', 'sentiment_negative'])

    # Recalculate Senti Score
    if post.global_influencer_id:
        from apps.scoring.services.calculator import SentiScoreCalculator
        SentiScoreCalculator.calculate_global_influencer_senti_score(post.global_influencer_id)
    elif post.influencer_id:
        from tasks.scoring_tasks import calculate_centi_score_task
        calculate_centi_score_task.delay(post.influencer_id)

    logger.info(f"Analyzed {len(raw_comments)} organic comments for benchmark post {post.id}. POS: {pos_count}, NEG: {neg_count}")
    return True




