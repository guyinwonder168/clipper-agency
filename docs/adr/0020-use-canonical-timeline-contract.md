# ADR 0020: Use Canonical Timeline Contract for Cross-Agent Timing

**Date:** 2026-06-06
**Status:** Proposed
**Phase:** Tier 4 / Phase 20 candidate

## Context

The job 2 retest after Phase 19 exposed a pipeline-level timing problem. Scriptwriter estimated short scene durations, Voice Producer generated much longer natural narration, Visual Director planned visuals from script estimates, and Composer rendered from mismatched inputs. The result was a video that exceeded the MVP 60s hard limit and had missing subtitles on the retry path.

The root cause is that no single component owns the final scene timeline. Each agent inferred timing independently.

## Decision

Introduce an Orchestrator-owned canonical timeline contract.

The timeline is created after Voice Producer and before Visual Director by combining:

- Researcher `content_direction`.
- validated Scriptwriter scene roles, text, word counts, and estimated durations.
- Voice Producer actual per-scene audio durations.
- niche/platform duration target and hard limit.

The canonical timeline becomes the source of truth for Visual Director and Composer.

Researcher will recommend content direction in its existing LLM synthesis call. Orchestrator validates that direction deterministically and derives word/time budgets. Scriptwriter obeys that budget. Voice Producer measures actual audio duration. Timeline Reconciler creates final start/end times and fails before visual/render spend if actual duration exceeds the hard limit.

## Alternatives Considered

### Let Composer fix timing

- **Pros:** Localized change.
- **Cons:** Composer would have to cut or stretch assets/audio after all expensive work is done. Trimming narration cuts sentences and damages quality.

### Add a new LLM Content Planner agent

- **Pros:** More flexible creative planning.
- **Cons:** Additional cost and failure point. Researcher already performs an LLM synthesis over factual data and is the better place to recommend content direction.

### Voice Producer owns timeline reconciliation

- **Pros:** Voice Producer has actual audio durations.
- **Cons:** It should not own story format, scene roles, visual instructions, or platform policy. Those are cross-agent orchestration concerns.

### Orchestrator-owned timeline service

- **Pros:** Deterministic, cheap, centralizes cross-agent contracts, preserves agent boundaries.
- **Cons:** Changes the earlier "Orchestrator dumb, agents smart" principle; Orchestrator now owns a small but critical contract reconciliation responsibility.

## Rationale

- Timing is a cross-agent invariant, so it belongs at the orchestration boundary.
- The cheapest place to prevent overlong videos is before TTS via a local script duration gate.
- The safest place to finalize timing is after TTS, using actual `ffprobe` durations.
- Visual Director should plan assets to match real narration, not guessed script durations.
- Composer should render an approved timeline, not infer one.

## Consequences

- **Positive:** Audio, subtitles, visuals, opening hook, and CTA share one timeline.
- **Positive:** Overlong jobs fail before visual planning/rendering spend.
- **Positive:** No extra LLM call is needed for MVP content planning.
- **Positive:** Retry/debug behavior improves because timeline artifacts are explicit.
- **Negative:** Orchestrator becomes responsible for more than sequencing; it owns timeline contract validation.
- **Negative:** Existing agent prompts/contracts must change.
- **Negative:** Main docs and traceability matrix must be updated to avoid contract drift.
- **Neutral:** MVP keeps 45-55s target and 60s hard limit as product policy, while future TikTok API integration can read account-specific `max_video_post_duration_sec`.
