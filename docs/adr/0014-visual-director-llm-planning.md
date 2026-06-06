# ADR 0014: Visual Director LLM-Driven Per-Scene Planning

**Date:** 2026-05-31
**Status:** Accepted
**Commits:** `7b45688` (merge commit), `95cf54e` (doc updates)
**Phase:** 16 (Visual Director LLM Planning), updated after Phases 17-19

## Context

The Visual Director agent was the least intelligent agent in the pipeline. It operated with a blind sequential strategy:

1. Take the list of source URLs from the Researcher.
2. Try to download each URL via yt-dlp in order.
3. For scenes without source clips, blindly search Pexels using the niche tag.
4. For scenes still without assets, generate a text card.

This approach ignored the Researcher's carefully gathered data — engagement metrics, content descriptions, source types — and treated all sources equally. The result was often irrelevant or low-quality visual selections that didn't match scene content.

The pipeline had rich research data (research contract JSON + research brief markdown) but the Visual Director never consumed it. This was a waste of the Researcher's LLM call and token spend.

Additionally, text cards (the fallback visual) were plain colored backgrounds with no contextual imagery, making them visually unappealing.

## Decision

Replace the Visual Director's blind sequential logic with LLM-driven per-scene planning:

1. **Data compaction** (`_compact_research_data()`): Read `research_contract.json` + `research_brief.md`, strip noise (raw HTML, boilerplate), sort sources by engagement relevance, produce ~2K char compact text for LLM context.

2. **LLM planning** (`_plan_with_llm()`): Send compact research + script scenes + niche config to LLM with structured output schema. LLM returns per-scene plan with `action.type` enum (`tiktok_clip`, `pexels_video`, `pexels_image`, `text_card`), `reasoning` (free text), and action-specific parameters.

3. **Treatment and transition metadata** (Phase 17+): Visual Director plans now include treatment and transition choices from `templates/treatments.yaml` so Composer can apply data-driven FFmpeg effects instead of hardcoded visual behavior.

4. **Dispatch execution** (`_execute_plan()` + `_execute_action()`): Route each action to handler (`_exec_tiktok_clip`, `_exec_pexels_video`, `_exec_pexels_image`, `_exec_text_card`). Each handler downloads or generates the visual asset.

5. **3-tier image fallback** (for text cards): `_fetch_image()` tries Pexels photo search (`search_photos()`) → Firecrawl article og:image → gradient card background. Every text card gets a relevant image when possible.

6. **Legacy fallback**: When LLM planning fails or returns `None`, `_run_legacy_planning()` uses the original sequential URL assignment + Pexels fallback.

**Configuration:** New `visual_director_model` field in `AppSettings` (default `mimo-v2-flash`), env var `VISUAL_DIRECTOR_MODEL`.

**Design principle:** "Orchestrator dumb, agents smart." The engine passes research file paths to Visual Director; the agent decides how to use them. The Orchestrator never filters or interprets research data.

**Known limitation after Phase 19:** Visual Director still plans durations from Scriptwriter estimates rather than actual Voice Producer audio durations. The job 2 retest showed that this can produce visual scenes shorter than narration. Tier 4 will introduce an Orchestrator-owned canonical timeline contract before Visual Director planning; see ADR 0020.

## Alternatives Considered

### Keep legacy sequential planning

- **Pros:** Simple, no additional LLM call, no new failure modes.
- **Cons:** Wastes research data. Produces irrelevant visuals. No intelligence in visual selection. Researcher's engagement metrics and source descriptions ignored.

### Rule-based heuristic planning

- **Pros:** No LLM cost/latency. Deterministic behavior.
- **Cons:** Requires encoding domain knowledge (which source types match which scene types) as brittle rules. Doesn't adapt to new niches. Doesn't scale across content types. Hard to maintain as niche configs evolve.

### Full agent-to-agent communication

- **Pros:** Researcher and Visual Director could negotiate directly.
- **Cons:** Violates the architecture principle of DB-mediated communication (agents communicate via DB state, not direct calls). Requires significant Orchestrator changes. Not MVP-appropriate.

## Rationale

- LLM planning leverages the research data the pipeline already pays to collect, improving visual relevance without additional data gathering.
- The dispatch table pattern keeps execution logic simple and testable — each action type has an isolated handler with clear inputs/outputs.
- Legacy fallback ensures zero regression: if LLM fails, the original behavior is preserved.
- The `visual_director_model` env var follows the established per-agent model config pattern (ADR 0007).
- Adding `search_photos()` to PexelsService enables image enrichment for text cards, a capability the service was missing despite already having video search.

## Consequences

- **Positive:** Visual selections are contextually relevant — LLM matches sources to scenes using research data.
- **Positive:** Text cards now include relevant images via 3-tier fallback, significantly improving visual quality.
- **Positive:** Treatment and transition metadata lets Visual Director communicate production intent to Composer without hardcoding effects in either agent.
- **Positive:** Extensible — adding new action types (e.g., `stock_video`, `ai_generated_image`) only requires a new handler in the dispatch table.
- **Positive:** Research data is utilized, justifying the Researcher's LLM cost.
- **Negative:** Additional LLM call per job (Visual Director planning) adds ~2-5 seconds latency and token cost.
- **Negative:** New failure mode — LLM can return invalid JSON, empty plan, or unknown action types. Mitigated by legacy fallback + defensive parsing.
- **Negative:** Prompt file (`prompts/visual_director.md`) is now a critical dependency. Poor prompt quality = poor visual decisions.
- **Negative:** Duration planning remains incomplete until Visual Director consumes the reconciled timeline from Tier 4.
- **Neutral:** The `visual_director_model` default (`mimo-v2-flash`) is a cost-optimized choice. Premium deployments may want to upgrade for better planning quality.
