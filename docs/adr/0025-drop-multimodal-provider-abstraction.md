# ADR 0025: Drop Superseded Multimodal Provider Abstraction

**Date:** 2026-06-15
**Status:** Accepted

## Context

Phase 22 introduced multimodal visual inspection for the Visual Director via two parallel
modules created in the same commit (`49d5b3f`):

1. `clipper_agency/core/multimodal_provider.py` — a `MultimodalProvider` Protocol
   (L28) plus a concrete `OpenRouterMultimodalProvider` (L165).
2. `clipper_agency/llm/multimodal_client.py` — a `MultimodalInspectionClient` class
   with tracing, `max_frames` capping, and decision inference.

Only `multimodal_client.py` was wired into production — it received integration
commit `137c215` ("visual director candidate inspection + LLM trace wiring") and
is imported by `clipper_agency/agents/visual_director.py`. The `multimodal_provider.py`
module was **never instantiated** by any production code.

The Phase 23 wiring plan (`docs/plans/2026-06-10-phase23-wire-unwired-modules.md`)
explicitly catalogued this:

- Line 42: listed `multimodal_provider.py` as unwired module #14.
- Line 68 (Out of Scope): "VLM provider changes (multimodal_client already wired in VD)".

The result: two modules implementing the same concept with near-identical code
(image base64 encoding, JSON response parsing, score keys, result/error dict builders),
producing a 0.1% duplicated-lines metric across the two files. The `MultimodalProvider`
Protocol has zero production consumers.

## Decision

**Delete `clipper_agency/core/multimodal_provider.py` and its tests.** Defer any
provider abstraction until a second concrete multimodal backend exists (e.g. a
direct Gemini or Anthropic multimodal call rather than OpenRouter-routed).

At that future point, extract the Protocol from the real, production-tested
`MultimodalInspectionClient` rather than from a speculative, never-wired example.

## Alternatives Considered

### Keep Both + Extract Shared Helpers

- Create a shared helpers module (`encode_image_as_data_uri`, `parse_inspection_json`,
  `_SCORE_KEYS`, result builders) that both files import.
- **Pros:** Reduces duplication metric to 0% while retaining the Protocol.
- **Cons:** Keeps dead code alive. The Protocol is speculative — guessed from one
  OpenRouter example, not derived from two real providers. Violates YAGNI. Modifies
  production `multimodal_client.py`, risking behavioral drift. Higher churn for no
  user-facing benefit.

### Leave As-Is

- 0.1% duplication passes the 3% SonarCloud gate.
- **Pros:** Zero effort, zero risk.
- **Cons:** Two implementations of the same concept invite future confusion
  ("which do I modify?"). Dead code accumulates. The duplication already caused this
  metric flag and the resulting review burden.

## Rationale

- **KISS / YAGNI (AGENTS.md):** A Protocol abstraction built from a single concrete
  example is over-engineering. Generalize from two real implementations, not one.
- **The Phase 23 plan already decided this:** wiring the provider was explicitly
  out-of-scope because the client covers the production need.
- **Low risk:** deletion touches no production call sites — `multimodal_provider.py`
  has zero production imports. Only a smoke-test reference and the module's own tests
  are affected.
- **Reversible:** if the abstraction is needed later, it can be re-introduced as a
  proper Protocol extracted from the two real providers at that time.
