# Clipper Agency — Requirements Traceability Matrix

**Version:** 2.8
**Date:** 2026-06-05
**Status:** MVP Phases 0-18 Complete — Treatment System, Scene Normalizer, LLM Visual Director

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
| 74 | `test-agent` CLI subcommand: runs individual agents independently, bypasses orchestrator DB tracking | SRS §2 FR-19, Design §13 |

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
| 94 | Output package fixed-contract nomenclature ensures `video.mp4`, not `final.mp4`; packager uses OWASP-safe path sandbox (S6549) | PRD §4, Design §1, Design §13 |
| 95 | Thumbnail generated as 1080x1920 PNG using Pillow with template-based styling, included in final package as `thumbnail.png` | PRD §4, Design §13 |

### From Phase 15a Template Rendering Engine

| # | Fact | New Location |
|---|------|-------------|
| 96 | YAML template definitions under `templates/` drive rendering; 3 built-in templates: News Card, B-Roll Narration, Rapid Update | PRD §5 PR-07, SRS §2 FR-21, Design §10 |
| 97 | `TemplateLoader` validates template YAML at load time (required fields, type checks, default values) — fails fast before any FFmpeg work | Design §10, Design §13 |
| 98 | Render contracts (`RenderContract`, `ClipSpec`, `AudioTrack`, `TextOverlay`, `TransitionSpec`) define typed inputs for every adapter | Design §7, Design §13 |
| 99 | Shared rendering primitives (`build_concat_filter`, `build_audio_mix`, `build_fade`, `build_crossfade`, `build_drawtext`) produce FFmpeg filter chains | Design §7, Design §13 |
| 100 | Template thumbnails generated via Pillow with title text, template-specific styling, and 1080x1920 output — replaces generic thumbnail when template selected | PRD §4, Design §13 |
| 101 | `RenderEngine` orchestrates FFmpeg filter graph from primitives + adapter output; produces intermediate and final video via two-pass concat + overlay | Design §7, Design §13 |
| 102 | Three adapters (`NewsCardRenderer`, `BRollNarrationRenderer`, `RapidUpdateRenderer`) translate template specs into `RenderContract` + filter chains | Design §10, Design §13 |
| 103 | Composer agent routes template selection by niche config and script structure; runs FFmpeg preflight diagnostics before rendering | Design §4, Design §7, Design §13 |
| 104 | All rendering tests offline: template loading, contract validation, primitive filter chains, thumbnail generation, adapter output, engine orchestration, composer template routing | SRS §3 NFR-09, Design §13 |

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

---

## Requirements Traceability Matrix

### MVP P0 Requirements

| PRD ID | SRS ID | Design Section | Gate | Edge Cases | Validation |
|--------|--------|---------------|------|------------|------------|
| PR-01 | FR-01 | §3 Gated Pipeline | All gates | Empty topic, no niche config | G1 preflight |
| PR-02 | FR-01..FR-14 | §3, §4 | G1-G10 | See edge case catalog below | Gate definitions |
| PR-03 | FR-17 | §13 Dashboard | N/A | Dashboard unavailable | N/A |
| PR-04 | FR-18 | §13 CLI | N/A | Invalid CLI args | N/A |
| PR-05 | FR-10 | §3, §13 Output | G10 | Missing file, wrong format | Deterministic check — **Phase 15a**: `clipper_agency/rendering/engine.py` produces video via template-driven rendering; `clipper_agency/rendering/thumbnails.py` generates thumbnail; tests: `tests/test_rendering_engine.py`, `tests/test_rendering_thumbnails.py` |
| PR-06 | FR-27 | §9 Config | N/A | Invalid config | Config validation |
| PR-10 | FR-02 | §4 Safety, §3 G4 | G4 pre + post | See safety edge cases | G1 preflight + G4 |
| PR-11 | FR-13 | §3 G2 | G2 | Zero credits | G2 estimate |
| PR-15 | NFR-04 | §12 Cost | N/A | Model pricing change | Cost recalculation |
| PR-22 | FR-24 | §9 Config, §9 Env Layer | N/A | Missing model env var | Default to `mimo-v2-flash` |
| PR-23 | FR-25, NFR-10 | §2 Logging | N/A | Log level misconfigured | Default to INFO |
| PR-25 | FR-06 | §4 Voice Provider, §9 Env Layer | G8 | ElevenLabs missing/fails, Gemini missing/fails, Fish Audio missing/fails | Try fallback order, persist attempts, then clear error/stop pipeline |
| PR-26 | FR-32 | §7 Treatment System, §10 Templates | N/A | Invalid treatment YAML, unknown treatment type, missing FFmpeg filter | `templates/treatments.yaml` validated at load time; unknown treatments fall back to `broll_standard` |
| PR-27 | FR-33 | §7 Scene Normalization | G9 | Mixed framerates, non-1:1 SAR, static images, flash frames | Scene normalizer in Composer pipeline: framerate→30fps, SAR→1:1, zoompan for images, reject <1s clips |

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

### Reviewer Edge Cases

| # | Edge Case | Handling | Location |
|---|-----------|----------|----------|
| E26 | Reviewer rejects (1st time) | Recommend specific step to retry. Human triggers. | PRD §8, Design §4 |
| E27 | Reviewer rejects (2nd time) | Human review required. No more auto-retry. | PRD §8, Design §4 |
| E28 | Variation exhausted | MVP: human review. Stage 2: Creative Director. | Design §8 |

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
