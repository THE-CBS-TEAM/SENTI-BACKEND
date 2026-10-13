import re
import logging
from apps.sentiment.services.analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


class BrandExtractor:
    def __init__(self):
        self.analyzer = SentimentAnalyzer()

    def extract_brand_sentiment(self, text, brand_name):
        """
        Isolates the sentence containing the brand name and calculates
        its specific sentiment.
        Returns:
            brand_mentioned (bool): True if brand name is found.
            brand_sentiment (str): POS, NEU, NEG (or None if not mentioned).
        """
        if not text or not brand_name:
            return False, None

        # Safe regex escape for brand name
        escaped_brand = re.escape(brand_name)
        pattern = re.compile(rf'\b{escaped_brand}\b', re.IGNORECASE)

        if not pattern.search(text):
            return False, None

        # Split text into sentences using simple punctuation splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        brand_sentences = []

        for sentence in sentences:
            if pattern.search(sentence):
                brand_sentences.append(sentence)

        # Join sentences containing the brand name
        brand_context = " ".join(brand_sentences)
        
        if not brand_context:
            brand_context = text  # Fallback to whole text if sentence splits missed it

        # Run sentiment analysis specifically on the brand context
        brand_sentiment, _ = self.analyzer.analyze_comment(brand_context)
        
        return True, brand_sentiment
