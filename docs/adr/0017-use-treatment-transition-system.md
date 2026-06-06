# ADR 0017: Use YAML-Driven Treatment and Transition System

**Date:** 2026-06-06
**Status:** Accepted
**Phase:** 17

## Context

After template rendering and Visual Director LLM planning, the pipeline could select visual assets but still lacked a stable vocabulary for production style. Effects such as Ken Burns, large hook captions, B-roll treatment, and transitions were either hardcoded or absent. Changing style risked code changes in Visual Director and Composer.

The project requires niche/template behavior to be data-driven. Changing visual treatments should not require application code changes when the effect can be represented declaratively.

## Decision

Define visual treatments and transitions in `templates/treatments.yaml` and pass treatment metadata through the Visual Director → Composer contract.

The treatment system includes:

- 9 treatment names such as `ken_burns_zoom_in`, `broll_standard`, `hook_big_caption`, `text_card_reveal`, and `fade_to_black`.
- 5 transition names such as `crossfade`, `hard_cut`, `wipe_left`, `dissolve`, and `circle_open`.
- FPS rules and pacing rules.
- Composer-side treatment config loading and filter generation.

Visual Director selects the treatment/transition based on scene purpose and content. Composer applies the corresponding FFmpeg filter chain.

## Alternatives Considered

### Hardcode treatments in Composer

- **Pros:** Fastest implementation.
- **Cons:** Visual Director could not reason about available styles; style changes would require code edits.

### Put all treatment logic inside Visual Director

- **Pros:** Keeps creative decisions in one agent.
- **Cons:** Visual Director would need FFmpeg-specific implementation knowledge, coupling creative planning to render details.

### YAML-driven metadata contract

- **Pros:** Data-driven, testable, keeps planning and rendering responsibilities separate.
- **Cons:** Requires strict validation and fallback behavior for unknown treatments.

## Rationale

- YAML keeps treatments configurable and reviewable.
- Visual Director owns creative selection; Composer owns FFmpeg execution.
- The contract is small: treatment name, transition name, duration, and optional headline/text metadata.
- Unknown treatment fallback prevents hard failures from LLM or config drift.

## Consequences

- **Positive:** Treatments and transitions are reusable across templates and niches.
- **Positive:** Visual Director can express production intent without generating FFmpeg filters.
- **Positive:** Composer remains deterministic and testable.
- **Negative:** YAML entries and Composer filter builders must stay aligned.
- **Negative:** Text-based treatment filters require careful drawtext escaping.
- **Neutral:** Some advertised treatments, such as slow motion, may need cross-agent duration coordination before safe production use.
