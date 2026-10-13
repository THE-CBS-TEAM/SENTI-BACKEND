import math
from typing import Dict, Any, List

class StandaloneScoringEngine:
    @staticmethod
    def calculate_fake_follower_score(metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assesses audience authenticity and fake follower risk based on ER and engagement ratios.
        """
        followers = metrics.get("followers", 0)
        er = metrics.get("engagement_rate", 0.0)
        avg_likes = metrics.get("avg_likes", 0)
        avg_comments = metrics.get("avg_comments", 0)

        # Baseline expected ER
        if followers < 10000:
            expected_er = 0.05
        elif followers < 100000:
            expected_er = 0.03
        else:
            expected_er = 0.015

        # Check comment to like ratio (healthy is 1:20 to 1:50)
        comment_ratio = avg_comments / (avg_likes or 1)
        risk_flags = []

        if er < (expected_er * 0.2):
            risk_flags.append({
                "severity": "CRITICAL",
                "code": "ABNORMALLY_LOW_ENGAGEMENT",
                "message": f"Engagement rate ({er:.2%}) is significantly lower than peer average ({expected_er:.2%})"
            })
        elif er > (expected_er * 4.0):
            risk_flags.append({
                "severity": "WARNING",
                "code": "SUSPICIOUS_ENGAGEMENT_SPIKE",
                "message": f"Engagement rate ({er:.2%}) is unusually elevated."
            })

        if comment_ratio < 0.005 and avg_likes > 500:
            risk_flags.append({
                "severity": "WARNING",
                "code": "LOW_COMMENT_TO_LIKE_RATIO",
                "message": "High like volume with disproportionately low comment count suggests bot likes."
            })

        # Score from 0 to 100 where 100 = 100% authentic
        penalty = len([f for f in risk_flags if f["severity"] == "CRITICAL"]) * 35
        penalty += len([f for f in risk_flags if f["severity"] == "WARNING"]) * 15
        authenticity_score = max(10, min(98, 95 - penalty))

        return {
            "authenticity_score": authenticity_score,
            "fake_follower_risk_score": 100 - authenticity_score,
            "confidence": "HIGH" if followers > 5000 else "MEDIUM",
            "risk_flags": risk_flags
        }

    @classmethod
    def calculate_centi_score(cls, platform_metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Computes composite Senti/Centi score across platforms.
        Weights:
        - Authenticity / Real Follower weight: 35%
        - Engagement Consistency weight: 35%
        - Reach / Volume weight: 30%
        """
        if not platform_metrics:
            return {
                "centi_score": 50,
                "label": "NEUTRAL",
                "grade": "C",
                "components": {}
            }

        total_followers = sum(m.get("followers", 0) for m in platform_metrics)
        avg_er = sum(m.get("engagement_rate", 0) for m in platform_metrics) / len(platform_metrics)

        primary_metrics = platform_metrics[0]
        auth_res = cls.calculate_fake_follower_score(primary_metrics)
        auth_score = auth_res["authenticity_score"]

        # Consistency / Engagement score (0-100)
        er_score = min(100, int((avg_er / 0.05) * 80))

        # Reach score logarithmic scale
        reach_score = min(100, int(math.log10(max(1, total_followers)) * 18))

        # Weighted Centi Score
        composite = int((auth_score * 0.35) + (er_score * 0.35) + (reach_score * 0.30))
        composite = max(10, min(99, composite))

        if composite >= 85:
            grade = "A+"
            label = "EXCEPTIONAL"
        elif composite >= 75:
            grade = "A"
            label = "HIGH_PERFORMER"
        elif composite >= 60:
            grade = "B"
            label = "AVERAGE"
        elif composite >= 40:
            grade = "C"
            label = "BELOW_AVERAGE"
        else:
            grade = "D"
            label = "HIGH_RISK"

        return {
            "centi_score": composite,
            "grade": grade,
            "label": label,
            "total_followers": total_followers,
            "average_engagement_rate": round(avg_er, 4),
            "components": {
                "authenticity_score": auth_score,
                "engagement_score": er_score,
                "reach_score": reach_score
            },
            "risk_flags": auth_res["risk_flags"]
        }

scoring_engine = StandaloneScoringEngine()
