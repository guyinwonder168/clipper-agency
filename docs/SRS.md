# Clipper Agency — Software Requirements Specification

**Version:** 3.0
**Date:** 2026-06-07
**Status:** v2.0.0 Architecture Redesign Complete — Audio-First Continuous Voiceover Implemented
**Related:** `docs/PRD.md`, `docs/technical_design.md`, `docs/requirements_traceability.md`

---

## 1. Platform Requirements

| Requirement | Specification |
|-------------|---------------|
| **OS** | Linux (primary), macOS (development), Windows (WSL2 acceptable) |
| **CPU** | x86_64, 4+ cores recommended for parallel FFmpeg |
| **GPU** | Not required (CPU-only FFmpeg rendering) |
| **RAM** | 8 GB minimum, 16 GB recommended |
| **Storage** | 20 GB free for outputs, assets, database |
| **Python** | 3.11+ |
| **FFmpeg** | 5.0+ with libx264, aac, mp3 support |
| **Docker** | Docker Compose for VPS deployment |

---

## 2. Functional Requirements

### 2.1 Pipeline

| ID | Requirement | Priority | Stage |
|----|-------------|----------|-------|
| FR-01 | Gated agent pipeline executes topic-to-output with pass/soft-fail/hard-fail at every transition | P0 | MVP |
| FR-02 | Safety Agent pre-checks topic before any paid generation using ultra-cheap model (GLM-4-9B) | P0 | MVP |
| FR-03 | Segment Producer Agent (formerly Researcher) gathers context + source URLs + music candidates via ScrapeCreators + Firecrawl, outputs structured edit blueprint with story_beats (visual_must_show/must_not_show, asset_candidates, overlay_text, caption_keywords), format_decision, verified_facts with safe_wording, unverified_claims, and do_not_use list. 5 sub-roles: Fact Checker, Viral Analyst, Clip Scout, Story Producer, Edit Planner. Renamed from `researcher.py` → `segment_producer.py`. See `docs/adr/0021-audio-first-continuous-voiceover.md` | P0 | MVP |
| FR-04 | Post-research risk gate: second safety check after real entities/claims/URLs are known | P0 | MVP |
| FR-05 | Scriptwriter Agent writes continuous voiceover narration (75-110 words, no emojis, spoken-word style) from Segment Producer's story_beats. Outputs voiceover_text + narrative_structure (beat_id, section, word_range, overlay_text, caption_keywords) + caption + hashtags. Removes per-scene max_words_per_scene formula in favor of total word budget | P0 | MVP |
| FR-06 | Voice Producer generates continuous voiceover via single TTS call (1 call instead of 8 per-scene = 87.5% cost reduction) with word-level timestamps. Primary: ElevenLabs `/with-timestamps` endpoint (character-level alignment grouped into words). Fallback: Gemini TTS (silence detection for approximate timing) → Fish Audio → fail clearly. Voice files and metadata saved under `ASSETS_CACHE/job_{id}/agents/voice_producer/` | P0 | MVP |
| FR-07 | Visual Director uses LLM to plan beat-driven visual strategy from story_beats + word-level timestamps. Each beat carries visual_must_show/visual_must_not_show rules, asset_candidates, and exact audio durations. Visual hierarchy: direct source clip → official screenshot → subject portrait with Ken Burns → text card → generic stock (abstract topics only). 3-tier image fallback for text cards: Pexels photo search → Firecrawl article image → gradient card. Falls back to legacy sequential planning when LLM unavailable. Sequential execution: Voice Producer must complete before Visual Director starts | P0 | MVP |
| FR-08 | Composer assembles video with single audio timeline (voiceover.mp3 as immutable anchor). Smart scene trimming: ffprobe keyframe boundary detection with ±15% tolerance, speed adjustment up to ±20% (imperceptible). Keyword captions (max 6 words, beat-aligned, bottom-positioned) replace full-sentence subtitles. Never trims or speeds up audio. Template-driven rendering via `clipper_agency/rendering/` engine with per-template adapters | P0 | MVP |
| FR-09 | Reviewer Agent performs 4 programmatic quality checks: (1) AV sync validation (audio vs visual duration drift < 0.5s), (2) caption quality (short keywords, max 6 words, not full sentences), (3) fact safety (unverified claims use safe wording, no definitive accusations), (4) narrative structure (beat completeness). Plus multimodal quality + safety + duplicate check. Max 2 retries by Admin/Creative Lead | P0 | MVP |
| FR-10 | Output packager produces `video.mp4` + `caption.txt` + `thumbnail.png` + `metadata.json` | P0 | MVP |
| FR-11 | Research cache with Time To Live (TTL): fresh <60min, stale 60-240min, expired >240min or new Asia/Jakarta day | P0 | MVP |
| FR-12 | Creative memory: pre-generation check prevents repetition; post-generation update records usage | P0 | MVP |
| FR-13 | Lightweight cost + credit estimate displayed before generation. Blocks job if insufficient credits. | P0 | MVP |
| FR-14 | Agent states, timestamps, failure summaries, gate results, and key artifact paths visible through debug-first dashboard/CLI observability | P0 | MVP |
| FR-15 | Asset/cache layout: intermediate agent/gate artifacts under `ASSETS_CACHE/job_{id}`, final customer package under `OUTPUT_DIR/job_{id}`, with downloaded media cacheable to avoid redundant downloads | P0 | MVP |
| FR-16 | Research data size guard: ScrapeCreators responses trimmed via `trim=true` + field extraction; researcher LLM input capped at 40K chars to prevent token overflow | P0 | MVP |
| FR-28 | Human-triggered retry and resume: CLI `job-retry <id> --from <agent>` re-runs from a specified agent, CLI `job-resume <id>` continues from a failed/paused stage; dashboard POST `/jobs/<id>/retry` and `/jobs/<id>/resume` routes provide the same controls | P0 | MVP |
| FR-29 | FFmpeg preflight diagnostic: before any render work, check `ffmpeg exists`, `ffprobe exists`, libx264 available, aac support, mp3 decode; fail clearly with diagnostic message if any missing | P0 | MVP |
| FR-30 | Generated card fallback: when no video clips or stock footage are available for a scene, generate 1080x1920 text-based PNG cards (headline, fact, context, CTA) using Pillow, styled from niche template; usage-only-cards condition escalates risk warning to Reviewer | P1 | MVP |
| FR-31 | Deterministic video validation (G10): before Reviewer multimodal spend, validate `video.mp4` exists, non-zero, 9:16 aspect ratio, 1080x1920, duration within configurable hard limit (default 60s), audio track present, h264/aac codec, metadata stripped | P0 | MVP |
| FR-32 | Treatment system: YAML-defined treatments in `templates/treatments.yaml` providing 9 visual treatments (ken_burns_zoom_in, ken_burns_pan_left, cinematic_crop, broll_standard, slow_motion, lower_third_slide, text_card_reveal, hook_big_caption, fade_to_black) + 5 transitions (crossfade, hard_cut, wipe_left, dissolve, circle_open) + FPS rules (30fps target) + pacing rules. Visual Director selects treatments per-scene; Composer applies via template-driven rendering engine. Adding new treatments requires YAML only, no code changes | P0 | MVP |
| FR-33 | Scene normalizer: unify mixed-asset framerates to 30fps target, normalize SAR to 1:1, apply Ken Burns zoompan for static images (2.5s zoom cycle), validate clip duration bounds (1-5s), enforce consistent encoding parameters (h264/aac) across all scenes before composition. Rejects flash-frame clips (<1s) and clips exceeding 5s | P0 | MVP |
| FR-34 | Audio sequencer: per-scene audio+video concat with two modes — Mode A (paired video+audio when no xfade) and Mode B (audio-only concat when xfade handles video). Pads missing audio with silence sources (anullsrc). Replaces broken amix that played all voice tracks simultaneously. Implemented in `clipper_agency/rendering/audio_sequencer.py` | P0 | MVP |
| FR-35 | Subtitle engine: converts script scene text into timed CaptionOverlay objects with absolute timestamps across scenes. Builds hook overlay (first 3s center-positioned caption) and validates TikTok output requirements (pix_fmt, faststart, libx264, aac, bitrate, shortest). Implemented in `clipper_agency/rendering/subtitle_engine.py` | P0 | MVP |
| FR-36 | Composer production output: xfade/concat mixed transition chain with offset calculation (cumulative_duration - trans_duration - safety_margin), duration clamping (min of transition_duration, min(prev_dur, next_dur) - headroom), fallback to crossfade for unknown transitions. Production flags: `-pix_fmt yuv420p`, `-movflags +faststart`, H.264/AAC codecs. Subtitle drawtext filters chained with `enable='between(t,start,end)'` and escape_drawtext for special characters | P0 | MVP |
| FR-37 | Segment Producer edit blueprint: outputs story_beats with per-beat visual instructions (visual_must_show, visual_must_not_show, asset_candidates, overlay_text, caption_keywords), format_decision (single_story_deep_dive / three_story_roundup / two_story_highlight), verified_facts with safe_wording, unverified_claims, and do_not_use list. Supersedes FR-37 (proposed content_direction) with richer beat contract | P0 | MVP |
| FR-38 | Scriptwriter continuous voiceover: writes single voiceover_text (75-110 words, no emojis, spoken-word style) from story_beats. Outputs narrative_structure mapping beats to word ranges with overlay_text and caption_keywords per beat. Total word budget replaces per-scene formula | P0 | MVP |
| FR-39 | Voice Producer single audio with timestamps: generates continuous voiceover via 1 TTS call (87.5% cost reduction). Returns voiceover.mp3 + word-level timestamps via ElevenLabs `/with-timestamps` (character-level grouped to words). Gemini TTS/Fish Audio fallback with silence-detection approximate timing | P0 | MVP |
| FR-40 | Shared schema contract via `config/schema.py`: 11 Pydantic models (StoryBeat, FormatDecision, VerifiedFact, UnverifiedClaim, VisualInstruction, AssetCandidate, KeywordCaption, VoiceSettings, VoiceProviderResult, ContentBrief, NarrativeSection) defining cross-agent data contracts | P0 | MVP |
| FR-41 | Beat-driven visual planning: Visual Director consumes story_beats + word timestamps + visual rules. Each beat has exact audio duration from timestamps. Sequential Voice→Visual execution enforced in engine | P0 | MVP |
| FR-42 | Audio-first composition: voiceover.mp3 is immutable timeline anchor (never trimmed). Composer smart-trims visuals at keyframe boundaries, overlays keyword captions (max 6 words, beat-aligned), speed-adjusts visuals ±20% to match audio | P0 | MVP |

### 2.2 User Interfaces

| ID | Requirement | Priority | Stage |
|----|-------------|----------|-------|
| FR-17 | Web dashboard for job management, agent configuration, niche profiles | P0 | MVP |
| FR-18 | CLI: `python3 cli.py run --topic "..." --niche indonesian_artists` | P0 | MVP |
| FR-19 | CLI `test-agent` subcommand: run individual agents independently for debugging/testing, bypassing orchestrator DB tracking | P1 | MVP |
| FR-20 | Configurable agent autonomy levels | P1 | MVP |
| FR-21 | Selectable video templates (manual or agent-auto) — implemented via `clipper_agency/rendering/` with YAML template definitions in `templates/*.yaml` and per-template adapters | P1 | MVP |

### 2.3 Configuration

| ID | Requirement | Priority | Stage |
|----|-------------|----------|-------|
| FR-22 | Configuration hierarchy: Agent defaults → Niche → Account → Job-level overrides | P0 | MVP |
| FR-23 | All agent settings configurable per level (LLM model, prompt version, temperature, max tokens, voice ID) | P0 | MVP |
| FR-24 | Per-agent LLM model configuration via environment variables (`SAFETY_MODEL`, `SEGMENT_PRODUCER_MODEL`, `SCRIPTWRITER_MODEL`, `REVIEWER_MODEL`, `VISUAL_DIRECTOR_MODEL`) with sensible defaults | P0 | MVP |
| FR-25 | Structured logging for all external API calls, agent executions, and pipeline state transitions with configurable log level (`LOG_LEVEL`) | P0 | MVP |
| FR-26 | Config versioning with diff and rollback | P0 | MVP |
| FR-27 | Niche profiles swappable without code changes | P0 | MVP |

---

## 3. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | Video generation time | < 15 minutes per video |
| NFR-02 | Pipeline success rate | > 90% |
| NFR-03 | Human review pass rate | > 80% |
| NFR-04 | LLM cost per video | < $0.01 (Budget East) |
| NFR-05 | CLI startup | < 2 seconds |
| NFR-06 | Dashboard page load | < 3 seconds |
| NFR-07 | All agent state transitions persisted with timestamps and observable through DB/dashboard/CLI | Required |
| NFR-08 | Jobs restartable in principle from persisted DB state plus `ASSETS_CACHE/job_{id}` agent/gate artifacts; write-enabled retry/resume implemented after artifact contract stabilization | Required |
| NFR-09 | Agent contracts identical at all scales (MVP → 1000+ accounts) | Required |
| NFR-10 | All external API calls log request parameters, response status, token usage, cost estimate, and latency | Required |

---

## 4. Integration Requirements

### 4.1 External Services (Required for MVP)

| Service | Purpose | Auth | Rate/Credits |
|---------|---------|------|--------------|
| OpenRouter | LLM access for all agents | API key | Per-model limits |
| ElevenLabs | Voice generation (primary) | API key | Free tier blocked — Starter plan ($5/mo) required for API access |
| Google AI Studio Gemini TTS | Voice generation fallback after ElevenLabs | API key (`GEMINI_API_KEY`) | Google AI Studio quota/limits; default voice `GEMINI_TTS_VOICE_NAME=Kore` |
| Fish Audio | Voice generation fallback after Gemini TTS | API key (`FISHAUDIO_API_KEY`) | No free tier — Plus plan ($11/mo) required for API access |
| Pexels API | Stock video/images fallback + photo search for text card images (`search_photos()`) | API key (free) | 200 requests/hr |
| yt-dlp | Video/audio download from 1000+ sites | None | Site-specific limits |
| ScrapeCreators | TikTok video URLs, creator data, song metadata | API key (`x-api-key`) | 75 free credits; `trim=true` + field extraction reduces 1-2MB raw responses to ~500 chars/result |
| Firecrawl | Web search + structured page scraping | API key | Daily free runs |

### 4.2 Provider Routing

```
Cache → ScrapeCreators (TikTok video/music) + Firecrawl (context/news)
→ If quota exhausted or no usable URL: ask user for source URL
→ If no source URL: Pexels/local asset/generated cards
Stage 2: + Serper. Stage 2+: + DuckDuckGo site-filtered.
```

**Voice provider fallback:** `ElevenLabs → Google AI Studio Gemini TTS → Fish Audio → fail clearly`.
- `ELEVENLABS_API_KEY` set → try `ElevenLabsService` first.
- If ElevenLabs is missing or fails, `GEMINI_API_KEY` set → try `GeminiTTSService` (`gemini-2.5-flash-preview-tts`, default voice `Kore`).
- If Gemini TTS is missing or fails, `FISHAUDIO_API_KEY` set → try `FishAudioService` (s2-pro model, `/v1/tts` endpoint).
- If all providers are missing or fail, pipeline stops with a clear error and sanitized attempts are persisted under the job workspace.

ScrapeCreators credits reserved for TikTok video URLs, creator profiles, engagement data, and song metadata. Results cached with TTL to minimize credit burn. Segment Producer preserves raw ScrapeCreators/Firecrawl payloads and normalized research artifacts under `ASSETS_CACHE/job_{id}/agents/segment_producer/`.

### 4.3 External Services (Future)

| Service | Purpose | Stage |
|---------|---------|-------|
| Cobalt/pybalt | Video download, different engine | Stage 2+ |
| instaloader | Instagram media | Stage 2+ |
| Douyin_TikTok_Download_API | TikTok/Douyin specialist | Stage 2+ |
| Serper API | Backup search | Stage 2 |
| DuckDuckGo site-filtered | Free fallback search | Stage 2+ |

---

## 5. Security Requirements

### 5.1 Secrets Management

- **No secrets stored in database** — only environment variable name references.
- Secrets via `.env` (local) or environment variables (production).
- `.env` loaded at CLI entry point via `python-dotenv` `load_dotenv()` in `__main__.py`; `pydantic-settings` `AppSettings` provides typed access for dashboard and CLI.
- Dashboard shows `configured ✅` or `missing ❌`, never exposes values.

### 5.2 Authentication & Authorization

| Requirement | MVP | Future |
|-------------|-----|--------|
| Dashboard auth | Basic auth + 2 groups (privileged, creative/ops) | OAuth2 / SSO |
| Role-based access | 2 groups | 4 roles (admin, creative lead, creative user, reviewer) |
| API auth | Not required (local only) | API keys |

### 5.3 Data Protection

- Client revenue, gross profit, margin **restricted** to privileged group.
- Creative users see operational budget only (estimated cost, remaining).
- Budget overrides and approvals logged in audit log.
- Soft deletes for data recovery.

---

## 6. Data Requirements

### 6.1 Database

| Requirement | MVP | Scale |
|-------------|-----|-------|
| Engine | SQLite | PostgreSQL |
| Schema | Same schema | Migrates with Alembic |
| Access | Local file | TCP connection |

### 6.2 Data Entities

| Entity | Description | Sensitive |
|--------|-------------|-----------|
| Jobs | Generation jobs with status, timestamps, config snapshot | No |
| Agent states | Per-agent inputs, outputs, state per job | No |
| Agent configs | Per-agent LLM, prompt, model, voice settings | Yes (API key refs) |
| Niche profiles | Language, tone, rules, video length | No |
| Accounts | TikTok accounts (1 for MVP) | Yes (credentials) |
| Outputs | Final package metadata, paths, scores | No |
| Creative history | Used angles, templates, assets per topic | No |
| Assets | Source metadata, license, hash, provider | No |
| Research cache | Cached research with Time To Live (TTL) (URLs, metadata, entities, tags, facts, risk flags, music) | No |
| Audit log | All actions | Yes (compliance) |
| Config versions | Patches with rollback snapshots | No |
| Prompt versions | Prompt version tracking with diffs | No |
| Templates | Video template definitions (layout, fonts, colors, animations) | No |
| Preflight estimates | Lightweight cost estimate before job | No |
| Job artifact workspace | Per-job intermediate artifacts, agent inputs/outputs, gate results, diagnostics, and manifest under `ASSETS_CACHE/job_{id}` | No |
| Job snapshots | Full reproducibility data | No |

### 6.3 Retention Policy

| Data Type | Duration |
|-----------|----------|
| Job metadata, config snapshots, output metadata | Indefinite |
| Agent inputs/outputs, gate results, manifests, diagnostics | 180 days |
| Raw provider payloads (ScrapeCreators, Firecrawl, TTS attempts metadata) | 90 days |
| Heavy intermediate assets in `ASSETS_CACHE/job_{id}` | 30 days |
| Failed render artifacts and FFmpeg diagnostics | 14 days |
| Final output packages | 365 days |

### 6.4 Audit Requirements

- All budget overrides, config patches, and role changes logged.
- Every approved prompt/config/template change versioned with diff.
- Rollback to any previous config version.

---

## 7. Compliance Requirements

| Area | Requirement |
|------|-------------|
| **Platform policy** | TikTok: target output governed by configurable `content_planning.hard_limit_sec`; 9:16 vertical; caption 150 chars; 5 hashtags max. 60s is MVP product policy, not universal TikTok ToS |
| **Copyright** | Third-party clips <5s, transformed, multi-source, original voiceover |
| **Content safety** | Safety Agent pre-checks before generation (cheapest model). Hard-block illegal/banned/high-risk defamation. Soft-warning for unverified claims. |
| **Unverified claims** | Soft wording required ("dikabarkan" — reported/said to be, "ramai dibahas netizen" — widely discussed by netizens) |
| **FFmpeg output** | Metadata stripping for platform-native appearance |

---

## 8. Deployment Requirements

| Requirement | MVP | Stage 2+ |
|-------------|-----|----------|
| Deployment | Local machine + manual | Docker Compose on VPS |
| Scaling | Single worker, sequential jobs | Parallel workers, DB-backed queue |
| Concurrency | SQLite Write-Ahead Logging (WAL) + advisory lock prevents concurrent CLI runs | DB-backed queue handles concurrency |
| Container | Dockerfile + docker-compose.yml | Same |
| CLI | `python3 cli.py run --topic "..."`; `python3 -m clipper_agency test-agent <AGENT> [OPTS]`; `--log-level` option | Same + `test-agent` for debugging |
| Dashboard | Flask/FastAPI + basic auth + 2 groups | Same + full role auth |
| Voice | ElevenLabs → Gemini TTS → Fish Audio fallback from env vars | Same |

### Scaling Path

```
MVP (1 account)              Scale (10-100)              Full (1000+)
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Single worker    │     │ Docker Compose   │     │ K8s / Multi-VPS  │
│ Sequential jobs  │ →   │ PostgreSQL       │ →   │ PG + Redis       │
│ SQLite           │     │ DB-backed queue  │     │ RQ/Celery workers│
│ CLI + Dashboard  │     │ 2-3 workers      │     │ Auto-scale       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

Agent contracts remain identical at all scales. Queue interface abstract. Workers stateless.
