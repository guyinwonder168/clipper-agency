# ADR 0027 — Asset-qualification cache-miss inspection: delegate to VD, do not lift

**Status:** Accepted
**Date:** 2026-06-18
**Supersedes (locally):** the "verbatim lift of `VD._run_multimodal_inspection`" wording
in `docs/plans/pr5-asset-qualification-design.md` §4 / §8 (PR 5, SLICE 6).

## Context

PR 5 introduces a pre-Visual-Director asset-qualification boundary
(`clipper_agency/core/asset_qualification.py`). On a cache miss,
`_score_candidate` must run a multimodal inspection of the candidate. The locked PR 5
design specified this as a **verbatim lift of `VD._run_multimodal_inspection`**
(`clipper_agency/agents/visual_director.py:895-952`).

A 3-lens necessity/verification workflow (`wf_f6b31e8b`, 2026-06-18, confidence 0.92)
found that `VD._run_multimodal_inspection` is **not** a self-contained ~58-line function.
It transitively pulls in:

- `self._extract_candidate_frames` (image/video download + frame extraction)
- `self._try_enhanced_frame_inspection` → `run_frame_inspection_pipeline`
- `self._run_ocr_and_face_on_frames` (PaddleOCR + MediaPipe ML)
- `self._trace_writer`, `self._face_data` (VD instance state)
- internally constructs `OpenRouterClient` + `MultimodalInspectionClient`

A faithful verbatim lift would therefore duplicate ~140 lines of ML machinery, and a
*minimal* lift (frames + `inspect_asset` only, dropping OCR/enhanced/face) would produce
an inspection **different from VD's under the same cache key** — because the cache key
(`compute_cache_key`) does not include OCR/face/enhanced inputs. That divergence is the
HIGHEST-rated risk in the design (§12: cache-namespace drift → VD re-spends VLM on a
candidate the qualification pass already "inspected" with a different, inferior result).

## Decision

**`_run_inspection` delegates to an injected callable** that the orchestrator's engine
seam binds to `VisualDirectorAgent._run_multimodal_inspection`, rather than lifting that
method's body.

```python
def _run_inspection(candidate, beat, job_id, cache_dir, cache_key, agent_dir, inspector):
    if inspector is None:
        logger.warning("...no inspector injected; candidate will be rejected.")
        return None
    return inspector(candidate, beat, job_id, cache_dir, cache_key, agent_dir)
```

The engine seam (SLICE 7/10) constructs a `VisualDirectorAgent` instance and passes its
bound `_run_multimodal_inspection` as `inspector` (alongside the injected
`RecoveryPolicy.discover_fn`).

## Alternatives considered

1. **Verbatim lift of the full `VD._run_multimodal_inspection` (+ the 4 helpers).**
   Rejected — duplicates ~140 lines of OCR/face/enhanced ML into `core/`, violating ADR
   0026 pt. 4 ("enforce contracts, do not rebuild") and creating a second copy that **will**
   drift from VD (the same DRY-delegation concern design §8 already flags for
   `_score_one_candidate`).
2. **Minimal lift (frames + `inspect_asset` + `store` only).** Rejected — silently drops
   the OCR/enhanced/face stages VD applies, so the cached inspection differs from VD's
   under the same cache key. VD (post-qualification) would hit the qualification pass's
   inferior cached result. This is the §12 HIGHEST-rated cache-namespace drift risk.
3. **Extract shared inspection helpers into a new `core/inspection_pipeline.py` consumed
   by BOTH VD and `asset_qualification`.** Deferred — this is the strictly-best DRY end
   state (one definition, no drift by construction) but it is a larger refactor that moves
   VD's private helpers into a shared module, exceeding PR 5's "minimal blast radius"
   mandate. Recorded as the follow-up that collapses this delegation (and the SLICE 1
   cache-key gate) into a single shared inspection module.

## Consequences

- **+** Reuses VD's exact inspection: frame ownership stays in VD, no double extraction,
  cached output byte-identical to VD's → the "100% cache hit, no double-VLM" guarantee
  (design §6 step 6 / §8) holds by construction.
- **+** No ~140-line ML duplication; ADR 0026 "do not rebuild" honored.
- **+** The module still imports neither `visual_director` nor `segment_producer`
  (the inspector is injected, preserving the design's import-cycle constraint).
- **−** `_run_inspection` is a thin delegate (one forwarding call) rather than
  self-contained. This is acceptable: its contract is "run VD's inspection on a cache
  miss," and delegation is the most faithful implementation of that contract.
- **−** `inspector`'s parameter type changes from `MultimodalInspectionClient` (locked
  design §4/§6) to `Callable[..., dict | None]`. The engine seam must bind
  `VD._run_multimodal_inspection` (not construct a `MultimodalInspectionClient`) — a
  SLICE 7/10 wiring note.
- **Follow-up:** extract the shared inspection pipeline (`_extract_candidate_frames` +
  OCR/face/enhanced + `inspect_asset`) into `core/inspection_pipeline.py` consumed by
  both VD and this module, removing the delegation indirection and the SLICE 1
  cache-key-literal drift risk in one move (same DRY-delegation follow-up design §8
  lists for `_score_one_candidate`).

## Compliance

ADR 0026 pt. 4 (the one genuinely-new architectural element of the phase) is honored:
the qualification boundary remains pure orchestration — it composes existing modules
(`inspection_cache`, `candidate_semantic_ranker`, `semantic_visual_review`) and now
**delegates** the inspection to VD's existing method rather than rebuilding it. No new
media-analysis subsystem, no new agent, no new gate.
