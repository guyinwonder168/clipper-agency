# Job #4 Improvement Parallel TDD Implementation Plan 2

> **For Claude / Sub-agents:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and follow strict TDD for every task.

**Goal:** Complete the runtime implementation missing from Phase 21 / PR #44 by adding real media detectors, OCR and face adapters, story-mode reconciliation, multimodal visual inspection, Reviewer scene wiring, and enforced repair execution.

**Filename:** `2026-06-09-job4-improvement-parallel-tdd-implementation2.md`  
**Date:** 2026-06-09  
**Target baseline:** `master` after PR #44 merge (`d75dceced2694f7605f5fedb50d73c7ec05ad6b1`)  
**Recommended branch:** `phase/22-job4-runtime-quality-enforcement`  
**Architecture:** Extend the existing seven-agent architecture. Do not add new top-level agents. Add runtime adapters and orchestration wiring around the existing deterministic contracts from Phase 21.

---

# 1. Scope

PR #44 implemented:

- schemas and configuration contracts;
- pure visual coverage evaluator;
- pure frame-sampling planner;
- OCR result normalization;
- text-collision geometry;
- safe-area geometry;
- story-mode classifier;
- duration-budget allocator;
- package-consistency evaluator;
- semantic relevance score combiner;
- structured repair schema and routing foundation.

This plan implements the missing runtime layer:

1. Actual FFmpeg/OpenCV media inspection.
2. Actual frame extraction and perceptual hashing.
3. Actual OCR execution.
4. Actual face detection.
5. Actual text, face, and safe-area diagnostics.
6. Canonical story-mode reconciliation.
7. Actual multimodal keyframe inspection.
8. Candidate-level visual semantic scoring.
9. Reviewer scene/timestamp wiring.
10. Quality-status and publication blocking.
11. Automated bounded repair cycles.
12. Before/after repair quality tracking.

---

# 2. Non-Goals

This plan does not include:

- direct publishing to TikTok, Instagram, or YouTube;
- analytics collection;
- engagement learning loop;
- new Creative Director agent;
- background-music implementation;
- watermark removal through generative inpainting;
- full dynamic subject tracking;
- PostgreSQL migration;
- multi-worker production queue;
- Kubernetes or distributed execution.

---

# 3. Core Design Decisions

## 3.1 No New Top-Level Agents

Responsibilities remain:

| Responsibility | Owner |
|---|---|
| Story mode and evidence intent | Segment Producer |
| Candidate asset selection and layout | Visual Director |
| Render and technical media analysis | Composer |
| Final deterministic and semantic validation | Reviewer |
| Repair routing and execution | Engine |

## 3.2 Runtime Adapters Around Existing Pure Functions

Existing pure functions remain authoritative for business rules.

New runtime adapters only:

- acquire media data;
- transform it into existing schemas;
- invoke existing evaluators;
- persist diagnostics.

## 3.3 Two-Pass Visual Validation

### Pre-render pass

Performed before asset selection is finalized:

```text
candidate asset
→ frame extraction
→ OCR
→ face detection
→ VLM semantic inspection
→ candidate score
→ accept / revise / reject
```

### Post-render pass

Performed after final composition:

```text
final video
→ black/freeze/empty-frame scan
→ final OCR
→ caption/source text collision
→ face/safe-area validation
→ timestamp semantic review
→ approve / repair / reject
```

## 3.4 Strict Status Separation

The following statuses must be separate:

```text
execution_status
quality_status
publication_status
repair_status
```

Example:

```json
{
  "execution_status": "completed",
  "quality_status": "failed",
  "publication_status": "blocked",
  "repair_status": "pending"
}
```

A completed process is not automatically an approved video.



## 3.6 Mandatory LLM Traceability Rule

Every LLM and multimodal model invocation must be traceable without relying only on aggregate token logs.

The current operational log style:

```text
LLM request: model=... messages=2 input_chars=...
LLM response: model=... tokens_in=... tokens_out=... cost=... latency=...
```

is insufficient for debugging prompt behavior, schema failures, semantic mistakes, or inconsistent agent decisions.

The implementation must distinguish:

```text
Operational log
→ concise metadata for runtime monitoring

Structured trace artifact
→ resolved request and response content for debugging and audit
```

### Operational log requirements

`run-job_{job_id}.log` should include:

```text
LLM call started:
job_id
agent
task
call_id
model
provider
prompt_template_id
prompt_version
message_count
text_character_count
image_count
request_artifact_path

LLM call completed:
call_id
provider_request_id
http_status
tokens_in
tokens_out
cost
latency
finish_reason
response_artifact_path
parse_status
schema_validation_status
retry_count
```

The operational log should not print the complete prompt or response by default.

### Structured trace artifact requirements

Every call must persist:

```text
data/assets/cache/job_{job_id}/llm_traces/
└── {agent}/
    └── {call_id}/
        ├── request.json
        ├── response.json
        ├── parsed_response.json
        ├── validation.json
        └── metadata.json
```

For multimodal calls:

```text
        ├── image_manifest.json
        └── images/
```

Images may be referenced by canonical artifact path and SHA-256 hash instead of duplicated.

### `request.json`

Must contain:

- agent name;
- task name;
- model and provider;
- system prompt after template resolution;
- user prompt after template resolution;
- complete ordered message list;
- prompt template path or ID;
- prompt version/hash;
- structured response schema requested;
- model parameters such as temperature and max tokens;
- referenced image paths/hashes for multimodal calls;
- request timestamp;
- correlation IDs.

### `response.json`

Must contain:

- provider request/generation ID;
- raw textual response;
- raw tool-call or structured-output payload where applicable;
- finish reason;
- provider usage object;
- HTTP status;
- retry attempt;
- response timestamp.

### `parsed_response.json`

Must contain the application-level parsed result actually passed to the agent.

This is important because:

```text
raw model response
≠ parsed result
≠ persisted agent output
```

All three layers must remain distinguishable.

### `validation.json`

Must contain:

- JSON parse result;
- schema validation result;
- validation errors;
- fallback or repair parsing performed;
- fields dropped or defaulted;
- whether the response was accepted, retried, or rejected.

### Security and redaction

Before persistence, redact:

- API keys;
- Authorization headers;
- cookies;
- signed download URLs where required;
- passwords or credentials;
- personal secrets configured by the user;
- raw binary/audio payloads.

Do not redact ordinary story content, prompts, model answers, or source URLs unless configured by policy.

### Configuration

```yaml
observability:
  llm_traces:
    enabled: true
    persist_resolved_prompts: true
    persist_raw_responses: true
    persist_parsed_responses: true
    persist_validation_results: true
    log_full_payload_inline: false
    redact_secrets: true
    retention_days: 30
```

### Failure behavior

Failure to write a trace artifact must:

- emit an explicit warning;
- not silently disappear;
- not fail content generation by default;
- become a hard failure when `observability.llm_traces.required=true`.


## 3.5 Mandatory Output Lifecycle Rule

The implementation must enforce the following rule:

```text
Blocked does not mean deleted.
Blocked means non-publishable.
```

When a Reviewer or deterministic quality gate fails:

- the generated candidate video must remain available;
- the thumbnail, captions, logs, diagnostics, keyframes, OCR output, semantic inspection, and repair plan must remain available;
- the candidate must be marked as `rejected`;
- the candidate must not enter the publishing queue;
- the Engine must start a repair cycle when a valid `RepairPlan` exists and the configured repair-cycle limit has not been reached;
- only a candidate that later passes review may be promoted to the final publishable artifact.

### Required artifact states

```text
candidate
rejected
repairing
approved
repair_exhausted
manual_review_required
```

### Required lifecycle

Successful first pass:

```text
candidate
→ approved
→ publication_status=ready
```

Failed first pass with successful repair:

```text
candidate
→ rejected
→ repairing
→ candidate
→ approved
→ publication_status=ready
```

Failed first pass with exhausted repairs:

```text
candidate
→ rejected
→ repairing
→ rejected
→ repair_exhausted
→ manual_review_required
→ publication_status=blocked
```

### Required artifact retention

Every render attempt must be retained under a cycle-specific path:

```text
data/assets/cache/job_{job_id}/outputs/
├── cycle_0/
│   ├── video.mp4
│   ├── thumbnail.jpg
│   ├── metadata.json
│   └── artifact_status.json
├── cycle_1/
│   ├── video.mp4
│   ├── thumbnail.jpg
│   ├── metadata.json
│   └── artifact_status.json
└── final/
    ├── video.mp4
    ├── thumbnail.jpg
    ├── metadata.json
    └── artifact_status.json
```

A rejected artifact must never be overwritten by a later repair cycle.

### Final promotion rule

The system may copy or promote an artifact into `outputs/final/` only when:

```text
quality_status == passed
AND publication_status == ready
AND artifact_status == approved
```

The existence of a rendered MP4 alone must never imply approval.

---

# 4. Global Execution Rules

1. TDD is mandatory.
2. Every task starts with a failing test.
3. A sub-agent may only modify files assigned to its task.
4. Shared integration files are modified only in sequential integration batches.
5. All external API/model calls must be injectable and mockable.
6. Offline test suite must not make paid API calls.
7. Use the existing virtual environment:

   ```bash
   .venv/bin/python3 -m ...
   ```

8. Full offline gate:

   ```bash
   .venv/bin/python3 -m pytest -m "not external and not integration" -q
   ```

9. Commit after every green task.
10. Do not broaden scope while implementing a task.
11. Persist all runtime diagnostics as JSON.
12. Do not silently downgrade hard failures to warnings.
13. Repair cycles must never exceed configured limits.
14. All generated keyframe and inspection artifacts must be traceable to job, beat, scene, and asset.

---

# 5. Parallel Dependency Graph

```text
Batch 0 — Runtime Contracts and Feature Flags (sequential)
  ↓
Batch 1 — Media Inspection Adapters (parallel A-D)
  ↓
Batch 2 — OCR, Face, and Final Layout Diagnostics (parallel E-H)
  ↓
Batch 3 — Story-Mode Reconciliation and Propagation (parallel I-K, then integration)
  ↓
Batch 4 — Multimodal Candidate Inspection (parallel L-O)
  ↓
Batch 5 — Reviewer Scene Wiring and Final Semantic Review (limited parallel P-R)
  ↓
Batch 6 — Repair Enforcement and Status Model (sequential S-U)
  ↓
Batch 7 — Job #5 Regression and Production Validation (sequential)
```

## Safe Parallelism Summary

| Batch | Parallel? | Reason |
|---|---:|---|
| Batch 0 | No | Shared schemas, paths, flags |
| Batch 1 | Yes | Independent media adapters |
| Batch 2 | Yes | Independent OCR, face, and geometry adapters |
| Batch 3 | Limited | Core classifier and propagation can split; Segment Producer integration is shared |
| Batch 4 | Yes | Keyframe persistence, VLM adapter, scoring, cache can split |
| Batch 5 | Limited | Reviewer and Composer/Visual Director outputs touch shared contracts |
| Batch 6 | No | Engine status machine and repair cycles require coordinated changes |
| Batch 7 | No | End-to-end validation |

---

# Batch 0 — Runtime Contracts, Paths, and Feature Flags

**Mode:** Sequential  
**Gate:** Schema/config tests and full offline suite pass.

## Task 0.1 — Add Runtime Inspection Models

**Files:**

- Modify: `clipper_agency/config/schema.py`
- Modify: `tests/test_content_planning_schema.py`

**Models to add:**

- `ExtractedFrame`
- `FrameExtractionManifest`
- `OCRInspectionResult`
- `FaceRegion`
- `FaceInspectionResult`
- `AssetSemanticInspection`
- `SceneSemanticReview`
- `QualityStatus`
- `RepairCycleRecord`

### Required fields

```python
class ExtractedFrame(BaseModel):
    timestamp_sec: float
    path: str
    perceptual_hash: str
    width: int
    height: int

class FrameExtractionManifest(BaseModel):
    asset_id: str
    beat_id: str
    source_path: str
    frames: list[ExtractedFrame]

class AssetSemanticInspection(BaseModel):
    asset_id: str
    beat_id: str
    person_match: float
    event_match: float
    claim_support: float
    visual_quality: float
    temporal_match: float = 0.0
    source_credibility: float = 0.0
    cleanliness_score: float = 0.0
    misleading_risk: float
    decision: str
    reason: str
    frame_paths: list[str]
    model: str
```

### TDD

Write tests asserting:

- JSON serialization.
- `frame_paths` persist.
- scores are bounded from 0 to 1.
- `RepairCycleRecord` tracks cycle, source agent, target agent, and before/after scores.

### Commit

```bash
git commit -m "feat: add runtime visual inspection schemas"
```

---

## Task 0.2 — Add Runtime Feature Flags

**Files:**

- Modify: `clipper_agency/config/schema.py`
- Modify: `tests/test_config.py`

### Configuration

```yaml
quality:
  runtime_inspection:
    enabled: true
    persist_keyframes: true
    frame_interval_sec: 0.5
    max_frames_per_asset: 8
    perceptual_hash_distance: 6

  ocr:
    enabled: true
    provider: paddleocr
    min_confidence: 0.55
    large_region_area_ratio: 0.20

  face_detection:
    enabled: true
    provider: mediapipe
    min_confidence: 0.60

  semantic_review:
    enabled: true
    provider: existing_multimodal_llm
    max_assets_per_beat: 3
    max_frames_per_asset: 4
    minimum_claim_support: 0.70
    maximum_misleading_risk: 0.30
    max_repair_cycles: 2

  enforcement:
    block_on_reviewer_fail: true
    block_publication_on_quality_fail: true
```

### Commit

```bash
git commit -m "feat: add runtime inspection feature flags"
```

---

## Task 0.3 — Add Canonical Artifact Paths

**Files:**

- Create: `clipper_agency/core/inspection_paths.py`
- Create: `tests/test_inspection_paths.py`

### Canonical layout

```text
data/assets/cache/job_{job_id}/
├── inspections/
│   ├── candidates/
│   │   └── beat_{beat_id}/asset_{asset_id}/
│   │       ├── keyframes/
│   │       ├── frame_manifest.json
│   │       ├── ocr.json
│   │       ├── faces.json
│   │       └── semantic.json
│   └── final/
│       ├── keyframes/
│       ├── frame_manifest.json
│       ├── ocr.json
│       ├── faces.json
│       ├── visual_coverage.json
│       └── semantic_review.json
└── repair/
    └── cycle_{n}.json
```

### Functions

```python
candidate_inspection_dir(cache_root, job_id, beat_id, asset_id)
final_inspection_dir(cache_root, job_id)
repair_cycle_path(cache_root, job_id, cycle)
```

### Commit

```bash
git commit -m "feat: add canonical inspection artifact paths"
```

---


## Task 0.4 — Add LLM Trace Contracts and Artifact Writer

**Files:**

- Create: `clipper_agency/observability/llm_trace.py`
- Create: `clipper_agency/observability/redaction.py`
- Create: `tests/test_llm_trace.py`
- Create: `tests/test_llm_trace_redaction.py`
- Modify: configuration schema/tests as needed

### Models

```python
class LLMTraceMetadata(BaseModel):
    call_id: str
    job_id: int
    agent: str
    task: str
    provider: str
    model: str
    prompt_template_id: str
    prompt_version: str
    request_timestamp: str
    response_timestamp: str | None
    provider_request_id: str | None
    retry_count: int
    latency_sec: float | None
    tokens_in: int | None
    tokens_out: int | None
    cost: float | None
    finish_reason: str | None
    parse_status: str
    schema_validation_status: str
```

### Writer interface

```python
class LLMTraceWriter:
    def start_call(...) -> TraceHandle:
        ...

    def persist_request(handle, messages, parameters, image_manifest=None) -> Path:
        ...

    def persist_response(handle, raw_response, usage, provider_metadata) -> Path:
        ...

    def persist_parsed_response(handle, parsed_result) -> Path:
        ...

    def persist_validation(handle, validation_result) -> Path:
        ...
```

### Mandatory TDD tests

```python
def test_llm_trace_persists_resolved_request_and_raw_response(tmp_path):
    writer = build_trace_writer(tmp_path)

    handle = writer.start_call(
        job_id=5,
        agent="reviewer",
        task="final_editorial_review",
        provider="openrouter",
        model="gemini-2.5-flash",
        prompt_template_id="reviewer.md",
        prompt_version="sha256:test",
    )

    request_path = writer.persist_request(
        handle,
        messages=[
            {"role": "system", "content": "You are a reviewer."},
            {"role": "user", "content": "Review this video package."},
        ],
        parameters={"temperature": 0.2},
    )
    response_path = writer.persist_response(
        handle,
        raw_response={"content": '{"verdict":"fail"}'},
        usage={"prompt_tokens": 100, "completion_tokens": 10},
        provider_metadata={"request_id": "gen-123"},
    )

    assert request_path.exists()
    assert response_path.exists()
    assert "Review this video package" in request_path.read_text()
    assert '"verdict":"fail"' in response_path.read_text()


def test_llm_trace_persists_raw_parsed_and_validation_as_separate_layers(tmp_path):
    writer = build_trace_writer(tmp_path)
    handle = make_trace_handle(writer)

    writer.persist_response(handle, {"content": "```json\n{\"score\":40}\n```"}, {}, {})
    writer.persist_parsed_response(handle, {"score": 40})
    writer.persist_validation(
        handle,
        {
            "json_parse": "passed_after_markdown_strip",
            "schema_validation": "passed",
        },
    )

    assert trace_file(handle, "response.json").exists()
    assert trace_file(handle, "parsed_response.json").exists()
    assert trace_file(handle, "validation.json").exists()


def test_llm_trace_redacts_api_keys_and_authorization_headers(tmp_path):
    payload = {
        "headers": {"Authorization": "Bearer secret-key"},
        "api_key": "sk-secret",
        "messages": [{"role": "user", "content": "ordinary content remains"}],
    }

    redacted = redact_trace_payload(payload)

    assert "secret-key" not in json.dumps(redacted)
    assert "sk-secret" not in json.dumps(redacted)
    assert "ordinary content remains" in json.dumps(redacted)
```

### Commit

```bash
git commit -m "feat: add structured llm trace artifacts"
```


## Batch 0 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_content_planning_schema.py \
  tests/test_config.py \
  tests/test_inspection_paths.py \
  tests/test_llm_trace.py \
  tests/test_llm_trace_redaction.py \
  -v

.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

---

# Batch 1 — Media Inspection Adapters

**Mode:** Parallel workers A-D.  
**Restriction:** Do not modify agent files.

---

## Worker A — Task 1.1: FFmpeg Black and Freeze Detector

**Files:**

- Create: `clipper_agency/core/media_detectors.py`
- Create: `tests/test_media_detectors.py`

### Functions

```python
detect_black_segments(video_path, min_duration_sec, pixel_threshold) -> list[tuple[float, float]]
detect_freeze_segments(video_path, min_duration_sec, noise_threshold) -> list[tuple[float, float]]
```

### Implementation

Run FFmpeg subprocess with:

```text
blackdetect
freezedetect
```

Parse stderr into intervals.

### TDD

Use fixture stderr text first. Add subprocess adapter tests with mocked process output.

Do not require FFmpeg in unit tests.

### Acceptance

- Parses multiple black segments.
- Parses multiple freeze intervals.
- Handles missing end markers safely.
- Raises typed error for failed subprocess.

### Commit

```bash
git commit -m "feat: add ffmpeg black and freeze detectors"
```

---

## Worker B — Task 1.2: Empty and Uniform Frame Detector

**Files:**

- Create: `clipper_agency/core/frame_quality.py`
- Create: `tests/test_frame_quality.py`

### Functions

```python
compute_frame_variance(image) -> float
is_empty_or_uniform_frame(image, threshold) -> bool
detect_empty_segments(sampled_frames, max_gap_sec) -> list[tuple[float, float]]
```

### Implementation

Use OpenCV-compatible NumPy arrays. Keep imports optional.

### Acceptance

- Pure black frame detected.
- Solid-color frame detected.
- Normal photo not detected.
- Consecutive empty frames merge into intervals.

### Commit

```bash
git commit -m "feat: add empty frame quality detector"
```

---

## Worker C — Task 1.3: Actual Frame Extraction

**Files:**

- Create: `clipper_agency/core/frame_extractor.py`
- Create: `tests/test_frame_extractor.py`

### Functions

```python
extract_frames(
    video_path,
    timestamps,
    output_dir,
    ffmpeg_runner,
) -> list[ExtractedFrame]
```

### Requirements

- use existing `plan_frame_samples`;
- extract JPEG or PNG through FFmpeg;
- persist deterministic filenames;
- probe width/height;
- tolerate one failed timestamp without losing successful frames;
- record extraction errors.

### Filename format

```text
frame_000000ms.jpg
frame_000500ms.jpg
```

### Tests

Mock FFmpeg runner and generated files.

### Commit

```bash
git commit -m "feat: add runtime frame extraction"
```

---

## Worker D — Task 1.4: Perceptual Hash Adapter

**Files:**

- Create: `clipper_agency/core/frame_hash.py`
- Create: `tests/test_frame_hash.py`

### Functions

```python
compute_perceptual_hash(image_path) -> str
hash_distance(hash_a, hash_b) -> int
deduplicate_extracted_frames(frames, max_distance) -> list[ExtractedFrame]
```

### Requirements

- use imagehash/Pillow or small internal implementation;
- deduplicate near-identical frames, not only exact hashes;
- preserve first timestamp;
- keep scene-boundary frame if duplicate with prior interval frame.

### Commit

```bash
git commit -m "feat: add perceptual frame hashing"
```

---

## Batch 1 Integration Task 1.5 — Candidate Frame Inspection Pipeline

**Mode:** Sequential after A-D.

**Files:**

- Create: `clipper_agency/core/frame_inspection_pipeline.py`
- Create: `tests/test_frame_inspection_pipeline.py`

### Flow

```text
probe duration
→ plan timestamps
→ extract frames
→ calculate hash
→ deduplicate
→ cap max frames
→ persist manifest
```

### Output

`FrameExtractionManifest`

### Commit

```bash
git commit -m "feat: add candidate frame inspection pipeline"
```

---

## Batch 1 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_media_detectors.py \
  tests/test_frame_quality.py \
  tests/test_frame_extractor.py \
  tests/test_frame_hash.py \
  tests/test_frame_inspection_pipeline.py \
  -v
```

---

# Batch 2 — OCR, Face Detection, and Final Layout Diagnostics

**Mode:** Parallel workers E-H.

---

## Worker E — Task 2.1: PaddleOCR Runtime Adapter

**Files:**

- Create: `clipper_agency/core/ocr_adapter.py`
- Create: `tests/test_ocr_adapter.py`

### Interface

```python
class OCRAdapter(Protocol):
    def inspect(self, image_path: str, timestamp_sec: float) -> OCRInspectionResult:
        ...
```

Implement:

```python
class PaddleOCRAdapter:
    ...
```

### Requirements

- lazy import PaddleOCR;
- model loaded once per process;
- normalize output through existing `normalize_text_region`;
- keep bounding boxes even when recognized text confidence is low but area is large;
- record provider and model metadata.

### Tests

Mock PaddleOCR output. Do not load model offline.

### Commit

```bash
git commit -m "feat: add paddleocr runtime adapter"
```

---

## Worker F — Task 2.2: Face Detection Runtime Adapter

**Files:**

- Create: `clipper_agency/core/face_adapter.py`
- Create: `tests/test_face_adapter.py`

### Interface

```python
class FaceDetector(Protocol):
    def detect(self, image_path: str, timestamp_sec: float) -> FaceInspectionResult:
        ...
```

Default:

```python
MediaPipeFaceDetector
```

### Requirements

- lazy model initialization;
- normalized pixel bounding boxes;
- confidence threshold;
- primary-face selection by area and centrality;
- no identity recognition in this task.

### Commit

```bash
git commit -m "feat: add face detection runtime adapter"
```

---

## Worker G — Task 2.3: Caption Bounding-Box Manifest

**Files:**

- Create: `clipper_agency/core/generated_text_manifest.py`
- Create: `tests/test_generated_text_manifest.py`

### Purpose

Composer already knows subtitle/headline coordinates. Persist them for Reviewer.

### Schema

```json
{
  "timestamp_start_sec": 4.0,
  "timestamp_end_sec": 6.5,
  "layer": "subtitle",
  "bbox": [120, 1480, 960, 1740],
  "text": "..."
}
```

### Functions

```python
build_generated_text_regions(render_plan, frame_size)
regions_at_timestamp(regions, timestamp_sec)
```

### Commit

```bash
git commit -m "feat: add generated text region manifest"
```

---

## Worker H — Task 2.4: Source Cleanliness Scoring

**Files:**

- Create: `clipper_agency/core/source_cleanliness.py`
- Create: `tests/test_source_cleanliness.py`

### Score Inputs

- OCR text area ratio;
- logo/watermark persistence;
- safe crop availability;
- face obstruction;
- resolution;
- burned-caption persistence.

### Output

```json
{
  "cleanliness_score": 0.38,
  "issues": [
    "BURNED_CAPTION",
    "DOMINANT_LOGO"
  ],
  "fullscreen_allowed": false,
  "allowed_treatments": [
    "picture_in_picture",
    "replace_asset"
  ]
}
```

### Commit

```bash
git commit -m "feat: add source cleanliness scoring"
```

---

## Batch 2 Integration Task 2.5 — Final Layout Inspection Pipeline

**Mode:** Sequential.

**Files:**

- Create: `clipper_agency/core/final_layout_inspection.py`
- Create: `tests/test_final_layout_inspection.py`

### Flow

```text
final frame manifest
→ OCR every unique frame
→ face detection
→ generated text regions at timestamp
→ text collision
→ source text density
→ safe-area check
→ persist diagnostics
```

### Output

```json
{
  "text_collision": [],
  "safe_area": [],
  "ocr_summary": {},
  "face_summary": {}
}
```

### Commit

```bash
git commit -m "feat: add final layout inspection pipeline"
```

---

## Batch 2 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_ocr_adapter.py \
  tests/test_face_adapter.py \
  tests/test_generated_text_manifest.py \
  tests/test_source_cleanliness.py \
  tests/test_final_layout_inspection.py \
  -v
```

---

# Batch 3 — Canonical Story Mode and Duration Propagation

**Mode:** Workers I-K in parallel, then sequential integration.

---

## Worker I — Task 3.1: Expand Story-Mode Rules

**Files:**

- Modify: `clipper_agency/core/story_mode.py`
- Modify: `tests/test_story_mode.py`

### Must classify as roundup

```text
berita hot gossip artist indonesia terbaru
gosip artis hari ini
kabar selebriti terbaru
top gossip hari ini
update artis terbaru
```

### Add normalization

- artist/artis;
- gossip/gosip;
- latest/terbaru;
- today/hari ini;
- plural intent;
- category-level topics.

### Commit

```bash
git commit -m "fix: classify broad entertainment topics as roundup"
```

---

## Worker J — Task 3.2: Decision Reconciliation Module

**Files:**

- Create: `clipper_agency/core/story_decision_reconciliation.py`
- Create: `tests/test_story_decision_reconciliation.py`

### Function

```python
reconcile_story_decisions(
    story_mode_decision,
    legacy_format_decision,
    story_beats,
) -> StoryModeDecision
```

### Rules

1. Explicit user mode wins.
2. More than one distinct story entity implies roundup unless explicitly overridden.
3. Legacy `three_story_roundup` cannot coexist with canonical `single_story`.
4. Reconciled decision must produce diagnostic reason.
5. Contradiction must be persisted.

### Commit

```bash
git commit -m "feat: reconcile story mode and legacy format decisions"
```

---

## Worker K — Task 3.3: Thumbnail and CTA Strategy Propagation

**Files:**

- Create: `clipper_agency/core/story_mode_contract.py`
- Create: `tests/test_story_mode_contract.py`

### Derived contract

For roundup:

```json
{
  "requires_intro_card": true,
  "thumbnail_strategy": "multi_entity_roundup",
  "cta_strategy": "compare_items",
  "duration_structure": "intro_story_items_cta"
}
```

For single story:

```json
{
  "requires_intro_card": false,
  "thumbnail_strategy": "single_claim",
  "cta_strategy": "opinion_or_followup",
  "duration_structure": "hook_context_evidence_reveal_cta"
}
```

### Commit

```bash
git commit -m "feat: derive visual contract from canonical story mode"
```

---

## Batch 3 Integration Task 3.4 — Segment Producer Canonical Mode

**Mode:** Sequential.

**Files:**

- Modify: `clipper_agency/agents/segment_producer.py`
- Modify: `tests/test_agents_segment_producer.py`
- Modify: `tests/test_segment_producer_content_direction.py`

### Required changes

- classify early;
- reconcile after LLM output;
- persist only one canonical `story_mode_decision`;
- preserve legacy `format_decision` only as derived compatibility output;
- allocate duration from reconciled mode;
- enforce item count;
- propagate thumbnail and CTA strategy;
- emit contradiction diagnostics.

### Acceptance

For Job #5 topic:

```json
{
  "story_mode": "roundup",
  "item_count": 3,
  "requires_intro_card": true,
  "thumbnail_strategy": "multi_entity_roundup"
}
```

Duration sections must be:

```text
intro
story
story
story
cta
```

### Commit

```bash
git commit -m "fix: make story mode canonical in segment producer"
```

---

## Batch 3 Integration Task 3.5 — SP Source Quality Refactor

**Mode:** Sequential. Depends on Task 3.4.

**Files:**

- Modify: `clipper_agency/agents/segment_producer.py`
- Modify: `clipper_agency/config/schema.py` (add `source_type` field to candidate schema)
- Modify: `tests/test_agents_segment_producer.py`
- Create: `tests/test_source_quality_tiers.py`

### Rationale

`_build_asset_candidates_from_sources()` hardcodes exactly 2 sources (ScrapeCreators=0.9, Firecrawl=0.7). The dead-code `_build_asset_portfolio()` at line 495 already has per-beat keyword scoring but is never called from `execute()`. This task refactors the interface so Batch 8 providers can plug in without modifying SP core logic.

### 3.5.1 — Source quality tiers constant

Create a module-level constant replacing hardcoded scores:

```python
SOURCE_QUALITY_TIERS: dict[str, float] = {
    "youtube_official": 0.95,
    "web_video": 0.85,
    "tiktok_clip": 0.50,   # downgraded from 0.9 — watermark/hardcoded subs
    "image": 0.70,
    "article": 0.40,
    "firecrawl": 0.30,
}
```

Default tier for unknown source types: 0.40.

### 3.5.2 — Generic source interface

Refactor `_build_asset_candidates_from_sources()` signature:

```python
# Before (hardcoded 2 sources):
def _build_asset_candidates_from_sources(
    firecrawl_data: list[dict], scrapecreators_data: list[dict],
) -> list[dict]:

# After (generic, source_type-driven):
def _build_asset_candidates_from_sources(
    sources: list[dict],
) -> list[dict]:
```

Each source dict must include `"source_type"` (str). The method maps `source_type` → `SOURCE_QUALITY_TIERS` for base score, then applies keyword relevance scoring.

Preserve backward compat: existing callers pass `scrapecreators_data` items with `source_type: "tiktok_clip"` and `firecrawl_data` items with `source_type: "firecrawl"`.

### 3.5.3 — Wire `_build_asset_portfolio()` into `execute()`

Replace the flat call at line 193:

```python
# Before:
discovered_candidates = self._build_asset_candidates_from_sources(
    firecrawl_data, scrapecreators_data,
)

# After: per-beat scoring via portfolio
all_sources = _normalize_sources(firecrawl_data, scrapecreators_data)
discovered_candidates = self._build_asset_portfolio(
    all_sources, beat_keywords=extracted_keywords,
)
```

Where `extracted_keywords` comes from `story_beats` synthesis output. If no beats yet (early in pipeline), fall back to topic words.

### 3.5.4 — Add `source_type` to candidate output

Every candidate dict must include `"source_type"` field. Update `AssetCandidate` in `config/schema.py` if it exists, or add to the dict construction in `_build_*_candidates()` helpers.

### Acceptance

1. `SOURCE_QUALITY_TIERS` constant exists and is used for all score assignments
2. ScrapeCreators candidates score 0.50 (down from 0.9)
3. Firecrawl candidates score 0.30
4. `_build_asset_portfolio()` is called from `execute()` with beat keywords
5. Unknown source types default to 0.40
6. All existing tests pass without modification (backward compat)
7. New test: `test_source_quality_tiers.py` validates tier lookup, downgrade, and default

### Commit

```bash
git commit -m "refactor: generic source quality tiers in segment producer"
```

---

## Batch 3 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_story_mode.py \
  tests/test_story_decision_reconciliation.py \
  tests/test_story_mode_contract.py \
  tests/test_agents_segment_producer.py \
  tests/test_segment_producer_content_direction.py \
  tests/test_source_quality_tiers.py \
  -v
```

---

# Batch 4 — Multimodal Candidate Inspection

**Mode:** Parallel workers L-O.

---

## Worker L — Task 4.1: Multimodal Provider Interface

**Files:**

- Create: `clipper_agency/core/multimodal_provider.py`
- Create: `tests/test_multimodal_provider.py`

### Interface

```python
class MultimodalProvider(Protocol):
    def inspect_asset(
        self,
        beat: dict,
        frame_paths: list[str],
        ocr_regions: list[dict],
        source_metadata: dict,
    ) -> dict:
        ...
```

### Requirements

- provider-independent;
- supports local file/image encoding;
- request payload logging with sensitive data omitted;
- token/cost diagnostics;
- retry and timeout;
- schema-validated response.

### Commit

```bash
git commit -m "feat: add multimodal inspection provider interface"
```

---

## Worker M — Task 4.2: Existing LLM Client Multimodal Adapter

**Files:**

- Create: `clipper_agency/llm/multimodal_client.py`
- Create: `tests/test_multimodal_client.py`

### Input

- story beat;
- evidence contract;
- up to configured number of keyframes;
- OCR text;
- source description and publish date.

### Required output schema

```json
{
  "person_match": 0.92,
  "event_match": 0.70,
  "claim_support": 0.78,
  "visual_quality": 0.65,
  "temporal_match": 0.50,
  "source_credibility": 0.40,
  "reason": "..."
}
```

### Prompt Questions

- Is the visible person consistent with the subject?
- Does the scene appear to show the same event?
- Does the visual directly support the spoken claim?
- Could the visual mislead the audience?
- Is the source text or logo dominant?
- Is this evidence, context, or decoration?

### Tests

Mock LLM response and verify image parts exist in payload.

### Commit

```bash
git commit -m "feat: add multimodal visual inspection client"
```

---

## Worker N — Task 4.3: Candidate Inspection Cache

**Files:**

- Create: `clipper_agency/core/inspection_cache.py`
- Create: `tests/test_inspection_cache.py`

### Cache key

```text
asset file hash
+ beat claim hash
+ evidence contract hash
+ model
+ prompt version
```

### Requirements

- reuse inspection for same asset and same beat intent;
- invalidate when prompt/model changes;
- persist JSON;
- expose cache hit/miss diagnostics.

### Commit

```bash
git commit -m "feat: add multimodal inspection cache"
```

---

## Worker O — Task 4.4: Candidate Portfolio Semantic Ranker

**Files:**

- Create: `clipper_agency/core/candidate_semantic_ranker.py`
- Create: `tests/test_candidate_semantic_ranker.py`

### Flow

```text
inspection output
+ existing score_visual_relevance
+ cleanliness
+ credibility
→ final candidate score
```

### Rules

- reject high misleading risk;
- reject low claim support;
- penalize dirty fullscreen sources;
- prefer direct evidence over generic context;
- keep fallback card candidate if all videos reject.

### Commit

```bash
git commit -m "feat: add semantic candidate portfolio ranking"
```

---

## Batch 4 Integration Task 4.5 — Visual Director Candidate Inspection

**Mode:** Sequential.

**Files:**

- Modify: `clipper_agency/agents/visual_director.py`
- Modify: `tests/test_agents_visual_director.py`
- Optional modify: existing Visual Director tests

### Required runtime

For each beat:

1. shortlist up to `max_assets_per_beat`;
2. download/resolve candidate;
3. extract keyframes;
4. run OCR and cleanliness;
5. call VLM;
6. score semantic relevance;
7. reject/revise/accept;
8. select best candidate;
9. persist all candidate diagnostics;
10. use text card fallback if none pass.

### Output extension

```json
{
  "candidate_inspections": [],
  "selected_asset_id": "...",
  "selection_reason": "...",
  "semantic_score": {}
}
```

### Logging

```text
Candidate inspection:
job=5 beat=4 asset=...
frames=4
vlm_model=...
claim_support=0.78
event_match=0.70
decision=accept
```

### Commit

```bash
git commit -m "feat: inspect and rank visual candidates semantically"
```

---


## Batch 4 Integration Task 4.6 — Wire Trace Writer into Text and Multimodal LLM Clients

**Mode:** Sequential.

**Files:**

- Modify: `clipper_agency/llm/client.py`
- Modify: `clipper_agency/llm/multimodal_client.py`
- Modify: relevant client tests
- Create or modify: `tests/test_llm_client_tracing.py`

### Required behavior

Every LLM call must:

1. allocate a unique `call_id`;
2. persist the fully resolved request before sending;
3. log the request artifact path;
4. execute the provider call;
5. persist the raw provider response;
6. parse the response;
7. persist the parsed application response;
8. validate against the expected schema;
9. persist validation outcome;
10. log the response artifact path and provider request ID.

### Correlation requirements

The trace must include:

```text
job_id
agent
task
call_id
repair_cycle
beat_id, when applicable
scene_id, when applicable
asset_id, when applicable
```

### Mandatory tests

```python
def test_text_llm_client_persists_prompt_response_and_parsed_result(tmp_path, mocker):
    provider = mock_successful_provider_response('{"verdict":"fail","score":40}')
    client = build_client(provider=provider, trace_root=tmp_path)

    result = client.complete(
        job_id=5,
        agent="reviewer",
        task="final_editorial_review",
        messages=[
            {"role": "system", "content": "SYSTEM PROMPT"},
            {"role": "user", "content": "USER PROMPT"},
        ],
        response_schema=ReviewerResult,
    )

    trace_dir = find_single_trace_dir(tmp_path)
    assert "SYSTEM PROMPT" in (trace_dir / "request.json").read_text()
    assert "USER PROMPT" in (trace_dir / "request.json").read_text()
    assert '"score":40' in (trace_dir / "response.json").read_text()
    assert result.score == 40
    assert (trace_dir / "parsed_response.json").exists()
    assert (trace_dir / "validation.json").exists()


def test_multimodal_trace_contains_image_manifest_not_raw_binary(tmp_path):
    client = build_multimodal_client(trace_root=tmp_path)
    client.inspect_asset(
        job_id=5,
        beat_id="4",
        asset_id="asset-12",
        frame_paths=["frame1.jpg", "frame2.jpg"],
        beat={"claim": "test"},
    )

    trace_dir = find_single_trace_dir(tmp_path)
    manifest = json.loads((trace_dir / "image_manifest.json").read_text())

    assert len(manifest["images"]) == 2
    assert manifest["images"][0]["sha256"]
    assert "base64" not in (trace_dir / "request.json").read_text().lower()
```

### Operational log example

```text
LLM call started: call_id=... job=5 agent=reviewer task=final_editorial_review model=gemini-2.5-flash request_trace=...
LLM call completed: call_id=... request_id=gen-... tokens_in=286 tokens_out=149 parse=pass schema=pass response_trace=...
```

### Commit

```bash
git commit -m "feat: trace resolved llm requests and responses"
```


## Batch 4 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_multimodal_provider.py \
  tests/test_multimodal_client.py \
  tests/test_llm_trace.py \
  tests/test_llm_trace_redaction.py \
  tests/test_llm_client_tracing.py \
  tests/test_inspection_cache.py \
  tests/test_candidate_semantic_ranker.py \
  tests/test_agents_visual_director.py \
  tests/test_llm_client_tracing.py \
  -v
```

---

# Batch 5 — Composer Runtime Diagnostics and Reviewer Scene Wiring

**Mode:** Limited parallel workers P-R.

---

## Worker P — Task 5.1: Composer Actual Coverage Diagnostics

**Files:**

- Modify: `clipper_agency/agents/composer.py`
- Modify: `tests/test_composer.py`

### Replace placeholder inputs

Remove:

```python
black_segments=[]
freeze_segments=[]
empty_segments=[]
scene_segments=[]
```

Use actual:

- `detect_black_segments`;
- `detect_freeze_segments`;
- frame extraction;
- empty-frame detector;
- rendered scene manifest;
- voice-over duration.

### Requirements

- persist `visual_coverage.json`;
- attach diagnostics;
- retain generated text manifest;
- do not silently ignore detector failure;
- detector failure becomes `DECODE_FAILURE` or `INSPECTION_FAILURE`.

### Commit

```bash
git commit -m "feat: run actual visual coverage detectors after render"
```

---

## Worker Q — Task 5.2: Rendered Scene Manifest

**Files:**

- Create: `clipper_agency/core/rendered_scene_manifest.py`
- Create: `tests/test_rendered_scene_manifest.py`
- Modify later: Composer integration

### Manifest fields

```json
{
  "scene": 2,
  "beat_id": 2,
  "start_sec": 4.951,
  "end_sec": 9.902,
  "source_path": "...",
  "source_type": "tiktok_clip",
  "selected_asset_id": "...",
  "caption_regions": []
}
```

### Commit

```bash
git commit -m "feat: add rendered scene timeline manifest"
```

---

## Worker R — Task 5.3: Reviewer Context Builder

**Files:**

- Create: `clipper_agency/core/reviewer_context.py`
- Create: `tests/test_reviewer_context.py`

### Build context from

- story beats;
- voice-over word timestamps;
- Visual Director selected asset diagnostics;
- rendered scene manifest;
- Composer diagnostics;
- caption;
- thumbnail;
- package metadata.

### Acceptance

Reviewer receives non-zero scenes.

```python
assert len(context["rendered_scenes"]) == 8
```

### Commit

```bash
git commit -m "feat: build complete reviewer scene context"
```

---

## Batch 5 Integration Task 5.4 — Timestamp-Level Final Semantic Review

**Mode:** Sequential.

**Files:**

- Modify: `clipper_agency/agents/reviewer.py`
- Modify: `tests/test_agents_reviewer.py`

### Required behavior

For every rendered scene:

1. map scene to beat;
2. use existing candidate inspection if still valid;
3. inspect final rendered keyframes where needed;
4. compare narration during timestamp range;
5. emit `SceneSemanticReview`;
6. create RepairPatch for revise/reject.

### Example

```json
{
  "beat_id": "4",
  "timestamp_start_sec": 14.85,
  "timestamp_end_sec": 19.80,
  "status": "revise",
  "failure_code": "WRONG_EVENT",
  "scores": {
    "person_match": 0.90,
    "event_match": 0.30,
    "claim_support": 0.25
  },
  "recommended_visual": "same-event announcement clip"
}
```

### Hard gate ordering

```text
asset integrity
duration
visual coverage
text collision
safe area
package consistency
timestamp semantic review
general LLM editorial review
```

### Commit

```bash
git commit -m "feat: add timestamp-level semantic reviewer"
```

---

## Batch 5 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_composer.py \
  tests/test_rendered_scene_manifest.py \
  tests/test_reviewer_context.py \
  tests/test_agents_reviewer.py \
  -v
```

---

# Batch 6 — Quality Enforcement and Automated Repair Cycles

**Mode:** Sequential.

---

## Task 6.1 — Add Quality, Publication, and Artifact Status Persistence

**Files:**

- Modify: database models/migrations according to existing project pattern
- Modify: `clipper_agency/orchestrator/engine.py`
- Modify: artifact manifest/persistence module according to the existing project pattern
- Modify: `tests/test_orchestrator_engine.py`
- Create or modify: `tests/test_artifact_lifecycle.py`

### Required statuses

```text
execution_status:
  pending
  running
  completed
  failed

quality_status:
  not_reviewed
  passed
  failed
  repair_pending
  repair_exhausted

publication_status:
  blocked
  ready

repair_status:
  none
  pending
  running
  completed
  exhausted

artifact_status:
  candidate
  rejected
  repairing
  approved
  repair_exhausted
  manual_review_required
```

### Mandatory rules

```text
Reviewer fail
→ execution may remain completed
→ candidate artifact remains stored
→ artifact_status=rejected
→ quality_status=failed or repair_pending
→ publication_status=blocked
→ repair_status=pending when a valid RepairPlan exists
```

```text
Reviewer pass
→ artifact_status=approved
→ quality_status=passed
→ publication_status=ready
```

```text
Repair limit exhausted
→ artifact_status=manual_review_required
→ quality_status=repair_exhausted
→ repair_status=exhausted
→ publication_status=blocked
```

### Mandatory TDD tests

```python
def test_quality_failure_keeps_rejected_artifacts_but_blocks_publication():
    result = complete_job_with_reviewer_failure()

    assert result["video_path"] is not None
    assert result["thumbnail_path"] is not None
    assert result["quality_status"] in {"failed", "repair_pending"}
    assert result["publication_status"] == "blocked"
    assert result["artifact_status"] == "rejected"
    assert Path(result["video_path"]).exists()


def test_rejected_artifact_is_not_promoted_to_final_output():
    result = complete_job_with_reviewer_failure()

    assert result["artifact_status"] == "rejected"
    assert result["final_video_path"] in {None, ""}
    assert not final_output_exists(result["job_id"])


def test_repairable_failure_sets_repair_pending_without_deleting_candidate():
    result = complete_job_with_repair_plan()

    assert result["artifact_status"] == "rejected"
    assert result["repair_status"] == "pending"
    assert result["publication_status"] == "blocked"
    assert Path(result["video_path"]).exists()


def test_passed_repair_promotes_new_cycle_artifact_and_preserves_rejected_cycle():
    result = complete_job_with_successful_repair()

    assert result["quality_status"] == "passed"
    assert result["publication_status"] == "ready"
    assert result["artifact_status"] == "approved"
    assert Path(result["final_video_path"]).exists()
    assert Path(result["cycle_0_video_path"]).exists()
    assert result["cycle_0_artifact_status"] == "rejected"


def test_exhausted_repairs_keep_latest_artifact_for_manual_review():
    result = complete_job_with_exhausted_repairs()

    assert result["quality_status"] == "repair_exhausted"
    assert result["publication_status"] == "blocked"
    assert result["repair_status"] == "exhausted"
    assert result["artifact_status"] == "manual_review_required"
    assert Path(result["latest_video_path"]).exists()
```

### Commit

```bash
git commit -m "feat: persist quality publication and artifact lifecycle"
```

---

## Task 6.2 — Implement Bounded Automated Repair Loop

**Files:**

- Modify: `clipper_agency/orchestrator/engine.py`
- Modify: `tests/test_orchestrator_engine.py`
- Optional modify: repair persistence module

### Flow

```text
Reviewer returns RepairPlan
→ validate cycle count
→ group patches by target agent
→ rerun earliest required agent
→ reuse unaffected artifacts
→ rerender
→ rereview
→ persist cycle record
```

### Rules

- maximum cycles from config;
- no infinite loop;
- same failure repeated twice triggers exhaustion;
- package/script change reruns downstream agents;
- Composer-only defect reruns Composer and Reviewer;
- Visual defect reruns Visual Director, Composer, Reviewer;
- semantic source defect may rerun Segment Producer source recovery;
- the rejected candidate from the previous cycle must remain stored;
- every new repair attempt must write to a new `cycle_{n}` directory;
- repair execution must never overwrite `cycle_0` or any prior cycle;
- publication remains blocked during all repair cycles;
- only the newly reviewed passing cycle may be promoted to `outputs/final`;
- when no valid RepairPlan exists, the job must move to `manual_review_required` rather than silently completing.

### Tests

- black frame routes to Composer;
- wrong event routes to Visual Director;
- package mismatch routes to Segment Producer;
- second successful cycle passes;
- third cycle blocked when max is 2;
- repeated identical patch marks exhausted.

### Commit

```bash
git commit -m "feat: execute bounded reviewer repair cycles"
```

---

## Task 6.3 — Before/After Quality Metrics

**Files:**

- Create: `clipper_agency/core/repair_metrics.py`
- Create: `tests/test_repair_metrics.py`
- Modify: Engine persistence

### Metrics

```json
{
  "cycle": 1,
  "before": {
    "reviewer_score": 40,
    "claim_support_avg": 0.41,
    "collision_count": 3,
    "black_frame_ms": 3330
  },
  "after": {
    "reviewer_score": 78,
    "claim_support_avg": 0.76,
    "collision_count": 0,
    "black_frame_ms": 0
  }
}
```

### Commit

```bash
git commit -m "feat: persist before and after repair quality metrics"
```

---

## Task 6.4 — Packaging, Artifact Retention, and Publication Block

**Files:**

- Modify: Packager / pipeline completion logic
- Modify: artifact manifest/persistence module
- Modify: CLI/dashboard status presentation where applicable
- Modify: relevant tests
- Create or modify: `tests/test_artifact_lifecycle.py`

### Required behavior

- failed quality does not produce a publishable package;
- failed quality does not delete or overwrite the candidate render;
- candidate video, thumbnail, metadata, logs, diagnostics, keyframes, OCR results, semantic reviews, and RepairPlan remain available;
- rejected candidate artifacts are stored under their original cycle directory;
- `outputs/final/` must remain empty or absent until a cycle passes;
- CLI/dashboard must distinguish:
  - execution completed;
  - quality failed;
  - publication blocked;
  - repair pending/running/exhausted;
  - manual review required;
- only `quality_status=passed` and `artifact_status=approved` set `publication_status=ready`;
- promotion to final must be atomic;
- a failed promotion must leave the approved cycle artifact intact and publication blocked until retried.

### Mandatory lifecycle assertion

```text
Blocked does not mean deleted.
Blocked means non-publishable.
```

### Mandatory TDD tests

```python
def test_quality_failure_keeps_rejected_artifacts_but_blocks_publication():
    result = complete_job_with_reviewer_failure()

    assert result["video_path"] is not None
    assert Path(result["video_path"]).exists()
    assert result["quality_status"] == "failed"
    assert result["publication_status"] == "blocked"
    assert result["artifact_status"] == "rejected"


def test_final_directory_is_created_only_after_quality_passes():
    failed = complete_job_with_reviewer_failure()
    assert not final_output_exists(failed["job_id"])

    passed = repair_job_until_pass(failed["job_id"])
    assert final_output_exists(passed["job_id"])
    assert passed["publication_status"] == "ready"


def test_repair_cycle_does_not_overwrite_rejected_output():
    result = complete_job_with_successful_repair()

    assert Path(result["cycle_0_video_path"]).exists()
    assert Path(result["cycle_1_video_path"]).exists()
    assert result["cycle_0_video_path"] != result["cycle_1_video_path"]
```

### Commit

```bash
git commit -m "fix: retain rejected artifacts and block publication until approval"
```

---

## Batch 6 Gate

```bash
.venv/bin/python3 -m pytest \
  tests/test_orchestrator_engine.py \
  tests/test_repair_metrics.py \
  tests/test_packager.py \
  -v
```

---

# Batch 7 — Job #5 Regression and Production Validation

**Mode:** Sequential.

---

## Task 7.1 — Add Job #5 Regression Fixture

**Files:**

- Create: `tests/fixtures/job5/`
- Create/modify: `tests/test_job5_runtime_quality_regression.py`

### Fixture expectations

1. Broad gossip topic resolves to roundup.
2. Duration budget uses intro/story/story/story/CTA.
3. Keyframes are produced.
4. OCR finds burned-in text.
5. Source cleanliness score prevents dirty fullscreen use when threshold fails.
6. Reviewer receives eight scenes.
7. Black segments are detected.
8. Reviewer fail blocks publication.
9. Repair route is generated.
10. Max repair cycles enforced.
11. Every LLM call produces request, raw response, parsed response, validation, and metadata artifacts.
12. Runtime logs contain trace paths and correlation IDs without dumping secrets.

### Commit

```bash
git commit -m "test: add job5 runtime quality regression fixture"
```

---

## Task 7.2 — Add Integration Test with Real FFmpeg

**Marker:** `integration`

### Test video fixtures

Create small synthetic videos:

- black segment;
- frozen frame;
- burned-in text;
- clean video;
- correct duration but black ending.

### Assertions

- detectors return correct intervals;
- Composer diagnostics fail correctly;
- Reviewer never calls LLM when deterministic gate fails.

### Commit

```bash
git commit -m "test: add ffmpeg runtime quality integration fixtures"
```

---

## Task 7.3 — Add Mocked Multimodal Integration Test

**Marker:** offline-safe

### Scenario

- candidate A: correct person, wrong event;
- candidate B: correct event and claim;
- candidate A rejected;
- candidate B selected;
- semantic metadata persisted.

### Commit

```bash
git commit -m "test: add semantic candidate rejection integration test"
```

---

## Task 7.4 — Full Runtime Smoke Test

Run a real job with paid/external integrations only in manual or external test mode.

### Expected log markers

```text
Story mode canonical: roundup
Frames extracted: ...
OCR regions: ...
Faces detected: ...
Candidate semantic inspection: ...
Selected asset: ...
Visual coverage: pass/fail
Reviewer scenes: 8
Repair cycle: 1/2
LLM call started: call_id=... request_trace=...
LLM call completed: call_id=... response_trace=... parse=... schema=...
Quality status: passed/failed
Publication status: ready/blocked
```

### Required artifact checks

```text
inspections/candidates/
inspections/final/
llm_traces/
repair/cycle_1.json
```

---

# 6. Proposed File Structure

```text
clipper_agency/
├── core/
│   ├── inspection_paths.py
│   ├── media_detectors.py
│   ├── frame_quality.py
│   ├── frame_extractor.py
│   ├── frame_hash.py
│   ├── frame_inspection_pipeline.py
│   ├── ocr_adapter.py
│   ├── face_adapter.py
│   ├── generated_text_manifest.py
│   ├── source_cleanliness.py
│   ├── final_layout_inspection.py
│   ├── story_decision_reconciliation.py
│   ├── story_mode_contract.py
│   ├── multimodal_provider.py
│   ├── inspection_cache.py
│   ├── candidate_semantic_ranker.py
│   ├── rendered_scene_manifest.py
│   ├── reviewer_context.py
│   └── repair_metrics.py
├── llm/
│   └── multimodal_client.py
├── observability/
│   ├── llm_trace.py
│   └── redaction.py
└── tests/
    ├── fixtures/
    │   ├── job5/
    │   └── media_quality/
    └── ...
```

---

# 7. Recommended Sub-Agent Assignment

| Sub-agent | Task |
|---|---|
| Alpha | FFmpeg black/freeze detector |
| Beta | Empty-frame detector |
| Gamma | Frame extractor |
| Delta | Perceptual hashing |
| Echo | OCR adapter |
| Foxtrot | Face adapter |
| Golf | Generated text manifest |
| Hotel | Source cleanliness |
| India | Story-mode rules |
| Juliet | Story-decision reconciliation |
| Kilo | Thumbnail/CTA mode contract |
| Lima | Multimodal provider interface |
| Mike | Multimodal client |
| November | Inspection cache |
| Oscar | Candidate semantic ranker |
| Papa | Composer runtime diagnostics |
| Quebec | Rendered scene manifest |
| Romeo | Reviewer context builder |

Shared integration files must only be modified by the designated integration owner after worker branches are green.

---

# 8. Merge Order

```text
1. Batch 0
2. Workers A-D
3. Batch 1 integration
4. Workers E-H
5. Batch 2 integration
6. Workers I-K
7. Batch 3 integration
8. Workers L-O
9. Batch 4 integration
10. Workers P-R
11. Batch 5 integration
12. Batch 6 sequential
13. Batch 7 validation
```

Do not merge a worker branch if:

- its targeted tests fail;
- it modifies unassigned shared files;
- it introduces direct API calls in offline tests;
- it duplicates another adapter;
- it bypasses existing pure evaluators.

---

# 9. Definition of Done

This implementation is complete only when:

- actual black/freeze detectors run on final video;
- actual empty-frame detection runs;
- actual frames are extracted and persisted;
- perceptual hashes are computed from images;
- OCR runs against extracted frames;
- face detection runs against extracted frames;
- generated caption bounding boxes are persisted;
- text collision and safe-area gates use actual runtime data;
- broad gossip topics resolve consistently to roundup;
- only one canonical story mode controls duration, thumbnail, and CTA;
- candidate keyframes are sent to a multimodal model;
- every selected visual has semantic inspection metadata;
- same-person/wrong-event candidates can be rejected;
- Reviewer receives rendered scenes and timestamps;
- Reviewer emits scene-level semantic feedback;
- quality failure blocks publication without deleting candidate artifacts;
- rejected renders, thumbnails, metadata, logs, keyframes, OCR results, and semantic diagnostics remain available;
- rejected cycles are never overwritten by later repairs;
- only approved artifacts are promoted into `outputs/final/`;
- structured repair plans trigger bounded retries;
- repair cycles persist before/after metrics;
- exhausted repairs retain the latest candidate and require manual review;
- Job #5 regression tests pass;
- full offline suite passes;
- external runtime smoke test produces inspection artifacts;
- every text and multimodal LLM call persists resolved request, raw response, parsed response, validation result, and metadata;
- operational logs contain trace correlation IDs and artifact paths;
- API keys, authorization headers, and credentials are absent from persisted traces.

---

# 10. Final Validation Commands

## Targeted tests

```bash
.venv/bin/python3 -m pytest \
  tests/test_media_detectors.py \
  tests/test_frame_quality.py \
  tests/test_frame_extractor.py \
  tests/test_frame_hash.py \
  tests/test_frame_inspection_pipeline.py \
  tests/test_ocr_adapter.py \
  tests/test_face_adapter.py \
  tests/test_generated_text_manifest.py \
  tests/test_source_cleanliness.py \
  tests/test_final_layout_inspection.py \
  tests/test_story_decision_reconciliation.py \
  tests/test_story_mode_contract.py \
  tests/test_multimodal_provider.py \
  tests/test_multimodal_client.py \
  tests/test_llm_trace.py \
  tests/test_llm_trace_redaction.py \
  tests/test_llm_client_tracing.py \
  tests/test_inspection_cache.py \
  tests/test_candidate_semantic_ranker.py \
  tests/test_rendered_scene_manifest.py \
  tests/test_reviewer_context.py \
  tests/test_artifact_lifecycle.py \
  tests/test_repair_metrics.py \
  tests/test_job5_runtime_quality_regression.py \
  -v
```

## Full offline suite

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

## Integration suite

```bash
.venv/bin/python3 -m pytest -m integration -v
```

## Optional coverage

```bash
.venv/bin/python3 -m pytest \
  -m "not external and not integration" \
  --cov=clipper_agency \
  --cov-report=term-missing
```

---

# 11. Recommended PR

```bash
git checkout master
git pull origin master
git checkout -b phase/22-job4-runtime-quality-enforcement
```

After all gates pass:

```bash
git push -u origin phase/22-job4-runtime-quality-enforcement

gh pr create \
  --base master \
  --title "Phase 22: Runtime visual inspection and repair enforcement" \
  --body "Completes the runtime adapters, multimodal asset inspection, canonical story-mode propagation, Reviewer scene wiring, and bounded repair enforcement missing from Phase 21."
```

Do not merge until:

- offline tests pass;
- integration detector tests pass;
- SonarCloud passes;
- one real Job #5-style smoke test produces keyframe, OCR, semantic, and repair artifacts;
- failed Reviewer result demonstrably blocks publication.

---

# Batch 8 — Multi-Provider Asset Sources

**Mode:** Sequential. Depends on Task 3.5 (Batch 3).

**Goal:** Expand Segment Producer's asset source pool from 2 providers (ScrapeCreators, Firecrawl) to 5+ providers (YouTube Search, Tavily, Brave Search) with source-tier quality scoring and YouTube thumbnail fallback.

**Why:** Live testing with Job 5 entities (Sarwendah-Ruben, Zara Adhisty, Dewi Perssik) showed:
- ScrapeCreators TikTok clips: watermarked, hardcoded subtitles — low visual quality
- Firecrawl: article URLs only, some news photos with copyright risk
- YouTube search: 15+ results per entity — clean videos from news channels
- Unsplash/Pexels: zero results for Indonesian celebrities — removed from pipeline

---

## Task 8.1 — YouTube Search via yt-dlp

**Files:**

- Modify: `clipper_agency/services/ytdlp.py`
- Create: `tests/test_ytdlp_search.py`

### Interface

```python
class YtDlpService:
    # ... existing download() ...

    def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Search YouTube via yt-dlp ytsearchN: prefix.

        Returns list of dicts:
        {
            "source_type": "youtube_official",
            "url": "https://www.youtube.com/watch?v=...",
            "title": "...",
            "description": "...",
            "duration": 120,
            "channel": "...",
            "thumbnail_url": "https://i.ytimg.com/...",
        }
        """
```

### Requirements

- Use `ytsearch{max_results}:{query}` as URL to `yt_dlp.YoutubeDL()`
- Extract only metadata (`"skip_download": True`), never download during search
- Return structured dicts with `source_type: "youtube_official"`
- Handle yt-dlp exceptions gracefully (empty results, network errors)
- No API key required — yt-dlp search is free
- Retry with exponential backoff (max 2 retries)

### Acceptance

1. `search("Sarwendah drama", max_results=5)` returns up to 5 results
2. Each result has `source_type`, `url`, `title`, `thumbnail_url`
3. Network errors return empty list (not exception)
4. Mock tests: verify `ytsearch5:` prefix construction
5. No actual network calls in offline tests

### Commit

```bash
git commit -m "feat: add YouTube search to YtDlpService"
```

---

## Task 8.2 — Tavily Search Service

**Files:**

- Create: `clipper_agency/services/tavily.py`
- Create: `tests/test_tavily_service.py`

### Interface

```python
class TavilyService:
    def __init__(self, api_key: str): ...

    def search(
        self,
        query: str,
        max_results: int = 5,
        include_videos: bool = True,
    ) -> list[dict]:
        """Search web via Tavily API.

        Returns list of dicts:
        {
            "source_type": "web_video" | "article",
            "url": "...",
            "title": "...",
            "content": "...",  # extracted text
            "score": 0.85,     # Tavily relevance score
        }
        """
```

### Requirements

- Tavily API endpoint: `POST https://api.tavily.com/search`
- Free tier: 1000 requests/month
- `include_videos=True` adds video results alongside web results
- Classify results: URLs containing youtube.com/watch → `source_type: "web_video"`, else `"article"`
- Retry with exponential backoff + jitter (max 3 retries)
- API key from config: `tavily_api_key`

### Acceptance

1. Search returns structured results with `source_type`
2. YouTube URLs in results get `source_type: "web_video"`
3. Non-video URLs get `source_type: "article"`
4. Network/auth errors return empty list
5. Mock tests verify API payload construction

### Commit

```bash
git commit -m "feat: add Tavily search service"
```

---

## Task 8.3 — Brave Search Service

**Files:**

- Create: `clipper_agency/services/brave.py`
- Create: `tests/test_brave_service.py`

### Interface

```python
class BraveSearchService:
    def __init__(self, api_key: str): ...

    def search_videos(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Search videos via Brave Search API.

        Returns list of dicts:
        {
            "source_type": "web_video",
            "url": "...",
            "title": "...",
            "description": "...",
            "thumbnail_url": "...",
        }
        """

    def search_web(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Search web pages via Brave Search API.

        Returns list of dicts:
        {
            "source_type": "article",
            "url": "...",
            "title": "...",
            "description": "...",
        }
        """
```

### Requirements

- Brave Search API: `GET https://api.search.brave.com/res/v1/web/search` (web) and `.../videos` (video)
- Free tier: 2000 requests/month
- Header: `X-Subscription-Token: {api_key}`
- Retry with exponential backoff (max 3 retries)
- API key from config: `brave_api_key`

### Acceptance

1. Video search returns structured results with `source_type: "web_video"`
2. Web search returns results with `source_type: "article"`
3. Network/auth errors return empty list
4. Mock tests verify header construction and URL formation

### Commit

```bash
git commit -m "feat: add Brave Search service"
```

---

## Task 8.4 — Config Schema: New API Keys

**Files:**

- Modify: `clipper_agency/config/schema.py`
- Modify: `tests/test_config_schema.py`
- Modify: `.env.example` (if exists)

### Changes

Add to `Settings` class after existing API key fields:

```python
tavily_api_key: str = ""
brave_api_key: str = ""
```

### Acceptance

1. Both keys load from environment variables
2. Empty string is valid default (services check before use)
3. Existing tests pass unchanged

### Commit

```bash
git commit -m "feat: add Tavily and Brave API keys to config schema"
```

---

## Task 8.5 — Wire Multi-Source into Segment Producer

**Files:**

- Modify: `clipper_agency/agents/segment_producer.py`
- Modify: `tests/test_agents_segment_producer.py`
- Modify: `tests/test_source_quality_tiers.py`

### Changes

In `execute()`, after existing ScrapeCreators + Firecrawl source collection, add multi-source aggregation:

```python
# ── 1a-extended. Multi-provider asset discovery ──────────────────
multi_sources = self._discover_multi_source_assets(
    topic=topic,
    entities=entities,
    config=self.config,
)

# Merge with existing sources
all_sources = _normalize_sources(firecrawl_data, scrapecreators_data)
all_sources.extend(multi_sources)
```

New method `_discover_multi_source_assets()`:

```python
def _discover_multi_source_assets(
    self,
    topic: str,
    entities: dict,
    config: Settings,
) -> list[dict]:
    """Search YouTube, Tavily, Brave for additional asset candidates."""
    sources: list[dict] = []
    search_queries = self._build_search_queries(topic, entities)

    # YouTube search (free, no API key needed)
    ytdlp = YtDlpService()
    for query in search_queries:
        results = ytdlp.search(query, max_results=3)
        sources.extend(results)

    # Tavily search (if API key configured)
    if config.tavily_api_key:
        tavily = TavilyService(config.tavily_api_key)
        for query in search_queries:
            results = tavily.search(query, max_results=3)
            sources.extend(results)

    # Brave search (if API key configured)
    if config.brave_api_key:
        brave = BraveSearchService(config.brave_api_key)
        for query in search_queries:
            results = brave.search_videos(query, max_results=3)
            sources.extend(results)

    return sources
```

`_build_search_queries()` derives search queries from topic + entity names (e.g., `"Sarwendah drama terbaru"`, `"Zara Adhisty berita"`).

### Requirements

- Multi-source discovery is **additive** — existing ScrapeCreators/Firecrawl sources are preserved
- Each provider is **optional** — if API key is empty, that provider is skipped
- YouTube search always runs (no API key needed)
- All results go through Task 3.5's generic source interface and `SOURCE_QUALITY_TIERS`
- No more than 3 queries per provider to stay within free tier limits
- Total candidate count capped at 30 per job (prevent API exhaustion)

### Acceptance

1. `_discover_multi_source_assets()` returns results from YouTube (always) + Tavily/Brave (if keys present)
2. Results flow through `_build_asset_portfolio()` with correct quality tiers
3. YouTube results get `source_type: "youtube_official"` → score 0.95
4. Tavily video results get `source_type: "web_video"` → score 0.85
5. ScrapeCreators still collected but scored 0.50
6. Offline tests use mocks for all external services
7. Existing tests pass unchanged

### Commit

```bash
git commit -m "feat: wire multi-source asset discovery into segment producer"
```

---

## Task 8.6 — YouTube Thumbnail Extraction Fallback

**Files:**

- Modify: `clipper_agency/services/ytdlp.py`
- Modify: `clipper_agency/agents/segment_producer.py`
- Create: `tests/test_yt_thumbnail_fallback.py`

### Changes

Add to `YtDlpService`:

```python
def download_thumbnail(
    self,
    video_url: str,
    output_path: str,
) -> str | None:
    """Download best-quality thumbnail for a YouTube video."""
```

In SP's asset fallback chain (when a beat has no suitable video):

```
YouTube video download → YouTube thumbnail → Pexels stock video → text card
```

When a YouTube search result exists but download fails (geo-blocked, removed), extract the thumbnail URL from the search result metadata and use it as an image asset.

### Acceptance

1. Thumbnail download returns path or None (never raises)
2. SP uses thumbnail as image fallback when video download fails
3. Thumbnail gets `source_type: "image"` → quality tier 0.70
4. Mock tests verify fallback chain order

### Commit

```bash
git commit -m "feat: YouTube thumbnail extraction as image fallback"
```

---

## Task 8.7 — Batch 8 Gate: Multi-Source Regression

**Files:**

- Create: `tests/test_batch8_multi_source.py`

### Test scenarios

1. **Happy path**: All providers return results → candidates aggregated, scored, sorted
2. **Partial providers**: Only YouTube available (no Tavily/Brave keys) → still produces candidates
3. **No providers**: All fail/empty → falls back to existing ScrapeCreators/Firecrawl
4. **Quality ordering**: YouTube (0.95) ranks above ScrapeCreators (0.50) in final portfolio
5. **Entity-specific**: Search queries include entity names from synthesis
6. **Candidate cap**: Total candidates ≤ 30
7. **Job #5 regression**: Sarwendah topic produces multi-source candidates with correct tiers

### Gate command

```bash
.venv/bin/python3 -m pytest \
  tests/test_ytdlp_search.py \
  tests/test_tavily_service.py \
  tests/test_brave_service.py \
  tests/test_source_quality_tiers.py \
  tests/test_batch8_multi_source.py \
  tests/test_yt_thumbnail_fallback.py \
  tests/test_agents_segment_producer.py \
  -v
```

### Full regression

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

---

# 12. Batch 8 Validation Commands

## Targeted tests

```bash
.venv/bin/python3 -m pytest \
  tests/test_source_quality_tiers.py \
  tests/test_ytdlp_search.py \
  tests/test_tavily_service.py \
  tests/test_brave_service.py \
  tests/test_batch8_multi_source.py \
  tests/test_yt_thumbnail_fallback.py \
  tests/test_agents_segment_producer.py \
  -v
```

## Full offline suite

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

## Optional coverage

```bash
.venv/bin/python3 -m pytest \
  -m "not external and not integration" \
  --cov=clipper_agency \
  --cov-report=term-missing
```
