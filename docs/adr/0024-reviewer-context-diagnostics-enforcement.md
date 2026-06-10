# ADR 0024: Reviewer Context and Diagnostics Enforcement Contract

**Date:** 2026-06-11
**Status:** Accepted

## Context

Phase 23 runtime quality gates depend on Composer diagnostics and rendered scene manifest evidence. Reviewer deterministic gates read `kwargs.get("diagnostics")` and expect `rendered_scene_manifest` to behave like a dictionary when consuming scene entries. The production engine paths passed `story_beats`, `word_timestamps`, and `rendered_scene_manifest`, but omitted `compose_output["diagnostics"]`; the manifest was also a Pydantic model before serialization. Without a fixed contract, visual coverage, text collision, safe-area, package consistency, timestamp semantic review, and semantic visual review gates could skip evidence or fail in production runs.

## Decision

Treat Reviewer context as a fixed engine-to-reviewer contract:

- Engine passes `story_beats`, `word_timestamps`, `rendered_scene_manifest`, and `diagnostics` to Reviewer in both normal pipeline and repair rerun paths.
- Composer manifest is serialized to dict before Reviewer gate code consumes `entries`.
- Reviewer gate order is enforced as: `visual_coverage → text_collision → safe_area → package_consistency → timestamp_semantic → semantic_review → LLM`.
- Composer diagnostics remain structured evidence for deterministic gates and repair routing rather than free-form text.

## Alternatives Considered

1. **Have Reviewer read diagnostics from the filesystem** — Rejected: couples Reviewer to artifact layout, reintroduces path-safety concerns, and makes tests dependent on workspace state.
2. **Run deterministic gates only in direct calls or tests** — Rejected: production pipeline would not be protected, defeating the purpose of runtime quality gates.
3. **Add a new top-level quality agent** — Rejected: unnecessary cost/latency and state complexity; deterministic services already belong inside the existing Reviewer gate chain.
4. **Suppress manifest serialization errors** — Rejected: hides contract drift and prevents deterministic gates from using scene evidence.

## Consequences

- Reviewer deterministic gates can enforce Composer evidence in both normal and repair paths.
- Timestamp-level semantic review can map rendered scenes to story beats with evidence contracts.
- Engine must preserve Composer context across retry and repair cycles.
- No new top-level agents are introduced; Reviewer remains the existing G10 quality gate.
- Regression tests should cover normal pipeline and repair rerun reviewer call sites plus manifest serialization.