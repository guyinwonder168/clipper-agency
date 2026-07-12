# Implementation Plan — Inter-Agent Contract Gates for TikTok-Worthy Output (job_18)

**Status:** DRAFT — investigation complete, implementation pending (resume target)
**Date:** 2026-06-29
**Governing ADR:** [0030 — Inter-Agent Contract Gates](../adr/0030-inter-agent-contract-gates.md)
**Amends (for quality work only):** ADR 0026 (no-rebuild) — product owner has lifted the MVP/no-rebuild constraint for output-quality fixes
**Related:** `docs/plans/2026-06-21-av-drift-and-output-quality.md` (the diagnosis plan this supersedes for the coverage/relevance/audio class), ADRs 0020/0021/0023/0027
**Goal:** produced videos are **worthy to post on TikTok** — zero of the five "AI low-effort tells" (frozen static image, mismatched B-roll, audio cutoff, monotony, bad pacing).

---

## 0. Resume Here — What Is Already Done

- ✅ **Root-cause investigation COMPLETE.** `scripts/diagnose_av_drift.py data/outputs/job_18` ran; full trace in this session. Evidence persisted: `data/outputs/job_18/visual_coverage.json`, `data/assets/cache/job_18/agents/composer/{ffmpeg_command.txt,ffmpeg_stderr.log,output.json}`, `data/assets/cache/job_18/agents/scriptwriter/narrative_structure.json`, `data/assets/cache/job_18/agents/voice_producer/output.json`. Frame contact sheet + AI-vision analysis performed.
- ✅ **Deep-research workflow COMPLETE** (run `wuoi4pvsl` output: `/tmp/claude-1001/.../tasks/wuoi4pvsl.output` — transient; the synthesis is captured in ADR 0030 + this plan).
- ✅ **Docs updated** (ADR 0030, CHANGELOG, README, SRS 3.4, PRD 3.4, technical_design 5.4, requirements_traceability 4.4 — this plan).
- ❌ **NO FIX CODE WRITTEN YET.** Working tree clean on `master` (`e6d5c80`). First code PR is FIX-1 below.

## 1. The Root Cause (one sentence)

The Scriptwriter LLM emitted `word_range` indices covering only words **0–23 of 76**; **nothing validated coverage**, so 52 words / ~23 s of narration collapsed into one 25-second closing scene, and five blind-trust layers downstream rendered that garbage faithfully — the Reviewer's total-duration-only gate passed it, repair re-built from the same broken structure, and the job "completed" unpostable.

### job_18 evidence (ground truth)
- Scriptwriter `voiceover_text` = 76 words, 35.3 s voiceover (correct, ElevenLabs P1 fix works — 76 timestamps).
- `narrative_structure` = 6 beats, `word_range` = `[0,2],[3,8],[9,12],[13,15],[16,19],[20,23]` → cover **words 0–23 only**.
- `build_canonical_timeline` extended beat 6 (start 10.12 s) → 35.3 s = **25.17 s mega-scene**.
- Visual Director: beat 2 (Sarwendah) got a **Jennifer Coppen** image (wrong artist); beat 6 (CTA) got a near-black card held 25 s.
- Composer: visual track 32.7 s < audio 35.3 s; `-shortest` cut last 2.6 s ("…like dan share").
- AI-vision contact sheet: t=0 YouTube clip; t=4/8/12 same Jennifer Coppen image; t=16/20/24/28 near-black "KOMEN DI BAWAH!" card.

## 2. The Fix Plan (ranked, dependency order)

Each fix = its own branch `phase/27-fixN-<slug>` + PR + SonarCloud (zero new issues, verify via `issues/search`) + Codex (👍 = pass) + `--merge` (never squash) + CHANGELOG + spec-doc entry. **Use the workflow-first pattern** (Workflow tool: impl + read-only audit + ECC python-reviewer) per fix — see CLAUDE.md "Workflow-first fixes."

| # | Title | Effort | Kills | Depends |
|---|-------|--------|-------|---------|
| **FIX-1** | G7 GateNarrativeCoverage + `_validate_narrative_coverage` | M | source (link 1) | — |
| FIX-6 | Timeline UNCOVERED_TAIL detection + MAX-beat cap (12 s) | S | amplifier (link 1.5) | FIX-1 |
| FIX-2 | Audio-as-master: drop `-shortest` → `-t voiceover_duration` + pre-render pad + G9.5 visual-coverage gate + G10 `AUDIO_NOT_TRUNCATED` re-probe | M | audio cut (link 4) | FIX-1 |
| FIX-3 | Entity-binding rejection at `candidate_semantic_ranker` chokepoint + VLM `subject_name` + threshold 0.8→0.6 + MAX-scene cap | M | wrong artist (link 2) | FIX-1 |
| FIX-5 | Repair router root-cause routing + force narrative regen + bounded `MAX_REPAIR_CYCLES` + terminal fail | M | repair loop (link 5) | FIX-1, FIX-4 |
| FIX-4 | Reviewer per-scene entity-vs-beat + frozen-frame/max-dwell + audio-not-truncated | L | blind pass (link 5) | FIX-2, FIX-3 |
| FIX-7 | Engagement gates: visual-change-density, hook-on-beat-0, duration-band 21–42 s, monotony guard | L | 5 AI-tells (post-worthy) | FIX-4 |

**Ship order:** FIX-1 → FIX-6 → FIX-2 → FIX-3 → FIX-5 → FIX-4 → FIX-7. (FIX-1/2/3/6 = correctness; FIX-4/5 = detection + repair; FIX-7 = post-worthy.)

## 3. Per-Fix Acceptance Gates

### FIX-1 — G7 GateNarrativeCoverage (THE load-bearing fix)
**Files:** `clipper_agency/orchestrator/gates.py`, `clipper_agency/orchestrator/engine.py` (`_stage_content`, after `_run_content_scriptwriter`, before Voice Producer), `clipper_agency/agents/scriptwriter.py` (`_validate_output` calls new `_validate_narrative_coverage`).
**Behavior:** tokenize `voiceover_text`; assert (a) every `word_range` in-bounds `[0, len-1]`; (b) beats sorted + contiguous (`beat[i].end+1 == beat[i+1].start`); (c) union of `word_range` == `[0, len-1]` within tolerance (last beat `end >= len-1 - floor(len*0.05)`). On failure: **in-place repair** (extend last beat / insert closing beat) only when uncovered tail < 5 % of words; else hard-fail routing repair to **Scriptwriter** (NOT Visual Director) with explicit "regenerate beats covering ALL words."
**Acceptance test:** a frozen job_18-style fixture (24/76 coverage) → gate fails with `reason=narrative_not_covered` → repair routes to scriptwriter. A full-coverage fixture passes. Offline suite green.
**Traceability:** SRS FR-74, PRD PR-38.

### FIX-6 — Timeline UNCOVERED_TAIL + MAX-beat cap
**Files:** `clipper_agency/core/beat_timeline.py`.
**Behavior:** `build_canonical_timeline` detects uncovered gaps (final timestamp end − last beat intended end > `max(2.0 s, one nominal beat span)`) → emit structured `UNCOVERED_TAIL` signal the orchestrator can gate on. Add `MAX_BEAT_DURATION_SEC` cap (12 s); a 25 s single entry is rejected as non-physical instead of silently manufactured. The "cover trailing audio" heuristic becomes a logged, gated extension.
**Acceptance test:** a 25 s trailing tail fixture → `UNCOVERED_TAIL` raised + beat rejected. Existing timeline tests green.
**Traceability:** SRS FR-79, PRD PR-42.

### FIX-2 — Audio-as-master (MoneyPrinterTurbo policy)
**Files:** `clipper_agency/agents/composer.py` (replace `-shortest` ~L1128 with `-t voiceover_duration`; pre-render pad visual to `voiceover_duration_sec`), `clipper_agency/orchestrator/engine.py` (`_stage_composition`, add G9.5), `clipper_agency/orchestrator/gates.py`.
**Behavior:** before FFmpeg, compute `sum(scene.target_duration)`; if `< voiceover_duration_sec - tol`, pad (loop/extend last still / cycle earlier clips) — **prefer re-running VD to discover more assets** (claude-auto-tok per-scene fallback) over blindly looping; loop is the last-resort "use anyway, never freeze" backstop. New **G9.5 GateVisualAudioCoverage** between VD and Composer: assert `sum(planned scene durations) >= voiceover_duration_sec`, route to VD on fail. Strengthen **G10**: independently re-probe the final video's audio-stream duration; assert `>= voiceover_duration_sec - 0.5 s` (`AUDIO_NOT_TRUNCATED`, immune to `-shortest` equalization).
**Acceptance test:** a job whose visual track would sum to 32.7 s against 35.3 s audio → padded to 35.3 s OR G9.5 routes repair; final video audio stream ≥ 35.3 − 0.5 s. The "…like dan share" CTA is never cut.
**Traceability:** SRS FR-75, PRD PR-39.

### FIX-3 — Entity-binding at the qualification/VD chokepoint — ✅ COMPLETE
> **Status (2026-07-12): SHIPPED** on `phase/27-fix3-entity-binding`. `WRONG_ENTITY` rule (first, most-specific) + `subject_name` VLM field end-to-end + pure helpers `derive_expected_entities`/`entity_overlap` (exact/substring≥4/Jaccard≥0.75) + Slice-3 missing-subject⇒revise + R-1 stale-cache guard (re-inspect on absent `subject_name`), decorated on BOTH scored-dict builders so cache-key parity is preserved. **DEFERRED → FIX-3.5:** the `misleading_risk` 0.8→0.6 threshold (char-pinning tests lock current behavior; Slices 1+2+3 close job_18 deterministically without it; the change needs a clamp, double-penalizes with WRONG_ENTITY, fleet-wide false-positive risk). The `MAX_BEAT_DURATION_SEC`/max-scene cap already shipped in FIX-6. Full detail in `CHANGELOG.md` `[Unreleased]` FIX-3 entry. Gate: 2353 passed / 22 deselected / cov 93% / ruff 0 new on FIX-3 lines.

**Files:** `clipper_agency/core/candidate_semantic_ranker.py` (`apply_rejection_rules` gains a `WRONG_ENTITY` rule — reject when inspection `subject_name` does not overlap the beat's `spoken_point` + job `main_entities`), `clipper_agency/core/semantic_visual_review.py` (lower `misleading_risk` `person_match` threshold 0.8 → 0.6), `clipper_agency/agents/visual_director.py` (`_run_multimodal_inspection` returns `subject_name`; missing → `revise`, not accept), `clipper_agency/core/asset_qualification.py` (shares the rule by cache-key parity), `clipper_agency/core/beat_timeline.py` / VD scene planning (`MAX_BEAT_DURATION_SEC` / max-scene cap → split into N scenes, never one card).
**Acceptance test:** a fixture where the only candidate depicts the wrong entity → rejected (`reason=WRONG_ENTITY`) → fallback / recovery. Fuzzy match tolerates aliases (Sarwendah/Sarwenda). Cache-key parity holds (no double-VLM). Existing qualification tests green.
**Traceability:** SRS FR-76, PRD PR-40.

### FIX-5 — Repair router root-cause routing
**Files:** `clipper_agency/orchestrator/engine.py` (`_rerun_upstream_cascade`).
**Behavior:** route the repair to the ROOT agent via the failure REASON — Scriptwriter for `narrative_not_covered` / coverage gaps; Visual Director for entity / split / dwell failures; Composer for audio-truncation / `-shortest` failures. When a coverage gate would re-fail, **force `narrative_structure` regeneration** (re-run Scriptwriter with "cover ALL words") instead of rebuilding `beat_timeline` from the known-broken structure. Add `MAX_REPAIR_CYCLES` bound + terminal fail-state (do NOT "complete" garbage). Add voiceover-text-diff skip optimization (skip Voice Producer when a revision touches non-voiceover fields only).
**Acceptance test:** a job_18-style coverage failure routed to Scriptwriter, not VD; after N failed regens → job `FAILED` (not `COMPLETED` garbage).
**Traceability:** SRS FR-78, PRD PR-43.

### FIX-4 — Reviewer per-scene detection
**Files:** `clipper_agency/agents/reviewer.py` (`_check_av_sync` extended beyond the total-duration scalar), `clipper_agency/core/reviewer_context.py`.
**Behavior:** (1) `AUDIO_NOT_TRUNCATED` — re-probe final video audio stream ≥ `voiceover_duration_sec - 0.5 s`. (2) Per-scene `ENTITY-VS-BIND` — each `rendered_scene_manifest` entry's `selected_asset subject_name` must match the mapped beat's `spoken_point` / `main_entities` (`map_scenes_to_beats`); hard-fail `WRONG_ENTITY` on mismatch. (3) `MAX-DWELL` / frozen-frame — flag any static card held > 4 s without a qualifying change-event (treatment motion, caption reveal). (4) Flag scenes matched to a synthetically-extended / uncovered-tail beat.
**Acceptance test:** a frozen-card fixture → flagged; a wrong-entity-in-right-window fixture → flagged; a clean fixture passes. Existing reviewer tests green.
**Traceability:** SRS FR-77, PRD PR-41.

### FIX-7 — Engagement gates (post-worthy bar)
**Files:** `clipper_agency/agents/reviewer.py`, `clipper_agency/orchestrator/gates.py`, `clipper_agency/core/reviewer_context.py`.
**Behavior:** programmatic_checks beyond correctness: (1) VISUAL-CHANGE-DENSITY — min change-events per 1.5–4 s (~8–15 for a 30 s video); a 1–2-image plan for 25 s+ fails. (2) HOOK — beat 0 must be a real image/motion, not a title/text card; first visual change by 1.5 s. (3) DURATION-BAND — final video 21–42 s (infotainment sweet spot). (4) MONOTONY — no same content-hash image across consecutive beats without treatment variation; beat-aligned caption reveals count as change-events.
**Acceptance test:** a job_18-shape plan (1 image for 25 s) → fails visual-change-density + max-dwell. **Keep as WARN+repair, not pipeline-death** (differentiate hook pacing "breathe" from body pacing "aggressive interrupts").
**Traceability:** SRS FR-80, PRD PR-44.

## 4. Per-Fix Workflow-First Execution (CLAUDE.md)

For each fix:
1. `git checkout -b phase/27-fixN-<slug>` (never push `master`).
2. TDD: failing test first → impl → green.
3. **Workflow tool** (ultracode), Design → Implement (TDD) → Review (4 parallel reviewers):
   - `ecc:python-reviewer` — gate/validator code quality (immutability, off-by-one, naming, purity).
   - `ecc:silent-failure-hunter` — silent failures / swallowed errors / unsafe fallbacks inside the gate.
   - contract/acceptance auditor — the frozen job_18-shape fixture hard-fails; the happy fixture passes; re-runs the tests itself to confirm GREEN is real.
   - **blast-radius / wiring-completeness reviewer** — *"This fix adds a contract at the A→B boundary. Use CodeGraph to enumerate EVERY path that produces A's output and feeds B — normal `_stage_content` + retry `_retry_downstream_stages` + repair `_rerun_upstream_cascade` + cache-replay. For each, assert the gate fires. Report any bypass."* (Learned from FIX-1 Codex P1: a gate on the happy path only is a half-fix; the first three reviewers review the gate in isolation and cannot see this — see `docs/repetitive-failure-patterns.md` #11.)
   Native queueing handles over-capacity.
4. Offline gate: `.venv/bin/python3 -m pytest -m "not external and not integration" -q` (all pass) + `--cov=clipper_agency --cov-report=term-missing` (≥93%).
5. `ruff` clean; **CHANGELOG.md** entry under `[Unreleased]`; spec-doc entries (SRS/PRD/design/traceability already have the FR/PR placeholders — fill in the "Implemented" status on merge).
6. `git push -u origin phase/27-fixN-<slug>` → `gh pr create --base master`.
7. Wait for SonarCloud ✅ **+ zero new issues** (verify `sonarcloud.io/api/issues/search?componentKeys=guyinwonder168_clipper-agency&pullRequest=N&statuses=OPEN,CONFIRMED`); wait for Codex (👍 reaction on the PR description = pass — `reviews[]` empty by design).
8. `gh pr merge <n> --merge` (never squash) → delete branch → `git pull origin master`.

## 5. Open Risks (from the research workflow)

- FIX-1 in-place repair must not invent low-quality beat metadata → auto-extend only for tail < 5 %.
- FIX-2 padding trades audio-correctness for visual monotony → prefer re-running VD over looping.
- FIX-3 entity name-match brittle for aliases/transliteration → fuzzy match + future CLIP (Phase 27+).
- FIX-5 force-regen could loop if qwen3-32b keeps emitting partial coverage → bounded `MAX_REPAIR_CYCLES` + terminal fail.
- FIX-7 thresholds are creator-economy guidance, not hard TikTok-API data → WARN+repair, not death; differentiate hook vs body pacing.
- Lowering thresholds + WRONG_ENTITY may raise VLM cost / false-positives → monitor reject rate + SLICE-12 `M<N`.

## 6. Definition of Done (the whole effort)

- A fresh job on `master` (post FIX-1..7) on a gossip topic produces a video where: 100 % of voiceover words map to a beat; audio is never truncated; no static card held > 4 s; every beat's asset depicts the beat's subject; final video 21–42 s with ≥8 visual change-events.
- Re-run `scripts/diagnose_av_drift.py` on that job: `offset_ms_achieved` per beat < 500 ms; no `UNCOVERED_TAIL`; `AUDIO_NOT_TRUNCATED` holds.
- The video is post-worthy by human judgment (user sign-off).
- v2.4.0 release gate (PR 12) can then proceed (this work is the quality precondition).

## 7. Fast Resume Commands

```bash
cd "/media/eddy/hdd/Project/clipper agency"
git checkout master && git pull origin master          # should be at the FIX-1 branch point
# Re-read this plan + ADR 0030:
#   docs/plans/2026-06-29-inter-agent-contract-gates-tiktok-quality.md
#   docs/adr/0030-inter-agent-contract-gates.md
# Re-run the harness on the existing job_18 to re-confirm the baseline:
.venv/bin/python3 scripts/diagnose_av_drift.py data/outputs/job_18
# Start FIX-1:
git checkout -b phase/27-fix1-narrative-coverage-gate
```
