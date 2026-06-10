# Phase 23 — Wire Unwired Modules & Complete Runtime Pipeline

> **For Claude / Sub-agents:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and follow strict TDD for every task.

**Goal:** Wire all 17 modules from Phases 21 & 22 that were built but never integrated into the production pipeline. Every runtime adapter must be called from actual agent production code — not just imported.

**Filename:** `2026-06-10-phase23-wire-unwired-modules.md`  
**Date:** 2026-06-10  
**Target baseline:** `master` after PR #46 merge (v2.2.0, Phase 22 complete)  
**Recommended branch:** `phase/23-wire-unwired-modules`  
**Architecture:** No new modules. No new agents. Only wiring — imports + call sites in existing agent files.

---

## 0. Discovery Context

Cross-reference audit of Phases 21 & 22 against actual production call sites revealed:

| Status | Count | Modules |
|--------|-------|---------|
| ✅ Wired & working | 13 | visual_coverage, media_detectors, story_mode, duration_budget, story_decision_reconciliation, story_mode_contract, package_consistency, semantic_visual_review, repair_router, repair_metrics, inspection_cache, candidate_semantic_ranker, reviewer_context, multimodal_client |
| ❌ Built, never called | 17 | (see below) |
| ✅ Batch 8 (yt-dlp) | done | YtDlpService, TavilyService, BraveSearchService, multi-source integration — all wired in SP |

### 17 Unwired Modules

| # | Module | Location | Missing Call Site |
|---|--------|----------|-------------------|
| 1 | `frame_sampler.py` | `core/` | Called only by dead `frame_inspection_pipeline.py` |
| 2 | `frame_extractor.py` | `core/` | Called only by dead `frame_inspection_pipeline.py` |
| 3 | `frame_hash.py` | `core/` | Called only by dead `frame_inspection_pipeline.py` |
| 4 | `frame_quality.py` | `core/` | Called only by dead `frame_inspection_pipeline.py` |
| 5 | `frame_inspection_pipeline.py` | `core/` | **Dead module** — never called from production |
| 6 | `ocr_adapter.py` | `core/` | Called only by dead `final_layout_inspection.py` |
| 7 | `face_adapter.py` | `core/` | Called only by dead `final_layout_inspection.py` |
| 8 | `generated_text_manifest.py` | `core/` | Called only by dead `final_layout_inspection.py` |
| 9 | `source_cleanliness.py` | `core/` | Never called from production |
| 10 | `final_layout_inspection.py` | `core/` | **Dead module** |
| 11 | `text_detection.py` | `core/` | Called only by dead `ocr_adapter.py` |
| 12 | `text_collision.py` | `core/` | `detect_text_collisions()` only called by dead `final_layout_inspection.py` |
| 13 | `safe_area.py` | `core/` | `detect_safe_area_issues()` only called by dead `final_layout_inspection.py` |
| 14 | `multimodal_provider.py` | `core/` | `OpenRouterMultimodalProvider` never instantiated |
| 15 | `inspection_paths.py` | `core/` | Only imported by dead `frame_inspection_pipeline.py` |
| 16 | `rendered_scene_manifest.py` | `core/` | `build_rendered_scene_manifest()` never called — composer passes `None` |
| 17 | `llm_trace.py` + `chat_traced()` | `observability/` | `LLMTraceWriter` exists, `chat_traced()` defined but never called. All 7 agents call `llm.chat()` without trace_writer. |

---

## 1. Scope

### In Scope

1. **Wire frame inspection** into Visual Director's pre-render candidate inspection
2. **Wire OCR + face detection** into Visual Director and Composer
3. **Wire text_collision + safe_area** into Reviewer with ACTUAL detection calls
4. **Wire empty-frame detection** into Composer (replace `empty_segments=[]`)
5. **Wire source_cleanliness** into Visual Director's candidate scoring
6. **Wire rendered_scene_manifest** into Composer → Reviewer flow
7. **Wire LLM trace** into all 7 agents (trace_writer + chat_traced)
8. **Wire final_layout_inspection** into Composer post-render
9. **Verify Batch 8** yt-dlp multi-source is properly wired (build verification)
10. **Add agent-level integration tests** for all new call sites

### Out of Scope

- New agents (architecture preserved)
- New core modules (all modules already built)
- VLM provider changes (multimodal_client already wired in VD)

---

## 2. Core Design Decisions

### 2.1 Wiring Not Building

All modules already exist and have unit tests. This phase ONLY:
- Adds imports to agent files
- Adds call sites in agent `execute()` / helper methods  
- Adds agent-level integration tests verifying modules are actually called
- Does NOT modify existing core module logic

### 2.2 Two-Pass Wiring (Pre-Render + Post-Render)

Per the Phase 22 design (Section 3.3):

**Pre-render pass (Visual Director):**
```
candidate asset → frame extraction → OCR → face detection → VLM inspection → candidate score → accept/revise/reject
```

**Post-render pass (Composer → Reviewer):**
```
final video → black/freeze/empty-frame scan → final OCR → caption/source text collision → face/safe-area validation → timestamp semantic review → approve/repair/reject
```

### 2.3 Agent Wiring Targets

| Agent | Modules to Wire | Has Config Gate? |
|-------|----------------|-------------------|
| **Visual Director** | frame_sampler, frame_extractor, frame_hash, frame_inspection_pipeline, ocr_adapter, face_adapter, source_cleanliness, inspection_paths | Yes — `quality.runtime_inspection.enabled` |
| **Composer** | frame_quality (empty-frame), generated_text_manifest, rendered_scene_manifest, final_layout_inspection | Byproduct of render |
| **Reviewer** | text_collision, safe_area — actual detection calls replacing null-dict checks | Yes — `quality.text_collision` / `quality.safe_area` |
| **All Agents** | LLMTraceWriter — pass `trace_writer` on `OpenRouterClient()` construction; switch from `llm.chat()` to `llm.chat_traced()` | Yes — `observability.llm_traces.enabled` |

### 2.4 Config-Driven Gating

Every new runtime feature must be gated by `config/schema.py` settings, defaulting to `enabled: true`:

```yaml
quality:
  runtime_inspection:
    enabled: true          # gates: frame_extractor, ocr, face, cleanliness
    persist_keyframes: true
    frame_interval_sec: 0.5
    max_frames_per_asset: 8
    perceptual_hash_distance: 6

  ocr:
    enabled: true
    provider: paddleocr

  face_detection:
    enabled: true
    provider: mediapipe

observability:
  llm_traces:
    enabled: true
```

- When config is disabled → agents skip the module call (preserves backward compat)
- When config is enabled → agents call the module; failures are caught and logged, not fatal
- Config already exists in schema.py (Task 0.2 from Phase 22)

### 2.5 LLM Trace Wiring Pattern

Current pattern (every agent):
```python
llm = OpenRouterClient()
response = llm.chat(...)
```

New pattern:
```python
llm = OpenRouterClient(trace_writer=self._trace_writer)
response = llm.chat_traced(
    model=..., messages=..., job_id=..., agent=..., task=...,
    prompt_template_id=..., prompt_version=...,
)
```

Where `self._trace_writer` is a module-level singleton created once by the orchestrator/engine and passed to each agent via its constructor or config dict.

**Implementation approach**: Add `trace_writer: LLMTraceWriter | None = None` to each agent's `__init__()`. The Engine creates one `LLMTraceWriter` and passes it to agents. If `trace_writer is None` (default), behavior is identical to current — no traces written.

---

## 3. Parallel Dependency Graph

```
Batch 0 — Config & Infrastructure Verification (sequential)
  ↓
Batch 1 — Visual Director Pre-Render Wiring (parallel A-C)
  ↓
Batch 2 — Composer Post-Render Wiring (parallel D-F)
  ↓
Batch 3 — Reviewer Actual Detection Wiring (sequential G)
  ↓
Batch 4 — LLM Trace Wiring — All Agents (parallel H-N)
  ↓
Batch 5 — End-to-End Verification (sequential)
```

### Safe Parallelism Summary

| Batch | Parallel? | Reason |
|-------|-----------|--------|
| Batch 0 | No | Config verification — must run first |
| Batch 1 | Yes | Frame pipeline (A), OCR/Face (B), Cleanliness (C) touch different VD methods |
| Batch 2 | Yes | Empty-frame (D), Text manifest (E), Scene manifest (F) are independent additions |
| Batch 3 | No | Reviewer wiring touches shared reviewer.py — single owner |
| Batch 4 | **YES** | All 7 agents (H-N) are independent — each agent gets its own trace_writer wiring |
| Batch 5 | No | End-to-end validation requires integrated state |

---

## 4. Global Execution Rules

1. **TDD is mandatory.** Every task starts with a failing agent-level integration test.
2. **Surgical changes only.** Add imports + call sites. Do not refactor existing logic.
3. **No agent file modification outside assigned task.**
4. **Use the project virtualenv:** `.venv/bin/python3 -m ...`
5. **Offline test gate:**
   ```bash
   .venv/bin/python3 -m pytest -m "not external and not integration" -q
   ```
6. **Commit after every green task.**
7. **Config-gate every new call site.** When `enabled: false`, skip the module call.
8. **Catch and log module failures.** A failed detector must not crash the pipeline.
9. **No new top-level agents.**
10. **No new core modules.** All modules to wire already exist.

---

## Batch 0 — Config & Infrastructure Verification

**Mode:** Sequential  
**Gate:** Verify runtime config exists, Batch 8 is properly wired, all existing tests pass.

### Task 0.1 — Verify Runtime Feature Flags Exist

**Files:**
- Read: `clipper_agency/config/schema.py`

**Checks:**
1. `quality.runtime_inspection.enabled` field exists
2. `quality.ocr.enabled` field exists  
3. `quality.face_detection.enabled` field exists
4. `observability.llm_traces.enabled` field exists

**Action:** If any flag is missing, add it (these were from Task 0.2 of Phase 22). If they already exist, confirm and move on.

### Task 0.2 — Verify Batch 8 Multi-Source Wiring

**Files:**
- Read: `clipper_agency/agents/segment_producer.py`
- Run: Targeted batch 8 tests

**Checks:**
1. `_discover_multi_source_assets()` is called from `execute()` (line ~229)
2. YtDlpService, TavilyService, BraveSearchService are imported and used
3. Tests pass:
```bash
.venv/bin/python3 -m pytest \
  tests/test_ytdlp_search.py \
  tests/test_tavily_service.py \
  tests/test_brave_service.py \
  tests/test_source_quality_tiers.py \
  tests/test_batch8_multi_source.py \
  tests/test_yt_thumbnail_fallback.py \
  -v
```

**Commit (if fixes needed):**
```bash
git commit -m "fix: verify batch8 multi-source wiring"
```

### Batch 0 Gate

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all existing tests pass. Config is verified.

---

## Batch 1 — Visual Director Pre-Render Wiring

**Mode:** Parallel workers A-C.

All workers modify `clipper_agency/agents/visual_director.py` but touch different methods/sections. Worker A touches frame inspection, Worker B touches OCR/face, Worker C touches cleanliness. Coordinate merge order in Batch 1 integration.

---

### Worker A — Task 1.1: Wire Frame Inspection Pipeline into Visual Director

**Files:**
- Modify: `clipper_agency/agents/visual_director.py` — `_inspect_candidate_asset()` method
- Create/Modify: `tests/test_agents_visual_director.py` — add frame inspection test

**What to wire:**
- Import `run_frame_inspection_pipeline` from `core.frame_inspection_pipeline`
- Import `candidate_inspection_dir` from `core.inspection_paths`
- After downloading a candidate asset, if config `runtime_inspection.enabled`:
  1. Call `run_frame_inspection_pipeline(video_path, beat_id, asset_id, output_dir, config)`
  2. Pass extracted frame paths to `MultimodalInspectionClient.inspect_asset()`
  3. Persist `FrameExtractionManifest` under `candidate_inspection_dir()`

**Wiring point:** Inside `_inspect_candidate_asset()` (around line 640-700), after asset download but before VLM call. Currently `frame_paths` is passed as empty list to VLM. After wiring, it contains actual extracted frames.

**TDD:**
```python
def test_frame_extraction_runs_during_candidate_inspection(mocker, tmp_path):
    """Frame inspection pipeline must be called when runtime_inspection is enabled."""
    # Mock frame inspection pipeline
    mock_pipeline = mocker.patch(
        "clipper_agency.agents.visual_director.run_frame_inspection_pipeline",
        return_value=make_manifest(frame_paths=["frame1.jpg", "frame2.jpg"]),
    )
    # Mock multimodal client
    mock_inspect = mocker.patch.object(MultimodalInspectionClient, "inspect_asset")

    vd = VisualDirectorAgent(config_with_inspection_enabled())
    result = vd._inspect_candidate_asset(candidate, beat, tmp_path)

    mock_pipeline.assert_called_once()
    # Frame paths should be passed to VLM
    vlm_call = mock_inspect.call_args
    assert len(vlm_call.kwargs["frame_paths"]) == 2


def test_frame_inspection_skipped_when_disabled(mocker, tmp_path):
    """Frame extraction must not run when runtime_inspection.enabled=false."""
    mock_pipeline = mocker.patch(
        "clipper_agency.agents.visual_director.run_frame_inspection_pipeline"
    )

    vd = VisualDirectorAgent(config_with_inspection_disabled())
    vd._inspect_candidate_asset(candidate, beat, tmp_path)

    mock_pipeline.assert_not_called()
```

**Commit:**
```bash
git commit -m "feat: wire frame inspection pipeline into visual director"
```

---

### Worker B — Task 1.2: Wire OCR + Face Detection into Visual Director

**Files:**
- Modify: `clipper_agency/agents/visual_director.py` — extend `_inspect_candidate_asset()`
- Create/Modify: `tests/test_agents_visual_director.py`

**What to wire:**
- Import `PaddleOCRAdapter` (lazy) from `core.ocr_adapter`
- Import `MediaPipeFaceDetector` (lazy) from `core.face_adapter`
- Import `score_source_cleanliness` from `core.source_cleanliness`
- After frame extraction, if config `ocr.enabled`:
  1. Create `PaddleOCRAdapter()`
  2. For each frame: `adapter.inspect(frame_path, timestamp_sec)`
  3. Normalize via `normalize_text_region` from `core.text_detection`
  4. Pass OCR regions to `MultimodalInspectionClient.inspect_asset(ocr_regions=...)`
- After frame extraction, if config `face_detection.enabled`:
  1. Create `MediaPipeFaceDetector()`
  2. For each frame: `detector.detect(frame_path, timestamp_sec)`
  3. Pass face regions through to diagnostics

**Wiring point:** Inside `_inspect_candidate_asset()`, after frame extraction, before VLM call. Currently `ocr_regions` and face data are not computed.

**TDD:**
```python
def test_ocr_runs_on_extracted_keyframes(mocker, tmp_path):
    """PaddleOCR must be called on keyframes during candidate inspection."""
    mocker.patch(
        "clipper_agency.agents.visual_director.run_frame_inspection_pipeline",
        return_value=make_manifest(frame_paths=["f1.jpg", "f2.jpg"]),
    )
    mock_ocr = mocker.patch("clipper_agency.core.ocr_adapter.PaddleOCRAdapter")
    mock_ocr_instance = mock_ocr.return_value
    mock_ocr_instance.inspect.return_value = make_ocr_result()

    vd = VisualDirectorAgent(config_with_ocr_enabled())
    vd._inspect_candidate_asset(candidate, beat, tmp_path)

    assert mock_ocr_instance.inspect.call_count == 2


def test_face_detection_runs_when_enabled(mocker, tmp_path):
    mocker.patch(
        "clipper_agency.agents.visual_director.run_frame_inspection_pipeline",
        return_value=make_manifest(frame_paths=["f1.jpg"]),
    )
    mock_face = mocker.patch("clipper_agency.core.face_adapter.MediaPipeFaceDetector")

    vd = VisualDirectorAgent(config_with_face_enabled())
    vd._inspect_candidate_asset(candidate, beat, tmp_path)

    mock_face.return_value.detect.assert_called()


def test_ocr_skipped_when_disabled(mocker, tmp_path):
    mocker.patch(
        "clipper_agency.agents.visual_director.run_frame_inspection_pipeline",
        return_value=make_manifest(frame_paths=["f1.jpg"]),
    )
    mock_ocr = mocker.patch("clipper_agency.core.ocr_adapter.PaddleOCRAdapter")

    vd = VisualDirectorAgent(config_with_ocr_disabled())
    vd._inspect_candidate_asset(candidate, beat, tmp_path)

    mock_ocr.assert_not_called()
```

**Commit:**
```bash
git commit -m "feat: wire OCR and face detection into visual director"
```

---

### Worker C — Task 1.3: Wire Source Cleanliness into Candidate Scoring

**Files:**
- Modify: `clipper_agency/agents/visual_director.py` — extend scoring logic
- Create/Modify: `tests/test_agents_visual_director.py`

**What to wire:**
- Import `score_source_cleanliness` from `core.source_cleanliness`
- In `rank_candidates` / selection logic, call `score_source_cleanliness(ocr_regions, face_regions, source_metadata)` for each candidate
- Factor cleanliness score into final candidate ranking via `candidate_semantic_ranker`

**Wiring point:** After OCR/face results are available, before final candidate selection (around line 800-815).

**TDD:**
```python
def test_source_cleanliness_affects_candidate_ranking(mocker):
    """Dirty sources (watermarks, burned-in text) should rank lower."""
    mock_cleanliness = mocker.patch(
        "clipper_agency.agents.visual_director.score_source_cleanliness",
        side_effect=[
            {"cleanliness_score": 0.90, "issues": []},       # clean
            {"cleanliness_score": 0.30, "issues": ["BURNED_CAPTION"]},  # dirty
        ],
    )

    vd = VisualDirectorAgent(config_default())
    ranked = vd._rank_and_select_candidates([clean_candidate, dirty_candidate], beat)

    assert ranked[0]["asset_id"] == clean_candidate["asset_id"]  # clean wins
    assert ranked[1]["asset_id"] == dirty_candidate["asset_id"]
```

**Commit:**
```bash
git commit -m "feat: wire source cleanliness into visual director scoring"
```

---

### Batch 1 Integration — Merge & Coordinate

**Mode:** Sequential. Coordinate A, B, C changes in `visual_director.py` to avoid conflicts.

**Gate:**
```bash
.venv/bin/python3 -m pytest tests/test_agents_visual_director.py -v
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

---

## Batch 2 — Composer Post-Render Wiring

**Mode:** Parallel workers D-F. All modify `composer.py` at different sections.

---

### Worker D — Task 2.1: Wire Empty-Frame Detection into Composer

**Files:**
- Modify: `clipper_agency/agents/composer.py` — `_attach_visual_coverage_diagnostics()`
- Create/Modify: `tests/test_composer.py`

**What to wire:**
- Import `detect_empty_segments` from `core.frame_quality`
- Replace hardcoded `empty_segments=[]` (line 563) with actual detection
- Extract a few keyframes from the final video, run frame variance analysis
- Pass detected empty segments to `evaluate_visual_coverage()`

**Wiring point:** Line 563 in `_attach_visual_coverage_diagnostics()`:
```python
# Before:
empty_segments=[],

# After:
empty_segs = _safe_detect_empty(video_path) if video_path else []
empty_segments=empty_segs,
```

**Note:** Unlike black/freeze detection (FFmpeg-based, lightweight), empty-frame detection requires frame extraction + image analysis (heavier). Use sampling: extract 1 frame every 1 second, analyze variance, merge consecutive low-variance frames.

**TDD:**
```python
def test_composer_detects_empty_frames_after_render(mocker):
    mocker.patch(
        "clipper_agency.agents.composer.detect_empty_segments",
        return_value=[(15.0, 17.5)],
    )
    mocker.patch(
        "clipper_agency.agents.composer.evaluate_visual_coverage",
        return_value=VisualCoverageResult(status="fail", ...),
    )

    result = run_composer_with_test_video(...)

    # Empty segments must be passed to evaluate_visual_coverage
    call_args = evaluate_visual_coverage_mock.call_args
    assert call_args.kwargs["empty_segments"] == [(15.0, 17.5)]
```

**Commit:**
```bash
git commit -m "feat: wire empty-frame detector into composer"
```

---

### Worker E — Task 2.2: Wire Generated Text Manifest into Composer

**Files:**
- Modify: `clipper_agency/agents/composer.py` — after render, before diagnostics
- Create/Modify: `tests/test_composer.py`

**What to wire:**
- Import `build_generated_text_regions` from `core.generated_text_manifest`
- After rendering, the template engine already knows subtitle/headline positions
- Call `build_generated_text_regions(render_plan, frame_size=(1080, 1920))`
- Persist result in `output["diagnostics"]["generated_text_regions"]`
- This data flows to Reviewer for text collision detection

**Wiring point:** After `_render_via_template()`, extract the render_plan's text layer coordinates and build the manifest.

**TDD:**
```python
def test_composer_persists_generated_text_regions(mocker):
    mocker.patch(
        "clipper_agency.agents.composer.build_generated_text_regions",
        return_value=[{"layer": "subtitle", "bbox": [120, 1480, 960, 1740]}],
    )

    result = run_composer_with_render_plan(...)

    assert "generated_text_regions" in result["diagnostics"]
    regions = result["diagnostics"]["generated_text_regions"]
    assert regions[0]["layer"] == "subtitle"
```

**Commit:**
```bash
git commit -m "feat: wire generated text manifest into composer"
```

---

### Worker F — Task 2.3: Wire Rendered Scene Manifest into Composer

**Files:**
- Modify: `clipper_agency/agents/composer.py` — after render  
- Create/Modify: `tests/test_composer.py`

**What to wire:**
- Import `build_rendered_scene_manifest` from `core.rendered_scene_manifest`
- After rendering, call `build_rendered_scene_manifest(scene_timeline, beat_metadata, asset_info)`
- Set `output["rendered_scene_manifest"]` to the result
- This fixes the Reviewer receiving `None` for `rendered_scene_manifest`

**Wiring point:** After successful render, the Composer already has: scene timeline (start_sec/end_sec per scene), beat assignments, selected asset info. Build the manifest from this data.

**TDD:**
```python
def test_composer_output_includes_rendered_scene_manifest(mocker):
    mocker.patch(
        "clipper_agency.agents.composer.build_rendered_scene_manifest",
        return_value={"entries": [{"beat_id": "1", "start_sec": 0.0, "end_sec": 5.0}]},
    )

    result = run_composer_with_full_pipeline(...)

    manifest = result.get("rendered_scene_manifest")
    assert manifest is not None
    assert len(manifest["entries"]) > 0
    assert manifest["entries"][0]["beat_id"] is not None


def test_composer_rendered_scene_manifest_flows_to_engine(mocker):
    """Manifest must be in composer output so engine reads it."""
    result = run_composer_with_full_pipeline(...)

    assert "rendered_scene_manifest" in result
    # engine.py reads: compose_output.get("rendered_scene_manifest")
```

**Commit:**
```bash
git commit -m "feat: wire rendered scene manifest into composer"
```

---

### Batch 2 Gate

```bash
.venv/bin/python3 -m pytest tests/test_composer.py -v
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

---

## Batch 3 — Reviewer Actual Detection Wiring

**Mode:** Sequential. All changes in `reviewer.py`.

---

### Task 3.1 — Wire Actual Text Collision Detection into Reviewer

**Files:**
- Modify: `clipper_agency/agents/reviewer.py`
- Create/Modify: `tests/test_agents_reviewer.py`

**Current state:** Reviewer has `_fail_if_text_collision_failed(diagnostics)` which checks `diagnostics.get("text_collision")`. But NOBODY populates this key — the Reviewer checks an empty dict.

**What to wire:**
- Import `detect_text_collisions` from `core.text_collision`
- Import `detect_source_text_density` from `core.text_collision`
- Build source_regions from OCR output (available in composer diagnostics)
- Build generated_regions from generated_text_manifest (available from Task E above)
- Call `detect_text_collisions(source_regions, generated_regions, thresholds)` BEFORE the LLM gate
- Call `detect_source_text_density(source_regions, frame_size, thresholds)`
- Populate `diagnostics["text_collision"]` with actual results
- The existing `_fail_if_text_collision_failed()` will then work properly

**Wiring point:** At the top of reviewer's `execute()`, before checking existing gates, build the text collision diagnostics from data available in the context bundle.

**TDD:**
```python
def test_reviewer_runs_actual_text_collision_detection(mocker):
    """Reviewer must call detect_text_collisions, not just check empty dict."""
    mock_collision = mocker.patch(
        "clipper_agency.agents.reviewer.detect_text_collisions",
        return_value=[{"type": "SUBTITLE_SOURCE_TEXT_OVERLAP"}],
    )
    mock_llm = mocker.patch("clipper_agency.agents.reviewer.OpenRouterClient")

    reviewer = ReviewerAgent()
    result = reviewer.execute(make_context_with_ocr_and_regions())

    mock_collision.assert_called_once()
    # Must block before LLM when collision detected
    assert result["status"] == "failed"
    mock_llm.assert_not_called()


def test_reviewer_text_collision_passes_clean_video(mocker):
    mock_collision = mocker.patch(
        "clipper_agency.agents.reviewer.detect_text_collisions",
        return_value=[],
    )
    mock_density = mocker.patch(
        "clipper_agency.agents.reviewer.detect_source_text_density",
        return_value=[],
    )

    reviewer = ReviewerAgent()
    result = reviewer.execute(make_context_clean())

    # Should proceed past text collision gate
    assert result.get("status") != "failed" or "TEXT_COLLISION" not in str(result)
```

**Commit:**
```bash
git commit -m "feat: wire actual text collision detection into reviewer"
```

---

### Task 3.2 — Wire Actual Safe Area Detection into Reviewer

**Files:**
- Modify: `clipper_agency/agents/reviewer.py`
- Create/Modify: `tests/test_agents_reviewer.py`

**Current state:** Same as text collision — `_fail_if_safe_area_failed()` checks empty dict.

**What to wire:**
- Import `detect_safe_area_issues` from `core.safe_area`
- Build generated_regions from composer's text manifest
- Build face_regions from Visual Director's candidate diagnostics (face inspection results)
- Call `detect_safe_area_issues(generated_regions, face_regions, frame_size, platform, thresholds)`
- Populate `diagnostics["safe_area"]` with actual results

**Wiring point:** Same as text collision — early in `execute()`, build diagnostics from available data.

**TDD:**
```python
def test_reviewer_runs_actual_safe_area_detection(mocker):
    mock_safe = mocker.patch(
        "clipper_agency.agents.reviewer.detect_safe_area_issues",
        return_value=[{"type": "PLATFORM_UNSAFE_ZONE"}],
    )

    reviewer = ReviewerAgent()
    result = reviewer.execute(make_context_with_face_and_caption_regions())

    mock_safe.assert_called_once()
    assert result["status"] == "failed"


def test_reviewer_safe_area_skips_when_no_face_data(mocker):
    """Safe area check gracefully degrades when face detection unavailable."""
    mock_safe = mocker.patch(
        "clipper_agency.agents.reviewer.detect_safe_area_issues"
    )

    reviewer = ReviewerAgent()
    result = reviewer.execute(make_context_without_face_regions())

    # Should not crash; should handle gracefully
    assert result is not None
```

**Commit:**
```bash
git commit -m "feat: wire actual safe area detection into reviewer"
```

---

### Batch 3 Gate

```bash
.venv/bin/python3 -m pytest tests/test_agents_reviewer.py -v
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

---

## Batch 4 — LLM Trace Wiring (All 7 Agents)

**Mode:** Parallel workers H-N. Each worker modifies one agent. No shared files.

**Shared infrastructure** (created in Task 4.0 before workers start):

### Task 4.0 — Create Trace Writer Singleton in Engine

**Files:**
- Modify: `clipper_agency/orchestrator/engine.py`
- Create/Modify: `tests/test_orchestrator_engine.py`

**What to do:**
- Import `LLMTraceWriter` from `clipper_agency.observability.llm_trace`
- In the engine's job setup, check `config.observability.llm_traces.enabled`
- If enabled, create one `LLMTraceWriter(job_cache_dir / "llm_traces")`
- Pass `trace_writer` to each agent via its config dict
- Each agent's `__init__` already accepts `trace_writer` parameter (or needs it added)

**Agent pattern** (same for all 7 agents):
```python
# In agent __init__:
def __init__(self, config: dict | None = None, trace_writer=None):
    self._trace_writer = trace_writer

# In execute(), where LLM is used:
llm = OpenRouterClient(trace_writer=self._trace_writer)
if self._trace_writer:
    response = llm.chat_traced(
        model=model, messages=messages,
        job_id=job_id, agent=self.agent_name, task=task_name,
        prompt_template_id=..., prompt_version=...,
    )
else:
    response = llm.chat(model=model, messages=messages)
```

**TDD:**
```python
def test_engine_creates_trace_writer_when_enabled(mocker, tmp_path):
    mock_writer = mocker.patch("clipper_agency.orchestrator.engine.LLMTraceWriter")
    config = config_with_traces_enabled(tmp_path)

    engine = Engine(config)
    engine.run_job(job_id=5)

    mock_writer.assert_called_once()


def test_engine_skips_trace_writer_when_disabled(mocker):
    mock_writer = mocker.patch("clipper_agency.orchestrator.engine.LLMTraceWriter")
    config = config_with_traces_disabled()

    engine = Engine(config)
    engine.run_job(job_id=5)

    mock_writer.assert_not_called()
```

**Commit:**
```bash
git commit -m "feat: create trace writer singleton in engine"
```

---

### Workers H-N — Wire Trace Writer Into Each Agent

**Pattern identical for all 7 agents.** Each worker:

1. Add `trace_writer=None` parameter to agent's `__init__()`
2. Store as `self._trace_writer`
3. In `execute()`, where `OpenRouterClient()` is created, pass `trace_writer=self._trace_writer`
4. Switch from `llm.chat()` to `llm.chat_traced()` when writer is available
5. Add test: `test_agent_writes_llm_trace_when_writer_configured()`
6. Add test: `test_agent_still_works_when_writer_is_none()`

**Agent mapping:**

| Worker | Agent File | LLM at line |
|--------|-----------|-------------|
| H | `agents/safety.py` | line 53-55 |
| I | `agents/segment_producer.py` | lines 782-783 |
| J | `agents/scriptwriter.py` | lines 180-181 |
| K | `agents/voice_producer.py` | (find LLM creation) |
| L | `agents/visual_director.py` | lines 317, 696, 1103 (3 LLM calls) |
| M | `agents/composer.py` | (find LLM creation — may only use card generator, not LLM) |
| N | `agents/reviewer.py` | lines 526-528 |

**Standard TDD per worker:**

```python
def test_{agent}_writes_llm_trace_when_writer_configured(mocker, tmp_path):
    writer = LLMTraceWriter(tmp_path / "traces")
    agent = {Agent}Class(trace_writer=writer)

    mocker.patch.object(OpenRouterClient, "chat", return_value={"content": "{}"})
    result = agent.execute(make_input())

    # Trace directory must exist
    trace_dirs = list((tmp_path / "traces").glob("*/"))
    assert len(trace_dirs) > 0
    assert (trace_dirs[0] / "request.json").exists()
    assert (trace_dirs[0] / "response.json").exists()


def test_{agent}_works_without_trace_writer(mocker):
    agent = {Agent}Class(trace_writer=None)

    mocker.patch.object(OpenRouterClient, "chat", return_value={"content": "{}"})
    result = agent.execute(make_input())

    # Must still complete normally
    assert result is not None
```

**Commit per worker:**
```bash
git commit -m "feat: wire llm trace into {agent_name}"
```

---

### Batch 4 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_llm_trace.py \
  tests/test_llm_trace_redaction.py \
  tests/test_llm_client_tracing.py \
  tests/test_agents_safety.py \
  tests/test_agents_segment_producer.py \
  tests/test_agents_scriptwriter.py \
  tests/test_agents_voice_producer.py \
  tests/test_agents_visual_director.py \
  tests/test_composer.py \
  tests/test_agents_reviewer.py \
  -v

.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: All agents work with or without trace_writer. Trace writer wiring is transparent.

---

## Batch 5 — End-to-End Verification

**Mode:** Sequential.

---

### Task 5.1 — E2E Wiring Verification Test

**Files:**
- Create/Modify: `tests/test_phase23_wiring_verification.py`

**Tests that must pass:**
1. Full pipeline with all gates enabled produces:
   - Frame inspection artifacts under `candidate_inspection_dir()`
   - OCR results per keyframe
   - Face detection results
   - Empty-frame diagnostics in composer output
   - Generated text regions in composer output
   - Rendered scene manifest in composer output
   - Actual text_collision results in reviewer diagnostics
   - Actual safe_area results in reviewer diagnostics
   - LLM trace artifacts for every LLM call

2. Full pipeline with all gates disabled:
   - Pipeline still completes (graceful degradation)
   - No new artifacts created
   - Existing behavior preserved

**TDD:**
```python
def test_full_pipeline_produces_inspection_artifacts(mocker, tmp_path):
    """End-to-end: runtime inspection produces keyframe, OCR, face artifacts."""
    config = config_with_all_gates_enabled(tmp_path)
    engine = Engine(config)

    result = engine.run_job(job_id=5, topic="test topic")

    # Frame inspection
    assert (tmp_path / "cache/job_5/inspections/candidates").exists()
    # OCR results
    assert any_file_matches(tmp_path / "cache/job_5", "*ocr*.json")
    # Empty-frame detected
    assert "empty_segments" in str(result.get("diagnostics", {}))
    # Rendered scene manifest
    assert result.get("rendered_scene_manifest") is not None
    # Text collision check ran
    assert "text_collision" in str(result.get("diagnostics", {}))
    # LLM traces
    assert (tmp_path / "cache/job_5/llm_traces").exists()


def test_full_pipeline_graceful_degradation(mocker, tmp_path):
    """Pipeline must complete even when inspection features are disabled."""
    config = config_with_all_gates_disabled(tmp_path)
    engine = Engine(config)

    result = engine.run_job(job_id=5, topic="test topic")

    assert result.get("status") in {"completed", "failed"}
    # Should not crash
```

**Commit:**
```bash
git commit -m "test: add e2e wiring verification tests"
```

---

### Task 5.2 — Full Offline Suite Validation

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all ~1793 offline tests pass (same as current baseline).

### Task 5.3 — Coverage Check

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" --cov=clipper_agency --cov-report=term-missing
```

Expected: coverage ≥ 93%.

---

## 6. Summary of Changes

### Files Modified (agents + engine):
- `clipper_agency/orchestrator/engine.py` — trace writer creation
- `clipper_agency/agents/visual_director.py` — frame, OCR, face, cleanliness wiring
- `clipper_agency/agents/composer.py` — empty-frame, text manifest, scene manifest wiring
- `clipper_agency/agents/reviewer.py` — actual text_collision + safe_area detection calls
- `clipper_agency/agents/safety.py` — trace writer
- `clipper_agency/agents/segment_producer.py` — trace writer
- `clipper_agency/agents/scriptwriter.py` — trace writer
- `clipper_agency/agents/voice_producer.py` — trace writer

### Files NOT Modified:
- All `core/` modules (already built and tested)
- `config/schema.py` (config already exists)
- `services/ytdlp.py`, `services/tavily.py`, `services/brave.py` (already wired in SP)

### New Files:
- `tests/test_phase23_wiring_verification.py` — E2E verification

---

## 7. Definition of Done

This phase is complete when:

1. ✅ Frame inspection pipeline is called from Visual Director
2. ✅ OCR and face detection run on candidate keyframes
3. ✅ Source cleanliness affects candidate ranking
4. ✅ Empty-frame detection replaces `empty_segments=[]` in Composer
5. ✅ Generated text regions are persisted by Composer
6. ✅ Rendered scene manifest is set in Composer output (Reviewer receives non-None)
7. ✅ `detect_text_collisions()` is called by Reviewer (not just checking empty dict)
8. ✅ `detect_safe_area_issues()` is called by Reviewer (not just checking empty dict)
9. ✅ All 7 agents pass `trace_writer` to `OpenRouterClient` and call `chat_traced()`
10. ✅ Full offline suite passes (≥1793 tests, ≥93% coverage)
11. ✅ All new call sites are config-gated (disabled = backward compat)
12. ✅ All new call sites catch failures gracefully (no pipeline crash)
13. ✅ Batch 8 multi-source wiring verified

---

## 8. Recommended PR

```bash
git checkout master
git pull origin master
git checkout -b phase/23-wire-unwired-modules
```

After all gates pass:

```bash
git push -u origin phase/23-wire-unwired-modules

gh pr create \
  --base master \
  --title "Phase 23: Wire unwired modules into production pipeline" \
  --body "Wires 17 Phase 21/22 modules that were built but never called from production:
  - Frame inspection pipeline → Visual Director
  - OCR + Face detection → Visual Director  
  - Source cleanliness → Visual Director ranking
  - Empty-frame detection → Composer
  - Generated text manifest → Composer
  - Rendered scene manifest → Composer → Reviewer
  - Actual text_collision detection → Reviewer
  - Actual safe_area detection → Reviewer
  - LLM trace writer → All 7 agents
  
  All wiring is config-gated. No new modules. No new agents."
```

Do not merge until SonarCloud passes.
