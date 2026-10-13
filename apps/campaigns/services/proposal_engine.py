import logging

from typing import List, Dict, Any
from decimal import Decimal
from django.db.models import Q
from apps.influencers.models import Influencer, PlatformMetrics
from apps.scoring.services.metrics_engine import MetricsEngine

logger = logging.getLogger(__name__)


def get_creator_tier(followers: int) -> str:
    if followers >= 1_000_000:
        return "Mega Creator"
    elif followers >= 500_000:
        return "Macro Creator"
    elif followers >= 100_000:
        return "Mid-tier Creator"
    elif followers >= 10_000:
        return "Micro Creator"
    else:
        return "Nano Creator"


def format_followers_short(followers: int) -> str:
    if followers >= 1_000_000:
        val = followers / 1_000_000
        val_str = f"{val:.1f}".rstrip('0').rstrip('.')
        return f"{val_str}M+ Followers"
    elif followers >= 1_000:
        val = followers / 1_000
        val_str = f"{val:.1f}".rstrip('0').rstrip('.')
        return f"{val_str}K+ Followers"
    else:
        return f"{followers} Followers"


def get_senti_rating(score: int) -> str:
    if score >= 90:
        return "Elite"
    elif score >= 75:
        return "Strong"
    elif score >= 60:
        return "Average"
    elif score >= 40:
        return "Below average"
    else:
        return "Poor"


class ProposalEngine:
    """
    Engine responsible for simulating and calculating expected KPI projections
    during Stage 1 (Proposal stage) of campaign creation and generating structured PDF proposal payloads.
    """

    @classmethod
    def estimate_campaign_kpis(cls, items_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Accepts a list of dictionaries with influencer_id and optional fee/platform filter.
        Returns projected aggregates and individual breakdowns.
        """
        total_fee = Decimal('0.00')
        total_reach = 0
        total_views = 0
        total_eng = 0
        
        influencers_breakdown = []
        senti_scores_sum = 0
        valid_influencers_count = 0

        for item in items_data:
            inf_id = item.get('influencer_id')
            fee_val = item.get('fee', 0.00)
            try:
                fee = Decimal(str(fee_val))
            except Exception:
                fee = Decimal('0.00')
                
            try:
                inf = Influencer.objects.get(pk=inf_id)
            except Influencer.DoesNotExist:
                continue

            if inf.global_influencer:
                metrics = PlatformMetrics.objects.filter(
                    Q(influencer=inf) | Q(global_influencer=inf.global_influencer)
                )
            else:
                metrics = PlatformMetrics.objects.filter(influencer=inf)
            inf_followers = sum(m.followers for m in metrics)
            inf_views = sum(m.avg_views for m in metrics)
            inf_eng = sum(
                MetricsEngine.engagement_total(m.avg_likes, m.avg_comments, m.avg_shares, m.avg_saves, m.avg_reposts)
                for m in metrics
            )

            # Calculate individual projected KPIs
            inf_aar = MetricsEngine.aar(inf_views, inf_followers)
            inf_cr = MetricsEngine.cr(inf_eng, inf_views)
            inf_re = MetricsEngine.resonance_efficiency(inf_aar, inf_cr)
            
            cpe = float(fee) / inf_eng if inf_eng > 0 else 0.0
            cpm = (float(fee) / inf_views) * 1000.0 if inf_views > 0 else 0.0

            creator_tier = get_creator_tier(inf_followers)
            followers_formatted = format_followers_short(inf_followers)
            senti_rating = get_senti_rating(inf.senti_score)

            influencers_breakdown.append({
                "influencer_id": inf.id,
                "display_name": inf.display_name,
                "avatar_url": inf.avatar_url,
                "niche": inf.niche or "General",
                "senti_score": inf.senti_score,
                "senti_label": inf.senti_label or senti_rating.upper(),
                "senti_rating": senti_rating,
                "creator_tier": creator_tier,
                "followers_formatted": followers_formatted,
                "creator_classification": f"{creator_tier} | {followers_formatted}",
                "fee": float(fee),
                "estimated_reach": inf_followers,
                "estimated_views": inf_views,
                "estimated_engagement": inf_eng,
                "estimated_aar": inf_aar,
                "estimated_cr": inf_cr,
                "estimated_er": inf_cr,
                "estimated_re": inf_re,
                "cpe": round(cpe, 4),
                "cpm": round(cpm, 2),
                "ig_handle": inf.ig_handle,
                "tiktok_handle": inf.tiktok_handle,
                "x_handle": inf.x_handle
            })

            total_fee += fee
            total_reach += inf_followers
            total_views += inf_views
            total_eng += inf_eng
            senti_scores_sum += inf.senti_score
            valid_influencers_count += 1

        # Calculate macro campaign projected KPIs
        macro_aar = MetricsEngine.aar(total_views, total_reach)
        macro_cr = MetricsEngine.cr(total_eng, total_views)
        macro_re = MetricsEngine.resonance_efficiency(macro_aar, macro_cr)
        
        avg_senti_score = round(senti_scores_sum / valid_influencers_count) if valid_influencers_count > 0 else 0
        macro_cpe = float(total_fee) / total_eng if total_eng > 0 else 0.0
        macro_cpm = (float(total_fee) / total_views) * 1000.0 if total_views > 0 else 0.0

        return {
            "summary": {
                "total_budget_required": float(total_fee),
                "total_influencers": valid_influencers_count,
                "estimated_reach": total_reach,
                "estimated_views": total_views,
                "estimated_engagement": total_eng,
                "estimated_aar": macro_aar,
                "estimated_cr": macro_cr,
                "estimated_er": macro_cr,
                "estimated_re": macro_re,
                "avg_senti_score": int(avg_senti_score),
                "cost_per_engagement": round(macro_cpe, 4),
                "cost_per_mille_views": round(macro_cpm, 2)
            },
            "influencers": influencers_breakdown
        }

    @classmethod
    def apply_projections_to_campaign(cls, campaign, items_data: List[Dict[str, Any]]) -> None:
        """
        Updates a campaign and its CampaignInfluencer links with calculated projected metrics.
        """
        projections = cls.estimate_campaign_kpis(items_data)
        summary = projections["summary"]
        
        campaign.estimated_reach = summary["estimated_reach"]
        campaign.estimated_views = summary["estimated_views"]
        campaign.estimated_engagement = summary["estimated_engagement"]
        campaign.estimated_aar = summary["estimated_aar"]
        campaign.estimated_cr = summary["estimated_cr"]
        campaign.estimated_re = summary["estimated_re"]
        campaign.save()

        # Update each CampaignInfluencer item with its corresponding breakdown metrics
        breakdown_map = {b["influencer_id"]: b for b in projections["influencers"]}
        for ci in campaign.campaign_influencers.all():
            if ci.influencer_id in breakdown_map:
                b = breakdown_map[ci.influencer_id]
                ci.estimated_reach = b["estimated_reach"]
                ci.estimated_views = b["estimated_views"]
                ci.estimated_engagement = b["estimated_engagement"]
                ci.estimated_aar = b["estimated_aar"]
                ci.estimated_cr = b["estimated_cr"]
                ci.estimated_re = b["estimated_re"]
                ci.save()

    @classmethod
    def generate_proposal_report_payload(cls, campaign) -> Dict[str, Any]:
        """
        Constructs a structured context dictionary for rendering a professional WeasyPrint PDF proposal.
        """
        ci_items = []
        for ci in campaign.campaign_influencers.all():
            ci_items.append({
                "influencer_id": ci.influencer_id,
                "fee": float(ci.fee)
            })
            
        projections = cls.estimate_campaign_kpis(ci_items)

        # Map qualitative fields from CampaignInfluencer into projections list
        ci_map = {ci.influencer_id: ci for ci in campaign.campaign_influencers.all()}
        for inf_data in projections["influencers"]:
            inf_id = inf_data["influencer_id"]
            if inf_id in ci_map:
                ci = ci_map[inf_id]
                inf_data["llm_summary"] = ci.llm_summary
                inf_data["llm_public_opinion"] = ci.llm_public_opinion
                inf_data["llm_prediction"] = ci.llm_prediction
                inf_data["llm_top_positive_comments"] = ci.llm_top_positive_comments
                inf_data["llm_top_negative_comments"] = ci.llm_top_negative_comments
                inf_data["llm_positive_keywords"] = ci.llm_positive_keywords
                inf_data["llm_negative_keywords"] = ci.llm_negative_keywords
        
        currency_code = getattr(campaign, 'currency', 'NGN') or 'NGN'
        currency_symbol = {
            'NGN': '₦',
            'USD': '$',
            'GBP': '£',
            'EUR': '€',
            'ZAR': 'R'
        }.get(currency_code, '₦')

        return {
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "brand_name": campaign.brand.name if campaign.brand else "Client",
            "start_date": campaign.start_date.strftime("%B %d, %Y") if campaign.start_date else 'N/A',
            "end_date": campaign.end_date.strftime("%B %d, %Y") if campaign.end_date else 'N/A',
            "goal": campaign.goal or "Brand Awareness and Engagement",
            "budget": float(campaign.budget),
            "currency_code": currency_code,
            "currency_symbol": currency_symbol,
            "status": campaign.status,
            "projections": projections
        }
