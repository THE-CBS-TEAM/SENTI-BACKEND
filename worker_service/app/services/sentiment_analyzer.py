import re
import logging
from typing import Dict, Any, List
from nltk.sentiment.vader import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

# Pidgin Lexicon definitions
PIDGIN_POSITIVE = {
    'dey sweet', 'correct', 'make sense', 'mad o', 'na fire', 'oga',
    'banger', 'e choke', 'as e dey hot', 'bad sharp', 'soft work',
    'jara', 'solid', 'over sweet', 'on point', 'sweet die', 'lit',
    'heavy', 'ginger', 'vibes', 'turn up', 'too much'
}

PIDGIN_NEGATIVE = {
    'wahala', 'sapa', 'e no clear', 'no loud am', 'scam', 'bad market',
    'dey play', 'mumu', 'kolo', 'e enter bush', 'fake life', 'yawa',
    'fall my hand', 'wetin be this', 'no sense', 'e choke me', 'rubbish',
    'nonsense', 'paraga', 'clown'
}

EMOTION_KEYWORDS = {
    'JOY': ['love', 'happy', 'excited', 'amazing', 'great', 'awesome', 'fire', 'banger', 'dope'],
    'TRUST': ['reliable', 'legit', 'authentic', 'recommend', 'trusted', 'quality', 'best'],
    'ANTICIPATION': ['waiting', 'soon', 'expecting', 'cant wait', 'next', 'ready'],
    'SURPRISE': ['wow', 'omg', 'unbelievable', 'shocking', 'really', 'no way'],
    'ANGER': ['hate', 'angry', 'scam', 'cheat', 'worst', 'annoying', 'terrible', 'fraud'],
    'SADNESS': ['disappointed', 'sad', 'crying', 'failed', 'bad', 'poor', 'hurt']
}

class StandaloneSentimentAnalyzer:
    def __init__(self):
        import os
        import nltk
        for p in ['/usr/local/share/nltk_data', os.path.expanduser('~/nltk_data')]:
            if p not in nltk.data.path:
                nltk.data.path.append(p)
        try:
            self.vader = SentimentIntensityAnalyzer()
        except LookupError:
            try:
                user_nltk = os.path.expanduser('~/nltk_data')
                os.makedirs(user_nltk, exist_ok=True)
                nltk.download('vader_lexicon', download_dir=user_nltk)
                self.vader = SentimentIntensityAnalyzer()
            except Exception as e:
                logger.warning(f"Could not initialize VADER analyzer: {e}")
                self.vader = None

    def analyze_comment(self, text: str, brand_name: str = None) -> Dict[str, Any]:
        if not text:
            return {
                "sentiment": "NEUTRAL",
                "score": 0.0,
                "emotion": "NEUTRAL",
                "brand_mentioned": False,
                "brand_sentiment": "NEUTRAL"
            }

        text_lower = text.lower()
        
        # 1. Check Pidgin boost
        pidgin_pos = any(re.search(rf"\b{re.escape(phrase)}\b", text_lower) for phrase in PIDGIN_POSITIVE)
        pidgin_neg = any(re.search(rf"\b{re.escape(phrase)}\b", text_lower) for phrase in PIDGIN_NEGATIVE)
        
        # 2. VADER score
        scores = self.vader.polarity_scores(text)
        compound = scores['compound']
        
        if pidgin_pos and not pidgin_neg:
            compound = min(1.0, compound + 0.3)
        elif pidgin_neg and not pidgin_pos:
            compound = max(-1.0, compound - 0.3)

        if compound >= 0.05:
            sentiment = "POSITIVE"
        elif compound <= -0.05:
            sentiment = "NEGATIVE"
        else:
            sentiment = "NEUTRAL"

        # 3. Emotion classification (word boundary match)
        detected_emotion = "NEUTRAL"
        max_matches = 0
        for emotion, keywords in EMOTION_KEYWORDS.items():
            matches = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", text_lower))
            if matches > max_matches:
                max_matches = matches
                detected_emotion = emotion

        # 4. Brand mentions
        brand_mentioned = False
        brand_sentiment = "NEUTRAL"
        if brand_name and re.search(rf"\b{re.escape(brand_name.lower())}\b", text_lower):
            brand_mentioned = True
            brand_sentiment = sentiment

        return {
            "sentiment": sentiment,
            "score": round(compound, 3),
            "emotion": detected_emotion,
            "brand_mentioned": brand_mentioned,
            "brand_sentiment": brand_sentiment
        }

    def analyze_batch(self, comments: List[Dict[str, Any]], brand_name: str = None) -> Dict[str, Any]:
        results = []
        pos_count = 0
        neu_count = 0
        neg_count = 0
        brand_pos = 0
        brand_neg = 0
        emotions_count = {}

        for item in comments:
            raw_text = item.get("text", "")
            res = self.analyze_comment(raw_text, brand_name=brand_name)
            res["comment_id"] = item.get("id")
            results.append(res)

            s = res["sentiment"]
            if s == "POSITIVE":
                pos_count += 1
            elif s == "NEGATIVE":
                neg_count += 1
            else:
                neu_count += 1

            if res["brand_mentioned"]:
                if res["brand_sentiment"] == "POSITIVE":
                    brand_pos += 1
                elif res["brand_sentiment"] == "NEGATIVE":
                    brand_neg += 1

            emo = res["emotion"]
            emotions_count[emo] = emotions_count.get(emo, 0) + 1

        total = len(comments) or 1
        return {
            "summary": {
                "total_analyzed": len(comments),
                "positive_count": pos_count,
                "neutral_count": neu_count,
                "negative_count": neg_count,
                "positive_pct": round((pos_count / total) * 100, 1),
                "neutral_pct": round((neu_count / total) * 100, 1),
                "negative_pct": round((neg_count / total) * 100, 1),
                "brand_perception": {
                    "brand_positive": brand_pos,
                    "brand_negative": brand_neg
                },
                "emotions": emotions_count
            },
            "details": results
        }

analyzer = StandaloneSentimentAnalyzer()
