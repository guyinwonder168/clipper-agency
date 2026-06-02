"""Pydantic models for Clipper Agency configuration."""

from pathlib import Path

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
