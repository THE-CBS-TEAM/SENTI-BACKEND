import os
import sys
import django

# Add app directories to path
sys.path.append("/app")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sentimentri.settings.development')
django.setup()

from apps.influencers.models import Influencer, OrganicBenchmark
from tasks.sentiment_tasks import analyze_organic_post_comments_task

def run_backfill():
    influencers = Influencer.objects.all()
    print(f"Starting backfill of organic comments for {influencers.count()} influencers...")
    
    total_queued = 0
    for inf in influencers:
        print(f"Queuing comment ingestion for creator: {inf.display_name}")
        for platform in ['IG', 'TT', 'X']:
            benchmarks = OrganicBenchmark.objects.filter(
                influencer=inf, platform=platform
            ).order_by('-post_created_at', '-id')[:15]
            
            for post in benchmarks:
                analyze_organic_post_comments_task.delay(post.id)
                total_queued += 1
                
    print(f"Successfully queued {total_queued} comment ingestion tasks in background!")

if __name__ == '__main__':
    run_backfill()
