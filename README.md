```
 ██████╗██╗     ██╗██████╗ ██████╗ ███████╗██████╗ 
██╔════╝██║     ██║██╔══██╗██╔══██╗██╔════╝██╔══██╗
██║     ██║     ██║██████╔╝██████╔╝█████╗  ██████╔╝
██║     ██║     ██║██╔═══╝ ██╔═══╝ ██╔══╝  ██╔══██╗
╚██████╗███████╗██║██║     ██║     ███████╗██║  ██║
 ╚═════╝╚══════╝╚═╝╚═╝     ╚═╝     ╚══════╝╚═╝  ╚═╝

 █████╗  ██████╗ ███████╗███╗   ██╗ ██████╗██╗   ██╗
██╔══██╗██╔════╝ ██╔════╝████╗  ██║██╔════╝╚██╗ ██╔╝
███████║██║  ███╗█████╗  ██╔██╗ ██║██║      ╚████╔╝ 
██╔══██║██║   ██║██╔══╝  ██║╚██╗██║██║       ╚██╔╝  
██║  ██║╚██████╔╝███████╗██║ ╚████║╚██████╗   ██║   
╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝ ╚═════╝   ╚═╝   
```

<p align="center">
  <strong>AI-powered TikTok content factory.</strong><br>
  Seven autonomous agents + gated pipeline → one command → ready-to-upload video.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python">
  <img alt="Tests" src="https://img.shields.io/badge/tests-1793%20passing-brightgreen">
  <img alt="Coverage" src="https://img.shields.io/badge/coverage-93%25-brightgreen">
  <img alt="FFmpeg" src="https://img.shields.io/badge/FFmpeg-5.0%2B-orange?logo=ffmpeg">
  <img alt="SonarCloud" src="https://img.shields.io/badge/SonarCloud-passing-brightgreen?logo=sonarcloud">
  <a href="docs/PRD.md"><img alt="Docs" src="https://img.shields.io/badge/docs-PRD-blue"></a>
  <a href="docs/SRS.md"><img alt="Docs" src="https://img.shields.io/badge/docs-SRS-blue"></a>
  <a href="docs/technical_design.md"><img alt="Docs" src="https://img.shields.io/badge/docs-Technical%20Design-blue"></a>
</p>

---

## Pipeline

```
Topic → G1 → Safety → G2 → Segment Producer (story_beats + edit blueprint) → G3-G5 → Scriptwriter (continuous voiceover) → Script Gate → Voice Producer (single audio + word timestamps) → G8 → Visual Director (beat-driven, audio-aware) → G9 → Composer (smart trim + keyword captions) → G10 → Reviewer (quality gates) → Output
```

Each step is **gated** (pass/soft-fail/hard-fail). Agents communicate through **database state** — no direct agent-to-agent calls. Audio-first architecture: voiceover generated first, visuals fitted to audio timeline.

### Output Package

```
outputs/{job_id}/
├── video.mp4        # 9:16 TikTok-ready video
├── caption.txt      # Auto-generated caption
├── thumbnail.png    # Video thumbnail
└── metadata.json    # Job metadata + cost + provenance
```

---

## Quick Start

```bash
git clone https://github.com/guyinwonder168/clipper-agency.git
cd "clipper agency"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Then fill in your API keys. Required:

| Key | Purpose |
|-----|---------|
| `OPENROUTER_API_KEY` | LLM routing for all agents |
| `ELEVENLABS_API_KEY` | Voice generation (primary) |
| `GEMINI_API_KEY` | Voice generation (fallback) & multimodal inspection |
| `FISHAUDIO_API_KEY` | Voice generation (fallback) |
| `PEXELS_API_KEY` | Stock video/images fallback |
| `FIRECRAWL_API_KEY` | Web research & scraping |
| `SCRAPECREATORS_API_KEY` | TikTok data scraping |
| `TAVILY_API_KEY` | Web news search (multi-source asset sourcing) |
| `BRAVE_API_KEY` | Video/web search (multi-source asset sourcing) |

### Run

```bash
# Run the full pipeline
python3 -m clipper_agency run --topic "Berita terbaru artis Indonesia"

# Debug mode with verbose logging
python3 -m clipper_agency run --topic "..." --log-level DEBUG

# Dry run (validate input without execution)
python3 -m clipper_agency run --topic "..." --dry-run

# Start the web dashboard
python3 -m clipper_agency dashboard

# List recent jobs
python3 -m clipper_agency jobs

# Run with a different niche
python3 -m clipper_agency run --topic "..." --niche indonesian_artists

# Test an individual agent (bypasses orchestrator DB tracking)
python3 -m clipper_agency test-agent safety --topic "..."
python3 -m clipper_agency test-agent segment_producer --topic "..."

# Retry/resume a failed job from a specific agent
python3 -m clipper_agency job-retry 125 --from composer
python3 -m clipper_agency job-resume 125
```

### Docker

```bash
docker compose up --build
# Dashboard at http://localhost:5000
```

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ |
| Video | FFmpeg 5.0+ (CPU-only) |
| Database | SQLite (WAL mode, advisory locks) |
| LLM | OpenRouter API (multi-model routing) |
| Voice | ElevenLabs / Gemini TTS / Fish Audio (fallback chain) |
| Media | yt-dlp (primary), Pexels (fallback), Brave (video search) |
| Research | ScrapeCreators + Firecrawl + Tavily (news) |
| Auth | Basic auth (2 groups: privileged, creative/ops) |
| Container | Docker Compose |
| CI/CD | GitHub Actions + SonarCloud + GitGuardian |

---

## Project Structure

```
clipper_agency/
├── __init__.py
├── __main__.py              # Entry point: python3 -m clipper_agency
├── config/                  # Pydantic config loader & hierarchy
├── core/                    # Quality gates, inspection, repair, shared utils
│   ├── visual_coverage.py, frame_sampler.py, media_detectors.py
│   ├── text_detection.py, text_collision.py, safe_area.py
│   ├── story_mode.py, story_mode_contract.py, story_decision_reconciliation.py
│   ├── duration_budget.py, package_consistency.py, semantic_visual_review.py
│   ├── rendered_scene_manifest.py, reviewer_context.py
│   ├── frame_extractor.py, frame_hash.py, frame_inspection_pipeline.py
│   ├── multimodal_provider.py, inspection_cache.py, candidate_semantic_ranker.py
│   ├── ocr_adapter.py, face_adapter.py, source_cleanliness.py
│   ├── final_layout_inspection.py, generated_text_manifest.py
│   ├── repair_router.py, repair_metrics.py
│   ├── scene_normalizer.py, scene_validator.py, validation.py
│   ├── ffmpeg_preflight.py, ffmpeg_runner.py, media_probe.py
│   ├── card_generator.py, card_to_video.py, artifacts.py
│   ├── model_diagnostics.py, job_debug.py, manifest.py
│   └── logging.py, paths.py, safe_paths.py, inspection_paths.py
├── observability/           # LLM trace artifacts & redaction
│   ├── llm_trace.py
│   └── redaction.py
├── db/                      # SQLite schema, queries, connection
├── orchestrator/            # Gated state machine
│   ├── engine.py
│   ├── gates.py
│   ├── state_machine.py
│   ├── timeline.py
│   ├── validator.py          # Content direction format validator
│   └── duration_gate.py      # Script duration gate (pre-TTS)
├── agents/                  # 7 pipeline agents
│   ├── base.py
│   ├── safety.py
│   ├── segment_producer.py   # Formerly researcher — edit blueprint + story beats
│   ├── scriptwriter.py
│   ├── voice_producer.py
│   ├── visual_director.py
│   ├── composer.py
│   ├── reviewer.py
│   └── prompts.py            # Shared prompt loading
├── llm/                     # OpenRouter client, model routing, multimodal
│   ├── client.py
│   ├── router.py
│   └── multimodal_client.py
├── services/                # External API integrations
│   ├── elevenlabs.py
│   ├── gemini_tts.py         # TTS fallback: Google AI Studio
│   ├── fish_audio.py         # TTS fallback: Fish Audio
│   ├── pexels.py
│   ├── ytdlp.py
│   ├── firecrawl_service.py
│   ├── scrapecreators.py
│   ├── brave.py              # Multi-source: Brave Search API
│   └── tavily.py             # Multi-source: Tavily News API
├── rendering/               # Template-driven video rendering engine
│   ├── templates.py         # YAML template loading & validation
│   ├── contracts.py         # Typed render plan dataclasses
│   ├── primitives.py        # FFmpeg filter chain builders
│   ├── engine.py            # FFmpeg render orchestrator
│   ├── treatment_config.py  # YAML loader for treatment/transition definitions
│   ├── treatment_filters.py # Per-scene FFmpeg filter string builder
│   ├── audio_sequencer.py   # Per-scene audio+video concat filter builder
│   ├── subtitle_engine.py   # Script text → timed CaptionOverlay + TikTok validation
│   ├── thumbnails.py        # Pillow thumbnail generation
│   └── renderers/           # Per-template adapters (News Card, B-Roll, Rapid Update)
├── output/                  # Video packaging & thumbnail
└── dashboard/               # Flask web UI (basic auth)
```

---

## Dashboard

The web dashboard provides job management, agent observability, and configuration editing.

```bash
python3 -m clipper_agency dashboard
# http://localhost:5000
```

Required `.env` config for dashboard auth:
- `DASHBOARD_USERNAME=admin`
- `DASHBOARD_PASSWORD=changeme`
- `DASHBOARD_SECRET_KEY=<random-secret>` (required for state-changing operations: retry, resume, delete)

---

## Niche & Template System

Content rules are **data-driven** — no code changes needed to change platform, language, or tone:

```
niches/           # Language, tone, platform rules, safety config
  └── indonesian_artists.yaml

templates/        # Scene structure, duration, overlay config
  ├── news_card.yaml
  ├── b_roll_narration.yaml
  ├── rapid_update.yaml
  └── treatments.yaml       # 9 visual treatments + 5 transitions + FPS/pacing rules
```

---

## Development

```bash
# Run all tests (fast, ~10s)
python3 -m pytest

# Run a single test
python3 -m pytest tests/path/test_file.py::test_name -v

# Run with coverage
python3 -m pytest --cov=clipper_agency

# Skip integration & external API tests
python3 -m pytest -m "not integration and not external"

# Run integration tests (requires API keys)
python3 -m pytest -m integration
```

Tests live in `tests/` mirroring the package structure. Currently **1793 tests** at **93%+ line coverage**.

---

## Documentation

| Document | Description |
|----------|-------------|
| [PRD](docs/PRD.md) | Product requirements & scope |
| [SRS](docs/SRS.md) | Software requirements specification |
| [Technical Design](docs/technical_design.md) | Architecture, gates, agents |
| [Requirements Traceability](docs/requirements_traceability.md) | End-to-end requirement mapping |
| [Evolution Plan](docs/design/evolution_plan.md) | Future stages roadmap |
| [Implementation Plan](docs/plans/2026-05-26-mvp-implementation.md) | Phase-by-phase build log |

---

## Status

**✅ MVP Complete** — Phases 0-22 implemented. Runtime quality enforcement with black/freeze frame detection, text/face detection, story-mode reconciliation, multimodal candidate inspection, multi-provider asset sourcing (YouTube/Tavily/Brave), bounded automated repair loop, and timestamp-semantic review. All 1793 offline tests passing.

1793 tests passing · 93%+ line coverage · Docker-ready · SonarCloud quality gate passing
