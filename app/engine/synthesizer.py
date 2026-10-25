import re
from typing import Dict, Any, List
from google import genai
from google.genai import types
from app.config import settings
from app.database import get_conn
from app.engine.schemas import TriageResult, SynthesizedDraft

FALLBACK_TRIAGE_MODELS = [
    settings.TRIAGE_MODEL,
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

FALLBACK_SYNTHESIS_MODELS = [
    settings.SYNTHESIS_MODEL,
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
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
        """模型自动容错回退机制，遇到弃用自动抓取 Google 官方报错推荐的新模型并自动重试"""
        last_err = None
        seen_models = set()
        queue = list(candidate_models)

        while queue:
            model_name = queue.pop(0)
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
                err_str = str(e)
                print(f"      [AI 降级重试] 模型 {model_name} 暂不可用 ({err_str[:120]}...)，尝试备选模型...")
                # 动态自适应：从 Google 官方错误信息中自动嗅探推荐的新模型（如 gemini-3.1-pro-preview）
                recommended = re.findall(r'models/([a-zA-Z0-9.-]+)', err_str)
                for rec in recommended:
                    if rec not in seen_models and rec not in queue and "gemini" in rec:
                        print(f"      💡 [动态自适应] 捕获到 Google 官方推荐新模型: {rec}，已排入优先调用队列！")
                        queue.insert(0, rec)
        raise last_err

    def quick_triage(self, signal: Dict[str, Any]) -> TriageResult:
        """二级漏斗：严格拦截纯求助帖、散户情绪水帖与平庸玩具项目，只放行高信噪比商业爆款素材"""
        is_github = signal.get("category") == "GITHUB_TRENDING"
        
        if is_github:
            prompt = f"""
You are an elite X (Twitter) Tech & Venture Capital Content Director evaluating organic viral and monetization potential.
Evaluate if this trending GitHub repository has high technical utility, real-world architecture value, or commercial/dev appeal suitable for an insightful breakdown on X.

CRITERIA:
- PASS if it solves an expensive problem, introduces novel architecture, or challenges commercial SaaS.
- REJECT if it is an empty toy repo, simple link/awesome collection, homework project, or spam.

Repository: {signal['title']}
README Excerpt:
{signal['selftext'][:1000]}
"""
        else:
            prompt = f"""
You are an elite X (Twitter) Growth Director evaluating organic viral, high-bookmark, and high-CPM impression potential for a senior Tech & Finance audience.

STRICT PASS CRITERIA (Must meet at least one):
1. Empirical benchmark data, real production post-mortems, or unit economics breakdown.
2. Fierce practitioner controversy, institutional vs retail divergence, or high bull/bear tension.
3. Breaking macro, energy/commodity bottleneck (oil, gold, nuclear grid), or major infrastructure inflection.

STRICT REJECT CRITERIA:
- Beginner "how-to" help questions, basic configuration bugs, simple code help ("how do I install X?").
- Low-effort emotional rants without hard data or numbers ("I hate this update", "market is rigged").
- Generic PR marketing fluff or trivial meme jokes.

Subreddit: r/{signal['subreddit']} ({signal['category']})
Title: {signal['title']}
Content snippet: {signal['selftext'][:700]}
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

### EXECUTION RULES (ENGINEERED FOR VIRAL X ALGORITHM & MONETIZATION)
1. **THE 3 HOOK OPTIONS (Click-Through & Open-Fold Multiplier)**:
   - Hook 1 (Counter-Consensus Shock): Violently contrast mainstream consensus against ground reality with empirical proof ("Everyone assumes X, but production telemetry proves Y:").
   - Hook 2 (Commercial Economics & Dollar Cost): Attack unit economics, hidden costs, or margin erosion ("Stop burning $X/month on... The real compute math is:").
   - Hook 3 (Practitioner / Trader Post-Mortem): First-person insider observation ("After profiling 5,000 requests on our cluster / After dissecting the latest CFTC positioning data...").
2. **DUAL-FORMAT DRAFTING**:
   - `short_post`: Exactly 60-120 words. Ultra-punchy, high-contrast, zero fluff. Optimized for fast mobile consumption.
   - `long_form_body`: Exactly 250-400 words. Structured with clean '•' bullets, high information density, designed as a "Bookmark Magnet" (30x algorithm weight).
3. **NO REPOST TRACES**: Never mention "Reddit", "r/{signal['subreddit']}", or "a user posted". Write from first-person insider authority ("Engineers deploying X are hitting a wall...", "The smartest debate around $TICKER right now...").
4. **CROSS-DOMAIN REALITY CHECK (Your Unique Alpha)**:
   - When topic is AI/Dev: Always link architecture choices to VRAM, token latency, energy/power draw, and SaaS margins.
   - When topic is US Stocks/Macro: Apply an engineer's first-principles data mindset to dissect earnings quality, institutional 13F positioning, and asymmetric risk/reward.
   - When topic is Energy/Commodities (Oil, Gold, Uranium): Directly connect the datacenter power bottleneck (grid capacity, natural gas, uranium SMRs) to AI scaling, and evaluate gold/fiat debasement against tech multiples.
   - When topic is Crypto: Focus strictly on real protocol revenue, fee cash flow, and on-chain liquidity depth, discarding meme slop.
5. **THE ENGAGEMENT CLOSER (75x Algorithm Weight - Verified Reply Magnet)**:
   - End the post with a sharp, polarizing question or controversial tradeoff that forces practitioners and traders to reply in the comments!
6. **REPLY SNIPER + X SEARCH QUERY**:
   - Craft `reply_sniper_text` (60-90 words) packed with the sharpest counter-intuitive data point from the comments so the user can drop it under big X influencers' posts to farm Verified followers.
   - Craft `x_search_query` using 1-2 core keywords/tickers from this topic + `min_faves:30 -filter:replies lang:en` so the user can 1-click find viral tweets to reply to right now.
7. **BANNED AI SLOP WORDS**: Strictly forbidden: {persona['banned_words']}.
"""

        resp = self._generate_with_fallback(prompt, SynthesizedDraft, FALLBACK_SYNTHESIS_MODELS, temperature=0.7)
        draft_obj = SynthesizedDraft.model_validate_json(resp.text)
        return draft_obj.model_dump()
