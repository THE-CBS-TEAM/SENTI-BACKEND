import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Q, Count
from apps.influencers.models import Influencer, PlatformMetrics, OrganicBenchmark
from apps.scoring.models import CentiScoreHistory, SentiScoreHistory
from apps.scoring.services.metrics_engine import MetricsEngine

logger = logging.getLogger(__name__)


class SentiScoreCalculator:
    """
    Core scoring service that computes the proprietary 0-100 Senti Score
    for every profiled influencer using the 4-component weighted model from MetricsEngine.
    """
    @classmethod
    def calculate_senti_score(cls, influencer_id: int) -> int:
        try:
            influencer = Influencer.objects.get(pk=influencer_id)
        except Influencer.DoesNotExist:
            logger.error(f"Influencer {influencer_id} not found for Senti Score calculation.")
            return 0

        # If influencer is linked to a GlobalInfluencer, delegate to global scoring
        if influencer.global_influencer:
            global_score = cls.calculate_global_influencer_senti_score(influencer.global_influencer_id)
            influencer.refresh_from_db()
            return global_score

        metrics_list = PlatformMetrics.objects.filter(influencer=influencer)
        total_followers = sum(m.followers for m in metrics_list)

        if not metrics_list.exists() or total_followers == 0:
            # No real data pull yet, initialize to 0 / POOR
            influencer.senti_score = 0
            influencer.senti_label = 'POOR'
            influencer.centi_score = 0
            influencer.sentiment_rating = 'NEUTRAL'
            influencer.save()
            return 0

        # --- 1. C1 Net Sentiment (30% weight) ---
        from apps.campaigns.models import TrackedPost
        from apps.sentiment.models import Comment

        tracked_posts = TrackedPost.objects.filter(campaign_inf__influencer=influencer).order_by('-published_at', '-created_at')[:10]
        
        pos_total = 0
        neg_total = 0
        if tracked_posts.exists():
            post_ids = [p.id for p in tracked_posts]
            pos_total = TrackedPost.objects.filter(id__in=post_ids).aggregate(total=Sum('sentiment_positive'))['total'] or 0
            neg_total = TrackedPost.objects.filter(id__in=post_ids).aggregate(total=Sum('sentiment_negative'))['total'] or 0

        if pos_total + neg_total == 0:
            # Check comment model directly if tracked post counts weren't aggregated
            pos_total = Comment.objects.filter(tracked_post__campaign_inf__influencer=influencer, sentiment='POS').count()
            neg_total = Comment.objects.filter(tracked_post__campaign_inf__influencer=influencer, sentiment='NEG').count()

        if pos_total + neg_total > 0:
            c1_result = MetricsEngine.c1_net_sentiment(pos_total, neg_total)
        else:
            # Default strong baseline if no comments scraped yet
            c1_result = {"raw_value": 0.0, "score": 0, "grade": "No Data", "weight": 0.30}

        # --- 2. C2 Resonance Efficiency (30% weight) ---
        # Update each PlatformMetrics record with AAR, CR, RE and aggregate overall totals
        total_views = 0
        total_eng = 0
        
        for p_metric in metrics_list:
            p_eng = MetricsEngine.engagement_total(
                p_metric.avg_likes, p_metric.avg_comments, 
                p_metric.avg_shares, p_metric.avg_saves, p_metric.avg_reposts
            )
            p_c2 = MetricsEngine.c2_resonance_efficiency(p_metric.avg_views, p_metric.followers, p_eng)
            
            # Save calculated per-platform KPI metrics
            p_metric.aar = p_c2["aar"]
            p_metric.cr = p_c2["cr"]
            p_metric.resonance_efficiency = p_c2["re"]
            p_metric.save()

            total_views += p_metric.avg_views
            total_eng += p_eng

        # Calculate combined C2 across all platforms
        c2_result = MetricsEngine.c2_resonance_efficiency(total_views, total_followers, total_eng)

        # --- 3. C3 Comment Quality (20% weight) ---
        total_comments_count = Comment.objects.filter(tracked_post__campaign_inf__influencer=influencer).count()
        if total_comments_count > 0:
            substantive_count = Comment.objects.filter(
                tracked_post__campaign_inf__influencer=influencer, 
                is_substantive=True, 
                is_pod_flagged=False
            ).count()
            c3_result = MetricsEngine.c3_comment_quality(substantive_count, total_comments_count)
        else:
            # Default to Good baseline if no individual comments stored yet
            c3_result = {"substantive_count": 0, "total_comments": 0, "ratio": 0.0, "score": 0, "grade": "No Data", "weight": 0.20}

        # --- 4. C4 Posting Consistency (20% weight) ---
        thirty_days_ago = timezone.now() - timedelta(days=30)
        recent_benchmarks = OrganicBenchmark.objects.filter(
            influencer=influencer, 
            post_created_at__gte=thirty_days_ago
        ).count()
        recent_tracked = TrackedPost.objects.filter(
            campaign_inf__influencer=influencer, 
            published_at__gte=thirty_days_ago
        ).count()
        
        # Take the maximum volume across organic vs tracked samples in last 30d
        total_recent_posts = max(recent_benchmarks, recent_tracked)
        
        # If no dates recorded on posts, estimate from benchmark volume if present
        if total_recent_posts == 0 and OrganicBenchmark.objects.filter(influencer=influencer).exists():
            total_recent_posts = min(10, OrganicBenchmark.objects.filter(influencer=influencer).count())

        c4_result = MetricsEngine.c4_posting_consistency(total_recent_posts)

        # --- 5. Calculate Final Score & Save History ---
        final_result = MetricsEngine.calculate_senti_score(
            c1_result["score"], c2_result["score"], c3_result["score"], c4_result["score"]
        )
        senti_score = final_result["senti_score"]
        senti_label = final_result["senti_label"]

        components_payload = {
            "c1_net_sentiment": c1_result,
            "c2_resonance_efficiency": c2_result,
            "c3_comment_quality": c3_result,
            "c4_posting_consistency": c4_result,
            "guidance": final_result["activation_guidance"],
            "display_label": final_result["display_label"]
        }

        # Record in SentiScoreHistory
        SentiScoreHistory.objects.create(
            influencer=influencer,
            score=senti_score,
            senti_label=senti_label,
            components=components_payload
        )

        # Also log to legacy CentiScoreHistory for backwards compat during migration
        CentiScoreHistory.objects.create(
            influencer=influencer,
            score=senti_score,
            components=components_payload
        )

        # Update Influencer model
        influencer.senti_score = senti_score
        influencer.senti_label = senti_label
        influencer.centi_score = senti_score  # Mirror to legacy field
        
        if senti_score >= 70:
            influencer.sentiment_rating = 'POSITIVE'
        elif senti_score >= 50:
            influencer.sentiment_rating = 'NEUTRAL'
        else:
            influencer.sentiment_rating = 'NEGATIVE'

        influencer.save()

        logger.info(f"Calculated Senti Score for {influencer.display_name}: {senti_score} ({senti_label})")
        return senti_score

    @classmethod
    def calculate_global_influencer_senti_score(cls, global_influencer_id: int) -> int:
        from apps.influencers.models import GlobalInfluencer, PlatformMetrics, OrganicBenchmark
        try:
            global_inf = GlobalInfluencer.objects.get(pk=global_influencer_id)
        except GlobalInfluencer.DoesNotExist:
            logger.error(f"GlobalInfluencer {global_influencer_id} not found for Senti Score calculation.")
            return 0

        metrics_list = PlatformMetrics.objects.filter(global_influencer=global_inf)
        total_followers = sum(m.followers for m in metrics_list)

        if not metrics_list.exists() or total_followers == 0:
            global_inf.senti_score = 0
            global_inf.senti_label = 'POOR'
            global_inf.save(update_fields=['senti_score', 'senti_label'])
            return 0

        # C1 Net Sentiment (using organic benchmark comments if available)
        pos_total = 0
        neg_total = 0
        for b in OrganicBenchmark.objects.filter(global_influencer=global_inf):
            pos_total += b.sentiment_positive or 0
            neg_total += b.sentiment_negative or 0

        # Also aggregate directly from OrganicComment
        from apps.sentiment.models import OrganicComment
        org_pos = OrganicComment.objects.filter(organic_post__global_influencer=global_inf, sentiment='POS').count()
        org_neg = OrganicComment.objects.filter(organic_post__global_influencer=global_inf, sentiment='NEG').count()
        pos_total = max(pos_total, org_pos)
        neg_total = max(neg_total, org_neg)

        if pos_total + neg_total > 0:
            c1_result = MetricsEngine.c1_net_sentiment(pos_total, neg_total)
        else:
            # Analyze sentiment of available benchmark post captions if comments not yet scraped
            from apps.sentiment.services.analyzer import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            bench_texts = [b.post_text for b in OrganicBenchmark.objects.filter(global_influencer=global_inf) if b.post_text]
            if bench_texts:
                cap_pos = 0
                cap_neg = 0
                for txt in bench_texts:
                    sent, _ = analyzer.analyze_comment(txt)
                    if sent == 'POS':
                        cap_pos += 1
                    elif sent == 'NEG':
                        cap_neg += 1
                if cap_pos + cap_neg > 0:
                    c1_result = MetricsEngine.c1_net_sentiment(cap_pos, cap_neg)
                    c1_result["grade"] = "Post Caption Sentiment"
                else:
                    c1_result = {"raw_value": 0.0, "score": 65, "grade": "Neutral Baseline", "weight": 0.30}
            else:
                c1_result = {"raw_value": 0.0, "score": 65, "grade": "Baseline", "weight": 0.30}

        # C2 Resonance Efficiency
        total_views = 0
        total_eng = 0
        for p_metric in metrics_list:
            p_eng = MetricsEngine.engagement_total(
                p_metric.avg_likes, p_metric.avg_comments,
                p_metric.avg_shares, p_metric.avg_saves, p_metric.avg_reposts
            )
            p_c2 = MetricsEngine.c2_resonance_efficiency(p_metric.avg_views, p_metric.followers, p_eng)
            p_metric.aar = p_c2["aar"]
            p_metric.cr = p_c2["cr"]
            p_metric.resonance_efficiency = p_c2["re"]
            p_metric.save(update_fields=['aar', 'cr', 'resonance_efficiency'])
            total_views += p_metric.avg_views
            total_eng += p_eng

        c2_result = MetricsEngine.c2_resonance_efficiency(total_views, total_followers, total_eng)

        # C3 Comment Quality
        total_comments = OrganicComment.objects.filter(organic_post__global_influencer=global_inf).count()
        if total_comments > 0:
            substantive_count = OrganicComment.objects.filter(
                organic_post__global_influencer=global_inf,
                is_substantive=True,
                is_pod_flagged=False
            ).count()
            c3_result = MetricsEngine.c3_comment_quality(substantive_count, total_comments)
        else:
            # Estimate from healthy Comment Ratio (CR) across platforms
            valid_cr = [m.cr for m in metrics_list if m.cr and m.cr > 0]
            if valid_cr:
                mean_cr = sum(valid_cr) / len(valid_cr)
                est_score = 80 if mean_cr >= 8.0 else (60 if mean_cr >= 3.0 else 40)
                grade = 'Good Ratio' if est_score >= 80 else ('Average Ratio' if est_score >= 60 else 'Low Ratio')
                c3_result = {
                    "substantive_count": 0,
                    "total_comments": 0,
                    "ratio": round(mean_cr, 2),
                    "score": est_score,
                    "grade": f"Estimated ({grade})",
                    "weight": 0.20
                }
            else:
                c3_result = {"substantive_count": 0, "total_comments": 0, "ratio": 0.0, "score": 60, "grade": "Estimated", "weight": 0.20}

        # C4 Posting Consistency
        thirty_days_ago = timezone.now() - timedelta(days=30)
        recent_count = OrganicBenchmark.objects.filter(
            global_influencer=global_inf,
            post_created_at__gte=thirty_days_ago
        ).count()
        if recent_count == 0:
            recent_count = min(10, OrganicBenchmark.objects.filter(global_influencer=global_inf).count())
        c4_result = MetricsEngine.c4_posting_consistency(recent_count)

        final_result = MetricsEngine.calculate_senti_score(
            c1_result["score"], c2_result["score"], c3_result["score"], c4_result["score"]
        )
        senti_score = final_result["senti_score"]
        senti_label = final_result["senti_label"]

        global_inf.senti_score = senti_score
        global_inf.senti_label = senti_label
        global_inf.centi_score = senti_score
        global_inf.consistency_score = c4_result.get("score", 0)
        global_inf.reach_score = min(100, int(total_followers / 10000))
        global_inf.save()

        components_payload = {
            "c1_net_sentiment": c1_result,
            "c2_resonance_efficiency": c2_result,
            "c3_comment_quality": c3_result,
            "c4_posting_consistency": c4_result,
            "guidance": final_result["activation_guidance"],
            "display_label": final_result["display_label"]
        }

        # Update linked legacy Influencer records and save history rows
        from apps.influencers.models import Influencer
        linked_infs = Influencer.objects.filter(global_influencer=global_inf)
        rating = 'POSITIVE' if senti_score >= 70 else ('NEUTRAL' if senti_score >= 50 else 'NEGATIVE')
        linked_infs.update(
            senti_score=senti_score,
            senti_label=senti_label,
            centi_score=senti_score,
            sentiment_rating=rating,
            consistency_score=global_inf.consistency_score,
            reach_score=global_inf.reach_score,
        )

        for inf in linked_infs:
            SentiScoreHistory.objects.create(
                influencer=inf,
                score=senti_score,
                senti_label=senti_label,
                components=components_payload
            )
            CentiScoreHistory.objects.create(
                influencer=inf,
                score=senti_score,
                components=components_payload
            )

        # Trigger FakeFollowerDetector to keep audience authenticity in sync
        try:
            from apps.scoring.services.fake_follower import FakeFollowerDetector
            FakeFollowerDetector.analyze_authenticity_for_global(global_inf.id)
        except Exception as auth_err:
            logger.warning(f"Error updating authenticity for GlobalInfluencer {global_inf.id}: {auth_err}")

        logger.info(f"Calculated Senti Score for GlobalInfluencer {global_inf.display_name}: {senti_score} ({senti_label})")
        return senti_score


class CentiScoreCalculator:
    """
    Legacy backwards compatibility wrapper. Redirects all score calculation 
    to the new SentiScoreCalculator.
    """
    @classmethod
    def calculate_centi_score(cls, influencer_id: int) -> int:
        return SentiScoreCalculator.calculate_senti_score(influencer_id)
