from django.core.management.base import BaseCommand
from apps.influencers.models import Influencer, PlatformMetrics, OrganicBenchmark, FetchJob
from apps.campaigns.models import Campaign, CampaignInfluencer, TrackedPost
from apps.sentiment.models import Comment
from apps.scoring.models import CentiScoreHistory
from apps.reports.models import GeneratedReport


class Command(BaseCommand):
    help = 'Cleans up all tracked influencers, campaigns, metrics, posts, comments, history, and jobs, preserving users, workspaces, and brands.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Clearing all demo metrics and data...'))

        # Delete in order of dependencies
        deleted_comments = Comment.objects.all().delete()[0]
        deleted_tracked_posts = TrackedPost.objects.all().delete()[0]
        deleted_campaign_influencers = CampaignInfluencer.objects.all().delete()[0]
        deleted_reports = GeneratedReport.objects.all().delete()[0]
        deleted_campaigns = Campaign.objects.all().delete()[0]
        
        deleted_platform_metrics = PlatformMetrics.objects.all().delete()[0]
        deleted_organic_benchmarks = OrganicBenchmark.objects.all().delete()[0]
        deleted_centi_history = CentiScoreHistory.objects.all().delete()[0]
        deleted_influencers = Influencer.objects.all().delete()[0]
        deleted_fetch_jobs = FetchJob.objects.all().delete()[0]

        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_comments} comments.'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_tracked_posts} tracked posts.'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_reports} generated reports.'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_campaigns} campaigns (and assignments: {deleted_campaign_influencers}).'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_platform_metrics} platform metrics.'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_organic_benchmarks} organic benchmarks.'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_centi_history} centi score histories.'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_influencers} influencers.'))
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_fetch_jobs} fetch jobs.'))

        self.stdout.write(self.style.SUCCESS('Cleanup complete! Your workspace has been cleared of all mock and demo data.'))
