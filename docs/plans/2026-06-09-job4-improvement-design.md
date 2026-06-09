# Job #4 Improvement Design

**Document ID:** JOB4-IMPROVEMENT-DESIGN  
**Filename:** `2026-06-09-job4-improvement-design.md`  
**Date:** 2026-06-09  
**Status:** Proposed  
**Target baseline:** Clipper Agency v2.0.0 with PR #42 changes  
**Scope:** Phase 1, Phase 2, and Phase 3 quality improvements after Job #4 analysis

---

## 1. Purpose

This document defines the design for improving the Clipper Agency video-generation pipeline after analysis of Job #4.

Job #4 proved that the end-to-end pipeline can successfully:

- research current entertainment topics;
- generate a continuous voice-over;
- retrieve source media;
- compose a vertical short-form video;
- generate captions and a thumbnail;
- complete the agent pipeline without fatal execution errors.

However, the output also exposed quality problems that were not fully prevented by the existing gates:

- visual content may end while audio continues;
- technically valid video duration may still contain black or empty frames;
- source captions and generated subtitles may overlap;
- source watermarks and burned-in text may dominate the frame;
- roundup content may not be clearly introduced;
- thumbnail, caption, script, and actual video scope may be inconsistent;
- asset relevance may only match the topic or person, not the exact event or claim;
- pacing and visual changes may follow duration rather than narrative meaning.

The purpose of this design is to improve those areas while preserving the current seven-agent architecture.

---

## 2. Design Decision: Do Not Add New Top-Level Agents

Phase 1, Phase 2, and Phase 3 should remain within the responsibilities of the existing agents and deterministic pipeline services.

Adding new top-level agents at this stage would create:

- more LLM calls;
- higher cost and latency;
- more state transitions;
- harder debugging;
- overlapping responsibilities;
- additional prompt inconsistency;
- more complicated retry behavior.

The recommended design is to extend the current agents and add deterministic quality modules.

### 2.1 Responsibility Mapping

| Capability | Primary owner | Supporting component |
|---|---|---|
| Topic scope classification | Segment Producer | Rule engine / small LLM fallback |
| Story mode selection | Segment Producer | Config schema |
| Duration allocation | Segment Producer | Scriptwriter |
| Evidence requirements | Segment Producer | Research providers |
| Asset candidate ranking | Segment Producer | Retrieval services |
| Text-aware visual planning | Visual Director | OCR service |
| Face and safe-area planning | Visual Director | CV detection service |
| Semantic timeline planning | Visual Director | Word timestamps |
| Black-frame detection | Composer | FFmpeg/OpenCV |
| Freeze detection | Composer | FFmpeg/OpenCV |
| Render duration validation | Composer | ffprobe |
| Text collision validation | Reviewer | OCR result + geometry |
| Package consistency | Reviewer | Embeddings / small LLM |
| Claim-to-visual relevance | Reviewer | Vision-language model |
| Repair instructions | Reviewer | Structured repair schema |
| Retry / partial regeneration | Engine | Existing agent execution flow |

### 2.2 Core Principle

Use LLMs only for tasks requiring semantic or editorial judgment.

Use deterministic services for:

- duration checks;
- black-frame detection;
- freeze detection;
- bounding-box overlap;
- safe-area calculations;
- frame sampling;
- perceptual deduplication;
- asset integrity;
- file and codec validation.

---

## 3. Existing Baseline

The design assumes PR #42 is included in the baseline.

PR #42 already provides:

- replacement of duplicate or invalid visual URLs;
- Composer output-duration guard;
- Reviewer hard gates for AV duration mismatch;
- Reviewer hard gate for broken `tiktok_clip` actions;
- explicit roundup intro-card handling;
- preference for no-watermark source URLs;
- improved diagnostics;
- asset relevance ranking based on keyword matching.

This design must not duplicate those changes.

Instead, it extends them with:

1. meaningful visual coverage validation;
2. OCR and text-collision detection;
3. safe-area and face-overlap checks;
4. topic-scope and story-mode control;
5. claim-to-visual semantic relevance;
6. structured repair instructions.

---

# 4. Phase 1 — Deterministic Visual Quality Gates

## 4.1 Objective

Prevent technically invalid or visibly broken videos from reaching final approval.

Phase 1 focuses on low-cost, deterministic checks that do not require a large language model.

## 4.2 Phase 1 Components

### 4.2.1 Visual Coverage Gate

The Visual Coverage Gate verifies that meaningful visual content exists for the entire voice-over timeline.

It extends the PR #42 duration check.

A video may have the correct total duration but still contain:

- black frames;
- empty canvas;
- frozen content;
- failed source decoding;
- missing visual segments;
- stale final frames;
- filler frames that do not represent an intended scene.

#### Checks

| Check | Initial threshold | Result |
|---|---:|---|
| Output shorter than voice-over | Any amount | Hard fail |
| Black segment | More than 200 ms | Hard fail |
| Empty/near-uniform frame | More than 300 ms | Hard fail |
| Frozen frame | More than 1.5 seconds | Warning or fail by scene type |
| Missing scene output | Any | Hard fail |
| Last meaningful visual before audio end | More than 200 ms | Hard fail |
| Decode failure | Any | Hard fail |

#### Implementation

Use:

- `ffprobe` for media duration and stream validation;
- FFmpeg `blackdetect`;
- FFmpeg `freezedetect`;
- OpenCV frame variance for empty-frame detection;
- perceptual hash for repeated-frame analysis.

#### Suggested Module

```text
clipper_agency/core/visual_coverage.py
```

#### Suggested Output

```json
{
  "status": "fail",
  "output_duration_sec": 21.2,
  "voiceover_duration_sec": 21.0,
  "coverage_ratio": 0.79,
  "issues": [
    {
      "type": "BLACK_FRAME",
      "start_sec": 17.83,
      "end_sec": 21.20,
      "severity": "hard_fail"
    }
  ]
}
```

#### Agent Ownership

- **Composer** performs the checks after rendering.
- **Reviewer** consumes and enforces the result.
- **Engine** decides whether to retry Visual Director or Composer.

---

### 4.2.2 OCR Text Detection

OCR should use a dedicated OCR model, not a general LLM.

Recommended initial implementation:

- PaddleOCR for text detection and recognition;
- OpenCV for frame extraction and preprocessing;
- optional Tesseract fallback for clean frames.

The most important OCR output is not only the recognized text but also:

- bounding box;
- confidence;
- timestamp;
- persistence across frames;
- frame-area ratio;
- screen zone.

#### Frame Sampling Strategy

Do not OCR every frame.

Recommended strategy:

1. detect scene boundaries;
2. sample the first frame of every scene;
3. sample one frame every 500 ms;
4. deduplicate visually similar frames using perceptual hashing;
5. run OCR only on unique or changed frames.

For a 20-second video, the expected OCR workload should normally remain below 10–30 unique frames.

#### Suggested Module

```text
clipper_agency/core/text_detection.py
```

#### Suggested Output

```json
{
  "timestamp_sec": 4.5,
  "regions": [
    {
      "text": "INI ALASAN RUBEN",
      "confidence": 0.96,
      "bbox": [80, 980, 990, 1220],
      "area_ratio": 0.11,
      "zone": "middle",
      "persistent_for_ms": 2300
    }
  ]
}
```

---

### 4.2.3 Text Collision Gate

The Text Collision Gate compares:

- source text regions;
- generated subtitle regions;
- generated headline regions;
- source watermark regions;
- CTA and branding regions.

#### Initial Rules

| Rule | Initial threshold |
|---|---:|
| Generated subtitle overlaps source text | More than 20% |
| Generated headline overlaps source text | More than 15% |
| More than two major text layers | Warning |
| Source text occupies more than 25% of frame | Warning |
| Source text occupies more than 40% of frame | Reject or use alternate layout |
| Subtitle falls inside platform unsafe zone | Reject |
| Subtitle overlaps detected face | More than 15% |

#### Suggested Module

```text
clipper_agency/core/text_collision.py
```

#### Visual Director Behavior

Before composition, the Visual Director receives the source-text map and may choose:

- move generated captions;
- use a top-caption layout;
- crop the source;
- blur or mask a source region;
- use picture-in-picture;
- choose a different asset;
- fall back to a screenshot or text card.

#### Reviewer Behavior

After composition, the Reviewer validates that the final rendered layout no longer violates the collision thresholds.

---

### 4.2.4 Face and Safe-Area Gate

A lightweight computer-vision model should detect:

- faces;
- primary subject;
- approximate head and torso location;
- platform UI unsafe zones.

Recommended options:

- MediaPipe;
- OpenCV DNN;
- YOLO face;
- RetinaFace where higher accuracy is needed.

#### Initial Rules

- do not cover the primary face with generated text;
- keep the primary face within the vertical safe frame;
- do not crop the head at the top boundary;
- keep subtitles outside TikTok/Reels/Shorts control areas;
- avoid CTA placement behind platform buttons;
- use dynamic reframing where the subject moves.

#### Suggested Module

```text
clipper_agency/core/safe_area.py
```

---

### 4.2.5 Phase 1 Reviewer Hard Gates

The existing Reviewer hard gates should be extended.

```text
Reviewer hard-gate order:

1. Asset integrity
2. Output duration
3. Visual coverage
4. Black/freeze detection
5. Text collision
6. Face and safe-area compliance
7. Existing caption and narrative checks
8. LLM review
```

The expensive LLM review must only run after deterministic gates pass.

---

## 4.3 Phase 1 Acceptance Criteria

Phase 1 is complete when:

- no black segment longer than 200 ms reaches final approval;
- no final video ends visually before the voice-over;
- text-collision results include timestamp and bounding boxes;
- generated subtitles do not overlap major source text beyond the threshold;
- primary faces are not covered by captions;
- deterministic failures prevent the Reviewer LLM call;
- all checks are represented in structured diagnostics;
- Job #4 becomes a regression fixture and fails on the expected defects.

---

# 5. Phase 2 — Topic Scope and Story Structure Control

## 5.1 Objective

Ensure that broad input topics are converted into an explicit editorial format before script and visual generation.

Job #4 used a broad topic equivalent to:

```text
berita hot gossip artist Indonesia terbaru
```

This may produce several unrelated stories in one short video.

The pipeline must explicitly choose whether to:

- produce one focused story; or
- produce a clearly structured roundup.

## 5.2 Segment Producer Extensions

Phase 2 belongs primarily to the **Segment Producer**.

The Segment Producer should create a `StoryModeDecision` before finalizing story beats.

### 5.2.1 Supported Story Modes

```text
single_story
roundup
profile
timeline
controversy_explainer
reaction
breaking_news
```

### 5.2.2 Classification Strategy

Use a hybrid model:

1. deterministic rules for obvious cases;
2. small LLM fallback for ambiguous cases.

Examples:

| Input pattern | Likely mode |
|---|---|
| “berita artis terbaru hari ini” | roundup |
| “kenapa X berhenti memberi nafkah” | controversy_explainer |
| “perjalanan karier X” | profile or timeline |
| “X akhirnya memberikan klarifikasi” | single_story |
| “3 kabar artis paling ramai” | roundup |

### 5.2.3 Proposed Schema

```json
{
  "story_mode": "roundup",
  "confidence": 0.97,
  "reason": "The topic requests multiple recent entertainment stories.",
  "item_count": 3,
  "target_duration_sec": 30,
  "requires_intro_card": true,
  "thumbnail_strategy": "roundup",
  "cta_strategy": "compare_items"
}
```

### 5.2.4 Topic Narrowing

If a broad topic cannot fit the duration target, the Segment Producer must either:

- reduce the number of stories; or
- select one story with the strongest editorial score.

Suggested ranking factors:

| Factor | Weight |
|---|---:|
| Freshness | 20% |
| Source credibility | 20% |
| Visual availability | 20% |
| Public interest | 15% |
| Conflict or curiosity strength | 15% |
| Uniqueness | 10% |

The exact weights should be configurable by niche.

---

## 5.3 Editorial Duration Budget

The Segment Producer should allocate time before the Scriptwriter produces narration.

### Example: 21-second roundup

```text
Intro/hook      2 seconds
Story 1         5 seconds
Story 2         5 seconds
Story 3         5 seconds
CTA             3 seconds
Transition      1 second total
```

### Example: 25-second single story

```text
Hook            3 seconds
Context         6 seconds
Evidence        8 seconds
Reveal          5 seconds
CTA             3 seconds
```

### Proposed Schema

```json
{
  "target_duration_sec": 25,
  "sections": [
    {
      "type": "hook",
      "duration_sec": 3
    },
    {
      "type": "context",
      "duration_sec": 6
    },
    {
      "type": "evidence",
      "duration_sec": 8
    },
    {
      "type": "reveal",
      "duration_sec": 5
    },
    {
      "type": "cta",
      "duration_sec": 3
    }
  ]
}
```

---

## 5.4 Structure Validation

Before the Scriptwriter and Visual Director proceed, the Segment Producer must validate:

### Roundup

- an intro explicitly signals multiple stories;
- the item count fits the duration;
- each story has at least one source;
- each story has at least one usable visual;
- each story receives a minimum duration;
- the CTA refers to the collection of stories;
- the thumbnail does not falsely imply a single-story explainer.

### Single Story

- one dominant claim or question is defined;
- supporting facts are linked to that story;
- visual evidence exists;
- unrelated stories are excluded;
- title, thumbnail, caption, and script share the same central subject.

---

## 5.5 Package Consistency Gate

The Reviewer should compare:

```text
topic
script
thumbnail text
caption
story mode
main entities
main claims
```

This check may use:

- deterministic entity extraction;
- embeddings for semantic similarity;
- a small text LLM only when needed.

### Example Failure

```json
{
  "status": "fail",
  "issue": "PACKAGE_SCOPE_MISMATCH",
  "thumbnail_scope": "single_story",
  "video_scope": "roundup",
  "caption_scope": "roundup",
  "reason": "Thumbnail presents a single definitive Ruben story while the video contains three unrelated stories."
}
```

---

## 5.6 Agent Responsibility in Phase 2

### Segment Producer

Owns:

- scope classification;
- story-mode decision;
- topic narrowing;
- duration budget;
- story-item selection;
- evidence requirements;
- format contract.

### Scriptwriter

Consumes the fixed mode and duration budget.

The Scriptwriter must not independently change:

- story mode;
- item count;
- primary topic;
- duration allocation.

### Visual Director

Implements the chosen format:

- roundup intro;
- story dividers;
- evidence cards;
- transition behavior;
- thumbnail visual concept.

### Reviewer

Validates package consistency and mode compliance.

---

## 5.7 Phase 2 Acceptance Criteria

Phase 2 is complete when:

- every job contains an explicit `story_mode`;
- broad topics are either narrowed or marked as roundup;
- roundup jobs include an explicit intro;
- story count is bounded by the duration budget;
- thumbnail strategy follows the story mode;
- package consistency is validated before approval;
- Job #4 no longer appears as an accidental three-story compilation;
- mode and budget decisions are traceable in diagnostics.

---

# 6. Phase 3 — Semantic Visual Relevance and Repair

## 6.1 Objective

Move from topic-level visual matching to claim-level and event-level visual relevance.

Phase 3 is the first stage that requires a vision-language model.

The pipeline must distinguish:

```text
same person
same topic
same event
same claim
direct evidence
```

These levels are not equivalent.

A video of the correct celebrity at an unrelated event may match the person but fail the event and claim.

## 6.2 Evidence-to-Visual Mapping

The Segment Producer should extend each story beat with a structured evidence contract.

### Proposed Story Beat Extension

```json
{
  "beat_id": "B04",
  "narration_intent": "Ruben explains the reason for stopping financial support.",
  "claim": {
    "subject": "Ruben",
    "action": "stopped financial support",
    "object": "child-related support",
    "event_date": null,
    "location": null,
    "confidence": 0.88
  },
  "visual_requirements": {
    "preferred": [
      "direct statement video",
      "interview about the same issue",
      "official social-media statement"
    ],
    "acceptable": [
      "same-event press footage",
      "verified article screenshot"
    ],
    "forbidden": [
      "unrelated red-carpet footage",
      "generic money footage presented as evidence",
      "old interview about another topic"
    ]
  }
}
```

## 6.3 Asset Portfolio Improvements

The current keyword-based relevance ranking should be retained as the first retrieval layer.

Phase 3 adds a second semantic layer.

### Retrieval Stages

```text
1. Keyword and metadata retrieval
2. URL and source validation
3. Frame extraction
4. OCR and entity inspection
5. Vision-language relevance scoring
6. Event and claim matching
7. Final asset ranking
```

### Candidate Scoring

Suggested initial score:

| Factor | Weight |
|---|---:|
| Person/entity match | 20% |
| Event match | 25% |
| Claim support | 25% |
| Temporal match | 10% |
| Source credibility | 10% |
| Visual quality | 5% |
| Watermark/text cleanliness | 5% |

These weights should remain configurable.

## 6.4 Multimodal Inspection

For each candidate asset:

1. extract representative keyframes;
2. run OCR;
3. detect visible people and scene;
4. identify source or logo where possible;
5. compare visual evidence with the beat;
6. calculate misleading-risk score.

### Suggested Output

```json
{
  "asset_id": "asset-17",
  "beat_id": "B04",
  "person_match": 0.96,
  "event_match": 0.41,
  "claim_support": 0.32,
  "temporal_match": 0.55,
  "visual_quality": 0.82,
  "misleading_risk": 0.71,
  "decision": "reject",
  "reason": "The person is correct, but the footage is from an unrelated film premiere."
}
```

## 6.5 Visual Director Semantic Timeline

The Visual Director should use word timestamps and semantic anchors.

A scene change should be motivated by:

- new person;
- new claim;
- new location;
- contradiction;
- reveal;
- direct quote;
- evidence presentation;
- emotional change.

The Visual Director should not change shots only because a fixed time interval has elapsed.

### Proposed Visual Action

```json
{
  "beat_id": "B04",
  "start_sec": 12.4,
  "end_sec": 17.8,
  "anchor_word": "akhirnya",
  "action": {
    "type": "tiktok_clip",
    "source_url": "https://...",
    "crop_subject": "face",
    "motion": "slow_push_in",
    "entry": "hard_cut_on_anchor",
    "exit": "cut_on_sentence_end"
  }
}
```

---

## 6.6 Timestamp-Level Semantic Review

The Reviewer should evaluate the video per beat or timestamp range.

### Review Questions

For every segment:

- What is the narration claiming?
- Who is shown?
- Which event is shown?
- Does the visual support the narration?
- Is the visual merely decorative?
- Could the viewer interpret it as false evidence?
- Is the source visible or traceable?
- Is the text readable?
- Is the visual held long enough?

### Suggested Output

```json
{
  "timestamp_start_sec": 12.4,
  "timestamp_end_sec": 17.8,
  "beat_id": "B04",
  "narration": "Ia membantah bahwa rumah tangganya sedang bermasalah.",
  "scores": {
    "person_match": 1.0,
    "event_match": 0.3,
    "claim_support": 0.2,
    "editorial_relevance": 0.4
  },
  "status": "revise",
  "failure_code": "WRONG_EVENT",
  "recommended_visual": "Current interview or verified statement screenshot"
}
```

---

## 6.7 Structured Repair Plan

The Reviewer should not return only `pass` or `fail`.

It should produce a structured repair plan.

### Proposed Repair Schema

```json
{
  "decision": "revise",
  "max_repair_cycles": 2,
  "patches": [
    {
      "beat_id": "B04",
      "timestamp_start_sec": 12.4,
      "timestamp_end_sec": 17.8,
      "action": "replace_visual",
      "reason": "wrong_event",
      "required_visual": "same-event interview or official statement",
      "rerun_from": "visual_director"
    },
    {
      "beat_id": "B06",
      "action": "move_caption",
      "reason": "text_collision",
      "target_zone": "top_safe"
    }
  ]
}
```

## 6.8 Repair Execution

The Engine should route repairs according to failure type.

| Failure | Retry target |
|---|---|
| Broken source URL | Visual Director |
| Wrong event | Segment Producer asset retrieval or Visual Director |
| Text collision | Visual Director |
| Black frame | Composer |
| Duration mismatch | Composer or Visual Director |
| Package mismatch | Segment Producer |
| Script scope mismatch | Segment Producer and Scriptwriter |
| Unsafe factual claim | Segment Producer and Scriptwriter |

Do not rerun the whole pipeline unless required.

## 6.9 Partial Render

Where technically practical, Composer should support rendering only changed scenes and concatenating them into the final timeline.

Initial implementation may still perform a full final render while reusing unchanged intermediate assets.

True partial final-render replacement can be introduced later if codec and timestamp consistency are guaranteed.

---

## 6.10 Phase 3 Acceptance Criteria

Phase 3 is complete when:

- every visual candidate receives semantic relevance metadata;
- same-person but wrong-event footage is detectable;
- story beats contain preferred, acceptable, and forbidden visual guidance;
- Reviewer produces timestamp-level semantic feedback;
- Reviewer can emit structured repair instructions;
- the Engine reruns only the relevant pipeline stages;
- maximum automated repair cycles are configurable;
- before/after quality scores are recorded;
- Job #4-style person-level relevance is upgraded to event- and claim-level relevance.

---

# 7. Revised Pipeline

```text
Topic
  ↓
Safety Agent
  ↓
Segment Producer
  - topic scope
  - story mode
  - duration budget
  - story beats
  - evidence requirements
  - asset portfolio
  ↓
Scriptwriter
  - continuous narration
  - mode-compliant structure
  ↓
Voice Producer
  - voice-over
  - word timestamps
  ↓
Visual Director
  - asset resolution
  - OCR-aware layout
  - face-safe layout
  - semantic timeline
  - intro/format implementation
  ↓
Composer
  - render
  - duration guard
  - black/freeze/coverage checks
  ↓
Reviewer
  - deterministic hard gates
  - package consistency
  - timestamp-level semantic relevance
  - structured repair plan
  ↓
Engine
  - approve
  - retry selected agent
  - limit repair cycles
```

---

# 8. Proposed Code Structure

```text
clipper_agency/
├── agents/
│   ├── segment_producer.py
│   ├── scriptwriter.py
│   ├── voice_producer.py
│   ├── visual_director.py
│   ├── composer.py
│   └── reviewer.py
├── core/
│   ├── visual_coverage.py
│   ├── frame_sampler.py
│   ├── text_detection.py
│   ├── text_collision.py
│   ├── safe_area.py
│   ├── face_detection.py
│   ├── semantic_visual_review.py
│   ├── package_consistency.py
│   └── repair_router.py
├── config/
│   └── schema.py
└── tests/
    ├── fixtures/
    │   └── job4/
    ├── test_visual_coverage.py
    ├── test_text_collision.py
    ├── test_safe_area.py
    ├── test_story_mode.py
    ├── test_package_consistency.py
    ├── test_semantic_visual_review.py
    └── test_job4_quality_regression.py
```

---

# 9. Schema Additions

Recommended Pydantic models:

```text
StoryModeDecision
DurationBudget
VisualCoverageResult
DetectedTextRegion
TextCollisionIssue
SafeAreaIssue
EvidenceContract
VisualRelevanceScore
PackageConsistencyResult
RepairPatch
RepairPlan
```

All new outputs must be JSON serializable and persisted in agent diagnostics.

---

# 10. Configuration

Recommended configuration areas:

```yaml
quality:
  visual_coverage:
    black_frame_max_ms: 200
    empty_frame_max_ms: 300
    freeze_warning_ms: 1500
    final_visual_gap_max_ms: 200

  text_collision:
    subtitle_overlap_max: 0.20
    headline_overlap_max: 0.15
    source_text_warning_area_ratio: 0.25
    source_text_reject_area_ratio: 0.40

  safe_area:
    face_overlap_max: 0.15
    platform: tiktok

  semantic_review:
    enabled: true
    minimum_claim_support: 0.70
    maximum_misleading_risk: 0.30
    max_repair_cycles: 2
```

Niche and account configuration may override these defaults.

---

# 11. Testing Strategy

## 11.1 Job #4 Regression Fixture

Job #4 should become a permanent regression fixture.

Expected detected defects:

```text
BLACK_FRAME
TEXT_COLLISION
SOURCE_TEXT_DENSITY
PACKAGE_SCOPE_MISMATCH
ROUNDUP_FORMAT_WEAKNESS
CLAIM_VISUAL_RELEVANCE_WEAKNESS
```

## 11.2 Unit Tests

Test:

- black-frame interval extraction;
- freeze detection;
- OCR bounding-box normalization;
- collision geometry;
- safe-area rules;
- story-mode classification;
- duration-budget validation;
- package consistency;
- repair routing.

## 11.3 Integration Tests

Test:

- Visual Director receives OCR map;
- Composer emits coverage diagnostics;
- Reviewer blocks before LLM;
- package mismatch routes to Segment Producer;
- semantic mismatch routes to Visual Director;
- repair-cycle limits are enforced.

## 11.4 Golden Video Set

Maintain a set of manually reviewed examples:

- single-person interview;
- roundup;
- image-only story;
- source video with burned-in captions;
- video with watermark;
- wrong-event visual;
- black-frame output;
- freeze-frame output;
- thumbnail mismatch;
- source quote insertion.

---

# 12. Rollout Plan

## Iteration 1 — Phase 1A

Implement:

- visual coverage;
- black-frame detection;
- freeze detection;
- extended Reviewer hard gates.

## Iteration 2 — Phase 1B

Implement:

- frame sampler;
- OCR text map;
- text collision;
- safe-area and face overlap.

## Iteration 3 — Phase 2A

Implement:

- StoryModeDecision;
- Topic Scope Classifier;
- explicit roundup/single-story contracts.

## Iteration 4 — Phase 2B

Implement:

- duration budget;
- topic narrowing;
- package consistency.

## Iteration 5 — Phase 3A

Implement:

- EvidenceContract;
- candidate keyframe inspection;
- multimodal relevance scoring.

## Iteration 6 — Phase 3B

Implement:

- timestamp-level Reviewer;
- RepairPlan;
- repair routing;
- maximum repair cycles.

---

# 13. Non-Goals

This design does not include:

- direct social-platform publishing;
- account analytics;
- engagement-based learning;
- Creative Memory;
- multi-account scheduling;
- Kubernetes scaling;
- PostgreSQL migration;
- new top-level autonomous agents;
- full generative-video creation;
- removal of third-party watermarks through inpainting.

Those items belong to later roadmap stages.

---

# 14. Risks

## OCR Accuracy

Stylized captions may reduce OCR confidence.

Mitigation:

- prioritize text detection over recognition;
- preprocess contrast and scale;
- use persistence across frames;
- treat low-confidence large regions as possible text.

## False Black-Frame Detection

Dark scenes may be classified as black.

Mitigation:

- combine FFmpeg detection with frame variance;
- allow niche-specific thresholds;
- inspect adjacent frames.

## VLM Cost

Semantic inspection may increase cost.

Mitigation:

- only inspect shortlisted assets;
- use sampled keyframes;
- cache results by asset hash;
- run deterministic gates first.

## Over-Strict Gates

Quality gates may reject usable footage.

Mitigation:

- begin in report-only mode;
- collect false-positive data;
- promote checks from warning to hard fail gradually.

## Agent Responsibility Overlap

Segment Producer, Visual Director, and Reviewer may duplicate decisions.

Mitigation:

- Segment Producer defines intent;
- Visual Director decides implementation;
- Reviewer validates final compliance;
- Engine performs routing only.

---

# 15. Final Architecture Decision

Phase 1, Phase 2, and Phase 3 will not introduce new top-level agents.

The capabilities will be integrated as follows:

```text
Segment Producer
→ decides what story is being told and what evidence is required

Visual Director
→ decides how the evidence is shown and how the timeline is constructed

Composer
→ guarantees that the final rendered media is technically complete

Reviewer
→ proves that the final output follows the story, visual, and quality contracts

Engine
→ routes structured repairs to the correct existing agent
```

This design preserves the current architecture while substantially improving video quality, visual relevance, and repairability.
