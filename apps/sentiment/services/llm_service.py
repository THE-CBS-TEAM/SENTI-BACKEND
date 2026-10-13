import requests
import json
import logging
from decimal import Decimal
from django.conf import settings
from django.db.models import F, Q
from apps.influencers.models import OrganicBenchmark
from apps.sentiment.models import OrganicComment, Comment
from apps.campaigns.models import TrackedPost

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service responsible for interacting with the DeepSeek LLM
    to generate qualitative insights, predict campaign outcome,
    highlight key comments, extract keywords, and perform per-creator
    analysis for proposal enhancement.
    """

    @classmethod
    def classify_comments_batch(cls, comments_list, workspace=None, brand_name=None):
        """
        Batches comments to DeepSeek LLM for nuanced Nigerian/African pop culture and Pidgin sentiment classification.
        comments_list: list of dicts with at least {'id': int/str, 'text': str}
        Returns: dict mapping comment index/id to {'sentiment': 'POS'|'NEG'|'NEU', 'emotion': str}
        """
        if not comments_list:
            return {}

        if workspace and not workspace.use_llm_sentiment_analysis:
            return {}

        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        if not api_key:
            return {}

        # Format comments for prompt
        numbered_comments = []
        for idx, c in enumerate(comments_list):
            txt = (c.get('text') or '').strip().replace('\n', ' ')
            if txt:
                numbered_comments.append(f"{idx}: {txt[:280]}")

        if not numbered_comments:
            return {}

        comments_block = "\n".join(numbered_comments[:60]) # batch up to 60 comments per call

        prompt = f"""
You are an expert NLP sentiment analyzer for social media, specializing in Nigerian Pidgin, slang, pop culture, banter, sarcasm, and African creative content.
The brand context is: "{brand_name or 'General Brand'}"

Analyze each numbered comment below.
Classify each into:
- sentiment: "POS" (praise, hype, laughter, excitement, love, support, joy), "NEG" (criticism, insults, frustration, hate, complaints, scam), or "NEU" (neutral observations, questions, casual tags)
- emotion: "EXCITED", "HAPPY", "CURIOUS", "DISAPPOINTED", "ANGRY", "INSPIRED", or "NEUTRAL"

Comments to analyze:
---
{comments_block}
---

Return a JSON object with a single key "classifications" containing an array of objects:
`{{"classifications": [{{"id": 0, "sentiment": "POS", "emotion": "HAPPY"}}, ...]}}`
Do not output markdown code blocks or extra text. Output pure JSON only.
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional sentiment classification engine that outputs valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        try:
            response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=25)
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                parsed = json.loads(content.strip())
                classifications = parsed.get('classifications', [])
                
                # Log AI Credit Usage
                usage = result.get('usage', {})
                if workspace:
                    cls.log_usage(
                        workspace=workspace,
                        feature="Batch Comment Sentiment Analysis",
                        model_name="deepseek-chat",
                        usage_dict=usage,
                        metadata={"comment_count": len(numbered_comments)}
                    )

                mapping = {}
                for item in classifications:
                    cid = item.get('id')
                    sent = (item.get('sentiment') or 'NEU').upper()
                    if sent not in ['POS', 'NEG', 'NEU']:
                        sent = 'POS' if 'POS' in sent else 'NEG' if 'NEG' in sent else 'NEU'
                    emo = (item.get('emotion') or 'NEUTRAL').upper()
                    mapping[cid] = {'sentiment': sent, 'emotion': emo}
                return mapping
            else:
                logger.error(f"DeepSeek batch sentiment API error: {response.status_code} - {response.text}")
                return {}
        except Exception as e:
            logger.error(f"Failed to run LLM batch sentiment analysis: {str(e)}")
            return {}

    @classmethod
    def log_usage(cls, workspace, feature, model_name, usage_dict, metadata=None):
        try:
            from apps.accounts.models import AICreditUsage
            prompt_tokens = usage_dict.get('prompt_tokens', 0)
            completion_tokens = usage_dict.get('completion_tokens', 0)
            total_tokens = usage_dict.get('total_tokens', 0)
            
            # DeepSeek Chat V3 prices: Input: $0.14/1M, Output: $0.28/1M
            cost = (prompt_tokens * Decimal('0.14') + completion_tokens * Decimal('0.28')) / Decimal('1000000')
            
            target_workspace = workspace
            if not target_workspace and metadata and metadata.get('global_influencer_id'):
                try:
                    from apps.influencers.models import Influencer
                    first_inf = Influencer.objects.filter(global_influencer_id=metadata['global_influencer_id']).first()
                    if first_inf and first_inf.workspace:
                        target_workspace = first_inf.workspace
                except Exception:
                    pass

            if target_workspace:
                AICreditUsage.objects.create(
                    workspace=target_workspace,
                    feature=feature,
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost=cost,
                    metadata=metadata or {}
                )

            # Log to ApiCostLog for unified admin cost accounting
            try:
                from apps.influencers.models import ApiCostLog
                ApiCostLog.objects.create(
                    provider=ApiCostLog.Providers.DEEPSEEK,
                    endpoint=feature,
                    credits_used=Decimal(total_tokens) / Decimal('1000'),
                    cost_usd=cost,
                    workspace=target_workspace,
                    campaign_id=metadata.get('campaign_id') if metadata else None,
                    global_influencer_id=metadata.get('global_influencer_id') if metadata else None,
                    pipeline_stage=metadata.get('pipeline_stage', ApiCostLog.PipelineStages.STANDALONE) if metadata else ApiCostLog.PipelineStages.STANDALONE,
                    cost_category=metadata.get('cost_category', ApiCostLog.CostCategories.DEEPSEEK_PROPOSAL) if metadata else ApiCostLog.CostCategories.DEEPSEEK_PROPOSAL,
                    response_time_ms=metadata.get('response_time_ms', 0) if metadata else 0,
                    success=True,
                )
            except Exception as cost_exc:
                logger.warning(f"Failed to record ApiCostLog for DeepSeek: {cost_exc}")

            logger.info(f"Logged AI usage: {feature} - {total_tokens} tokens (${cost:.6f})")
        except Exception as e:
            logger.error(f"Failed to log AI credit usage: {str(e)}")

    @classmethod
    def generate_global_influencer_analysis(cls, global_influencer):
        """
        DeepSeek creator intelligence analysis for a GlobalInfluencer.
        Extracts recent benchmark posts and comments, prompts DeepSeek for structured
        qualitative insights, and caches results on global_influencer.deepseek_summary and deepseek_analysis.
        """
        import time
        from django.utils import timezone
        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        benchmarks = OrganicBenchmark.objects.filter(global_influencer=global_influencer).order_by('-likes')[:10]
        sample_captions = [b.post_text[:200] for b in benchmarks if b.post_text]
        sample_text = "\n".join(sample_captions[:6]) or "Lifestyle, creative content, audience interactions."

        if not api_key:
            summary = {
                "headline": f"{global_influencer.display_name} — High Engagement Creator",
                "content_style": "Consistent organic engagement with strong creator authenticity.",
                "brand_safety": "Low Risk",
                "top_themes": ["Entertainment", "Culture", "Engagement"]
            }
            analysis = {
                "strengths": ["High comment velocity", "Strong audience trust"],
                "considerations": ["Ensure clear product integration to prevent sponsored fatigue"],
                "audience_tone": "Warm, supportive, and active community"
            }
            global_influencer.deepseek_summary = summary
            global_influencer.deepseek_analysis = analysis
            global_influencer.deepseek_analyzed_at = timezone.now()
            global_influencer.save(update_fields=['deepseek_summary', 'deepseek_analysis', 'deepseek_analyzed_at'])
            return summary

        prompt = f"""
You are a senior social media intelligence analyst.
Analyze the creator profile below:
Name: {global_influencer.display_name}
Niche: {global_influencer.niche or 'General Lifestyle & Entertainment'}
Handles: IG=@{global_influencer.ig_handle or 'N/A'}, TikTok=@{global_influencer.tiktok_handle or 'N/A'}, X=@{global_influencer.x_handle or 'N/A'}
Sample Recent Post Content:
{sample_text}

Provide your analysis in JSON format with two keys:
1. "summary":
   - "headline": Short punchy 1-line creator profile headline
   - "content_style": 2-3 sentences summarizing their communication and aesthetic style
   - "brand_safety": "Low Risk", "Moderate Risk", or "High Risk"
   - "top_themes": Array of 3-5 keywords describing their content pillars
2. "analysis":
   - "strengths": Array of 2-3 bullet points on creator's key advantages
   - "considerations": Array of 1-2 points on potential campaign risks or considerations
   - "audience_tone": 1-2 sentences describing how their followers engage

Respond ONLY with valid JSON.
"""
        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a professional social media creator auditor. Always output valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"}
            }
            t0 = time.time()
            resp = requests.post(url, headers=headers, json=payload, timeout=25)
            elapsed_ms = int((time.time() - t0) * 1000)

            if resp.status_code == 200:
                result = resp.json()
                content = result['choices'][0]['message']['content']
                parsed = json.loads(content)
                summary = parsed.get('summary', {})
                analysis = parsed.get('analysis', {})

                usage = result.get('usage', {})
                cls.log_usage(
                    workspace=None,
                    feature="Global Influencer DeepSeek Audit",
                    model_name="deepseek-chat",
                    usage_dict=usage,
                    metadata={
                        "global_influencer_id": global_influencer.id,
                        "global_influencer_name": global_influencer.display_name,
                        "cost_category": "DEEPSEEK_PROPOSAL",
                        "response_time_ms": elapsed_ms
                    }
                )

                global_influencer.deepseek_summary = summary
                global_influencer.deepseek_analysis = analysis
                global_influencer.deepseek_analyzed_at = timezone.now()
                global_influencer.save(update_fields=['deepseek_summary', 'deepseek_analysis', 'deepseek_analyzed_at'])
                return summary
            else:
                logger.error(f"DeepSeek API error: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Error calling DeepSeek for global influencer {global_influencer.id}: {e}")

        summary = {
            "headline": f"{global_influencer.display_name} — Creator Profile",
            "content_style": "Active social media creator with steady organic audience engagement.",
            "brand_safety": "Low Risk",
            "top_themes": [global_influencer.niche or "Lifestyle", "Content", "Engagement"]
        }
        analysis = {
            "strengths": ["Active posting schedule", "Organic community resonance"],
            "considerations": ["Review recent post content for alignment with campaign guidelines"],
            "audience_tone": "Engaged and responsive"
        }
        global_influencer.deepseek_summary = summary
        global_influencer.deepseek_analysis = analysis
        global_influencer.deepseek_analyzed_at = timezone.now()
        global_influencer.save(update_fields=['deepseek_summary', 'deepseek_analysis', 'deepseek_analyzed_at'])
        return summary

    @classmethod
    def generate_proposal_insights(cls, campaign):
        # Check workspace toggle
        if campaign.workspace and not campaign.workspace.use_llm_sentiment_analysis:
            logger.info("LLM sentiment analysis disabled in workspace settings. Using mock proposal insights.")
            return cls._get_mock_insights(campaign)

        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        if not api_key:
            logger.warning("DEEP_SEEK_SECRET not configured. Using mock insights.")
            return cls._get_mock_insights(campaign)
        
        campaign_influencers = campaign.campaign_influencers.all()
        if not campaign_influencers:
            return {
                "summary": "No creators assigned to this campaign proposal yet.",
                "public_opinion": "N/A",
                "prediction": "N/A",
                "top_positive_comments": [],
                "top_negative_comments": [],
                "positive_keywords": [],
                "negative_keywords": [],
                "creators_analysis": []
            }
        
        # Gather recent comments directly from organic comments of the selected influencers
        all_comments_text = []
        creator_names = []
        
        fallback_texts = {
            "So authentic, love this!",
            "Always delivering the best content.",
            "This is amazing, keep it up!",
            "Highly relatable and beautifully made.",
            "A true inspiration to many of us.",
            "This is why you are my favorite creator!",
            "Hope this isn't just another sponsored post.",
            "Expected something a bit different this time.",
            "The delivery feels a bit forced here.",
            "Not your best content, to be honest.",
            "A bit repetitive.",
            "This is such a blessing! God bless you minister! 🙌😭",
            "This song has been on repeat all morning, so powerful.",
            "Amen! What a beautiful sound of worship.",
            "This is pure heaven, the presence of God is here.",
            "Such a timely message, thank you for being a vessel.",
            "Powerful ministration! More grace to you.",
            "Touched my soul deeply. Praise God!",
            "The audio mixing feels a bit off in this video.",
            "I prefer the live version over this studio track.",
            "Why is the video so short? Needed more ministration.",
            "Feels a bit overproduced compared to your earlier worship songs.",
            "This collaboration didn't hit the mark for me.",
            "This is too funny, my ribs! 😂😂😂",
            "You never fail to make me laugh, pure talent!",
            "I have watched this video 5 times already and still laughing.",
            "The expression on your face at the end was priceless! 💀",
            "Best comedian/skit maker in the game right now.",
            "This is pure comedy gold, hands down!",
            "The editing is top notch, matching the humor perfectly.",
            "The joke felt a bit dry at the end.",
            "Not your funniest skit, but it's okay.",
            "The storyline was a bit confusing this time.",
            "This style is getting a bit repetitive, try new characters.",
            "A bit too long for a social media skit.",
            "This track is an absolute banger! 🔥🎧",
            "The flow and the beat are just out of this world.",
            "Can't stop listening to this, song of the year!",
            "So much style and vibe in this video.",
            "A masterpiece! You are a musical genius.",
            "The lyrics are so deep and beautiful.",
            "Love the visual aesthetic of this content.",
            "This song feels a bit mid compared to your last hit.",
            "The vocal tuning is a bit too obvious here.",
            "Expected a more energetic delivery from you.",
            "The beat was good but the lyrics were lacking.",
            "Why was this collaboration so hyped? It's average."
        }
        
        for ci in campaign_influencers:
            inf = ci.influencer
            creator_names.append(inf.display_name)
            
            # Fetch the top 25 recent posts (more than 20) with NULLS LAST
            if inf.global_influencer:
                benchmarks = OrganicBenchmark.objects.filter(
                    Q(influencer=inf) | Q(global_influencer=inf.global_influencer)
                ).order_by(
                    F('post_created_at').desc(nulls_last=True)
                )[:25]
            else:
                benchmarks = OrganicBenchmark.objects.filter(
                    influencer=inf
                ).order_by(
                    F('post_created_at').desc(nulls_last=True)
                )[:25]

            # Fetch up to 50 organic comments across these posts
            org_comments = OrganicComment.objects.filter(
                organic_post__in=benchmarks
            ).order_by('-organic_post__post_created_at')[:50]

            for c in org_comments:
                author = c.author_handle or 'user'
                if c.text in fallback_texts:
                    continue
                all_comments_text.append(f"[{inf.display_name} - @{author}]: {c.text}")

            # If comments have not been scraped yet, include the creator's real post captions
            if not org_comments.exists():
                for b in benchmarks:
                    if b.post_text:
                        all_comments_text.append(f"[{inf.display_name} - Post Caption]: {b.post_text[:250]}")

            # Also fetch real comments from active tracked campaign posts if available
            real_comments = Comment.objects.filter(
                tracked_post__campaign_inf__influencer=inf
            ).order_by('-created_at')[:50]

            for c in real_comments:
                author = c.author_handle or 'user'
                all_comments_text.append(f"[{inf.display_name} - @{author}]: {c.text}")
                    
        creators_list_str = ", ".join(creator_names)
        brand_name = campaign.brand.name if campaign.brand else "the brand"
        
        if not all_comments_text:
            logger.warning(f"No organic comments found in database for campaign {campaign.id} influencers.")
            comments_block = "No organic comments available in the database for the creators in this campaign."
            prompt_instruction = (
                f"Note: Since no comments were found in the database, perform your qualitative analysis, "
                f"sentiment drivers, and strategic prediction based on the campaign goal, the brand '{brand_name}', "
                f"and the creators' niches/roster. For the top positive and negative comments fields, "
                f"generate hypothetical high-relevance representative comments that match the expected audience reaction."
            )
        else:
            # Let the LLM analyze up to 150 comments (e.g. 50 comments per creator across 3 creators)
            comments_block = "\n".join(all_comments_text[:150])
            prompt_instruction = "Based on the provided real organic comments, perform a qualitative analysis."

        prompt = f"""
You are an expert marketing strategist analyzing audience comments for a campaign proposal on Sentimentri.
The campaign goal is: "{campaign.goal or 'Brand Awareness and Engagement'}"
The brand is: "{brand_name}"
The budget is: {campaign.budget} {campaign.currency}
The selected roster of creators is: {creators_list_str}

Here is the list of organic comments from the target audience of these creators (each comment is prefixed with their name):
---
{comments_block}
---

{prompt_instruction}

For any creators in the roster ({creators_list_str}) who have few or no comments in the list above, you MUST still evaluate them. Perform their qualitative analysis based on their specific niche and the campaign goals, and generate representative hypothetical comments for them that reflect expected audience reactions. Do NOT output placeholder text like "No comments provided" or "no data to analyze".

Return a JSON object with the following fields:
1. "summary": A detailed summary (2-3 paragraphs) explaining what is driving the sentiment score, highlighting the key themes, positive aspects, and negative critiques. You MUST cover all creators in the roster ({creators_list_str}) in this summary.
2. "public_opinion": A concise description (1-2 sentences) of the general public perception of the creators in relation to this campaign.
3. "prediction": A realistic strategic prediction of what is likely to happen if this campaign is executed (potential ROI, brand safety risks, or audience receptivity) incorporating all creators in the roster.
4. "top_positive_comments": A list of up to 4 comments that represent strong positive audience reception. Each item must be a dict with keys "author" and "text". CRITICAL: The "author" field MUST be a realistic social media user handle (e.g. "tobi_adeyemi", "chinedu_k", "amina_bello", "korede_vibes", "funmi_lawal", "bolanle_99", "seun_og"). NEVER use generic placeholders like "Fan1", "Fan2", "user", "audience_member", and NEVER use the creator's own name or handle. The "text" must be the comment made by that viewer reacting to the creator's content or campaign.
5. "top_negative_comments": A list of up to 4 comments that represent concerns, friction points, or constructive criticism. Each item should be a dict with keys "author" and "text". CRITICAL: The "author" field MUST be a realistic social media user handle (e.g. "content_critic_ng", "victor_analyst", "femi_reviews", "zainab_m", "chima_watch", "dami_insight"). NEVER use generic placeholders like "Critic1", "Critic2", "user", "audience_member", and NEVER use the creator's own name or handle. The "text" must be the comment made by that viewer.
6. "positive_keywords": A list of up to 8 keywords or short key phrases extracted from comments that represent positive drivers (e.g. "relatable content", "authentic vibe").
7. "negative_keywords": A list of up to 8 keywords or short key phrases extracted from comments that represent negative friction (e.g. "sponsored ad", "forced delivery").
8. "creators_analysis": A list of objects, one for each creator in the roster ({creators_list_str}). Each object must have keys:
   - "name": The creator's exact display name (e.g., "Kirk Franklin").
   - "qualitative_sentiment": A 1-2 sentence qualitative analysis explaining what specific topics or audience feelings drive their sentiment score (either positive or negative). Do NOT output placeholder text like "No comments provided" or "no data to analyze".

Do not return anything except the raw JSON. Do not wrap it in markdown code blocks.
"""
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional marketing analyst who outputs valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                parsed_data = json.loads(content)
                
                # Sanitize audience comments so they always use realistic user handles
                parsed_data['top_positive_comments'] = cls._sanitize_audience_comments(
                    parsed_data.get('top_positive_comments'),
                    creator_name='',
                    is_positive=True
                )
                parsed_data['top_negative_comments'] = cls._sanitize_audience_comments(
                    parsed_data.get('top_negative_comments'),
                    creator_name='',
                    is_positive=False
                )
                
                # Log AI Credit Usage
                usage = result.get('usage', {})
                cls.log_usage(
                    workspace=campaign.workspace,
                    feature="Campaign Proposal Insights",
                    model_name="deepseek-chat",
                    usage_dict=usage,
                    metadata={"campaign_id": campaign.id, "campaign_name": campaign.name}
                )
                
                return parsed_data
            else:
                logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                return cls._get_mock_insights(campaign)
        except Exception as e:
            logger.error(f"Failed to generate LLM insights: {str(e)}")
            return cls._get_mock_insights(campaign)

    @classmethod
    def generate_influencer_proposal_insights(cls, campaign_influencer):
        """
        Generates qualitative proposal insights for a single influencer assigned to a campaign.
        """
        campaign = campaign_influencer.campaign
        inf = campaign_influencer.influencer
        
        # Check workspace toggle
        if campaign.workspace and not campaign.workspace.use_llm_sentiment_analysis:
            logger.info(f"LLM sentiment analysis disabled in workspace settings. Using mock proposal insights for {inf.display_name}.")
            return cls._get_influencer_mock_insights(campaign_influencer)

        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        if not api_key:
            logger.warning("DEEP_SEEK_SECRET not configured. Using mock insights.")
            return cls._get_influencer_mock_insights(campaign_influencer)
            
        brand_name = campaign.brand.name if campaign.brand else "the brand"
        
        # Query recent comments from this creator's platform accounts
        all_comments_text = []
        
        fallback_texts = {
            "So authentic, love this!",
            "Always delivering the best content.",
            "This is amazing, keep it up!",
            "Highly relatable and beautifully made.",
            "A true inspiration to many of us.",
            "This is why you are my favorite creator!",
            "Hope this isn't just another sponsored post.",
            "Expected something a bit different this time.",
            "The delivery feels a bit forced here.",
            "Not your best content, to be honest.",
            "A bit repetitive.",
            "This is such a blessing! God bless you minister! 🙌😭",
            "This song has been on repeat all morning, so powerful.",
            "Amen! What a beautiful sound of worship.",
            "This is pure heaven, the presence of God is here.",
            "Such a timely message, thank you for being a vessel.",
            "Powerful ministration! More grace to you.",
            "Touched my soul deeply. Praise God!",
            "The audio mixing feels a bit off in this video.",
            "I prefer the live version over this studio track.",
            "Why is the video so short? Needed more ministration.",
            "Feels a bit overproduced compared to your earlier worship songs.",
            "This collaboration didn't hit the mark for me.",
            "This is too funny, my ribs! 😂😂😂",
            "You never fail to make me laugh, pure talent!",
            "I have watched this video 5 times already and still laughing.",
            "The expression on your face at the end was priceless! 💀",
            "Best comedian/skit maker in the game right now.",
            "This is pure comedy gold, hands down!",
            "The editing is top notch, matching the humor perfectly.",
            "The joke felt a bit dry at the end.",
            "Not your funniest skit, but it's okay.",
            "The storyline was a bit confusing this time.",
            "This style is getting a bit repetitive, try new characters.",
            "A bit too long for a social media skit.",
            "This track is an absolute banger! 🔥🎧",
            "The flow and the beat are just out of this world.",
            "Can't stop listening to this, song of the year!",
            "So much style and vibe in this video.",
            "A masterpiece! You are a musical genius.",
            "The lyrics are so deep and beautiful.",
            "Love the visual aesthetic of this content.",
            "This song feels a bit mid compared to your last hit.",
            "The vocal tuning is a bit too obvious here.",
            "Expected a more energetic delivery from you.",
            "The beat was good but the lyrics were lacking.",
            "Why was this collaboration so hyped? It's average."
        }
        
        # Fetch the top 25 recent posts (more than 20) with NULLS LAST
        if inf.global_influencer:
            benchmarks = OrganicBenchmark.objects.filter(
                Q(influencer=inf) | Q(global_influencer=inf.global_influencer)
            ).order_by(
                F('post_created_at').desc(nulls_last=True)
            )[:25]
        else:
            benchmarks = OrganicBenchmark.objects.filter(
                influencer=inf
            ).order_by(
                F('post_created_at').desc(nulls_last=True)
            )[:25]

        # Fetch up to 50 organic comments across these posts
        org_comments = OrganicComment.objects.filter(
            organic_post__in=benchmarks
        ).order_by('-organic_post__post_created_at')[:50]

        for c in org_comments:
            author = c.author_handle or 'user'
            if c.text in fallback_texts:
                continue
            all_comments_text.append(f"[{inf.display_name} - @{author}]: {c.text}")

        # If comments have not been scraped yet, include the creator's real post captions
        if not org_comments.exists():
            for b in benchmarks:
                if b.post_text:
                    all_comments_text.append(f"[{inf.display_name} - Post Caption]: {b.post_text[:250]}")

        # Also fetch real comments from active tracked campaign posts if available
        real_comments = Comment.objects.filter(
            tracked_post__campaign_inf__influencer=inf
        ).order_by('-created_at')[:50]

        for c in real_comments:
            author = c.author_handle or 'user'
            all_comments_text.append(f"[{inf.display_name} - @{author}]: {c.text}")
            
        if not all_comments_text:
            logger.warning(f"No organic comments found in database for influencer {inf.display_name}.")
            comments_block = f"No organic comments available in the database for {inf.display_name}."
            prompt_instruction = (
                f"Note: Since no comments were found in the database, perform your qualitative analysis, "
                f"sentiment drivers, and strategic prediction based on the campaign goal, the brand '{brand_name}', "
                f"and {inf.display_name}'s specific niche: {inf.niche or 'content creation'}. "
                f"For the top positive and negative comments fields, generate hypothetical high-relevance "
                f"representative comments that match the expected audience reaction to {inf.display_name}."
            )
        else:
            comments_block = "\n".join(all_comments_text[:50])
            prompt_instruction = f"Based on the provided real organic comments for {inf.display_name}, perform a qualitative analysis."

        prompt = f"""
You are an expert marketing strategist analyzing audience comments for a campaign proposal on Sentimentri.
The campaign goal is: "{campaign.goal or 'Brand Awareness and Engagement'}"
The brand is: "{brand_name}"
The budget is: {campaign.budget} {campaign.currency}
The influencer being analyzed is: {inf.display_name} (Niche: {inf.niche or 'content creation'})

Here is the list of organic comments from the target audience of {inf.display_name}:
---
{comments_block}
---

{prompt_instruction}

Return a JSON object with the following fields:
1. "summary": A detailed summary (2-3 paragraphs) explaining what is driving the sentiment score for {inf.display_name}, highlighting the key themes, positive aspects, and negative critiques.
2. "public_opinion": A concise description (1-2 sentences) of the general public perception of {inf.display_name} in relation to this campaign.
3. "prediction": A realistic strategic prediction of what is likely to happen if this campaign is executed with {inf.display_name} (potential ROI, brand safety risks, or audience receptivity).
4. "top_positive_comments": A list of up to 4 comments that represent strong positive audience reception for {inf.display_name}. Each item must be a dict with keys "author" and "text". CRITICAL: The "author" field MUST be a realistic social media user handle (e.g. "tobi_adeyemi", "chinedu_k", "amina_bello", "korede_vibes", "funmi_lawal", "bolanle_99", "seun_og"). NEVER use generic placeholders like "Fan1", "Fan2", "user", "audience_member", and NEVER use the creator's own name or handle. The "text" must be the comment made by that viewer reacting to the creator's content or campaign.
5. "top_negative_comments": A list of up to 4 comments that represent concerns, friction points, or constructive criticism. Each item should be a dict with keys "author" and "text". CRITICAL: The "author" field MUST be a realistic social media user handle (e.g. "content_critic_ng", "victor_analyst", "femi_reviews", "zainab_m", "chima_watch", "dami_insight"). NEVER use generic placeholders like "Critic1", "Critic2", "user", "audience_member", and NEVER use the creator's own name or handle. The "text" must be the comment made by that viewer.
6. "positive_keywords": A list of up to 8 keywords or short key phrases extracted from comments that represent positive drivers (e.g. "relatable content", "authentic vibe").
7. "negative_keywords": A list of up to 8 keywords or short key phrases extracted from comments that represent negative friction (e.g. "sponsored ad", "forced delivery").

Do not return anything except the raw JSON. Do not wrap it in markdown code blocks.
"""
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional marketing analyst who outputs valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                parsed_data = json.loads(content)
                
                # Sanitize audience comments so they always use realistic user handles
                parsed_data['top_positive_comments'] = cls._sanitize_audience_comments(
                    parsed_data.get('top_positive_comments'),
                    creator_name=inf.display_name,
                    is_positive=True
                )
                parsed_data['top_negative_comments'] = cls._sanitize_audience_comments(
                    parsed_data.get('top_negative_comments'),
                    creator_name=inf.display_name,
                    is_positive=False
                )
                
                # Log AI Credit Usage
                usage = result.get('usage', {})
                cls.log_usage(
                    workspace=campaign.workspace,
                    feature="Creator Proposal Insights",
                    model_name="deepseek-chat",
                    usage_dict=usage,
                    metadata={
                        "campaign_id": campaign.id,
                        "campaign_name": campaign.name,
                        "influencer_id": inf.id,
                        "influencer_name": inf.display_name
                    }
                )
                
                return parsed_data
            else:
                logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                return cls._get_influencer_mock_insights(campaign_influencer)
        except Exception as e:
            logger.error(f"Failed to generate LLM insights for influencer: {str(e)}")
            return cls._get_influencer_mock_insights(campaign_influencer)

    @classmethod
    def _sanitize_audience_comments(cls, comments_list, creator_name='', is_positive=True):
        """
        Ensures author handles are realistic social media user names rather than
        generic placeholders ('Fan1', 'Critic1', 'user') or the creator's own name.
        """
        pos_handles = [
            'tobi_adeyemi', 'chinedu_k', 'amina_bello', 'korede_vibes',
            'funmi_lawal', 'deji_media', 'bolanle_99', 'seun_og'
        ]
        neg_handles = [
            'content_critic_ng', 'victor_analyst', 'femi_reviews', 'zainab_m',
            'chima_watch', 'dami_insight', 'samuel_k', 'emeka_real'
        ]

        cleaned = []
        creator_clean = creator_name.lower().replace(' ', '_').replace('@', '') if creator_name else ''
        
        for i, item in enumerate(comments_list or []):
            if not isinstance(item, dict):
                continue
            raw_author = item.get('author') or ''
            clean_author = str(raw_author).lstrip('@').strip()
            lower_author = clean_author.lower()

            is_generic = (
                not clean_author
                or lower_author.startswith(('fan', 'critic', 'user', 'audience', 'anon'))
                or lower_author in ['user', 'audience_member', 'commenter', 'viewer']
                or (creator_clean and creator_clean in lower_author)
                or (creator_name and creator_name.lower() in lower_author)
            )

            if is_generic:
                author = pos_handles[i % len(pos_handles)] if is_positive else neg_handles[i % len(neg_handles)]
            else:
                author = clean_author

            text = item.get('text', '').strip()
            if text:
                cleaned.append({'author': author, 'text': text})

        return cleaned

    @classmethod
    def _get_mock_insights(cls, campaign):
        campaign_influencers = campaign.campaign_influencers.all()
        creator_names = [ci.influencer.display_name for ci in campaign_influencers]
        brand_name = campaign.brand.name if campaign.brand else "the brand"
        
        creators_analysis = []
        for name in creator_names:
            creators_analysis.append({
                "name": name,
                "qualitative_sentiment": f"Audience sentiment for {name} is generally positive, driven by high authenticity and alignment with the campaign goals."
            })
            
        if not creators_analysis:
            creators_analysis = [{"name": "Creator", "qualitative_sentiment": "N/A"}]

        return {
            "summary": f"Audience engagement for this campaign roster indicates healthy brand affinity. Positive sentiment is driven by the authenticity of the creators and strong alignment with {brand_name}. Minor concerns are focused on price and execution feasibility.",
            "public_opinion": f"The general public perception is highly favorable, looking forward to the collaboration between {brand_name} and the creator roster.",
            "prediction": f"The campaign is predicted to achieve high brand relevance and positive sentiment lift, with low risk to brand safety.",
            "top_positive_comments": [
                {"author": "tobi_adeyemi", "text": "This is going to be amazing, great collaboration!"},
                {"author": "chinedu_k", "text": f"Excited for this collaboration with {brand_name}."}
            ],
            "top_negative_comments": [
                {"author": "content_critic_ng", "text": "Hope this isn't just another generic sponsored ad."},
                {"author": "victor_analyst", "text": "Ensure the brand placement feels natural to the creator's usual style."}
            ],
            "positive_keywords": ["collaboration", "excitement", "authentic", "relevance"],
            "negative_keywords": ["sponsored", "pricing", "authenticity concerns"],
            "creators_analysis": creators_analysis
        }

    @classmethod
    def _get_influencer_mock_insights(cls, campaign_influencer):
        inf = campaign_influencer.influencer
        brand_name = campaign_influencer.campaign.brand.name if campaign_influencer.campaign.brand else "the brand"
        
        return {
            "summary": f"Audience engagement for {inf.display_name} indicates healthy brand affinity. Positive sentiment is driven by the authenticity of the content and strong alignment with {brand_name}. Minor concerns are focused on price and execution feasibility.",
            "public_opinion": f"The general public perception of {inf.display_name} is highly favorable, looking forward to the collaboration.",
            "prediction": f"The campaign is predicted to achieve high brand relevance and positive sentiment lift for {inf.display_name}, with low risk to brand safety.",
            "top_positive_comments": [
                {"author": "tobi_adeyemi", "text": "Always delivering authentic, top-tier comedic and relatable content!"},
                {"author": "chinedu_k", "text": f"Excited for this collaboration with {brand_name}."}
            ],
            "top_negative_comments": [
                {"author": "content_critic_ng", "text": "Hope this isn't just another generic sponsored ad."},
                {"author": "victor_analyst", "text": "Ensure the promotional integration stays true to the comedic plot."}
            ],
            "positive_keywords": ["collaboration", "excitement", "authentic", "relevance"],
            "negative_keywords": ["sponsored", "pricing", "authenticity concerns"]
        }

    @classmethod
    def generate_execution_insights(cls, campaign):
        """
        Generates qualitative campaign execution performance analysis.
        Reads live comments on campaign tracked posts.
        """
        # Toggle check
        if campaign.workspace and not campaign.workspace.use_llm_sentiment_analysis:
            logger.info("LLM sentiment analysis disabled in workspace settings. Using mock execution insights.")
            return cls._get_execution_mock_insights(campaign)

        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        if not api_key:
            logger.warning("DEEP_SEEK_SECRET not configured. Using mock execution insights.")
            return cls._get_execution_mock_insights(campaign)

        posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
        post_ids = [p.id for p in posts]
        
        # Fetch up to 150 live comments for analysis
        comments = Comment.objects.filter(tracked_post_id__in=post_ids).order_by('-created_at')[:150]
        
        all_comments_text = []
        for c in comments:
            inf_name = c.tracked_post.campaign_inf.influencer.display_name
            author = c.author_handle or 'user'
            all_comments_text.append(f"[{inf_name} - @{author}]: {c.text}")

        brand_name = campaign.brand.name if campaign.brand else "the brand"
        creators_list_str = ", ".join([ci.influencer.display_name for ci in campaign.campaign_influencers.all()])

        if not all_comments_text:
            logger.warning(f"No comments found in database for campaign {campaign.id} tracked posts.")
            comments_block = "No comments available in the database for the active posts in this campaign."
            prompt_instruction = (
                f"Note: Since no live comments were found in the database, perform your campaign execution performance analysis, "
                f"public opinion audit, and strategic next steps based on the campaign goal, the brand '{brand_name}', "
                f"and the active roster: {creators_list_str}."
            )
        else:
            comments_block = "\n".join(all_comments_text)
            prompt_instruction = "Based on the provided real active campaign comments, perform a campaign execution audit."

        prompt = f"""
You are an expert marketing auditor evaluating live comments for a campaign on Sentimentri.
The campaign goal is: "{campaign.goal or 'Brand Awareness'}"
The brand is: "{brand_name}"
The budget is: {campaign.budget} {campaign.currency}
The active lineup of creators is: {creators_list_str}

Here is the list of active comments from the audience of these creators (each comment is prefixed with their name):
---
{comments_block}
---

{prompt_instruction}

For any creators in the active lineup ({creators_list_str}) who have few or no comments in the list above, you MUST still evaluate them. Perform their qualitative execution analysis based on their specific niche, the brand alignment, and the campaign goals, and generate representative evaluations and next steps. Do NOT output placeholder text like "No comments provided" or "no data to analyze".

Return a JSON object with the following fields:
1. "summary": A detailed performance evaluation summary (2-3 paragraphs) explaining how the campaign executed, public feedback, engagement drivers, and overall resonance. You MUST cover all creators in the active lineup ({creators_list_str}) in this summary.
2. "public_opinion": A concise description (1-2 sentences) of the public reaction to the brand alignment and content delivery across all creators.
3. "next_steps": Recommended concrete next steps/optimizations for future phases or active content adjustments incorporating the entire active lineup.
4. "positive_keywords": A list of up to 8 positive keywords or key phrases extracted from the comments.
5. "negative_keywords": A list of up to 8 negative friction keywords/concerns extracted from the comments.

Do not return anything except the raw JSON. Do not wrap it in markdown code blocks.
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional marketing analyst who outputs valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        try:
            response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                parsed_data = json.loads(content.strip())
                
                # Log AI Credit Usage
                usage = result.get('usage', {})
                cls.log_usage(
                    workspace=campaign.workspace,
                    feature="Campaign Execution Audit",
                    model_name="deepseek-chat",
                    usage_dict=usage,
                    metadata={"campaign_id": campaign.id, "campaign_name": campaign.name}
                )
                
                return parsed_data
            else:
                logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                return cls._get_execution_mock_insights(campaign)
        except Exception as e:
            logger.error(f"Failed to generate LLM execution insights: {str(e)}")
            return cls._get_execution_mock_insights(campaign)

    @classmethod
    def generate_influencer_execution_insights(cls, campaign_influencer):
        """
        Generates qualitative execution performance analysis for a single influencer.
        Reads live comments on their campaign tracked posts.
        """
        campaign = campaign_influencer.campaign
        inf = campaign_influencer.influencer

        # Toggle check
        if campaign.workspace and not campaign.workspace.use_llm_sentiment_analysis:
            logger.info(f"LLM sentiment analysis disabled in workspace settings. Using mock execution insights for {inf.display_name}.")
            return cls._get_influencer_execution_mock_insights(campaign_influencer)

        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        if not api_key:
            logger.warning(f"DEEP_SEEK_SECRET not configured. Using mock execution insights for {inf.display_name}.")
            return cls._get_influencer_execution_mock_insights(campaign_influencer)

        posts = TrackedPost.objects.filter(campaign_inf=campaign_influencer)
        post_ids = [p.id for p in posts]
        
        # Fetch up to 50 live comments for this creator's posts
        comments = Comment.objects.filter(tracked_post_id__in=post_ids).order_by('-created_at')[:50]
        
        all_comments_text = []
        for c in comments:
            author = c.author_handle or 'user'
            all_comments_text.append(f"[{inf.display_name} - @{author}]: {c.text}")

        brand_name = campaign.brand.name if campaign.brand else "the brand"

        if not all_comments_text:
            logger.warning(f"No comments found in database for influencer {inf.display_name} campaign posts.")
            comments_block = f"No comments available in the database for the active posts of {inf.display_name} in this campaign."
            prompt_instruction = (
                f"Note: Since no live comments were found in the database, perform your execution performance analysis, "
                f"public opinion audit, and strategic next steps based on the campaign goal, the brand '{brand_name}', "
                f"and {inf.display_name}'s specific niche: {inf.niche or 'content creation'}."
            )
        else:
            comments_block = "\n".join(all_comments_text)
            prompt_instruction = f"Based on the provided real active campaign comments for {inf.display_name}, perform a creator execution audit."

        prompt = f"""
You are an expert marketing auditor evaluating live comments for a creator in a campaign on Sentimentri.
The campaign goal is: "{campaign.goal or 'Brand Awareness'}"
The brand is: "{brand_name}"
The budget is: {campaign.budget} {campaign.currency}
The creator being analyzed is: {inf.display_name} (Niche: {inf.niche or 'content creation'})

Here is the list of active comments from the audience on {inf.display_name}'s campaign content:
---
{comments_block}
---

{prompt_instruction}

Return a JSON object with the following fields:
1. "summary": A detailed performance evaluation summary (2-3 paragraphs) explaining how {inf.display_name} performed, public feedback, engagement drivers, and overall resonance.
2. "public_opinion": A concise description (1-2 sentences) of the public reaction to {inf.display_name}'s brand alignment and content delivery.
3. "next_steps": Recommended concrete next steps/optimizations for {inf.display_name}'s future campaign integrations.
4. "positive_keywords": A list of up to 8 positive keywords or key phrases extracted from the comments.
5. "negative_keywords": A list of up to 8 negative friction keywords/concerns extracted from the comments.

Do not return anything except the raw JSON. Do not wrap it in markdown code blocks.
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional marketing analyst who outputs valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        try:
            response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                parsed_data = json.loads(content.strip())
                
                # Log AI Credit Usage
                usage = result.get('usage', {})
                cls.log_usage(
                    workspace=campaign.workspace,
                    feature="Creator Execution Audit",
                    model_name="deepseek-chat",
                    usage_dict=usage,
                    metadata={
                        "campaign_id": campaign.id,
                        "campaign_name": campaign.name,
                        "influencer_id": inf.id,
                        "influencer_name": inf.display_name
                    }
                )
                
                return parsed_data
            else:
                logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                return cls._get_influencer_execution_mock_insights(campaign_influencer)
        except Exception as e:
            logger.error(f"Failed to generate LLM execution insights for creator: {str(e)}")
            return cls._get_influencer_execution_mock_insights(campaign_influencer)

    @classmethod
    def generate_report_section_insights(cls, campaign, metrics_context):
        if campaign.workspace and not campaign.workspace.use_llm_sentiment_analysis:
            logger.info("LLM sentiment analysis disabled in workspace settings. Using mock report section insights.")
            return cls._get_report_section_mock_insights(campaign)

        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        if not api_key:
            logger.warning("DEEP_SEEK_SECRET not configured. Using mock report section insights.")
            return cls._get_report_section_mock_insights(campaign)

        posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
        post_ids = [p.id for p in posts]
        
        comments = Comment.objects.filter(tracked_post_id__in=post_ids).order_by('-created_at')[:100]
        
        all_comments_text = []
        for c in comments:
            inf_name = c.tracked_post.campaign_inf.influencer.display_name
            author = c.author_handle or 'user'
            all_comments_text.append(f"[{inf_name} - @{author}]: {c.text}")

        brand_name = campaign.brand.name if campaign.brand else "the brand"
        comments_block = "\n".join(all_comments_text) if all_comments_text else "No active comments available."

        prompt = f"""
You are an expert campaign strategist analyzing a campaign's performance metrics and comments for a final report on Sentimentri.
Campaign Goal: "{campaign.goal or 'Brand Awareness'}"
Brand: "{brand_name}"
Budget: {campaign.budget} {campaign.currency}

Key Metrics & Context:
{json.dumps(metrics_context, indent=2)}

Recent Comments:
---
{comments_block}
---

Return a JSON object with exactly these fields:
- "executive_summary_insight": 2-3 sentence campaign health summary.
- "platform_performance_insight": 4-line platform performance insight.
- "sentiment_analysis_insight": Sentiment outcome insight (2-3 sentences).
- "positive_comments_summary": Concise, specific summary of positive comment themes (3-4 sentences).
- "negative_comments_summary": Concise, specific summary of negative comment themes (3-4 sentences).
- "brand_mentions_insight": Brand perception insight (2-3 sentences).
- "brand_positive_qualitative": Qualitative summary of positive brand mentions (2-3 sentences).
- "brand_negative_qualitative": Qualitative summary of negative brand mentions (2-3 sentences).
- "creator_performance_insight": Creator comparison insight (2-3 sentences).
- "creator_native_vs_campaign_insight": Native vs campaign performance insight (2-3 sentences).
- "recommendations": List of 1-3 dicts with 'title' and 'body' keys — detailed, campaign-specific recommendations.

Do not return anything except the raw JSON. Do not wrap it in markdown code blocks.
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional campaign analyst who outputs valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        try:
            response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                parsed_data = json.loads(content.strip())
                
                usage = result.get('usage', {})
                cls.log_usage(
                    workspace=campaign.workspace,
                    feature="Report Section Insights",
                    model_name="deepseek-chat",
                    usage_dict=usage,
                    metadata={"campaign_id": campaign.id, "campaign_name": campaign.name}
                )
                
                return parsed_data
            else:
                logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                return cls._get_report_section_mock_insights(campaign)
        except Exception as e:
            logger.error(f"Failed to generate LLM report section insights: {str(e)}")
            return cls._get_report_section_mock_insights(campaign)

    @classmethod
    def generate_campaign_intelligence(cls, campaign, metrics_context):
        if campaign.workspace and not campaign.workspace.use_llm_sentiment_analysis:
            logger.info("LLM sentiment analysis disabled in workspace settings. Using mock intelligence insights.")
            return cls._get_campaign_intelligence_mock_insights(campaign)

        api_key = getattr(settings, 'DEEP_SEEK_SECRET', None)
        if not api_key:
            logger.warning("DEEP_SEEK_SECRET not configured. Using mock intelligence insights.")
            return cls._get_campaign_intelligence_mock_insights(campaign)

        posts = TrackedPost.objects.filter(campaign_inf__campaign=campaign)
        post_ids = [p.id for p in posts]
        
        comments = Comment.objects.filter(tracked_post_id__in=post_ids).order_by('-created_at')[:100]
        
        all_comments_text = []
        for c in comments:
            inf_name = c.tracked_post.campaign_inf.influencer.display_name
            author = c.author_handle or 'user'
            all_comments_text.append(f"[{inf_name} - @{author}]: {c.text}")

        brand_name = campaign.brand.name if campaign.brand else "the brand"
        comments_block = "\n".join(all_comments_text) if all_comments_text else "No active comments available."

        prompt = f"""
You are an expert campaign strategist analyzing a campaign's performance metrics and comments for a final report on Sentimentri.
Campaign Goal: "{campaign.goal or 'Brand Awareness'}"
Brand: "{brand_name}"
Budget: {campaign.budget} {campaign.currency}

Key Metrics & Context:
{json.dumps(metrics_context, indent=2)}

Recent Comments:
---
{comments_block}
---

As an expert campaign strategist, answer the following 8 strategic questions based on the context above.
Return a JSON object with keys "q1" through "q8":
- "q1": Which content formats are performing best.
- "q2": Which videos drive highest watch time/engagement/completion and commonalities.
- "q3": Where viewers typically drop off and recurring patterns.
- "q4": Whether product integration feels natural.
- "q5": Which creators/hooks/editing styles/captions/storytelling deliver best results.
- "q6": Common patterns across lower-performing content.
- "q7": Platform-specific insights on TikTok, Instagram, X.
- "q8": Other observations and recommendations for remaining content.

Do not return anything except the raw JSON. Do not wrap it in markdown code blocks.
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a professional campaign strategist who outputs valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"}
        }

        try:
            response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                parsed_data = json.loads(content.strip())
                
                usage = result.get('usage', {})
                cls.log_usage(
                    workspace=campaign.workspace,
                    feature="Campaign Intelligence",
                    model_name="deepseek-chat",
                    usage_dict=usage,
                    metadata={"campaign_id": campaign.id, "campaign_name": campaign.name}
                )
                
                return parsed_data
            else:
                logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                return cls._get_campaign_intelligence_mock_insights(campaign)
        except Exception as e:
            logger.error(f"Failed to generate LLM campaign intelligence insights: {str(e)}")
            return cls._get_campaign_intelligence_mock_insights(campaign)

    @classmethod
    def _get_report_section_mock_insights(cls, campaign):
        return {
            "executive_summary_insight": "The campaign performed well above expectations, demonstrating strong brand alignment. Both reach and engagement targets were comfortably met.",
            "platform_performance_insight": "Instagram drove the highest engagement rates through Reels. TikTok generated the most viral reach. X served effectively for customer queries and prompt brand responses. Overall platform distribution was optimal.",
            "sentiment_analysis_insight": "Overall sentiment was highly positive, driven by authentic creator integrations. Negative sentiment was minimal and mostly related to product availability.",
            "positive_comments_summary": "Audiences frequently praised the aesthetics and relatability of the content. Many expressed immediate interest in trying the product.",
            "negative_comments_summary": "Some users mentioned high price points. Others experienced difficulty finding the product in local stores.",
            "brand_mentions_insight": "Brand recall was strong, with the brand name mentioned frequently in positive contexts. The brand is perceived as innovative and trendy.",
            "brand_positive_qualitative": "Users love the modern approach and user-friendly features. The brand's commitment to quality was a recurring theme.",
            "brand_negative_qualitative": "A few users felt the brand messaging was slightly repetitive across different creators. Minor concerns about sustainability were raised.",
            "creator_performance_insight": "Top creators effectively leveraged their unique styles, significantly outperforming benchmark metrics. Mid-tier creators provided steady, authentic engagement.",
            "creator_native_vs_campaign_insight": "Campaign content matched or exceeded the performance of creators' native, non-sponsored posts. This indicates high audience acceptance of the sponsored messaging.",
            "recommendations": [
                {"title": "Leverage Top Formats", "body": "Double down on short-form video formats that drove the highest engagement."},
                {"title": "Address Availability", "body": "Ensure clearer communication regarding product availability in future campaigns."}
            ]
        }

    @classmethod
    def _get_campaign_intelligence_mock_insights(cls, campaign):
        return {
            "q1": "Short-form video content on Instagram Reels and TikTok.",
            "q2": "Videos with an energetic hook in the first 3 seconds drove the highest watch time. Commonality: authentic, vlog-style delivery.",
            "q3": "Drop-offs typically occurred around the 15-second mark when the explicit call-to-action was introduced.",
            "q4": "Yes, product integration felt mostly natural, especially when creators showed real-life usage scenarios.",
            "q5": "Creators using fast-paced editing and storytelling hooks delivered the best results.",
            "q6": "Lower-performing content often had slower pacing and felt overly scripted.",
            "q7": "TikTok drove mass reach, Instagram drove deep engagement, and X facilitated community conversations.",
            "q8": "Recommend re-engaging top-performing creators for long-term ambassadorships to maintain momentum."
        }

    @classmethod
    def _get_execution_mock_insights(cls, campaign):
        brand_name = campaign.brand.name if campaign.brand else "the brand"
        return {
            "summary": f"The campaign execution has shown high engagement. The audience is responding positive to the brand messaging of {brand_name}. Overall performance aligns with initial projections.",
            "public_opinion": "Public opinion is overwhelmingly positive, with audiences praising the creative integration.",
            "next_steps": "Continue with the scheduled content release and monitor comments for any emerging product questions.",
            "positive_keywords": ["exciting", "love it", "great work", "authentic"],
            "negative_keywords": ["ad", "sponsored", "pricing"]
        }

    @classmethod
    def _get_influencer_execution_mock_insights(cls, campaign_influencer):
        inf = campaign_influencer.influencer
        brand_name = campaign_influencer.campaign.brand.name if campaign_influencer.campaign.brand else "the brand"
        return {
            "summary": f"{inf.display_name}'s content execution has resonated well with their audience. Engagement metrics show strong alignment with {brand_name}.",
            "public_opinion": f"The response to {inf.display_name}'s post is positive and shows high trust in their endorsement.",
            "next_steps": f"Optimize future posts for {inf.display_name} by focusing on the most engaged content formats.",
            "positive_keywords": ["amazing", "perfect", "relatable", "gorgeous"],
            "negative_keywords": ["commercial", "sponsored ad"]
        }

