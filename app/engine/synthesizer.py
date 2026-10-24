from typing import Dict, Any, List
from google import genai
from google.genai import types
from app.config import settings
from app.database import get_conn
from app.engine.schemas import TriageResult, SynthesizedDraft

FALLBACK_TRIAGE_MODELS = [
    settings.TRIAGE_MODEL,
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

FALLBACK_SYNTHESIS_MODELS = [
    settings.SYNTHESIS_MODEL,
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]


class SynthesisEngine:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _get_default_persona(self) -> Dict[str, Any]:
        conn = get_conn()
        row = conn.execute("SELECT * FROM personas WHERE is_default = 1 LIMIT 1").fetchone()
        conn.close()
        return dict(row)

    def _generate_with_fallback(self, contents: str, schema_class, candidate_models: List[str], temperature: float = 0.5):
        """模型自动容错回退机制，确保 API Key 无论处于哪种权限均能平滑调用"""
        last_err = None
        seen_models = set()
        for model_name in candidate_models:
            if not model_name or model_name in seen_models:
                continue
            seen_models.add(model_name)
            try:
                resp = self.client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema_class,
                        temperature=temperature,
                    ),
                )
                return resp
            except Exception as e:
                last_err = e
                print(f"      [AI 降级重试] 模型 {model_name} 暂不可用 ({e})，尝试备选模型...")
        raise last_err

    def quick_triage(self, signal: Dict[str, Any]) -> TriageResult:
        """二级漏斗：用极低成本的 Flash 模型拦截纯求助帖、情绪宣泄水贴或低价值项目"""
        is_github = signal.get("category") == "GITHUB_TRENDING"
        
        if is_github:
            prompt = f"""
Evaluate if this trending GitHub repository has high technical utility, real-world architecture value, or commercial/dev appeal suitable for an insightful breakdown on X (Twitter).
Reject if it is an empty toy repo, simple link collection, or spam.

Repository: {signal['title']}
Context & README Excerpt:
{signal['selftext'][:1000]}
"""
        else:
            prompt = f"""
Evaluate if this community thread has enough substance, industry alpha, benchmark data, or fascinating debate to be synthesized into a high-performing X post for a Tech & Finance audience.

Subreddit: r/{signal['subreddit']} ({signal['category']})
Title: {signal['title']}
Content snippet: {signal['selftext'][:600]}
"""
        try:
            resp = self._generate_with_fallback(prompt, TriageResult, FALLBACK_TRIAGE_MODELS, temperature=0.2)
            return TriageResult.model_validate_json(resp.text)
        except Exception as e:
            print(f"      [初筛失败] 所有初筛模型异常: {e}，默认放行交由深度合成。")
            return TriageResult(pass_triage=True, reason="初筛异常默认放行")

    def synthesize(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        # 先过 Flash 初筛漏斗
        triage = self.quick_triage(signal)
        if not triage.pass_triage:
            return {
                "is_worth_posting": False,
                "skip_reason": f"[Flash 初筛拦截] {triage.reason}",
                "narrative_framework": "Contrarian Reality Check",
                "content_tier": "FLASH_PUNCH",
                "hook_options": [],
                "short_post": "",
                "long_form_body": "",
                "reply_sniper_text": "",
                "x_search_query": "",
                "visual_card_title": "",
                "visual_card_type": "terminal_benchmark",
                "visual_card_metrics": [],
            }

        persona = self._get_default_persona()
        is_github = signal.get("category") == "GITHUB_TRENDING"

        if is_github:
            prompt = f"""
### YOUR PERSONA & CROSS-DOMAIN ANGLE
{persona['system_prompt']}

### TARGET GITHUB REPOSITORY TO TEARDOWN
- Title & Language: {signal['title']} | Primary Lang: {signal['flair']}
- Momentum: {signal['score']} stars today ({signal['velocity']} stars/hr)
- Project URL: {signal['permalink']}
- Source Intelligence & README Content:
{signal['selftext'][:3500]}

### CRITICAL RULES FOR GITHUB CURATION WITH PERSONAL VERDICT:
1. **NARRATIVE FRAMEWORK & TIER**:
   - `narrative_framework`: Select "Repo Teardown & Production Verdict".
   - `content_tier`: Assess information density. If it's a simple lightweight utility, use `FLASH_PUNCH`. If it's a deep framework, use `DEEP_DIVE_MEMO`.
2. **THE HOOK**: Never write "Check out this repo". Instead, attack a painful problem or contrast it against expensive commercial SaaS (e.g., "Stop paying $X/month for...", "Most engineers deploying X don't realize this open-source repo just solved the latency bottleneck:").
3. **DUAL-FORMAT DRAFTING (CRUCIAL)**:
   - `short_post`: Exactly 60-120 words. Ultra-punchy, single core problem solved, stack + star momentum, direct link/verdict. High read-through rate.
   - `long_form_body`: Exactly 250-400 words. Deep architecture teardown in clean '•' bullets, production tradeoffs, compute economics, and personal production verdict. High bookmark magnet.
4. **PERSONAL VERDICT & BUSINESS IMPLICATION (Your Unique Alpha)**:
   - Provide your sharp verdict: Is it production-ready or experimental?
   - What are the compute/unit economics?
   - Who should adopt or fork this right now?
   - Mention license implications if relevant.
5. **VISUAL CARD PROTOCOL**: Set `visual_card_type` to "github_repo_card". Provide 4 sharp metrics in `visual_card_metrics` (e.g. "Primary Stack", "Star Velocity", "License/Safety", "Production Verdict").
6. **REPLY SNIPER & X SEARCH**:
   - Provide a 60-80 word technical insight to reply under big tech influencers discussing this space.
   - Provide an X search query with core keywords (e.g. repo name or tech concept) + `min_faves:30 -filter:replies lang:en`.
7. **BANNED AI SLOP WORDS**: Strictly forbidden: {persona['banned_words']}.
"""
        else:
            comments_block = "\n".join(signal.get("top_comments", [])) or "No top comments yet."
            prompt = f"""
### YOUR PERSONA & CROSS-DOMAIN ANGLE
{persona['system_prompt']}

### SOURCE INTELLIGENCE (Category: {signal['category']})
- Community Context: r/{signal['subreddit']} | Flair: {signal['flair']}
- Engagement Velocity: {signal['score']} upvotes ({signal['velocity']}/min) | {signal['num_comments']} comments (Controversy: {signal['controversy']})
- Topic Title: {signal['title']}
- Main Post Content:
{signal['selftext'] or '[Link/Data Post - Refer to Title and Practitioner Comments]'}

- Top Practitioner Comments & Pushback:
{comments_block}

### EXECUTION RULES (CRITICAL FOR X MONETIZATION & GROWTH)
1. **CONTENT TIER & DUAL-FORMAT**:
   - Set `content_tier`:
     * `FLASH_PUNCH`: Rapid data point, single anomaly or breaking event (best for 60-120 words).
     * `DEBATE_ROUNDTABLE`: Fierce community clash or bull vs bear dispute (best for 150-220 words).
     * `DEEP_DIVE_MEMO`: Complex engineering post-mortem or multi-factor capital thesis (best for 280-400 words).
   - Generate `short_post`: 60-120 words high-density punch for mobile reading.
   - Generate `long_form_body`: 250-400 words comprehensive breakdown synthesizing main post + top comment pushbacks.
2. **NO REPOST TRACES**: Never mention "Reddit", "r/{signal['subreddit']}", or "a user posted". Write from first-person insider observation ("Engineers deploying X are hitting a wall...", "The smartest debate around $TICKER right now...").
3. **BRIDGE AI & CAPITAL**: Even if the topic is pure AI coding, briefly connect it to compute economics, SaaS moats, or capex. Even if it's pure stock trading, dissect it with systematic/engineering rigor.
4. **REPLY SNIPER + X SEARCH QUERY**:
   - Craft `reply_sniper_text` (60-90 words) packed with the sharpest counter-intuitive data point from the comments so the user can drop it under big X influencers' posts to farm Verified followers.
   - Craft `x_search_query` using 1-2 core keywords/tickers from this topic + `min_faves:50 -filter:replies lang:en` so the user can 1-click find viral tweets to reply to right now.
5. **BANNED AI SLOP WORDS**: Strictly forbidden: {persona['banned_words']}.
"""

        resp = self._generate_with_fallback(prompt, SynthesizedDraft, FALLBACK_SYNTHESIS_MODELS, temperature=0.7)
        draft_obj = SynthesizedDraft.model_validate_json(resp.text)
        return draft_obj.model_dump()
