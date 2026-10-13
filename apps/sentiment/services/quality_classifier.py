import re
import math
from difflib import SequenceMatcher
from typing import List, Dict, Set, Any

try:
    import emoji
    emoji_available = True
except ImportError:
    emoji_available = False


class CommentQualityClassifier:
    """
    Service for C3 Comment Quality component and Pod Signature detection per Senti Score spec.
    """
    SPAM_PHRASES = [
        "check my bio", "check out my page", "follow my page", "follow me",
        "dm me", "dm on", "promote it on", "promote on", "earn money",
        "bitcoin", "crypto", "forex", "link in bio", "buy followers",
        "free real estate", "telegram"
    ]

    @classmethod
    def is_substantive(cls, text: str) -> bool:
        """
        Determines if a comment is substantive:
        - >= 4 words
        - Not emoji-only or handle-only
        - Not a repetitive string pattern (e.g., "nice nice nice nice")
        - Not a spam signature or URL promotion
        """
        if not text or not text.strip():
            return False

        text_lower = text.lower().strip()

        # 1. Check for spam phrases or URLs
        if re.search(r'https?://\S+|www\.\S+', text_lower):
            return False
        for phrase in cls.SPAM_PHRASES:
            if phrase in text_lower:
                return False

        # 2. Strip emojis if library is available
        clean_text = text_lower
        if emoji_available:
            try:
                clean_text = emoji.replace_emoji(text_lower, replace='')
            except Exception:
                # If replace_emoji is not in older versions, use regex or demojize
                clean_text = emoji.demojize(text_lower)
                clean_text = re.sub(r':[-a-z0-9_]+:', ' ', clean_text)

        # 3. Strip mentions (@username) and hashtags (#tag) for word counting
        clean_text = re.sub(r'[@#]\w+', ' ', clean_text)

        # 4. Extract alphabetic words
        words = re.findall(r'\b[a-z]{2,}\b', clean_text)

        # Must have at least 4 words
        if len(words) < 4:
            return False

        # 5. Check for repetitive pattern (e.g. "good good good good")
        unique_words = set(words)
        if len(unique_words) / len(words) < 0.4 and len(words) <= 10:
            return False

        return True

    @classmethod
    def is_pod_signature(cls, text: str, author: str = None) -> bool:
        """
        Determines if a single comment exhibits spam / pod signature traits.
        """
        if not text or not text.strip():
            return False
        text_lower = text.lower().strip()
        for phrase in cls.SPAM_PHRASES:
            if phrase in text_lower:
                return True
        return False

    @classmethod
    def detect_pods(cls, comments: List[Dict[str, Any]], text_key: str = 'text', id_key: str = 'id') -> Set[Any]:
        """
        Detects engagement pod signatures within a single post's comments:
        3+ identical or near-identical (>90% text similarity) comments within one post.
        Returns a set of comment IDs to flag as pod signatures.
        """
        pod_ids: Set[Any] = set()
        n = len(comments)
        if n < 3:
            return pod_ids

        # Group similar comments using a simple clustering approach
        # For each comment, find all other comments >= 90% similar
        cleaned_texts = []
        for c in comments:
            raw_text = c.get(text_key, '')
            # Clean slightly for comparison
            t = re.sub(r'\s+', ' ', raw_text.lower()).strip()
            cleaned_texts.append(t)

        visited = [False] * n
        for i in range(n):
            if visited[i] or not cleaned_texts[i]:
                continue
            
            cluster_indices = [i]
            for j in range(i + 1, n):
                if not cleaned_texts[j]:
                    continue
                # Fast equality check first, then SequenceMatcher if needed
                if cleaned_texts[i] == cleaned_texts[j] or \
                   SequenceMatcher(None, cleaned_texts[i], cleaned_texts[j]).ratio() >= 0.90:
                    cluster_indices.append(j)
                    
            if len(cluster_indices) >= 3:
                for idx in cluster_indices:
                    visited[idx] = True
                    pod_ids.add(comments[idx].get(id_key, idx))

        return pod_ids

    @classmethod
    def analyze_comment_list(cls, comments: List[Dict[str, Any]], text_key: str = 'text', id_key: str = 'id') -> Dict[str, Any]:
        """
        Analyzes a batch of comments for quality and pod signatures.
        Returns aggregate stats and updated flags per comment.
        """
        pod_ids = cls.detect_pods(comments, text_key=text_key, id_key=id_key)
        
        substantive_count = 0
        total = len(comments)
        
        results = []
        for c in comments:
            cid = c.get(id_key)
            text = c.get(text_key, '')
            is_pod = cid in pod_ids or (id_key not in c and c in pod_ids)
            
            # A comment cannot be substantive if it is flagged as part of an engagement pod
            is_sub = False if is_pod else cls.is_substantive(text)
            if is_sub:
                substantive_count += 1
                
            results.append({
                "id": cid,
                "is_substantive": is_sub,
                "is_pod_flagged": is_pod
            })
            
        from apps.scoring.services.metrics_engine import MetricsEngine
        c3_score_info = MetricsEngine.c3_comment_quality(substantive_count, total)
        
        return {
            "substantive_count": substantive_count,
            "total_comments": total,
            "pod_count": len(pod_ids),
            "ratio": c3_score_info["ratio"],
            "score": c3_score_info["score"],
            "grade": c3_score_info["grade"],
            "comment_flags": results
        }
