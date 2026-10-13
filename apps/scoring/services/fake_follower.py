import math
from django.db.models import Avg, Sum, Q
from apps.influencers.models import Influencer, PlatformMetrics, OrganicBenchmark
from apps.sentiment.models import Comment, OrganicComment
from apps.scoring.models import AuthenticityScoreHistory


class FakeFollowerDetector:
    @classmethod
    def analyze_authenticity_for_global(cls, global_influencer_id):
        """
        Runs authenticity audit for all workspace instances of a GlobalInfluencer.
        """
        from apps.influencers.models import GlobalInfluencer, Influencer
        try:
            gi = GlobalInfluencer.objects.get(id=global_influencer_id)
        except GlobalInfluencer.DoesNotExist:
            return None

        infs = list(Influencer.objects.filter(global_influencer=gi))
        res = None
        for inf in infs:
            res = cls.analyze_authenticity(inf.id)
        return res

    @classmethod
    def analyze_authenticity(cls, influencer_id):
        try:
            influencer = Influencer.objects.get(id=influencer_id)
        except Influencer.DoesNotExist:
            return None

        if influencer.global_influencer:
            metrics = list(PlatformMetrics.objects.filter(
                Q(influencer=influencer) | Q(global_influencer=influencer.global_influencer)
            ).distinct())
        else:
            metrics = list(PlatformMetrics.objects.filter(influencer=influencer))

        signal_scores = {
            'S1': {'score': 50, 'weight': 0.25, 'label': 'Engagement Rate Anomaly', 'detail': 'No Data', 'grade': 'N/A'},
            'S2': {'score': 50, 'weight': 0.20, 'label': 'Likes-to-Comments Ratio', 'detail': 'No Data', 'grade': 'N/A'},
            'S3': {'score': 50, 'weight': 0.25, 'label': 'Comment Quality Signal', 'detail': 'No Data', 'grade': 'N/A'},
            'S4': {'score': 50, 'weight': 0.15, 'label': 'Views-to-Followers Ratio', 'detail': 'No Data', 'grade': 'N/A'},
            'S5': {'score': 50, 'weight': 0.15, 'label': 'Engagement Consistency', 'detail': 'Insufficient Data', 'grade': 'N/A'},
        }

        s1_scores = []
        s2_scores = []
        s4_scores = []

        platform_scores_dict = {}
        risk_flags = []

        # Process S1, S2, S4 per platform
        for m in metrics:
            plat = m.platform

            # S1: Engagement Rate Anomaly
            er = m.engagement_rate
            followers = m.followers
            s1_score = 50
            if plat in ['IG', 'INSTAGRAM']:
                healthy = (1.0, 5.0)
                susp_low = 0.5
                susp_high = 12.0
            elif plat in ['TT', 'TIKTOK']:
                healthy = (3.0, 10.0)
                susp_low = 1.0
                susp_high = 20.0
            else:  # X
                healthy = (0.3, 2.0)
                susp_low = 0.1
                susp_high = 8.0

            if healthy[0] <= er <= healthy[1]:
                s1_score = 95
            elif (susp_low <= er < healthy[0]) or (healthy[1] < er <= susp_high):
                s1_score = 70
            else:
                if followers > 10000 and er < susp_low:
                    s1_score = 25
                    risk_flags.append({'severity': 'CRITICAL', 'code': 'ER_CRITICALLY_LOW', 'message': f'{plat} ER critically low for audience size', 'platform': plat})
                else:
                    if followers > 10000 or er > susp_high:
                        s1_score = 25
                    else:
                        s1_score = 70
            s1_scores.append(s1_score)

            # S2: Likes-to-Comments Ratio
            likes = m.avg_likes
            comments = m.avg_comments
            s2_score = 50
            lcr = 9999
            if comments > 0:
                lcr = likes / comments

            if 5 <= lcr <= 100:
                s2_score = 95
            elif 100 < lcr <= 200:
                s2_score = 75
            elif 200 < lcr <= 500:
                s2_score = 40
                risk_flags.append({'severity': 'WARNING', 'code': 'LCR_HIGH', 'message': f'{plat} LCR suspicious', 'platform': plat})
            elif lcr > 500 or lcr == 9999:
                s2_score = 10
            elif lcr < 2 and comments > 10:
                s2_score = 40
                risk_flags.append({'severity': 'WARNING', 'code': 'LCR_TOO_LOW', 'message': f'{plat} possible engagement pod', 'platform': plat})
            else:
                s2_score = 50
            s2_scores.append(s2_score)

            # S4: Views-to-Followers Ratio
            views = m.avg_views
            s4_score = 50
            vfr = 0
            if followers > 0:
                vfr = (views / followers) * 100

            if vfr > 20:
                s4_score = 95
            elif 10 < vfr <= 20:
                s4_score = 80
            elif 5 < vfr <= 10:
                s4_score = 60
            elif 1 < vfr <= 5:
                s4_score = 35
            else:
                s4_score = 10
            s4_scores.append(s4_score)

        if s1_scores:
            signal_scores['S1']['score'] = sum(s1_scores) // len(s1_scores)
            signal_scores['S1']['detail'] = 'Analyzed across platforms'
            signal_scores['S1']['grade'] = 'Good' if signal_scores['S1']['score'] >= 80 else ('Average' if signal_scores['S1']['score'] >= 50 else 'Poor')

        if s2_scores:
            signal_scores['S2']['score'] = sum(s2_scores) // len(s2_scores)
            signal_scores['S2']['detail'] = 'Analyzed across platforms'
            signal_scores['S2']['grade'] = 'Good' if signal_scores['S2']['score'] >= 80 else ('Average' if signal_scores['S2']['score'] >= 50 else 'Poor')

        if s4_scores:
            signal_scores['S4']['score'] = sum(s4_scores) // len(s4_scores)
            signal_scores['S4']['detail'] = 'Analyzed across platforms'
            signal_scores['S4']['grade'] = 'Good' if signal_scores['S4']['score'] >= 80 else ('Average' if signal_scores['S4']['score'] >= 50 else 'Poor')

        # S3: Comment Quality Signal (checks both OrganicComment and Campaign Comment)
        if influencer.global_influencer:
            organic_comments = OrganicComment.objects.filter(organic_post__global_influencer=influencer.global_influencer)
        else:
            organic_comments = OrganicComment.objects.filter(organic_post__influencer=influencer)

        campaign_comments = Comment.objects.filter(tracked_post__campaign_inf__influencer=influencer)

        total_comments = organic_comments.count() + campaign_comments.count()
        has_comments = False
        if total_comments > 0:
            has_comments = True
            substantive = organic_comments.filter(is_substantive=True).count() + campaign_comments.filter(is_substantive=True).count()
            pod_flagged = organic_comments.filter(is_pod_flagged=True).count() + campaign_comments.filter(is_pod_flagged=True).count()
            sub_ratio = (substantive / total_comments) * 100
            pod_ratio = (pod_flagged / total_comments) * 100

            s3_score = 50
            if sub_ratio > 60:
                s3_score = 95
            elif 40 <= sub_ratio <= 60:
                s3_score = 80
            elif 20 <= sub_ratio < 40:
                s3_score = 55
            else:
                s3_score = 20

            if pod_ratio > 30:
                s3_score = max(0, s3_score - 20)
                risk_flags.append({'severity': 'WARNING', 'code': 'POD_ACTIVITY_HIGH', 'message': 'High engagement pod activity', 'platform': None})
            elif pod_ratio > 20:
                risk_flags.append({'severity': 'WARNING', 'code': 'POD_ACTIVITY', 'message': 'Noticeable engagement pod activity', 'platform': None})

            signal_scores['S3']['score'] = s3_score
            signal_scores['S3']['detail'] = f'{sub_ratio:.1f}% substantive comments ({total_comments} analyzed)'
            signal_scores['S3']['grade'] = 'Good' if s3_score >= 80 else ('Average' if s3_score >= 50 else 'Poor')
        else:
            valid_cr = [m.cr for m in metrics if m.cr and m.cr > 0]
            if valid_cr:
                mean_cr = sum(valid_cr) / len(valid_cr)
                s3_score = 80 if mean_cr >= 8.0 else (60 if mean_cr >= 3.0 else 40)
                signal_scores['S3']['score'] = s3_score
                signal_scores['S3']['detail'] = f'Estimated from comment ratio ({mean_cr:.1f}%)'
                signal_scores['S3']['grade'] = 'Good' if s3_score >= 80 else ('Average' if s3_score >= 60 else 'Poor')
            else:
                signal_scores['S3']['score'] = 50
                signal_scores['S3']['detail'] = 'Pending Comment Extraction'
                signal_scores['S3']['grade'] = 'Average'

        # S5: Engagement Consistency
        if influencer.global_influencer:
            benchmarks = OrganicBenchmark.objects.filter(
                Q(influencer=influencer) | Q(global_influencer=influencer.global_influencer)
            )
        else:
            benchmarks = OrganicBenchmark.objects.filter(influencer=influencer)
        has_benchmarks = False
        if benchmarks.count() >= 3:
            has_benchmarks = benchmarks.count() >= 5
            engagements = [b.engagement_total for b in benchmarks]
            mean_eng = sum(engagements) / len(engagements)
            if mean_eng > 0:
                variance = sum((e - mean_eng) ** 2 for e in engagements) / len(engagements)
                std_dev = math.sqrt(variance)
                cv = std_dev / mean_eng

                s5_score = 50
                if cv < 0.3:
                    s5_score = 95
                elif 0.3 <= cv <= 0.6:
                    s5_score = 80
                elif 0.6 < cv <= 1.0:
                    s5_score = 55
                elif 1.0 < cv <= 2.0:
                    s5_score = 40
                else:
                    s5_score = 30

                signal_scores['S5']['score'] = s5_score
                signal_scores['S5']['detail'] = f'CV: {cv:.2f} across {len(engagements)} posts'
                signal_scores['S5']['grade'] = 'Good' if s5_score >= 80 else ('Average' if s5_score >= 50 else 'Poor')
        else:
            signal_scores['S5']['score'] = 50
            signal_scores['S5']['detail'] = 'Insufficient Data'
            signal_scores['S5']['grade'] = 'N/A'

        if len(metrics) == 1:
            risk_flags.append({'severity': 'INFO', 'code': 'SINGLE_PLATFORM', 'message': 'Only one platform connected', 'platform': None})

        # Platform scores
        for i, m in enumerate(metrics):
            p = m.platform
            p_s1 = s1_scores[i] if i < len(s1_scores) else 50
            p_s2 = s2_scores[i] if i < len(s2_scores) else 50
            p_s4 = s4_scores[i] if i < len(s4_scores) else 50
            p_score = (p_s1 * 0.25 + p_s2 * 0.20 + p_s4 * 0.15 + signal_scores['S3']['score'] * 0.25 + signal_scores['S5']['score'] * 0.15)
            platform_scores_dict[p] = int(p_score)

        # Overall score
        overall_score = 0
        total_weight = 0
        for s_key, s_data in signal_scores.items():
            overall_score += s_data['score'] * s_data['weight']
            total_weight += s_data['weight']

        final_score = int(overall_score / total_weight) if total_weight > 0 else 50

        # Confidence
        if has_comments and has_benchmarks and len(metrics) >= 2:
            confidence = 'HIGH'
        elif has_comments or has_benchmarks or len(metrics) >= 2:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        # Update History for this influencer
        history = AuthenticityScoreHistory.objects.create(
            influencer=influencer,
            overall_score=final_score,
            confidence=confidence,
            platform_scores=platform_scores_dict,
            signal_breakdown=signal_scores,
            risk_flags=risk_flags
        )

        # Update Influencer
        influencer.fake_follower_score = final_score
        influencer.authenticity_confidence = confidence
        influencer.authenticity_risk_flags = risk_flags
        influencer.save(update_fields=['fake_follower_score', 'authenticity_confidence', 'authenticity_risk_flags'])

        if influencer.global_influencer:
            influencer.global_influencer.fake_follower_score = final_score
            influencer.global_influencer.save(update_fields=['fake_follower_score'])

            # Mirror to all other workspace Influencer records linked to this GlobalInfluencer
            other_infs = Influencer.objects.filter(
                global_influencer=influencer.global_influencer
            ).exclude(id=influencer.id)
            for o_inf in other_infs:
                o_inf.fake_follower_score = final_score
                o_inf.authenticity_confidence = confidence
                o_inf.authenticity_risk_flags = risk_flags
                o_inf.save(update_fields=['fake_follower_score', 'authenticity_confidence', 'authenticity_risk_flags'])
                AuthenticityScoreHistory.objects.create(
                    influencer=o_inf,
                    overall_score=final_score,
                    confidence=confidence,
                    platform_scores=platform_scores_dict,
                    signal_breakdown=signal_scores,
                    risk_flags=risk_flags
                )

        return {
            'overall_score': final_score,
            'confidence': confidence,
            'platform_scores': platform_scores_dict,
            'signal_breakdown': signal_scores,
            'risk_flags': risk_flags,
            'calculated_at': history.calculated_at
        }
