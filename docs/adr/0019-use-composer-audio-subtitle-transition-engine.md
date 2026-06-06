# ADR 0019: Use Composer Audio, Subtitle, and Transition Engine

**Date:** 2026-06-06
**Status:** Accepted
**Phase:** 19

## Context

The pre-Phase 19 Composer could generate a video, but job output showed production issues:

- voice tracks could clash because multiple scene narrations were mixed instead of sequenced.
- subtitles were missing even though Scriptwriter already produced text.
- Visual Director treatment/transition metadata was not fully applied.
- output flags were not consistently production-ready.
- dead `_build_filter()` logic still contained broken `amix` assumptions.

The Composer needed to become a contract-obedient renderer rather than a best-effort assembler.

## Decision

Implement a dedicated Composer rendering engine for audio sequencing, subtitles, xfade transitions, treatment filters, and production output flags.

Key decisions:

- Replace broken `amix` with per-scene concat sequencing.
- Use Mode A for paired audio+video concat when there are no xfade transitions.
- Use Mode B for audio-only concat when xfade handles the video chain.
- Generate subtitles from script scene text using timed drawtext overlays.
- Build xfade/concat mixed transition chains with duration clamping and safety margins.
- Apply treatment filters from `templates/treatments.yaml` through `TreatmentFilterBuilder`.
- Enforce production flags: H.264/AAC, `yuv420p`, and `+faststart`.
- Remove dead `_build_filter()` code.

## Alternatives Considered

### Keep `amix`

- **Pros:** Simple filter graph.
- **Cons:** Incorrect for per-scene narration; voice tracks overlap and become unintelligible.

### Render each scene as a separate final clip then concatenate files

- **Pros:** Easier local reasoning per scene.
- **Cons:** More intermediate files, more FFmpeg passes, harder xfade timing, more filesystem surface.

### Single filter graph with explicit labels

- **Pros:** One render pass, explicit audio/video ownership, testable filter strings.
- **Cons:** Complex graph construction and edge cases around xfade duration.

## Rationale

- Per-scene narration must play sequentially, not simultaneously.
- Subtitle overlays are already derivable from Scriptwriter output; no extra LLM is required.
- xfade chains must account for short clips and unknown transition names to avoid FFmpeg failures.
- Production flags improve platform compatibility and streaming readiness.

## Consequences

- **Positive:** Voice tracks no longer clash.
- **Positive:** Subtitle generation becomes deterministic from script text.
- **Positive:** Visual Director's treatment/transition intent is finally consumed by Composer.
- **Positive:** Output is closer to TikTok-ready MP4 requirements.
- **Negative:** Filter graph complexity increased.
- **Negative:** Retry paths must pass script scenes and future timeline artifacts, otherwise subtitle/timing contracts can be lost.
- **Negative:** Per-scene audio sequencing revealed a deeper cross-agent timing problem: actual TTS duration can exceed script/visual duration estimates.
- **Neutral:** Tier 4 will solve the timing ownership issue with a canonical timeline contract instead of trimming audio mid-sentence.
