# FIX-8 — word_range cue-anchor contract (root-cause fix for LLM mis-counting)

**Status:** DESIGN APPROVED (approach A + start_cue), implementation pending
**Date:** 2026-07-28
**Governing ADR:** 0030 (Inter-Agent Contract Gates — quality work, no-rebuild lifted)
**Supersedes contract part of:** FIX-1 G7 (gate stays, input shifts from LLM word_range → derived-from-cue)
**Root cause:** LLM cannot reliably count its own words. Empirically validated 2x:
- job_19 (qwen3-32b): over-index `word_range[52,64]` for 60-word voiceover
- job_20 (qwen3-30b-a3b-instruct): under-index union `[0,94]` for 101 words (6-word tail uncovered)

Industry pattern (HeyGen HyperFrames research): TTS word timestamps = source of truth; LLM identifies semantic boundaries, code computes indices. We already have ElevenLabs `/with-timestamps` (v2.0 audio-first).

---

## 1. Contract change

**Before (LLM emits word_range — adversarial):**
```json
{"beat_id":1, "section":"hook", "word_range":[0,15], "overlay_text":"...", "caption_keywords":[...]}
```

**After (LLM emits start_cue — semantic, code derives word_range):**
```json
{"beat_id":1, "section":"hook", "start_cue":"<3-5 first words of beat>", "overlay_text":"...", "caption_keywords":[...]}
```

- `start_cue` REQUIRED: 3-5 word phrase marking beat start, MUST appear (fuzzy) in `voiceover_text`.
- `word_range` REMOVED from LLM output schema. Backfilled by code in `_normalize_narrative_structure` (downstream consumers unchanged).

## 2. New helper — `clipper_agency/core/beat_anchor.py`

```python
def derive_word_ranges(voiceover_text: str, cues: list[str]) -> DeriveResult:
    """Tokenize voiceover; fuzzy-find each cue; derive [start,end] per beat.
    beat[0].start=0; beat[i].start=cue[i] pos; beat[i].end=beat[i+1].start-1; last.end=len-1.
    Returns word_ranges OR failure (cue_not_found / cue_out_of_order)."""
```

- Tokenizer: lowercase + strip Indonesian punctuation, keep enclitics (nya/kah/lah) as tokens.
- Fuzzy match: token-set overlap (Jaccard ≥ 0.6) OR normalized subsequence against voiceover token windows. Pick best-scoring position. Deterministic (no randomness).
- Fail-loud if cue not found OR cues out of order.

## 3. G7 gate change — `GateNarrativeCoverage`

Validate DERIVED word_range (from cues via helper), not LLM-emitted:
1. Every `start_cue` found in voiceover (fuzzy).
2. Cues in order (position monotonic).
3. Derived union == [0, len-1] (automatic given 1+2 + last.end=len-1).
- Fail reasons: `cue_not_found`, `cue_out_of_order` → route Scriptwriter regen (FIX-5 router already reason-based).
- KEEP existing FIX-1 in-place repair for uncovered tail <5% as defense-in-depth (rarely needed now).

## 4. Scriptwriter changes — `agents/scriptwriter.py`

- Prompt: replace "emit word_range covering [0,N-1]" → "emit start_cue = 3-5 first words of each beat, copied verbatim from voiceover_text".
- `_validate_output`: require `start_cue` (3-5 tokens), stop validating `word_range`.
- `_normalize_narrative_structure`: backfill `word_range` via `derive_word_ranges(voiceover, cues)` so downstream still sees the field.

## 5. Backward compat (zero downstream change)

Downstream consumers (`build_canonical_timeline`, Visual Director, Composer, Reviewer) read `word_range`. Populated by normalize step from derived values. No downstream code change.

## 6. Cache-key parity (FIX-3 lesson)

`start_cue` is part of narrative_structure → changes content hash → Scriptwriter cache invalidates (acceptable, contract changed). `derive_word_ranges` MUST be deterministic (same input → same output) so VD/qualification cache-key (which hashes `word_range` per FIX-3 §8) stays stable post-derivation.

## 7. Tests (TDD)

1. `derive_word_ranges` happy path: 101-word voiceover + 5 cues → 5 contiguous ranges covering [0,100].
2. Cue parafrase tolerance: cue "Publik ramai bahas" vs voiceover "publik ramai membahas" → matched.
3. Cue not found → `cue_not_found`.
4. Cues out of order → `cue_out_of_order`.
5. Single beat → [0, len-1].
6. job_20 fixture (101 words, old mis-index) → derived correct, G7 passes.
7. Integration: Scriptwriter emits start_cue → normalize derives word_range → G7 passes → `build_canonical_timeline` produces correct beat durations.

## 8. Blast-radius (memory: run-4th-blast-radius-lane)

Gate contract change MUST cover every path that reads narrative_structure word_range:
- normal `_stage_content` (Scriptwriter → G7 → Voice Producer)
- retry `_retry_downstream_stages`
- repair `_rerun_upstream_cascade` (FIX-5 router — reason `cue_not_found` routes Scriptwriter)
- resume `job-resume`
- cache-replay (derived word_range must be deterministic for cache parity)

Blast-radius reviewer enumerates every consumer of `word_range` + every caller of Scriptwriter normalize; asserts derivation fires on each. Report bypass.

## 9. Spec docs

- CHANGELOG `[Unreleased]` FIX-8 entry.
- SRS FR-74 (G7 now cue-derived).
- PRD PR-38 update.
- technical_design §5.4 (contract change).
- requirements_traceability.

## 10. Ship

Branch `phase/27-fix8-word-range-cue-anchor` → workflow-first (Design done → TDD impl → 5-lane ECC review → codex fix-loop) → Sonar 0-new → Codex 👍 → `--merge`. Then retry job_21 (full validation downstream FIX-2/3/4/6).
