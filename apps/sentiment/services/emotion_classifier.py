import logging

logger = logging.getLogger(__name__)


class EmotionClassifier:
    """
    Classifies comment text into granular emotions:
    excited, happy, curious, disappointed, angry, inspired, neutral.
    Uses rules/keywords for MVP, and provides interfaces for future Hugging Face models.
    """
    EMOTION_KEYWORDS = {
        'EXCITED': ['wow', 'excited', 'cant wait', 'hype', 'omg', 'incredible', 'amazing', 'yay', 'hooray', 'awesome!'],
        'HAPPY': ['love', 'good', 'great', 'happy', 'nice', 'sweet', 'cool', 'perfect', 'glad', 'smile', 'beautiful'],
        'CURIOUS': ['how', 'why', 'where', 'when', 'what', 'cost', 'price', 'buy', 'shop', 'curious', 'question', 'info'],
        'DISAPPOINTED': ['sad', 'disappointed', 'fail', 'bad', 'bummer', 'poor', 'regret', 'unfortunate', 'unfortunately'],
        'ANGRY': ['hate', 'angry', 'mad', 'terrible', 'worst', 'stupid', 'garbage', 'trash', 'scam', 'fake', 'annoyed'],
        'INSPIRED': ['inspire', 'inspired', 'goals', 'motivated', 'dream', 'creative', 'moving', 'touching', 'mindset']
    }

    def classify_emotion(self, text):
        """
        Classifies the text into an emotion category.
        Defaults to 'NEUTRAL'.
        """
        if not text:
            return 'NEUTRAL'

        text_lower = text.lower()
        scores = {emotion: 0 for emotion in self.EMOTION_KEYWORDS.keys()}

        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            for word in keywords:
                # Basic token search
                if word in text_lower:
                    scores[emotion] += 1

        # Find the highest score
        max_score = 0
        best_emotion = 'NEUTRAL'

        for emotion, score in scores.items():
            if score > max_score:
                max_score = score
                best_emotion = emotion

        return best_emotion
