from django.test import SimpleTestCase
from apps.scoring.services.metrics_engine import MetricsEngine

class MetricsEngineTests(SimpleTestCase):
    def test_chef_amaka_worked_example(self):
        """
        Verify the complete end-to-end calculation for @chef_amaka 
        from the Senti Score Developer Dictionary Section 4/4b.
        """
        # Raw inputs
        pos = 1710
        neg = 36
        total = 1800
        substantive = 1224
        avg_views = 89400
        followers = 185000
        avg_eng = 12840
        posts_30d = 17

        # Step 2: C1 Net Sentiment
        c1 = MetricsEngine.c1_net_sentiment(pos, neg)
        self.assertEqual(c1["score"], 96)
        self.assertEqual(c1["grade"], "Excellent")
        self.assertAlmostEqual(c1["raw_value"], 95.88, places=1)

        # Step 3: C2 Resonance Efficiency
        c2 = MetricsEngine.c2_resonance_efficiency(avg_views, followers, avg_eng)
        self.assertAlmostEqual(c2["aar"], 48.32, places=1)
        self.assertAlmostEqual(c2["cr"], 14.36, places=2)
        self.assertAlmostEqual(c2["re"], 26.34, places=1)
        self.assertEqual(c2["score"], 80)
        self.assertEqual(c2["grade"], "Very good")

        # Step 4: C3 Comment Quality
        c3 = MetricsEngine.c3_comment_quality(substantive, total)
        self.assertEqual(c3["ratio"], 68.0)
        self.assertEqual(c3["score"], 95)
        self.assertEqual(c3["grade"], "Excellent")

        # Step 5: C4 Posting Consistency
        c4 = MetricsEngine.c4_posting_consistency(posts_30d)
        self.assertEqual(c4["score"], 100)
        self.assertEqual(c4["grade"], "Posts almost daily")
        self.assertAlmostEqual(c4["mean_gap"], 1.76, places=2)

        # Step 6: Final Senti Score
        final_res = MetricsEngine.calculate_senti_score(
            c1["score"], c2["score"], c3["score"], c4["score"]
        )
        self.assertEqual(final_res["senti_score"], 92)
        self.assertEqual(final_res["senti_label"], "ELITE")

    def test_instabellz_worked_example_c2_and_c4(self):
        """
        Verify AAR capping and low frequency handling for @instabellz.
        """
        # C2: @instabellz had AAR=100%, CR=12.6%, RE=35.5% -> Score 100
        # Let's test AAR capping where views > followers
        c2 = MetricsEngine.c2_resonance_efficiency(avg_views=250000, followers=200000, avg_engagement=31500)
        self.assertEqual(c2["aar"], 100.0)  # Capped at 100%
        self.assertEqual(c2["cr"], 12.6)
        self.assertAlmostEqual(c2["re"], 35.5, places=1)
        self.assertEqual(c2["score"], 100)
        self.assertEqual(c2["grade"], "Excellent")

        # C4: 2 posts in 30 days -> 15 day gap -> score 10
        c4 = MetricsEngine.c4_posting_consistency(2)
        self.assertEqual(c4["mean_gap"], 15.0)
        self.assertEqual(c4["score"], 10)
        self.assertEqual(c4["grade"], "Rarely posts")

        # C4 edge case: fewer than 2 posts in 30 days -> default score 10
        c4_zero = MetricsEngine.c4_posting_consistency(1)
        self.assertEqual(c4_zero["score"], 10)
        self.assertEqual(c4_zero["grade"], "Rarely posts")
