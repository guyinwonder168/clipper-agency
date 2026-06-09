"""Pydantic models for Clipper Agency configuration."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, computed_field
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

    @computed_field
    @property
    def target_script_duration_sec(self) -> int:
        """Alias: Scriptwriter guidance, not a downstream command."""
        return self.target_duration_sec

    @computed_field
    @property
    def max_final_duration_sec(self) -> int:
        """Alias: Hard final safety cap enforced at G10."""
        return self.hard_limit_sec


class VisualCoverageConfig(BaseModel):
    """Thresholds for visual coverage quality gates."""

    black_frame_max_ms: int = 200
    empty_frame_max_ms: int = 300
    freeze_warning_ms: int = 1500
    final_visual_gap_max_ms: int = 200


class TextCollisionConfig(BaseModel):
    """Thresholds for text collision detection."""

    subtitle_overlap_max: float = 0.20
    headline_overlap_max: float = 0.15


class SafeAreaConfig(BaseModel):
    """Thresholds for safe-area and face overlap checks."""

    face_overlap_max: float = 0.15


class RuntimeInspectionConfig(BaseModel):
    """Runtime keyframe extraction and inspection controls."""

    enabled: bool = True
    persist_keyframes: bool = True
    frame_interval_sec: float = 0.5
    max_frames_per_asset: int = 8
    perceptual_hash_distance: int = 6


class OCRConfig(BaseModel):
    """OCR runtime inspection controls."""

    enabled: bool = True
    provider: str = "paddleocr"
    min_confidence: float = 0.55
    large_region_area_ratio: float = 0.20


class FaceDetectionConfig(BaseModel):
    """Face detection runtime inspection controls."""

    enabled: bool = True
    provider: str = "mediapipe"
    min_confidence: float = 0.60


class SemanticReviewConfig(BaseModel):
    """Settings for semantic visual review and repair."""

    enabled: bool = True
    provider: str = "existing_multimodal_llm"
    max_assets_per_beat: int = 3
    max_frames_per_asset: int = 4
    minimum_claim_support: float = 0.70
    maximum_misleading_risk: float = 0.30
    max_repair_cycles: int = 2


class EnforcementConfig(BaseModel):
    """Quality enforcement controls for review and publication."""

    block_on_reviewer_fail: bool = True
    block_publication_on_quality_fail: bool = True


class QualityConfig(BaseModel):
    """Top-level quality gate configuration."""

    visual_coverage: VisualCoverageConfig = Field(default_factory=VisualCoverageConfig)
    text_collision: TextCollisionConfig = Field(default_factory=TextCollisionConfig)
    safe_area: SafeAreaConfig = Field(default_factory=SafeAreaConfig)
    runtime_inspection: RuntimeInspectionConfig = Field(default_factory=RuntimeInspectionConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    face_detection: FaceDetectionConfig = Field(default_factory=FaceDetectionConfig)
    semantic_review: SemanticReviewConfig = Field(default_factory=SemanticReviewConfig)
    enforcement: EnforcementConfig = Field(default_factory=EnforcementConfig)


class LLMTracesConfig(BaseModel):
    """Structured LLM trace persistence settings."""

    enabled: bool = True
    persist_resolved_prompts: bool = True
    persist_raw_responses: bool = True
    persist_parsed_responses: bool = True
    persist_validation_results: bool = True
    log_full_payload_inline: bool = False
    redact_secrets: bool = True
    retention_days: int = 30
    required: bool = False


class ObservabilityConfig(BaseModel):
    """Observability configuration for runtime diagnostics."""

    llm_traces: LLMTracesConfig = Field(default_factory=LLMTracesConfig)


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

    # Per-agent LLM models (overridable via .env, empty = use hierarchy preset)
    safety_model: str = ""
    researcher_model: str = ""
    scriptwriter_model: str = ""
    visual_director_model: str = ""
    reviewer_model: str = ""

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

    # Quality gates
    quality: QualityConfig = Field(default_factory=QualityConfig)

    # Observability
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)


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

    type: str  # "tiktok_clip", "screenshot", "photo", "text_card", "text_overlay"
    url: str = ""  # Empty for text_overlay / text_card types
    reason: str
    source: str = ""  # "scrapecreators", "firecrawl", "pexels", "llm"
    page_url: str = ""
    title: str = ""
    relevance_score: float = 0.0
    provenance: str = ""  # "primary_clip", "supporting_context"
    related_beat_id: int | None = None
    story_id: str = ""
    license_status: str = "unknown"


class BeatFallback(BaseModel):
    """Fallback visual plan when no primary asset is available."""

    type: str  # "text_card", "ken_burns_photo", etc.
    headline: str
    image_search: str = ""


class EvidenceContract(BaseModel):
    """Visual evidence guidance for a story beat."""

    preferred: list[str] = Field(default_factory=list)
    acceptable: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


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
    evidence_contract: EvidenceContract | None = None


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


# -- Job #4 Quality Gate Contracts --


class VisualCoverageIssue(BaseModel):
    """A single visual coverage defect detected in rendered output."""

    type: str  # BLACK_FRAME, EMPTY_FRAME, FREEZE_FRAME, MISSING_SCENE, FINAL_VISUAL_GAP, DECODE_FAILURE
    start_sec: float
    end_sec: float
    severity: str  # "hard_fail", "warning", "info"
    detail: str = ""


class VisualCoverageResult(BaseModel):
    """Aggregated visual coverage evaluation result."""

    status: str  # "pass", "fail"
    output_duration_sec: float
    voiceover_duration_sec: float
    coverage_ratio: float
    issues: list[VisualCoverageIssue]


class DetectedTextRegion(BaseModel):
    """A normalized OCR-detected text region in a video frame."""

    text: str
    confidence: float
    bbox: list[int]  # [x1, y1, x2, y2]
    frame_size: tuple[int, int] = (1080, 1920)
    timestamp_sec: float
    zone: str = "middle"  # "top", "middle", "bottom"
    area_ratio: float = 0.0


class TextCollisionIssue(BaseModel):
    """Detected collision between source text and generated overlays."""

    type: str  # SUBTITLE_SOURCE_TEXT_OVERLAP, HEADLINE_SOURCE_TEXT_OVERLAP, SOURCE_TEXT_DENSITY
    severity: str  # "reject", "warning", "info"
    detail: str = ""
    overlap_ratio: float = 0.0


class SafeAreaIssue(BaseModel):
    """Detected safe-area or face-text overlap violation."""

    type: str  # PLATFORM_UNSAFE_ZONE, FACE_TEXT_OVERLAP
    severity: str  # "reject", "warning"
    detail: str = ""
    overlap_ratio: float = 0.0


class StoryModeDecision(BaseModel):
    """Deterministic story-mode classification for a topic."""

    story_mode: str  # "roundup", "single_story", "controversy_explainer", "breaking_news"
    confidence: float
    reason: str
    item_count: int = 1
    target_duration_sec: int = 30
    requires_intro_card: bool = False
    thumbnail_strategy: str = "default"
    cta_strategy: str = "default"


class DurationBudgetSection(BaseModel):
    """A single section allocation within the editorial duration budget."""

    type: str  # "intro", "hook", "story", "context", "evidence", "reveal", "cta"
    duration_sec: float
    label: str = ""


class DurationBudget(BaseModel):
    """Full editorial duration budget allocation."""

    target_duration_sec: int
    sections: list[DurationBudgetSection]


class VisualRelevanceScore(BaseModel):
    """Scored relevance between a visual asset and a story beat claim."""

    decision: str  # "accept", "revise", "reject"
    misleading_risk: float = 0.0
    person_match: float = 0.0
    event_match: float = 0.0
    claim_support: float = 0.0
    visual_quality: float = 0.0
    detail: str = ""


class PackageConsistencyResult(BaseModel):
    """Result of package-level consistency check (thumbnail vs video scope)."""

    status: str  # "pass", "fail"
    issue: str = ""
    detail: str = ""


class RepairPatch(BaseModel):
    """A single targeted repair action for a specific beat/timestamp."""

    beat_id: str
    action: str  # "replace_visual", "narrow_topic", "fix_text", etc.
    reason: str
    rerun_from: str  # agent name to rerun from
    timestamp_start_sec: float = 0.0
    timestamp_end_sec: float = 0.0
    required_visual: str = ""


class RepairPlan(BaseModel):
    """Structured repair plan with cycle limit and targeted patches."""

    decision: str  # "revise", "reject", "accept"
    max_repair_cycles: int = 2
    patches: list[RepairPatch] = Field(default_factory=list)


# -- Runtime Inspection Contracts --


class ExtractedFrame(BaseModel):
    """A persisted frame sampled from a visual asset or rendered output."""

    timestamp_sec: float
    path: str
    perceptual_hash: str
    width: int
    height: int


class FrameExtractionManifest(BaseModel):
    """Manifest linking an inspected asset to its extracted frames."""

    asset_id: str
    beat_id: str
    source_path: str
    frames: list[ExtractedFrame]


class OCRInspectionResult(BaseModel):
    """OCR inspection output for a frame or asset."""

    provider: str
    model: str = ""
    timestamp_sec: float = 0.0
    regions: list[DetectedTextRegion] = Field(default_factory=list)


class FaceRegion(BaseModel):
    """Detected face region in pixel coordinates."""

    bbox: list[int]
    confidence: float = Field(ge=0.0, le=1.0)
    is_primary: bool = False


class FaceInspectionResult(BaseModel):
    """Face detection output for a frame or asset."""

    provider: str
    model: str = ""
    timestamp_sec: float = 0.0
    faces: list[FaceRegion] = Field(default_factory=list)


class AssetSemanticInspection(BaseModel):
    """Multimodal semantic inspection of one candidate asset for one beat."""

    asset_id: str
    beat_id: str
    person_match: float = Field(ge=0.0, le=1.0)
    event_match: float = Field(ge=0.0, le=1.0)
    claim_support: float = Field(ge=0.0, le=1.0)
    visual_quality: float = Field(ge=0.0, le=1.0)
    temporal_match: float = Field(0.0, ge=0.0, le=1.0)
    source_credibility: float = Field(0.0, ge=0.0, le=1.0)
    cleanliness_score: float = Field(0.0, ge=0.0, le=1.0)
    misleading_risk: float = Field(ge=0.0, le=1.0)
    decision: str
    reason: str
    frame_paths: list[str]
    model: str


class SceneSemanticReview(BaseModel):
    """Semantic review result for a rendered scene or timestamp range."""

    beat_id: str
    timestamp_start_sec: float
    timestamp_end_sec: float
    decision: str
    reason: str
    score: float = Field(ge=0.0, le=1.0)


class QualityStatus(BaseModel):
    """Separate runtime statuses for execution, quality, publication, and repair."""

    execution_status: str
    quality_status: str
    publication_status: str
    repair_status: str


class RepairCycleRecord(BaseModel):
    """Before/after score snapshot for a bounded repair cycle."""

    cycle: int
    source_agent: str
    target_agent: str
    before_scores: dict[str, float]
    after_scores: dict[str, float]
