# PR 5 (Step 5) — Pre-Visual-Director Asset Qualification Boundary

**Status:** LOCKED — codegraph-verified (2026-06-17)
**Branch:** `phase/26-pr5-pre-vd-qualification`
**Parent plan:** [`docs/plans/2026-06-15-phase26-production-correctness-asset-qualification.md`](./2026-06-15-phase26-production-correctness-asset-qualification.md) (Step 5 / PR 5, ~lines 298–340)
**Implementation method:** `/ecc:orch-change-feature`, TDD per slice (14 slices below)
**Version:** stays `v2.3.0` (PR 8 owns the `v2.4.0` bump)

> This document is the verified implementation design for PR 5. It was produced by a 4-phase
> design workflow (Understand → Design → Judge → Synthesize; 11 agents) and then **locked by a
> 7-claim codegraph verification pass** (3 claims held, 4 refined — none invalidated the design).
> Every signature and line number below was confirmed against the live source. The amendments from
> verification are marked **[V#]** inline.

---

## 1. Context & Goal

Phase 26 is the v2.4.0 roadmap: fix the 4 confirmed production-correctness defects from Job #8 and
make built-but-unenforced contracts actually govern pipeline behavior. **PR 5 is the real Job #8 fix.**

Job #8 root cause was **candidate rejection, not scarcity**: Visual Director rejected 7 of 8
candidates and fell back to text cards. PR 5 introduces a **pre-VD asset qualification boundary**
that scores candidates *before* VD consumes them, and — critically — runs **source recovery before
the text-card fallback** so a beat with zero qualified candidates gets fresh candidates from a new
discovery pass rather than immediately degrading to a text card.

**Qualification boundary definition:** an in-process, synchronous transform that runs inside the
orchestrator's `_run_visual_director_phase`, *after* voicing and *before* VD. It reuses VD's own
candidate-scoring logic, qualifies each beat's candidates, rewrites the candidate pool VD receives,
and emits a `qualification_report.json` artifact.

---

## 2. Design Decision — Minimal Boundary Coordinator

A 3-way design panel (Minimal boundary coordinator / Contract-first typed boundary /
Pipeline-staged with explicit recovery) was scored by an adversarial 3-judge panel. **All 3 judges
selected Design 1 (Minimal Boundary Coordinator)** — the only design that strictly honors ADR 0026's
"enforce contracts, do NOT rebuild."

### Rejected alternatives (and why)

- **Contract-first typed boundary (Design 2)** — REJECTED. It built a genuinely-new 7-scalar
  OCR/face cleanliness-aggregation subsystem (`has_logo`, `logo_coverage_ratio`,
  `safe_crop_available` from corner-clustered OCR regions; `has_burned_captions` from bottom-zone
  text). That is a **new media-analysis subsystem** in direct violation of ADR 0026 pt. 4. It also
  duplicated existing model shapes (DRY violation) and coupled pre-VD recovery to the post-Reviewer
  `RepairPlan` lifecycle (ADR 0023 collision).
- **Pipeline-staged (Design 3)** — REJECTED. Same smuggled aggregation subsystem, plus an
  **unresolved frame-ownership problem** (double FFmpeg/VLM extraction, or a VD refactor larger than
  PR 5's "reuse, don't rebuild" mandate). One idea was grafted: a **named RECOVER stage** with a
  `recovery_outcome` enum for auditability.

**Graft from Design 3:** `BeatQualificationResult.recovery_outcome` enum
(`none` | `ran` | `exhausted` | `no_fn`) so `qualification_report.json` proves recovery was attempted
before any text card.

---

## 3. Verification Status (7-claim codegraph pass)

| # | Claim | Verdict | Amendment |
|---|-------|---------|-----------|
| 1 | SP discovery + transform method kinds | ⚠️ wording | transforms are `@staticmethod` (not instance); callable on `self.` as `execute()` already does. **No code change.** |
| 2 | `_score_one_candidate` lift + cache-key parity | ✅ holds | literals byte-identical; lift injects `_run_inspection`/`_score_cleanliness` as module fns |
| 3 | Cleanliness proxy + dead `_inspection_metrics` | ✅ holds | proxy returns `visual_quality`; metrics dict confirmed dead in production |
| 4 | Dual-surface rewrite + fallback paths | ⚠️ **simplified** | `_find_replacement_url` is dead code reading a per-beat pool; sole live surface is `_apply_best_candidate` |
| 5 | Engine seam + in-scope vars | ⚠️ wiring | use `assets_cache` + `paths.agent_dir(...)` + `load_settings()` (no `self.config`) |
| 6 | Job #8 golden fixture | ⚠️ harness-build | fixture exists & offline; build inline VD driver; copy `research_contract.json`; re-derive baseline N inline |
| 7 | Settings/config keys | ✅ holds | `load_settings()` → `AppSettings` has both keys top-level; available at seam |

---

## 4. Module Design

**File:** `clipper_agency/core/asset_qualification.py` (~300 lines, pure orchestration)

Lifts VD's scoring chain into a pre-VD service. **Imports only** existing modules:
`inspection_cache` (`compute_cache_key`, `compute_asset_content_hash`, `lookup`, `store`),
`MultimodalInspectionClient` (`inspect_asset`), `semantic_visual_review` (`score_visual_relevance`),
`candidate_semantic_ranker` (`rank_candidates`, `select_best_candidate`).

**Imports NEITHER** `segment_producer` nor `visual_director` — the SP discovery callable is injected
as an opaque `Callable` (via `RecoveryPolicy.discover_fn`) to break the import cycle.

| Function | Signature | Responsibility |
|----------|-----------|----------------|
| `qualify_research_candidates` | `(research_output: dict, job_id: int, cache_dir: str, agent_dir: str, *, inspector: MultimodalInspectionClient \| None = None, recovery: RecoveryPolicy \| None = None, min_claim_support: float = 0.30, max_misleading_risk: float = 0.50, sp: 'SegmentProducerAgent' \| None = None, config: Any \| None = None, topic: str = '', entities: list \| None = None) -> list[BeatQualificationResult]` | **Public entry.** Per-beat orchestrator; parses each `research_output['story_beats']` entry into a `StoryBeat`, filters `do_not_use` URLs, qualifies each beat via `_qualify_beat`. The engine seam uses results to rewrite `research_output` and write the report. |
| `_qualify_beat` | `(beat: StoryBeat, beat_dict: dict, plan_item: dict \| None, job_id: int, cache_dir: str, agent_dir: str, do_not_use: list[str], inspector, recovery, ctx_factory: Callable[[], AssetQualificationContext], min_claim_support: float, max_misleading_risk: float) -> BeatQualificationResult` | Score → rank → **recover if zero qualified** → re-score/re-rank → assemble result. **The recovery-before-text-card ordering lives here (module-level contract — not outsourced to engine).** |
| `_score_candidate` | `(candidate: Any, beat: StoryBeat, plan_item: dict \| None, job_id: int, cache_dir: str, agent_dir: str, inspector) -> dict \| None` | **Verbatim lift of `VD._score_one_candidate`** (visual_director.py:748-803) with `self.*` deps removed. Cache-key literals byte-identical to VD:759-766. Calls the module's own `_run_inspection` and `_score_cleanliness` (the lifted, de-self'd equivalents). |
| `_run_inspection` | `(candidate: Any, beat: StoryBeat, job_id: int, cache_dir: str, cache_key: str, agent_dir: str, inspector) -> dict \| None` | **Verbatim lift of `VD._run_multimodal_inspection`** (visual_director.py:895). Extracts frames via the same `_extract_candidate_frames` path VD uses (frame ownership stays put — no double extraction **[V2/V4]**), calls `inspect_asset`, `store()` only when `decision != 'error'`, returns `None` on exception. |
| `_score_cleanliness` | `(candidate: Any, inspection: dict) -> float` | Identical dead-`_inspection_metrics` proxy behavior: `inspection.get("visual_quality", 0.5)`. **No new heuristics** (logo clustering etc. are a future PR) **[V3]**. |
| `_attempt_recovery` | `(beat: StoryBeat, ctx: AssetQualificationContext, recovery: RecoveryPolicy, cycle: int) -> tuple[list[Any], list[dict]]` | **Named RECOVER stage.** Builds expanded per-beat queries from `beat.visual_must_show` + `beat.spoken_point`, invokes the injected `recovery.discover_fn`, logs a structured event, returns `(new_candidates, new_provider_attempts)`. Bounded by `MAX_RECOVERY_CYCLES` (module constant = 1). |
| `_build_sp_discovery_adapter` | `(sp: 'SegmentProducerAgent', topic: str, entities: list, config: Any, beats: list[dict] \| None = None) -> Callable[[list[str]], tuple[list[dict], list[dict]]]` | **[V1]** Curries `(sp, topic, entities, config, beats)` and returns `Callable[queries -> (candidate_dicts, attempts)]`. Internally calls `sp._discover_multi_source_assets(topic, entities, config, beats=[beat_dict])` then `sp._build_asset_candidates_from_sources(sources=raw)` + `sp._distribute_candidates_to_beats(...)` (both `@staticmethod`, callable on the instance). |
| `build_qualification_report` | `(job_id: int, results: list[BeatQualificationResult]) -> dict` | Pure serializer → `qualification_report.json`. |

---

## 5. Contract Types (module-local, NOT promoted to `config/schema.py` — YAGNI/DRY)

- **`BeatQualificationResult`** (`@dataclass`) — `beat_id: str`; `verdict: str`
  (`'qualified' | 'recovered' | 'exhausted_text_card'`); `recovery_outcome: str`
  (`'none' | 'ran' | 'exhausted' | 'no_fn'`); `recovery_attempts: int`; `qualified: list[dict]`
  (accept+revised, rank order, exact `rank_candidates` shape); `scored: list[dict]` (full set incl.
  rejects); `reject_reasons: dict[str, str]` (`asset_id -> reason`); `fallback_card: dict | None`
  (only when `verdict == 'exhausted_text_card'`); `provider_attempts_added: list[dict]`.
- **`AssetQualificationContext`** (`@dataclass`) — bundles the >5 scalars per the `>5 params →
  dataclass` rule: `job_id`, `beat`, `cache_dir`, `agent_dir`, `inspector`, `recovery`, `plan_item`.
  Enables per-beat unit testing with fakes.
- **`RecoveryPolicy`** (`@dataclass`) — `enabled: bool = True`; `max_cycles: int = MAX_RECOVERY_CYCLES`
  (1); `discover_fn: Callable[[list[str]], tuple[list[dict], list[dict]]] | None = None`.
- **`qualification_report.json` artifact** — plain dict produced by `build_qualification_report`,
  written by the orchestrator via existing `write_json` (`core/paths.py`). Shape:
  `{job_id, generated_at, summary:{total_beats, qualified_beats, recovered_beats,
  text_card_last_resort_beats, providers_attempted_added}, beats:[{beat_id, verdict,
  recovery_outcome, qualified_count, recovery_attempts, reject_reasons, top_asset_id, top_score}]}`.

---

## 6. Orchestration Flow (the seam)

**Seam:** `Engine._run_visual_director_phase` (`clipper_agency/orchestrator/engine.py:1206`).
Insert ~15 lines between line 1229 (research paths resolved) and line 1230 (the
`_run_visual_director` call). **[V5]** Real in-scope vars: `self` (only `db_path` + `_trace_writer`),
`conn`, `job_id`, `topic`, `research_output`, `script_output`, `output_dir`, `assets_cache`,
`voice_output`, `beat_timeline`, locals `vo`, `research_contract_path`, `research_brief_path`.

1. **Acquire config & dirs [V5/V7]:** `settings = load_settings()` (module-imported in engine.py:19,
   the same idiom SP uses at segment_producer.py:213). Cache root = the `assets_cache` parameter.
   Per-agent dir via `clipper_agency.core.paths.agent_dir(assets_cache, job_id, "segment_producer")`.
2. **Build the SP adapter:** `sp = SegmentProducerAgent()` (lightweight, no API calls on
   construction); `discover_fn = _build_sp_discovery_adapter(sp, topic, research_output.get('entities', []), settings, beats=research_output.get('story_beats', []))`;
   `recovery = RecoveryPolicy(enabled=True, max_cycles=1, discover_fn=discover_fn)`. Build
   `MultimodalInspectionClient` with the same client/trace_writer VD uses.
3. **Call:** `results = qualify_research_candidates(research_output, job_id, cache_dir, agent_dir, inspector=mic, recovery=recovery, sp=sp, config=settings, topic=topic, entities=research_output.get('entities', []))`.
4. **Rewrite `research_output` immutably** (new dicts per CLAUDE.md): for each beat + matching
   result, `qualified_story_beats.append({**beat_dict, 'asset_candidates': [c['candidate'] for c in result.qualified]})`;
   for `verdict == 'exhausted_text_card'` beats also set `beat_dict['qualification_text_card'] = result.fallback_card`.
   Then `qualified_flat = research_output['asset_candidates']` minus every `asset_id` in the union of
   all `reject_reasons` across all beats. *(The flat-pool filter is cheap defense-in-depth —
   **[V4]** the load-bearing surface is the per-beat `beat.asset_candidates`.)*
5. **Write artifact:** `write_json(<job_dir>/qualification_report.json, build_qualification_report(job_id, results))`.
6. **Call VD** with the SAME kwargs as today (engine.py:1230-1242) but
   `story_beats=qualified_story_beats`, `asset_candidates=qualified_flat`. VD receives pre-qualified
   input transparently; its `_apply_best_candidate` still runs as defense-in-depth but on a pool with
   100% cache hits (candidates just inspected) → **no double VLM spend**.
7. `_complete_agent('visual_director')` as today. **DB state machine unchanged** — no new state, no
   new gate (ADR 0023 precedent of 0 new top-level agents honored).

---

## 7. Source-Recovery-Before-Fallback (the Job #8 fix)

Lives **inside** `_qualify_beat` (module-level, unit-testable — **[V4]** not outsourced to engine):

1. **SCORE** all candidates via `_score_candidate` (cache-key literals `'multimodal'`/`'1.0'`/`''`
   byte-identical to VD:759-766).
2. **RANK** via `candidate_semantic_ranker.rank_candidates(beat_dict, scored)` → decisions
   `{accept, revise, reject, fallback_card}`.
3. **QUALIFIED CHECK:** if any ranked candidate is `{accept, revise}` → return
   `verdict='qualified'`, `recovery_outcome='none'`. No recovery, no text card.
4. **RECOVER STAGE** (fires ONLY when qualified is empty): if `recovery.enabled AND discover_fn AND
   recovery_attempts < max_cycles` → build expanded queries, call `_attempt_recovery` → invokes
   `discover_fn` (bound to `SP._discover_multi_source_assets` with the failing beat as
   `beats=[beat_dict]` **[V1]**). YouTube always runs (free); Tavily/Brave run additively if keyed
   (no tier escalation — 4d-confirmed union). New candidates get fresh content-hash cache keys →
   fresh `inspect_asset`; identical URLs stay cached (no double VLM). Re-run steps 1-2. If now any
   `{accept, revise}` → `verdict='recovered'`, `recovery_outcome='ran'`, `recovery_attempts=1`.
5. **FALLBACK (terminal, last resort):** if qualified STILL empty after recovery, OR recovery
   disabled (`recovery_outcome='no_fn'`), OR budget exhausted (`recovery_outcome='exhausted'`) →
   `verdict='exhausted_text_card'`, `qualified=[]`, `fallback_card={...}`. **The only path that
   emits a text card.**

Recovery emits **no** `RepairPatch`, calls **no** `build_gate_failure_repair_plan`, touches **no**
`GATE_FAILURE_REPAIR_MAP` — synchronous in-process, distinct from ADR 0023's post-Reviewer path.

---

## 8. Hand-off Changes

- **MODIFY `Engine._run_visual_director_phase`** (engine.py:1206-1242): insert the seam (~15 lines
  between 1229 and 1230). The `_run_visual_director` call kwargs are **unchanged in shape** — only
  the CONTENT of `story_beats`/`asset_candidates` is qualified.
- **MODIFY `VD._apply_best_candidate`** (visual_director.py:1087): **no signature change.** It still
  ranks/selects over whatever candidates it receives. Post-qualification the all-rejected text-card
  path at 1117-1130 becomes a genuine last resort (only for `verdict == 'exhausted_text_card'`
  beats). Keep as defense-in-depth.
- **`VD._score_one_candidate`** (visual_director.py:748): **kept as-is** for PR 5's minimal blast
  radius. It hits cache 100% on pre-qualified candidates (just inspected), so no double VLM spend.
  Delegating to `asset_qualification._score_candidate` (DRY) is a **follow-up**, not a PR 5 deliverable.
- **DO NOT MODIFY:** `StoryBeat` schema (qualification replaces list CONTENT immutably);
  `state_machine.py`; `core/repair_router.py`; `MultimodalInspectionClient`; `inspection_cache`;
  `candidate_semantic_ranker`; `semantic_visual_review`.

---

## 9. TDD Slice Breakdown (drives `/ecc:orch-change-feature`)

| # | Slice | Notes |
|---|-------|-------|
| 1 | Cache-key parity = VD convention (byte-identical) | **HARD merge gate** — verified [V2] |
| 2 | Happy-path qualified set (accept+revised) | |
| 3 | **All-reject → recovery BEFORE text_card** | *the Job #8 fix test* |
| 4 | Recovery exhausted → text_card last resort | |
| 5 | `MAX_RECOVERY_CYCLES=1` bound (no infinite loop) | |
| 6 | Inspection error = cache-miss, no store | |
| 7 | SP discovery adapter real-signature | **[V1]** `@staticmethod` transforms; pin named args |
| 8 | `do_not_use` URL filter | |
| 9 | Rejected `asset_id`s removed from the **live per-beat** `beat.asset_candidates` surface | **[V4]** re-scoped — `_find_replacement_url` is dead; flat-pool filter is defense-in-depth only |
| 10 | VD hand-off transparency (0 double-VLM) | |
| 11 | `qualification_report.json` written | |
| 12 | **Job #8 golden regression: M < N text-cards** | **HARD merge gate** — **[V6]** build inline VD driver; copy `research_contract.json`; re-derive N inline |
| 13 | Known-bad source rejected before VD | |
| 14 | Existing VD suite passes unmodified | blast-radius containment |

**[V6] SLICE 12 harness detail:**
- Inline driver: `VD.execute(job_id=8, topic=..., output_dir=tmp, story_beats=load(narrative_structure.json), timestamps=load(voice_producer_output.json), assets_cache=tmp)` with mocked OpenRouter/Pexels/inspection → capture baseline N from `result['assets']`.
- Copy `data/assets/cache/job_8/agents/segment_producer/research_contract.json` (+ `research_brief.md`) into `tests/fixtures/job8/` for hermetic recovery input.
- **Do not** read expected N from `vd_output.json` — it encodes the old rejection logic. Re-derive N inline.

---

## 10. Files

**Create:**
- `clipper_agency/core/asset_qualification.py`
- `tests/core/test_asset_qualification.py`
- `tests/integration/test_job8_qualification_regression.py`

**Modify:**
- `clipper_agency/orchestrator/engine.py` (`_run_visual_director_phase`: insert seam ~1229-1230)
- `CHANGELOG.md` (PR 5 entry under `[Unreleased]`)
- `docs/technical_design.md` (pre-VD qualification boundary + agent role note)
- `docs/requirements_traceability.md` (trace PR 5 acceptance criteria)
- `docs/plans/2026-06-15-phase26-production-correctness-asset-qualification.md` (mark PR 5 ✅ after merge)

---

## 11. Acceptance Criteria (mapped to plan doc)

- Rejected candidates never reach Visual Director — SLICE 9 (live per-beat surface) + SLICE 13. *(plan line 335)*
- `qualification_report.json` exists with the documented shape — SLICE 11. *(plan line 337)*
- All existing VD tests pass on pre-qualified input — SLICE 14. *(plan line 338)*
- Job #8 rerun → VD receives qualified candidates → **fewer** text-card fallbacks than baseline — SLICE 12 (M < N). *(plan line 339)*
- Known-bad source rejected before VD — SLICE 13. *(plan line 340)*
- Source-recovery-before-text-card enforced at module level — SLICE 3 + 4. *(plan line 333)*
- ADR 0026: zero new inspection/scoring/ranking subsystems — orchestration only + recovery ordering.
- ADR 0023: recovery is synchronous in-process, no `RepairPatch`, no `GATE_FAILURE_REPAIR_MAP` entry.
- ADR 0020: runs after voicing, before visualizing; beat timing untouched.
- Version stays `v2.3.0`.
- Pre-PR: `.venv/bin/python3 -m pytest -m "not external and not integration" -q` all pass; `--cov ≥ 93%`; SonarCloud zero new issues; Codex resolved; `gh pr merge --merge`.

---

## 12. Risks & Mitigations

- **Cache-key literal drift** (HIGHEST — forks cache namespace, re-spends VLM). → SLICE 1 hard gate; verbatim lift; module constants.
- **Recovery infinite loop.** → `MAX_RECOVERY_CYCLES=1` + SLICE 5.
- **SP discovery signature mismatch.** → **[V1]** verified; `_build_sp_discovery_adapter` + SLICE 7.
- **Dual-surface divergence.** → **[V4]** simplified: one live per-beat surface; flat filter is defense-in-depth.
- **No `self.config` at the seam.** → **[V5]** `load_settings()` at the seam (matches SP idiom).
- **SP/VD import cycle.** → SP discovery injected as opaque `Callable`; module imports neither agent.
- **StoryBeat immutability.** → new dicts via spread; SLICE 9/10 verify input untouched.
- **Recovery API spend.** → only failing beats trigger recovery; `MAX_RECOVERY_CYCLES=1`; key-gated.
- **Dead cleanliness proxy inherited.** → stated trade-off: the win comes from source-recovery ordering, not better rejection. `qualification_report.json` records `reject_reasons`.

---

## 13. ADR 0026 Compliance

ADR 0026 pt. 4 names pre-VD qualification as the **one** genuinely-new architectural element of the
phase, governed by *"enforce contracts, do NOT rebuild."* This design complies on every axis:
`asset_qualification.py` **imports and calls only existing modules**; `_score_candidate` is a verbatim
lift of `VD._score_one_candidate`; `_run_inspection` is a verbatim lift of `VD._run_multimodal_inspection`
preserving frame ownership, store-on-non-error, and None-on-exception. It **rejects** the
cleanliness-aggregation subsystem Designs 2/3 smuggled in. The only genuinely-new logic is (a) the
recovery-before-text-card ordering, (b) the SP discovery adapter shim (plumbing, not analysis), and
(c) two module-local dataclasses. No new agent, no new gate, no `state_machine.py` change, no new
`RepairPatch`/`RepairPlan` (ADR 0023 non-collision), no new `schema.py` models (DRY). Cache invariants
preserved byte-identical. This is exactly the orchestration-over-rebuild ADR 0026 mandates.

---

## 14. Verification Evidence Appendix (codegraph-confirmed)

| Symbol | Location | Verified signature / behavior |
|--------|----------|-------------------------------|
| `SegmentProducerAgent._discover_multi_source_assets` | segment_producer.py:652 | `(self, topic: str, entities: list, config: Any, beats: list[dict] \| None = None) -> tuple[list[dict], list[dict]]`; instance method; returns RAW provider source dicts |
| `_build_asset_candidates_from_sources` | segment_producer.py:420 | `@staticmethod (sources=None, firecrawl_data=None, scrapecreators_data=None) -> list[dict]`; callable on instance |
| `_distribute_candidates_to_beats` | segment_producer.py:852 | `@staticmethod (story_beats, global_candidates, max_per_beat=5, min_score=0.1) -> list[dict]`; callable on instance |
| `VD._score_one_candidate` | visual_director.py:748-803 | `(self, candidate, beat: StoryBeat, plan_item: dict, job_id: int, cache_dir: str, agent_dir: str = "") -> dict \| None`; `asset_id = f"{candidate.type}_{candidate.url[:40]}"` (758); cache_key literals byte-identical (759-766); 2 `self.*` deps: `_run_multimodal_inspection` (768), `_compute_cleanliness_score` (795) |
| `VD._compute_cleanliness_score` | visual_director.py:805 | `metrics = self._inspection_metrics.get(url, None); if not metrics: return inspection.get("visual_quality", 0.5)`; `_inspection_metrics` dead in production (init `{}` 87, reset `{}` 107, read 819) |
| `VD._apply_best_candidate` | visual_director.py:1087-1130 | trigger `if best and best.decision=="accept" and best.asset_id!="fallback"` (1104) → apply+return (1112); else fallback 1117-1130 |
| `VD._find_replacement_url` | visual_director.py:1200 | `(candidates, action_type, blocked, used_urls) -> str \| None`; **DEAD CODE** — caller `_resolve_beat_plan_assets` (1177) has zero production callers; reads per-beat pool |
| `VD._collect_candidate_scores` | visual_director.py:723 | `for candidate in beat.asset_candidates` — the **live** per-beat surface VD reads |
| `VD._run_multimodal_inspection` | visual_director.py:895-952 | frame extract (909); `store` only when `decision != 'error'` (947-948); `None` on exception (950-952) |
| `Engine._run_visual_director_phase` | engine.py:1206 | `(self, conn, job_id, topic, research_output, script_output, output_dir, assets_cache, voice_output=None, beat_timeline=None) -> dict`; seam between 1229 and 1230; `story_beats` kwarg 1236, `asset_candidates` kwarg 1239; no `self.config` |
| `load_settings` | config/loader.py:10 | `() -> AppSettings`; module-imported in engine.py:19 |
| `AppSettings` | config/schema.py:187 | `tavily_api_key: str = ""` (204), `brave_api_key: str = ""` (205) top-level; SP reads via `getattr(config, "tavily_api_key", "")` (693), `getattr(config, "brave_api_key", "")` (715) |
| Job #8 fixture | tests/fixtures/job8/ | `narrative_structure.json` (8 beats), `vd_output.json` (8 candidate_inspections: 7 reject, 1 accept beat 6); offline (16 tests pass); **no `research_contract.json`** — copy from `data/assets/cache/job_8/agents/segment_producer/` |
