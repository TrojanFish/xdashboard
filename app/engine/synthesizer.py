from typing import Dict, Any
from google import genai
from google.genai import types
from app.config import settings
from app.database import get_conn
from app.engine.schemas import TriageResult, SynthesizedDraft


class SynthesisEngine:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _get_default_persona(self) -> Dict[str, Any]:
        conn = get_conn()
        row = conn.execute("SELECT * FROM personas WHERE is_default = 1 LIMIT 1").fetchone()
        conn.close()
        return dict(row)

    def quick_triage(self, signal: Dict[str, Any]) -> TriageResult:
        """二级漏斗：用极低成本的 Flash 模型拦截纯求助帖、情绪宣泄水贴"""
        prompt = f"""
Evaluate if this community thread has enough substance, industry alpha, benchmark data, or fascinating debate to be synthesized into a high-performing X post for a Tech & Finance audience.

Subreddit: r/{signal['subreddit']} ({signal['category']})
Title: {signal['title']}
Content snippet: {signal['selftext'][:600]}
"""
        resp = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TriageResult,
                temperature=0.2,
            ),
        )
        return TriageResult.model_validate_json(resp.text)

    def synthesize(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        # 先过 Flash 初筛漏斗
        triage = self.quick_triage(signal)
        if not triage.pass_triage:
            return {
                "is_worth_posting": False,
                "skip_reason": f"[Flash 初筛拦截] {triage.reason}",
                "narrative_framework": "Contrarian Reality Check",
                "hook_options": [],
                "long_form_body": "",
                "reply_sniper_text": "",
                "x_search_query": "",
                "visual_card_title": "",
                "visual_card_type": "terminal_benchmark",
                "visual_card_metrics": [],
            }

        persona = self._get_default_persona()
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
1. **NO REPOST TRACES**: Never mention "Reddit", "r/{signal['subreddit']}", or "a user posted". Write from first-person insider observation ("Engineers deploying X are hitting a wall...", "The smartest debate around $TICKER right now...").
2. **BRIDGE AI & CAPITAL**: Even if the topic is pure AI coding, briefly connect it to compute economics, SaaS moats, or capex. Even if it's pure stock trading, dissect it with systematic/engineering rigor.
3. **REPLY SNIPER + X SEARCH QUERY**:
   - Craft `reply_sniper_text` (60-90 words) packed with the sharpest counter-intuitive data point from the comments so the user can drop it under big X influencers' posts to farm Verified followers.
   - Craft `x_search_query` using 1-2 core keywords/tickers from this topic + `min_faves:50 -filter:replies lang:en` so the user can 1-click find viral tweets to reply to right now.
4. **BANNED AI SLOP WORDS**: Strictly forbidden: {persona['banned_words']}.
"""
        resp = self.client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SynthesizedDraft,
                temperature=0.7,
            ),
        )
        draft_obj = SynthesizedDraft.model_validate_json(resp.text)
        return draft_obj.model_dump()
