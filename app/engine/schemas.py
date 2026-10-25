from typing import List, Literal
from pydantic import BaseModel, Field


class TriageResult(BaseModel):
    pass_triage: bool = Field(description="True if this post or repo contains deep insights, alpha, benchmark data, or high utility suitable for a viral X post. False if it is a beginner toy, meme, or low-value fluff.")
    reason: str = Field(description="1-sentence reason")


class CardMetric(BaseModel):
    label: str = Field(description="Short dimension/metric name (max 4 words)")
    value: str = Field(description="Punchy data point, takeaway, or counter-argument (max 12 words)")
    sentiment: Literal["positive", "negative", "neutral"]


class SynthesizedDraft(BaseModel):
    is_worth_posting: bool = True
    skip_reason: str = ""
    narrative_framework: Literal[
        "Contrarian Reality Check",
        "Bull vs Bear Roundtable",
        "Production Post-Mortem & Economics",
        "Asymmetric Trade Breakdown",
        "Repo Teardown & Production Verdict",
    ] = "Repo Teardown & Production Verdict"
    content_tier: Literal[
        "FLASH_PUNCH",
        "DEBATE_ROUNDTABLE",
        "DEEP_DIVE_MEMO"
    ] = Field(default="DEEP_DIVE_MEMO", description="Content tier assessed based on information density: FLASH_PUNCH for fast metrics/breaking tools (60-120 words), DEBATE_ROUNDTABLE for contrarian clashes (150-220 words), DEEP_DIVE_MEMO for architectural analysis (280-400 words).")
    hook_options: List[str] = Field(default_factory=list, description="3 high-converting 2-line hooks (pain point attack, data shock, or commercial SaaS alternative thesis)")
    short_post: str = Field(default="", description="60-120 words punchy short-form body (excluding hook). Zero filler, direct takeaway, high read-through rate.")
    long_form_body: str = Field(default="", description="250-400 words X Long-form body (excluding hook). Crisp line breaks, bullet points, synthesizing the core architecture, real-world utility, production tradeoffs, and your personal verdict.")
    reply_sniper_text: str = Field(default="", description="60-90 words ultra-dense insight paragraph designed to reply under big X accounts discussing this topic to steal impressions and gain verified followers.")
    x_search_query: str = Field(default="", description='Ready-to-use X advanced search query to find recent viral tweets on this topic, e.g.: ("OpenShell" OR "AI runtime") min_faves:30 -filter:replies lang:en')
    visual_card_title: str = Field(default="", description="Headline for the 16:9 dark mode visual summary card")
    visual_card_type: Literal["terminal_benchmark", "bull_vs_bear", "capital_impact", "github_repo_card"] = "terminal_benchmark"
    visual_card_metrics: List[CardMetric] = Field(default_factory=list, description="4 structured items for the visual card grid")
