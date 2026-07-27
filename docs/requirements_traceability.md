# Clipper Agency — Requirements Traceability Matrix

**Version:** 4.4
**Date:** 2026-06-29
**Status:** Phase 23 Complete + ADR 0030 (Inter-Agent Contract Gates — Proposed, investigation complete, implementation pending)

---

## Purpose

This document maps every product requirement to its SRS requirement, technical design section, edge cases, and validation checks. Use this to verify no requirement is lost between docs and to audit for gaps.

---

## Fact Preservation Register

Every fact from the archived documents (`docs/old/25may2026/`) is mapped below. If a fact appears missing, the archive is the source of truth.

### From Archived PRD

| # | Fact | New Location |
|---|------|-------------|
| 1 | Single client, single TikTok account, Indonesian artist infotainment MVP | PRD §3, SRS §1, Design §1 |
| 2 | Manual topic input | PRD §3 |
| 3 | yt-dlp Layer 1 primary, Pexels fallback | PRD §9, SRS §4, Design §2 |
| 4 | Output: video.mp4 + caption.txt + thumbnail.png + metadata.json | PRD §4, SRS §2 FR-10 |
| 5 | 9:16, 1080x1920, 20-30s video | PRD §3, SRS §7 |
| 6 | Caption max 150 chars, 5 hashtags | PRD §4, SRS §7 |
| 7 | Template-based thumbnail 1080x1920 | PRD §4 |
| 8 | Manual upload (no TikTok API posting) | PRD §3 |
| 9 | Config-swappable niche/language/tone | PRD §3, SRS §2 FR-22 |
| 10 | 6 user roles (Admin, Creative Lead, Creative User, Reviewer, Viewer, Client) | PRD §2 |
| 11 | Basic auth + 2 groups MVP | PRD §3, SRS §5 |
| 12 | One configured voice ID, with TTS provider fallback order ElevenLabs → Gemini TTS → Fish Audio → fail clearly | PRD §3, PRD §5 PR-25, SRS §2 FR-06, SRS §4, Design §9 |
| 13 | Budget East default model preset | PRD §13, Design §12 |
| 14 | LLM cost target < $0.01/video | PRD §10, SRS §3 |
| 15 | Pipeline success rate > 90% | PRD §10, SRS §3 |
| 16 | Generation time < 15 min | PRD §10, SRS §3 |
| 17 | Human review pass rate > 80% | PRD §10, SRS §3 |
| 18 | Safety hard-block: illegal/banned/high-risk defamation, no override | PRD §6, Design §3 G4 |
| 19 | Safety soft-warning: unverified claims, cautious wording | PRD §6, Design §3 G4 |
| 20 | Post-research risk gate | PRD §6, Design §3 G4 |
| 21 | Manual retry only, no auto-retry | PRD §3, SRS §2 FR-09, Design §3 |
| 22 | Creative Director deferred Stage 2 | PRD §5 PR-09, Design §4 |
| 23 | Local machine + Docker-ready | PRD §3, SRS §8 |
| 24 | ScrapeCreators 75 free credits | SRS §4 |
| 25 | Firecrawl daily free runs | SRS §4 |
| 26 | Research cache TTL policy | Design §5, SRS §2 FR-11 |
| 27 | Cache key includes entities | Design §5 |
| 28 | Background music default: none | Design §6 |
| 29 | Max clip 5s, 2 unique sources target | PRD §9, Design §7 |
| 30 | Fallback: 1 source + Pexels/generated cards | PRD §9, Design §7 |
| 31 | Transformation stack required | Design §7 |
| 32 | Creative memory pre-generation check | Design §8 |
| 33 | Variation rotation by angle/template | Design §8 |
| 34 | Config hierarchy: Agent → Niche → Account → Job | Design §9 |
| 35 | 3 templates: News Card, B-Roll Narration, Rapid Update | Design §10 |
| 36 | SQLite MVP → PostgreSQL scale | SRS §6, Design §2 |
| 37 | No GPU required | PRD §11, SRS §1 |
| 38 | Python 3.11+, FFmpeg 5.0+ | SRS §1 |
| 39 | No secrets in DB, env vars only; `.env` loaded via `python-dotenv` `load_dotenv()` at CLI entry, typed via `pydantic-settings` `AppSettings` | SRS §5, Design §2, Design §9 |
| 40 | Financial data restricted to privileged roles | PRD §13, SRS §5 |
| 41 | Data retention schedule | SRS §6.3 |
| 42 | 7 MVP agents | Design §4 |
| 43 | DB-driven state, orchestrator | Design §1 |
| 44 | Agent states, timestamps, gate results, provider attempts, artifact paths, and failure summaries visible in debug-first dashboard/CLI | SRS §2 FR-14, Design §1 |
| 45 | Jobs restartable in principle from persisted DB state plus job workspace artifacts; write-enabled retry/resume follows after artifact contracts stabilize | SRS §3 NFR-08, Design §1 |

### From Archived TRD (additional facts not covered above)

| # | Fact | New Location |
|---|------|-------------|
| 46 | CLI startup < 2 seconds | SRS §3 NFR-05 |
| 47 | Dashboard page load < 3 seconds | SRS §3 NFR-06 |
| 48 | Pexels 200 requests/hr | SRS §4 |
| 49 | Serper 2,500 free (Stage 2) | SRS §4 |
| 50 | DuckDuckGo unlimited (Stage 2+) | SRS §4 |
| 51 | Soft deletes for data recovery | SRS §5 |
| 52 | Config versioning with diff and rollback | SRS §2 FR-21 |
| 53 | All state transitions timestamped | SRS §3 NFR-07 |
| 54 | Agent contracts identical at all scales | SRS §3 NFR-09 |
| 55 | FFmpeg metadata stripping | SRS §7 |
| 56 | ScrapeCreators: ~1 credit per search | SRS §4 |
| 57 | Multi-tenant schema from day one | Design §11 |

### From Archived Technical Design (additional facts not covered above)

| # | Fact | New Location |
|---|------|-------------|
| 58 | Researcher query construction: topic + entities + infotainment terms | Design §4 |
| 59 | Prefer recent Indonesian sources | Design §4 |
| 60 | Creative history: same topic cluster + batch (strict), account recent (light) | Design §8 |
| 61 | Reviewer: multimodal (Gemini 2.5 Flash) | Design §4 |
| 62 | Reviewer max 2 human-triggered retries | Design §4 |
| 63 | Emergency override: soft-warnings only, requires reason + admin alert | PRD §6 |
| 64 | Variation exhaustion: MVP → human review; Stage 2 → Creative Director | Design §8 |
| 65 | Running jobs cannot be edited/retried until paused/failed/completed | Design §1 |
| 66 | User-upload: local file path or single import | PRD §9 |
| 67 | Template mode: manual, agent_select, hybrid | Design §10 |

### From Phase 11 (Logging, Model Config, ScrapeCreators Cache)

| # | Fact | New Location |
|---|------|-------------|
| 68 | Per-agent model config via env vars (`SAFETY_MODEL`, `RESEARCHER_MODEL`, `SCRIPTWRITER_MODEL`, `REVIEWER_MODEL`) in `AppSettings` | SRS §2 FR-24, Design §9 |
| 69 | Structured logging: all agents log start/result/error; all services log API requests/responses; LLM client logs model, tokens, cost, latency | SRS §2 FR-25, SRS §3 NFR-10, Design §2 |
| 70 | ScrapeCreators: `trim=true` + `_extract_fields()` reduces 1-2MB raw responses to ~500 chars/result; max 20 results | SRS §2 FR-16, SRS §4, Design §4 |
| 71 | Researcher token guard: `MAX_SOURCE_CHARS=40000`, `MAX_CHARS_PER_SOURCE=500` prevents 551K token LLM overflow | SRS §2 FR-16, Design §4 |
| 72 | Researcher file cache existed as `scrapecreators.json`, `firecrawl.json`, `research_brief.json` per job output dir in Phase 11; Phase 12 supersedes this with `ASSETS_CACHE/job_{id}/agents/researcher/` raw/normalized artifacts and `research_brief.md` | Design §4, Design §9 |
| 73 | `clipper_agency/core/paths.py`: shared cache path helpers; `clipper_agency/core/logging.py`: `setup_logging()` + `get_logger()` | Design §9 |
| 74 | `test-agent` CLI subcommand: runs individual agents independently, bypasses orchestrator DB tracking | SRS §2 FR-19, Design §14 |

### From Fish Audio TTS Implementation (post-Phase 11)

| # | Fact | New Location |
|---|------|-------------|
| 75 | Configurable TTS provider fallback now attempts ElevenLabs → Google AI Studio Gemini TTS → Fish Audio → fail clearly and persists sanitized provider attempts | PRD §5 PR-25, SRS §2 FR-06, SRS §4, Design §4, Design §9 |
| 76 | `FishAudioService`: s2-pro model (`POST /v1/tts`), `reference_id` for voice model, Bearer auth, mp3 output | Design §2, Design §9 |
| 77 | `_extract_fields()` handles both `aweme_info`-wrapped (full API) and flat (trim=true) responses via `source = item.get("aweme_info") or item`; trimmed responses have no music or hashtags | Design §4, SRS §2 FR-16 |
| 78 | `AppSettings` fields: `fish_audio_api_key` (validation_alias `FISHAUDIO_API_KEY`), `fish_audio_voice_id`, `elevenlabs_voice_id` | Design §9, SRS §5 |
| 79 | Voice provider env var fallback: `FISHAUDIO_API_KEY` (Fish Audio), `ELEVENLABS_API_KEY` (ElevenLabs) | SRS §4, Design §9 |
| 80 | Free tier API blocked for both ElevenLabs (401 abuse detection) and Fish Audio (402 insufficient balance). Both require paid plans. | PRD §3, SRS §4 |

### From Phase 12 Artifact Contracts + Debug Observability

| # | Fact | New Location |
|---|------|-------------|
| 81 | Intermediate artifacts, raw provider responses, agent inputs/outputs, gate results, diagnostics, and `manifest.json` live under `ASSETS_CACHE/job_{id}` | PRD §4, SRS §2 FR-15, SRS §6.2-6.3, Design §1 |
| 82 | Final customer package lives under `OUTPUT_DIR/job_{id}` and contains only `video.mp4`, `caption.txt`, `thumbnail.png`, and `metadata.json` | PRD §4, SRS §2 FR-10/FR-15, Design §1 |
| 83 | Researcher persists `research_brief.md`, `research_contract.json`, raw ScrapeCreators/Firecrawl payloads, and normalized derived files | PRD §4, SRS §6.3, Design §4 |
| 84 | Every gate persists one JSON result and hard-fail gates stop downstream execution | PRD §5 PR-02, SRS §2 FR-01/FR-14, Design §3 |
| 85 | Agent DB states transition pending → running → completed/failed with timestamps and error details | SRS §3 NFR-07, Design §1 |

### From Phase 13 Retry/Resume + Cache Reuse

| # | Fact | New Location |
|---|------|-------------|
| 86 | CLI `job-retry <id> --from <agent>` re-runs from a specified agent; `job-resume <id>` resumes from failed/paused stage. Both use the original config snapshot by default and skip valid cached artifacts via `validate_agent_cache()`. | SRS §2 FR-28, Design §1 |
| 87 | Dashboard POST `/jobs/<id>/retry` and `/jobs/<id>/resume` routes provide the same write-enabled retry controls with CSRF protection | Design §1 |
| 88 | Job config snapshot frozen at creation time (`jobs.config_snapshot`); retries/resumes use the same snapshot even if global config changed. Override flag available for explicit re-snapshot. | Design §1 |
| 89 | `validate_agent_cache()` checks persisted artifacts deterministically (exists, non-zero, valid JSON/format/timing) before skipping a paid provider call. Invalid cache falls through to re-run. | Design §1 |

### From Phase 14 Media/Composer Correctness

| # | Fact | New Location |
|---|------|-------------|
| 90 | FFmpeg preflight diagnostic checks `ffmpeg`, `ffprobe`, libx264, aac, mp3 before any render work; fails clearly if missing | SRS §2 FR-29, Design §7 |
| 91 | Scene normalization: every clip re-encoded to 1080x1920, yuv420p, h264, metadata stripped, duration 1-5s, before concat. Provenance recorded in `provenance.json`. | Design §7 |
| 92 | Generated card fallback: Visual Director uses Pillow to render 1080x1920 PNG text-on-background cards when no clips or stock footage available | PRD §9, SRS §2 FR-30, Design §7 |
| 93 | Deterministic video validation (G10): check `video.mp4` exists, >1KB, 9:16, 1080x1920, 20-60s, audio track, h264/aac, metadata stripped — before Reviewer multimodal spend | SRS §2 FR-31, Design §3 G10 |
| 94 | Output package fixed-contract nomenclature ensures `video.mp4`, not `final.mp4`; packager uses OWASP-safe path sandbox (S6549) | PRD §4, Design §1, Design §14 |
| 95 | Thumbnail generated as 1080x1920 PNG using Pillow with template-based styling, included in final package as `thumbnail.png` | PRD §4, Design §14 |

### From Phase 15a Template Rendering Engine

| # | Fact | New Location |
|---|------|-------------|
| 96 | YAML template definitions under `templates/` drive rendering; 3 built-in templates: News Card, B-Roll Narration, Rapid Update | PRD §5 PR-07, SRS §2 FR-21, Design §10 |
| 97 | `TemplateLoader` validates template YAML at load time (required fields, type checks, default values) — fails fast before any FFmpeg work | Design §10, Design §14 |
| 98 | Render contracts (`RenderContract`, `ClipSpec`, `AudioTrack`, `TextOverlay`, `TransitionSpec`) define typed inputs for every adapter | Design §7, Design §14 |
| 99 | Shared rendering primitives (`build_concat_filter`, `build_audio_mix`, `build_fade`, `build_crossfade`, `build_drawtext`) produce FFmpeg filter chains | Design §7, Design §14 |
| 100 | Template thumbnails generated via Pillow with title text, template-specific styling, and 1080x1920 output — replaces generic thumbnail when template selected | PRD §4, Design §14 |
| 101 | `RenderEngine` orchestrates FFmpeg filter graph from primitives + adapter output; produces intermediate and final video via two-pass concat + overlay | Design §7, Design §14 |
| 102 | Three adapters (`NewsCardRenderer`, `BRollNarrationRenderer`, `RapidUpdateRenderer`) translate template specs into `RenderContract` + filter chains | Design §10, Design §14 |
| 103 | Composer agent routes template selection by niche config and script structure; runs FFmpeg preflight diagnostics before rendering | Design §4, Design §7, Design §14 |
| 104 | All rendering tests offline: template loading, contract validation, primitive filter chains, thumbnail generation, adapter output, engine orchestration, composer template routing | SRS §3 NFR-09, Design §14 |

### From Phase 16 Visual Director LLM Planning

| # | Fact | New Location |
|---|------|-------------|
| 105 | Visual Director uses LLM to plan per-scene visual strategy: `_compact_research_data()` strips noise, `_plan_with_llm()` creates structured plan, `_execute_plan()` executes via dispatch table | SRS §2 FR-07, Design §4 |
| 106 | Dispatch table action types: `tiktok_clip` (yt-dlp download), `pexels_video` (stock video), `pexels_image` (stock photo via `search_photos()`), `text_card` (Pillow-generated card with optional image) | SRS §2 FR-07, Design §4 |
| 107 | 3-tier image fallback for text cards: Pexels photo search (`search_photos()`) → Firecrawl article og:image → gradient card background | SRS §2 FR-07, PRD §9, Design §4 |
| 108 | `visual_director_model` config field added to `AppSettings` (default `mimo-v2-flash`); env var `VISUAL_DIRECTOR_MODEL` | SRS §2 FR-24, Design §9 |
| 109 | Orchestrator engine passes `research_contract_path` + `research_brief_path` to Visual Director instead of raw source URLs | Design §4, Design §9 |
| 110 | LLM planning failure returns `None` → routes to legacy `_plan_scenes()` + `_download_assets()` sequential path | SRS §2 FR-07, Design §4 |
| 111 | Prompt files renamed `.txt` → `.md` for better editor support (safety, researcher, scriptwriter, reviewer); new `prompts/visual_director.md` for LLM planning prompt | Design §2, SRS §2 FR-07 |
| 112 | `search_photos()` added to PexelsService for photo search (query, orientation, per_page) — enables text card image enrichment | SRS §4, Design §4 |

### From Phase 17 Treatment System

| # | Fact | New Location |
|---|------|-------------|
| 113 | Treatment definitions in `templates/treatments.yaml`: 9 visual treatments (ken_burns_zoom_in, ken_burns_pan_left, cinematic_crop, broll_standard, slow_motion, lower_third_slide, text_card_reveal, hook_big_caption, fade_to_black) + 5 transitions (crossfade, hard_cut, wipe_left, dissolve, circle_open) + fps_rules + pacing_rules | PRD §5 PR-26, SRS §2 FR-32, Design §7 |
| 114 | Treatments are data-driven: adding a new treatment requires YAML entry + FFmpeg filter chain builder in `primitives.py`, no agent/orchestrator code changes | PRD §5 PR-26, Design §7 |
| 115 | FPS rules: 30fps target, acceptable range 24-60fps, force constant framerate for all scenes | PRD §5 PR-26, Design §7 |
| 116 | Pacing rules: min 2s, max 8s, preferred 3.5s per scene; hook max 3s, CTA max 4s | PRD §5 PR-26, Design §7 |
| 117 | Visual Director selects treatment per-scene via LLM; Composer applies treatment-specific FFmpeg filter chains (zoompan for Ken Burns, speed for slow-motion, fade for transitions) | PRD §5 PR-26, SRS §2 FR-32, Design §4, Design §7 |

### From Phase 18 Scene Normalizer

| # | Fact | New Location |
|---|------|-------------|
| 118 | Scene normalizer unifies mixed-asset framerates to 30fps target (PAL 25fps, NTSC 24/29.97fps, variable-rate downloads all normalized) | PRD §5 PR-27, SRS §2 FR-33, Design §7 |
| 119 | SAR normalized to 1:1 to prevent FFmpeg concat demuxer aspect ratio mismatches | PRD §5 PR-27, SRS §2 FR-33, Design §7 |
| 120 | Ken Burns zoompan applied to static images (2.5s zoom cycle) to create motion from stills | PRD §5 PR-27, SRS §2 FR-33, Design §7 |
| 121 | Flash-frame clips (<1s) rejected; clips >5s trimmed to 5s max | PRD §5 PR-27, SRS §2 FR-33, Design §7 |
| 122 | Default treatment routing when LLM unavailable: text_card_reveal for text cards, broll_standard for video clips, ken_burns_zoom_in for static images | Design §4 |

### From Phase 19 Composer Treatment & Transition Engine

| # | Fact | New Location |
|---|------|-------------|
| 123 | Audio sequencer replaces broken `amix=inputs=N` with per-scene `concat` filter — Mode A (paired video+audio) and Mode B (audio-only when xfade handles video); missing audio padded with `anullsrc` silence | PRD §5 PR-28, SRS §2 FR-34, Design §7 |
| 124 | Subtitle engine converts script scene text to timed `CaptionOverlay` objects with absolute timestamps; `build_hook_overlay()` creates center-positioned hook caption for first 3s | PRD §5 PR-28, SRS §2 FR-35, Design §7 |
| 125 | xfade/concat mixed transition chain with offset calculation (`cumulative_duration - trans_duration - 0.1`), duration clamping (`min(trans_duration, min(prev_dur, next_dur) - 0.15)`), safety margins; unknown transitions fallback to crossfade | PRD §5 PR-28, SRS §2 FR-36, Design §7 |
| 126 | Production output flags: `-pix_fmt yuv420p` (player compatibility), `-movflags +faststart` (streaming-ready MP4), H.264/AAC codecs enforced | PRD §5 PR-28, SRS §2 FR-36, Design §7 |
| 127 | Treatment filter builder with variable substitution (`{frames}`, `{text}`, `{duration}`, `{start_time}`), input-type rules (image+zoompan → prepend scale, after scale/crop → append setsar), null/unknown → `"null"` | PRD §5 PR-26, SRS §2 FR-32, Design §7 |
| 128 | Treatment config YAML loader with frozen dataclasses (`TreatmentDef`, `TransitionDef`) for immutable access; `TreatmentConfig` exposes `get_treatment()`, `get_transition()`, `target_fps`, `pacing` properties | PRD §5 PR-26, SRS §2 FR-32, Design §7 |
| 129 | Orchestrator threads `script_scenes` from scriptwriter output to Composer for subtitle generation; Composer chains drawtext filters with `enable='between(t,start,end)'` and `escape_drawtext()` | PRD §5 PR-28, SRS §2 FR-35, Design §4 |

### From Audio-First Continuous Voiceover Architecture (v2.0.0)

| # | Fact | New Location |
|---|------|-------------|
| 140 | Researcher renamed to Segment Producer with 5 sub-roles: Fact Checker, Viral Analyst, Clip Scout, Story Producer, Edit Planner. File renamed `researcher.py` → `segment_producer.py` | PRD §5 PR-02, SRS §2 FR-03, Design §4, ADR 0021 |
| 141 | Segment Producer outputs edit blueprint with story_beats (visual_must_show/must_not_show, asset_candidates, overlay_text, caption_keywords), format_decision, verified_facts with safe_wording, unverified_claims, do_not_use list | PRD §5 PR-29, SRS §2 FR-03/FR-37, Design §4, ADR 0021 |
| 142 | Scriptwriter writes continuous voiceover narration (75-110 words, no emojis, spoken-word style) instead of per-scene headline fragments. Outputs voiceover_text + narrative_structure mapping beats to word ranges | PRD §5 PR-29, SRS §2 FR-05/FR-38, Design §4, ADR 0021 |
| 143 | Voice Producer generates single continuous TTS call (87.5% cost reduction: 8 calls → 1). Returns voiceover.mp3 + word-level timestamps via ElevenLabs `/with-timestamps` (character-level grouped to words) | PRD §5 PR-29, SRS §2 FR-06/FR-39, Design §4, ADR 0021 |
| 144 | Sequential Voice→Visual pipeline: Voice Producer must complete before Visual Director starts. Removed parallel asyncio.gather from engine | PRD §5 PR-02, SRS §2 FR-41, Design §3, ADR 0021 |
| 145 | Visual Director beat-driven planning: consumes story_beats + word timestamps + visual rules. Each beat has exact audio duration from timestamps. Visual hierarchy enforced: source clip → screenshot → portrait → text card → stock | PRD §5 PR-29, SRS §2 FR-07/FR-41, Design §4, ADR 0021 |
| 146 | Composer single audio timeline: voiceover.mp3 is immutable anchor (never trimmed). Smart scene trimming at ffprobe keyframe boundaries (±15% tolerance), speed adjustment ±20% | PRD §5 PR-29, SRS §2 FR-08/FR-42, Design §4/§7, ADR 0021 |
| 147 | Keyword captions (max 6 words, beat-aligned, bottom-positioned) replace full-sentence subtitles. Implemented in subtitle_engine.py | PRD §5 PR-28/PR-29, SRS §2 FR-08/FR-42, Design §4/§7, ADR 0021 |
| 148 | Reviewer enhanced with 4 programmatic quality checks: (1) AV sync (drift < 0.5s), (2) caption quality (short keywords, max 6 words), (3) fact safety (safe wording), (4) narrative structure (beat completeness) | PRD §5 PR-29, SRS §2 FR-09, Design §4, ADR 0021 |
| 149 | Shared schema contract via `config/schema.py`: 11 Pydantic models (StoryBeat, FormatDecision, VerifiedFact, UnverifiedClaim, VisualInstruction, AssetCandidate, KeywordCaption, VoiceSettings, VoiceProviderResult, ContentBrief, NarrativeSection) | SRS §2 FR-40, Design §7, ADR 0021 |
| 150 | Timeline Reconciler removed from engine — replaced by direct data flow: engine passes timestamps from Voice Producer to Visual Director and Composer | Design §3, ADR 0021 |
| 151 | ElevenLabs `chars_to_words()` converts character-level timestamps to word-level. Voice settings: stability=0.4, similarity_boost=0.75, style=0.7, use_speaker_boost=True | SRS §2 FR-39, Design §4, ADR 0021 |
| 152 | Gemini TTS fallback uses FFmpeg silencedetect for approximate timestamps when provider returns raw PCM only (no timestamps) | SRS §2 FR-39, Design §4, ADR 0021 |
| 153 | Backward-compat files removed: researcher.py, researcher.md, 2 test wrappers. All references updated to segment_producer | Design §4, ADR 0021 |

### From Phase 21 Deterministic Quality Gates + Repair Routing

| # | Fact | New Location |
|---|------|-------------|
| 154 | Visual coverage evaluation: `evaluate_visual_coverage()` scores frame-level completeness via sampled thumbnails; detects black/freeze frames | PRD §5 PR-30, SRS §2 FR-43, Design §13 |
| 155 | Frame sampler: `plan_frame_samples()` + `deduplicate_samples_by_hash()` produce deterministic sampling schedules for coverage analysis | SRS §2 FR-43, Design §13 |
| 156 | Text collision detection: `detect_text_collisions()` + `detect_source_text_density()` flag overlapping or dense on-screen text regions | PRD §5 PR-30, SRS §2 FR-44, Design §13 |
| 157 | Safe-area compliance: `detect_safe_area_issues()` validates placement against TikTok safe zones | PRD §5 PR-30, SRS §2 FR-45, Design §13 |
| 158 | Story mode classification: `classify_story_mode()` determines narrative structure and validates consistency | PRD §5 PR-30, SRS §2 FR-46, Design §13 |
| 159 | Duration budget allocation: `allocate_duration_budget()` distributes total duration across beats by role weight | SRS §2 FR-47, Design §13 |
| 160 | Package consistency: `evaluate_package_consistency()` validates story mode matches actual scene/clip composition | PRD §5 PR-30, SRS §2 FR-48, Design §13 |
| 161 | Semantic visual relevance: `score_visual_relevance()` scores claim-to-visual alignment using keyword overlap and evidence contracts | PRD §5 PR-30, SRS §2 FR-49, Design §13 |
| 162 | Structured repair routing: `route_repair()` + `build_repair_plan()` map quality failures to correct existing agent for targeted fix | PRD §5 PR-30, SRS §2 FR-50, Design §13 |
| 163 | Reviewer gate chain: visual_coverage → text_collision → safe_area → package_consistency → semantic_review → LLM | PRD §5 PR-30, Design §13, ADR 0023 |
| 164 | 10 new core modules, 0 new top-level agents; all modules are pure functions with injected dependencies | Design §13, ADR 0023 |
| 165 | Evidence contracts on StoryBeat: each claim maps to required visual evidence and actual alignment score | SRS §2 FR-49, Design §13 |
| 166 | Repair routing table: visual_coverage→Composer, text_collision→Visual Director, safe_area→Visual Director, package_consistency→Segment Producer, semantic_review→Segment Producer | SRS §2 FR-50, Design §13 |

### From Phase 22 Runtime Quality Enforcement + Multi-Source Asset Sourcing

| # | Fact | New Location |
|---|------|-------------|
| 167 | Multi-provider asset sourcing: YouTube (yt-dlp search), Tavily (web news), Brave (video/web) with graceful per-provider fallback and SOURCE_QUALITY_TIERS scoring | PRD §5 PR-31, SRS §2 FR-51, Design §15 |
| 168 | YouTube thumbnail fallback: maxresdefault→hqdefault as image candidates (0.70 tier) | PRD §5 PR-31, SRS §2 FR-52, Design §15 |
| 169 | Runtime FFmpeg black/freeze detection: detect_black_segments() + detect_freeze_segments() with MediaDetectionError fallback | PRD §5 PR-32, SRS §2 FR-53, Design §15 |
| 170 | Runtime frame extraction + perceptual hashing: extract_frames(), perceptual_hash(), hash_distance() for deduplication | SRS §2 FR-54, Design §15 |
| 171 | PaddleOCR runtime text detection adapter with model auto-download | SRS §2 FR-55, Design §15 |
| 172 | MediaPipe face detection runtime adapter using image array input | SRS §2 FR-56, Design §15 |
| 173 | Source cleanliness scoring: 4-dimension score (resolution, aspect ratio, source type, file size) | SRS §2 FR-57, Design §15 |
| 174 | Final layout inspection pipeline: pipelines FFmpeg + text + face detection | SRS §2 FR-58, Design §15 |
| 175 | Story-mode reconciliation: 4-rule priority system (explicit override → multi-entity → legacy → fallback) | PRD §5 PR-33, SRS §2 FR-59, Design §15 |
| 176 | Rendered scene manifest: build_rendered_scene_manifest() with scene-to-beat temporal mapping | SRS §2 FR-60, Design §15 |
| 177 | Reviewer context builder: SceneBeatMapping, get_semantic_review_context() | SRS §2 FR-61, Design §15 |
| 178 | Multimodal candidate inspection: OpenRouterMultimodalProvider, MultimodalInspectionClient, semantic ranking with rejection | PRD §5 PR-35, SRS §2 FR-62, Design §15 |
| 179 | LLM trace artifacts: chat_traced() + TraceWriter protocol | SRS §2 FR-63, Design §15 |
| 180 | Bounded automated repair loop: max N cycles, identical-patch exhaustion detection, cycle retention | PRD §5 PR-34, SRS §2 FR-64, Design §15 |
| 181 | Repair quality metrics: before/after snapshots, improvement detection, cycle persistence | SRS §2 FR-65, Design §15 |
| 182 | Publication blocking: atomic promotion via temp+rename, requires quality=passed AND artifact=approved | SRS §2 FR-66, Design §15 |
| 183 | Timestamp-semantic review in reviewer gate chain: scene-to-beat mapping with evidence contracts | SRS §2 FR-67, Design §15 |

### From Phase 23 Reviewer Context + Diagnostics Enforcement Contract

| # | Fact | New Location |
|---|------|-------------|
| 184 | Rendered scene manifest + reviewer context: engine passes serialized `rendered_scene_manifest`, `story_beats`, and `word_timestamps` to Reviewer for timestamp-level semantic review | SRS §2 FR-67/FR-68, Design §16 |
| 185 | Composer diagnostics passthrough: engine forwards diagnostics to Reviewer in normal and repair rerun paths so visual_coverage, text_collision, and safe_area gates enforce Composer evidence | SRS §2 FR-68, Design §16, ADR 0024 |

### From Phase 26 PR 5 — Pre-Visual-Director Asset Qualification Boundary

| # | Fact | New Location |
|---|------|-------------|
| 186 | Pre-Visual-Director asset-qualification boundary: `clipper_agency/core/asset_qualification.py` scores each beat's image candidates (reuse of VD's scoring chain) BEFORE Visual Director consumes them; engine seam `_apply_asset_qualification` in `Engine._run_visual_director_phase` (engine.py ~1206-1242) runs after voicing, before VD | PRD §5 PR-37, SRS §2 FR-69, Design §17, ADR 0026 |
| 187 | Source-recovery-before-text-card (real Job #8 fix): when a beat has zero qualified candidates, a bounded RECOVER stage re-runs Segment Producer discovery for fresh candidates and re-scores them BEFORE the text-card fallback. Job #8 root cause was candidate REJECTION, not scarcity. `MAX_RECOVERY_CYCLES=1` bounds the loop | PRD §5 PR-37, SRS §2 FR-69, Design §17, ADR 0026 |
| 188 | `qualification_report.json` artifact: per-beat verdicts (`qualified` / `recovered` / `exhausted_text_card`), `recovery_outcome`, `reject_reasons` written under the job's ASSETS_CACHE dir via existing `write_json` | PRD §5 PR-37, SRS §2 FR-69, Design §17 |
| 189 | Zero double-VLM spend (cache-key parity): `asset_qualification._score_candidate` computes byte-identical cache keys to `VD._score_one_candidate`, so VD's re-inspection of a pre-qualified candidate is a cache hit. SLICE 1 hard gate | SRS §2 FR-69, Design §17, ADR 0027 |
| 190 | Rejected candidates never reach VD: engine immutably rewrites `beat.asset_candidates` to the qualified set only (the load-bearing per-beat surface); flat-pool filter is defense-in-depth. Existing 69 VD tests pass unmodified — VD source untouched, blast-radius contained | PRD §5 PR-37, SRS §2 FR-69, Design §17, ADR 0026 |
| 191 | Inspection delegation (ADR 0027): the cache-miss inspection delegates to VD's own bound `_run_multimodal_inspection` rather than verbatim-lifting ~140 lines of OCR/face/enhanced ML — cached output byte-identical to VD's (no cache-namespace drift), frame ownership stays in VD | SRS §2 FR-69, Design §17, ADR 0027 |
| 192 | ADR 0026 compliance: pure orchestration — NO new agent, NO new gate, NO schema change, NO state-machine change. SLICE 8 (do_not_use URL filter at the boundary) DEFERRED to post-PR-5 (VD already enforces do_not_use at four downstream points; re-filtering would be redundant contract re-enforcement the rebuild-ADR forbids) | ADR 0026 |

### From Phase 26 PR 6 — Clip-Window Selector (Minimal, Contract-First)

| # | Fact | New Location |
|---|------|-------------|
| 193 | Clip-window module + pluggable selector: `clipper_agency/core/clip_window.py` exposes a frozen `ClipWindow(start_sec, end_sec)` dataclass, a `WindowSelector` Protocol, and `KeywordOverlapWindowSelector` (v1 default, conservative: returns `ClipWindow(0.0, None)` — the full-clip window — because keyword overlap cannot localize a spoken point to a timestamp) | SRS §2 FR-72, Design §18, ADR 0026 |
| 194 | `AssetCandidate` window fields: optional `source_start_sec: float = 0.0` and `source_end_sec: float | None = None` (additive — defaults preserve today's from-zero trim). Excluded from `compute_asset_content_hash` so FR-69 / PR 5 cache-key parity holds (no VLM double-spend) | SRS §2 FR-72, Design §18 |
| 195 | End-to-end propagation: qualification seam attaches the window to kept candidates → Visual Director `_attach_candidate_windows` re-attaches by `source_url` and `_exec_tiktok_clip` threads it into the asset dict → Composer `_smart_trim` clamps to source bounds (degenerate ⇒ full clip) and `_trim_long_clip` / `_stretch_short_clip` emit `-ss <source_start_sec>` | SRS §2 FR-72, Design §18 |
| 196 | Transcript backend DEFERRED (post-v2.4.0): faster-whisper behind a config flag, yt-dlp auto-caption extraction, and keyframe-precise snapping. Blocked by ADR 0026 (do-not-rebuild), the GPU-forbidden constraint, no existing transcript infra, and the fact that the v2.4.0 release gate does NOT require clip-windowing. The "trimmed segment matches beat's spoken point" verification criterion waits for this backend (the v1 default cannot satisfy it because it never narrows the window) | ADR 0026, Design §18 |
| 197 | Visual Director LLM JSON-parse robustness (job_17 fix): `_llm_plan_scenes_response` requests OpenRouter JSON mode (`response_format={"type":"json_object"}`) on both traced + untraced paths (forwarded via `chat_traced`'s `**kwargs`), and the parse is centralized in a static `_parse_scenes_json` backed by a `json_repair` salvage net (both passes must fail to raise). MiMo-V2.5 supports `json_object` but NOT native strict `json_schema` (schema enforcement is prompt-based/"transformed"). Schema defense: `_parse_scenes_json` rejects non-list `scenes` AND non-dict scene items → routes to the deterministic fallback (covers ALL beats) so `_normalize_beat_plan` never sees invalid items. Both planning entry points return `None` on an empty recovered plan (routes to legacy fallback, not a 0-scene G9-tripping plan). Eliminates the malformed-JSON → 0-assets → G9 hard-fail class. `json-repair==0.61.0` pinned | SRS §2 FR-73, Design §Visual Director Beat-Driven Planning, ADR 0026 |

### From ADR 0030 — Inter-Agent Contract Gates (job_18 root cause, investigation complete / implementation pending)

| # | Fact | New Location |
|---|------|-------------|
| 198 | job_18 root cause: Scriptwriter (`qwen/qwen3-32b`) emitted `narrative_structure` `word_range` covering only words 0–23 of 76; `_validate_output` checks word-count + emoji, never coverage; `_normalize_narrative_structure` only backfills missing fields → 52 words / ~23 s of narration had NO beat → `build_canonical_timeline` stretched the last beat into a 25.17 s mega-beat → Visual Director planned one wrong-artist scene (Jennifer Coppen for Sarwendah) → Composer `-shortest` cut the last ~2.6 s ("…like dan share") → Reviewer total-duration-only `_check_av_sync` PASSED (structurally defeated by `-shortest` equalization) → repair re-derived the timeline from the broken structure → job "completed" unpostable (~60 % static: one image ~8 s, near-black "KOMEN DI BAWAH!" card ~24 s) | PRD §5 PR-38..PR-44, SRS §2 FR-74..FR-80, Design §19, ADR 0030 |
| 199 | ADR 0030 decision: KEEP the 7-agent chain + audio-first beat-driven architecture; ADD deterministic contract gates at every inter-agent boundary + fix the repair router + remove `-shortest`. NOT a restructure — MoneyPrinterTurbo's opaque-string topology was REJECTED (would discard the richer beat-driven contract, which research shows is AHEAD of per-sentence tools and is NOT the job_18 problem). ADR 0030 amends ADR 0026's no-rebuild default FOR OUTPUT-QUALITY WORK ONLY (product owner lifted the constraint) | ADR 0030, Design §19 |
| 200 | G7 GateNarrativeCoverage: assert `word_range` union == `[0, word_count-1]`, contiguous, in-bounds, AFTER Scriptwriter BEFORE Voice Producer; in-place repair for tail <5 % of words else hard-fail routing repair to Scriptwriter (NOT Visual Director). **FIX-8 (cue-anchor):** the LLM cannot reliably count words (job_19 over-index, job_20 under-index), so the Scriptwriter emits `start_cue` (3-5 verbatim first words of each beat) and `core/beat_anchor.py::derive_word_ranges` derives `word_range` (fuzzy `max(Jaccard, LCS) ≥ 0.6`, deterministic Indonesian tokenizer). Cue failures (`cue_not_found` / `cue_out_of_order`) → stable `narrative_not_covered` routing token → FIX-5 Scriptwriter regen. THE load-bearing fix | PRD §5 PR-38, SRS §2 FR-74, Design §19 |
| 201 | Audio-as-master: drop Composer `-shortest` → `-t voiceover_duration`; pre-render pad visual ≥ `voiceover_duration_sec`; G9.5 GateVisualAudioCoverage (VD→Composer); G10 `AUDIO_NOT_TRUNCATED` independent audio-stream re-probe (`>= voiceover_duration_sec - 0.5 s`, immune to `-shortest` equalization). MoneyPrinterTurbo policy adopted without its topology | PRD §5 PR-39, SRS §2 FR-75, Design §19 |
| 202 | Entity-binding rejection at the shared `candidate_semantic_ranker` chokepoint (`WRONG_ENTITY` rule — `subject_name` must overlap beat `spoken_point` + `main_entities`, fuzzy for aliases), VLM inspector `subject_name` required (missing ⇒ revise), `person_match` 0.8→0.6, `MAX_BEAT_DURATION_SEC`/max-scene cap (~12 s). Cache-key parity ⇒ one rule fixes pre-VD qualification AND Visual Director. CLIP image-text ranking DEFERRED to Phase 27+ | PRD §5 PR-40, SRS §2 FR-76, Design §19 |
| 203 | Repair-router root-cause routing: `_rerun_upstream_cascade` routes by failure REASON (Scriptwriter=coverage, VD=entity/dwell, Composer=audio); forces `narrative_structure` regen on coverage re-fail; bounded `MAX_REPAIR_CYCLES` + terminal fail-state (a job that cannot satisfy the coverage gate after N regens FAILS, never "completes" garbage); voiceover-text-diff skip optimization | PRD §5 PR-43, SRS §2 FR-78, Design §19 |
| 204 | Engagement gates (post-worthy bar): VISUAL-CHANGE-DENSITY (min change-events per 1.5–4 s; ~8–15 for 30 s), HOOK (beat 0 real image not title card; first change by 1.5 s), DURATION-BAND (21–42 s), MONOTONY (no same content-hash across consecutive beats without treatment variation). WARN+repair, not pipeline-death; creator-economy guidance not hard TikTok-API data | PRD §5 PR-44, SRS §2 FR-80, Design §20 |
| 205 | Deferred (Phase 27+): CLIP image-text cosine similarity for final candidate relevance; multimodal "watch the rendered video" Reviewer (claude-auto-tok style). The deterministic gates (FR-74..FR-80) are the primary line; these are higher-fidelity optional upgrades | ADR 0030, Design §19.5 |

---

## Requirements Traceability Matrix

### MVP P0 Requirements

| PRD ID | SRS ID | Design Section | Gate | Edge Cases | Validation |
|--------|--------|---------------|------|------------|------------|
| PR-01 | FR-01 | §3 Gated Pipeline | All gates | Empty topic, no niche config | G1 preflight |
| PR-02 | FR-01..FR-14 | §3, §4 | G1-G10 | See edge case catalog below | Gate definitions |
| PR-03 | FR-17 | §14 Dashboard | N/A | Dashboard unavailable | N/A |
| PR-04 | FR-18 | §14 CLI | N/A | Invalid CLI args | N/A |
| PR-05 | FR-10 | §3, §14 Output | G10 | Missing file, wrong format | Deterministic check — **Phase 15a**: `clipper_agency/rendering/engine.py` produces video via template-driven rendering; `clipper_agency/rendering/thumbnails.py` generates thumbnail; tests: `tests/test_rendering_engine.py`, `tests/test_rendering_thumbnails.py` |
| PR-06 | FR-27 | §9 Config | N/A | Invalid config | Config validation |
| PR-10 | FR-02 | §4 Safety, §3 G4 | G4 pre + post | See safety edge cases | G1 preflight + G4 |
| PR-11 | FR-13 | §3 G2 | G2 | Zero credits | G2 estimate |
| PR-15 | NFR-04 | §12 Cost | N/A | Model pricing change | Cost recalculation |
| PR-22 | FR-24 | §9 Config, §9 Env Layer | N/A | Missing model env var | Default to `mimo-v2-flash` |
| PR-23 | FR-25, NFR-10 | §2 Logging | N/A | Log level misconfigured | Default to INFO |
| PR-25 | FR-06 | §4 Voice Provider, §9 Env Layer | G8 | ElevenLabs missing/fails, Gemini missing/fails, Fish Audio missing/fails | Try fallback order, persist attempts, then clear error/stop pipeline |
| PR-26 | FR-32 | §7 Treatment System, §10 Templates | N/A | Invalid treatment YAML, unknown treatment type, missing FFmpeg filter | `templates/treatments.yaml` validated at load time; unknown treatments fall back to `broll_standard` |
| PR-27 | FR-33 | §7 Scene Normalization | G9 | Mixed framerates, non-1:1 SAR, static images, flash frames | Scene normalizer in Composer pipeline: framerate→30fps, SAR→1:1, zoompan for images, reject <1s clips |
| PR-28 | FR-34, FR-35, FR-36 | §7 Audio/Subtitle/Transition, §4 Composer | G9, G10 | Audio silence padding, missing script text, xfade on short clips, special chars in drawtext | Audio sequencer + subtitle engine + xfade chain + production flags |
| PR-29 | FR-37, FR-38, FR-39, FR-40, FR-41, FR-42 | §7 Audio-First Architecture, §3 G7/G8/G10, §4 Agent Contracts | G7, G8, G9, G10 | TTS too long/short (atempo ±15%), single TTS failure, word timestamp inaccuracy, clip longer than beat (smart trim), clip shorter (slow 30%), downloaded clip watermarks, no video clips (text_only), fewer clips than stories (deep dive), generic stock for named-person (visual rules), unverified claim as fact (reviewer catch) | Story beats with visual rules, continuous voiceover contract, word-level timestamps, beat-driven visual planning, smart scene trimming, keyword captions, 4 reviewer quality checks, shared schema.py contract |
| PR-30 | FR-43, FR-44, FR-45, FR-46, FR-47, FR-48, FR-49, FR-50 | §13 Deterministic Quality Gates, §3 G10, §4 Agent Roles | G10 (extended) | Black/freeze frames undetected, text collisions from overlapping overlays, safe-area violations, story mode vs actual composition mismatch, claim-to-visual irrelevance, repair routing to wrong agent | Deterministic gate chain (visual_coverage→text_collision→safe_area→package_consistency→timestamp_semantic→semantic_review→LLM), evidence contracts on StoryBeat, repair routing table, 10 pure-function core modules |
| PR-36 | FR-67, FR-68 | §16 Reviewer Context + Diagnostics Enforcement | G10 (extended) | Engine omits diagnostics/manifest; Pydantic manifest not dict; timestamp semantic review skips | Reviewer receives serialized manifest + diagnostics in normal and repair rerun paths; gate chain includes timestamp_semantic before semantic_review |
| PR-37 | FR-69 | §17 Pre-VD Qualification Boundary | Pre-VD (no new gate) | Beat has zero qualified candidates (all rejected); recovery discovers nothing new; recovery budget exhausted; cache-key drift would double-spend VLM | `clipper_agency/core/asset_qualification.py` qualifies each beat before VD; engine seam `_apply_asset_qualification` rewrites `beat.asset_candidates` to qualified set only and writes `qualification_report.json`; recovery-before-text-card with `MAX_RECOVERY_CYCLES=1`; cache-key parity hard gate (SLICE 1) → 0 double-VLM; SLICE 12 Job #8 regression proves M<N text-cards; ADR 0026/0027 |

### MVP P1 Requirements

| PRD ID | SRS ID | Design Section | Gate | Edge Cases | Validation |
|--------|--------|---------------|------|------------|------------|
| PR-07 | FR-21 | §10 Templates | N/A | Invalid template config | Config validation — **Phase 15a**: `clipper_agency/rendering/templates.py`, `clipper_agency/rendering/renderers/news_card.py`, `clipper_agency/rendering/renderers/b_roll_narration.py`, `clipper_agency/rendering/renderers/rapid_update.py`; tests: `tests/test_rendering_templates.py`, `tests/test_rendering_adapters.py` |
| PR-08 | FR-20 | §9 Autonomy Levels | N/A | Invalid autonomy setting | Config validation |
| PR-12 | SRS §5 | §9 Auth | N/A | Unauthorized access | Auth check |
| PR-24 | FR-19 | §13 CLI | N/A | Invalid agent name | CLI validation |
| PR-09 | — | Stage 2 | — | — | — |
| PR-13 | — | Stage 2 | — | — | — |
| PR-14 | — | Stage 2 | — | — | — |
| PR-16 | — | Stage 2 | — | — | — |

### ADR 0030 Requirements (job_18 output-quality — investigation complete, implementation pending)

| PRD ID | SRS ID | Design Section | Gate | Edge Cases | Validation |
|--------|--------|---------------|------|------------|------------|
| PR-38 | FR-74 | §19 Inter-Agent Contract Gates | G7 GateNarrativeCoverage (new) | E53 — `word_range` under-covers script | Tokenize `voiceover_text`; assert union == `[0, word_count-1]`, contiguous, in-bounds; in-place repair for tail <5 % else hard-fail → Scriptwriter. Frozen job_18 fixture (24/76) fails + routes to scriptwriter |
| PR-39 | FR-75 | §19 Audio-as-Master | G9.5 visual-coverage (new) + G10 `AUDIO_NOT_TRUNCATED` (strengthened) | E55, E56 — visual < audio; `-shortest` truncates CTA | Drop `-shortest` → `-t voiceover_duration`; pre-render pad visual ≥ audio; G10 independently re-probes audio stream |
| PR-40 | FR-76 | §19 Entity-Binding | Pre-VD qualification + VD chokepoint (no new gate — rejection rule) | E57, E58 — wrong-artist asset; VLM omits subject_name | `WRONG_ENTITY` rule at `candidate_semantic_ranker` (subject_name vs beat entities); `person_match` 0.8→0.6; MAX-scene cap; cache-key parity holds |
| PR-41 | FR-77 | §19 Reviewer Per-Scene Detection | G10 (extended) | frozen card, wrong face in right window, truncated audio | Per-scene entity-vs-beat + audio-not-truncated + max-dwell/frozen-frame checks extend `_check_av_sync` past the total-duration scalar. **FIX-4 IMPLEMENTED:** entity-vs-beat (`ENTITY_MISMATCH`, reuses FIX-3 `derive_expected_entities`/`entity_overlap`; `subject_name` threaded VD→manifest→`SceneBeatMapping`) + audio-not-truncated reviewer re-probe (`AUDIO_TRUNCATED_REVIEWER`, reuses `media_probe.AUDIO_TRUNC_TOL_SEC`; `voiceover_duration_sec` wired on both engine reviewer paths). **DEFERRED:** max-dwell/frozen-frame → FIX-7 (engagement); uncovered-tail-scene redundant with PR-42 (FIX-6 UNCOVERED_TAIL) |
| PR-42 | FR-79 | §19 Timeline Backstop | Pre-VD (no new gate — builder signal) | E54 — 25 s mega-beat | `build_canonical_timeline` UNCOVERED_TAIL detection + `MAX_BEAT_DURATION_SEC` cap (12 s); defense-in-depth behind PR-38 |
| PR-43 | FR-78 | §19 Repair-Router Root-Cause Routing | Repair loop | E59 — coverage re-fails on regen | Route by REASON to root agent; force narrative regen; bounded `MAX_REPAIR_CYCLES` + terminal fail (never "complete" garbage) |
| PR-44 | FR-80 | §20 Engagement Gates | Reviewer programmatic_checks | E60 — frozen card / low visual-change-density | WARN+repair gates: visual-change-density, hook-on-beat-0, duration-band 21–42 s, monotony guard. Not pipeline-death |

---

## Edge Case Catalog

### Safety Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E1 | Topic looks safe but research reveals defamation risk | Post-research risk gate (G4) hard-fails | Design §3 G4 |
| E2 | Topic is ambiguous — could be safe or unsafe | G4 uses GLM-4-9B for classification, soft-warning if unclear | Design §3 G4 |
| E3 | Researcher returns risk_flags | G4 processes flags; hard-fail on high-risk, soft-fail on unverified | Design §3 G4 |
| E4 | Entity mentioned is a real person with defamation potential | G4 checks entities list; requires cautious wording | Design §3 G4 |
| E5 | Safety hard-block needs override | **No override for hard-block.** Only soft-warnings can be overridden by Creative Lead or Admin. | PRD §6 |
| E5a | Reviewer catches safety issue Safety Agent missed | Reviewer rejects. Admin/Creative Lead decides. Safety rules should be reviewed but no automatic feedback loop in MVP. | PRD §8 |

### Research Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E6 | ScrapeCreators quota exhausted (75 credits) | Ask Admin/Creative Lead for source URL or use Pexels/generated | PRD §8, SRS §4 |
| E7 | Firecrawl daily quota exhausted | Same as E6 | PRD §8, SRS §4 |
| E8 | Both providers fail | Ask Admin/Creative Lead for source URL. If none: Pexels/generated cards | PRD §8 |
| E9 | Research returns 0 usable URLs | G5 hard-fail → ask Admin/Creative Lead for source URL | Design §3 G5 |
| E9a | Research returns completely empty output (no URLs, no context, no entities) | G5 hard-fail → stop job. No grounding for script generation. | Design §3 G5 |
| E10 | Research returns only 1 usable URL | G5 soft-fail → proceed with Pexels/generated cards, log risk | Design §3 G5 |
| E11 | Cached research is stale (60-240 min) | Reuse with stale marking, log | Design §3 G3 |
| E12 | Cache key collision (different artists, same topic cluster) | Entities in cache key prevent collision | Design §5 |

### Voice Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E13 | ElevenLabs API fails | Try Gemini TTS; if Gemini fails/missing, try Fish Audio; if all fail, stop clearly. | PRD §8, SRS §4 |
| E14 | ElevenLabs rate limit hit | Same as E13; sanitized provider attempt recorded. | PRD §8, SRS §4 |
| E15 | Generated audio file is corrupt | G8 hard-fail → stop, human retry | Design §3 G8 |
| E16 | Audio duration mismatch with script | G8 soft-fail if <2s, hard-fail if way off | Design §3 G8 |
| E16a | Gemini TTS key missing or PCM/WAV conversion fails | Try Fish Audio; if all providers fail, stop clearly with attempts persisted. | SRS §4, Design §9 |
| E16b | All TTS providers missing or return non-success | Voice Producer returns clear failure, no visual/composer work starts. | PRD §8, SRS §2 FR-06 |

### Visual/Asset Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E17 | yt-dlp download fails for a URL | Try next URL in list (max 5 attempts) | PRD §8 |
| E18 | All yt-dlp downloads fail | G9 hard-fail if no valid assets. Pexels fallback if configured. | Design §3 G9 |
| E19 | Downloaded clip > 5 seconds | Trim to 5s max during Visual Director processing | Design §7 |
| E19a | Downloaded clip < 1 second | Rejected by G9 (flash frame, not usable) | Design §3 G9, Design §7 |
| E20 | Downloaded file is corrupt or 0 bytes | G9 validates each asset (file size > 0), skips corrupt ones | Design §3 G9 |
| E21 | No Pexels API key configured | Generated cards only. If no cards: hard-fail. | Design §3 G9 |
| E21a | Scene normalization fails (wrong resolution/codec after re-encode) | Clip excluded from concat; provenance records failure. If no valid clips remain, G9 handles. | Design §7 |
| E21b | Visual Director LLM returns invalid JSON or schema mismatch | `_plan_with_llm()` catches parse error, logs warning, returns `None` → falls back to legacy sequential planning | SRS §2 FR-07, Design §4 |
| E21c | Visual Director LLM returns empty plan (0 actions) | Treated as LLM failure, falls back to legacy sequential planning | SRS §2 FR-07, Design §4 |
| E21d | Visual Director dispatch encounters unknown action type | `_execute_action()` logs warning, skips unknown action, scene gets text_card fallback | SRS §2 FR-07, Design §4 |
| E21e | All 3-tier image fallbacks fail for a text card (Pexels down, Firecrawl fails, gradient generator error) | Text card generated with plain colored background (no image); provenance records all failures | SRS §2 FR-07, Design §4 |
| E21f | Treatment YAML missing or invalid (malformed, missing required fields) | Composer falls back to `broll_standard` treatment for all scenes; warning logged; `provenance.json` records fallback | PRD §5 PR-26, SRS §2 FR-32 |
| E21g | Visual Director selects unknown treatment type | Default routing applied (text_card→text_card_reveal, video→broll_standard, image→ken_burns_zoom_in); provenance records original and fallback | PRD §5 PR-26, Design §4 |
| E21h | Pre-VD qualification: a beat has zero qualified candidates after scoring (all rejected) | Bounded RECOVER stage re-runs Segment Producer discovery for fresh candidates and re-scores BEFORE the text-card fallback (`MAX_RECOVERY_CYCLES=1`); only if recovery still yields nothing does the beat emit a `verdict='exhausted_text_card'` text card | PRD §5 PR-37, SRS §2 FR-69, Design §17, ADR 0026 |
| E21i | Pre-VD qualification: cache-key drift between qualifier and VD | Hard-gated by SLICE 1 (`asset_qualification._score_candidate` and `VD._score_one_candidate` compute byte-identical cache keys); VD's re-inspection of a pre-qualified candidate is a cache hit → 0 double-VLM spend | SRS §2 FR-69, Design §17, ADR 0027 |

### Composer Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E22 | FFmpeg render fails | Stop. Admin/Creative Lead triggers retry. Max 3 retries. | PRD §8 |
| E23 | Rendered video has no audio track | G10 hard-fail | Design §3 G10 |
| E24 | Rendered video wrong resolution | G10 hard-fail | Design §3 G10 |
| E24a | Rendered video is 0 bytes | G10 hard-fail (file size > 1KB check) | Design §3 G10 |
| E25 | Rendered video too long/short | G10 checks 20-60s range | Design §3 G10 |
| E25a | FFmpeg preflight diagnostic fails (missing ffmpeg, libx264, aac, or mp3) | Pipeline stops before any render work with clear diagnostic message. Admin/Creative Lead must fix system environment. | SRS §2 FR-29, Design §7 |
| E25b | Scene normalizer encounters variable-framerate clip (VFR) | FFmpeg `-fps_mode cfr` forces constant 30fps; provenance records original and target fps | PRD §5 PR-27, SRS §2 FR-33 |
| E25c | Scene normalizer encounters SAR ≠ 1:1 (e.g., 4:3 display aspect with 16:9 storage) | `setsar=1:1` filter applied; provenance records original SAR | PRD §5 PR-27, SRS §2 FR-33 |
| E25d | Static image needs conversion to video segment | Ken Burns zoompan applied (2.5s zoom cycle, max zoom 1.5x); output at 30fps, 1080x1920 | PRD §5 PR-27, SRS §2 FR-33 |
| E26a | All voice files missing for audio concat | Audio sequencer returns `anullsrc` silent track; video renders without narration | PRD §8, Design §7 |
| E26b | xfade transition duration exceeds clip duration | Duration clamped to `min(trans_duration, min(prev_dur, next_dur) - 0.15)` with `MIN_TRANSITION_DUR=0.01` floor | PRD §5 PR-28, Design §7 |
| E26c | Script text contains special characters (colons, quotes, percent signs) | `escape_drawtext()` escapes `\`, `'`, `:`, `%` for FFmpeg drawtext filter | PRD §5 PR-28, Design §7 |
| E26d | Unknown transition type in asset metadata | Falls back to crossfade with default 0.3s duration; warning logged | PRD §5 PR-28, Design §7 |

### Audio-First Architecture Edge Cases (v2.0.0)

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E34 | TTS audio too long (exceeds 60s hard limit) | G8 hard-fail; FFmpeg atempo ±15% can adjust, but major overage stops pipeline | Design §3 G8, ADR 0021 |
| E35 | TTS audio too short (< 20s) | G8 soft-fail, continue with warning | Design §3 G8, ADR 0021 |
| E36 | Word timestamp inaccuracy (ElevenLabs drift) | Character-level grouping is proven accurate; ±50ms acceptable | Design §4, ADR 0021 |
| E37 | Clip longer than beat duration | Smart scene trimming at keyframe boundaries with ±15% tolerance + speed adjust ±20% | Design §7, SRS §2 FR-42, ADR 0021 |
| E38 | Clip shorter than beat duration | Slow down max 30% or loop | Design §7, SRS §2 FR-42, ADR 0021 |
| E39 | Downloaded clip has watermarks/captions | Leave them (authenticity). Our keyword captions go at bottom of frame, shifted up if overlap | Design §7, ADR 0021 |
| E40 | Segment Producer finds no video clips | Format = `text_only` or skip job | SRS §2 FR-03, ADR 0021 |
| E41 | Fewer clips than stories | Deep dive format instead of roundup (format_decision) | SRS §2 FR-03, ADR 0021 |
| E42 | Generic stock used for named-person story | Visual Director rejects per visual_must_not_show / do_not_use rules | SRS §2 FR-07, ADR 0021 |
| E43 | Unverified claim stated as fact | Reviewer fact_safety check catches; Scriptwriter uses safe_wording | SRS §2 FR-09, ADR 0021 |
| E44 | Gemini TTS fallback returns no timestamps | FFmpeg silencedetect provides approximate timing (less precise but functional) | Design §4, ADR 0021 |
| E45 | Voice Provider single TTS call fails | Same fallback chain: ElevenLabs → Gemini TTS → Fish Audio → fail clearly | SRS §2 FR-06, ADR 0021 |

### Reviewer Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E26 | Reviewer rejects (1st time) | Recommend specific step to retry. Human triggers. | PRD §8, Design §4 |
| E27 | Reviewer rejects (2nd time) | Human review required. No more auto-retry. | PRD §8, Design §4 |
| E28 | Variation exhausted | MVP: human review. Stage 2: Creative Director. | Design §8 |

### Deterministic Quality Gate Edge Cases (Phase 21)

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E46 | Visual coverage detects black/freeze frame | `visual_coverage` gate fails → repair router routes to Composer for re-render | SRS §2 FR-43, Design §13 |
| E47 | Text collision between caption and source clip text | `text_collision` gate fails → repair router routes to Visual Director for overlay repositioning | SRS §2 FR-44, Design §13 |
| E48 | Caption placed in TikTok safe zone | `safe_area` gate fails → repair router routes to Visual Director for safe-area adjustment | SRS §2 FR-45, Design §13 |
| E49 | Story mode declared as roundup but actual composition is deep dive | `package_consistency` gate fails → repair router routes to Segment Producer for beat adjustment | SRS §2 FR-46/FR-48, Design §13 |
| E50 | Narration describes specific person but visuals show generic stock | `semantic_visual_review` gate fails → repair router routes to Segment Producer for visual_must_show update | SRS §2 FR-49, Design §13 |
| E51 | Repair plan targets multiple agents | Engine executes patches in dependency order: Segment Producer → Visual Director → Composer | SRS §2 FR-50, Design §13 |
| E52 | All deterministic gates pass but LLM rejects | LLM rejection follows existing Reviewer retry policy (max 2 human-triggered retries) | PRD §8, Design §4 |

### Cost/Credit Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E29 | Not enough credits for any provider | G2 hard-fail before any spending | Design §3 G2 |
| E30 | Cost estimate exceeds expected range | G2 soft-fail, show warning, require acknowledgment | Design §3 G2 |
| E31 | Provider pricing changes | Cost estimates use config-driven pricing, recalculate | Design §12 |
| E32 | Multiple jobs depleting shared credits simultaneously | MVP: SQLite WAL + advisory lock prevents concurrent runs. Sequential enforcement. | SRS §8 |
| E33 | Job paused mid-pipeline | PAUSED state. State persisted in DB. Resume re-runs current step with same config snapshot. Credits and cache re-validated on resume. | Design §3.3 |

### General Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E34 | Topic is whitespace-only (`"   "`, `"\t"`) | G1 hard-fail: topic must be non-empty after trim | Design §3 G1 |
| E35 | Niche specifies language not supported by LLM | G1 hard-fail: language-model compatibility check | Design §3 G1 |
| E36 | User provides source URL not supported by yt-dlp | G5 checks domain against supported sites list. Soft-fail: continue without that URL. | Design §3 G5 |
| E37 | Config changed while job running | Running jobs use config snapshot at creation time | Design §9 |
| E38 | Niche config missing required fields | G1 hard-fail, specific error message | Design §3 G1 |
| E39 | Platform (TikTok) policy changes | Safety rules configurable per niche, no code change | PRD §3 |

### ADR 0030 / job_18 Edge Cases (Inter-Agent Contract Gates)

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E53 | Scriptwriter `word_range` does not cover all `voiceover_text` words (job_18: 24/76) | G7 GateNarrativeCoverage fails; in-place repair if tail <5 % of words, else hard-fail routing repair to **Scriptwriter** (not VD) with "cover ALL words" instruction | SRS §2 FR-74, Design §19 |
| E54 | `build_canonical_timeline` would manufacture a >12 s mega-beat from an uncovered tail | UNCOVERED_TAIL detection + `MAX_BEAT_DURATION_SEC` cap reject the non-physical entry + surface a structured signal the orchestrator gates on | SRS §2 FR-79, Design §19 |
| E55 | Visual track sums to less than voiceover duration (xfade shrinkage) | G9.5 GateVisualAudioCoverage fails pre-render; Composer pads (loop/extend) OR repair routes to VD; `-shortest` removed so audio is never the cut stream | SRS §2 FR-75, Design §19 |
| E56 | Composer `-shortest` would truncate the CTA audio | replaced by `-t voiceover_duration`; G10 `AUDIO_NOT_TRUNCATED` re-probe independently asserts audio ≥ `voiceover_duration_sec - 0.5 s` | SRS §2 FR-75, Design §19 |
| E57 | Selected asset depicts the wrong entity (job_18: Jennifer Coppen for Sarwendah beat) | `WRONG_ENTITY` rejection at the shared `candidate_semantic_ranker` chokepoint (subject_name vs beat `spoken_point`+`main_entities`); beat falls back / recovers | SRS §2 FR-76, Design §19 |
| E58 | VLM inspector omits `subject_name` | degrades to `revise` (NOT accept) — entity binding cannot be satisfied | SRS §2 FR-76, Design §19 |
| E59 | Repair loop keeps re-failing the coverage gate (model regenerates partial coverage) | bounded `MAX_REPAIR_CYCLES`; after N failed regens the job FAILS (terminal state) — never "completes" garbage | SRS §2 FR-78, Design §19 |
| E60 | A single static card held >4 s, or a 1–2-image plan for a 25 s+ tail | Engagement gates (VISUAL-CHANGE-DENSITY + MAX-DWELL + MONOTONY) flag as a "low-effort tell"; WARN+repair routes to VD/Scriptwriter (not pipeline-death) | SRS §2 FR-80, Design §20 |

---

## Adversarial Review Checklist

Use this checklist to verify the documentation set is airtight. Any reviewer (human or AI model) should answer "yes" to all questions or identify a specific gap.

### Cross-Document Alignment

- [ ] Every PRD requirement has a corresponding SRS requirement (check priority alignment: PR-10/FR-02 and PR-11/FR-13 are both P0).
- [ ] Every SRS requirement has a corresponding technical design section (check FR-17 autonomy levels, NFR-05/06 startup/load times).
- [ ] Pipeline order is identical across PRD §5 PR-02, SRS §2, Design §3 (must include Post-Research Risk Gate).
- [ ] Safety rules are consistent across PRD §6, SRS §7, Design §3 G4 (placement may differ but rules must match).
- [ ] Failure/fallback behavior is consistent across PRD §8, SRS §2, Design §3 (retry limits and roles must match).
- [ ] Cost principles in PRD §7 are implemented via gates in Design §3 (not necessarily repeated as principles in SRS/Design).
- [ ] MVP scope dimensions (1 client, TikTok, Indonesian, etc.) are stated in PRD §3 and referenced in SRS/Design.
- [ ] Provider routing is consistent across SRS §4 (research) and Design §2 (media download) — note these are different routing chains for different purposes.
- [ ] Asset safeguards (clip duration, transformation, fallback) are consistent across PRD §9, SRS §7, Design §7.
- [ ] TTS fallback order is consistent across PRD §3/§5/§8, SRS §2/§4, and Design §4/§9.
- [ ] Job workspace and final output package boundaries are consistent across PRD §4, SRS §2/§6, and Design §1/§4/§7.

### Flow Completeness

- [ ] Every pipeline step has a defined gate before it.
- [ ] Every gate has pass/soft-fail/hard-fail conditions.
- [ ] Every hard-fail has a human escalation path.
- [ ] Every agent has defined input, output, cost tier, and caching behavior.
- [ ] Retry policy is explicit at every failure point.
- [ ] No implicit assumptions about agent ordering.

### Safety Airtight

- [ ] Pre-research safety gate exists (G1 + A1).
- [ ] Post-research safety gate exists (G4).
- [ ] Hard-block has no override path.
- [ ] Soft-warning override requires reason + admin alert.
- [ ] Every gate that could encounter safety issues has safety-aware logic.

### Cost/Credit Airtight

- [ ] No paid API call happens before a gate validates it is needed.
- [ ] Cache check happens before provider call.
- [ ] Deterministic checks happen before LLM checks.
- [ ] Cheap models used before expensive models.
- [ ] ElevenLabs only after script validation.
- [ ] FFmpeg only after audio + asset validation.
- [ ] Reviewer only after deterministic video validation.

### Edge Cases

- [ ] Every edge case in the catalog has a defined handling strategy.
- [ ] No edge case results in silent failure.
- [ ] No edge case results in unbounded spending.
- [ ] No edge case results in unsafe content being published.
- [ ] Provider fallback failures leave enough sanitized diagnostics to explain what happened without exposing secrets.
- [ ] Raw and normalized research artifacts are distinct so retries/debugging do not lose provider evidence.

### Missing/Gap Check

- [ ] No requirement exists in old docs that is missing from new docs (see fact register).
- [ ] No undefined term used without explanation.
- [ ] No "TODO" or "TBD" left in MVP sections.
- [ ] No Stage 2+ detail bloating MVP sections.

---

## Glossary

### Acronyms

| Acronym | Full Form | Context |
|---------|-----------|---------|
| **LLM** | Large Language Model | AI model for text generation (GPT, Claude, Qwen, etc.) |
| **TTL** | Time To Live | Cache expiry policy — research cache freshness window |
| **WAL** | Write-Ahead Logging | SQLite journaling mode for safe concurrent reads during writes |
| **NFR** | Non-Functional Requirement | Performance, scalability, and operational requirements (SRS §3) |
| **ADR** | Architecture Decision Record | Documented rationale for major technical choices (`docs/adr/`) |
| **API** | Application Programming Interface | External service integration (OpenRouter, ElevenLabs, etc.) |
| **CLI** | Command Line Interface | Terminal-based pipeline execution (`python3 cli.py run ...`) |
| **FFmpeg** | Fast Forward MPEG | Cross-platform video/audio processing framework |
| **yt-dlp** | YouTube Download (plus) | Command-line tool to download video/audio from 1000+ sites |

### Indonesian Terms

| Term | Translation | Usage Context |
|------|-------------|---------------|
| **dikabarkan** | reported / said to be | Soft wording for unverified claims (safety soft-warning) |
| **ramai dibahas netizen** | widely discussed by netizens | Hedging phrase for trending but unconfirmed stories |
| **klarifikasi** | clarification | Research query term for artist response/clarification events |
| **viral** | viral | Trending content indicator (same in English) |
| **rilis lagu** | song release | Research query term for new music releases |
| **hubungan** | relationship | Research query term for gossip/relationship news |

### Technical Terms

| Term | Definition |
|------|------------|
| **Gate** | Checkpoint in the pipeline that evaluates pass/soft-fail/hard-fail before proceeding |
| **Niche** | Configurable content profile (language, tone, audience, rules, providers) |
| **Agent** | Independent processing unit with defined input/output contract (Safety, Researcher, etc.) |
| **Orchestrator** | Coordination layer that manages agent execution via database-driven state machine |
| **Autonomy Level** | Per-agent setting controlling how orchestrator handles gate transitions (autonomous, semi-autonomous, manual) |
| **Creative Memory** | System that tracks used angles/templates/assets to prevent repetitive content |
| **Config Hierarchy** | Agent defaults → Niche → Account → Job-level overrides |
| **Output Package** | Delivered artifacts: video.mp4 + caption.txt + thumbnail.png + metadata.json |
| **Generated Cards** | Text-based PNG images (1080x1920) created by Visual Director as last-resort visual fallback |
| **Template Loader** | YAML template parser and validator (`clipper_agency/rendering/templates.py`) — loads template definitions with required field validation |
| **Render Contract** | Typed data model (`clipper_agency/rendering/contracts.py`) defining clips, audio, text overlays, and transitions for the FFmpeg engine |
| **Render Engine** | FFmpeg filter graph orchestrator (`clipper_agency/rendering/engine.py`) — assembles primitives into a two-pass render pipeline |
| **Rendering Primitives** | Shared FFmpeg filter chain builders (`clipper_agency/rendering/primitives.py`) — concat, fade, crossfade, drawtext, audio mix |
| **Template Adapter** | Per-template renderer that translates YAML spec + scene data into a `RenderContract` (News Card, B-Roll, Rapid Update) |
| **Treatment** | Data-driven visual effect definition (Ken Burns, slow-motion, etc.) in `templates/treatments.yaml`, applied by Composer via FFmpeg filter chains |
| **Scene Normalizer** | Pipeline stage that unifies mixed-asset framerates, SAR, and encoding parameters before concat; part of Composer rendering flow |
| **Audio Sequencer** | Per-scene audio+video concat filter builder (`clipper_agency/rendering/audio_sequencer.py`) — pairs voice files with video clips, pads missing audio with silence |
| **Subtitle Engine** | Script text → timed CaptionOverlay converter (`clipper_agency/rendering/subtitle_engine.py`) — generates drawtext filter parameters with absolute timestamps |
| **Treatment Filter Builder** | Per-scene FFmpeg filter string builder (`clipper_agency/rendering/treatment_filters.py`) — variable substitution and input-type-aware filter generation |
| **Treatment Config** | YAML loader for treatment/transition definitions (`clipper_agency/rendering/treatment_config.py`) — frozen dataclasses for immutable config access |
| **Content Direction** | Researcher-recommended video format, story selection, and content angle — validated by Orchestrator before Scriptwriter execution |
| **Content Planning Config** | Deterministic configuration block (`ContentPlanningConfig`) governing format, max story count, target/hard duration limits, and words-per-second estimate |
| **Timeline Reconciler** | Orchestrator-owned deterministic service that creates a canonical timeline from Researcher direction + Scriptwriter output + Voice Producer actual audio durations |
| **Canonical Timeline** | Source-of-truth per-scene timing contract consumed by Visual Director and Composer; includes `start_sec`, `end_sec`, `role`, `audio_path`, `target_duration_sec`, `visual_instruction` |
| **Script Duration Gate** | Pre-TTS deterministic check that estimates total duration from word count and rejects scripts likely to exceed the hard limit |
| **Format Validator** | ~~Orchestrator service that validates Researcher content_direction against niche config and derives word/time budgets~~ (Removed in v2.0.0 — Segment Producer edit blueprint supersedes content_direction) |
| **Story Beat** | Primary data contract in audio-first architecture. Each beat carries visual_must_show/must_not_show rules, asset_candidates, overlay_text, caption_keywords, narration_goal, safe_wording |
| **Smart Scene Trimming** | Composer technique: ffprobe keyframe boundary detection with ±15% tolerance, speed adjustment ±20%, for fitting visuals to audio timeline |
| **Keyword Captions** | Short captions (max 6 words, beat-aligned, bottom-positioned) replacing full-sentence subtitles. Changed at each beat boundary |
| **Continuous Voiceover** | Single TTS call generating complete narration (75-110 words) with word-level timestamps, replacing 8 per-scene TTS calls (87.5% cost reduction) |
| **Visual Coverage** | Frame-level visual completeness check via sampled thumbnails — detects black/freeze frames and blank regions (`clipper_agency/core/visual_coverage.py`) |
| **Text Collision** | Overlap detection between on-screen text regions (captions, overlays, source text) — flags overlapping bounding boxes and excessive density (`clipper_agency/core/text_collision.py`) |
| **Safe Area** | TikTok safe-zone compliance check for caption/overlay placement — validates against top/bottom UI overlays and side action buttons (`clipper_agency/core/safe_area.py`) |
| **Story Mode** | Narrative structure classification (single_deep_dive, three_roundup, two_highlight) validated against actual scene composition (`clipper_agency/core/story_mode.py`) |
| **Duration Budget** | Per-role duration allocation distributing total video time across beats by role weight (hook, main_claim, evidence, reaction, closing_cta) (`clipper_agency/core/duration_budget.py`) |
| **Package Consistency** | Validation that declared story mode, scene count, clip types, and visual hierarchy match actual composition (`clipper_agency/core/package_consistency.py`) |
| **Semantic Visual Review** | Claim-to-visual alignment scoring using keyword overlap between narration goals and actual visual content with evidence contracts (`clipper_agency/core/semantic_visual_review.py`) |
| **Repair Router** | Quality failure → agent mapping service that produces targeted repair plans for specific agents without full pipeline re-runs (`clipper_agency/core/repair_router.py`) |
| **Evidence Contract** | Mapping on StoryBeat that links each claim to required visual evidence and tracks actual alignment score |
| **Reviewer Gate Chain** | Ordered deterministic quality checks run before LLM multimodal review: visual_coverage → text_collision → safe_area → package_consistency → timestamp_semantic → semantic_review → LLM |
| **Reviewer Context Bundle** | Engine-provided Reviewer kwargs: `story_beats`, `word_timestamps`, `rendered_scene_manifest`, and Composer `diagnostics` |
| **Asset Qualification Boundary** | Pre-Visual-Director in-process synchronous transform (`clipper_agency/core/asset_qualification.py`) wired via `_apply_asset_qualification` in `Engine._run_visual_director_phase`; scores each beat's candidates, runs source-recovery-before-text-card (`MAX_RECOVERY_CYCLES=1`), immutably rewrites `beat.asset_candidates` to the qualified set, and writes `qualification_report.json`. ADR 0026: pure orchestration (no new agent/gate/schema/state-machine); ADR 0027: inspection delegates to VD's own `_run_multimodal_inspection` for cache-key-parity (0 double-VLM) |
