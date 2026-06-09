# Job #4 Improvement Parallel TDD Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Job #4 quality-improvement design with deterministic visual gates, explicit story-mode control, semantic visual relevance foundations, and structured repair routing while preserving the existing seven-agent architecture.

**Architecture:** Build shared schema/config contracts first, then run independent deterministic modules in parallel, followed by narrow integration batches for Composer, Reviewer, Segment Producer, and Engine. Every implementation slice follows strict TDD: write the failing test, verify RED, implement the minimum code, verify GREEN, then refactor only while tests remain green.

**Tech Stack:** Python 3.11+, Pydantic, pytest, FFmpeg/ffprobe, OpenCV-compatible data contracts, existing SQLite/orchestrator pipeline, existing agent modules.

---

## Source Design

This plan implements the staged design in:

- `docs/plans/2026-06-09-job4-improvement-design.md`

The plan assumes PR #42 / `phase/20-job4-quality-fixes` is baseline and must not duplicate already-completed fixes:

- duplicate / invalid visual URL replacement;
- Composer output-duration guard;
- Reviewer AV duration mismatch hard gate;
- Reviewer broken `tiktok_clip` hard gate;
- explicit roundup intro-card handling;
- no-watermark URL preference;
- model diagnostics;
- keyword-based asset relevance ranking.

---

## Global Execution Rules

1. **TDD is mandatory.** No production code before a failing test is observed.
2. **Batch gates are strict.** Do not start a downstream batch until all upstream tests pass.
3. **Parallel workers must not modify shared integration files unless assigned.**
4. **Use the project virtualenv.** All Python commands use `.venv/bin/python3 -m ...`.
5. **Offline test command for batch gates:**

   ```bash
   .venv/bin/python3 -m pytest -m "not external and not integration" -q
   ```

6. **Do not add top-level agents.** Extend existing agents and deterministic services only.
7. **Prefer deterministic checks before LLM checks.** Reviewer LLM must only run after deterministic gates pass.
8. **Keep changes additive where possible.** Avoid broad refactors outside the assigned batch.
9. **Commit after each green task or logical worker completion.** Use concise commit messages.

---

## Parallel Dependency Graph

```text
Batch 0 — Shared Contracts (sequential)
  ↓
Batch 1 — Deterministic Core Modules (parallel workers A-E)
  ↓
Batch 2 — Deterministic Agent Integration (limited parallel, then gate)
  ↓
Batch 3 — Story Mode + Package Scope (parallel workers H-K)
  ↓
Batch 4 — Semantic Relevance + Repair Foundations (parallel workers L-O)
  ↓
Batch 5 — Job #4 Regression + Final Validation (sequential)
```

### Safe Parallelism Summary

| Batch | Parallel? | Reason |
|---|---:|---|
| Batch 0 | No | Shared schema/config foundation used by all workers |
| Batch 1 | Yes | Independent pure/deterministic core modules |
| Batch 2 | Limited | Composer and Reviewer integration touch agent outputs but can be split carefully |
| Batch 3 | Yes | Story mode, duration budget, and package consistency can be developed independently after schemas exist |
| Batch 4 | Yes | Semantic contracts, scoring stubs, repair routing, and reviewer output contracts are separable |
| Batch 5 | No | End-to-end regression and final offline suite require integrated state |

---

# Batch 0 — Shared Contracts and Configuration

**Mode:** Sequential  
**Gate:** Schema/config tests pass and full offline suite still passes.

## Task 0.1: Add quality and editorial schema models

**Files:**

- Modify: `clipper_agency/config/schema.py`
- Test: `tests/test_content_planning_schema.py`

**Models to add:**

- `VisualCoverageIssue`
- `VisualCoverageResult`
- `DetectedTextRegion`
- `TextCollisionIssue`
- `SafeAreaIssue`
- `StoryModeDecision`
- `DurationBudgetSection`
- `DurationBudget`
- `EvidenceContract`
- `VisualRelevanceScore`
- `PackageConsistencyResult`
- `RepairPatch`
- `RepairPlan`

**Step 1: Write failing schema tests**

Add tests to `tests/test_content_planning_schema.py`:

```python
def test_visual_coverage_result_is_json_serializable():
    from clipper_agency.config.schema import VisualCoverageIssue, VisualCoverageResult

    result = VisualCoverageResult(
        status="fail",
        output_duration_sec=21.2,
        voiceover_duration_sec=21.0,
        coverage_ratio=0.79,
        issues=[
            VisualCoverageIssue(
                type="BLACK_FRAME",
                start_sec=17.83,
                end_sec=21.2,
                severity="hard_fail",
                detail="black segment exceeds threshold",
            )
        ],
    )

    payload = result.model_dump()
    assert payload["issues"][0]["type"] == "BLACK_FRAME"
    assert payload["status"] == "fail"


def test_story_mode_decision_supports_roundup_contract():
    from clipper_agency.config.schema import StoryModeDecision

    decision = StoryModeDecision(
        story_mode="roundup",
        confidence=0.97,
        reason="Broad entertainment topic requests multiple recent stories.",
        item_count=3,
        target_duration_sec=30,
        requires_intro_card=True,
        thumbnail_strategy="roundup",
        cta_strategy="compare_items",
    )

    assert decision.story_mode == "roundup"
    assert decision.requires_intro_card is True


def test_repair_plan_limits_cycles_and_routes_patch():
    from clipper_agency.config.schema import RepairPatch, RepairPlan

    plan = RepairPlan(
        decision="revise",
        max_repair_cycles=2,
        patches=[
            RepairPatch(
                beat_id="B04",
                action="replace_visual",
                reason="wrong_event",
                rerun_from="visual_director",
                timestamp_start_sec=12.4,
                timestamp_end_sec=17.8,
                required_visual="same-event interview",
            )
        ],
    )

    assert plan.patches[0].rerun_from == "visual_director"
```

**Step 2: Verify RED**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_content_planning_schema.py -v
```

Expected: FAIL because the new schema classes do not exist.

**Step 3: Implement minimal schema models**

Add Pydantic models to `clipper_agency/config/schema.py`. Keep fields JSON-serializable and mostly additive. Use `Literal` only where values are stable; otherwise use `str` to avoid over-constraining early rollout.

**Step 4: Verify GREEN**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_content_planning_schema.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/config/schema.py tests/test_content_planning_schema.py
git commit -m "feat: add job4 quality contract schemas"
```

---

## Task 0.2: Add quality configuration defaults

**Files:**

- Modify: `clipper_agency/config/schema.py`
- Test: `tests/test_config.py`

**Step 1: Write failing config test**

Add:

```python
def test_app_settings_include_quality_gate_defaults():
    from clipper_agency.config.schema import AppSettings

    settings = AppSettings()

    assert settings.quality.visual_coverage.black_frame_max_ms == 200
    assert settings.quality.visual_coverage.empty_frame_max_ms == 300
    assert settings.quality.visual_coverage.freeze_warning_ms == 1500
    assert settings.quality.visual_coverage.final_visual_gap_max_ms == 200
    assert settings.quality.text_collision.subtitle_overlap_max == 0.20
    assert settings.quality.safe_area.face_overlap_max == 0.15
    assert settings.quality.semantic_review.max_repair_cycles == 2
```

**Step 2: Verify RED**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_config.py::test_app_settings_include_quality_gate_defaults -v
```

Expected: FAIL because `quality` config does not exist.

**Step 3: Implement minimal config models**

Add:

- `VisualCoverageConfig`
- `TextCollisionConfig`
- `SafeAreaConfig`
- `SemanticReviewConfig`
- `QualityConfig`
- `quality: QualityConfig = Field(default_factory=QualityConfig)` on `AppSettings`

**Step 4: Verify GREEN**

Run the single test, then:

```bash
.venv/bin/python3 -m pytest tests/test_config.py -v
```

**Step 5: Batch 0 gate**

Run:

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass.

**Step 6: Commit**

```bash
git add clipper_agency/config/schema.py tests/test_config.py
git commit -m "feat: add quality gate configuration defaults"
```

---

# Batch 1 — Deterministic Core Modules

**Mode:** Parallel after Batch 0 passes.  
**Shared rule:** Workers must not modify agent files. Only create/modify assigned core modules and tests.

---

## Worker A / Task 1.1: Visual coverage detection contract

**Files:**

- Create: `clipper_agency/core/visual_coverage.py`
- Create: `tests/test_visual_coverage.py`

**Scope:** Determine whether rendered video meaningfully covers the voiceover timeline using injected detector results first, then FFmpeg/OpenCV implementations later.

**Step 1: Write failing tests**

```python
def test_visual_coverage_fails_when_black_segment_exceeds_threshold():
    from clipper_agency.core.visual_coverage import evaluate_visual_coverage


    result = evaluate_visual_coverage(
        output_duration_sec=21.2,
        voiceover_duration_sec=21.0,
        black_segments=[(17.83, 18.10)],
        freeze_segments=[],
        empty_segments=[],
        scene_segments=[(0.0, 21.2)],
        thresholds={"black_frame_max_ms": 200, "final_visual_gap_max_ms": 200},
    )

    assert result.status == "fail"
    assert result.issues[0].type == "BLACK_FRAME"


def test_visual_coverage_fails_when_final_visual_ends_before_audio():
    from clipper_agency.core.visual_coverage import evaluate_visual_coverage

    result = evaluate_visual_coverage(
        output_duration_sec=21.0,
        voiceover_duration_sec=21.0,
        black_segments=[],
        freeze_segments=[],
        empty_segments=[],
        scene_segments=[(0.0, 20.6)],
        thresholds={"black_frame_max_ms": 200, "final_visual_gap_max_ms": 200},
    )

    assert result.status == "fail"
    assert result.issues[0].type == "FINAL_VISUAL_GAP"
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_visual_coverage.py -v
```

Expected: FAIL because module does not exist.

**Step 3: Implement minimal pure evaluator**

Implement:

- `evaluate_visual_coverage(...) -> VisualCoverageResult`
- hard-fail issue types: `DURATION_SHORT`, `BLACK_FRAME`, `EMPTY_FRAME`, `MISSING_SCENE`, `FINAL_VISUAL_GAP`, `DECODE_FAILURE`
- warning/fail issue type: `FREEZE_FRAME` based on thresholds

Do not call FFmpeg yet in this task. Keep detector inputs injectable for fast unit tests.

**Step 4: Verify GREEN**

```bash
.venv/bin/python3 -m pytest tests/test_visual_coverage.py -v
```

**Step 5: Commit**

```bash
git add clipper_agency/core/visual_coverage.py tests/test_visual_coverage.py
git commit -m "feat: add visual coverage evaluator"
```

---

## Worker B / Task 1.2: Frame sampling and deduplication contract

**Files:**

- Create: `clipper_agency/core/frame_sampler.py`
- Create: `tests/test_frame_sampler.py`

**Scope:** Provide deterministic timestamp selection and perceptual-hash deduplication hooks for OCR and semantic inspection.

**Step 1: Write failing tests**

```python
def test_sample_timestamps_include_scene_starts_and_half_second_intervals():
    from clipper_agency.core.frame_sampler import plan_frame_samples

    samples = plan_frame_samples(
        duration_sec=2.0,
        scene_boundaries=[0.0, 1.25],
        interval_sec=0.5,
    )

    assert samples == [0.0, 0.5, 1.0, 1.25, 1.5, 2.0]


def test_deduplicate_samples_removes_repeated_hashes():
    from clipper_agency.core.frame_sampler import deduplicate_samples_by_hash

    samples = [(0.0, "aaa"), (0.5, "aaa"), (1.0, "bbb")]

    assert deduplicate_samples_by_hash(samples) == [(0.0, "aaa"), (1.0, "bbb")]
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_frame_sampler.py -v
```

**Step 3: Implement minimal functions**

Implement pure functions only:

- `plan_frame_samples(duration_sec, scene_boundaries, interval_sec=0.5) -> list[float]`
- `deduplicate_samples_by_hash(samples: list[tuple[float, str]]) -> list[tuple[float, str]]`

Leave actual image hashing as a later adapter to avoid test flakiness.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_frame_sampler.py -v
git add clipper_agency/core/frame_sampler.py tests/test_frame_sampler.py
git commit -m "feat: add frame sampling helpers"
```

---

## Worker C / Task 1.3: Text detection normalization contract

**Files:**

- Create: `clipper_agency/core/text_detection.py`
- Create: `tests/test_text_detection.py`

**Scope:** Normalize OCR outputs into consistent text regions with bounding boxes, area ratio, zone, and persistence. Do not require PaddleOCR in unit tests.

**Step 1: Write failing tests**

```python
def test_normalize_ocr_region_computes_area_ratio_and_zone():
    from clipper_agency.core.text_detection import normalize_text_region

    region = normalize_text_region(
        text="INI ALASAN RUBEN",
        confidence=0.96,
        bbox=[80, 980, 990, 1220],
        frame_size=(1080, 1920),
        timestamp_sec=4.5,
    )

    assert region.text == "INI ALASAN RUBEN"
    assert region.zone == "middle"
    assert region.area_ratio > 0


def test_filter_text_regions_keeps_large_low_confidence_possible_text():
    from clipper_agency.core.text_detection import filter_text_regions, normalize_text_region

    region = normalize_text_region(
        text="",
        confidence=0.35,
        bbox=[0, 500, 1080, 1000],
        frame_size=(1080, 1920),
        timestamp_sec=1.0,
    )

    assert filter_text_regions([region], min_confidence=0.6, large_area_ratio=0.20) == [region]
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_text_detection.py -v
```

**Step 3: Implement minimal normalization**

Implement:

- `normalize_text_region(...) -> DetectedTextRegion`
- `filter_text_regions(...) -> list[DetectedTextRegion]`
- zone calculation: top/middle/bottom based on vertical center thirds

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_text_detection.py -v
git add clipper_agency/core/text_detection.py tests/test_text_detection.py
git commit -m "feat: add OCR text region normalization"
```

---

## Worker D / Task 1.4: Text collision geometry

**Files:**

- Create: `clipper_agency/core/text_collision.py`
- Create: `tests/test_text_collision.py`

**Scope:** Detect overlap between source text, generated captions/headlines, watermarks, and unsafe zones.

**Step 1: Write failing tests**

```python
def test_overlap_ratio_detects_caption_collision_with_source_text():
    from clipper_agency.core.text_collision import detect_text_collisions


    issues = detect_text_collisions(
        source_regions=[{"bbox": [100, 900, 900, 1100], "text": "SOURCE", "timestamp_sec": 4.5}],
        generated_regions=[{"bbox": [120, 950, 880, 1150], "layer": "subtitle"}],
        thresholds={"subtitle_overlap_max": 0.20, "headline_overlap_max": 0.15},
    )

    assert issues
    assert issues[0].type == "SUBTITLE_SOURCE_TEXT_OVERLAP"


def test_source_text_density_warns_when_text_area_is_large():
    from clipper_agency.core.text_collision import detect_source_text_density

    issues = detect_source_text_density(
        source_regions=[{"bbox": [0, 0, 1080, 600], "text": "BIG"}],
        frame_size=(1080, 1920),
        warning_area_ratio=0.25,
        reject_area_ratio=0.40,
    )

    assert issues[0].type == "SOURCE_TEXT_DENSITY"
    assert issues[0].severity == "reject"
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_text_collision.py -v
```

**Step 3: Implement minimal geometry**

Implement:

- `bbox_area(bbox)`
- `intersection_area(a, b)`
- `overlap_ratio(a, b)`
- `detect_text_collisions(...) -> list[TextCollisionIssue]`
- `detect_source_text_density(...) -> list[TextCollisionIssue]`

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_text_collision.py -v
git add clipper_agency/core/text_collision.py tests/test_text_collision.py
git commit -m "feat: add text collision geometry"
```

---

## Worker E / Task 1.5: Safe-area and face overlap checks

**Files:**

- Create: `clipper_agency/core/safe_area.py`
- Create: `tests/test_safe_area.py`

**Scope:** Deterministic geometry for TikTok safe zones and face/caption overlap. Face detection model integration can remain an adapter later.

**Step 1: Write failing tests**

```python
def test_caption_inside_tiktok_unsafe_zone_is_rejected():
    from clipper_agency.core.safe_area import detect_safe_area_issues

    issues = detect_safe_area_issues(
        generated_regions=[{"bbox": [760, 1500, 1080, 1900], "layer": "subtitle"}],
        face_regions=[],
        frame_size=(1080, 1920),
        platform="tiktok",
        face_overlap_max=0.15,
    )

    assert issues[0].type == "PLATFORM_UNSAFE_ZONE"


def test_caption_overlapping_face_above_threshold_is_rejected():
    from clipper_agency.core.safe_area import detect_safe_area_issues

    issues = detect_safe_area_issues(
        generated_regions=[{"bbox": [400, 300, 700, 650], "layer": "headline"}],
        face_regions=[{"bbox": [420, 320, 680, 640], "confidence": 0.9}],
        frame_size=(1080, 1920),
        platform="tiktok",
        face_overlap_max=0.15,
    )

    assert issues[0].type == "FACE_TEXT_OVERLAP"
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_safe_area.py -v
```

**Step 3: Implement minimal checks**

Implement:

- `tiktok_unsafe_zones(frame_size) -> list[list[int]]`
- `detect_safe_area_issues(...) -> list[SafeAreaIssue]`

Reuse simple bbox intersection logic locally or import a small shared helper only if already created.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_safe_area.py -v
git add clipper_agency/core/safe_area.py tests/test_safe_area.py
git commit -m "feat: add safe area geometry checks"
```

---

## Batch 1 Gate

After Workers A-E complete, run:

```bash
.venv/bin/python3 -m pytest \
  tests/test_visual_coverage.py \
  tests/test_frame_sampler.py \
  tests/test_text_detection.py \
  tests/test_text_collision.py \
  tests/test_safe_area.py \
  -v

.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass.

---

# Batch 2 — Deterministic Agent Integration

**Mode:** Limited parallel. Composer diagnostics and Reviewer hard-gates can be implemented separately after Batch 1, then integrated together.

---

## Worker F / Task 2.1: Composer emits visual coverage diagnostics

**Files:**

- Modify: `clipper_agency/agents/composer.py`
- Test: `tests/test_composer.py`
- Optional fixture helper: `tests/test_job4_quality_regression.py`

**Step 1: Write failing Composer test**

Add a test that stubs detector outputs and asserts Composer stores/returns `visual_coverage` diagnostics after render.

```python
def test_composer_output_includes_visual_coverage_diagnostic(tmp_path, mocker):
    from clipper_agency.agents.composer import ComposerAgent
    from clipper_agency.config.schema import VisualCoverageResult

    mocker.patch(
        "clipper_agency.agents.composer.evaluate_visual_coverage",
        return_value=VisualCoverageResult(
            status="pass",
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            coverage_ratio=1.0,
            issues=[],
        ),
    )

    # Use existing composer test helper/input pattern.
    # Assert output["diagnostics"]["visual_coverage"]["status"] == "pass".
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_composer.py::test_composer_output_includes_visual_coverage_diagnostic -v
```

Expected: FAIL because Composer does not emit this diagnostic.

**Step 3: Implement minimal integration**

- Import/use `evaluate_visual_coverage` after rendering.
- Read output duration and voiceover duration from existing media metadata/manifest where available.
- Attach result under `output["diagnostics"]["visual_coverage"]`.
- Do not fail Composer directly unless an existing Composer hard-fail path already handles diagnostics; Reviewer owns final enforcement.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_composer.py -v
git add clipper_agency/agents/composer.py tests/test_composer.py
git commit -m "feat: emit visual coverage diagnostics from composer"
```

---

## Worker G / Task 2.2: Reviewer enforces deterministic gates before LLM review

**Files:**

- Modify: `clipper_agency/agents/reviewer.py`
- Test: `tests/test_agents_reviewer.py`
- Test: `tests/test_job4_quality_regression.py`

**Step 1: Write failing Reviewer test**

```python
def test_reviewer_blocks_visual_coverage_failure_before_llm(mocker):
    from clipper_agency.agents.reviewer import ReviewerAgent

    llm_call = mocker.patch("clipper_agency.agents.reviewer.LLMClient")
    reviewer = ReviewerAgent()

    result = reviewer.run({
        "video_path": "outputs/job_4/video.mp4",
        "diagnostics": {
            "visual_coverage": {
                "status": "fail",
                "issues": [{"type": "BLACK_FRAME", "severity": "hard_fail"}],
            }
        },
    })

    assert result["status"] == "failed"
    assert result["reason"] == "VISUAL_COVERAGE_FAILED"
    llm_call.assert_not_called()
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_agents_reviewer.py::test_reviewer_blocks_visual_coverage_failure_before_llm -v
```

Expected: FAIL because Reviewer does not yet check visual coverage first.

**Step 3: Implement minimal hard-gate order**

Reviewer hard-gate order:

1. Asset integrity
2. Output duration
3. Visual coverage
4. Black/freeze detection
5. Text collision
6. Face and safe-area compliance
7. Existing caption/narrative checks
8. LLM review

Add small helper methods to keep cognitive complexity low:

- `_fail_if_visual_coverage_failed(output)`
- `_fail_if_text_collision_failed(output)`
- `_fail_if_safe_area_failed(output)`

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_agents_reviewer.py tests/test_job4_quality_regression.py -v
git add clipper_agency/agents/reviewer.py tests/test_agents_reviewer.py tests/test_job4_quality_regression.py
git commit -m "feat: enforce deterministic reviewer quality gates"
```

---

## Batch 2 Gate

Run:

```bash
.venv/bin/python3 -m pytest tests/test_composer.py tests/test_agents_reviewer.py tests/test_job4_quality_regression.py -v
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass and Reviewer deterministic failures skip expensive LLM review.

---

# Batch 3 — Topic Scope, Story Mode, Duration Budget, Package Consistency

**Mode:** Parallel after Batch 2 passes.

---

## Worker H / Task 3.1: Story mode classifier

**Files:**

- Create: `clipper_agency/core/story_mode.py`
- Create: `tests/test_story_mode.py`

**Step 1: Write failing tests**

```python
def test_broad_entertainment_topic_classifies_as_roundup():
    from clipper_agency.core.story_mode import classify_story_mode

    decision = classify_story_mode("berita artis terbaru hari ini", target_duration_sec=30)

    assert decision.story_mode == "roundup"
    assert decision.requires_intro_card is True
    assert decision.item_count >= 2


def test_specific_clarification_topic_classifies_as_single_story():
    from clipper_agency.core.story_mode import classify_story_mode

    decision = classify_story_mode("Ruben akhirnya memberikan klarifikasi soal nafkah", target_duration_sec=30)

    assert decision.story_mode in {"single_story", "controversy_explainer", "breaking_news"}
    assert decision.item_count == 1
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_story_mode.py -v
```

**Step 3: Implement minimal deterministic classifier**

Use explicit phrase/rule matching first. Add LLM fallback only as a future extension; do not call external APIs in offline tests.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_story_mode.py -v
git add clipper_agency/core/story_mode.py tests/test_story_mode.py
git commit -m "feat: add deterministic story mode classifier"
```

---

## Worker I / Task 3.2: Duration budget allocation

**Files:**

- Create: `clipper_agency/core/duration_budget.py`
- Create: `tests/test_duration_budget.py`

**Step 1: Write failing tests**

```python
def test_roundup_duration_budget_allocates_intro_items_and_cta():
    from clipper_agency.core.duration_budget import allocate_duration_budget

    budget = allocate_duration_budget(story_mode="roundup", item_count=3, target_duration_sec=21)

    assert budget.target_duration_sec == 21
    assert [section.type for section in budget.sections] == ["intro", "story", "story", "story", "cta"]
    assert sum(section.duration_sec for section in budget.sections) == 21


def test_single_story_budget_allocates_hook_context_evidence_reveal_cta():
    from clipper_agency.core.duration_budget import allocate_duration_budget

    budget = allocate_duration_budget(story_mode="single_story", item_count=1, target_duration_sec=25)

    assert [section.type for section in budget.sections] == ["hook", "context", "evidence", "reveal", "cta"]
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_duration_budget.py -v
```

**Step 3: Implement minimal allocator**

Implement deterministic allocations for `roundup` and `single_story`; keep other modes as safe aliases until later.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_duration_budget.py -v
git add clipper_agency/core/duration_budget.py tests/test_duration_budget.py
git commit -m "feat: add editorial duration budget allocator"
```

---

## Worker J / Task 3.3: Segment Producer story-mode contract

**Files:**

- Modify: `clipper_agency/agents/segment_producer.py`
- Test: `tests/test_agents_segment_producer.py`
- Test: `tests/test_segment_producer_content_direction.py`

**Step 1: Write failing tests**

Add tests asserting Segment Producer output contains:

- `story_mode_decision`
- `duration_budget`
- `requires_intro_card` for roundup
- bounded story count based on duration

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py tests/test_segment_producer_content_direction.py -v
```

Expected: FAIL because output does not include new contract fields.

**Step 3: Implement minimal integration**

- Call `classify_story_mode(topic, target_duration_sec)` early.
- Call `allocate_duration_budget(...)` before finalizing story beats.
- Add serialized results to Segment Producer output.
- Preserve existing asset portfolio and no-watermark preference behavior.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py tests/test_segment_producer_content_direction.py -v
git add clipper_agency/agents/segment_producer.py tests/test_agents_segment_producer.py tests/test_segment_producer_content_direction.py
git commit -m "feat: add story mode contract to segment producer"
```

---

## Worker K / Task 3.4: Package consistency gate

**Files:**

- Create: `clipper_agency/core/package_consistency.py`
- Create: `tests/test_package_consistency.py`
- Modify later: `clipper_agency/agents/reviewer.py`

**Step 1: Write failing pure tests**

```python
def test_package_consistency_fails_thumbnail_single_story_for_roundup_video():
    from clipper_agency.core.package_consistency import evaluate_package_consistency

    result = evaluate_package_consistency(
        topic="berita artis terbaru hari ini",
        script="Kita bahas tiga kabar artis yang ramai hari ini...",
        thumbnail_text="Ruben Akhirnya Jujur",
        caption="Tiga kabar artis paling ramai hari ini",
        story_mode="roundup",
        main_entities=["Ruben", "A", "B"],
    )

    assert result.status == "fail"
    assert result.issue == "PACKAGE_SCOPE_MISMATCH"
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_package_consistency.py -v
```

**Step 3: Implement minimal deterministic heuristic**

Use story mode, entity count, and simple single-vs-roundup phrase rules. Do not add embeddings or LLM calls in the first pass.

**Step 4: Add Reviewer integration test**

Add test in `tests/test_agents_reviewer.py` asserting package consistency failure blocks before LLM review.

**Step 5: Implement Reviewer integration**

Call `evaluate_package_consistency` before LLM review when required fields are available.

**Step 6: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_package_consistency.py tests/test_agents_reviewer.py -v
git add clipper_agency/core/package_consistency.py tests/test_package_consistency.py clipper_agency/agents/reviewer.py tests/test_agents_reviewer.py
git commit -m "feat: add package consistency gate"
```

---

## Batch 3 Gate

Run:

```bash
.venv/bin/python3 -m pytest \
  tests/test_story_mode.py \
  tests/test_duration_budget.py \
  tests/test_package_consistency.py \
  tests/test_agents_segment_producer.py \
  tests/test_agents_reviewer.py \
  -v

.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass and every job can persist explicit story-mode and budget diagnostics.

---

# Batch 4 — Semantic Relevance and Repair Foundations

**Mode:** Parallel after Batch 3 passes.  
**Important:** This batch creates contracts and deterministic/rule-based scaffolding first. Vision-language model calls remain injectable and disabled in offline tests.

---

## Worker L / Task 4.1: Evidence contract extension for story beats

**Files:**

- Modify: `clipper_agency/config/schema.py`
- Modify: `clipper_agency/agents/segment_producer.py`
- Test: `tests/test_agents_segment_producer.py`

**Step 1: Write failing test**

Assert each story beat can include an `evidence_contract` with preferred/acceptable/forbidden visual guidance.

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py::test_story_beats_include_evidence_contract -v
```

**Step 3: Implement minimal additive field**

- Add optional `evidence_contract: EvidenceContract | None = None` to `StoryBeat` if not already present.
- Populate contracts from `visual_must_show` / `visual_must_not_show` and claim metadata where available.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py -v
git add clipper_agency/config/schema.py clipper_agency/agents/segment_producer.py tests/test_agents_segment_producer.py
git commit -m "feat: add evidence contracts to story beats"
```

---

## Worker M / Task 4.2: Semantic visual scoring contract

**Files:**

- Create: `clipper_agency/core/semantic_visual_review.py`
- Create: `tests/test_semantic_visual_review.py`

**Step 1: Write failing tests**

```python
def test_same_person_wrong_event_scores_as_reject():
    from clipper_agency.core.semantic_visual_review import score_visual_relevance

    score = score_visual_relevance(
        beat={"beat_id": "B04", "claim": {"subject": "Ruben", "action": "klarifikasi"}},
        asset_inspection={"person_match": 0.96, "event_match": 0.30, "claim_support": 0.20, "visual_quality": 0.82},
        weights={"person_match": 0.20, "event_match": 0.25, "claim_support": 0.25, "visual_quality": 0.05},
    )

    assert score.decision == "reject"
    assert score.misleading_risk > 0.5
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_semantic_visual_review.py -v
```

**Step 3: Implement deterministic score combiner**

No VLM calls yet. Implement:

- `score_visual_relevance(beat, asset_inspection, weights) -> VisualRelevanceScore`
- decision thresholds: accept/revise/reject
- misleading-risk calculation for high person match + low event/claim support

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_semantic_visual_review.py -v
git add clipper_agency/core/semantic_visual_review.py tests/test_semantic_visual_review.py
git commit -m "feat: add semantic visual relevance scoring contract"
```

---

## Worker N / Task 4.3: Repair router

**Files:**

- Create: `clipper_agency/core/repair_router.py`
- Create: `tests/test_repair_router.py`

**Step 1: Write failing tests**

```python
def test_repair_router_routes_wrong_event_to_visual_director():
    from clipper_agency.core.repair_router import route_repair

    patch = {"reason": "wrong_event", "action": "replace_visual"}

    assert route_repair(patch) == "visual_director"


def test_repair_router_routes_package_mismatch_to_segment_producer():
    from clipper_agency.core.repair_router import route_repair

    patch = {"reason": "package_mismatch", "action": "narrow_topic"}

    assert route_repair(patch) == "segment_producer"
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_repair_router.py -v
```

**Step 3: Implement minimal routing table**

Route:

- broken source URL → `visual_director`
- wrong event → `visual_director` by default; allow `segment_producer` if asset retrieval must be redone
- text collision → `visual_director`
- black frame → `composer`
- duration mismatch → `composer`
- package mismatch → `segment_producer`
- script scope mismatch → `segment_producer_and_scriptwriter`
- unsafe factual claim → `segment_producer_and_scriptwriter`

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_repair_router.py -v
git add clipper_agency/core/repair_router.py tests/test_repair_router.py
git commit -m "feat: add structured repair routing"
```

---

## Worker O / Task 4.4: Reviewer timestamp-level semantic feedback contract

**Files:**

- Modify: `clipper_agency/agents/reviewer.py`
- Test: `tests/test_agents_reviewer.py`

**Step 1: Write failing test**

Assert Reviewer can return a structured `repair_plan` with timestamp-level patches when semantic review reports `revise`.

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_agents_reviewer.py::test_reviewer_returns_repair_plan_for_semantic_visual_failure -v
```

**Step 3: Implement minimal contract handling**

- Parse semantic review results from diagnostics when available.
- Convert `revise`/`reject` timestamp results into `RepairPlan`.
- Respect `quality.semantic_review.max_repair_cycles`.
- Do not yet auto-rerun pipeline stages in Reviewer.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_agents_reviewer.py -v
git add clipper_agency/agents/reviewer.py tests/test_agents_reviewer.py
git commit -m "feat: add reviewer repair plan output"
```

---

## Batch 4 Gate

Run:

```bash
.venv/bin/python3 -m pytest \
  tests/test_semantic_visual_review.py \
  tests/test_repair_router.py \
  tests/test_agents_segment_producer.py \
  tests/test_agents_reviewer.py \
  -v

.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass and semantic review remains injectable/offline-safe.

---

# Batch 5 — Job #4 Regression Fixture and Final Integration

**Mode:** Sequential.

---

## Task 5.1: Convert Job #4 defects into deterministic regression fixture

**Files:**

- Modify: `tests/test_job4_quality_regression.py`
- Optional create: `tests/fixtures/job4/README.md`
- Optional create: `tests/fixtures/job4/diagnostics.json`

**Expected detected defects:**

- `BLACK_FRAME`
- `TEXT_COLLISION`
- `SOURCE_TEXT_DENSITY`
- `PACKAGE_SCOPE_MISMATCH`
- `ROUNDUP_FORMAT_WEAKNESS`
- `CLAIM_VISUAL_RELEVANCE_WEAKNESS`

**Step 1: Write failing regression test**

Use lightweight diagnostic fixture JSON rather than a large binary video unless the repo already has a suitable test asset.

```python
def test_job4_fixture_detects_expected_quality_defects():
    from clipper_agency.core.visual_coverage import evaluate_visual_coverage
    from clipper_agency.core.text_collision import detect_source_text_density
    from clipper_agency.core.package_consistency import evaluate_package_consistency

    # Arrange fixture data representing observed Job #4 defects.
    # Act through deterministic modules.
    # Assert expected failure codes are present.
```

**Step 2: Verify RED**

```bash
.venv/bin/python3 -m pytest tests/test_job4_quality_regression.py::test_job4_fixture_detects_expected_quality_defects -v
```

**Step 3: Implement fixture and minimal wiring**

Add fixture data and assertions. Keep it deterministic and offline.

**Step 4: Verify GREEN and commit**

```bash
.venv/bin/python3 -m pytest tests/test_job4_quality_regression.py -v
git add tests/test_job4_quality_regression.py tests/fixtures/job4
git commit -m "test: add job4 quality regression fixture"
```

---

## Task 5.2: Engine repair-cycle integration planning checkpoint

**Files:**

- Modify: `clipper_agency/orchestrator/engine.py` only if current engine has repair-cycle hooks ready
- Test: `tests/test_orchestrator_engine.py` or `tests/orchestrator/test_retry_timeline.py`

**Decision gate before implementation:**

Inspect current engine retry/resume structure. If adding repair-cycle execution would require broad refactor, stop and split into a follow-up plan. The minimum acceptable Batch 5 output is structured `RepairPlan` persistence plus clear routing; automated partial regeneration can be a later phase.

**TDD slice if engine hook is small:**

1. Write failing test: Engine receives Reviewer `RepairPlan` and chooses next agent from `repair_router`.
2. Verify RED.
3. Implement minimal route selection and max-cycle guard.
4. Verify GREEN.
5. Commit:

```bash
git add clipper_agency/orchestrator/engine.py tests/test_orchestrator_engine.py
git commit -m "feat: route reviewer repair plans through engine"
```

---

## Task 5.3: Documentation updates

Update canonical docs to reflect the new deterministic quality gates, story-mode contracts, semantic relevance foundations, and repair routing. **Do not update before code lands** — wait until Batch 5 to ensure docs match the exact implemented scope.

**Files:**

- Modify: `docs/PRD.md`
- Modify: `docs/SRS.md`
- Modify: `docs/technical_design.md`
- Modify: `docs/requirements_traceability.md`
- Create: `docs/adr/0022-job4-quality-gates-and-repair-routing.md`
- Modify: `AGENTS.md`
- Modify: `docs/plans/2026-06-09-job4-improvement-design.md` if status needs updating

### Documentation update mapping

| Doc | What to add | Timing |
|---|---:|---:|
| `docs/PRD.md` | Add product-level requirement for deterministic visual quality gates, package consistency, semantic visual relevance, and structured repair. Consider a new PR-30 entry. | After implementation |
| `docs/SRS.md` | Add FR-43..FR-50 for visual coverage, OCR/text collision, safe-area checks, story-mode decision, duration budget, package consistency, semantic review, repair routing. | After implementation |
| `docs/technical_design.md` | Add architecture details: new core modules (`visual_coverage.py`, `frame_sampler.py`, `text_detection.py`, `text_collision.py`, `safe_area.py`, `story_mode.py`, `duration_budget.py`, `package_consistency.py`, `semantic_visual_review.py`, `repair_router.py`), revised Reviewer hard-gate order, Composer diagnostics, repair routing table, no-new-agent decision. | After implementation |
| `docs/requirements_traceability.md` | Map new PRD/SRS requirements to design sections, edge cases, and validation tests. | After implementation |
| `docs/adr/0022-job4-quality-gates-and-repair-routing.md` | New ADR capturing the architecture decision. | After implementation |

### ADR decision summary

```text
docs/adr/0022-job4-quality-gates-and-repair-routing.md

Decision: Add deterministic visual quality gates, story-mode/package consistency
checks, semantic relevance contracts, and structured repair routing inside the
existing seven-agent architecture instead of introducing new top-level agents.

Context: Job #4 output analysis revealed black frames, text collisions,
package-scope mismatches, and claim-to-visual irrelevance that the existing
Reviewer gates did not catch.

Alternatives considered:
  1. Add new top-level agents for each quality area (rejected: more LLM calls,
     higher cost/latency, more state transitions, harder debugging,
     overlapping responsibilities).
  2. Extend existing agents with deterministic services (chosen: preserves
     architecture, cheaper, offline-testable, composable).
  3. Single monolithic quality service (rejected: lower composability,
     harder to test individual checks).

Consequences:
  - Reviewer LLM only runs after all deterministic gates pass.
  - Segment Producer owns story scope and evidence contracts.
  - Visual Director owns layout-level compliance (safe-area, text collision).
  - Composer owns frame-level technical quality (black/freeze, coverage).
  - Engine routes structured repairs to the correct existing agent.
  - New modules are pure functions with injected dependencies for
    offline testability.
```

**Step 1: Write/update docs after code is green**

Document:

- deterministic gates now run before Reviewer LLM;
- story-mode and duration-budget contract;
- semantic relevance scoring is contract-first and offline-safe;
- repair plans are structured and routed to existing agents;
- no new top-level agents were added.

**Step 2: Verify docs are consistent**

Read changed docs and ensure product requirements, technical design, and architecture remain separate. Use the adversarial review checklist from `docs/requirements_traceability.md` to verify cross-document alignment.

**Step 3: Commit**

```bash
git add docs/PRD.md docs/SRS.md docs/technical_design.md docs/requirements_traceability.md docs/adr/0022-job4-quality-gates-and-repair-routing.md AGENTS.md docs/plans/2026-06-09-job4-improvement-design.md
git commit -m "docs: document job4 quality gate rollout"
```

---

## Task 5.4: Final validation

**Files:** none expected.

**Step 1: Run targeted test groups**

```bash
.venv/bin/python3 -m pytest \
  tests/test_visual_coverage.py \
  tests/test_frame_sampler.py \
  tests/test_text_detection.py \
  tests/test_text_collision.py \
  tests/test_safe_area.py \
  tests/test_story_mode.py \
  tests/test_duration_budget.py \
  tests/test_package_consistency.py \
  tests/test_semantic_visual_review.py \
  tests/test_repair_router.py \
  tests/test_job4_quality_regression.py \
  -v
```

Expected: PASS.

**Step 2: Run full offline suite**

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass.

**Step 3: Optional coverage check before PR**

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" --cov=clipper_agency --cov-report=term-missing
```

Expected: coverage remains at or above current project threshold, currently documented around 93%.

---

## Recommended Branch and PR Workflow

Use the project branch workflow from `AGENTS.md`.

```bash
git checkout master
git pull origin master
git checkout -b phase/21-job4-quality-gates
```

After implementation and final validation:

```bash
git push -u origin phase/21-job4-quality-gates
gh pr create --base master --title "Phase 21: Job4 quality gates and repair contracts" --body "Implements deterministic visual gates, story-mode contracts, semantic relevance foundations, and structured repair routing per Job #4 improvement design."
```

Do not merge until SonarCloud Quality Gate passes.

---

## Implementation Stop Points

Stop and ask before continuing if any of these occur:

1. FFmpeg/OpenCV detector implementation requires new heavyweight dependencies.
2. Engine repair routing requires broad state-machine refactor.
3. VLM/embedding implementation would require paid API calls in offline tests.
4. Job #4 binary fixtures are too large for the repo.
5. Any batch gate fails after a worker reports completion.

---

## Definition of Done

This implementation is complete when:

- all new schema/config models exist and are JSON-serializable;
- deterministic visual coverage, frame sampling, text detection normalization, text collision, and safe-area checks are unit-tested;
- Composer emits structured visual quality diagnostics;
- Reviewer blocks deterministic failures before LLM review;
- Segment Producer emits story-mode and duration-budget decisions;
- package consistency is validated before approval;
- semantic visual relevance scoring and repair routing contracts exist;
- Job #4 defects are represented by a deterministic regression fixture;
- full offline test suite passes;
- docs/ADR/AGENTS are updated as needed;
- PR is opened and SonarCloud passes.
