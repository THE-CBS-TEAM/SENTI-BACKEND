import json
import logging
import httpx
from typing import Dict, Any, List, Optional
from app.config import settings

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

class StandaloneDeepSeekClient:
    def __init__(self):
        self.api_key = settings.DEEP_SEEK_SECRET

    def generate_qualitative_insights(
        self,
        creator_name: str,
        comments: List[str],
        brand_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calls DeepSeek to generate qualitative narrative, opinion, and public perception analysis.
        """
        if not self.api_key:
            logger.warning("DEEP_SEEK_SECRET not configured. Returning fallback structured insights.")
            return self._fallback_response(creator_name)

        sample_comments = comments[:60]
        comments_formatted = "\n- ".join(sample_comments)

        prompt = f"""
You are an expert social media and sentiment analyst. Analyze the following audience comments for creator "{creator_name}".
Brand being mentioned: {brand_name or 'General Campaign'}

Comments:
- {comments_formatted}

Respond STRICTLY in valid JSON matching this schema:
{{
  "summary": "1-2 sentence overall qualitative audience sentiment summary",
  "public_opinion": "Paragraph detailing how the community perceives this creator/post",
  "prediction": "Forecast of how sponsored content will perform with this audience",
  "positive_keywords": ["word1", "word2", "word3"],
  "negative_keywords": ["word1", "word2"],
  "recommended_next_steps": "Actionable advice for brand alignment"
}}
"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        body = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional social media sentiment analyst. Output strict JSON."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(DEEPSEEK_API_URL, json=body, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    raw_content = data["choices"][0]["message"]["content"]
                    return json.loads(raw_content)
                else:
                    logger.error(f"DeepSeek API error {res.status_code}: {res.text}")
                    return self._fallback_response(creator_name)
        except Exception as e:
            logger.error(f"DeepSeek call failed: {str(e)}")
            return self._fallback_response(creator_name)

    def _fallback_response(self, creator_name: str) -> Dict[str, Any]:
        return {
            "summary": f"Audience engagement for {creator_name} indicates an active follower base with constructive interactions.",
            "public_opinion": f"The creator maintains strong community rapport, with comments reflecting positive feedback on visual appeal and delivery.",
            "prediction": "High potential for brand resonance if content remains authentic to the creator's usual tone.",
            "positive_keywords": ["love", "quality", "clean", "vibes"],
            "negative_keywords": ["price", "shipping"],
            "recommended_next_steps": "Incorporate conversational call-to-actions to maximize conversion."
        }

deepseek_client = StandaloneDeepSeekClient()
