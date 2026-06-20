# Clipper Agency — Technical Design Document

**Version:** 5.3
**Date:** 2026-06-11
**Status:** Phase 23 Complete — Reviewer Context + Diagnostics Enforcement Contract
**Related:** `docs/PRD.md`, `docs/SRS.md`, `docs/requirements_traceability.md`

---

## 1. System Architecture

### Design Decision: Fully Agentic (Approach B)

Seven MVP agents, each independently configurable and observable. Orchestrator coordinates via database-driven state. Creative Director deferred to Stage 2.

```
                      DASHBOARD (Web UI)
   Safety | Segment Producer | Scriptwriter | Voice | Visual | Composer | Reviewer
                      ┌───────────────────────┐
                      │     ORCHESTRATOR      │
                      │ Gated State Machine   │
                      └──────┬────────────────┘
                             ▼
                      DATABASE (SQLite → PG)
```

**Why Fully Agentic:** Each agent independently testable, configurable, observable. Scales naturally. Avoids rigid monolith and limited-visibility structured pipeline.

### Agent Communication

- **Database-driven state** — each agent reads/writes `JobState` in DB.
- Orchestrator checks DB to determine "can next agent run?"
- Every agent state visible in dashboard (idle, running, completed, failed).
- Jobs are restartable from persisted DB state plus `ASSETS_CACHE/job_{id}` artifacts.
- **Manual retry from failed step** — CLI `job-retry <id> --from <agent>` and dashboard POST `/jobs/<id>/retry` trigger `run_pipeline_from()` in the engine, which clears downstream agent states to `pending`, reuses valid cached artifacts, and restarts from the specified point. `job-resume <id>` (CLI) and `/jobs/<id>/resume` (dashboard) detect failed/paused state and auto-target the correct resume point.
- **Cache reuse** — `validate_agent_cache()` checks persisted artifacts against deterministic rules (exists, non-zero, valid JSON/format/timing) before skipping a paid provider call. Invalid cache falls through to re-running the agent.
- **Config snapshot** — job config is frozen at creation time and stored in `jobs.config_snapshot`; retries/resumes use the same snapshot even if global `.env` or niche config changed. Override flag available for explicit re-snapshot.
- No auto-retry loops in MVP.
- CLI and dashboard both create the same `jobs` record type.
- Running jobs cannot be edited or retried until paused, failed, or completed.

### Job Workspace and Final Package Boundaries

Each job has two separate roots:

```text
ASSETS_CACHE/job_{id}/   # intermediate agent/gate artifacts, diagnostics, manifest
OUTPUT_DIR/job_{id}/     # final customer-ready package only
```

`ASSETS_CACHE/job_{id}` contains agent `input.json`/`output.json`, gate result JSON, raw provider payloads, normalized research contracts, TTS provider attempts, FFmpeg diagnostics, clip provenance records, generated cards, and `manifest.json`. `OUTPUT_DIR/job_{id}` contains only `video.mp4`, `caption.txt`, `thumbnail.png`, and `metadata.json`.

---

## 2. Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Language** | Python 3.11+ | Best FFmpeg/video automation ecosystem, AI pipelines |
| **Video Engine** | FFmpeg (CPU-only) | No GPU required, battle-tested, programmable |
| **Database** | SQLite → PostgreSQL | Same schema, swap for scale |
| **Queue** | None/sequential (MVP) → DB-backed → Redis + RQ/Celery | Avoid overhead until multi-account |
| **LLM Access** | OpenRouter API | Large Language Model (LLM) access, multi-model, single key |
| **Secrets** | `python-dotenv` + `pydantic-settings` `AppSettings` | `.env` loaded at CLI entry (`__main__.py`); services use `os.getenv()`. No secrets in DB. |
| **Logging** | Python `logging` + `clipper_agency/core/logging.py` | `setup_logging()` + `get_logger()`. All agents, services, orchestrator, and LLM client log at DEBUG/INFO/ERROR. Configurable via `LOG_LEVEL` env var. |
| **Prompts** | Filesystem (`prompts/*.md`) | Git-tracked, versioned, Markdown format |
| **Container** | Docker Compose | VPS-ready |

### External Services (MVP Required)

| Service | Purpose |
|---------|---------|
| OpenRouter | LLM for all agents |
| ElevenLabs | Voice generation |
| Google AI Studio Gemini TTS | Voice generation fallback after ElevenLabs |
| Fish Audio | Voice generation fallback after Gemini TTS |
| Pexels API | Stock video/images fallback |
| yt-dlp | Source video/audio download |
| ScrapeCreators | TikTok video URL + song metadata |
| Firecrawl | Web search + structured scraping |

### Layered Media Providers

```
MVP:
    ├── Layer 1: yt-dlp (default, 1000+ sites) — PRIMARY
    └── Fallback: Pexels/user asset/generated cards

Stage 2+:
    ├── Layer 2: Cobalt/pybalt (different engine)
    ├── Layer 3a: instaloader (Instagram)
    ├── Layer 3b: Douyin_TikTok_Download_API (TikTok specialist)
    ├── Layer 3c: gallery-dl (image galleries)
    └── Fallback: Pexels (always available)
```

**MVP selection flow:** source URL → try yt-dlp → if missing/fails: approved local user asset, Pexels, or generated cards.

**Stage 2+ selection flow:** URL → extract platform → try specialist → try yt-dlp → try Cobalt → fallback to Pexels. All providers config-driven, all optional via toggle.

---

## 3. Gated Agent Pipeline

### 3.1 Pipeline Flow

```text
1.  Topic Input
2.  Gate G1: Input Preflight
3.  Gate G2: Lightweight Cost + Credit Estimate
4.  Agent A1: Safety Pre-Check (ultra-cheap model)
5.  Gate G3: Research Cache Check
6.  Agent A2: Segment Producer (ScrapeCreators + Firecrawl + story_beats + edit blueprint)
7.  Gate G4: Post-Research Risk Gate
8.  Gate G5: Source Quality Gate
9.  Gate G6: Creative Memory Gate
10. Agent A3: Scriptwriter (continuous voiceover from story beats, 75-110 words)
11. Gate G7: Script Validation Gate
12. Agent A4: Voice Producer (single TTS call + word-level timestamps)
13. Gate G8: Audio Validation Gate
14. Agent A5: Visual Director (beat-driven, audio-aware, visual_must_show rules)
    (Asset qualification boundary runs here — see §17: score → rank → recover → fallback before VD consumes candidates)
15. Gate G9: Asset Validation Gate
16. Agent A6: Composer (single audio timeline, smart trimming, keyword captions)
17. Gate G10: Deterministic Video Validation
18. Agent A7: Reviewer (AV sync + caption quality + fact safety + narrative structure)
19. Output Package
```

### 3.2 Gate Definitions

#### G1: Input Preflight

| Field | Value |
|-------|-------|
| **Purpose** | Validate topic input before any processing |
| **Input** | Topic string, optional source URL, niche config |
| **Check type** | Deterministic (no LLM) |
| **Pass** | Topic non-empty after trim, niche config loaded, source URL valid format if provided, configured language supported by assigned LLM models |
| **Soft fail** | Missing source URL — show warning, continue |
| **Hard fail** | Empty/whitespace-only topic, invalid niche, malformed URL, language-model incompatibility |
| **Cost protection** | Zero cost. Blocks all downstream spending on invalid input. |
| **Next** | User must fix input (CLI error message or dashboard validation error). Then G2. |

#### G2: Lightweight Cost + Credit Estimate

| Field | Value |
|-------|-------|
| **Purpose** | Show estimated cost and credit usage before generation |
| **Input** | Niche config, model presets, cached research availability |
| **Check type** | Deterministic calculation |
| **Pass** | Estimate within acceptable range, sufficient credits for all required providers |
| **Soft fail** | Estimate exceeds expected range — show warning to user, require acknowledgment |
| **Hard fail** | Insufficient credits for any required provider |
| **Cost protection** | Zero marginal cost. Prevents jobs that cannot complete. |
| **Next** | User must add credits or acknowledge warning. Then A1. |

#### G3: Research Cache Check

| Field | Value |
|-------|-------|
| **Purpose** | Avoid redundant paid research calls |
| **Input** | Topic, entities, niche, date |
| **Check type** | Deterministic DB lookup |
| **Pass** | Fresh cache (<60 min) exists → skip to G4 with cached data |
| **Soft fail** | Stale cache (60-240 min) → reuse with stale marking, log |
| **Hard fail** | No cache or expired (>240 min or new Asia/Jakarta day) → proceed to A2 |
| **Cost protection** | Saves ScrapeCreators credits + Firecrawl API calls |
| **Next** | G4 (if cached) or A2 (if not) |

#### G4: Post-Research Risk Gate

| Field | Value |
|-------|-------|
| **Purpose** | Catch risk discovered after research finds real entities, claims, URLs |
| **Input** | Researcher output: entities, risk_flags, source URLs, context_notes |
| **Check type** | Deterministic keyword/flag scan → GLM-4-9B (ultra-cheap) only if flags or new entities detected |
| **Pass** | No illegal/banned/high-defamation risk detected |
| **Soft fail** | Unverified rumor detected — require cautious wording in downstream agents |
| **Hard fail** | Clear defamation, illegal content, banned platform policy — stop job, no override |
| **Cost protection** | Blocks script, voice, visual, composer spending on unsafe content |
| **Next** | Admin/Creative Lead if hard fail or unclear. G5 if pass/soft-fail. |

#### G5: Source Quality Gate

| Field | Value |
|-------|-------|
| **Purpose** | Ensure enough usable source material exists before expensive generation |
| **Input** | Resolved video_sources list from researcher, researcher topic_brief and context_notes |
| **Check type** | Deterministic count + URL domain validation against yt-dlp supported sites |
| **Pass** | ≥2 usable source URLs on yt-dlp-supported domains, research has topic_brief and context |
| **Soft fail** | 1 usable URL — proceed with Pexels/generated cards, log risk warning. Or empty research context but URLs exist — proceed with URL-only mode. |
| **Hard fail** | 0 usable URLs and no Pexels fallback configured — ask user for source URL. Or completely empty research output (no URLs, no context) — stop job. |
| **Cost protection** | Prevents script/voice/render spend on jobs with no visual material or research grounding |
| **Next** | Admin/Creative Lead if hard fail. G6 if pass/soft-fail. |

#### G6: Creative Memory Gate

| Field | Value |
|-------|-------|
| **Purpose** | Prevent repetitive content without wasting generation tokens |
| **Input** | Topic cluster, account history, used angles/templates/assets |
| **Check type** | Deterministic DB lookup |
| **Pass** | Sufficient variation available — select next angle |
| **Soft fail** | Variation running low — log warning, continue with remaining angles |
| **Hard fail** | All angles exhausted — MVP: flag for human review; Stage 2: route to Creative Director |
| **Cost protection** | Prevents generation of duplicate content |
| **Next** | Human if hard fail. A3 if pass/soft-fail. |

#### G7: Script Validation Gate

| Field | Value |
|-------|-------|
| **Purpose** | Validate script budget compliance before spending ElevenLabs credits on voice |
| **Input** | Script scenes with word_count, estimated_duration_sec; content direction budget |
| **Check type** | Deterministic (word-count duration estimate, scene role validation, format adherence) |
| **Pass** | Script fits word/time budget, scene roles present, estimated total ≤ target |
| **Soft fail** | Exceeds target but within hard limit — log, continue with warning |
| **Hard fail** | Exceeds hard limit — stop early before TTS spend. Missing required scene roles. |
| **Cost protection** | Blocks ElevenLabs spend on scripts that cannot fit within duration limits |
| **Next** | Human if hard fail. A4 if pass/soft-fail. |

#### G8: Audio Validation Gate

| Field | Value |
|-------|-------|
| **Purpose** | Validate continuous voiceover file, duration, and word-level timestamps before downstream visual/render spend |
| **Input** | Voiceover file path (`voiceover.mp3`), `voiceover_duration_sec`, word-level timestamps, expected word count range (75-110) |
| **Check type** | Deterministic (file exists, file size > 0, duration metadata present, timestamps non-empty, total within hard limit) |
| **Pass** | Audio file valid, metadata present, timestamps extracted, duration within limit |
| **Soft fail** | Minor duration deviation or fewer timestamps than expected — log, continue |
| **Hard fail** | File missing, 0 bytes, no metadata, no timestamps, total exceeds hard limit |
| **Cost protection** | Prevents Visual Director and Composer spend when audio is broken or too long |
| **Next** | Visual Director if pass/soft-fail. Admin/Creative Lead if hard fail. |

#### G9: Asset Validation Gate

| Field | Value |
|-------|-------|
| **Purpose** | Validate downloaded assets before FFmpeg render |
| **Input** | Asset file paths, expected counts |
| **Check type** | Deterministic (file exists, file size > 0, format check, duration 1-5s for clips) |
| **Pass** | All assets valid, clips 1-5s, files non-zero |
| **Soft fail** | Some assets missing/clips <1s (rejected) but enough for composition — log warning |
| **Hard fail** | No valid assets — stop |
| **Cost protection** | Prevents FFmpeg render with no visual material |
| **Next** | Admin/Creative Lead if hard fail. A6 if pass/soft-fail. |

#### G10: Deterministic Video Validation

| Field | Value |
|-------|-------|
| **Purpose** | Validate rendered video before spending multimodal Reviewer tokens |
| **Input** | Output video file path |
| **Check type** | Deterministic (file exists, file size > 0, duration, resolution, codec, audio track present) |
| **Pass** | Video 9:16, 1080x1920, duration within configurable hard limit (default 60s), audio track present, file size > 1KB |
| **Soft fail** | Minor deviations — log, continue to reviewer |
| **Hard fail** | File missing, 0 bytes, wrong resolution, no audio, or duration out of configurable range |
| **Cost protection** | Prevents multimodal Reviewer spend on broken video files |
| **Next** | Admin/Creative Lead if hard fail. A7 if pass/soft-fail. |

### 3.3 State Machine

Each job has a state tracked in the database:

```text
CREATED → PREFLIGHT → COST_ESTIMATED → SAFETY_CHECKED → RESEARCHING
→ RESEARCH_REVIEWED → SOURCES_VALIDATED → MEMORY_CHECKED → SCRIPTING
→ SCRIPT_VALIDATED → VOICING → AUDIO_VALIDATED
→ VISUALIZING → ASSETS_VALIDATED → COMPOSING → VIDEO_VALIDATED → REVIEWING
→ COMPLETED

Any state → PAUSED (Admin/Creative Lead action via dashboard or CLI signal)
Any state → FAILED (with gate/agent that caused failure)
PAUSED → same state where paused (resume re-runs current step with same config snapshot)
FAILED → any earlier state (Admin/Creative Lead triggers retry from that point)
```

**PAUSED state rules:**
- Config snapshot frozen at job creation time; resume uses same snapshot even if global config changed.
- Cached research may be stale after pause — G3 re-checks cache freshness on resume.
- ScrapeCreators credits re-validated on resume (G2 re-checks credits).

**Phase 12 retry/resume boundary:** Phase 12 is read-only observability first. It persists agent inputs/outputs, gate results, job manifests, and debug views so failures can be diagnosed safely, but it does not expose write-enabled retry/resume commands yet. Phase 13 adds human-triggered mutation commands only after these prerequisites are reliable:

```text
python3 -m clipper_agency job-retry 125 --from composer
python3 -m clipper_agency job-resume 125
python3 -m clipper_agency job-retry 125 --from voice_producer --use-cache
```

Required before enabling those commands:

- `agent_states` accurately transitions `pending`/`running`/`completed`/`failed`.
- Gate results are persisted and enforce hard-fail stops.
- Job config snapshots are stored and reused.
- Agent input/output artifacts are persisted.
- Paid provider calls can be skipped when valid cached artifacts exist.
- Retry policy remains human-triggered only; no automatic retry loops.

---

## 4. Agent Roles

| Agent | Role | Cost Tier | Caching |
|-------|------|-----------|---------|
| **Safety Agent** | Pre-checks topic. Ultra-cheap model (GLM-4-9B). Hard-blocks illegal/banned/high-risk defamation; soft-warns unverified claims. | Ultra Budget | Not cached |
| **Segment Producer** | Formerly Researcher. Gathers context + source URLs via ScrapeCreators + Firecrawl. Outputs edit blueprint with story_beats (visual_must_show/must_not_show, asset_candidates, overlay_text, caption_keywords), format_decision, verified_facts, unverified_claims, and do_not_use list. 5 sub-roles: Fact Checker, Viral Analyst, Clip Scout, Story Producer, Edit Planner. See `docs/adr/0021-audio-first-continuous-voiceover.md`. | Budget East | TTL-based + job workspace file cache |
| **Scriptwriter** | Writes continuous voiceover narration (75-110 words, no emojis, spoken-word style) from Segment Producer's story_beats. Outputs voiceover_text + narrative_structure (beat_id, word_range, overlay_text, caption_keywords). Removes per-scene word limit formula. Rotates angle from creative history. | Budget East | Never |
| **Voice Producer** | Generates continuous voiceover via single TTS call (87.5% cost reduction vs per-scene). Primary: ElevenLabs `/with-timestamps` (character-level alignment grouped into words). Fallback: Gemini TTS (silence detection) → Fish Audio → fail clearly. Returns voiceover.mp3 + word-level timestamps + duration. Voice files and metadata saved under `ASSETS_CACHE/job_{id}/agents/voice_producer/`. | API cost | Never |
| **Visual Director** | Beat-driven, audio-aware visual planning: consumes story_beats + word timestamps + visual rules (must_show/must_not_show) + do_not_use list. Each beat has exact audio duration from timestamps. Visual hierarchy: source clip → screenshot → portrait with Ken Burns → text card → stock (abstract only). Sequential execution: Voice Producer must complete first. Receives a **pre-qualified candidate pool**: rejected candidates never reach VD (see §17). | Budget East | Never |
| **Composer** | Single audio timeline: voiceover.mp3 is immutable anchor (never trimmed). Smart scene trimming at ffprobe keyframe boundaries (±15% tolerance). Speed adjustment ±20% (imperceptible). Keyword captions (max 6 words, beat-aligned, bottom-positioned) replace full-sentence subtitles. Treatment-aware rendering from `templates/treatments.yaml`. Scene normalizer unifies framerates to 30fps. Production flags: `-pix_fmt yuv420p`, `-movflags +faststart`. | N/A | Never |
| **Reviewer** | 4 programmatic quality checks: (1) AV sync (drift < 0.5s), (2) caption quality (short keywords, max 6 words), (3) fact safety (safe wording for unverified claims), (4) narrative structure (beat completeness). Plus multimodal quality + safety + duplicate check. Max 2 human-triggered retries. | Moderate | Never |
| **Creative Director** | Stage 2. Proposes new angles/templates when variation exhausted. | Agentic East | Triggered |

### Visual Director Beat-Driven Planning (Phase 16–18 + v2.0.0)

The Visual Director uses LLM-driven planning with video production expertise to intelligently select visual assets and treatments per scene, replacing the original blind sequential URL assignment.

**Flow:**

1. **`_compact_research_data()`** — reads `research_contract.json` + `research_brief.md`, strips noise (raw HTML, boilerplate), sorts sources by engagement relevance, returns compact text block (~2K chars) for LLM context.
2. **`_plan_with_llm()`** — sends compact research + script scenes + niche config + available treatments (from `templates/treatments.yaml`) to LLM with structured output schema. LLM returns per-scene plan with `action.type` (enum: `tiktok_clip`, `pexels_video`, `pexels_image`, `text_card`), `treatment` (selected from 9 treatment types), `transition` (selected from 5 transition types), `reasoning` (free text), and action-specific parameters. LLM applies video production expertise: FPS rules (30fps target), pacing (scene duration matches narration), treatment selection based on content type (e.g., hook for intro, Ken Burns for static images, B-roll for narration). Returns `None` on failure.
3. **`_execute_plan()`** + **`_execute_action()`** — dispatch table routes each action to handler (`_exec_tiktok_clip`, `_exec_pexels_video`, `_exec_pexels_image`, `_exec_text_card`). Each handler downloads/generates the visual asset.
4. **3-tier image fallback** (for `text_card` actions): `_fetch_image()` tries Pexels photo search (`search_photos()`) → Firecrawl article og:image → gradient card background.
5. **Legacy fallback**: `_run_legacy_planning()` uses the original sequential URL assignment + Pexels fallback when LLM planning fails or returns `None`.

**Default treatment routing:** When LLM is unavailable or returns no treatment, Visual Director applies sensible defaults: `text_card_reveal` for text_card scenes, `broll_standard` for video clips, `ken_burns_zoom_in` for static images.

**Pre-VD asset qualification (Phase 26, PR 5):** Before Visual Director runs, the orchestrator qualifies each beat's `asset_candidates` via `clipper_agency/core/asset_qualification.py` and immutably rewrites the candidate pool VD receives. Ordering inside `_qualify_beat`: **SCORE → RANK → RECOVER → FALLBACK**. Rejected candidates never reach VD's live per-beat surface; a `qualification_report.json` artifact is written. See §17.

**Design principle:** "Orchestrator owns cross-agent contracts, agents own creative decisions." The Orchestrator validates content direction, derives word/time budgets, and reconciles the canonical timeline. Agents receive explicit contracts rather than inferring timing independently. See `docs/adr/0020-use-canonical-timeline-contract.md`.

**Configuration:** `visual_director_model` in `AppSettings` controls which LLM is used. Default: `mimo-v2-flash`.

### Researcher Structured Output

#### Research Query Construction

Before calling providers, the Researcher builds queries from:
1. **Topic** + detected entities (artist names, event names from topic string).
2. **Niche infotainment terms** (configurable list per niche, e.g., `viral`, `ramai dibahas`, `klarifikasi`, `hubungan`, `rilis lagu`).
3. **Language** from niche config (e.g., `id` → queries in Bahasa Indonesia).
4. **ScrapeCreators queries:** Artist name + TikTok-specific terms → TikTok video URLs, song metadata, creator profiles.
5. **Firecrawl queries:** Topic + news terms → recent Indonesian entertainment/news articles with title, author, published date, key facts.

Query construction is config-driven: the niche profile defines search terms, language, and preferred source domains. No hardcoded queries.

#### Agent Input/Output Contracts

| Agent | Input | Output | On Failure |
|-------|-------|--------|------------|
| **Safety** | Topic string, niche safety_rules; persisted as `agents/safety/input.json` | Pass/soft-warning/hard-fail + reason; persisted as `agents/safety/output.json` + `summary.md` | Hard-fail stops pipeline |
| **Segment Producer** | Topic, niche config, cached research (if fresh); persisted as `agents/segment_producer/input.json` | Edit blueprint: story_beats, format_decision, verified_facts, unverified_claims, do_not_use list, `output.json` | Empty result → G5 handles |
| **Scriptwriter** | Segment Producer story_beats + verified_facts; persisted as `agents/scriptwriter/input.json` | `voiceover_text` (75-110 words), `narrative_structure` (beat_id, word_range, overlay_text), `caption`, `hashtags`, and `output.json` | N/A (always produces output) |
| **Voice Producer** | voiceover_text + voice_id; persisted as `agents/voice_producer/input.json` | `voiceover.mp3` (single file), `voiceover_duration_sec`, `timestamps` (word-level), `provider`, `output.json` | All providers fail → stop, retry by Admin/Creative Lead |
| **Visual Director** | story_beats + timestamps + do_not_use + asset_candidates; persisted as `agents/visual_director/input.json` | `visual_plan.json` (LLM decisions), `scene_plan.json`, `provenance.json`, scene/card files, and `output.json` | Download failures → G9 handles |
| **Composer** | voiceover_path + timestamps + visual assets + narrative_structure; persisted as `agents/composer/input.json` | Final `OUTPUT_DIR/job_{id}/video.mp4`, plus `ffmpeg_command.txt`, diagnostics, and `output.json` | FFmpeg failure → stop, retry by Admin/Creative Lead |
| **Reviewer** | Rendered video file, script text, caption, voiceover_duration, visual_duration, narrative_structure, unverified_claims, `story_beats`, `word_timestamps`, `rendered_scene_manifest`, Composer diagnostics; persisted as `agents/reviewer/input.json` | Pass/reject + specific issues (AV sync, caption quality, fact safety, narrative structure) + deterministic gate results (visual coverage, text collision, safe area, package consistency, timestamp semantic, semantic visual relevance); persisted as `agents/reviewer/output.json` | Reject → Admin/Creative Lead decides or repair loop routes targeted fix |

### Segment Producer Output Schema

```yaml
segment_producer_output:
  topic_brief: "Short verified summary"

  angle:
    main_angle: "Why this story matters now"
    viewer_hook: "What makes people stop scrolling"
    emotional_driver: "shock | curiosity | sympathy | conflict | surprise | scandal | comeback"
    risk_level: "low | medium | high"

  format_decision:
    format: "single_story_deep_dive | three_story_roundup | two_story_highlight"
    story_count: 1
    rationale: "Why this format was chosen"
    video_asset_ratio: 0.33

  verified_facts:
    - fact: "..."
      source_url: "https://..."
      confidence: "verified | likely | unconfirmed"
      safe_wording: "Safe version for narration"

  unverified_claims:
    - claim: "..."
      label: "rumor"
      safe_wording: "Safe wording with hedging"

  story_beats:
    - beat_id: 1
      role: "hook | main_claim | evidence | reaction | closing_cta"
      narration_goal: "What this beat should achieve"
      spoken_point: "Key point to convey"
      safe_wording: "Safe version"
      visual_must_show: "Required visual content"
      visual_must_not_show: "Forbidden visual content"
      overlay_text: "RAMAI DIBAHAS"
      caption_keywords: ["KEYWORD1", "KEYWORD2"]
      asset_candidates:
        - type: "tiktok_clip | pexels_video | pexels_image | text_card"
          url: "https://..."
          reason: "Why this asset"
      fallback:
        type: "text_card"
        headline: "HEADLINE"
      evidence_source: "https://..."
      risk_note: "Safety guidance"

  do_not_use:
    - "generic Pexels city footage for named-person stories"

  video_sources:
    - url: "https://..."
      desc: "Description"
      type: "tiktok_clip"

  context_sources:
    - title: "Article title"
      description: "Summary"
```

#### Persisted Research Artifacts

The Researcher writes a human-readable brief and a machine-readable contract:

```text
ASSETS_CACHE/job_{id}/agents/segment_producer/research_brief.md
ASSETS_CACHE/job_{id}/agents/segment_producer/research_contract.json
ASSETS_CACHE/job_{id}/agents/segment_producer/raw/scrapecreators_response.json
ASSETS_CACHE/job_{id}/agents/segment_producer/raw/firecrawl_response.json
ASSETS_CACHE/job_{id}/agents/segment_producer/normalized/video_sources.json
ASSETS_CACHE/job_{id}/agents/segment_producer/normalized/context_sources.json
ASSETS_CACHE/job_{id}/agents/segment_producer/normalized/entities.json
```

`research_contract.json` is the downstream machine contract consumed by gates, Scriptwriter, and Visual Director.

---

## 5. Researcher Cache Policy

| Freshness | Age | Behavior |
|-----------|-----|----------|
| Fresh | 0-60 min | Use directly |
| Stale | 60-240 min | Reuse with stale marking, log |
| Expired | >240 min or new Asia/Jakarta day | Force new research |

**Cache key:** `niche:platform:language:topic_cluster:entities:date`

Entities (named: specific people, places, events) are included in cache key to prevent returning research about Artist A when user asks about Artist B.

---

## 6. Background Music Policy

| Priority | Option |
|----------|--------|
| 1 (default) | No background music |
| 2 (if configured) | Safe stock music |
| 3 (reviewer note) | Recommend platform-native sound during manual TikTok upload |

MVP does not automatically extract or embed copyrighted TikTok audio. ScrapeCreators provides song metadata for reference only.

---

## 7. Asset Safeguards

| Rule | Value |
|------|-------|
| Max clip duration | 5 seconds |
| Min clip duration | 1 second (clips <1s are flash frames, rejected by G9) |
| Min unique sources target | 2. If <2 usable: proceed with 1 + Pexels/generated cards, log risk warning |
| Original voiceover | Required |
| Transformation required | Re-encode → micro-crop → brightness shift → hue shift → pitch shift → metadata strip → per-account parameter variation |
| Attribution | When source is known |
| Risk logging | Always |

### Asset Caching

The primary per-job cache is the job workspace:
- Workspace directory: `ASSETS_CACHE/job_{id}`.
- Agent/gate artifacts and diagnostics live in that workspace for audit, debug observability, and future retry/resume.
- Final deliverables are copied/packaged separately under `OUTPUT_DIR/job_{id}`.

Downloaded clips (yt-dlp) and stock footage (Pexels) may also use an optional source URL hash cache to avoid redundant downloads:
- Global cache pattern: `ASSETS_CACHE/downloads/{url_hash}.{ext}`.
- Cache checked before any download attempt (saves Pexels API calls and yt-dlp I/O).
- Reused media is still copied or referenced through the per-job workspace and recorded in provenance.
- Cache invalidated by source URL change or manual cleanup per retention policy (SRS §6.3).

### FFmpeg Preflight Diagnostic

A deterministic preflight check runs before any render work (in the Orchestrator before Composer execution):

| Check | Command | Purpose |
|-------|---------|---------|
| FFmpeg exists | `ffmpeg -version` | Basic availability |
| FFprobe exists | `ffprobe -version` | Media probing required for G9/G10 |
| libx264 available | `ffmpeg -encoders \| grep libx264` | H.264 encoding for final output |
| aac support | `ffmpeg -encoders \| grep aac` | Audio encoding for final output |
| mp3 decode | `ffmpeg -decoders \| grep mp3` | Decode voiceover files if provider-sourced as mp3 |

If any check fails, the pipeline stops with a clear diagnostic message before spending time on expensive render operations. Results are logged and persisted in the job workspace.

### Scene Normalization (Phase 18)

Every visual scene is normalized before concatenation to ensure deterministic output quality and consistent playback:

| Property | Requirement |
|----------|-------------|
| Resolution | 1080x1920 (9:16 vertical) |
| Framerate | 30fps target (unified from mixed sources — PAL 25fps, NTSC 24/29.97fps, variable-rate downloads) |
| SAR | 1:1 (normalized — prevents FFmpeg concat demuxer aspect ratio mismatches) |
| Codec | H.264 (libx264) |
| Pixel format | yuv420p |
| Clip duration | 1-5 seconds (clips <1s rejected as flash frames; >5s trimmed) |
| Static images | Ken Burns zoompan applied (2.5s zoom cycle, `zoompan=z+'min(zoom+0.0015,1.5)':d={frames}:s=1080x1920:fps=30`) to create motion from stills |
| Audio from source clips | Stripped unless the clip is intentionally retained safe stock media |
| Metadata | Stripped (neutral platform-native appearance) |
| Transformation applied | Re-encode → micro-crop if aspect ratio differs → framerate unification → brightness/hue shift → metadata strip |

Normalization is performed by the Composer via FFmpeg filter chains before the concat demuxer. Each clip's transformation is recorded in `provenance.json` for audit. The scene normalizer module (`clipper_agency/rendering/normalizer.py`) handles framerate detection, SAR normalization, and zoompan generation for static assets.

### Generated Cards

When no source clips or stock footage are available, the Visual Director generates text-based card images:
- **Rendered by:** Pillow (Python imaging library) — chosen for offline deterministic rendering without FFmpeg drawtext complexity for text-on-background cards. Cards are later converted to video segments via FFmpeg if integrated into the scene sequence.
- **Format:** Static PNG at 1080x1920.
- **Content:** Headline text from script + colored background from niche template + optional avatar.
- **Style:** Fonts, colors, layout from niche config template definition.
- **Usage:** Integrated into scene sequence by Composer as full-screen slides between other clips.
- **Quality signal:** Jobs using only generated cards (no real clips or stock footage) get escalated risk warning; Reviewer notified.

### Template-Driven Rendering (Phase 15a)

The Composer supports template-driven rendering via a hybrid YAML + FFmpeg + Pillow system in `clipper_agency/rendering/`. This system was chosen because it is offline-testable, uses only existing stack dependencies, and produces deterministic output for tests.

**Architecture:**

```text
clipper_agency/rendering/
├── templates.py          # YAML loading and strict validation
├── contracts.py          # Typed dataclasses: RenderPlan, RenderScene, CaptionBlock, etc.
├── primitives.py         # Reusable FFmpeg filter chains (captions, overlays, lower-thirds, fades)
├── thumbnails.py         # Pillow-generated template-aware cards and thumbnails
├── engine.py             # Standalone FFmpeg render orchestrator
└── renderers/
    ├── news_card.py      # Headline + key facts + caption overlays
    ├── b_roll_narration.py  # Voiceover-led pacing + dynamic captions + lower-thirds
    └── rapid_update.py   # Short clip sequences + punchy captions + quick transitions
```

**Flow:**

1. `templates.py` loads the selected YAML template (`templates/*.yaml`) and validates layout, fonts, colors, caption style, scene durations, transitions, and thumbnail config.
2. The appropriate per-template adapter converts script/research inputs into a `RenderPlan` (typed via `contracts.py`).
3. Shared `primitives.py` generates FFmpeg filter chains for captions, overlays, lower-thirds, and transitions (fade/crossfade).
4. `thumbnails.py` produces Pillow-rendered cards at 1080×1920 when no source media is available.
5. `engine.py` orchestrates the final FFmpeg render from the `RenderPlan`, producing the output video.

**Composer integration:** `ComposerAgent._render_via_template()` is called as an early return in `clipper_agency/agents/composer.py`. When a template is configured in the scene plan, Composer delegates all rendering to the template engine. When no template is set, the legacy Composer FFmpeg assembly path is preserved unchanged.

**Diagnostics:** Template rendering diagnostics (template config, render plan, FFmpeg filtergraph, command log, stderr) are persisted under `ASSETS_CACHE/job_{id}/agents/composer/` for debug-first observability.

### Treatment System (Phase 17)

The treatment system provides a data-driven way to define visual effects and transitions without code changes. Treatments are defined in `templates/treatments.yaml` and applied by the Composer's rendering engine based on Visual Director's per-scene treatment selections.

**Available Treatments (9):**

| Treatment | Effect | Use Case |
|-----------|--------|----------|
| `ken_burns_zoom_in` | Slow zoom into center (zoompan filter) | Static images, establishing shots |
| `ken_burns_pan_left` | Slow left pan (zoompan filter) | Wide shots, landscape images |
| `cinematic_crop` | 2.39:1 crop with letterbox bars | Dramatic moments, premium feel |
| `broll_standard` | No special effect, clean playback | Standard B-roll footage |
| `slow_motion` | 0.5x speed with frame interpolation | Emotional highlights, impact moments |
| `lower_third_slide` | Animated lower-third overlay | Name/title/context overlays |
| `text_card_reveal` | Fade-in text card with background | Facts, headlines, transitions |
| `hook_big_caption` | Large animated caption overlay | Video hooks, attention grabbers |
| `fade_to_black` | Fade to/from black | Scene transitions, dramatic pauses |

**Available Transitions (5):**

| Transition | Duration | Effect |
|------------|----------|--------|
| `crossfade` | 0.5s | Smooth blend between scenes |
| `hard_cut` | 0s | Instant cut (default for fast pacing) |
| `wipe_left` | 0.3s | Left-to-right wipe effect |
| `dissolve` | 0.8s | Slow dissolve between scenes |
| `circle_open` | 0.5s | Circular reveal transition |

**FPS & Pacing Rules:**

```yaml
fps_rules:
  target_fps: 30
  acceptable_range: [24, 60]
  force_constant_fps: true

pacing_rules:
  min_scene_duration: 2.0
  max_scene_duration: 8.0
  preferred_scene_duration: 3.5
  hook_max_duration: 3.0
  cta_max_duration: 4.0
```

**Extensibility:** Adding a new treatment requires only a YAML entry in `treatments.yaml` plus a corresponding FFmpeg filter chain builder in `primitives.py`. No changes to Visual Director, Composer, or Orchestrator code needed.

### Audio Sequencing & Subtitle Overlays (Phase 19)

The Composer uses dedicated rendering modules for per-scene audio pairing and subtitle generation:

**Audio Sequencer** (`rendering/audio_sequencer.py`):
- Pure function `build_audio_video_concat()` produces FFmpeg concat filter strings.
- Mode A (`has_xfade=False`): interleaves video labels with audio references — `[t0][3:a][t1][4:a]concat=n=2:v=1:a=1[outv][outa]`.
- Mode B (`has_xfade=True`): audio-only concat — `[3:a][4:a]concat=n=2:v=0:a=1[outa]` — video handled by xfade chain.
- Edge cases: no audio → `anullsrc`; fewer audio → silence padding; more audio → truncation.
- Replaces broken `amix=inputs=N` that played all voice tracks simultaneously.

**Subtitle Engine** (`rendering/subtitle_engine.py`):
- `build_subtitle_overlays()`: converts scene dicts (text, duration) into timed `CaptionOverlay` objects with absolute timestamps (scene_start accumulates across scenes). Words split into chunks of `words_per_caption` (default 6).
- `build_hook_overlay()`: creates center-positioned hook caption for first N seconds (default 3.0s), clamped to scene duration.
- `validate_tiktok_output()`: checks 6 FFmpeg output flags (pix_fmt, faststart, libx264, aac, bitrate, shortest) and returns pass/fail dict.

**Treatment Filter Builder** (`rendering/treatment_filters.py`):
- `TreatmentFilterBuilder(config)` with `build(asset, start_time=0.0) -> str` method.
- Variable substitution: `{frames}` = duration × fps, `{text}` = headline, `{duration}`, `{start_time}`.
- Input-type rules: image+zoompan → prepend `scale=5400:-1,`; after scale/crop → append `,setsar=1/1`; null/unknown → `"null"`.

**Treatment Config** (`rendering/treatment_config.py`):
- Frozen dataclasses: `TreatmentDef` and `TransitionDef` for immutable access.
- `TreatmentConfig(path)` loads YAML, exposes `get_treatment()`, `get_transition()`, `target_fps`, `pacing` properties.
- Returns copies from dict properties for immutability.

**xfade Transition Chain:**
- `_build_transition_chain()` pure function builds mixed xfade/concat filter.
- Offset: `cumulative_duration - trans_duration - 0.1` (safety margin).
- Duration clamped: `min(trans_duration, min(prev_dur, next_dur) - 0.15)` (prevents FFmpeg errors on short clips).
- Unknown transitions → fallback to crossfade.
- Single scene → no transitions, direct output label.

**Subtitle Integration:**
- Orchestrator threads `script_scenes` to Composer via `_stage_composition()`.
- Composer chains drawtext filters: `[outv] → [vsub_in] → drawtext=...:enable='between(t,start,end)' → [outv]`.
- Special characters escaped via `escape_drawtext()` from `primitives.py`.

### Audio-First Continuous Voiceover Architecture (v2.0.0)

The following replaces the proposed Tier 4 Content Planning & Timeline Reconciliation with the implemented audio-first architecture. See `docs/adr/0021-audio-first-continuous-voiceover.md` for full rationale.

#### Key Principles

- **Audio-first**: voiceover generated first (single TTS call), visuals fitted to audio timeline
- **Beat-driven**: story_beats flow through pipeline as primary data contract
- **Sequential voice→visual**: Voice Producer must complete before Visual Director starts
- **Continuous voiceover**: single `voiceover.mp3` (never trimmed), word-level timestamps from ElevenLabs `/with-timestamps`
- **Smart trimming**: ffprobe keyframe boundary detection (±15% tolerance), speed ±20%
- **Keyword captions**: max 6 words, beat-aligned, bottom-positioned

#### Shared Schema Contract

`config/schema.py` contains 11 Pydantic models defining cross-agent data contracts: `StoryBeat`, `FormatDecision`, `VerifiedFact`, `UnverifiedClaim`, `VisualInstruction`, `AssetCandidate`, `KeywordCaption`, `VoiceSettings`, `VoiceProviderResult`, `ContentBrief`, `NarrativeSection`.

#### Data Flow

```python
# Segment Producer → edit blueprint
segment_output = run_segment_producer(topic, ...)
# Contains: story_beats, format_decision, asset_candidates, do_not_use

# Scriptwriter → continuous voiceover
script_output = run_scriptwriter(story_beats, verified_facts, ...)
# Contains: voiceover_text, narrative_structure, caption_keywords

# Voice Producer → single audio + timestamps
voice_output = run_voice_producer(voiceover_text)
# Contains: voiceover.mp3, timestamps, duration

# Visual Director → beat-driven visuals
visual_output = run_visual_director(story_beats, timestamps, do_not_use, ...)
# Contains: visual assets mapped to audio timeline

# Composer → single audio timeline with smart trimming
composer_output = run_composer(voiceover_path, timestamps, assets, narrative_structure, ...)
# Contains: video.mp4

# Reviewer → quality validation
review_output = run_reviewer(story_beats, video_path, voiceover_duration, ...)
# Contains: pass/fail with 4 quality checks
```

#### Artifact Additions

```text
config/schema.py (11 Pydantic models)
agents/segment_producer/ (renamed from researcher)
prompts/segment_producer.md (renamed, rewritten)
prompts/scriptwriter.md (rewritten for voiceover)
```

---

## 8. Variation Strategy & Creative Memory

### Pre-Generation Memory Check

Each creative agent checks `creative_history` **before** generating — prevents repetition without wasting generation tokens.

### Variation Rotation

Script angle, template, and asset mix rotate per topic cluster.

Example angles: `breaking_update` → `fan_reaction` → `timeline_recap` → `what_this_means` → `controversy_context`.

### Creative History Record

Per topic cluster: stores used angles, hooks, templates, assets, CTAs.
Checks: same topic cluster + same generation batch (strict), same account recent history (light signal, not block).

---

## 9. Configuration Hierarchy

```
Agent Defaults (global base config)
    → Niche Profile Overrides (e.g., indonesian_artists)
        → Account Overrides (per-client customizations)
            → Job-Level Overrides (one-off changes)
```

Every level overrides the previous. Config patches versioned with rollback support.

| Setting | Researcher | Scriptwriter | Voice | Visual | Composer | Reviewer | Safety |
|---------|-----------|-------------|-------|--------|----------|---------|--------|
| LLM Model | ✅ | ✅ | N/A | ✅ | N/A | ✅ | ✅ |
| API Key | ✅ | ✅ | ✅ | ✅ | N/A | ✅ | ✅ |
| Prompt Version | ✅ | ✅ | N/A | ✅ | ✅ | ✅ | ✅ |
| Temperature | ✅ | ✅ | N/A | ✅ | N/A | ✅ | ✅ |
| Max Tokens | ✅ | ✅ | N/A | ✅ | N/A | ✅ | ✅ |
| Voice ID | N/A | N/A | ✅ | N/A | N/A | N/A | N/A |

### Niche Profile Example

```yaml
niche:
  name: indonesian_artists
  language: id
  tone: casual_tiktok
  video_length:
    target: 30s
    hard_limit: 60s
  voice:
    provider: elevenlabs
    default_voice_id: "configured_indonesian_casual_voice"
  thumbnail:
    template: headline_frame
    resolution: 1080x1920
  content_angle: trending_artist_update
  safety_rules:
    - no_defamation
    - mark_rumors_as_unconfirmed
    - soft_wording_for_unverified
  caption_style: short_with_hashtags
```

### Environment Configuration Layer

Below the agent-default level, the system loads base configuration from `.env` via `python-dotenv`:

- **`AppSettings`** (`pydantic-settings` `BaseSettings`) — typed config class at `clipper_agency/config/schema.py` mapping env vars 1:1 (uppercased) to fields.
- **`load_dotenv()`** — called once at `clipper_agency/__main__.py` import time, before any service reads `os.getenv()`.
- **Fields:** `db_path`, `assets_cache`, `output_dir`, `dashboard_secret_key`, `dashboard_username`, `dashboard_password`, `llm_api_key`, `elevenlabs_api_key`, `gemini_api_key`, `gemini_tts_voice_name`, `fish_audio_api_key` (alias `FISHAUDIO_API_KEY`), `fish_audio_voice_id`, `elevenlabs_voice_id`, `pexels_api_key`, `scrapecreators_api_key`, `firecrawl_api_key`, `log_level`, `safety_model` (default `mimo-v2-flash`), `segment_producer_model` (default `mimo-v2-flash`), `scriptwriter_model` (default `mimo-v2-flash`), `reviewer_model` (default `mimo-v2-flash`), `visual_director_model` (default `mimo-v2-flash`).
- **Usage:** CLI (`__main__.py`) and dashboard (`app.py`) call `load_settings()` to resolve paths and secrets. Services read keys directly via `os.getenv()`. Agents read their model from `load_settings().<agent>_model` instead of hardcoding.
- **Test isolation:** Tests must use both `AppSettings(_env_file=None)` and `patch.dict(os.environ, {}, clear=True)` to prevent the user's `.env` (loaded by `load_dotenv()` at import) from leaking into test expectations.
- **Cache path helpers:** `clipper_agency/core/paths.py` provides `job_cache_dir()`, `agent_dir()`, `agent_input_file()`, `agent_output_file()`, `gate_result_file()`, `segment_producer_brief_file()`, `segment_producer_contract_file()`, `voice_scene_file()`, `visual_scene_file()`, and `job_final_output_dir()` for consistent per-job cache/final paths.

#### Voice Provider Fallback

The `VoiceProducerAgent` attempts providers in order and records sanitized attempts:

| Priority | Env Var | Service | Model |
|----------|---------|---------|-------|
| 1 (highest) | `ELEVENLABS_API_KEY` | `ElevenLabsService` | Configured voice ID |
| 2 | `GEMINI_API_KEY` | `GeminiTTSService` | `gemini-2.5-flash-preview-tts`, default voice `Kore` |
| 3 | `FISHAUDIO_API_KEY` | `FishAudioService` | `s2-pro` via `POST /v1/tts` |

- **Fallback voice IDs** per provider: `elevenlabs_voice_id`, `gemini_tts_voice_name`, or `fish_audio_voice_id`.
- If a provider key is missing or a provider returns an API/HTTP error, the agent tries the next provider.
- If no provider succeeds, the pipeline stops with a clear error and `provider_attempts.json` records provider name, status, sanitized message, latency, HTTP code, and output path if successful.

---

### Agent Autonomy Levels

Each agent has a configurable autonomy level that controls how the orchestrator handles gate transitions. Configured per-agent via the hierarchy in §9 (agent defaults → niche → account → job).

| Level | Behavior | Use Case |
|-------|----------|----------|
| **Autonomous** (default) | Agent runs through gates without human intervention. Gates apply pass/soft-fail/hard-fail rules automatically. | Normal production runs (all 7 MVP agents) |
| **Semi-Autonomous** | Agent runs but orchestrator pauses for human approval at each gate transition. Dashboard shows gate result and awaits explicit continue/abort. | High-cost agents (Reviewer with premium models), high-risk topics, debugging |
| **Manual** | Agent requires explicit human trigger to start each step. No automatic gate transitions. | Training, testing new prompts, validating new niches |

**Orchestrator behavior by level:**

- **Autonomous:** Gate evaluates → action taken automatically (pass → next step, soft-fail → continue with warning, hard-fail → stop + notify).
- **Semi-Autonomous:** Gate evaluates → dashboard notification + await human response. Human can approve pass/soft-fail, escalate hard-fail, or abort.
- **Manual:** No gate evaluation until human triggers step. Human sees input and output at each stage.

**Override rules:** Autonomy level can be elevated (more human involvement) at runtime via dashboard or CLI. Cannot be lowered below configured minimum without Admin/Creative Lead approval. All autonomy changes logged in audit trail.

**SRS traceability:** Implements FR-17 (Configurable agent autonomy levels, P1 MVP).

---

## 10. Video Templates

| Template | Style | Best For |
|----------|-------|----------|
| **News Card** | Headline + image + facts + captions | Quick updates |
| **B-Roll Narration** | Voiceover + clips + dynamic captions | Context-rich stories |
| **Rapid Update** | Fast cuts + punchy captions | Trending gossip |

FFmpeg-based. Layout in config (positions, fonts, colors, animations). 1080x1920 vertical. Template mode: `manual | agent_select | hybrid`. Visual treatments and transitions defined in `templates/treatments.yaml` (see §7 Treatment System).

---

## 11. Database Schema (MVP)

| Table | Purpose |
|-------|---------|
| `niches` | Niche configurations |
| `accounts` | TikTok accounts (multi-tenant ready) |
| `jobs` | Video generation jobs |
| `agent_states` | Per-agent state per job |
| `agent_configs` | Per-agent LLM, prompt, model config |
| `templates` | Video template definitions |
| `assets` | Asset metadata (source, license, hash, provider) |
| `research_cache` | Cached research with Time To Live (TTL) expiry |
| `job_outputs` | Final output metadata |
| `audit_log` | All actions for compliance |
| `config_versions` | Versioned config patches |
| `prompt_versions` | Prompt version tracking |
| `creative_history` | Used angles/templates/assets per topic |
| `job_snapshots` | Full reproducibility data |
| `preflight_estimates` | Lightweight cost estimate |

SQLite for MVP (same schema migrates to PostgreSQL). Multi-tenant from day one.

---

## 12. Cost Optimization

### Model Selection (May 2026)

| Model | Input $/1M | Output $/1M | Best For |
|-------|-----------|-------------|----------|
| GLM-4-9B | $0.01 | $0.01 | Ultra-cheap: safety, memory checks |
| MiMo-V2-Flash | $0.09 | $0.29 | Default text (Claude quality at 3.5% cost) |
| Qwen3-32B | $0.18 | $0.28 | Indonesian-sensitive scripts |
| Gemini 2.5 Flash | $0.15 | $0.60 | Multimodal: reviewer |
| DeepSeek V3.2 | $0.25 | $0.38 | Multilingual reasoning |
| MiniMax M2.7 | $0.30 | $1.20 | Agentic planning (Stage 2) |
| Kimi K2.5 | $0.44 | $2.00 | Premium fallback |

### Presets

| Preset | Models | LLM Cost/Job |
|--------|--------|-------------|
| **Budget East** | MiMo-V2-Flash, Qwen3-32B, GLM-4-9B | ~$0.003 |
| **Agentic East** | MiniMax M2.7, DeepSeek V3.2 | ~$0.008 |
| **Premium East** | Kimi K2.5, Qwen Max, GLM-5.1 | ~$0.015 |
| **Premium West** | Claude Sonnet 4, GPT-5, Gemini Pro | ~$0.04 |

### Model Slug Resolution + Startup Preflight (PR 7)

OpenRouter requires canonical `vendor/model` slugs. Bare slugs (e.g. `mimo-v2-flash`) 404 with "No endpoints found", and removed models (e.g. `xiaomi/mimo-v2-flash`) return deprecation errors — both surfaced mid-pipeline after paid research (job_9/job_11 root causes). The `budget_east` preset (`config/hierarchy.py`) now stores canonical slugs and is the source of truth when no `*_MODEL` env override is set:

| Agent | Canonical slug |
|-------|----------------|
| safety | `z-ai/glm-4.7-flash` |
| segment_producer | `xiaomi/mimo-v2.5` |
| scriptwriter | `qwen/qwen3-32b` |
| visual_director | `xiaomi/mimo-v2.5` |
| reviewer | `google/gemini-2.5-flash` |

Resolution order: `*_MODEL` env var (`.env`) → `budget_east` preset → metadata from `data/model_cache.json`. The cache refreshes on a 7-day TTL (`model_cache._load_cache` now force-refreshes when stale, not only when missing) and exposes `list_catalog_models()` for validation.

`config/preflight.py` → `preflight_agent_models()` runs at the `Orchestrator.run_pipeline` / `run_pipeline_from` chokepoint (the single source of truth covering CLI, dashboard create, retry, and resume) and on `--dry-run`: it force-refreshes the cache, resolves every LLM-backed agent's model, and validates each slug is a key in the live catalog. A miss against a **populated** catalog fails fast (clear error → failed status / exit 1) before billing research credits; when no catalog is reachable (offline + no cache) it logs a warning and continues rather than block every run. `refresh_model_cache` dedupes refresh attempts within a 30s window so an offline run degrades promptly instead of stacking 30s `/models` timeouts. The dead `llm/router.py` (`ModelPreset`/`resolve_model`, 0 production consumers) was removed in the same PR.

### Asset-Qualification Cost Optimization (PR 8)

The PR 5 qualification boundary had no cheap filter before the VLM (`candidate_semantic_ranker` is post-VLM arithmetic; `_score_candidate` *is* the VLM), so every irrelevant candidate paid a full inspection (job_11: ~9,078 frame extractions + thousands of VLM calls, ~all `claim_support=0.00`). PR 8 adds three additive knobs — the qualification contract is unchanged:

- **Pre-VLM skip gate (option 1):** on a cache miss, `_score_candidate` computes `KeywordOverlapWindowSelector().relevance_score(candidate.model_dump(), beat)` and returns `None` without calling the VLM when overlap ≤ `_PREFILTER_MIN_OVERLAP` (default 0.0 → skips only literally-zero-overlap candidates). Cached candidates are never re-decided.
- **Frame multiplier (option 2):** `AppSettings.frame_inspection_max_frames` (48, was 120) + `frame_inspection_interval_sec` (1.0, was 0.5), threaded into Visual Director's `run_frame_inspection_pipeline` call (~7.5× fewer VLM-bound frames).
- **RECOVER cap (option 9):** `_qualify_beat` caps recovered candidates to `MAX_RECOVERED_PER_BEAT` (8) before scoring, bounding fresh inspections per all-reject beat.

All three reuse existing pure-python machinery (no torch/embeddings; ADR 0026/0027).

---

## 13. Deterministic Quality Gates and Repair Routing (Phase 21)

### Design Decision: Extend Existing Agents, No New Top-Level Agents

Job #4 output analysis revealed four categories of issues that the existing LLM-only Reviewer gate did not catch:

1. **Black/freeze frames** — video segments with no visual content
2. **Text collisions** — overlapping on-screen text from captions, overlays, and source clip text
3. **Package-scope mismatches** — declared story mode (e.g., `three_story_roundup`) did not match actual scene composition
4. **Claim-to-visual irrelevance** — narration described specific visuals but actual footage was generic or unrelated

Instead of adding new top-level agents (which would increase cost, latency, state transitions, and debugging complexity), these checks are implemented as deterministic service modules called by existing agents.

### New Core Modules

| Module | File | Key Functions | Owned By |
|--------|------|---------------|----------|
| Visual Coverage | `core/visual_coverage.py` | `evaluate_visual_coverage()` | Composer |
| Frame Sampler | `core/frame_sampler.py` | `plan_frame_samples()`, `deduplicate_samples_by_hash()` | Composer |
| Text Detection | `core/text_detection.py` | `normalize_text_region()`, `filter_text_regions()` | Visual Director |
| Text Collision | `core/text_collision.py` | `detect_text_collisions()`, `detect_source_text_density()` | Visual Director |
| Safe Area | `core/safe_area.py` | `detect_safe_area_issues()` | Visual Director |
| Story Mode | `core/story_mode.py` | `classify_story_mode()` | Segment Producer |
| Duration Budget | `core/duration_budget.py` | `allocate_duration_budget()` | Segment Producer |
| Package Consistency | `core/package_consistency.py` | `evaluate_package_consistency()` | Reviewer |
| Semantic Visual Review | `core/semantic_visual_review.py` | `score_visual_relevance()` | Reviewer |
| Repair Router | `core/repair_router.py` | `route_repair()`, `build_repair_plan()` | Engine |

### New Schema Models (in `config/schema.py`)

| Model | Purpose |
|-------|---------|
| `VisualCoverageIssue` | Individual frame coverage problem (black frame, freeze, blank region) |
| `VisualCoverageResult` | Aggregate visual coverage score + per-frame issues |
| `DetectedTextRegion` | Normalized text bounding box with position, size, source |
| `TextCollisionIssue` | Pair of overlapping text regions with overlap area |
| `SafeAreaIssue` | Caption/overlay violating TikTok safe zone boundary |
| `StoryModeDecision` | Classified narrative structure + confidence + rationale |
| `DurationBudgetSection` | Per-role duration allocation (hook, main_claim, evidence, reaction, closing_cta) |
| `DurationBudget` | Total budget + sections + remaining buffer |
| `EvidenceContract` | Maps story beat to required visual evidence + actual visual alignment |
| `VisualRelevanceScore` | Per-beat relevance score + keyword overlap + evidence match |
| `PackageConsistencyResult` | Story mode vs actual composition consistency report |
| `RepairPatch` | Single targeted fix instruction for a specific agent |
| `RepairPlan` | Ordered list of repair patches routed to correct agents |

### Revised Reviewer Hard-Gate Order

Before Phase 21, the Reviewer ran a single multimodal LLM call. Now it runs a deterministic gate chain first:

```text
visual_coverage → text_collision → safe_area → package_consistency → semantic_review → LLM
```

Each gate is a pure function that returns pass/fail with structured issues. The LLM only runs if all deterministic gates pass. This saves cost on clearly broken outputs and provides more specific failure diagnostics for repair routing.

### Repair Routing Table

| Failure Category | Detected By | Routed To | Repair Action |
|------------------|-------------|-----------|---------------|
| Black/freeze frames | `visual_coverage` | Composer | Re-render affected segments |
| Text collision | `text_collision` | Visual Director | Adjust overlay positions, reduce density |
| Safe-area violation | `safe_area` | Visual Director | Reposition captions/overlays |
| Package-scope mismatch | `package_consistency` | Segment Producer | Adjust story_beats to match declared format |
| Claim-to-visual irrelevance | `semantic_visual_review` | Segment Producer | Update visual_must_show / evidence contracts |

The engine's `route_repair()` maps each failure to a `RepairPlan` containing ordered `RepairPatch` objects. Each patch targets a specific agent with a specific fix instruction. The engine re-runs only the affected agent(s), not the entire pipeline.

### Design Principles

- **Pure functions with injected dependencies** — all modules are offline-testable without FFmpeg or LLM calls
- **Composable** — each module can be called independently or as part of the gate chain
- **Agent ownership, not agent creation** — existing agents own their quality domain, no new top-level agents
- **Deterministic before LLM** — cheap checks run first, expensive LLM only when deterministic gates pass
- **Structured repair, not blind retry** — failures produce targeted repair plans, not full pipeline re-runs

---

## 14. MVP Deliverables

1. **7 MVP Agents** — Safety, Segment Producer (edit blueprint + story beats + evidence contracts), Scriptwriter (continuous voiceover), Voice Producer (single audio + word timestamps), Visual Director (beat-driven, audio-aware, safe-area/text collision compliance), Composer (smart trimming + keyword captions + single audio timeline + visual coverage), Reviewer (deterministic gate chain: visual_coverage → text_collision → safe_area → package_consistency → semantic_review → LLM multimodal)
2. **Orchestrator** — Gated state machine with human-triggered retry + structured repair routing
3. **Creative Memory** — Pre-generation check, variation rotation
4. **Web Dashboard** — Agent observability, config editing, basic auth + 2 groups
5. **CLI** — `python3 cli.py run --topic "..." --niche indonesian_artists`; `test-agent` subcommand for independent agent debugging; `--log-level` option
6. **3 Templates + Treatment System + Audio/Subtitle Engine** — News Card, B-Roll Narration, Rapid Update + 9 treatments + 5 transitions in `templates/treatments.yaml` + per-scene audio sequencing + timed subtitle overlays + TikTok output validation
7. **Scene Normalizer** — Framerate unification (30fps), SAR normalization, Ken Burns zoompan for static images, clip duration validation
8. **Deterministic Quality Gates + Repair Routing** — 10 core modules (visual_coverage, frame_sampler, text_detection, text_collision, safe_area, story_mode, duration_budget, package_consistency, semantic_visual_review, repair_router) extending existing agents with deterministic checks before LLM review
9. **Config System** — Agent → Niche → Account → Job hierarchy with versioning
10. **Output Packager** — `video.mp4` + `caption.txt` + `thumbnail.png` + `metadata.json`
11. **Multi-Source Asset Sourcing** — YouTube, Tavily, Brave search with quality tier scoring + thumbnail fallback
12. **Runtime Visual Inspection** — Black/freeze segment detection, frame extraction with perceptual hashing, PaddleOCR text detection, MediaPipe face detection  
13. **Story-Mode Reconciliation** — 4-rule priority system + contract derivation
14. **Rendered Scene Manifest + Reviewer Context** — Scene-to-beat mapping for timestamp-semantic review
15. **Multimodal Candidate Inspection** — Image-based candidate evaluation + semantic ranking
16. **Bounded Automated Repair Loop** — Max N cycles, exhaustion detection, cycle retention, atomic promotion

---

## 15. Phase 22: Runtime Quality Enforcement & Multi-Source Asset Sourcing

Phase 22 extends the pipeline with runtime media inspection, multi-provider asset discovery, story-mode reconciliation, bounded automated repair, and multimodal candidate validation.

### Multi-Source Asset Discovery (Batch 8)

The Segment Producer now searches three additional providers beyond the existing ScrapeCreators + Firecrawl pipeline:

| Provider | Service | Search Type | Use Case |
|----------|---------|-------------|----------|
| YouTube | `YtDlpService.search()` | Video search via yt-dlp | Primary video source discovery |
| Tavily | `TavilyService` | Web news search via httpx | Recent news articles |
| Brave | `BraveSearchService` | Video + web search via stdlib urllib | Broad web + video discovery |

**Source quality tiers** (config/schema.py `SOURCE_QUALITY_TIERS`):

| Source Type | Quality Score |
|-------------|---------------|
| `youtube_official` | 0.95 |
| `web_video` | 0.85 |
| `image` | 0.70 |
| `tiktok_clip` | 0.50 |
| `article` | 0.40 |
| `firecrawl` | 0.30 |

**Flow**: `_build_search_queries()` derives max 3 queries from topic + entity names. `_discover_multi_source_assets()` calls each provider with retry/backoff, aggregates results via `_merge_asset_candidates()`. YouTube thumbnail fallback extracts `maxresdefault`→`hqdefault` as image candidates.

### Runtime Media Inspection (Batch 1-2, 5)

**FFmpeg black/freeze detection** (`core/media_detectors.py`): `detect_black_segments()` uses `blackdetect` filter, `detect_freeze_segments()` uses `freezedetect` filter. Both return typed `MediaSegment` lists. Graceful `MediaDetectionError` fallback for environment issues.

**Frame extraction** (`core/frame_extraction.py`, `core/frame_hashing.py`):
- `extract_frames()` schedules frame sampling from video at configurable intervals
- `perceptual_hash()` + `hash_distance()` compute pHash for frame deduplication

**Text detection** (`core/text_detection.py`): `normalize_text_region()` and `filter_text_regions()` normalize bounding boxes from OCR output.

**PaddleOCR runtime adapter** (`paddleocr_adapter.py`): Wraps PaddleOCR with model auto-download, confidence thresholding (default 0.5), and region normalization.

**Face detection runtime adapter** (`face_adapter.py`): Wraps MediaPipe `mp.solutions.face_detection` with image array input (cv2.imread + numpy), processes model output directly.

**Generated text region manifest** (`generated_text_manifest.py`): Tracks overlay text regions from captions and treatments for collision detection with source clip text.

### Source Cleanliness Scoring (Batch 3)

`core/source_cleanliness.py`: `score_candidate()` evaluates each asset candidate on four dimensions:
1. Source type (direct clip > image > article)
2. Resolution confidence (≥720p scores higher)
3. Aspect ratio (close to 9:16 preferred)
4. File size consistency
Score is combined with quality tier for final candidate ranking.

### Story-Mode Reconciliation (Batch 3)

`core/story_decision_reconciliation.py`: 4-rule priority system for resolving story mode conflicts:
1. **Explicit niche override**: if niche YAML declares `story_mode`, use it
2. **Multi-entity roundup**: ≥3 distinct entity names → auto `roundup`
3. **Legacy contradiction**: if `format_decision.format` contradicts item count → reconcile
4. **Fallback**: `single_story`

`core/story_mode_contract.py`: `derive_story_contract()` produces thumbnail_text, cta_text, duration_structure from canonical story mode.

### Multimodal Candidate Inspection (Batch 4)

**MultimodalInspectionClient**: wraps `OpenRouterClient` with inspection prompt construction and structured response parsing. Inspects asset candidates for:
- Relevance to topic
- Caption/overlay readability  
- Face quality (visible, centered)
- Overall suitability

**Inspection cache**: SHA-256 keyed cache with `store()`, `lookup()`, `stats()`, `invalidate()` for reuse across pipeline runs.

**Candidate semantic ranker** (`candidate_semantic_ranker.py`): Combines multimodal inspection score + relevance score + cleanliness score + credibility with rejection rules and text_card fallback.

### Rendered Scene Manifest & Reviewer Context (Batch 5)

`core/rendered_scene_manifest.py`:
- `RenderedSceneEntry`: scene_id, duration_sec, has_audio, source_type, start_timecode
- `RenderedSceneManifest`: entries, total_duration_sec, scene_count
- `build_rendered_scene_manifest()` constructs from composer output
- `scenes_at_timestamp()` finds scenes covering a timestamp
- `beat_to_scenes()` maps beats to overlapping scenes

`core/reviewer_context.py`:
- `SceneBeatMapping`: scene_id, beat_id, temporal_overlap_sec, coverage_pct
- `build_review_context_bundle()`: aggregates scene-beat mappings for reviewer
- `get_semantic_review_context()`: produces per-beat review context with evidence

**Timestamp semantic review** (reviewer.py): `_run_timestamp_semantic_review()` maps rendered scenes to story beats via midpoint containment + range overlap, emits `SceneSemanticReview` objects. Gate chain: `visual_coverage → text_collision → safe_area → package_consistency → timestamp_semantic → semantic_review → LLM`.

### Bounded Automated Repair Loop (Batch 6)

`_execute_repair_cycle()` in engine replaces manual-only repair with a bounded loop:

1. **Route patches** to correct agent via `route_repair()` (Composer for visual, Visual Director for text/safe-area, Segment Producer for scope)
2. **Re-run target agent + all downstream** (status transitions: running→completed/exhausted/manual_review)
3. **Detect repeated identical patches** via `_are_patches_identical()` → mark as exhausted
4. **Limit cycles** — max N cycles, then mark for manual review

**Status columns** added to `jobs` table: `quality_status`, `publication_status`, `repair_status`, `artifact_status`. Migration via `ensure_status_columns()`.

**Repair metrics** (`core/repair_metrics.py`):
- `compute_repair_cycle_record()`: before/after quality snapshots
- `extract_quality_snapshot()`: reviewer score + gate results
- `is_repair_improved()`: true if quality improved
- `persist_repair_cycle()`: persists record to assets_cache

### Publication Workflow (Batch 6)

`_promote_to_final()`: atomic promotion via temp directory + `os.rename`:
- Only runs when `quality_status=passed` AND `artifact_status=approved`
- Failed promotion leaves source artifacts intact
- Cycle directories preserved under `outputs/job_{id}/cycle_{n}/`

Failed outputs are retained (not deleted) for manual review. Blocked publication requires explicit approval.

### Composer Real Coverage Diagnostics (Batch 5)

Replace placeholder empty detector lists with real FFmpeg black/freeze calls:
- `_attach_visual_coverage_diagnostics()` now runs `detect_black_segments()` and `detect_freeze_segments()` on the rendered video
- Falls back gracefully to empty lists on `MediaDetectionError`
- Results persisted as structured `VisualCoverageResult`

### Repaired Composer Output Path (P1 Fix)

When running repair cycles (cycle > 0), the Composer writes to the standard contract path (`output_dir/job_{id}/video.mp4`), and output files are copied post-compose to the cycle-specific directory (`cycle_{n}/`) for `_promote_to_final`. This prevents the double-nested path bug where `video.mp4` was written to `cycle_{n}/job_{id}/video.mp4`.

### Wired Timestamp Semantic Review (P2 Fix)

The semantic review gate was wired into both reviewer call sites:
- `_execute_single_repair_cycle()` and `_retry_review_and_package()` now pass `story_beats`, `word_timestamps`, `rendered_scene_manifest`, and `diagnostics` to the reviewer
- The timestamp semantic review gate actually enforces scene-to-beat alignment instead of silently skipping

## 16. Phase 23: Reviewer Context + Diagnostics Enforcement Contract

Phase 23 closes the Reviewer enforcement gap exposed by runtime quality gates. Composer now emits structured diagnostics and a rendered scene manifest; the engine forwards both into Reviewer on normal and repair rerun paths.

### Reviewer Context Inputs

- `story_beats` — Segment Producer beat contract with visual instructions and evidence contracts.
- `word_timestamps` — Voice Producer word-level timestamps.
- `rendered_scene_manifest` — serialized Composer manifest with scene durations, source types, and timecodes.
- `diagnostics` — Composer diagnostics including visual coverage, text collision, safe-area, package consistency, and semantic visual review results.

### Enforcement Contract

- Normal pipeline `_retry_review_and_package()` passes all Reviewer context kwargs.
- Repair rerun path after Composer repair passes the same kwargs so deterministic gates remain active after repair.
- `RenderedSceneManifest` is serialized to dict before Reviewer gate code reads `entries`.
- Gate order: `visual_coverage → text_collision → safe_area → package_consistency → timestamp_semantic → semantic_review → LLM`.

### Consequences

- Deterministic gates can fail or route repairs using Composer evidence instead of silently skipping.
- Timestamp-level semantic review can map rendered scenes to story beats with evidence contracts.
- Reviewer LLM spend is protected by deterministic gates in both production and repair paths.

## 17. Phase 26 (PR 5): Pre-Visual-Director Asset Qualification Boundary

PR 5 is the real Job #8 fix. Job #8 root cause was **candidate rejection, not scarcity**: Visual Director rejected ~7 of 8 candidates and fell back to text cards. A new in-process boundary scores image candidates *before* VD consumes them and — critically — runs **source recovery before the text-card fallback**.

**ADR compliance:** ADR 0026 governs this work as *"enforce contracts, do NOT rebuild"* — pure orchestration, no new agent, no new gate, no schema change, no state-machine change. ADR 0027 governs the cache-miss inspection delegation (below).

### Module & Seam

| Element | Value |
|---------|-------|
| **Module** | `clipper_agency/core/asset_qualification.py` (pure orchestration) |
| **Engine seam** | `Engine._run_visual_director_phase` via helper `_apply_asset_qualification` — runs after voicing, before the `_run_visual_director` call |
| **DB state machine** | Unchanged (no new state, no new gate) |
| **Version** | Stays `v2.3.0` (PR 10 owns the `v2.4.0` bump) |

The module imports and calls only existing modules (`inspection_cache`, `MultimodalInspectionClient`, `semantic_visual_review`, `candidate_semantic_ranker`); it imports **neither** `segment_producer` nor `visual_director` — the Segment Producer discovery callable is injected as an opaque `Callable` via `RecoveryPolicy.discover_fn` to break the import cycle.

### Per-Beat Ordering (SCORE → RANK → RECOVER → FALLBACK)

`_qualify_beat` is the module-level contract that owns the ordering:

1. **SCORE** all candidates via `_score_candidate`.
2. **RANK** via `candidate_semantic_ranker.rank_candidates()` → decisions `{accept, revise, reject, fallback_card}`.
3. **QUALIFIED CHECK** — if any candidate is `{accept, revise}` → `verdict='qualified'`, `recovery_outcome='none'`. No recovery, no text card.
4. **RECOVER stage** — fires **only** when qualified is empty: a bounded re-run of Segment Producer discovery for fresh candidates (`MAX_RECOVERY_CYCLES=1`, no loop), then re-score/re-rank. Success → `verdict='recovered'`, `recovery_outcome='ran'`. This runs **before** any text-card fallback. Recovery is synchronous in-process: it emits no `RepairPatch`, calls no `build_gate_failure_repair_plan`, and touches no `GATE_FAILURE_REPAIR_MAP` (distinct from ADR 0023's post-Reviewer repair path).
5. **FALLBACK (terminal, last resort)** — only if qualified is *still* empty after recovery (or recovery is disabled/exhausted) → `verdict='exhausted_text_card'`, `qualified=[]`, `fallback_card={...}`. **The only path that emits a text card.**

### Immutable Candidate-Pool Rewrite & Artifact

The seam **immutably rewrites** `beat.asset_candidates` to the qualified set only (new dicts per spread — rejected candidates never reach VD's live per-beat surface), defense-in-depth-filters the flat candidate pool, and writes a `qualification_report.json` artifact via existing `core/paths.py` helpers. The report documents per-beat verdicts (`qualified` | `recovered` | `exhausted_text_card`), `recovery_outcome` (`none` | `ran` | `exhausted` | `no_fn`), `recovery_attempts`, and `reject_reasons` (`asset_id → reason`).

### Cache-Key Parity & Inspection Delegation (0 double-VLM spend)

- **Cache-key parity (hard gate):** `asset_qualification._score_candidate` and `VD._score_one_candidate` compute byte-identical cache keys. VD's re-inspection of a pre-qualified candidate is therefore a cache hit → **0 double-VLM spend**. Existing VD tests pass unmodified (VD source untouched — blast-radius contained).
- **Inspection delegation (ADR 0027):** on a cache miss, the qualification layer **delegates** to Visual Director's own bound `_run_multimodal_inspection` (injected at the seam) rather than lifting ~140 lines of OCR/face/enhanced ML machinery. The cached output is byte-identical to VD's (no cache-namespace drift) and frame ownership stays in VD.

### Evidence

The SLICE 12 hard merge gate proves M < N (recovery strictly reduces text-card fallbacks vs the all-reject baseline) on the real frozen Job #8 research contract. Visual Director source is untouched; its existing 69 tests pass unmodified. `do_not_use` URL re-filtering at the boundary (SLICE 8) is deferred — Visual Director already enforces `do_not_use` at four downstream points, so re-filtering here would be redundant contract re-enforcement; the qualification layer's native badness signal is `reject_reasons`.

**Reference design:** `docs/plans/pr5-asset-qualification-design.md`. **ADRs:** `docs/adr/0026-v2.4.0-contract-enforcement-over-rebuild.md`, `docs/adr/0027-asset-qualification-inspection-delegation.md`.

## 18. Phase 26 (PR 6): Clip-Window Selector (Minimal, Contract-First)

PR 6 freezes the clip-window **data-flow contract** so the propagation path (qualification → VD → Composer) is fixed, then ships a conservative default selector. The localizing backend (transcript/whisper) is deferred — it plugs into the same `WindowSelector` Protocol later without touching the propagation shape. Per ADR 0026, this is "enforce contracts, do NOT rebuild": pure orchestration, no new agent, no new gate, no state-machine change.

### Module & Data Contract

| Element | Value |
|---------|-------|
| **Module** | `clipper_agency/core/clip_window.py` (pure orchestration) |
| **Frozen dataclass** | `ClipWindow(start_sec: float, end_sec: float | None)` — `None` end ⇒ through end of source |
| **Pluggable Protocol** | `WindowSelector.select(candidate, beat, *, source_duration_sec=None) -> ClipWindow` |
| **v1 default selector** | `KeywordOverlapWindowSelector` — **conservative**: returns `ClipWindow(0.0, None)` for every candidate because keyword overlap cannot localize a spoken point to a timestamp (returns the full-clip window, equivalent to today's from-zero trim) |
| **Schema** | `AssetCandidate` gains optional `source_start_sec: float = 0.0` and `source_end_sec: float | None = None` (additive — defaults preserve today's from-zero trim) |
| **Cache parity** | The two new fields are **excluded** from `compute_asset_content_hash` (`type`/`url`/`source_type` only), so PR 5's cache-key parity holds — identical content still hits the inspection cache regardless of window |
| **Version** | Stays `v2.3.0` (PR 10 owns the `v2.4.0` bump) |

### Propagation (qualification → VD → Composer)

1. **Qualification seam** — `Orchestrator._apply_asset_qualification` invokes the injected selector and attaches the resulting `ClipWindow` to each kept candidate (writing `source_start_sec` / `source_end_sec`).
2. **Visual Director** — `_attach_candidate_windows` re-attaches the window by `source_url` (candidate dicts flow through VD; the window rides along); `_exec_tiktok_clip` carries `source_start_sec`/`source_end_sec` into the asset dict VD emits.
3. **Composer** — `_smart_trim` clamps the window to the source's actual duration (a degenerate `ClipWindow(0.0, None)` clamps to the full clip, so behavior is unchanged for the v1 default). `_trim_long_clip` and `_stretch_short_clip` emit `-ss <source_start_sec>` so the FFmpeg trim honors the window.

### Deferred Backend (post-v2.4.0)

The transcript/whisper backend is **deferred**: faster-whisper behind a config flag, yt-dlp auto-caption extraction, and keyframe-precise snapping. Blocked by ADR 0026 (do-not-rebuild), the GPU-forbidden constraint, the absence of any existing transcript infra, and the fact that the v2.4.0 release gate does NOT require clip-windowing. The "trimmed segment matches beat's spoken point" verification criterion waits for this backend (documented honestly; the PR 6 v1 default cannot satisfy it because it never narrows the window). Until then, the propagation contract is proven end-to-end on the degenerate full-clip window: source bounds are respected, `source_start_sec`/`source_end_sec` flow through, and Composer emits `-ss <start>`.

**Reference design:** `docs/plans/pr6-clip-window-design.md`. **ADR:** `docs/adr/0026-v2.4.0-contract-enforcement-over-rebuild.md`.

