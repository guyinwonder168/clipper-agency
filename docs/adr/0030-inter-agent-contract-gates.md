# ADR 0030 — Inter-Agent Contract Gates for Narration–Visual Alignment (job_18)

**Status:** Proposed (root-cause investigation complete 2026-06-29; implementation pending — see `docs/plans/2026-06-29-inter-agent-contract-gates-tiktok-quality.md`)
**Date:** 2026-06-29
**Supersedes / amends:** Partially amends ADR 0026's "enforce contracts, do NOT rebuild" default — the product owner has explicitly lifted the no-rebuild / MVP-only constraint for output-quality work. The 7-agent topology itself stays (research-validated); what changes is that **inter-agent data contracts become hard deterministic gates instead of trusted `status=="completed"` handshakes.**
**Related:** ADR 0020 (canonical timeline), ADR 0021 (audio-first), ADR 0023 (quality gates + repair routing), ADR 0026 (contract enforcement over rebuild), ADR 0027 (asset-qualification inspection delegation), `docs/plans/2026-06-21-av-drift-and-output-quality.md`

---

## Context

**job_18** was the first end-to-end-completed ElevenLabs job (the P1/P2/VD/composer fixes delivered). The voiceover was correct (76 words, 35.3 s, 76 word-level timestamps, `provider=elevenlabs`). But the produced video was not post-worthy: ~60 % of its frames read as static (one image held ~8 s, then a near-black "KOMEN DI BAWAH!" card held ~24 s), the visuals mismatched the narration (a Jennifer Coppen image shown during the Sarwendah beat), and the final ~2.6 s of audio ("…like dan share!") was cut.

A read-only trace (the PR-13 `scripts/diagnose_av_drift.py` harness + frame extraction + AI-vision verification + codegraph audit) traced a **single load-bearing defect cascading through five blind-trust layers**:

1. **Scriptwriter** (`qwen/qwen3-32b`) emitted `narrative_structure` whose `word_range` indices covered only words **0–23 of 76**. `_normalize_narrative_structure` (`agents/scriptwriter.py`) only backfills missing fields; `_validate_output` checks word-count + emoji, **never coverage**. So 52 words / ~23 s of narration (5 distinct topics) had **no beat**.
2. **`build_canonical_timeline`** (`core/beat_timeline.py`) silently stretched the last beat from 10.12 s to 35.3 s — a 25.17 s "mega-beat" — via its "cover trailing audio" heuristic, with no warning and no max-beat guard. The timeline builder was a **silent failure amplifier**, not a validator.
3. **Visual Director** had to plan **one scene** for the 25 s beat; because "accept" is a numeric threshold (≥ 0.60) with no entity binding to the beat's named subject, it selected a **wrong-artist image** (Jennifer Coppen for the Sarwendah beat). `asset_qualification` shares the same scoring code and certified it.
4. **Composer** rendered the broken timeline faithfully; xfade transitions shrank the visual track to 32.7 s < 35.3 s audio, and `-shortest` **silently cut the last 2.6 s** of the CTA. The post-hoc duration guard saw near-equal durations because `-shortest` had already equalized them.
5. **Reviewer**'s `_check_av_sync` is total-duration-only (one scalar) — structurally defeated by `-shortest` equalization — so it **passed**; blackdetect misfired on the legitimately dark closing card; repair was routed to **Visual Director** (wrong target — the defect was upstream in Scriptwriter + composition); `_rerun_upstream_cascade` re-built the timeline from the **same broken `narrative_structure`** every cycle; the job "completed" with garbage output.

The root cause is **NOT wrong agent topology**. A deep-research workflow (study of reference OSS pipelines `MoneyPrinterTurbo-Extended` + `claude-auto-tok`, plus web research on production short-form tools — Opus Clip, Pictory, ShortGPT, Submagic, Descript) confirmed each of the 7 agents did its job faithfully given the data it received. The defect is that **no agent validated the inter-agent data contract** — they trusted `status=="completed"`. The product owner has lifted the MVP / no-rebuild constraint (ADR 0026) specifically to fix output quality, so adding these gates is now in scope.

## Decision

**KEEP the 7-agent chain and the audio-first beat-driven architecture. ADD deterministic contract gates at every inter-agent boundary, fix the repair router to target the root agent, and remove the `-shortest` audio-cut.** Do NOT restructure, merge, or remove agents.

The gates (full spec in the implementation plan; new SRS FR-74..FR-80, PRD PR-38..PR-44, Design §19/§20):

| Gate / lever | Location | Kills (job_18 link) |
|---|---|---|
| **G7 GateNarrativeCoverage** — assert `word_range` union == `[0, word_count-1]`, contiguous, in-bounds; in-place repair for tail < 5 % else force Scriptwriter regen | `orchestrator/gates.py` + `engine._stage_content` (after Scriptwriter, before Voice Producer) | Link 1 (source) |
| **Timeline UNCOVERED_TAIL detection + MAX-beat cap (12 s)** — stop `build_canonical_timeline` manufacturing mega-beats | `core/beat_timeline.py` | Link 1.5 (amplifier) |
| **Audio-as-master** — replace `-shortest` with `-t voiceover_duration`; pre-render pad visual ≥ audio; G9.5 visual-coverage gate; G10 audio-stream re-probe (`AUDIO_NOT_TRUNCATED`) | `agents/composer.py` + `orchestrator/engine.py` + `gates.py` | Link 4 (audio cut) |
| **Entity-binding rejection** at the shared qualification/VD chokepoint (`candidate_semantic_ranker.apply_rejection_rules`) + VLM inspector `subject_name` + threshold 0.8→0.6 | `core/candidate_semantic_ranker.py`, `core/semantic_visual_review.py`, `agents/visual_director.py`, `core/asset_qualification.py` | Link 2 (wrong artist) |
| **Reviewer per-scene entity-vs-beat + frozen-frame + audio-not-truncated** | `agents/reviewer.py`, `core/reviewer_context.py` | Link 5 (blind pass) |
| **Repair router root-cause routing** — route by failure REASON; force `narrative_structure` regen on coverage re-fail; bounded `MAX_REPAIR_CYCLES` + terminal fail (never "complete" garbage) | `orchestrator/engine.py` (`_rerun_upstream_cascade`) | Link 5 (repair loop) |
| **Engagement gates (post-worthy bar)** — visual-change-density, hook-on-beat-0, duration-band 21–42 s, monotony guard, max-dwell 4 s | `agents/reviewer.py`, `orchestrator/gates.py` | All 5 "AI low-effort tells" |

## Alternatives Considered

1. **Restructure to MoneyPrinterTurbo's opaque-string model** (LLM emits a single plaintext script, never per-segment `word_range`; segmentation is deterministic post-TTS regex; coverage enforced by a visual duration-loop against the single `audio_duration` scalar). **REJECTED.** It would discard clipper-agency's richer beat-driven contract — which the research shows is *ahead* of per-sentence tools and is *not* the job_18 problem (segmentation was fine; **coverage + relevance + audio-truncation** were). We adopt MoneyPrinterTurbo's `audio_duration`-as-authoritative-timing-scalar + "use anyway, never freeze" loop-fill *policy* (FIX-2) without adopting its opaque-string topology.

2. **Trust the LLM and rely on the Reviewer.** **REJECTED.** The Reviewer's AV-sync check is total-duration-only and structurally blind to intra-timeline drift / frozen frames / wrong entities; it passed job_18. Detection must be deterministic and placed at the boundary where the defect originates, not at the end.

3. **Multimodal "watch the rendered video" Reviewer** (claude-auto-tok style). **DEFERRED.** Strongest defense against frozen-card / wrong-face but adds cost + latency + a vision-model dependency. The deterministic gates above are the primary line; a multimodal second pass is a Phase 27+ optional upgrade, not a replacement.

4. **CLIP image-text cosine similarity for final candidate relevance ranking.** **DEFERRED (Phase 27+).** The documented state-of-the-art fix for the wrong-artist class beyond keyword overlap. Complements FIX-3's name-overlap gate but is not load-bearing for job_18 (name-overlap is the now-fix).

## Consequences

**Positive**
- The job_18 class is killed at the source: a partial `word_range` never leaves Scriptwriter; audio is never truncated; wrong-entity assets are rejected; the Reviewer can see frozen/wrong/truncated output; repair reaches the root agent instead of looping on the wrong one.
- The 7-agent chain's brittleness ("one issue → all agents dumb") is addressed structurally: every inter-agent boundary becomes a parse-and-validate gate that fails hard with a reason-keyed repair target.
- The output target is elevated from "technically correct" to **TikTok-post-worthy** (engagement gates: ~4 s interrupts correlate with ~58 % vs 41 % retention; the bar requires zero of the five "AI low effort tells").

**Negative / risks**
- More gates ⇒ more repair cycles possible ⇒ higher VLM cost / latency. Mitigation: monitor qualified-candidate reject rate + the SLICE-12 `M<N` recovery gate; keep engagement gates as WARN+repair, not pipeline-death.
- Entity name-match is brittle for aliases / Indonesian transliteration (Sarwendah vs Sarwenda). Mitigation: fuzzy/normalized match; future CLIP upgrade (Phase 27+).
- FIX-1 in-place repair risks manufacturing beat metadata for a tiny tail; mitigation: auto-extend only when tail < 5 % of words, else force Scriptwriter regen.
- `MAX_REPAIR_CYCLES` must have a terminal fail-state — a job that cannot satisfy the coverage gate after N regens must **fail**, not "complete" garbage.

## Compliance

This ADR amends ADR 0026 for output-quality work only: the product owner has authorized deterministic **new gates** (GateNarrativeCoverage, G9.5 visual-coverage, engagement gates) and **new rejection rules** (entity binding) — items ADR 0026 would otherwise have classed as "rebuild." It does **not** add a new agent, change the state machine, or alter the audio-first beat-driven topology. ADR 0026 still governs non-quality contract work.
