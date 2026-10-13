import logging
from django.db.models import Avg, Sum
from apps.influencers.models import OrganicBenchmark, PlatformMetrics

logger = logging.getLogger(__name__)


class BenchmarkEngine:
    @classmethod
    def calculate_platform_benchmarks(cls, influencer, platform):
        """
        Calculates and returns the baseline average metrics (views, likes, comments, engagement)
        for an influencer's organic posts.
        """
        posts = OrganicBenchmark.objects.filter(influencer=influencer, platform=platform)
        count = posts.count()

        if count == 0:
            return {
                'avg_views': 0,
                'avg_likes': 0,
                'avg_comments': 0,
                'avg_shares': 0,
                'avg_engagement_total': 0.0,
                'posts_count': 0
            }

        aggregates = posts.aggregate(
            avg_views=Avg('views'),
            avg_likes=Avg('likes'),
            avg_comments=Avg('comments_count'),
            avg_shares=Avg('shares'),
            avg_saves=Avg('saves'),
            avg_reposts=Avg('reposts'),
            avg_eng=Avg('engagement_total')
        )

        return {
            'avg_views': round(aggregates['avg_views'] or 0),
            'avg_likes': round(aggregates['avg_likes'] or 0),
            'avg_comments': round(aggregates['avg_comments'] or 0),
            'avg_shares': round(aggregates['avg_shares'] or 0),
            'avg_saves': round(aggregates['avg_saves'] or 0),
            'avg_reposts': round(aggregates['avg_reposts'] or 0),
            'avg_engagement_total': round(aggregates['avg_eng'] or 0.0, 2),
            'posts_count': count
        }

    @classmethod
    def compare_post_to_benchmark(cls, tracked_post):
        """
        Compares a tracked campaign post's metrics to the creator's organic benchmark for that platform.
        Returns percentage differences and raw comments from both sponsored and organic baseline posts.
        """
        influencer = tracked_post.campaign_inf.influencer
        platform = tracked_post.platform

        benchmarks = cls.calculate_platform_benchmarks(influencer, platform)

        # Engagement total for tracked post = likes + comments + shares + saves
        tracked_engagement = (
            tracked_post.likes +
            tracked_post.comments_count +
            tracked_post.shares +
            tracked_post.saves
        )

        def pct_diff(actual, baseline):
            if not baseline:
                return 100.0 if actual > 0 else 0.0
            return round(((actual - baseline) / baseline) * 100, 2)

        # 1. Fetch live sponsored post comments from database
        from apps.sentiment.models import Comment
        sponsored_comments = Comment.objects.filter(tracked_post=tracked_post).order_by('-created_at')[:10]
        sponsored_data = []
        for c in sponsored_comments:
            sponsored_data.append({
                'author_handle': c.author_handle,
                'text': c.text,
                'sentiment': c.sentiment,
                'emotion_category': c.emotion_category,
                'created_at': c.created_at.isoformat() if c.created_at else None
            })

        # 2. Extract organic comments from recent benchmark posts raw API response
        organic_data = []
        platform_metrics = PlatformMetrics.objects.filter(influencer=influencer, platform=platform).first()
        if platform_metrics and platform_metrics.raw_api_response:
            raw_posts = platform_metrics.raw_api_response
            if isinstance(raw_posts, list):
                for p in raw_posts:
                    latest_comments = p.get('latestComments', []) or p.get('comments', [])
                    for c_item in latest_comments:
                        text = c_item.get('text') or c_item.get('string') or ''
                        author = c_item.get('ownerUsername') or c_item.get('author', {}).get('uniqueId') or 'anonymous'
                        if text:
                            # Extract timestamp
                            c_time = (
                                c_item.get('createdTime') or
                                c_item.get('createTime') or
                                c_item.get('timestamp') or
                                c_item.get('created_at')
                            )
                            c_date_str = None
                            if c_time:
                                try:
                                    if isinstance(c_time, (int, float)):
                                        from django.utils.timezone import make_aware
                                        from datetime import datetime
                                        c_date_str = make_aware(datetime.fromtimestamp(c_time)).isoformat()
                                    else:
                                        c_date_str = str(c_time)
                                except Exception:
                                    c_date_str = str(c_time)

                            # Apply simple VADER heuristic for label
                            text_lower = text.lower()
                            pos_words = ['love', 'good', 'great', 'awesome', 'nice', 'yes', 'amazing', 'happy', 'excited', 'crushing', 'best']
                            neg_words = ['bad', 'hate', 'worse', 'sad', 'angry', 'no', 'disappointed', 'terrible', 'worst', 'expensive', 'latency']
                            pos_count = sum(1 for w in pos_words if w in text_lower)
                            neg_count = sum(1 for w in neg_words if w in text_lower)
                            sentiment = 'NEU'
                            if pos_count > neg_count:
                                sentiment = 'POS'
                            elif neg_count > pos_count:
                                sentiment = 'NEG'

                            organic_data.append({
                                'author_handle': author,
                                'text': text,
                                'sentiment': sentiment,
                                'created_at': c_date_str
                            })
                            if len(organic_data) >= 10:
                                break
                    if len(organic_data) >= 10:
                        break

        # Calculate Campaign CR vs Benchmark CR per Senti Score specs
        benchmark_cr = 0.0
        if benchmarks['avg_views'] > 0:
            benchmark_cr = round((benchmarks['avg_engagement_total'] / benchmarks['avg_views']) * 100.0, 4)
        
        campaign_cr = 0.0
        if tracked_post.views > 0:
            campaign_cr = round((tracked_engagement / tracked_post.views) * 100.0, 4)

        # Calculate Resonance Efficiency of sponsored vs organic baseline
        import math
        followers = platform_metrics.followers if platform_metrics else 0
        
        sponsored_aar = min(100.0, (tracked_post.views / followers) * 100.0) if followers > 0 else 0.0
        sponsored_re = math.sqrt(sponsored_aar * campaign_cr) if (sponsored_aar > 0 and campaign_cr > 0) else 0.0

        organic_aar = min(100.0, (benchmarks['avg_views'] / followers) * 100.0) if followers > 0 else 0.0
        organic_re = math.sqrt(organic_aar * benchmark_cr) if (organic_aar > 0 and benchmark_cr > 0) else 0.0

        resonance_efficiency = round((sponsored_re / organic_re) * 100.0, 1) if organic_re > 0 else (100.0 if sponsored_re > 0 else 0.0)

        return {
            'views_diff_pct': pct_diff(tracked_post.views, benchmarks['avg_views']),
            'likes_diff_pct': pct_diff(tracked_post.likes, benchmarks['avg_likes']),
            'comments_diff_pct': pct_diff(tracked_post.comments_count, benchmarks['avg_comments']),
            'engagement_diff_pct': pct_diff(tracked_engagement, benchmarks['avg_engagement_total']),
            'campaign_cr': campaign_cr,
            'benchmark_cr': benchmark_cr,
            'cr_diff_pct': pct_diff(campaign_cr, benchmark_cr),
            'resonance_efficiency': resonance_efficiency,
            'sponsored_views': tracked_post.views,
            'organic_avg_views': benchmarks['avg_views'],
            'sponsored_eng_rate': campaign_cr,
            'organic_eng_rate': benchmark_cr,
            'benchmarks': benchmarks,
            'sponsored_comments': sponsored_data,
            'organic_comments': organic_data
        }

