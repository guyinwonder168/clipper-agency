"""Pydantic models for Clipper Agency configuration."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VideoLengthConfig(BaseModel):
    """Video length constraints."""

    target: int = 30
    hard_limit: int = 60


class LLMConfig(BaseModel):
    """OpenRouter LLM routing configuration."""

    model: str = "openai/gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 2048


class AgentLLMConfig(BaseModel):
    """Per-agent LLM configuration with prompt versioning."""

    model: str = "mimo-v2-flash"
    temperature: float = 0.7
    max_tokens: int = 1024
    prompt_version: str = "1.0"


class SafetyConfig(BaseModel):
    """Safety gate configuration."""

    enabled: bool = True
    blocked_categories: list[str] = Field(default_factory=lambda: ["politics", "religion", "nsfw"])


class NicheConfig(BaseModel):
    """Niche profile — content rules and constraints."""

    name: str
    language: str = "id"
    tone: str = "casual_tiktok"
    video_length: VideoLengthConfig = Field(default_factory=VideoLengthConfig)
    safety_rules: list[str] = Field(default_factory=list)
    caption_style: str = "short_with_hashtags"
    content_angle: str = "trending_artist_update"
    search_terms: list[str] = Field(default_factory=list)
    max_hashtags: int = 5


class TemplateConfig(BaseModel):
    """Video template configuration."""

    name: str
    type: str  # news_card | b_roll_narration | rapid_update
    duration: int = 30
    assets_required: list[str] = Field(default_factory=list)


class ContentPlanningConfig(BaseModel):
    """Content planning constraints — format, story count, duration budgets."""

    default_format: str = "three_story_roundup"
    max_stories_per_video: int = Field(3, ge=1, le=10)
    target_duration_sec: int = Field(55, ge=20, le=300)
    hard_limit_sec: int = Field(60, ge=20, le=300)
    estimated_words_per_second: float = Field(2.0, ge=0.5, le=5.0)


class AppSettings(BaseSettings):
    """Application-level settings loaded from .env / environment.

    Field names map 1:1 to environment variable names (uppercased).
    For example, ``db_path`` reads ``DB_PATH`` from the env.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API keys
    openrouter_api_key: str = ""
    elevenlabs_api_key: str = ""
    fish_audio_api_key: str = Field(default="", validation_alias="FISHAUDIO_API_KEY")
    pexels_api_key: str = ""
    firecrawl_api_key: str = ""
    scrapecreators_api_key: str = ""
    gemini_api_key: str = ""

    # Paths
    db_path: str = Field(default="data/clipper.db")
    assets_cache: Path = Field(default=Path("assets/cache"))
    output_dir: Path = Field(default=Path("outputs"))

    # Per-agent LLM models (overridable via .env)
    safety_model: str = "mimo-v2-flash"
    researcher_model: str = "mimo-v2-flash"
    scriptwriter_model: str = "mimo-v2-flash"
    visual_director_model: str = "mimo-v2-flash"
    reviewer_model: str = "mimo-v2-flash"

    # Default LLM
    llm: LLMConfig = Field(default_factory=LLMConfig)

    # Logging
    log_level: str = "INFO"

    # TTS provider configuration (Fish Audio or ElevenLabs)
    fish_audio_voice_id: str = ""   # Fish Audio reference_id (voice model)
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    gemini_tts_voice_name: str = "Kore"

    # Debug / dev
    debug: bool = False
    dry_run: bool = False

    # Content planning
    content_planning: ContentPlanningConfig = Field(default_factory=ContentPlanningConfig)


# ---------------------------------------------------------------------------
# Audio-First Architecture models (v2.0 redesign)
# ---------------------------------------------------------------------------


# -- Segment Producer (Phase A) --


class VerifiedFact(BaseModel):
    """A fact with verification status and safe wording for narration."""

    fact: str
    source_url: str
    confidence: Literal["verified", "likely", "unconfirmed"]
    safe_wording: str


class UnverifiedClaim(BaseModel):
    """A claim that is unconfirmed, with safe wording label."""

    claim: str
    label: str  # "rumor", "unconfirmed", etc.
    safe_wording: str


class AssetCandidate(BaseModel):
    """A candidate visual asset found during research."""

    type: str  # "tiktok_clip", "screenshot", "photo", "text_card"
    url: str
    reason: str


class BeatFallback(BaseModel):
    """Fallback visual plan when no primary asset is available."""

    type: str  # "text_card", "ken_burns_photo", etc.
    headline: str
    image_search: str = ""


class StoryBeat(BaseModel):
    """A single beat in the edit blueprint produced by the Segment Producer."""

    beat_id: int
    role: str  # "hook", "main_claim", "evidence", "reaction", "closing_cta"
    narration_goal: str
    spoken_point: str
    safe_wording: str
    visual_must_show: str
    visual_must_not_show: str
    overlay_text: str
    caption_keywords: list[str]
    asset_candidates: list[AssetCandidate]
    fallback: BeatFallback
    evidence_source: str = ""
    risk_note: str = ""


class FormatDecision(BaseModel):
    """Format selection made by the Segment Producer based on available assets."""

    format: Literal[
        "single_story_deep_dive",
        "three_story_roundup",
        "two_story_highlight",
        "text_only",
    ]
    story_count: int
    rationale: str
    video_asset_ratio: float


class ReferenceStyle(BaseModel):
    """Reference style parameters derived from the Segment Producer's research."""

    format: str
    target_duration_sec: int
    hook_duration_sec: float
    avg_scene_duration_sec: float
    caption_style: str
    transition_style: str
    visual_priority: list[str]


# -- Voice Producer (Phase B) --


class WordTimestamp(BaseModel):
    """A single word with its start and end time in the voiceover audio."""

    word: str
    start: float
    end: float


class VoiceoverOutput(BaseModel):
    """Output contract for the Voice Producer's single continuous voiceover."""

    status: str
    voiceover_path: str
    voiceover_duration_sec: float
    timestamps: list[WordTimestamp]
    provider: str


# -- Scriptwriter (Phase B) --


class NarrativeBeat(BaseModel):
    """A narrative section mapped to a story beat with word range."""

    beat_id: int
    section: str  # "hook", "story_1", "story_1_reveal", "closing_cta"
    description: str
    word_range: list[int]  # [start_word_index, end_word_index]
    overlay_text: str
    caption_keywords: list[str]


# -- Reviewer (Phase D) --


class QualityCheckResult(BaseModel):
    """Result of a single quality check performed by the Reviewer."""

    check_name: str
    passed: bool
    details: dict
