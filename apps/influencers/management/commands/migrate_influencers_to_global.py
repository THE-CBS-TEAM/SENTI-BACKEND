from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from apps.influencers.models import (
    Influencer,
    GlobalInfluencer,
    WorkspaceInfluencer,
    PlatformMetrics,
    OrganicBenchmark,
)


class Command(BaseCommand):
    help = "Migrates legacy workspace-scoped Influencer records to the GlobalInfluencer catalog."

    def handle(self, *args, **options):
        self.stdout.write("Starting migration of legacy influencers to global catalog...")

        influencers = Influencer.objects.all().order_by('id')
        migrated = 0
        linked = 0

        for inf in influencers:
            with transaction.atomic():
                # 1. Check if GlobalInfluencer already exists with matching handles
                q = Q()
                if inf.ig_handle:
                    q |= Q(ig_handle__iexact=inf.ig_handle)
                if inf.tiktok_handle:
                    q |= Q(tiktok_handle__iexact=inf.tiktok_handle)
                if inf.x_handle:
                    q |= Q(x_handle__iexact=inf.x_handle)

                global_inf = None
                if q:
                    global_inf = GlobalInfluencer.objects.filter(q).first()

                if not global_inf:
                    # Create new global influencer
                    global_inf = GlobalInfluencer.objects.create(
                        display_name=inf.display_name,
                        niche=inf.niche,
                        avatar_url=inf.avatar_url,
                        ig_handle=inf.ig_handle or None,
                        tiktok_handle=inf.tiktok_handle or None,
                        x_handle=inf.x_handle or None,
                        centi_score=inf.centi_score,
                        senti_score=inf.senti_score,
                        sentiment_rating=inf.sentiment_rating,
                        senti_label=inf.senti_label,
                        fake_follower_score=inf.fake_follower_score,
                        consistency_score=inf.consistency_score,
                        reach_score=inf.reach_score,
                        authenticity_confidence=inf.authenticity_confidence,
                        authenticity_risk_flags=inf.authenticity_risk_flags,
                        last_scraped_at=inf.last_successful_fetch_at,
                        data_expires_at=(
                            inf.last_successful_fetch_at + timedelta(hours=24)
                            if inf.last_successful_fetch_at else None
                        ),
                    )
                    migrated += 1

                # 2. Link legacy record to global
                if inf.global_influencer_id != global_inf.id:
                    inf.global_influencer = global_inf
                    inf.save(update_fields=['global_influencer'])

                # 3. Create WorkspaceInfluencer junction
                WorkspaceInfluencer.objects.get_or_create(
                    workspace=inf.workspace,
                    global_influencer=global_inf,
                )

                # 4. Migrate PlatformMetrics to GlobalInfluencer
                for pm in PlatformMetrics.objects.filter(influencer=inf):
                    if not pm.global_influencer_id:
                        pm.global_influencer = global_inf
                        pm.save(update_fields=['global_influencer'])

                # 5. Migrate OrganicBenchmark to GlobalInfluencer
                for ob in OrganicBenchmark.objects.filter(influencer=inf):
                    if not ob.global_influencer_id:
                        ob.global_influencer = global_inf
                        ob.save(update_fields=['global_influencer'])

                linked += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Migration completed! Created {migrated} new GlobalInfluencers and linked {linked} workspace records."
            )
        )
