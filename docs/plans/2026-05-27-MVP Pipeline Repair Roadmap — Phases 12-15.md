# MVP Pipeline Repair Roadmap — Phases 12-15

> Phase 12 ✅ Complete (merged `c001685` on master via PR #15).
> Phase 13 ✅ Complete (merged `497aa3c` on master via PR #16).
> Phase 14 ✅ Complete (merged `1f36918` on master via PR #17).
> Phase 15a ✅ Complete (all 3 PRs merged to master).

**Goal:** Repair the MVP pipeline across Phases 12-15a so it matches the PRD/SRS/technical design: restartable job workspaces, persisted agent/gate contracts, retry/resume, correct media composition, and template-driven rendering.

**Architecture:** Implement the cleanup as four reviewable MVP repair phases. Phase 12 creates the canonical per-job workspace under `settings.assets_cache`, persists each agent's `input.json`/`output.json`, persists every gate result, and keeps `settings.output_dir` only for final customer-ready packages. Phase 13 adds retry/resume and cache reuse. Phase 14 repairs media/composer correctness. Phase 15 completes template-driven rendering and full observability.

**Tech Stack:** Python 3.11, pydantic-settings, SQLite, pytest, httpx, FFmpeg, yt-dlp, Pexels, ScrapeCreators, Firecrawl, ElevenLabs, Google AI Studio Gemini TTS, Fish Audio.

---

## Context and Current Problem

Current implementation drifted from `docs/PRD.md`, `docs/SRS.md`, `docs/technical_design.md`, and `docs/requirements_traceability.md`:

- `ASSETS_CACHE` exists in config but production code does not use it.
- Researcher writes cache files into `OUTPUT_DIR/job_{id}/research/` instead of `ASSETS_CACHE/job_{id}/agents/researcher/`.
- Scriptwriter returns data in memory only; no persisted script artifacts.
- Voice Producer writes flat `scene_{i}.mp3` files into the output directory.
- Visual Director writes flat `scene_{i}.mp4` files into the output directory.
- Composer writes `final.mp4`, but PRD output package requires `video.mp4`.
- Composer does plain concat/amix and does not use `templates/` yet.
- `agent_states` rows are created but not updated during execution.
- Dashboard and `/jobs` pages do not show useful job observability details: current stage, failed step, agent states, gate results, provider attempts, artifact paths, or FFmpeg errors.
- CLI job commands also do not expose useful job diagnostics. Existing CLI can list jobs and run `test-agent`, but cannot inspect a job, list artifacts, explain failures, or safely retry/resume from a stage.
- Gates are evaluated in places but some hard-fail results are ignored.
- Fish Audio was added, but required provider priority is now ElevenLabs first, Gemini TTS second, Fish Audio third.
- Research brief should be Markdown, not JSON.
- Raw ScrapeCreators and Firecrawl responses should be preserved as real provider response JSON.

## MVP Repair Phase Roadmap

This is one roadmap for the remaining MVP cleanup. Each phase should still be implemented as its own branch/PR for reviewability.

| Phase | Name | MVP Gap Fixed | Expected Branch |
|---|---|---|---|
| 12 | Artifact contracts + debug observability | Makes jobs inspectable, restartable in principle, and auditable. Fixes artifact layout, agent/gate dumps, DB state transitions, debug dashboard, and debug CLI. | `phase/12-artifact-layout-agent-contracts` |
| 13 | Retry/resume + cache reuse | Makes jobs actually restartable at stages without wasting paid API calls. Adds `job-retry`, `job-resume`, config snapshots, and artifact reuse validation. | `phase/13-retry-resume-cache-reuse` — ✅ PR #16 merged |
| 14 | Media/composer correctness | Makes generated videos satisfy MVP output requirements: 9:16, 1080x1920, 20-60s, audio track, valid clips, generated card fallback, thumbnail, metadata stripping. | `phase/14-media-composer-correctness` — ✅ PR #17 merged |
| 15a | Template rendering | Makes the three MVP templates real: template loader (News Card, B-Roll Narration, Rapid Update) + caption overlays + transitions + template thumbnails. Full observability upgrade deferred to Stage 2 (SRS FR-14 is debug-first dashboard/CLI only). | `phase/15a-template-rendering` |

Phases 12-15 are MVP repair work, not Stage 2+. Stage 2+ remains for scale, official APIs, advanced analytics, and broader provider expansion.

## Target Artifact Layout

Given `.env` values like:

```env
ASSETS_CACHE=data/assets/cache
OUTPUT_DIR=data/outputs
```

The target layout for job `125` is:

```text
data/assets/cache/job_125/
├── manifest.json
├── agents/
│   ├── safety/
│   │   ├── input.json
│   │   ├── output.json
│   │   └── summary.md
│   ├── researcher/
│   │   ├── input.json
│   │   ├── research_brief.md
│   │   ├── research_contract.json
│   │   ├── raw/
│   │   │   ├── scrapecreators_response.json
│   │   │   └── firecrawl_response.json
│   │   └── normalized/
│   │       ├── video_sources.json
│   │       ├── context_sources.json
│   │       ├── music_candidates.json
│   │       ├── entities.json
│   │       └── risk_flags.json
│   ├── scriptwriter/
│   │   ├── input.json
│   │   ├── script.json
│   │   ├── caption.txt
│   │   ├── hashtags.json
│   │   └── output.json
│   ├── voice_producer/
│   │   ├── input.json
│   │   ├── output.json
│   │   ├── provider_attempts.json
│   │   └── voices/
│   │       ├── scene_1.mp3
│   │       └── scene_2.mp3
│   ├── visual_director/
│   │   ├── input.json
│   │   ├── scene_plan.json
│   │   ├── output.json
│   │   ├── provenance.json
│   │   ├── scenes/
│   │   │   ├── scene_1.mp4
│   │   │   └── scene_2.mp4
│   │   └── cards/
│   ├── composer/
│   │   ├── input.json
│   │   ├── ffmpeg_command.txt
│   │   ├── ffmpeg_stderr.log
│   │   └── output.json
│   └── reviewer/
│       ├── input.json
│       ├── output.json
│       └── review.md
├── gates/
│   ├── G1_input_preflight.json
│   ├── G2_cost_estimate.json
│   ├── G3_research_cache.json
│   ├── G4_post_research_risk.json
│   ├── G5_source_quality.json
│   ├── G6_creative_memory.json
│   ├── G7_script_validation.json
│   ├── G8_audio_validation.json
│   ├── G9_asset_validation.json
│   └── G10_video_validation.json
└── diagnostics/
    └── tts_provider_probe.json
```

Final output package only:

```text
data/outputs/job_125/
├── video.mp4
├── caption.txt
├── thumbnail.png
└── metadata.json
```

## Researcher File Semantics

| File | Purpose |
|---|---|
| `raw/scrapecreators_response.json` | Raw ScrapeCreators response, as close to the provider response as possible. |
| `raw/firecrawl_response.json` | Raw Firecrawl response, as close to the provider response as possible. |
| `research_brief.md` | Human-readable research brief for audit/review. |
| `research_contract.json` | Normalized machine-readable contract consumed by gates, Scriptwriter, and Visual Director. |
| `normalized/video_sources.json` | Extracted usable video candidates. |
| `normalized/context_sources.json` | Extracted news/context sources. |
| `normalized/music_candidates.json` | Song/music metadata for reference only. MVP does not embed copyrighted TikTok audio. |
| `normalized/entities.json` | Extracted people, locations, events. |
| `normalized/risk_flags.json` | Safety/risk flags for G4. |

`research_contract.json` should point to the other artifacts and include inline normalized summaries:

```json
{
  "topic": "Agnez Mo latest concert",
  "topic_brief_path": "data/assets/cache/job_125/agents/researcher/research_brief.md",
  "raw_scrapecreators_path": "data/assets/cache/job_125/agents/researcher/raw/scrapecreators_response.json",
  "raw_firecrawl_path": "data/assets/cache/job_125/agents/researcher/raw/firecrawl_response.json",
  "video_sources": [],
  "context_sources": [],
  "music_candidates": [],
  "entities": {},
  "risk_flags": [],
  "cache_key": "indonesian_artists:tiktok:id:agnez-mo:2026-05-27",
  "cache_freshness": "fresh"
}
```

## TTS Provider Semantics

Required provider priority:

```text
1. ElevenLabs
2. Google AI Studio Gemini TTS
3. Fish Audio
4. Fail clearly
```

Fallback rules:

```text
If ELEVENLABS_API_KEY is missing → try Gemini TTS.
If ElevenLabs returns non-200/API error → try Gemini TTS.
If GEMINI_API_KEY is missing → try Fish Audio.
If Gemini TTS returns non-200/API error → try Fish Audio.
If FISHAUDIO_API_KEY is missing → fail clearly.
If Fish Audio returns non-200/API error → fail clearly.
```

Provider attempts must be saved to:

```text
data/assets/cache/job_{id}/agents/voice_producer/provider_attempts.json
```

Do not log secrets. Store only provider name, status, HTTP code, sanitized message, latency, and output path if successful.

Gemini TTS diagnostic already proved Google AI Studio TTS can return audio:

```text
model: gemini-2.5-flash-preview-tts
voice: Kore
mime: audio/L16;codec=pcm;rate=24000
```

The implementation must use an environment variable, never a hardcoded key:

```env
GEMINI_API_KEY=
GEMINI_TTS_VOICE_NAME=Kore
```

---

# Phase 12 — Artifact Contracts + Debug Observability

**Phase 12 objective:** Make the pipeline explain itself. After this phase, every job should have a deterministic workspace, every agent/gate should persist inputs/results, the dashboard and CLI should show where a job failed, and final outputs should be separated from intermediate artifacts.

**Phase 12 branch:** `phase/12-artifact-layout-agent-contracts`

**Phase 12 scope:** Tasks 1-18 below.

**Note on retry/resume (Phase 13) and template rendering (Phase 15a):** Phase 12 is read-only observability first — it persists state for safe diagnosis but does not expose write-enabled retry commands (Phase 13) or template-based rendering (Phase 15a). These follow in subsequent phases.

---

## Task 1: ✅ Add Canonical Job Workspace Path Helpers

**Files:**
- Modify: `clipper_agency/core/paths.py`
- Test: `tests/test_paths.py`

**Step 1: Write failing tests**

Add tests for the canonical asset workspace and final output paths:

```python
from pathlib import Path

from clipper_agency.core.paths import (
    agent_dir,
    agent_input_file,
    agent_output_file,
    gate_result_file,
    job_cache_dir,
    job_final_output_dir,
    researcher_brief_file,
    researcher_contract_file,
    voice_scene_file,
    visual_scene_file,
)


def test_job_cache_dir_uses_assets_cache():
    assert job_cache_dir("data/assets/cache", 125) == "data/assets/cache/job_125"


def test_agent_paths_are_under_job_cache():
    assert agent_dir("data/assets/cache", 125, "researcher") == "data/assets/cache/job_125/agents/researcher"
    assert agent_input_file("data/assets/cache", 125, "safety") == "data/assets/cache/job_125/agents/safety/input.json"
    assert agent_output_file("data/assets/cache", 125, "safety") == "data/assets/cache/job_125/agents/safety/output.json"


def test_researcher_specific_paths():
    assert researcher_brief_file("data/assets/cache", 125) == "data/assets/cache/job_125/agents/researcher/research_brief.md"
    assert researcher_contract_file("data/assets/cache", 125) == "data/assets/cache/job_125/agents/researcher/research_contract.json"


def test_voice_and_visual_asset_paths():
    assert voice_scene_file("data/assets/cache", 125, 1) == "data/assets/cache/job_125/agents/voice_producer/voices/scene_1.mp3"
    assert visual_scene_file("data/assets/cache", 125, 1) == "data/assets/cache/job_125/agents/visual_director/scenes/scene_1.mp4"


def test_gate_and_final_output_paths_are_separate():
    assert gate_result_file("data/assets/cache", 125, "G1_input_preflight") == "data/assets/cache/job_125/gates/G1_input_preflight.json"
    assert job_final_output_dir("data/outputs", 125) == "data/outputs/job_125"
```

**Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_paths.py -v
```

Expected: FAIL because new helper functions do not exist.

**Step 3: Implement minimal path helpers**

In `clipper_agency/core/paths.py`, keep existing helpers if needed for compatibility, but add new helpers using `Path` internally and returning strings for current call-site compatibility.

Required helpers:

```python
def job_cache_dir(assets_cache: str | Path, job_id: int) -> str: ...
def ensure_job_cache_dir(assets_cache: str | Path, job_id: int) -> str: ...
def job_final_output_dir(output_dir: str | Path, job_id: int) -> str: ...
def agent_dir(assets_cache: str | Path, job_id: int, agent_name: str) -> str: ...
def ensure_agent_dir(assets_cache: str | Path, job_id: int, agent_name: str) -> str: ...
def agent_input_file(assets_cache: str | Path, job_id: int, agent_name: str) -> str: ...
def agent_output_file(assets_cache: str | Path, job_id: int, agent_name: str) -> str: ...
def gate_result_file(assets_cache: str | Path, job_id: int, gate_name: str) -> str: ...
def researcher_brief_file(assets_cache: str | Path, job_id: int) -> str: ...
def researcher_contract_file(assets_cache: str | Path, job_id: int) -> str: ...
def voice_scene_file(assets_cache: str | Path, job_id: int, scene_id: int) -> str: ...
def visual_scene_file(assets_cache: str | Path, job_id: int, scene_id: int) -> str: ...
```

**Step 4: Verify**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_paths.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/core/paths.py tests/test_paths.py
git commit -m "feat: add canonical job workspace paths"
```

---

## Task 2: ✅ Add JSON/Markdown Artifact Writer Utilities

**Files:**
- Create: `clipper_agency/core/artifacts.py`
- Test: `tests/test_artifacts.py`

**Step 1: Write failing tests**

Test safe JSON and text writes:

```python
import json

from clipper_agency.core.artifacts import write_json, write_text


def test_write_json_creates_parent_directories(tmp_path):
    path = tmp_path / "job_1" / "agents" / "safety" / "output.json"
    write_json(path, {"status": "completed"})
    assert json.loads(path.read_text()) == {"status": "completed"}


def test_write_text_creates_parent_directories(tmp_path):
    path = tmp_path / "job_1" / "agents" / "researcher" / "research_brief.md"
    write_text(path, "# Brief")
    assert path.read_text() == "# Brief"
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_artifacts.py -v
```

Expected: FAIL because `clipper_agency.core.artifacts` does not exist.

**Step 3: Implement utilities**

Create simple helpers:

```python
import json
from pathlib import Path
from typing import Any


def write_json(path: str | Path, data: Any) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return str(target)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text(path: str | Path, content: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)
```

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_artifacts.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/core/artifacts.py tests/test_artifacts.py
git commit -m "feat: add artifact writer helpers"
```

---

## Task 3: ✅ Persist Safety Agent Input and Output

**Files:**
- Modify: `clipper_agency/agents/safety.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_agent_artifacts.py`

**Step 1: Write failing test**

Test that Safety Agent writes input/output when `assets_cache` is passed:

```python
import json

from clipper_agency.agents.safety import SafetyAgent


def test_safety_agent_persists_input_and_output(tmp_path):
    agent = SafetyAgent()
    result = agent.execute(job_id=125, topic="Agnez Mo", assets_cache=str(tmp_path))

    base = tmp_path / "job_125" / "agents" / "safety"
    assert (base / "input.json").exists()
    assert (base / "output.json").exists()
    assert json.loads((base / "input.json").read_text())["topic"] == "Agnez Mo"
    assert json.loads((base / "output.json").read_text())["status"] == result["status"]
```

**Step 2: Run failing test**

```bash
.venv/bin/python3 -m pytest tests/test_agent_artifacts.py::test_safety_agent_persists_input_and_output -v
```

Expected: FAIL because Safety Agent does not persist artifacts.

**Step 3: Implement minimal persistence**

Add optional `assets_cache: str = ""` to `SafetyAgent.execute()`. When provided, write:

```text
agents/safety/input.json
agents/safety/output.json
agents/safety/summary.md
```

Do not change safety behavior.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_agent_artifacts.py::test_safety_agent_persists_input_and_output -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/safety.py clipper_agency/orchestrator/engine.py tests/test_agent_artifacts.py
git commit -m "feat: persist safety agent artifacts"
```

---

## Task 4: ✅ Repair Researcher Artifact Contract

**Files:**
- Modify: `clipper_agency/agents/researcher.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_agents_researcher.py`

**Step 1: Write failing tests**

Test that Researcher writes raw responses, Markdown brief, normalized files, and `research_contract.json` under `assets_cache`.

Use mocks for ScrapeCreators, Firecrawl, and OpenRouter so tests are offline.

Expected files:

```text
job_125/agents/researcher/input.json
job_125/agents/researcher/raw/scrapecreators_response.json
job_125/agents/researcher/raw/firecrawl_response.json
job_125/agents/researcher/research_brief.md
job_125/agents/researcher/research_contract.json
job_125/agents/researcher/normalized/video_sources.json
job_125/agents/researcher/normalized/context_sources.json
job_125/agents/researcher/normalized/music_candidates.json
job_125/agents/researcher/normalized/entities.json
job_125/agents/researcher/normalized/risk_flags.json
job_125/agents/researcher/output.json
```

**Step 2: Run failing test**

```bash
.venv/bin/python3 -m pytest tests/test_agents_researcher.py -v
```

Expected: FAIL because current Researcher writes only `research/*.json` under output dir.

**Step 3: Implement**

Changes:

- Add `assets_cache: str = ""` to `ResearcherAgent.execute()`.
- Use `settings.assets_cache` when orchestrator runs pipeline.
- Save raw provider results before trimming/normalizing.
- Write `research_brief.md` as Markdown text.
- Build `research_contract.json` as the machine-readable downstream contract.
- Keep `output.json` equal to the returned result.

Researcher return shape should still support existing orchestrator keys:

```python
return {
    "status": "completed",
    "research_brief": brief_text,
    "sources": aggregated,
    "research_contract_path": contract_path,
    "research_brief_path": brief_path,
}
```

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_agents_researcher.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/researcher.py clipper_agency/orchestrator/engine.py tests/test_agents_researcher.py
git commit -m "feat: persist researcher contract artifacts"
```

---

## Task 5: ✅ Persist Scriptwriter Artifacts

**Files:**
- Modify: `clipper_agency/agents/scriptwriter.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_agents_scriptwriter.py`

**Step 1: Write failing test**

Mock OpenRouter and assert files exist:

```text
job_125/agents/scriptwriter/input.json
job_125/agents/scriptwriter/script.json
job_125/agents/scriptwriter/caption.txt
job_125/agents/scriptwriter/hashtags.json
job_125/agents/scriptwriter/output.json
```

**Step 2: Run failing test**

```bash
.venv/bin/python3 -m pytest tests/test_agents_scriptwriter.py -v
```

Expected: FAIL because Scriptwriter does not persist artifacts.

**Step 3: Implement**

- Add `assets_cache: str = ""` to `ScriptwriterAgent.execute()`.
- Persist input and parsed output.
- Write caption as plain text.
- Write hashtags as JSON list.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_agents_scriptwriter.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/scriptwriter.py clipper_agency/orchestrator/engine.py tests/test_agents_scriptwriter.py
git commit -m "feat: persist scriptwriter artifacts"
```

---

## Task 6: ✅ Add Google AI Studio Gemini TTS Service

**Files:**
- Create: `clipper_agency/services/gemini_tts.py`
- Modify: `clipper_agency/config/schema.py`
- Modify: `.env.example`
- Test: `tests/test_gemini_tts.py`

**Step 1: Write failing tests**

Test missing key fails clearly and response parsing wraps PCM into WAV:

```python
from unittest.mock import Mock

import pytest

from clipper_agency.services.gemini_tts import GeminiTTSService


def test_gemini_tts_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiTTSService()
```

Add an httpx mocked response test for `audio/L16;codec=pcm;rate=24000`.

**Step 2: Run failing test**

```bash
.venv/bin/python3 -m pytest tests/test_gemini_tts.py -v
```

Expected: FAIL because service does not exist.

**Step 3: Implement**

Implement `GeminiTTSService.generate_voice(text, voice_id, output_path)` using REST:

```text
POST https://generativelanguage.googleapis.com/v1alpha/models/gemini-2.5-flash-preview-tts:generateContent?key=...
```

Payload uses:

```json
{
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": {
      "voiceConfig": {
        "prebuiltVoiceConfig": {"voiceName": "Kore"}
      }
    }
  }
}
```

If response is PCM `audio/L16`, wrap bytes as WAV at the response sample rate.

Config fields:

```python
gemini_api_key: str = ""
gemini_tts_voice_name: str = "Kore"
```

`.env.example` additions:

```env
GEMINI_API_KEY=
GEMINI_TTS_VOICE_NAME=Kore
```

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_gemini_tts.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/services/gemini_tts.py clipper_agency/config/schema.py .env.example tests/test_gemini_tts.py
git commit -m "feat: add gemini tts service"
```

---

## Task 7: ✅ Repair Voice Producer Provider Fallback and Artifact Paths

**Files:**
- Modify: `clipper_agency/agents/voice_producer.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_voice_producer.py`

**Step 1: Write failing tests**

Test provider priority and fallback:

1. ElevenLabs configured and succeeds → uses ElevenLabs.
2. ElevenLabs configured but service raises/non-200 → tries Gemini.
3. Gemini missing/fails → tries Fish Audio.
4. All missing/fail → returns clear failure with attempts.
5. Voice files are written to `agents/voice_producer/voices/scene_{scene_id}.mp3` or `.wav` depending provider output.

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_voice_producer.py -v
```

Expected: FAIL because current Voice Producer prefers Fish Audio and writes flat output paths.

**Step 3: Implement**

- Replace `_detect_provider()` with attempt loop.
- Provider order: `elevenlabs`, `gemini_tts`, `fish_audio`.
- Save `provider_attempts.json`.
- Save `input.json` and `output.json`.
- Use script scene IDs, not enumerate index, for filenames.

Failure output shape:

```json
{
  "status": "failed",
  "error": "All TTS providers failed",
  "attempts": [
    {"provider": "elevenlabs", "status": "missing_key"},
    {"provider": "gemini_tts", "status": "http_403"},
    {"provider": "fish_audio", "status": "http_402"}
  ],
  "audio_files": []
}
```

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_voice_producer.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/voice_producer.py clipper_agency/orchestrator/engine.py tests/test_voice_producer.py
git commit -m "feat: add tts fallback and voice artifacts"
```

---

## Task 8: ✅ Repair Visual Director Artifact Paths and Provenance

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_visual_director.py`

**Step 1: Write failing tests**

Assert files are written under:

```text
job_125/agents/visual_director/input.json
job_125/agents/visual_director/scene_plan.json
job_125/agents/visual_director/output.json
job_125/agents/visual_director/provenance.json
job_125/agents/visual_director/scenes/scene_1.mp4
```

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_visual_director.py -v
```

Expected: FAIL because current Visual Director writes flat scene files to output dir.

**Step 3: Implement**

- Add `assets_cache: str = ""` to `VisualDirectorAgent.execute()`.
- Download scenes into `agents/visual_director/scenes/`.
- Persist scene plan and provenance.
- Keep MVP music behavior as metadata-only; do not download copyrighted TikTok music.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_visual_director.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/visual_director.py clipper_agency/orchestrator/engine.py tests/test_visual_director.py
git commit -m "feat: persist visual director artifacts"
```

---

## Task 9: ✅ Repair Composer Output Package and Diagnostics

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Modify: `clipper_agency/output/packager.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_composer.py`
- Test: `tests/test_output_packager.py`

**Step 1: Write failing tests**

Assert Composer writes:

```text
job_125/agents/composer/input.json
job_125/agents/composer/ffmpeg_command.txt
job_125/agents/composer/ffmpeg_stderr.log
job_125/agents/composer/output.json
```

Assert final package uses:

```text
data/outputs/job_125/video.mp4
data/outputs/job_125/caption.txt
data/outputs/job_125/thumbnail.png
data/outputs/job_125/metadata.json
```

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_composer.py tests/test_output_packager.py -v
```

Expected: FAIL because Composer writes `final.mp4` and diagnostics are not persisted.

**Step 3: Implement**

- Keep composition simple initially; do not solve full template rendering in this task.
- Normalize final output naming to `video.mp4`.
- Persist FFmpeg command and stderr.
- Ensure `OutputPackager` emits PRD-required filenames.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_composer.py tests/test_output_packager.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/composer.py clipper_agency/output/packager.py clipper_agency/orchestrator/engine.py tests/test_composer.py tests/test_output_packager.py
git commit -m "feat: repair composer output package"
```

---

## Task 10: ✅ Persist Gate Results and Enforce Hard-Fails

**Files:**
- Modify: `clipper_agency/orchestrator/engine.py`
- Possibly modify: `clipper_agency/orchestrator/gates.py`
- Test: `tests/test_orchestrator_engine.py`

**Step 1: Write failing tests**

Tests:

1. Each gate writes one JSON file under `job_{id}/gates/`.
2. G5 hard fail stops before Scriptwriter.
3. G8 hard fail stops before Visual Director.
4. G9 hard fail stops before Composer.
5. G10 hard fail stops before Reviewer.

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_orchestrator_engine.py -v
```

Expected: FAIL because not all gate results are persisted/enforced.

**Step 3: Implement**

Add orchestration helper:

```python
def _record_gate(self, assets_cache: str, job_id: int, gate_name: str, result: GateResult) -> None:
    ...
```

Then enforce:

```python
if not result.passed and result.severity == "hard_fail":
    update_job_status(...)
    return failed_response
```

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_orchestrator_engine.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/orchestrator/engine.py clipper_agency/orchestrator/gates.py tests/test_orchestrator_engine.py
git commit -m "feat: persist and enforce gate results"
```

---

## Task 11: ✅ Repair Agent State DB Transitions

**Files:**
- Modify: `clipper_agency/db/queries.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_db_queries.py`
- Test: `tests/test_orchestrator_engine.py`

**Step 1: Write failing tests**

Assert each agent moves:

```text
pending → running → completed
pending → running → failed
```

and stores:

```text
input_data
output_data
started_at
completed_at
error_message
```

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_db_queries.py tests/test_orchestrator_engine.py -v
```

Expected: FAIL because current `agent_states` stay pending.

**Step 3: Implement**

Add DB query helpers if missing:

```python
mark_agent_running(conn, job_id, agent_name, input_data)
mark_agent_completed(conn, job_id, agent_name, output_data)
mark_agent_failed(conn, job_id, agent_name, error_message, output_data=None)
```

Wrap each `_run_*` call in orchestrator state updates.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_db_queries.py tests/test_orchestrator_engine.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/db/queries.py clipper_agency/orchestrator/engine.py tests/test_db_queries.py tests/test_orchestrator_engine.py
git commit -m "feat: track agent state transitions"
```

---

## Task 12: ✅ Add Job Manifest

**Files:**
- Create or modify: `clipper_agency/core/manifest.py`
- Modify: `clipper_agency/orchestrator/engine.py`
- Test: `tests/test_manifest.py`

**Step 1: Write failing tests**

Assert `manifest.json` exists and includes:

```json
{
  "job_id": 125,
  "topic": "Agnez Mo latest concert",
  "assets_cache": "data/assets/cache",
  "output_dir": "data/outputs",
  "agents": {},
  "gates": {},
  "final_outputs": {}
}
```

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_manifest.py -v
```

Expected: FAIL because manifest does not exist.

**Step 3: Implement**

Write manifest at pipeline start and update it after each agent/gate/final package.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_manifest.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/core/manifest.py clipper_agency/orchestrator/engine.py tests/test_manifest.py
git commit -m "feat: add job artifact manifest"
```

---

## Task 13: ✅ Update Core Requirements Documents

**Files:**
- Modify: `docs/PRD.md`
- Modify: `docs/SRS.md`
- Modify: `docs/technical_design.md`
- Modify: `docs/requirements_traceability.md`
- Modify: `docs/design/evolution_plan.md`

**Step 1: Update PRD**

Required changes:

- Version bump to next version.
- Update voice scope to include `ElevenLabs → Google AI Studio Gemini TTS → Fish Audio → fail clearly`.
- Clarify final output package in `OUTPUT_DIR/job_{id}`.
- Add requirement that intermediate agent/gate artifacts are persisted under `ASSETS_CACHE/job_{id}` for audit/retry/analysis.

**Step 2: Update SRS**

Required changes:

- FR-06: TTS provider fallback order.
- FR-14/NFR-07/NFR-08: agent state + artifact persistence.
- FR-15: asset cache layout.
- SRS §4 external services: add Google AI Studio Gemini TTS.
- SRS §6 retention: agent/gate artifacts, diagnostics, raw provider payloads.

**Step 3: Update technical design**

Required changes:

- Architecture section: `ASSETS_CACHE/job_{id}` workspace + `OUTPUT_DIR/job_{id}` package.
- Agent contracts table: include persisted artifact files.
- Researcher output: `research_brief.md`, raw responses, `research_contract.json`.
- Voice provider auto-detection/fallback table.
- Asset caching section: job workspace plus optional URL-hash global cache.
- Background music policy remains: MVP does not embed copyrighted TikTok audio.

**Step 4: Update requirements traceability**

Required changes:

- Add facts for Gemini TTS and job workspace artifact persistence.
- Update PR-25/FR-06 mapping.
- Add edge cases for provider fallback and failed provider chain.
- Update adversarial checklist to include artifact persistence and raw/normalized research split.

**Step 5: Update evolution plan**

Add the future full observability dashboard to `docs/design/evolution_plan.md` under Stage 2, keeping it out of the current Phase 12 scope:

```text
Full observability dashboard:
- polished pipeline timeline with visual status icons
- retry-from-step buttons
- artifact browser with download buttons
- video/audio preview
- provider latency and cost charts
- gate decision explanations
- dashboard notifications
- approval workflow integration
- filtered job history
- searchable logs
```

The current phase only implements the debug-first internal dashboard in Task 14.

**Step 6: Verify docs references**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_config.py tests/test_config_loader.py -v
```

Expected: PASS. No docs-specific test exists yet; manually inspect cross-doc consistency.

**Step 7: Commit**

```bash
git add docs/PRD.md docs/SRS.md docs/technical_design.md docs/requirements_traceability.md docs/design/evolution_plan.md
git commit -m "docs: update artifact workspace and tts fallback requirements"
```

---

## Task 14: ✅ Add Debug-First Job Observability Dashboard

**Files:**
- Modify: `clipper_agency/dashboard/app.py`
- Modify: `clipper_agency/dashboard/templates/jobs.html`
- Create: `clipper_agency/dashboard/templates/job_detail.html`
- Test: `tests/test_dashboard.py`

**Step 1: Write failing tests**

Add tests for read-only debug endpoints/pages:

1. `/jobs` includes current stage/failure summary fields when job data exists.
2. `/jobs/<job_id>` renders a debug detail page for an existing job.
3. `/api/jobs/<job_id>/debug` returns job row, agent states, artifact manifest if present, gate artifact list if present, and agent artifact list if present.
4. Missing job returns 404.
5. Binary artifacts are not read inline; only path, size, and type metadata are returned.

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_dashboard.py -v
```

Expected: FAIL because no job detail page or debug API exists.

**Step 3: Implement debug-first dashboard**

Keep the UI intentionally simple and read-only. Do not add retry buttons in this phase.

Add routes:

```text
GET /jobs/<job_id>
GET /api/jobs/<job_id>/debug
```

The debug API should combine:

```text
SQLite:
- jobs row
- agent_states rows
- job_outputs row if present

Artifact workspace:
- data/assets/cache/job_{id}/manifest.json
- data/assets/cache/job_{id}/agents/*/input.json
- data/assets/cache/job_{id}/agents/*/output.json
- data/assets/cache/job_{id}/agents/researcher/research_brief.md
- data/assets/cache/job_{id}/agents/voice_producer/provider_attempts.json
- data/assets/cache/job_{id}/agents/composer/ffmpeg_stderr.log
- data/assets/cache/job_{id}/gates/*.json
```

`/jobs/<job_id>` should show:

```text
Overview:
- job id, topic, niche, status
- error_message
- created_at, updated_at, completed_at

Pipeline Debug:
- agent states table
- gate results list
- artifact manifest link/status

Useful previews:
- research_brief.md first 2-4 KB
- provider_attempts.json pretty printed
- ffmpeg_stderr.log first 4 KB

Artifact inventory:
- path
- file type
- size
- last modified
```

Security constraints:

- Never display `.env` files.
- Never display known secret-like keys.
- Do not inline binary files (`.mp3`, `.wav`, `.mp4`, `.png`). Show metadata only.
- Keep artifact reads inside configured `ASSETS_CACHE/job_{id}` and `OUTPUT_DIR/job_{id}` roots.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_dashboard.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/dashboard/app.py clipper_agency/dashboard/templates/jobs.html clipper_agency/dashboard/templates/job_detail.html tests/test_dashboard.py
git commit -m "feat: add debug-first job observability dashboard"
```

---

## Task 15: ✅ Add Debug-First CLI Job Inspection Commands

**Files:**
- Modify: `clipper_agency/__main__.py`
- Possibly create: `clipper_agency/core/job_debug.py`
- Test: `tests/test_cli.py` or create `tests/test_cli_job_debug.py`

**Step 1: Write failing tests**

Add CLI tests for read-only job diagnostics:

1. `jobs` includes status, updated time, and compact failure summary.
2. `job-show <job_id>` prints one job's DB status, topic, timestamps, and error message.
3. `job-debug <job_id>` prints job row, agent states, gate result summary, and key artifact paths.
4. `job-artifacts <job_id>` lists artifact files under `ASSETS_CACHE/job_{id}` and final files under `OUTPUT_DIR/job_{id}`.
5. Missing job returns non-zero exit and a clear message.
6. Binary artifacts are listed with size/path only; not printed inline.

**Step 2: Run failing tests**

```bash
.venv/bin/python3 -m pytest tests/test_cli.py tests/test_cli_job_debug.py -v
```

Expected: FAIL because these commands do not exist yet.

**Step 3: Implement read-only commands**

Add commands:

```text
python3 -m clipper_agency job-show 125
python3 -m clipper_agency job-debug 125
python3 -m clipper_agency job-artifacts 125
```

Command behavior:

```text
job-show:
- DB job row summary
- status, error_message, created_at, updated_at, completed_at

job-debug:
- everything from job-show
- agent_states table
- gate result files if present
- manifest path/status
- useful artifact previews: research_brief.md, provider_attempts.json, ffmpeg_stderr.log

job-artifacts:
- inventory of files under configured ASSETS_CACHE/job_{id}
- inventory of files under configured OUTPUT_DIR/job_{id}
- path, type, size, last modified
```

Do not add retry/resume commands yet. This phase is read-only for CLI diagnostics.

Security constraints:

- Never print `.env` files.
- Never print secret-like values.
- Do not inline binary files (`.mp3`, `.wav`, `.mp4`, `.png`).
- Keep file traversal inside configured `ASSETS_CACHE/job_{id}` and `OUTPUT_DIR/job_{id}`.

**Step 4: Verify**

```bash
.venv/bin/python3 -m pytest tests/test_cli.py tests/test_cli_job_debug.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/__main__.py clipper_agency/core/job_debug.py tests/test_cli.py tests/test_cli_job_debug.py
git commit -m "feat: add cli job debug commands"
```

---

## Task 16: Document Retry/Resume as Follow-Up Scope ✅

**Files:**
- Modify: `docs/design/evolution_plan.md`
- Modify: `docs/technical_design.md`

**Step 1: Document what is intentionally not implemented in Phase 12**

Add a note that Phase 12 adds read-only observability first. Write-enabled retry/resume requires reliable persisted state and artifact contracts.

Future CLI commands:

```text
python3 -m clipper_agency job-retry 125 --from composer
python3 -m clipper_agency job-resume 125
python3 -m clipper_agency job-retry 125 --from voice_producer --use-cache
```

Prerequisites before retry/resume:

```text
- agent_states accurately transitions pending/running/completed/failed
- gate results are persisted and enforce hard-fail stops
- job config snapshot is stored and reused
- agent input/output artifacts are persisted
- paid provider calls can be skipped when valid cached artifacts exist
- retry policy remains human-triggered only
```

**Step 2: Commit**

```bash
git add docs/design/evolution_plan.md docs/technical_design.md
git commit -m "docs: document job retry and resume follow-up"
```

---

## Task 17: Add ADR for Job Workspace Artifact Contract ✅

**Files:**
- Create: `docs/adr/0012-use-assets-cache-job-workspace.md`

**Step 1: Create ADR**

Use existing ADR format: Context → Decision → Alternatives Considered → Consequences.

Decision:

```text
Intermediate artifacts, raw provider responses, agent inputs/outputs, gate results, diagnostics, and failed-job debug material live under ASSETS_CACHE/job_{id}. Final customer-ready packages live under OUTPUT_DIR/job_{id}.
```

**Step 2: Verify ADR numbering**

Existing ADRs are `0001`-`0011`; this must be `0012`.

**Step 3: Commit**

```bash
git add docs/adr/0012-use-assets-cache-job-workspace.md
git commit -m "docs: add adr for job artifact workspace"
```

---

## Task 18: Full Verification ✅

**Files:**
- No direct file edits unless failures reveal approved fixes are needed.

**Step 1: Run targeted tests**

```bash
.venv/bin/python3 -m pytest \
  tests/test_paths.py \
  tests/test_artifacts.py \
  tests/test_agents_researcher.py \
  tests/test_agents_scriptwriter.py \
  tests/test_voice_producer.py \
  tests/test_visual_director.py \
  tests/test_composer.py \
  tests/test_output_packager.py \
  tests/test_orchestrator_engine.py \
  tests/test_dashboard.py \
  tests/test_cli.py \
  tests/test_cli_job_debug.py \
  -v
```

Expected: PASS.

**Step 2: Run offline suite**

```bash
.venv/bin/python3 -m pytest -m "not external" -v
```

Expected: PASS except any already-documented pre-existing external/FFmpeg-dependent smoke test issues.

**Step 3: Run diagnostic test-agent commands only if keys are configured**

Do not hardcode keys. If `GEMINI_API_KEY` is configured, run:

```bash
.venv/bin/python3 -m clipper_agency test-agent voice --script '[{"scene":1,"text":"Tes suara singkat.","duration":3}]' --output-dir data/test_outputs
```

Expected: creates voice artifact under job workspace once `test-agent` is updated to pass `assets_cache`.

**Step 4: Inspect git diff**

```bash
git status --short
git diff --stat
```

Expected: only intended files changed.

**Step 5: Commit verification adjustments if needed**

Only after approval if new fixes are needed.

---

## Out of Scope for This Phase

- Full template rendering with animations beyond preserving template config hooks.
- Automatic copyrighted TikTok music download/embed.
- Stage 2 providers such as Serper, Cobalt, instaloader, or queue workers.
- Multi-account scheduling.
- Dashboard UI redesign for artifact browsing, unless required by tests.

## Acceptance Criteria

- `ASSETS_CACHE` is used for all intermediate artifacts.
- `OUTPUT_DIR` contains only final package files.
- Every agent persists `input.json` and `output.json`.
- Every gate persists its result JSON.
- Research brief is Markdown.
- Raw ScrapeCreators and Firecrawl responses are preserved as JSON.
- `research_contract.json` is the normalized machine contract.
- Voice provider fallback order is ElevenLabs → Gemini TTS → Fish Audio → fail clearly.
- Provider attempts are persisted without secrets.
- Agent DB states transition out of `pending` and include timestamps.
- Hard-fail gates stop downstream execution.
- Core docs and traceability matrix are updated.
- `docs/design/evolution_plan.md` captures the future full observability dashboard.
- Debug-first `/jobs/<id>` dashboard shows job state, agent states, gates, artifact inventory, provider attempts, and FFmpeg errors.
- Debug-first CLI commands can show one job, debug a job, and list artifacts without rerunning the pipeline.
- Retry/resume commands are documented as follow-up scope and are not implemented until persisted state is reliable.
- ADR 0012 records the workspace decision.
- Offline tests pass.

---

# Phase 13 — Retry/Resume + Cache Reuse

**Status:** ✅ Complete. Merged `497aa3c` on master via PR #16 (11 commits including SonarCloud fixes + CSRF protection).
- **Batch 1** (merged to master): CLI `job-retry`/`job-resume` commands, config snapshot persistence, engine `run_pipeline_from`.
- **Batch 2** (`94345fc`): Dashboard POST retry/resume routes with basic UI controls.
- **Batch 3** (`5359499`): `validate_agent_cache` wired into engine — cached artifacts are validated before reuse; invalid cache falls through to re-running the agent.

**Phase 13 objective:** Make failed/paused jobs restartable without blindly rerunning earlier successful steps or wasting provider credits.

**Branch:** `phase/13-retry-resume-cache-reuse`

## Phase 13 Required Capabilities

### 1. Job config snapshot reuse

Persist and reuse the job's config snapshot for all retries/resumes:

```text
jobs.config_snapshot
data/assets/cache/job_{id}/manifest.json
```

Rules:

- Retry/resume must use the original config snapshot by default.
- User may explicitly request a new config snapshot only with an override flag.
- Global `.env` or niche changes must not silently alter a running/retried job.

### 2. Retry from a specific agent or gate

Add write-enabled CLI commands:

```bash
.venv/bin/python3 -m clipper_agency job-retry 125 --from composer
.venv/bin/python3 -m clipper_agency job-retry 125 --from voice_producer --use-cache
```

Minimum retry targets:

```text
safety
researcher
scriptwriter
voice_producer
visual_director
composer
reviewer
```

Retry behavior:

- Preserve earlier successful artifacts unless invalidated.
- Mark target and downstream agent states as pending/rerun-required.
- Never auto-retry without explicit user command.
- Respect retry limits from PRD/SRS.

### 3. Resume failed/paused jobs

Add:

```bash
.venv/bin/python3 -m clipper_agency job-resume 125
```

Resume behavior:

- If failed, resume from failed agent/gate by default.
- If paused, resume from current paused stage.
- Re-check stale research/cache freshness gates before resuming.
- Revalidate required artifacts before skipping paid providers.

### 4. Cache/artifact reuse validation

Before reusing an artifact, validate it:

| Artifact | Validation |
|---|---|
| `research_contract.json` | Exists, valid JSON, has `topic`, `video_sources`, `context_sources`, `cache_key`, `cache_freshness`. |
| `research_brief.md` | Exists, non-empty, linked by contract. |
| `script.json` | Exists, valid JSON, contains scenes/text/caption. |
| Voice files | Exist, non-zero, valid audio duration. |
| Scene files | Exist, non-zero, valid video, 1-5s clip after trimming. |
| `video.mp4` | Exists, non-zero, 9:16, 1080x1920, audio track present. |

### 5. Dashboard retry controls — basic version

Add minimal write-enabled dashboard controls after CLI retry/resume works:

```text
Retry from failed step
Retry from selected agent
Resume job
```

Keep the UI basic; full polished retry UX belongs to Phase 15.

## Phase 13 Acceptance Criteria

- `job-retry` can rerun a failed step without rerunning earlier successful paid steps.
- `job-resume` can continue a failed/paused job from the correct stage.
- Cached artifacts are reused only after deterministic validation.
- Retry/resume updates `agent_states`, gate results, manifest, and audit log.
- Retry remains human-triggered only.
- Provider calls are not repeated when valid cached artifacts exist.

---

# Phase 14 — Media and Composer Correctness

**Phase 14 objective:** Make generated videos satisfy the MVP media requirements reliably.

**Expected branch:** `phase/14-media-composer-correctness`

## Phase 14 Required Capabilities

### 1. FFmpeg preflight

Add a deterministic preflight check before composition:

```text
ffmpeg exists
ffprobe exists
libx264 available
aac audio support available
mp3 decode support available
```

If missing, fail before expensive render work with a clear message.

### 2. Scene normalization

Every visual scene must be normalized before concat:

```text
resolution: 1080x1920
aspect: 9:16
codec: h264
pixel format: yuv420p
duration: 1-5 seconds per clip
audio: stripped from source clips unless intentionally retained for safe stock media
metadata: stripped
```

This directly fixes failures like mixed dimensions between `scene_4.mp4` and `scene_6.mp4`.

### 3. Clip safeguards

Implement and test:

- max clip duration 5s
- min clip duration 1s
- reject corrupt/zero-byte files
- transform clips through re-encode/crop/scale/metadata stripping
- record provenance for every clip

### 4. Generated card fallback

If there are too few valid clips, generate 1080x1920 PNG cards:

```text
headline card
fact card
context card
CTA card
```

Cards should use niche/template colors and be usable as full-screen scenes.

### 5. Audio mixing correctness

Composer must:

- align voice files to scenes
- produce a final audio track
- optionally mix safe stock background music if configured
- default to no background music
- never embed copyrighted TikTok audio automatically

### 6. Output package correctness

Final output must be:

```text
data/outputs/job_{id}/video.mp4
data/outputs/job_{id}/caption.txt
data/outputs/job_{id}/thumbnail.png
data/outputs/job_{id}/metadata.json
```

Validation:

```text
video.mp4 exists
video.mp4 size > 1KB
duration 20-60s
resolution 1080x1920
has audio track
codec h264/aac
metadata stripped
```

### 7. Thumbnail generation

Generate template-based `thumbnail.png` at 1080x1920.

## Phase 14 Acceptance Criteria

- Composer no longer fails on mixed source dimensions.
- Valid source clips are normalized to 1080x1920 before concat.
- Invalid/too-short clips are rejected or replaced with generated cards.
- Final `video.mp4` passes G10 deterministic validation.
- `thumbnail.png`, `caption.txt`, and `metadata.json` are generated consistently.
- FFmpeg stderr and command logs are persisted for failed renders.

**Status:** ✅ Complete. Merged `1f36918` on master via PR #17 (19 commits: FFmpeg preflight, media probing, scene validation/normalization, clip provenance, generated card fallback, card-to-video, composer assembly, output packaging validation, deterministic G10, fixed-contract packager with S6549 safe path sandbox).

---

# Phase 15a — Template Rendering ✅ COMPLETE

**Phase 15a objective:** Complete the MVP creative/rendering promise: real template-driven video rendering with caption overlays, transitions, and template-specific thumbnails.

**Branches:** `phase/15a-template-foundation` (PR 1), `phase/15a-template-adapters` (PR 2), `phase/15a-composer-template-integration` (PR 3)

**Related:** Full observability dashboard and CLI parity (caps 6-8) moved to `docs/design/evolution_plan.md` Stage 2 — they were recognized as scope creep beyond the MVP debug-first requirement (SRS FR-14).

## Phase 15a Required Capabilities

### 1. Template loader

Load and validate:

```text
templates/news_card.yaml
templates/b_roll_narration.yaml
templates/rapid_update.yaml
```

Template validation should check:

- layout positions
- fonts/colors
- caption style
- scene durations
- transition names
- animation presets
- thumbnail config

### 2. News Card renderer

Implement a renderer for quick updates:

```text
headline card
supporting image/video
key facts
caption overlays
template thumbnail
```

Best for: short breaking update stories.

### 3. B-Roll Narration renderer

Implement a renderer for context-rich stories:

```text
voiceover-led pacing
b-roll clips/cards
dynamic captions
lower-thirds/source labels
template thumbnail
```

Best for: explanation/context clips.

### 4. Rapid Update renderer

Implement a renderer for fast cuts:

```text
short clip/card sequence
punchy captions
quick transitions
headline overlays
template thumbnail
```

Best for: trending gossip/viral updates.

### 5. Captions, overlays, and animations

Add MVP-safe visual effects:

- burned-in captions
- headline overlays
- lower-third source labels
- simple zoom/pan on cards
- simple fade/cut transitions
- no heavy GPU dependencies

## Phase 15a Acceptance Criteria

- All three `templates/*.yaml` files are actually loaded and used. ✅
- Final videos include template-specific captions/overlays/thumbnail treatment. ✅
- Observability stays at the Phase 12 debug-first level — retry-from-step controls and preview browsers are Stage 2 scope. ✅
- CLI observability stays at the Phase 13 debug commands — `job-timeline`, `job-open-artifact`, and `job-export-debug-bundle` are Stage 2 scope. ✅

### Phase 15a Implementation Summary

**Rendering package:** `clipper_agency/rendering/` — hybrid YAML + FFmpeg + Pillow template system.

| Component | File | Purpose |
|-----------|------|---------|
| Template loader | `templates.py` | Loads and validates `templates/*.yaml` with strict schema checks |
| Render contracts | `contracts.py` | Typed dataclasses for render plans, scenes, captions, overlays, transitions |
| Shared primitives | `primitives.py` | Reusable FFmpeg filter chains: captions, overlays, lower-thirds, fade/crossfade |
| Thumbnails | `thumbnails.py` | Pillow-generated template-aware cards and thumbnails at 1080×1920 |
| Render engine | `engine.py` | Standalone FFmpeg orchestrator producing video from render plans |
| News Card adapter | `renderers/news_card.py` | Headline + key facts + caption overlays |
| B-Roll Narration adapter | `renderers/b_roll_narration.py` | Voiceover-led pacing with dynamic captions and lower-thirds |
| Rapid Update adapter | `renderers/rapid_update.py` | Short clip sequences with punchy captions and quick transitions |

**Composer integration:** `ComposerAgent._render_via_template()` early return in `clipper_agency/agents/composer.py`. When a template is configured, Composer delegates to the rendering engine; when no template is set, legacy Composer behavior is preserved.

**Why hybrid YAML + FFmpeg + Pillow:** Offline-testable without external APIs, low dependency risk (both already in the stack), deterministic output for tests, and no new rendering framework introduced.
