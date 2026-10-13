import re
from typing import Tuple, Optional

class PidginSentimentAnalyzer:
    """
    Lexicon and rule-based sentiment classifier for Nigerian Pidgin English.
    Designed to supplement English NLP pipelines by catching regional idioms and slang.
    """
    
    # Positive Pidgin phrases and words
    POSITIVE_PHRASES = [
        "dey sweet", "too fine", "na banger", "no level", "make sense", 
        "dey make sense", "too much", "chop pass", "no carry second", 
        "badder", "e enter", "gbai", "odogwu", "correct", "enjoyment", 
        "blessings", "chilling", "flexing", "shey you know", "no capping",
        "more oil", "grace", "doings", "balling", "e dey give", "no lele",
        "no wahala", "too sweet", "e go sweet", "baba wiz", "fire", "burst"
    ]
    
    # Negative Pidgin phrases and words
    NEGATIVE_PHRASES = [
        "wahala", "yeye", "nonsense", "no make sense", "na lie", "stop lie", 
        "no go work", "rubbish", "scam", "thief", "jagajaga", "mugu", 
        "mumu", "no like am", "wack", "eye service", "419", "ole", 
        "head no correct", "crass", "suffer", "no progress", "don tire"
    ]
    
    # Pidgin indicator words (used to identify if a statement contains Pidgin syntax)
    PIDGIN_MARKERS = [
        "dey", "na", "abi", "abeg", "shey", "sha", "oyaan", "nawa", 
        "wetin", "who", "kuku", "kilo", "sef", "wahala", "yeye"
    ]

    @classmethod
    def contains_pidgin_markers(cls, text_lower: str) -> bool:
        """Checks if text likely contains Nigerian Pidgin."""
        words = set(re.findall(r'\b\w+\b', text_lower))
        return any(marker in words for marker in cls.PIDGIN_MARKERS)

    @classmethod
    def analyze(cls, text: str) -> Optional[Tuple[str, float]]:
        """
        Evaluates text for Nigerian Pidgin sentiment expressions.
        Returns (sentiment, confidence) if explicit Pidgin sentiment is detected, or None otherwise.
        """
        if not text:
            return None

        text_lower = text.lower()

        # Count occurrences of positive vs negative phrases
        pos_hits = sum(1 for phrase in cls.POSITIVE_PHRASES if phrase in text_lower)
        neg_hits = sum(1 for phrase in cls.NEGATIVE_PHRASES if phrase in text_lower)
        
        # Check explicit phrase dominance
        if pos_hits > 0 and neg_hits == 0:
            return 'POS', min(0.85 + (pos_hits * 0.05), 0.98)
        elif neg_hits > 0 and pos_hits == 0:
            return 'NEG', min(0.85 + (neg_hits * 0.05), 0.98)
        elif pos_hits > 0 and neg_hits > 0:
            if pos_hits >= neg_hits + 2:
                return 'POS', 0.75
            elif neg_hits >= pos_hits + 2:
                return 'NEG', 0.75
            # Mixed signals with Pidgin keywords -> let fallback or neutral handle it
            return 'NEU', 0.65

        # If no explicit positive/negative Pidgin lexicon match, return None to let standard NLP pipeline process
        return None
