import math
from typing import Dict, Tuple, Any

class MetricsEngine:
    """
    Centralized formula engine implementing all calculations from the 
    Senti Score Algorithm v1.0 Developer Dictionary.
    All methods are purely static and side-effect free.
    """

    # --- 1. KPI DEFINITIONS: SENTIMENT ---

    @staticmethod
    def sentiment_share(positive: int, neutral: int, negative: int) -> Dict[str, float]:
        """
        Calculates sentiment share percentages that always sum to 100%.
        Returns float percentages rounded to 2 decimal places.
        """
        total = positive + neutral + negative
        if total <= 0:
            return {"positive_pct": 0.0, "neutral_pct": 0.0, "negative_pct": 0.0, "total": 0}
        
        pos_pct = round((positive / total) * 100.0, 2)
        neg_pct = round((negative / total) * 100.0, 2)
        neu_pct = round((neutral / total) * 100.0, 2)
        
        return {
            "positive_pct": pos_pct,
            "neutral_pct": neu_pct,
            "negative_pct": neg_pct,
            "total": total
        }

    @staticmethod
    def net_sentiment(positive: float, negative: float) -> float:
        """
        Calculates Net Sentiment Score: ((Positive - Negative) / (Positive + Negative)) * 100.
        Neutral comments are excluded entirely. Works with raw counts or percentages.
        """
        denom = positive + negative
        if denom <= 0:
            return 0.0
        val = ((positive - negative) / denom) * 100.0
        return round(val, 2)

    # --- 2. KPI DEFINITIONS: ENGAGEMENT, REACH & VIEWS ---

    @staticmethod
    def engagement_total(likes: int = 0, comments: int = 0, shares: int = 0, saves: int = 0, reposts: int = 0) -> int:
        """
        Total interactions: likes + comments + shares + saves + reposts.
        """
        return int((likes or 0) + (comments or 0) + (shares or 0) + (saves or 0) + (reposts or 0))

    @staticmethod
    def er_audience_quality(engagement: float, followers_or_reach: float) -> float:
        """
        ER (Audience Quality) = (Engagement / Followers or Reach) * 100
        """
        if not followers_or_reach or followers_or_reach <= 0:
            return 0.0
        return round((engagement / followers_or_reach) * 100.0, 4)

    @staticmethod
    def aar(avg_views: float, followers: float) -> float:
        """
        AAR (Audience Activity Rate) = min(100, (Views / Followers) * 100)
        What % of followers are actually watching content. Capped at 100%.
        """
        if not followers or followers <= 0:
            return 0.0
        val = (avg_views / followers) * 100.0
        return round(min(100.0, max(0.0, val)), 2)

    @staticmethod
    def cr(engagement: float, views: float) -> float:
        """
        CR (Content Resonance) = (Engagement / Views) * 100
        Of those who watched, what % found it valuable enough to engage.
        """
        if not views or views <= 0:
            return 0.0
        return round((engagement / views) * 100.0, 4)

    @staticmethod
    def resonance_efficiency(aar_val: float, cr_val: float) -> float:
        """
        RE (Resonance Efficiency) = sqrt(AAR * CR)
        Geometric mean of AAR and CR.
        """
        if aar_val <= 0 or cr_val <= 0:
            return 0.0
        return round(math.sqrt(aar_val * cr_val), 2)

    # --- 3. THE 4 SENTI SCORE COMPONENTS ---

    @staticmethod
    def c1_net_sentiment(pos_count: int, neg_count: int) -> Dict[str, Any]:
        """
        Component 1: Net Sentiment (30% weight).
        Normalised score measuring directional sentiment balance, excluding neutrals.
        """
        raw_val = MetricsEngine.net_sentiment(pos_count, neg_count)
        score = int(min(100, max(0, round(raw_val))))
        
        if raw_val >= 85.0:
            grade = "Excellent"
        elif raw_val >= 70.0:
            grade = "Strong"
        elif raw_val >= 55.0:
            grade = "Good"
        elif raw_val >= 35.0:
            grade = "Average"
        elif raw_val >= 20.0:
            grade = "Below average"
        else:
            grade = "Poor"
            
        return {
            "raw_value": raw_val,
            "score": score,
            "grade": grade,
            "weight": 0.30
        }

    @staticmethod
    def c2_resonance_efficiency(avg_views: float, followers: float, avg_engagement: float) -> Dict[str, Any]:
        """
        Component 2: Resonance Efficiency (30% weight).
        Geometric mean of AAR and CR across last 10 posts.
        """
        aar_val = MetricsEngine.aar(avg_views, followers)
        cr_val = MetricsEngine.cr(avg_engagement, avg_views)
        re_val = MetricsEngine.resonance_efficiency(aar_val, cr_val)
        
        if re_val > 35.0:
            grade = "Excellent"
            score = 100
        elif re_val >= 25.0:
            grade = "Very good"
            score = 80
        elif re_val >= 15.0:
            grade = "Good"
            score = 60
        elif re_val >= 8.0:
            grade = "Average"
            score = 40
        else:
            grade = "Poor"
            score = 20
            
        return {
            "aar": aar_val,
            "cr": cr_val,
            "re": re_val,
            "raw_value": re_val,
            "score": score,
            "grade": grade,
            "weight": 0.30
        }

    @staticmethod
    def c3_comment_quality(substantive_comments: int, total_comments: int) -> Dict[str, Any]:
        """
        Component 3: Comment Quality (20% weight).
        Ratio of substantive comments to total comments across last 10 posts.
        Formula: min(100, max(0, Ratio * 1.4))
        """
        if total_comments <= 0:
            ratio = 0.0
            score = 0
        else:
            ratio = round((substantive_comments / total_comments) * 100.0, 2)
            score = int(min(100, max(0, round(ratio * 1.4))))
            
        if ratio > 60.0:
            grade = "Excellent"
        elif ratio >= 40.0:
            grade = "Good"
        elif ratio >= 20.0:
            grade = "Average"
        elif ratio >= 10.0:
            grade = "Below average"
        else:
            grade = "Poor"
            
        return {
            "substantive_count": substantive_comments,
            "total_comments": total_comments,
            "ratio": ratio,
            "raw_value": ratio,
            "score": score,
            "grade": grade,
            "weight": 0.20
        }

    @staticmethod
    def c4_posting_consistency(posts_in_last_30_days: int) -> Dict[str, Any]:
        """
        Component 4: Posting Consistency (20% weight).
        Mean gap = 30 / Total posts in last 30 days.
        Fewer than 2 posts in 30 days: default C4 = 10.
        """
        count = max(0, int(posts_in_last_30_days or 0))
        if count < 2:
            mean_gap = 30.0 if count == 1 else 30.0
            score = 10
            grade = "Rarely posts"
        else:
            mean_gap = round(30.0 / count, 2)
            if mean_gap <= 2.0:
                score = 100
                grade = "Posts almost daily"
            elif mean_gap <= 4.0:
                score = 80
                grade = "Posts every few days"
            elif mean_gap <= 7.0:
                score = 60
                grade = "Posts weekly"
            elif mean_gap <= 14.0:
                score = 35
                grade = "Posts fortnightly"
            else:
                score = 10
                grade = "Rarely posts"
                
        return {
            "posts_in_30d": count,
            "mean_gap": mean_gap,
            "raw_value": mean_gap,
            "score": score,
            "grade": grade,
            "weight": 0.20
        }

    @staticmethod
    def calculate_senti_score(c1_score: int, c2_score: int, c3_score: int, c4_score: int) -> Dict[str, Any]:
        """
        Final Senti Score calculation from component scores:
        Senti Score = (C1 x 0.30) + (C2 x 0.30) + (C3 x 0.20) + (C4 x 0.20)
        Round to nearest integer. Cap at 100, floor at 0.
        """
        weighted_sum = (c1_score * 0.30) + (c2_score * 0.30) + (c3_score * 0.20) + (c4_score * 0.20)
        final_score = int(min(100, max(0, round(weighted_sum))))
        
        if final_score >= 90:
            label = "ELITE"
            display_label = "Elite"
            guidance = "Top performers. Prioritise for all major campaigns."
        elif final_score >= 75:
            label = "STRONG"
            display_label = "Strong"
            guidance = "Reliable choice. Good for most campaign goals."
        elif final_score >= 60:
            label = "AVERAGE"
            display_label = "Average"
            guidance = "Acceptable. Monitor sentiment and RE closely."
        elif final_score >= 40:
            label = "BELOW_AVG"
            display_label = "Below average"
            guidance = "Activate with caution. Investigate weak components."
        else:
            label = "POOR"
            display_label = "Poor"
            guidance = "Do not activate. Flag for review or removal."
            
        return {
            "senti_score": final_score,
            "senti_label": label,
            "display_label": display_label,
            "activation_guidance": guidance,
            "weighted_sum": round(weighted_sum, 2)
        }
