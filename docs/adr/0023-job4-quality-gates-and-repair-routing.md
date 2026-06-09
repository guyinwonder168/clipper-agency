# ADR 0023: Job #4 Quality Gates and Repair Routing

**Date:** 2026-06-09
**Status:** Accepted

## Context

Job #4 output analysis revealed black frames, text collisions, package-scope mismatches, and claim-to-visual irrelevance that the existing Reviewer LLM-only gates did not catch. The existing Reviewer relied on a single multimodal LLM call for quality assessment, which was expensive and inconsistent at detecting deterministic issues like frame-level black screens, overlapping text regions, and story-mode/package inconsistencies.

## Decision

Add deterministic visual quality gates, story-mode/package consistency checks, semantic relevance contracts, and structured repair routing inside the existing seven-agent architecture instead of introducing new top-level agents.

Ten new core modules in `clipper_agency/core/`:

1. **`visual_coverage.py`** — `evaluate_visual_coverage()` scores frame-level visual completeness via sampled thumbnails.
2. **`frame_sampler.py`** — `plan_frame_samples()` + `deduplicate_samples_by_hash()` produce deterministic sampling schedules.
3. **`text_detection.py`** — `normalize_text_region()` + `filter_text_regions()` detect and normalize text bounding boxes.
4. **`text_collision.py`** — `detect_text_collisions()` + `detect_source_text_density()` flag overlapping or excessively dense text.
5. **`safe_area.py`** — `detect_safe_area_issues()` checks caption and overlay placement against TikTok safe zones.
6. **`story_mode.py`** — `classify_story_mode()` determines narrative structure (single_deep_dive, three_roundup, two_highlight).
7. **`duration_budget.py`** — `allocate_duration_budget()` distributes total duration across beats by role weight.
8. **`package_consistency.py`** — `evaluate_package_consistency()` validates story mode matches actual scene/clip composition.
9. **`semantic_visual_review.py`** — `score_visual_relevance()` scores claim-to-visual alignment using keyword overlap and evidence contracts.
10. **`repair_router.py`** — `route_repair()` + `build_repair_plan()` map quality failures to the correct agent for repair.

New schema models in `config/schema.py`: `VisualCoverageIssue`, `VisualCoverageResult`, `DetectedTextRegion`, `TextCollisionIssue`, `SafeAreaIssue`, `StoryModeDecision`, `DurationBudgetSection`, `DurationBudget`, `EvidenceContract`, `VisualRelevanceScore`, `PackageConsistencyResult`, `RepairPatch`, `RepairPlan`.

Reviewer gate chain (ordered, all deterministic before LLM): `visual_coverage → text_collision → safe_area → package_consistency → semantic_review → LLM`.

## Alternatives Considered

1. **Add new top-level agents** for each quality area — Rejected: more LLM calls, higher cost/latency, more state transitions, harder debugging, overlapping responsibilities.
2. **Extend existing agents with deterministic services** — Chosen: preserves architecture, cheaper, offline-testable, composable.
3. **Single monolithic quality service** — Rejected: lower composability, harder to test individual checks, couples unrelated concerns.

## Consequences

- Reviewer LLM only runs after all deterministic gates pass, saving cost on clearly broken outputs.
- Segment Producer owns story scope and evidence contracts.
- Visual Director owns layout-level compliance (safe-area, text collision).
- Composer owns frame-level technical quality (black/freeze, coverage).
- Engine routes structured repairs to the correct existing agent via `RepairPlan`.
- New modules are pure functions with injected dependencies for offline testability.
- 10 new core modules, 0 new top-level agents.
- 1210+ offline tests passing, 93%+ coverage.
