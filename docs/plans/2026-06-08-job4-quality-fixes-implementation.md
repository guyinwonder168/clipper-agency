# Job #4 Quality Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent Job #4-style failures by repairing Visual Director asset selection, making Composer duration-safe, adding programmatic review gates, and improving diagnostics.

**Architecture:** Keep the audio-first pipeline. Scriptwriter target duration remains soft guidance, Voice Producer actual audio duration becomes downstream authority, Visual Director creates/repairs a valid visual plan, Composer renders visuals to cover audio, and Reviewer enforces deterministic quality gates.

**Tech Stack:** Python 3.11+, pytest, FFmpeg/ffprobe helpers, SQLite-backed orchestrator, OpenRouter LLM client, configured TTS providers.

---

## Batch Parallel Execution Plan

This plan is structured for batch execution with independent tasks running in parallel where safe.

### Batch 1A — Independent failure characterization and tests

Can run in parallel:

- Task 1: Visual Plan Resolver tests.
- Task 2: Composer duration-safety tests.
- Task 3: Reviewer hard-gate tests.
- Task 4: Universal model-call diagnostics tests.
- Task 5: Segment Producer richer asset portfolio tests.

Gate before Batch 1B: all Batch 1A tests must fail for the expected reason.

### Batch 1B — Cross-cutting failing tests

Sequential after Batch 1A:

- Task 6: Intro card contract tests.

Task 6 touches both Visual Director and Composer test files, so it should not run in parallel with Task 1 or Task 2.

Gate before Batch 2A: Task 6 tests must fail for the expected reason.

### Batch 2A — Independent implementations

Can run in parallel after Batch 1A/1B:

- Task 7: Implement Visual Plan Resolver.
- Task 8: Implement Composer duration-safe render adjustments.
- Task 9: Implement Reviewer hard gates.
- Task 10: Implement universal model-call diagnostics plumbing.
- Task 11: Improve Segment Producer asset portfolio/ranking.

Gate before Batch 2B: each Batch 2A task's targeted tests pass in isolation.

### Batch 2B — Cross-cutting implementation

Sequential after Batch 2A:

- Task 12: Implement explicit intro card contract.

Task 12 touches both Visual Director and Composer implementation files, so it should not run in parallel with Task 7 or Task 8.

Gate before Batch 3: Task 12 targeted tests pass.

### Batch 3 — Integration and orchestration

Sequential:

- Task 13: Wire duration/config semantics through orchestrator and docs.
- Task 14: Add Job #4 regression fixture or focused integration test.
- Task 15: Run offline test suite and fix only approved failures.

Gate before completion: offline tests pass and artifacts show expected diagnostics.

---

## Task 1: Visual Plan Resolver Failing Tests

**Files:**
- Modify: `tests/agents/test_visual_director_beat_driven.py`
- Reference: `clipper_agency/agents/visual_director.py`

**Step 1: Write failing tests**

Add tests covering:

```python
def test_resolver_replaces_duplicate_url_with_alternate_candidate():
    # beat 1 uses primary URL; beat 2 has same primary plus alternate URL.
    # Expected: beat 2 action uses alternate URL, not broken tiktok_clip.

def test_resolver_recovers_missing_source_url_from_same_beat_candidates():
    # LLM action is {"type": "tiktok_clip"}; beat has candidate URL.
    # Expected: source_url is restored.

def test_resolver_normalizes_video_candidate_type_to_tiktok_clip():
    # Segment Producer candidate type is "video" with TikTok URL.
    # Expected: resolved action is type "tiktok_clip" with source_url.

def test_resolver_never_leaves_broken_tiktok_action():
    # No usable candidate exists.
    # Expected: action becomes explicit text_card fallback with reason.
```

**Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py -k "resolver or broken_tiktok" -v
```

Expected: FAIL because resolver does not exist or current dedup deletes URLs.

**Step 3: Commit tests only**

Do not commit if running as subtask in a shared branch unless orchestrator instructs. Otherwise:

```bash
git add tests/agents/test_visual_director_beat_driven.py
git commit -m "test: capture visual plan resolver failures"
```

---

## Task 2: Composer Duration-Safety Failing Tests

**Files:**
- Modify: `tests/test_composer.py`
- Reference: `clipper_agency/agents/composer.py`

**Step 1: Write failing tests**

Add tests for:

```python
def test_audio_first_render_never_returns_video_shorter_than_voiceover():
    # Mock/provide assets totaling less than voiceover duration after crossfade.
    # Expected: composer extends visual timeline or fails before mux.

def test_crossfade_overlap_is_compensated_when_matching_audio_duration():
    # Scene sum equals audio duration but crossfade overlap makes output short.
    # Expected: output duration remains >= audio duration.
```

**Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_composer.py -k "duration or crossfade or voiceover" -v
```

Expected: FAIL because current Composer can output video shorter than audio.

---

## Task 3: Reviewer Hard-Gate Failing Tests

**Files:**
- Modify: `tests/test_agents_reviewer.py`
- Reference: `clipper_agency/agents/reviewer.py`
- Reference: `clipper_agency/orchestrator/engine.py:604-613`

**Step 1: Write failing tests**

Add tests for:

```python
def test_reviewer_fails_when_video_shorter_than_audio():
    result = reviewer.execute(audio_duration_sec=23.25, visual_duration_sec=21.21, ...)
    assert result["status"] == "failed" or result["verdict"] == "fail"

def test_reviewer_fails_broken_tiktok_clip_action_when_visual_plan_provided():
    # Provide visual diagnostics/scene plan with {"type": "tiktok_clip"} and no source_url.
    # Expected: fail.
```

**Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_agents_reviewer.py -k "duration or tiktok or hard_gate" -v
```

Expected: FAIL because current Reviewer passes Job #4-style metadata.

---

## Task 4: Universal Model-Call Diagnostics Failing Tests

**Files:**
- Create: `tests/test_model_call_diagnostics.py`
- Modify: `clipper_agency/llm/client.py`
- Modify: `clipper_agency/services/elevenlabs.py`
- Modify: `clipper_agency/services/gemini_tts.py`
- Modify: `clipper_agency/services/fish_audio.py`

**Step 1: Write failing tests**

Add tests for a shared diagnostics writer/helper:

```python
def test_llm_client_writes_model_call_diagnostic_when_context_provided(tmp_path):
    # Mock OpenRouter response and usage.
    # Expected JSON contains provider, model, input, raw_response, parsed_output/status, usage, latency.

def test_tts_provider_writes_model_call_diagnostic_when_context_provided(tmp_path):
    # Mock TTS provider result.
    # Expected JSON contains provider, text length, duration, retry count/status.
```

**Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_model_call_diagnostics.py -v
```

Expected: FAIL because shared diagnostics helper/context does not exist.

---

## Task 5: Segment Producer Asset Portfolio Failing Tests

**Files:**
- Modify: `tests/test_agents_segment_producer.py`
- Reference: `clipper_agency/agents/segment_producer.py`

**Step 1: Write failing tests**

Add tests for:

```python
def test_asset_candidates_are_ranked_with_relevance_metadata():
    # Input mixed TikTok/news sources.
    # Expected candidates include relevance_score, role/provenance, source metadata.

def test_scrapecreators_no_watermark_url_becomes_download_url():
    # Input ScrapeCreators item with url and download_no_watermark_addr.
    # Expected candidate keeps canonical url and sets download_url to no-watermark URL.

def test_scrapecreators_missing_no_watermark_uses_existing_download_url_fallback():
    # Input ScrapeCreators item without download_no_watermark_addr.
    # Expected candidate download_url uses current fallback logic.

def test_important_beat_gets_video_image_and_text_fallback_candidates():
    # Beat with named subject and matching sources.
    # Expected: at least two video candidates where available, one backup image/screenshot, fallback.
```

**Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py -k "asset_candidates or relevance" -v
```

Expected: FAIL or partial fail until richer portfolio metadata is implemented.

---

## Task 6: Intro Card Contract Failing Tests

**Files:**
- Modify: `tests/agents/test_visual_director_beat_driven.py`
- Modify: `tests/test_composer.py`

**Step 1: Write failing tests**

Add tests for:

```python
def test_visual_director_adds_intro_card_scene_zero_for_roundup():
    # Given three_story_roundup beat-driven plan.
    # Expected first scene has role intro_card and target_duration 3.0.

def test_composer_renders_intro_card_scene_as_part_of_timeline():
    # Given scene 0 intro card asset.
    # Expected duration contribution is included and scene order starts with card.
```

**Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py tests/test_composer.py -k "intro_card" -v
```

Expected: FAIL because intro card is not explicit today.

---

## Task 7: Implement Visual Plan Resolver

**Files:**
- Modify: `clipper_agency/agents/visual_director.py:213-217`
- Modify: `clipper_agency/agents/visual_director.py:411-558`

**Step 1: Add resolver function**

Implement a deterministic resolver after `_normalize_beat_plan()` and before `_execute_beat_plan()`.

Target call flow:

```python
plan = self._normalize_beat_plan(plan, allowed_beat_ids)
plan = self._resolve_beat_plan_assets(plan, parsed_beats, do_not_use)
assets = self._execute_beat_plan(plan, scenes_dir)
```

**Step 2: Resolver behavior**

Rules:

```text
- Normalize candidate types: video/tiktok -> tiktok_clip.
- If action is tiktok_clip and source_url is missing, choose first usable candidate for same beat.
- If action source_url is duplicate, choose next usable candidate.
- If no unused candidate but same URL is highly relevant, allow reuse and add reuse_reason.
- If no candidate works, replace action with explicit text_card fallback and reason.
```

**Step 3: Run targeted tests**

Run:

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py -k "resolver or duplicate or broken_tiktok" -v
```

Expected: PASS.

---

## Task 8: Implement Composer Duration-Safe Render

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Reference: `clipper_agency/core/media_probe.py`

**Step 1: Identify audio-first render path**

Work in `_run_audio_first_render()` and helper functions that build FFmpeg filter chains.

**Step 2: Add duration guard**

Before final success return, probe final rendered video duration and compare with voiceover duration. Minimal implementation may extend the last visual/card before final mux or fail explicitly if output is too short.

Preferred two-pass design:

```text
render visual-only timeline -> probe duration -> repair if short -> mux audio
```

If a full two-pass refactor is too large for first patch, implement the smallest safe guard that prevents truncation and logs the repair.

**Step 3: Run targeted tests**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_composer.py -k "duration or crossfade or voiceover" -v
```

Expected: PASS.

---

## Task 9: Implement Reviewer Programmatic Hard Gates

**Files:**
- Modify: `clipper_agency/agents/reviewer.py`
- Modify: `clipper_agency/orchestrator/engine.py:604-613` if extra metadata must be passed.

**Step 1: Add deterministic checks before LLM review**

Implement checks for:

```text
video_duration >= audio_duration - tolerance
scene_count > 0 when scene metadata is available
no broken tiktok_clip action when scene plan metadata is available
```

**Step 2: Make hard failures visible**

Return a failed status/verdict with clear reasons. Do not package a video that fails hard gates.

**Step 3: Run targeted tests**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_agents_reviewer.py -k "duration or hard_gate or tiktok" -v
```

Expected: PASS.

---

## Task 10: Implement Universal Model-Call Diagnostics

**Files:**
- Create: `clipper_agency/core/model_diagnostics.py`
- Modify: `clipper_agency/llm/client.py`
- Modify: `clipper_agency/services/elevenlabs.py`
- Modify: `clipper_agency/services/gemini_tts.py`
- Modify: `clipper_agency/services/fish_audio.py`
- Modify agents only if they must pass diagnostic context.

**Step 1: Add helper**

Create a small helper that writes JSON to:

```text
data/assets/cache/job_{job_id}/agents/{agent_name}/model_calls/{timestamp}_{purpose}.json
```

**Step 2: Add optional context**

Avoid large invasive changes. Accept optional diagnostic context parameters. If absent, preserve current behavior.

**Step 3: Capture minimum fields**

Fields:

```text
agent, purpose, provider, model, input_payload, raw_response, parsed_output/status,
usage, estimated_cost_usd when available, latency_ms, retry_count, status, error
```

**Step 4: Run targeted tests**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_model_call_diagnostics.py -v
```

Expected: PASS.

---

## Task 11: Improve Segment Producer Asset Portfolio

**Files:**
- Modify: `clipper_agency/agents/segment_producer.py`
- Modify: `clipper_agency/config/schema.py` only if schema needs new optional fields.

**Step 1: Normalize and enrich candidates**

Ensure candidates include optional metadata already available in `AssetCandidate`:

```text
source, relevance_score, provenance, related_beat_id, story_id, license_status
```

For ScrapeCreators TikTok keyword search results, preserve canonical URL and preferred download URL separately:

```json
{
  "type": "tiktok_clip",
  "url": "https://www.tiktok.com/@user/video/123",
  "download_url": "https://...download_no_watermark_addr...",
  "download_url_type": "no_watermark",
  "source": "scrapecreators"
}
```

Use this download URL priority:

```text
download_no_watermark_addr
-> existing download_url logic / download_addr / best video_urls entry
-> play_addr
-> share_url
-> url
```

If `download_no_watermark_addr` is absent, preserve the existing download URL behavior.

**Step 2: Rank candidates**

Implement simple scoring. Keep it YAGNI: subject/spoken-point match and engagement are enough for first version.

**Step 3: Run targeted tests**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py -k "asset_candidates or relevance" -v
```

Expected: PASS.

---

## Task 12: Implement Explicit Intro Card Contract

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Modify: `clipper_agency/agents/composer.py` only if scene ordering/duration logic rejects scene 0.

**Step 1: Add intro card plan item**

For roundup format or configured intro behavior, Visual Director should add:

```json
{
  "scene_number": 0,
  "beat_id": 0,
  "role": "intro_card",
  "target_duration": 3.0,
  "action": {"type": "text_card", "headline": "...", "style": "breaking_news"}
}
```

**Step 2: Preserve audio alignment**

Do not make this card steal time from voiceover-aligned beats unless product decision says intro is silent pre-roll. Preferred first version: silent 3s pre-roll before voiceover starts, with Composer duration math aware of it.

**Step 3: Run targeted tests**

Run:

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py tests/test_composer.py -k "intro_card" -v
```

Expected: PASS.

---

## Task 13: Wire Duration/Config Semantics

**Files:**
- Modify: `clipper_agency/config/schema.py:64-72`
- Modify: `niches/indonesian_artists.yaml:26-31`
- Modify docs only if config names are changed.

**Step 1: Preserve existing names or add aliases**

If renaming, keep old config compatibility:

```text
target_duration_sec -> target_script_duration_sec alias
hard_limit_sec -> max_final_duration_sec alias
```

**Step 2: Verify orchestrator behavior**

Ensure `target_duration_sec` only guides Scriptwriter and hard limit remains enforced at G10/final validation.

**Step 3: Run config tests**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_config.py tests/test_config_loader.py -v
```

Expected: PASS.

---

## Task 14: Job #4 Regression Test

**Files:**
- Create or modify: `tests/test_job4_quality_regression.py`
- Use existing fixture patterns from `tests/agents/test_visual_director_beat_driven.py` and `tests/test_composer.py`.

**Step 1: Add focused regression**

Test a minimal pipeline slice:

```text
story beat 1 and beat 2 both prefer same Ruben/Sarwendah URL
beat 2 has alternate Sarwendah apology URL
resolver chooses replacement or explicit allowed reuse
composer output duration >= audio duration
reviewer fails if duration is short
```

**Step 2: Run regression**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_job4_quality_regression.py -v
```

Expected: PASS.

---

## Task 15: Full Offline Verification

**Files:**
- No code changes unless failures are reported and approved.

**Step 1: Run offline tests**

Run:

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass.

**Step 2: If failures occur**

Stop. Report failing tests and proposed fix. Do not auto-fix without approval.

**Step 3: Commit final verified work**

After approval and passing tests:

```bash
git status
git diff
git log --oneline -10
git add <intended files only>
git commit -m "fix: harden audio-first visual quality gates"
```
