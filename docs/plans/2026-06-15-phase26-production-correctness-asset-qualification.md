# Phase 26 — Production Correctness & Asset Qualification (v2.4.0 Roadmap)

> **For Claude / Sub-agents:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and follow strict TDD for every task.

**Goal:** Fix four confirmed production-correctness defects and enforce existing architectural contracts (ADR 0020 canonical timeline, ADR 0023 repair routing) so that built-but-unenforced infrastructure actually governs pipeline behavior. Cut v2.4.0 as the release where these contracts are realized.

**Filename:** `2026-06-15-phase26-production-correctness-asset-qualification.md`
**Date:** 2026-06-15
**Target baseline:** `master` after PR #49 merge (v2.3.0)
**Phase:** 26
**ADR:** [0026 — v2.4.0 Contract Enforcement Over Rebuild](../adr/0026-v2.4.0-contract-enforcement-over-rebuild.md)
**Related ADRs:** [0020 (canonical timeline)](../adr/0020-use-canonical-timeline-contract.md), [0023 (repair routing)](../adr/0023-job4-quality-gates-and-repair-routing.md)
**Version strategy:** v2.3.0 throughout. Version bump to v2.4.0 happens **only after PR 8 (P3) passes** — no intermediate bumps.

---

## 0. Discovery Context

A code audit of `master` (v2.3.0) after PR #48 + PR #49, cross-referenced with an external plan review (ChatGPT), identified four confirmed defects. Each was verified against the actual codebase with specific file/line references before this plan was written.

### Already implemented — DO NOT rebuild

Per AGENTS.md (phases 21–24) and grep confirmation, the following exist and have tests:

- Multi-provider Segment Producer discovery (ScrapeCreators, Firecrawl, yt-dlp, Tavily, Brave)
- Source-quality tiers, OCR, face detection, cleanliness inspection
- Multimodal candidate inspection (`MultimodalInspectionClient`)
- Candidate semantic ranker + rejection rules
- Composer black/freeze/empty diagnostics
- Reviewer deterministic gates (visual_coverage, text_collision, safe_area, package_consistency)
- Bounded repair-loop infrastructure (`repair_router` + `repair_metrics`)
- Lifecycle statuses (quality, publication, repair)
- LLM tracing for all 7 agents

### Four confirmed defects

| # | Defect | Evidence | Severity |
|---|--------|----------|----------|
| 1 | Rejected candidates leave original action in plan | `visual_director.py:997` — `_apply_best_candidate` only modifies on `accept` | P0 — wrong asset rendered |
| 2 | Two competing beat-duration derivations | VD `_calculate_beat_durations` (L263) vs Composer `_compute_beat_durations` (L1255) | P1 — timeline drift |
| 3 | `fade_to_black` fades out at `st=0.0` not clip end | `treatment_filters.py:19` default `0.0`; composer.py:1016,1398 omit arg | P0 — broken transition |
| 4 | Deterministic gate failures can't reach repair loop | `engine.py:264` — repair only enters if `review_output["repair_plan"]` exists; gates don't auto-generate patches | P1 — manual review bypass |

Defect 5 (Segment Producer precision) is plausible but not exhaustively verified; it is staged as P2 improvement work.

---

## 1. Scope

### In Scope

- **Freeze Job #8 as golden regression fixture** (Batch 0 — prerequisite, no production changes)
- Fix the four confirmed defects (PR 1)
- Enforce ADR 0020 canonical timeline (PR 2)
- Make deterministic failures auto-generate repair patches (PR 3)
- Improve Segment Producer per-beat precision (PR 4)
- Introduce pre-VD asset qualification boundary (PR 5)
- Source transcript + clip-window selector (PR 6)
- Visual Director multi-shot planning (PR 7)
- Release gate + golden-set validation (PR 8)
- Version bump to v2.4.0 (final step, after PR 8)

### Out of Scope

- New agents (architecture preserved — 7 agents, 10 gates)
- New core inspection modules (all inspection modules already built)
- GPU rendering, new TTS providers, new LLM providers
- Social media API publishing (out of MVP scope)
- Rebuilding existing infrastructure (the whole point is to NOT rebuild)

---

## 2. Priority Ordering & Version Strategy

> **Numbering note:** "PR 1"–"PR 8" below are **logical phase-internal step numbers**, not GitHub PR numbers. The actual GitHub PRs are sequential repo-wide (Batch 0 = #50, Step 1 ≈ #51, Step 2 ≈ #52, …). Branch names use the step number; the GitHub PR title/body will reference the real `#NN`.

| Priority | Step | Title | Branch | Risk | Status | Version after merge |
|----------|------|-------|--------|------|-------|---------------------|
| **P0** | Batch 0 | Freeze Job #8 golden regression fixture | `phase/26-batch0-job8-fixture` | Low | ✅ MERGED (#50, f16e86e) | v2.3.0 |
| **P0** | 1 | Job #8 production correctness hotfix | `phase/26-pr1-hotfix` | Low | ✅ MERGED (#51, b0e3deb) | v2.3.0 |
| **P1** | 2 | Canonical beat timeline enforcement | `phase/26-pr2-canonical-timeline` | Medium | ✅ IMPLEMENTED (PR #52) | v2.3.0 |
| **P1** | 3 | Deterministic failure-to-repair integration | `phase/26-pr3-repair-integration` | Medium | ⬜ Pending | v2.3.0 |
| **P2** | 4 | Segment Producer precision upgrade | `phase/26-pr4-sp-precision` | Medium | ⬜ Pending | v2.3.0 |
| **P2** | 5 | Pre-VD asset qualification boundary | `phase/26-pr5-pre-vd-qualification` | **High** | ⬜ Pending | v2.3.0 |
| **P2** | 6 | Source transcript + clip-window selector | `phase/26-pr6-clip-window` | Medium | ⬜ Pending | v2.3.0 |
| **P2** | 7 | Visual Director multi-shot planning | `phase/26-pr7-multishot-vd` | Medium | ⬜ Pending | v2.3.0 |
| **P3** | 8 | Release gate + golden-set validation | `phase/26-pr8-release-gate` | Low | ⬜ Pending | **v2.4.0** (bump here) |

**Version bump rule:** v2.3.0 is frozen across steps 1–7. Step 8 is the release PR that bumps to v2.4.0 in the same commit that passes the golden-set validation. No intermediate version bumps.

---

## 3. PR Detail

### Batch 0 — Freeze Job #8 Golden Regression Fixture (P0, prerequisite) ✅ MERGED (PR #50)

**Branch:** `phase/26-batch0-job8-fixture` — merged commit `f16e86e`
**Scope:** Capture Job #8's confirmed failure as a characterization test. **No production code changes.** This is a prerequisite for PR 1 — it pins the broken behavior before any fix lands, so every subsequent fix is verifiable.

**Source artifacts (exist on disk at `data/assets/cache/job_8/` and `data/outputs/job_8/`):**

| Artifact | Source path | What it proves |
|----------|-------------|----------------|
| `vd_output.json` | `agents/visual_director/output.json` | Bug 1 (rejected candidates in assets) + Bug 2 (hook=33.173s, reaction=29.681s) |
| `composer_output.json` | `agents/composer/output.json` | Composer marked "completed" despite black frames |
| `visual_coverage.json` | `data/outputs/job_8/visual_coverage.json` | Bug 3 (3 BLACK_FRAME issues, worst=13533ms black tail) |
| `manifest.json` | `manifest.json` | Gates G3/G6/G7 hard_failed but pipeline continued; reviewer has no output |
| `narrative_structure.json` | `agents/scriptwriter/narrative_structure.json` | Beats with word_range for timeline regression |
| `voice_producer_output.json` | `agents/voice_producer/output.json` | Actual audio duration + timestamps for timeline regression |

**Frozen into `tests/fixtures/job8/` (JSON only — no binaries):**

```
tests/fixtures/job8/
├── vd_output.json
├── composer_output.json
├── visual_coverage.json
├── manifest.json
├── narrative_structure.json
├── voice_producer_output.json
└── expected_failures.json    ← NEW: maps each artifact to the bug(s) it documents
```

**Characterization tests** (`tests/test_job8_regression.py`):

These tests assert the **current broken behavior** — they PASS on master today. They serve as tripwires: if someone "fixes" one symptom but recreates another, the test catches it.

| Test | Asserts (broken behavior) | Bug |
|------|---------------------------|-----|
| `test_bug1_rejected_candidate_still_in_plan` | Beat 2 inspection=`reject` but asset `source=tiktok_clip` | 1 |
| `test_bug2_hook_duration_is_33s` | Hook `target_duration=33.173` (absurd) | 2 |
| `test_bug3_fade_to_black_st_is_zero` | `builder.build(asset)` contains `st=0.0` | 3 |
| `test_bug3_black_tail_13s` | visual_coverage has BLACK_FRAME 2100ms+ in output | 3 |
| `test_bug4_reviewer_no_artifact` | `reviewer/output.json` does not exist | 4 |
| `test_bonus_gates_hard_failed_pipeline_continued` | G3/G6/G7 hard_fail but all agents "completed" | bonus |

**Phase 2 transition:** When PR 1 fixes a bug, the corresponding test is updated from asserting broken behavior → asserting correct behavior. Same fixture, same test name, only the expected value changes — making the fix visible in the diff.

**Two testing levels:**

| Level | What | Speed | API keys? | When |
|-------|------|-------|-----------|------|
| **L1: Artifact-based** | Load frozen JSON, run specific function, assert output | Fast (<1s) | No | Batch 0 + PRs 1–3 |
| **L2: Full-pipeline** | Re-run entire pipeline with Job #8's topic | Slow (minutes) | Yes (`@integration`) | PR 8 only |

**Batch 0 does L1 only.** L2 comes in PR 8 because it requires API keys and is marked `@pytest.mark.integration`.

**FFmpeg command capture (Bug 3):** `TreatmentFilterBuilder.build()` is a pure function — calling it with the frozen asset reproduces the broken command deterministically (`st=0.0`). No code changes needed to capture it.

**Verification:**
- `.venv/bin/python3 -m pytest tests/test_job8_regression.py -v` — all characterization tests pass on current master
- No production code modified
- SonarCloud Quality Gate passes

---

### PR 1 — Job #8 Production Correctness Hotfix (P0) ✅ IMPLEMENTED

**Branch:** `phase/26-pr1-hotfix`
**Scope:** Fix only confirmed runtime defects. No architecture changes.

**Fixes applied:**

1. **Candidate rejection enforcement** (`visual_director.py:997`)
   - When `select_best_candidate` returns `None` (all rejected), clear the original `plan_item["action"]` and replace with fallback text card.
   - Logic: rejected → remove original action → select next accepted → otherwise fallback card → otherwise fail gate.
   - Tests: rejected-candidate clears action; all-rejected → fallback card; mixed → best accepted.

2. **`fade_to_black` start time** (`treatment_filters.py` + `composer.py:1016,1398`)
   - The fade-out `st` value should be `scene_duration - 0.5`, not a cumulative offset or `0.0`.
   - **Note:** verify `templates/treatments.yaml` — the template may use `{start_time}` where it should use a computed `{duration}-0.5`. Fix at the correct layer (template or builder).
   - Tests: fade-out `st` equals `duration - 0.5`; render command fixture matches.

3. **Freeze-detector threshold format** (Composer diagnostics)
   - Verify the freeze-detection threshold is passed in the correct format to FFmpeg.
   - Tests: generated filter string uses correct threshold syntax.

4. **Persist Composer/Reviewer output after diagnostics**
   - Composer output artifact written only after diagnostics pass.
   - Reviewer deterministic decisions persisted to artifact (not just in-memory).
   - Tests: artifact exists after diagnostics; deterministic gate results in JSON.

**Verification:**
- `.venv/bin/python3 -m pytest -m "not external and not integration" -q` — all green
- Job #8 regression fixture added (if artifacts available)
- SonarCloud Quality Gate passes

---

### PR 2 — Canonical Beat Timeline Enforcement (P1)

**Branch:** `phase/26-pr2-canonical-timeline`
**Scope:** Realize ADR 0020. Single immutable timeline after voice generation.

**Changes:**

1. Add `BeatTimelineEntry` model to `config/schema.py` (extends existing 11 Pydantic models):
   ```python
   @dataclass(frozen=True)
   class BeatTimelineEntry:
       beat_id: int
       start_sec: float
       end_sec: float
       duration_sec: float
       word_start_index: int
       word_end_index: int
   ```

2. Build the canonical timeline once, after Voice Producer, using `ffprobe` actual audio duration + word-level timestamps from ElevenLabs `/with-timestamps`.

3. **Visual Director reads the timeline** — remove `_calculate_beat_durations()` + `_find_word_range_timestamps()`. Use `timeline[beat_id].duration_sec`.

4. **Composer reads the timeline** — remove `_compute_beat_durations()`. Use the same canonical entry.

5. **Reviewer reads the timeline** — validate rendered scene durations against canonical entries.

6. Timeline artifact persisted to `job_{id}/canonical_timeline.json` for debugging.

**Verification:**
- VD and Composer produce identical durations from the same timeline
- Timeline artifact exists and is valid JSON
- Existing tests pass (adapted to read timeline instead of deriving)

---

### PR 3 — Deterministic Failure-to-Repair Integration (P1)

**Branch:** `phase/26-pr3-repair-integration`
**Scope:** Extend ADR 0023. Make deterministic gates auto-generate repair patches.

**Changes:**

1. Add failure-to-patch mapping table (extends `repair_router.py`):
   ```
   BLACK_FRAME        → RepairPatch(reason="black_frame",        rerun_from="composer")
   FREEZE_FRAME       → RepairPatch(reason="freeze_frame",       rerun_from="composer")
   DUPLICATE_TEXT     → RepairPatch(reason="duplicate_text",     rerun_from="composer")
   MISSING_ASSET      → RepairPatch(reason="broken_source",      rerun_from="visual_director")
   TEXT_COLLISION     → RepairPatch(reason="text_collision",     rerun_from="visual_director")
   DIRTY_SOURCE       → RepairPatch(reason="broken_source",      rerun_from="visual_director")
   WRONG_EVENT        → RepairPatch(reason="wrong_event",        rerun_from="segment_producer")
   ```

2. When a deterministic gate fails with no LLM repair plan, auto-generate `RepairPatch` from the mapping.

3. `_handle_review_outcome()` enters repair loop on deterministic failures even when `review_output["repair_plan"]` is absent.

4. Every hard failure either produces a repair patch or explicitly states why it's not repairable.

**Verification:**
- Simulated BLACK_FRAME failure enters repair loop and reruns Composer
- Simulated TEXT_COLLISION enters repair loop and reruns Visual Director
- Gate failure with no mapping produces explicit "not repairable" reason

---

### PR 4 — Segment Producer Precision Upgrade (P2)

**Branch:** `phase/26-pr4-sp-precision`
**Scope:** Improve existing multi-source discovery; do NOT add new providers.

**Changes:**

1. Structured entity extraction from research (event name, date, location, quoted statement, original publisher).
2. Per-beat search queries driven by `story_beats[].visual_must_show` + `spoken_point`.
3. Provider attempt history persisted (which provider returned which candidate).
4. Source-tier escalation (if tier-1 source fails, escalate to tier-2).
5. Candidates grouped by beat, not globally.

**Verification:**
- Each beat has its own candidate group
- Entity extraction produces structured fields
- Provider history artifact exists

---

### PR 5 — Pre-Visual-Director Asset Qualification Boundary (P2, HIGH RISK)

**Branch:** `phase/26-pr5-pre-vd-qualification`
**Scope:** Move qualification upstream. Reuse existing modules — do NOT rebuild.

> ⚠️ **Highest-risk PR.** This refactors a working pipeline. Requires PRs 1–4 merged and stable. Strong integration tests mandatory.

**Changes:**

1. Create `core/asset_qualification.py` — a service that orchestrates existing modules:
   - `frame_sampler` + `frame_extractor` → sample frames
   - `ocr_adapter` → extract text
   - `face_adapter` → detect faces
   - `source_cleanliness` → score cleanliness
   - `MultimodalInspectionClient` → visual inspection
   - `candidate_semantic_ranker` → rank + reject

2. Pipeline becomes:
   ```
   Segment Producer raw candidates
   → Asset Qualification (existing modules, new orchestration)
   → qualified portfolio (only accepted/revised candidates)
   → Visual Director (plans from qualified assets only)
   ```

3. Visual Director no longer discovers bad sources for the first time — it receives pre-qualified candidates.

4. VD may still inspect final crop/layout, but source qualification happens upstream.

**Verification:**
- Rejected candidates never reach Visual Director
- Qualification artifact (`job_{id}/qualification_report.json`) exists
- All existing VD tests pass (adapted to receive pre-qualified candidates)
- Integration test: full pipeline with a known-bad source → rejected before VD

---

### PR 6 — Source Transcript & Clip-Window Selector (P2)

**Branch:** `phase/26-pr6-clip-window`
**Scope:** Adapt the Clip-Anything concept for precise source trimming.

**Changes:**

1. For qualified source videos, generate transcript (whisper or existing transcription).
2. Find the coherent relevant window matching the beat's claim.
3. Output `source_start_sec` / `source_end_sec` for Composer trimming.
4. Composer trims from the validated window, not always from timestamp zero.

**Verification:**
- Clip window falls within source video bounds
- Trimmed segment matches the beat's spoken point
- Composer uses `source_start_sec` in FFmpeg trim command

---

### PR 7 — Visual Director Multi-Shot Planning (P2)

**Branch:** `phase/26-pr7-multishot-vd`
**Scope:** Upgrade VD from one asset per beat to multiple shots when needed.

**Rules:**
```
hook card ≤ 3s
CTA ≤ 3s
static image/card ≤ 3–4s before visual change
normal shot 2–5s
long beat must contain multiple shots
dirty source cannot be fullscreen
```

**Verification:**
- Beats longer than 5s contain multiple shots
- Hook/CTA shots respect duration limits
- Dirty sources rendered as inset, not fullscreen

---

### PR 8 — Release Gate & Golden-Set Validation (P3)

**Branch:** `phase/26-pr8-release-gate`
**Scope:** Validate the full release against Job #8 + golden set. Cut v2.4.0.

**Changes:**

1. Golden-set test suite: Job #8 + ≥9 other jobs (diverse niches, durations, source types).
2. Release gate fails if ANY of:
   - Any rejected candidate is rendered
   - Any unintentional black frame exceeds 200ms
   - Duplicate card text exists
   - Any important beat lacks a qualified visual
   - Any hard gate fails while `publication_status == "ready"`
   - Reviewer output artifact is missing

3. **Version bump** — in the same PR, after golden-set passes:
   - Update version in `clipper_agency/__init__.py` (or wherever version is defined — verify location)
   - Update `CHANGELOG.md` (create if missing)
   - Update AGENTS.md Repository State
   - Tag `v2.4.0`

**Verification:**
- Golden-set: 10/10 jobs pass
- Version string reads `2.4.0`
- Git tag `v2.4.0` created
- Full test suite green
- SonarCloud Quality Gate passes

---

## 4. Execution Order & Dependencies

```
Batch 0 (job8 fixture) ─────────────────────► merge (prerequisite, no code changes)
                                               │
PR 1 (hotfix) ──────────────────────────────► merge (needs Batch 0 to verify fixes)
                                               │
PR 2 (canonical timeline) ───────────────────► merge (needs PR 1)
                                               │
PR 3 (repair integration) ───────────────────► merge (needs PR 1)
                                               │
          ┌────────────────────────────────────┘
          │
PR 4 (SP precision) ──────┐
PR 5 (pre-VD qual)  ──────┤ (needs PRs 1–3; PR 5 is highest risk)
PR 6 (clip window)  ──────┤ (needs PR 5 for qualified sources)
PR 7 (multishot VD) ──────┘ (needs PR 2 for canonical timeline)
          │
          ▼
PR 8 (release gate + v2.4.0 bump) ──────────► merge (needs ALL prior)
```

**Rule:** Batch 0 is the prerequisite — it must merge before PR 1. PRs 4–7 can be developed in parallel branches but must merge sequentially after PR 3. PR 8 is the final merge that bumps the version.

---

## 5. Constraints

- **AGENTS.md git workflow:** branch → PR → SonarCloud MUST pass → merge `--merge` (no squash) → delete branch → pull master. Every PR.
- **Pre-PR checklist:** `.venv/bin/python3 -m pytest -m "not external and not integration" -q` (all pass); `--cov` ≥93%.
- **KISS/YAGNI/DRY:** reuse existing modules. Do not build new inspection/repair/ranking subsystems.
- **TDD:** tests first for every change.
- **No intermediate version bumps:** v2.3.0 frozen until PR 8.
