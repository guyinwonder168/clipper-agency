# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] — 2026-06-05

### Phase 19: Composer Treatment & Transition Engine

Complete overhaul of the Composer agent's video assembly pipeline — replacing broken `amix` audio mixing with per-scene audio pairing, adding xfade transition support, timed subtitle overlays, and TikTok-ready production output.

#### New Modules (4)

- **`rendering/treatment_config.py`** — Frozen dataclass YAML loader for treatment/transition definitions. `TreatmentDef` and `TransitionDef` with immutable access via `TreatmentConfig`.
- **`rendering/treatment_filters.py`** — Per-scene FFmpeg filter string builder with variable substitution (`{frames}`, `{text}`, `{duration}`, `{start_time}`) and input-type rules (image+zoompan prepend scale, post-scale/crop append setsar).
- **`rendering/audio_sequencer.py`** — Per-scene audio+video concat filter builder. Mode A (paired when no xfade), Mode B (audio-only when xfade handles video). Pads missing audio with silence.
- **`rendering/subtitle_engine.py`** — Script text to timed `CaptionOverlay` conversion with absolute timestamps. Hook overlay (first 3s). TikTok output validation (6 FFmpeg flags).

#### Composer Overhaul

- Replaced broken `amix=inputs=N` (all voices played simultaneously) with per-scene `concat` filter pairing each voice file with its scene.
- Added xfade/concat mixed transition chain with offset calculation (`cumulative_duration - trans_duration - safety_margin`), duration clamping, and fallback to crossfade for unknown transitions.
- Integrated treatment filter chains into assembly — treatment filters prepended before trim when present.
- Added timed subtitle drawtext overlays from scriptwriter text, chained with `enable='between(t,start,end)'` and `escape_drawtext()`.
- Threaded `script_scenes` from orchestrator through Composer pipeline.
- Added production output flags: `-pix_fmt yuv420p`, `-movflags +faststart`.
- Removed dead `_build_filter()` code (broken amix pattern, zero callers).

#### Tests

- 699 → 783 tests (+84 new, -7 dead removed, net +77).
- 93%+ line coverage maintained.
- New test classes: `TestComposerTreatmentFilters` (5), `TestComposerTransitions` (8), `TestComposerAudioSequencer` (6), `TestComposerSubtitles` (5), `TestComposerUnifiedPipeline` (6), `TestComposerEdgeCases` (10), `TestTreatmentConfig` (9), `TestTreatmentFilters` (13), `TestAudioSequencer` (8), `TestSubtitleEngine` (17), expanded `TestTreatmentTemplates` (7→11).

#### Documentation

- All 6 spec docs updated (PRD v2.8, SRS v2.8, technical_design v3.9, requirements_traceability v2.9, README, AGENTS.md).
- New PR-28, FR-34/35/36, facts #123-129, edge cases E26a-E26d.
- Slow-motion treatment deferred to evolution plan (technical constraint with trim-based duration contract).

---

## [1.1.0] — 2026-06-04

### Phase 13: Retry/Resume + Cache Reuse

- CLI `job-retry <id> --from <agent>` and `job-resume <id>` for human-triggered retry from any agent.
- Dashboard POST `/jobs/<id>/retry` and `/jobs/<id>/resume` with CSRF protection.
- Job config snapshot frozen at creation; retries use same snapshot.
- `validate_agent_cache()` skips paid provider calls when valid cached artifacts exist.

### Phase 12: Artifact Contracts + Debug Observability

- Canonical job workspace paths (`ASSETS_CACHE/job_{id}/agents/{agent}/`).
- Artifact writer helpers for persisting agent input.json, output.json, gate results.
- Safety, Researcher, Scriptwriter, Voice Producer, Visual Director artifacts all persisted.
- Job manifest for full reproducibility.

### Phase 11: Logging, Model Config, ScrapeCreators Cache

- Structured logging for all agents, services, and LLM client (model, tokens, cost, latency).
- Per-agent model configuration via environment variables (`SAFETY_MODEL`, `RESEARCHER_MODEL`, etc.).
- ScrapeCreators response caching with `trim=true` + `_extract_fields()`.
- `test-agent` CLI subcommand for independent agent debugging.
- All 14 SonarCloud issues resolved (log injection, exception logging, complexity).

### Phase 10: .env Config Fix

- `pydantic-settings` `AppSettings` for typed config access.
- `load_dotenv()` called at CLI entry (`__main__.py`).
- Test isolation with `AppSettings(_env_file=None)` + `patch.dict(os.environ, clear=True)`.

### Phase 9: Docker Deployment

- Dockerfile + docker-compose.yml for VPS deployment.
- Integration smoke test for full pipeline.
- CI push trigger for master branch SonarCloud analysis.

### Phase 8: Configurable Prompts & Templates

- YAML-based prompt and template configuration.
- Configurable niche profiles, video templates, agent prompts.

### Phase 7: Web Dashboard

- Flask web dashboard with basic auth (2 groups: privileged, creative/ops).
- Job listing, agent observability, configuration editing.
- CSRF-protected POST routes.

### Phase 6: Orchestrator Engine

- Gated state machine with 10 gates (G1-G10) — pass/soft-fail/hard-fail at every transition.
- CLI interface: `python3 -m clipper_agency run --topic "..." --niche indonesian_artists`.
- 216 tests, 97% line coverage.

### Phase 5: Individual Agents

- 7 agents: Safety, Researcher, Scriptwriter, Voice Producer, Visual Director, Composer, Reviewer.
- Output Packager: `video.mp4` + `caption.txt` + `thumbnail.png` + `metadata.json`.
- Base agent class with DB state tracking.

### Phase 4: Agent Framework

- Base agent class with lifecycle management.
- Job state machine with transition validation.
- All 10 gate definitions (G1-G10).

### Phase 3: External Service Integrations

- OpenRouter LLM client with model routing.
- ElevenLabs voice generation service.
- yt-dlp media download service.
- Pexels stock media service.
- Firecrawl web search service.
- ScrapeCreators TikTok data service.

### Phase 2: Database Layer

- SQLite schema with 15 tables (WAL mode, advisory locks).
- Connection management, CRUD queries.
- Multi-tenant schema from day one.

### Phase 1: Configuration System

- Config hierarchy: Agent → Niche → Account → Job-level overrides.
- YAML-based niche and account configuration.

### Phase 0: Project Scaffolding

- Package skeleton with CLI entry point.
- Test infrastructure with conftest.
- CI/CD: GitHub Actions + SonarCloud + GitGuardian.
- Product documentation (PRD, SRS, technical design, traceability matrix).

---

## [1.1.0] — 2026-06-04

### Phase 18: Visual Director Enhancement

- Treatment metadata pipeline: Visual Director selects per-scene treatments and transitions from `templates/treatments.yaml`.
- 9 visual treatments (Ken Burns zoom/pan, cinematic crop, B-roll, slow-motion, lower-third, text card reveal, hook caption, fade-to-black) and 5 transitions (crossfade, hard_cut, wipe_left, dissolve, circle_open).
- Per-scene `target_duration` applied as `trim=duration=X` in Composer assembly.
- Rewritten Visual Director prompt with video production expertise (FPS rules, pacing, treatment selection, default routing).
- FFmpeg visual techniques research document added.

### Phase 17: Niche Wiring + Prompt Deduplication

- Niche config wired through orchestrator — `channel_description`, `safety_rules`, `search_terms` derived from YAML.
- CLI validates niche exists before pipeline start.
- Individual niche fields as prompt template variables replacing hardcoded text.
- `content_angle`, `search_terms`, `max_hashtags` added to NicheConfig schema.
- All prompt files renamed `.txt` → `.md` for editor support.
- ADR 0014 (Visual Director LLM), ADR 0015 (artifact workspace), ADR 0016 (OWASP path traversal).

### Phase 16: Visual Director LLM Planning

- LLM-driven per-scene visual planning replacing blind sequential URL assignment.
- `_compact_research_data()` strips noise, `_plan_with_llm()` creates structured plan, `_execute_plan()` dispatches via action table.
- 4 action types: `tiktok_clip`, `pexels_video`, `pexels_image`, `text_card`.
- 3-tier image fallback for text cards: Pexels photo search → Firecrawl article image → gradient background.
- `search_photos()` added to PexelsService.
- Graceful fallback to legacy sequential planning on LLM failure.

### Phase 15b: E2E Pipeline Bugfixes

- Fixed voice producer partial completion (Gemini TTS 429 backoff).
- SAR normalization in scene normalizer.
- Agent failure status checks for voice_producer, visual_director, composer.
- `_fail_agent` deduplication — extracted shared failure handler.
- Composer FFmpeg progress logging and timeout.

### Phase 15a: Template Rendering Engine

- YAML template system under `clipper_agency/rendering/` with 3 adapters (News Card, B-Roll Narration, Rapid Update).
- Typed render contracts (`contracts.py`), shared FFmpeg primitives (`primitives.py`), template-aware thumbnails (`thumbnails.py`).
- `RenderEngine` orchestrates FFmpeg filter graph from primitives + adapter output.
- Composer template routing with diagnostics.

### Phase 14: Media/Composer Correctness

- FFmpeg preflight diagnostic (ffmpeg, ffprobe, libx264, aac, mp3).
- Generated card fallback (Pillow-rendered 1080x1920 text cards).
- Deterministic video validation (G10): resolution, duration, codec, audio track check before Reviewer.
- Fixed-contract packager (S6549 safe paths).
- Repetitive failure patterns documented (`docs/repetitive-failure-patterns.md`).
