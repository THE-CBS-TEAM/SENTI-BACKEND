import csv
import io
import logging
from django.http import HttpResponse
from apps.campaigns.models import TrackedPost

logger = logging.getLogger(__name__)


class CSVReportExporter:
    @classmethod
    def export_campaign_posts_csv(cls, campaign):
        """
        Generates a CSV string containing all tracked posts details and metrics for a campaign.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'Influencer Display Name', 'Platform', 'Post URL', 
            'Views', 'Likes', 'Comments Count', 'Shares', 'Saves', 'Retweets',
            'Positive Sentiment', 'Neutral Sentiment', 'Negative Sentiment',
            'Brand Mentions Positive', 'Brand Mentions Negative', 'Status',
            'Polling Tier', 'Last Ingested At'
        ])

        posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
        for post in posts:
            writer.writerow([
                post.campaign_inf.influencer.display_name,
                post.platform,
                post.post_url,
                post.views,
                post.likes,
                post.comments_count,
                post.shares,
                post.saves,
                post.retweets,
                post.sentiment_positive,
                post.sentiment_neutral,
                post.sentiment_negative,
                post.brand_sentiment_pos,
                post.brand_sentiment_neg,
                post.status,
                post.polling_tier,
                post.last_fetched_at.strftime('%Y-%m-%d %H:%M:%S') if post.last_fetched_at else 'N/A'
            ])

        return output.getvalue()
