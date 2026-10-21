from typing import List, Literal
from pydantic import BaseModel, Field


class TriageResult(BaseModel):
    pass_triage: bool = Field(description="True if this post contains deep insights, alpha, benchmarks, or intense debate suitable for a viral X post. False if it is a beginner help question, meme, or low-value rant.")
    reason: str = Field(description="1-sentence reason")


class CardMetric(BaseModel):
    label: str = Field(description="Short dimension/metric name (max 4 words)")
    value: str = Field(description="Punchy data point, takeaway, or counter-argument (max 12 words)")
    sentiment: Literal["positive", "negative", "neutral"]


class SynthesizedDraft(BaseModel):
    is_worth_posting: bool
    skip_reason: str
    narrative_framework: Literal[
        "Contrarian Reality Check",
        "Bull vs Bear Roundtable",
        "Production Post-Mortem & Economics",
        "Asymmetric Trade Breakdown"
    ]
    hook_options: List[str] = Field(description="3 high-converting 2-line hooks (data shock, contrarian thesis, or industry reality check)")
    long_form_body: str = Field(description="250-400 words X Long-form body (excluding hook). Crisp line breaks, bullet points, synthesizing the main post + smartest comment pushbacks, ending with a polarizing question.")
    reply_sniper_text: str = Field(description="60-90 words ultra-dense insight paragraph designed to reply under big X accounts discussing this exact topic to steal impressions and gain verified followers.")
    x_search_query: str = Field(description='Ready-to-use X advanced search query to find recent viral tweets on this topic, e.g.: ("Llama" OR "VRAM") min_faves:50 -filter:replies lang:en')
    visual_card_title: str = Field(description="Headline for the 16:9 dark mode visual summary card")
    visual_card_type: Literal["terminal_benchmark", "bull_vs_bear", "capital_impact"]
    visual_card_metrics: List[CardMetric] = Field(description="4 structured items for the visual card grid")
