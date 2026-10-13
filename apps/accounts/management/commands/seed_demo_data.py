import decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.accounts.models import Workspace, Brand, WorkspaceMembership
from apps.influencers.models import Influencer, PlatformMetrics, OrganicBenchmark
from apps.campaigns.models import Campaign, CampaignInfluencer, TrackedPost
from apps.sentiment.models import Comment
from apps.scoring.models import CentiScoreHistory

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds the database with high-quality demo data for testing the Sentimetri platform.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Seeding demo data...'))

        # 1. Create Users
        admin_user, created = User.objects.get_or_create(
            username='admin_user',
            email='admin@sentimetri.com',
            defaults={
                'role': User.Roles.ADMIN,
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            admin_user.set_password('adminpass')
            admin_user.save()
            self.stdout.write(self.style.SUCCESS('Created admin user (admin@sentimetri.com / adminpass)'))

        viewer_user, created = User.objects.get_or_create(
            username='viewer_user',
            email='viewer@sentimetri.com',
            defaults={
                'role': User.Roles.VIEWER
            }
        )
        if created:
            viewer_user.set_password('viewerpass')
            viewer_user.save()
            self.stdout.write(self.style.SUCCESS('Created viewer user (viewer@sentimetri.com / viewerpass)'))

        # 2. Create Workspace
        workspace, created = Workspace.objects.get_or_create(
            name='Nike Marketing Hub',
            defaults={
                'type': Workspace.Types.AGENCY,
                'owner': admin_user
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Created workspace "Nike Marketing Hub"'))

        # 3. Create Memberships
        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=admin_user,
            defaults={'role': WorkspaceMembership.Roles.ADMIN}
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=viewer_user,
            defaults={'role': WorkspaceMembership.Roles.VIEWER}
        )
        self.stdout.write(self.style.SUCCESS('Set workspace memberships (Admin: admin, Viewer: viewer)'))

        # 4. Create Brand
        brand, created = Brand.objects.get_or_create(
            workspace=workspace,
            name='Nike',
            defaults={
                'logo_url': 'https://upload.wikimedia.org/wikipedia/commons/a/a6/Logo_NIKE.svg'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Created Nike brand'))

        # 5. Create Influencers
        inf1, created = Influencer.objects.get_or_create(
            workspace=workspace,
            display_name='Sarah Jenkins',
            defaults={
                'niche': 'Creative Lifestyle & Design',
                'ig_handle': 'sarah_j_style',
                'tiktok_handle': 'sarah_jenkins_design',
                'x_handle': 'sarah_j_tweets',
                'fake_follower_score': 92,
                'centi_score': 84.50,
                'sentiment_rating': 'POSITIVE'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Created Influencer: Sarah Jenkins'))

        inf2, created = Influencer.objects.get_or_create(
            workspace=workspace,
            display_name='Alex Rivera',
            defaults={
                'niche': 'Tech & Gear',
                'ig_handle': 'alex_tech_reviews',
                'tiktok_handle': 'alexrivera_reviews',
                'x_handle': 'alex_rivera_dev',
                'fake_follower_score': 88,
                'centi_score': 79.20,
                'sentiment_rating': 'POSITIVE'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Created Influencer: Alex Rivera'))

        # Seed Platform Metrics & Benchmarks
        # Sarah Jenkins
        PlatformMetrics.objects.get_or_create(
            influencer=inf1,
            platform='IG',
            defaults={
                'followers': 125000,
                'engagement_rate': decimal.Decimal('4.50'),
                'avg_views': 35000,
                'avg_likes': 5200,
                'avg_comments': 425
            }
        )
        PlatformMetrics.objects.get_or_create(
            influencer=inf1,
            platform='TT',
            defaults={
                'followers': 480000,
                'engagement_rate': decimal.Decimal('8.20'),
                'avg_views': 120000,
                'avg_likes': 38000,
                'avg_comments': 1200
            }
        )
        OrganicBenchmark.objects.get_or_create(
            influencer=inf1,
            platform='IG',
            defaults={
                'post_url': 'https://instagram.com/p/sarah-j-organic-1/',
                'views': 30000,
                'likes': 4500,
                'comments_count': 250,
                'shares': 80,
                'engagement_total': 4830.0
            }
        )


        # Alex Rivera
        PlatformMetrics.objects.get_or_create(
            influencer=inf2,
            platform='X',
            defaults={
                'followers': 45000,
                'engagement_rate': decimal.Decimal('2.10'),
                'avg_views': 12000,
                'avg_likes': 850,
                'avg_comments': 95
            }
        )
        PlatformMetrics.objects.get_or_create(
            influencer=inf2,
            platform='TT',
            defaults={
                'followers': 650000,
                'engagement_rate': decimal.Decimal('6.80'),
                'avg_views': 250000,
                'avg_likes': 16000,
                'avg_comments': 800
            }
        )
        OrganicBenchmark.objects.get_or_create(
            influencer=inf2,
            platform='TT',
            defaults={
                'post_url': 'https://tiktok.com/@alexrivera/video/alex-tech-organic-1/',
                'views': 220000,
                'likes': 14000,
                'comments_count': 700,
                'shares': 120,
                'engagement_total': 14820.0
            }
        )
        self.stdout.write(self.style.SUCCESS('Seeded metrics and benchmarks'))

        # 6. Create Campaigns
        campaign, created = Campaign.objects.get_or_create(
            workspace=workspace,
            brand=brand,
            name='Nike Summer Run 2026',
            defaults={
                'budget': decimal.Decimal('35000.00'),
                'start_date': timezone.now().date(),
                'end_date': timezone.now().date() + timezone.timedelta(days=60),
                'status': Campaign.Statuses.ACTIVE,
                'goal': 'Promoting Nike Air Zoom Summer Pegasus series with creative lifestyle and technical breakdowns.'

            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Created campaign: Nike Summer Run 2026'))

        # 7. Add Campaign Influencers
        ci1, created = CampaignInfluencer.objects.get_or_create(
            campaign=campaign,
            influencer=inf1,
            defaults={'fee': decimal.Decimal('4500.00')}
        )
        ci2, created = CampaignInfluencer.objects.get_or_create(
            campaign=campaign,
            influencer=inf2,
            defaults={'fee': decimal.Decimal('6000.00')}
        )

        # 8. Add Tracked Posts
        tp1, created = TrackedPost.objects.get_or_create(
            campaign_inf=ci1,
            post_url='https://instagram.com/p/nike-summer-run-1/',
            defaults={
                'platform': 'IG',
                'views': 45000,
                'likes': 4200,
                'comments_count': 320,
                'shares': 110,
                'saves': 250,
                'sentiment_positive': 280,
                'sentiment_neutral': 30,
                'sentiment_negative': 10,
                'brand_sentiment_pos': 95,
                'brand_sentiment_neg': 5
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Tracked IG post seeded'))

        tp2, created = TrackedPost.objects.get_or_create(
            campaign_inf=ci2,
            post_url='https://tiktok.com/@alexrivera/video/nike-pegasus-review/',
            defaults={
                'platform': 'TT',
                'views': 310000,
                'likes': 22000,
                'comments_count': 1450,
                'shares': 820,
                'saves': 1500,
                'sentiment_positive': 1100,
                'sentiment_neutral': 250,
                'sentiment_negative': 100,
                'brand_sentiment_pos': 450,
                'brand_sentiment_neg': 42
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Tracked TikTok post seeded'))


        # 9. Add Comments for sentiment
        demo_comments = [
            ('Best running shoes I have owned so far!', 'run_fast_99', 'POS', 'HAPPY'),
            ('Love the summer colorways. Definitely buying a pair.', 'fit_mom_lifestyle', 'POS', 'EXCITED'),
            ('Decent review, but how is the sole cushioning compared to last years?', 'shoe_geek_01', 'NEU', 'CURIOUS'),
            ('Too expensive, not worth the price imo.', 'frugal_jogger', 'NEG', 'DISAPPOINTED'),
            ('Nike is crushing it with this design.', 'athletic_aesthetics', 'POS', 'EXCITED'),
        ]
        
        for text, author, sentiment, emotion in demo_comments:
            is_nike = 'nike' in text.lower()
            Comment.objects.get_or_create(
                tracked_post=tp1,
                author_handle=author,
                text=text,
                defaults={
                    'platform_comment_id': f"inst_{author}",
                    'sentiment': sentiment,
                    'emotion_category': emotion,
                    'brand_mentioned': is_nike,
                    'brand_sentiment': sentiment if is_nike else None,
                    'created_at': timezone.now()
                }
            )


        # 10. Seed Centi Score History
        for month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']:
            CentiScoreHistory.objects.create(
                influencer=inf1,
                score=int(float(inf1.centi_score) - (6 - len(month))),
                components={'er': 4.5, 'sentiment': 85.0, 'authenticity': 92.0}
            )
            CentiScoreHistory.objects.create(
                influencer=inf2,
                score=int(float(inf2.centi_score) - (6 - len(month))),
                components={'er': 6.8, 'sentiment': 80.0, 'authenticity': 88.0}
            )


        self.stdout.write(self.style.SUCCESS('Demo data seeding successfully completed!'))
