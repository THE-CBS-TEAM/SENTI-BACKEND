import os
import logging
import re
import nltk
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import emoji
    emoji_available = True
except ImportError:
    emoji_available = False

# Register local bundled nltk_data if present
local_nltk_dir = os.path.join(settings.BASE_DIR, 'nltk_data')
if os.path.exists(local_nltk_dir) and local_nltk_dir not in nltk.data.path:
    nltk.data.path.insert(0, local_nltk_dir)

vader_available = False
vader_error = None
try:
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    _test_sia = SentimentIntensityAnalyzer()
    vader_available = True
    logger.info("VADER Lexicon loaded successfully from local data.")
except Exception as e:
    vader_available = False
    vader_error = str(e)
    logger.warning(f"VADER Lexicon unavailable ({vader_error}). Sentiment analysis running in Pidgin + rule-based mode.")

from apps.sentiment.services.pidgin_lexicon import PidginSentimentAnalyzer


class SocialSentimentClassifier:
    """
    Pluggable RoBERTa classifier for social media sentiment.
    """
    def __init__(self):
        self.pipeline = None
        self.initialized = False
        self.load_attempted = False

    def initialize_model(self):
        """Method to initialize the actual Hugging Face pipeline when needed."""
        if self.load_attempted:
            return
        self.load_attempted = True
        
        # Guard: Do not attempt Hugging Face download in standard web/worker threads unless explicitly enabled
        if not getattr(settings, 'ENABLE_ROBERTA_SENTIMENT', False):
            self.initialized = False
            return

        try:
            from transformers import pipeline
            self.pipeline = pipeline(
                "sentiment-analysis", 
                model="cardiffnlp/twitter-roberta-base-sentiment-latest",
                max_length=512,
                truncation=True
            )
            self.initialized = True
            logger.info("RoBERTa model loaded successfully.")
        except Exception as e:
            logger.info(f"Hugging Face transformers not loaded ({str(e)}). Running in high-precision Lexicon mode.")
            self.initialized = False

    def predict(self, text, fallback_sentiment='NEU', fallback_confidence=0.5):
        """Runs prediction with RoBERTa if available, otherwise returns primary lexicon classification."""
        if not self.load_attempted:
            self.initialize_model()

        if self.initialized and self.pipeline:
            try:
                results = self.pipeline(text)
                label = results[0]['label'].lower()
                score = results[0]['score']
                
                if label == 'positive':
                    sentiment = 'POS'
                elif label == 'negative':
                    sentiment = 'NEG'
                else:
                    sentiment = 'NEU'
                return sentiment, score
            except Exception as e:
                logger.error(f"RoBERTa prediction failed: {str(e)}")

        return fallback_sentiment, fallback_confidence


class SentimentAnalyzer:
    def __init__(self):
        if vader_available:
            self.sia = SentimentIntensityAnalyzer()
        else:
            self.sia = None
            logger.error(f"VADER Lexicon is not available: {vader_error}")
        
        self.social_model = SocialSentimentClassifier()

    def clean_text(self, text):
        """Cleans usernames, links and excessive spaces from comments."""
        if not text:
            return ""
        # Convert emojis to text
        if emoji_available:
            try:
                text = emoji.demojize(text, delimiters=(" ", " "))
            except Exception:
                pass
        # Remove URLs
        text = re.sub(r'https?://\S+|www\.\S+', '', text)
        # Remove Mentions (@username)
        text = re.sub(r'@\w+', '', text)
        # Clean extra spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def analyze_comment(self, text):
        """
        Runs the full sentiment analysis pipeline:
        1. Preprocessing & emoji conversion
        2. Nigerian Pidgin Lexicon evaluation
        3. VADER Lexicon scoring
        4. RoBERTa enhancement if model is initialized
        """
        cleaned = self.clean_text(text)
        if not cleaned:
            return 'NEU', 1.0

        # 0. Check Nigerian Pidgin expressions first
        pidgin_result = PidginSentimentAnalyzer.analyze(cleaned)
        if pidgin_result:
            logger.debug(f"Pidgin lexicon matched ({pidgin_result[0]}, confidence={pidgin_result[1]:.2f}) for: '{cleaned}'")
            return pidgin_result

        # Fallback if VADER fails to load
        if not self.sia:
            return self.social_model.predict(cleaned, fallback_sentiment='NEU', fallback_confidence=0.5)

        # 1. Run VADER
        scores = self.sia.polarity_scores(cleaned)
        compound = scores['compound']
        confidence = abs(compound)

        # Classify based on compound
        if compound >= 0.05:
            vader_sentiment = 'POS'
        elif compound <= -0.05:
            vader_sentiment = 'NEG'
        else:
            vader_sentiment = 'NEU'

        # If RoBERTa is initialized and VADER confidence is low, attempt RoBERTa refinement
        if self.social_model.initialized and confidence < 0.60:
            db_sentiment, db_confidence = self.social_model.predict(cleaned, fallback_sentiment=vader_sentiment, fallback_confidence=confidence)
            return db_sentiment, db_confidence

        return vader_sentiment, max(0.5, confidence)
