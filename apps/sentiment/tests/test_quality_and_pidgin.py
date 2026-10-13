from django.test import SimpleTestCase
from apps.sentiment.services.quality_classifier import CommentQualityClassifier
from apps.sentiment.services.pidgin_lexicon import PidginSentimentAnalyzer
from apps.sentiment.services.analyzer import SentimentAnalyzer

class QualityAndPidginTests(SimpleTestCase):
    def test_substantive_comment_classification(self):
        # Substantive: >= 4 words, meaningful
        self.assertTrue(CommentQualityClassifier.is_substantive("I really love this product, amazing work!"))
        self.assertTrue(CommentQualityClassifier.is_substantive("This service is completely terrible and slow."))

        # Low-quality: < 4 words
        self.assertFalse(CommentQualityClassifier.is_substantive("Nice"))
        self.assertFalse(CommentQualityClassifier.is_substantive("Good work"))
        self.assertFalse(CommentQualityClassifier.is_substantive("Love it! ❤️"))

        # Low-quality: repetitive string pattern
        self.assertFalse(CommentQualityClassifier.is_substantive("nice nice nice nice nice nice"))

        # Low-quality: spam phrases / URLs
        self.assertFalse(CommentQualityClassifier.is_substantive("Check out my bio for free crypto money"))
        self.assertFalse(CommentQualityClassifier.is_substantive("Visit https://spam-link.com for discounts now today"))

    def test_pod_signature_detection(self):
        comments = [
            {"id": 1, "text": "Great job bro keep it up!"},
            {"id": 2, "text": "great job bro keep it up!"},
            {"id": 3, "text": "Great job bro keep it up!"},
            {"id": 4, "text": "This video was actually informative and useful for my marketing class."}
        ]
        res = CommentQualityClassifier.analyze_comment_list(comments)
        self.assertEqual(res["pod_count"], 3)
        self.assertEqual(res["substantive_count"], 1) # Only comment 4 is substantive (1-3 are in a pod)
        self.assertEqual(res["ratio"], 25.0)

    def test_pidgin_sentiment(self):
        # Positive Pidgin
        pos_res = PidginSentimentAnalyzer.analyze("Abeg e dey sweet me well well, na banger!")
        self.assertIsNotNone(pos_res)
        self.assertEqual(pos_res[0], "POS")
        self.assertGreaterEqual(pos_res[1], 0.85)

        # Negative Pidgin
        neg_res = PidginSentimentAnalyzer.analyze("Why all this wahala and yeye service na?")
        self.assertIsNotNone(neg_res)
        self.assertEqual(neg_res[0], "NEG")
        self.assertGreaterEqual(neg_res[1], 0.85)
