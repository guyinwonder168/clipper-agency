# AGENTS.md

Project-specific instructions for AI agents working in this repository.

## Repository State

- **Greenfield project** — early implementation phase (Phases 0-21 complete + Audio-First Continuous Voiceover v2.0.0 architecture redesign).
- Phase 21: deterministic quality gates + story-mode contracts + semantic relevance foundations + repair routing. 10 new core modules (`visual_coverage`, `frame_sampler`, `text_detection`, `text_collision`, `safe_area`, `story_mode`, `duration_budget`, `package_consistency`, `semantic_visual_review`, `repair_router`). Reviewer gate chain: `visual_coverage → text_collision → safe_area → package_consistency → semantic_review → LLM`. Evidence contracts on StoryBeat. Engine repair plan routing to correct existing agent. 0 new top-level agents.
- Phase 26 (in progress, v2.3.0 → v2.4.0 on PR 12): production-correctness + contract-enforcement roadmap (ADR 0026). Steps 1–6 COMPLETE — PR #50 Job #8 golden fixture; PR #51 hotfix (rejected-candidate enforcement, `fade_to_black` at clip end, reviewer artifact persistence); PR #52 ADR 0020 canonical timeline enforced (VD + Composer read orchestrator-built timeline); PR #53 ADR 0023 deterministic-gate→repair integration (`build_gate_failure_repair_plan`); PR #56/#58 + 4f-artifact-correctness Segment Producer precision (4a/4b/4c/4e + 4f-SP/VD/Reviewer); PR #5 pre-Visual-Director asset-qualification boundary (ADR 0026 + 0027, SLICE 1-12); PR #6 source transcript & clip-window selector (minimal contract-first, ADR 0026). **4d source-tier escalation deferred-confirmed** — providers already run additively (YouTube always; Tavily/Brave when keyed) and union results, so there is no tier escalation to build; Job #8 root cause was candidate rejection, not scarcity. Reviewer `programmatic_checks` now persisted on ALL gate-fail paths; inspection cache keyed by candidate content hash (`compute_asset_content_hash` → `asset_hash`) so SP-regenerated candidates invalidate stale entries. **PR 5 (pre-VD asset qualification + source recovery)** — new `clipper_agency/core/asset_qualification.py` scores image candidates BEFORE Visual Director consumes them; engine seam `_apply_asset_qualification` in `_run_visual_director_phase` qualifies each beat, IMMUTABLY rewrites `beat.asset_candidates` to the qualified set only, defense-in-depth-filters the flat pool, writes `qualification_report.json`. Job #8 root cause was candidate REJECTION (not scarcity), so on zero qualified candidates a RECOVER stage re-runs Segment Producer discovery and re-scores BEFORE the text-card fallback (bounded: `MAX_RECOVERY_CYCLES=1`, no loop). SLICE 1 cache-key parity hard gate — `asset_qualification._score_candidate` and `VD._score_one_candidate` compute byte-identical cache keys → VD re-inspection of a pre-qualified candidate is a cache hit (0 double-VLM spend). ADR 0027 cache-miss inspection delegates to VD's bound `_run_multimodal_inspection` (byte-identical cached output, no namespace drift, frame ownership stays in VD). ADR 0026 = enforce contracts, do NOT rebuild — pure orchestration, 0 new agent / 0 new gate / 0 state-machine change. SLICE 8 (do_not_use URL filter at the boundary) deferred to post-PR-5 — VD already enforces do_not_use at four downstream points, so re-filtering would be redundant contract re-enforcement; the layer's native badness signal is `reject_reasons`. SLICE 12 HARD merge gate proves M<N (recovery strictly reduces text-card fallbacks vs all-reject baseline) on the frozen Job #8 research contract; 69 existing VD tests pass unmodified (VD source untouched). **PR 6 (clip-window selector — minimal contract-first)** — new `clipper_agency/core/clip_window.py` (frozen `ClipWindow` dataclass + pluggable `WindowSelector` Protocol + `KeywordOverlapWindowSelector` v1 default, conservative: returns full-clip window `ClipWindow(0.0, None)` since keyword overlap cannot localize a spoken point to a timestamp). `AssetCandidate` gained optional `source_start_sec`/`source_end_sec` (additive, defaults preserve today's from-zero trim; excluded from inspection content hash so PR 5 cache-key parity holds). Propagated end-to-end: qualification seam attaches the window → VD (`_attach_candidate_windows` re-attaches by `source_url`; `_exec_tiktok_clip` threads it into the asset dict) → Composer (`_smart_trim` clamps to source bounds — degenerate ⇒ full clip — and `_trim_long_clip`/`_stretch_short_clip` emit `-ss <start>`). Transcript/whisper backend, yt-dlp auto-caption extraction, and keyframe-precise snapping DEFERRED to post-v2.4.0 (ADR 0026 do-not-rebuild, GPU forbidden, no transcript infra, release gate does NOT require clip-windowing). **PR 7 (model-resolution correctness — COMPLETE)** — `budget_east` preset canonicalized to OpenRouter `vendor/model` slugs (`xiaomi/mimo-v2.5`, `z-ai/glm-4.7-flash`, `qwen/qwen3-32b`, `google/gemini-2.5-flash`; resolves the job_9 bare-slug 404 + job_11 removed-model deprecation); `model_cache._load_cache` now force-refreshes when stale (7-day TTL was dead code); new `config/preflight.py` `preflight_agent_models()` force-refreshes the cache and validates every resolved agent slug against the live catalog at the `Orchestrator.run_pipeline`/`run_pipeline_from` chokepoint (covers CLI + dashboard + retry + resume; also `--dry-run`), failing fast before billing research credits; `refresh_model_cache` dedupes refresh attempts within 30s so offline runs degrade promptly (Codex P2#1 + P2#2); dead `llm/router.py` + its test deleted; `.env.example` canonical slugs + added `VISUAL_DIRECTOR_MODEL`. Remaining: **PR 8 (asset-qualification cost optimization — COMPLETE)** — three additive knobs cut the job_11 rejection storm without changing the qualification contract: (1) pre-VLM keyword-overlap skip gate in `asset_qualification._score_candidate` (reuses PR 6's `KeywordOverlapWindowSelector.relevance_score`; returns `None` without calling the VLM when overlap ≤ `_PREFILTER_MIN_OVERLAP=0.0`; cached candidates never re-decided); (2) frame-multiplier reduction via `AppSettings.frame_inspection_max_frames=48` + `frame_inspection_interval_sec=1.0` threaded into VD's `run_frame_inspection_pipeline` (~7.5× fewer VLM-bound frames, was 120 @ 0.5s); (3) RECOVER cap `MAX_RECOVERED_PER_BEAT=8` ranks recovered candidates by keyword-overlap relevance to the failing beat THEN slices, so one all-reject beat can't flood N fresh VLM inspections and the most relevant recovered candidate isn't lost to provider ordering (Codex P2#1); frame fields validated `ge=1`/`gt=0` so a bad env value fails fast instead of hanging `frame_sampler` (Codex P2#2). **PR 9 (face-detection — MediaPipe Tasks API migration — COMPLETE, GitHub PR #64)**; **PR 10 (ffmpeg_runner DEBUG-log quieting — this PR)** stops logging raw FFmpeg stderr line-by-line at DEBUG (the 536k-line job_12 flood), emits a one-line summary + tail-on-failure; extraction behavior unchanged. Remaining: PR 11 (multi-shot VD), PR 12 (release gate + golden-set → v2.4.0 bump). Plans: `.claude/plans/pr-7-model-resolution.plan.md`, `.claude/plans/pr-8-qualification-cost.plan.md`. 2053 offline tests pass, 18 deselected, ruff clean, 93% coverage.
- **Phase 27 / ADR 0030 (Inter-Agent Contract Gates — IMPLEMENTING; FIX-1 COMPLETE PR #84/#85/#86, FIX-6 COMPLETE):** job_18 (first fully-completed ElevenLabs job) produced an **unpostable** video. Root cause = a SINGLE load-bearing defect cascading through 5 blind-trust layers: Scriptwriter (`qwen/qwen3-32b`) emitted `narrative_structure` `word_range` covering only words **0–23 of 76** (`_validate_output` checks word-count + emoji, never coverage; `_normalize_narrative_structure` only backfills missing fields) → `build_canonical_timeline` silently stretched the last beat into a **25.17 s mega-beat** → Visual Director planned one wrong-artist scene (Jennifer Coppen for the Sarwendah beat; "accept" = numeric threshold ≥0.60, no entity binding) → Composer `-shortest` cut the last **~2.6 s** ("…like dan share"; visual 32.7 s < audio 35.3 s) → Reviewer total-duration-only `_check_av_sync` PASSED (structurally defeated by `-shortest` equalization) → repair re-derived the timeline from the SAME broken `narrative_structure` → job "completed" garbage (~60 % static: one image ~8 s, near-black "KOMEN DI BAWAH!" card ~24 s). Confirmed via `scripts/diagnose_av_drift.py data/outputs/job_18` + frame contact sheet + AI-vision + a 6-agent research workflow (reference pipelines `MoneyPrinterTurbo-Extended` / `claude-auto-tok` + production short-form tools). **Decision (research-validated): KEEP the 7-agent chain + audio-first beat-driven architecture; ADD deterministic contract gates at every inter-agent boundary + fix the repair router + remove `-shortest`. NOT a restructure** — MoneyPrinterTurbo's opaque-string topology REJECTED (would discard the richer beat-driven contract, which is AHEAD of per-sentence tools and is NOT the job_18 problem). **ADR 0030 amends ADR 0026's no-rebuild default FOR OUTPUT-QUALITY WORK ONLY** (product owner has explicitly lifted the MVP/no-rebuild constraint for output-quality fixes — new gates + new rejection rules are now in scope; still no new agent, no state-machine change, no topology change). Planned gates (SRS FR-74..FR-80, PRD PR-38..PR-44, Design §19/§20): **FIX-1 G7 GateNarrativeCoverage** (assert `word_range` union == `[0, word_count-1]`, contiguous, in-bounds; in-place repair for tail <5 % else force Scriptwriter regen) — THE load-bearing fix; **FIX-6** timeline UNCOVERED_TAIL detection + MAX-beat cap (12 s); **FIX-2 audio-as-master** (drop `-shortest` → `-t voiceover_duration`, pre-render pad visual ≥ audio, G9.5 visual-coverage gate, G10 `AUDIO_NOT_TRUNCATED` re-probe; MoneyPrinterTurbo policy adopted w/o its topology); **FIX-3 entity-binding** at shared `candidate_semantic_ranker` chokepoint (`WRONG_ENTITY` rule — `subject_name` vs beat `spoken_point`+`main_entities`, fuzzy for aliases; VLM `subject_name` required, missing ⇒ revise; `person_match` 0.8→0.6; MAX-scene cap); **FIX-5 repair-router root-cause routing** (route by failure REASON; force narrative regen on coverage re-fail; bounded `MAX_REPAIR_CYCLES` + terminal fail — never "complete" garbage; voiceover-text-diff skip); **FIX-4 Reviewer per-scene** (entity-vs-beat + frozen-frame/max-dwell + audio-not-truncated, extends `_check_av_sync` past the total-duration scalar); **FIX-7 engagement gates** (visual-change-density, hook-on-beat-0, duration-band 21–42 s, monotony guard; WARN+repair not pipeline-death). **DEFERRED Phase 27+:** CLIP image-text relevance ranking; multimodal "watch the rendered video" Reviewer. Ship order: FIX-1 → 6 → 2 → 3 → 5 → 4 → 7, each its own `phase/27-fixN-<slug>` branch + PR + SonarCloud(0 new issues)+Codex(👍)+`--merge`. **FIX-1 COMPLETE (PR #84/#85/#86 — G7 GateNarrativeCoverage + atomic mark-scriptwriter-failed-on-g7). FIX-6 COMPLETE (this PR — timeline UNCOVERED_TAIL + MAX-beat cap, backstop for G7).** Docs updated: ADR `docs/adr/0030-inter-agent-contract-gates.md`, plan `docs/plans/2026-06-29-inter-agent-contract-gates-tiktok-quality.md` (resume target with per-fix acceptance gates), CHANGELOG/README/SRS 3.4/PRD 3.4/technical_design 5.4/requirements_traceability 4.4. **Pre-PR checklist unchanged:** `.venv/bin/python3 -m pytest -m "not external and not integration" -q` + cov ≥93% + ruff + CHANGELOG + spec docs + Sonar 0-new-issues (verify via `sonarcloud.io/api/issues/search?componentKeys=guyinwonder168_clipper-agency&pullRequest=N&statuses=OPEN,CONFIRMED`) + Codex 👍. Use the workflow-first pattern (Workflow tool: impl + read-only audit + ECC `python-reviewer`/`silent-failure-hunter`) per fix.
- All 1210+ offline tests pass (2 pre-existing `integration`-marked tests deselected — `test_full_pipeline_smoke` requires FFmpeg + paid API keys, 1 other requires API keys). 93%+ test coverage. 7 agents built + Orchestrator engine + CLI interface + Web dashboard + data-driven config/prompt files + Docker deployment + pydantic-settings .env config system + structured logging + per-agent model config + test-agent CLI + configurable TTS provider (ElevenLabs/Gemini TTS/Fish Audio fallback) + artifact workspace contract + job debug dashboard/CLI + job manifest + gated pipeline hard-fail enforcement + agent state DB transitions + retry/resume/cache-reuse via dashboard/CLI + CSRF-protected retry/resume routes + FFmpeg preflight diagnostics + media probing + scene validation/normalization (30fps target, Ken Burns zoompan for images) + clip provenance tracking + generated card fallback (Pillow) + G10 deterministic validation + fixed-contract packager (S6549 safe) + template-driven rendering engine (YAML templates, 3 adapters, FFmpeg filter chains with fade/crossfade transitions, drawtext captions, Pillow thumbnails) + Composer template routing with diagnostics + E2E pipeline bugfixes (voice producer partial completion, Gemini TTS 429 backoff, SAR normalization, agent failure status checks for voice_producer/visual_director/composer, _fail_agent deduplication) + LLM-driven Visual Director (compact research data, per-scene visual planning, 3-tier image fallback Pexels→Firecrawl→gradient, text cards with relevant images, **enhanced with video production expertise — FPS rules, pacing, treatment selection, transitions, default treatment routing**) + treatment template YAML definitions (9 treatments, 5 transitions) + prompt files .txt→.md + search_photos() for PexelsService + prompt deduplication + NicheConfig schema cleanup (content_angle, search_terms, max_hashtags) + niche wiring through orchestrator + safety_rules from niche YAML + CLI niche validation + individual niche fields as prompt vars + repetitive failure patterns doc (docs/repetitive-failure-patterns.md) + **audio-first continuous voiceover architecture (v2.0.0)**: Segment Producer (researcher renamed with 5 sub-roles: fact checker, viral analyst, clip scout, story producer, edit planner), continuous voiceover via single TTS call with ElevenLabs `/with-timestamps` word-level timestamps, beat-driven Visual Director with `visual_must_show`/`visual_must_not_show` rules, smart scene trimming with ffprobe keyframe boundary detection, keyword captions (max 6 words, beat-aligned), sequential Voice→Visual pipeline, enhanced Reviewer with 4 programmatic quality checks (AV sync, caption quality, fact safety, narrative structure), shared schema contract via `config/schema.py` (11 Pydantic models). 93% test coverage.

## Python Commands

- **Use the project virtualenv first** for all Python commands when `.venv/` exists.
- Preferred command prefix in this repo: `.venv/bin/python3 -m ...`
- Fall back to system `python3 -m ...` only when `.venv/` does not exist.
- This prevents false failures from missing dependencies in the system interpreter, such as `ModuleNotFoundError: flask_wtf` when the package is already installed in `.venv/`.
- Use `python3` for all Python commands when not using the project virtualenv.
- Do **not** use `python`; this environment may not provide it.
- Prefer module execution when applicable:

```bash
.venv/bin/python3 -m pytest          # run all tests
.venv/bin/python3 -m pytest tests/path/test_file.py::test_name -v  # single test
.venv/bin/python3 -m pip install -r requirements.txt
.venv/bin/python3 -m clipper_agency  # run the app
```

## Shell Command Notes

- The project path contains a space: `clipper agency`.
- Always quote paths when needed.
- Prefer setting the command working directory instead of using `cd` in commands.

## Security Lesson: Sonar pythonsecurity:S6549 Filesystem Oracle / Path Traversal

Phase 14 hit a difficult SonarCloud `pythonsecurity:S6549` issue: “Change this code to not construct the path from user-controlled data.” Treat this as a design problem, not a warning to suppress.

What failed:
- ❌ `# NOSONAR` suppression — hides the warning but does not fix the vulnerability.
- ❌ `os.path.realpath()`, `os.path.abspath()`, `os.path.normpath()`, and `os.path.isfile()` around a caller-provided path — safer at runtime, but Sonar still sees user-controlled data reaching filesystem sinks.
- ❌ Passing dynamic `video_path` into validation/probing helpers, even when wrapped by a sandbox helper — still looked like tainted input reaching file I/O.

What succeeded:
- ✅ Follow OWASP path traversal guidance: prefer no user input for filesystem calls; use known-good application-owned paths.
- ✅ Use fixed contract paths for pipeline artifacts. For final packaging, Composer owns `output_dir/job_{job_id}/video.mp4`; Packager validates/probes that path only and does not open arbitrary caller-provided video paths.
- ✅ For unavoidable relative artifact paths, use `pathlib.Path.resolve()` plus `relative_to()` containment in `clipper_agency/core/safe_paths.py`, then pass the resolved path to shell-free subprocess calls.
- ✅ Add regression tests proving outside paths are ignored/rejected and fixed job-owned paths are used.
- ✅ Re-run full offline tests and wait for both GitHub `SonarCloud` and `SonarCloud Code Analysis` checks to pass before merging.

## Engineering Lessons (Phases 12–17)

Ten recurring failure patterns documented in `docs/repetitive-failure-patterns.md`. The condensed rules below must prevent re-introduction.

### Agent Pipeline Integrity
- ❌ Never advance pipeline after a failed agent. Check `output.get("status")=="failed"` BEFORE `_complete_agent()`.
- ❌ Never copy-paste agent failure handlers. Extract `_fail_agent()`, reuse everywhere.
- ✅ Every agent's output must be validated before next agent consumes it (normalization boundary).

### Error Handling & API Calls
- ❌ Never silently default to unsafe state on exceptions. Fail hard with `{"status":"failed","reason":...}`.
- ✅ Every external API call needs retry + exponential backoff + jitter. Non-negotiable.

### Configuration & Retry
- ✅ Config loaded at pipeline start must be frozen. Retries read `config_snapshot`, not disk.

### Code Quality Guardrails
- ❌ Extract helpers before `cognitive_complexity > 15`.
- ❌ Bundle >5 scalar params into dict/dataclass.
- ❌ Error string used >1x = module constant.

### Pre-PR Checklist
Before `git push`: `.venv/bin/python3 -m pytest -m "not external and not integration" -q` (all pass); `--cov=clipper_agency --cov-report=term-missing` (≥93%). Fix uncovered spots. **Update `CHANGELOG.md`** (add entry under `[Unreleased]`). **Update spec docs** (`docs/PRD.md`, `docs/SRS.md`, `docs/technical_design.md`, `docs/requirements_traceability.md`) if code changes affect requirements, architecture, or traceability. Wait for SonarCloud ✅ **with zero new issues** before merging.

## Git Branching & PR Workflow

**Never push directly to `master`.** Every phase of work must go through a branch + PR + SonarCloud gate.

```
                         Create     Push     Open      SonarCloud   Codex       Merge    Delete
 Phase N Start ────────► branch ──► push ──► PR ────► pass+0 iss? ─► resolved? ──► PR ────► branch
                                    │         │         │           │             │
                                    │         │         │           └─ address ───┘
                                    │         │         └─ fix ────┘
                                    │         │
                                    └─────────┘
```

### Per-Phase Workflow

1. **Create feature branch** — `phase/N-short-description`
   ```bash
   git checkout -b phase/N-short-description
   ```
2. **Implement** — TDD: tests first, code, commit incrementally. Multiple commits per phase are fine.
   - **Update `CHANGELOG.md`** — add an entry under `[Unreleased]` describing the change (what was added/fixed/changed).
   - **Update spec docs if affected** — if code changes affect product requirements, software requirements, architecture, or traceability, update the corresponding docs:
     - `docs/PRD.md` — product requirements changed/added
     - `docs/SRS.md` — functional/non-functional requirements changed/added
     - `docs/technical_design.md` — architecture, agent roles, pipeline, or modules changed
     - `docs/requirements_traceability.md` — new facts, edge cases, or traceability mappings
   - These doc updates go in the **same PR** as the code changes, not after merge.
3. **Push branch** — `git push -u origin phase/N-short-description`
4. **Create PR** — via `gh pr create`:
   ```bash
   gh pr create --base master --title "Phase N: Feature Title" --body "Implements feature per the implementation plan."
   ```
5. **Wait for SonarCloud** — PR must show ✅ green Quality Gate **AND zero new issues**.
   - **Quality Gate passing is necessary but NOT sufficient.** The gate can pass while new issues (bugs, vulnerabilities, code smells, cognitive complexity violations, unused code) are still present.
   - If the Quality Gate fails, fix issues on the branch, push again, and wait for re-check.
   - If the Quality Gate passes but **new issues** exist, fix them on the branch, push again, and wait for re-check. Repeat until zero new issues.
   - **Do NOT merge until SonarCloud passes with zero new issues.**
6. **Wait for Codex review** — check PR for Codex (ChatGPT) review comments.
   - **Codex 👍 = pass.** A thumbs-up (👍) reaction from `chatgpt-codex-connector[bot]` on the PR — with NO written review comments — IS the Codex pass signal. It is a reaction (not a formal `APPROVED` review), so GitHub's `reviewDecision` stays empty and `reviews[]` is empty; that is expected by design and does NOT block the merge. You are cleared to continue/merge.
   - If Codex review has NOT started yet (no 👍 AND no comments posted), **wait** — do not merge until Codex has reviewed.
   - If Codex posted written comments, evaluate each one (P0/P1 must fix, P2 should fix, P3 optional). Address or push back with reasoning.
   - **Do NOT merge until all Codex comments are resolved** (fixed or acknowledged with a reply) — or until Codex posts a 👍 with no comments.
7. **Merge** — **without squashing** (retain commit history):
   ```bash
   gh pr merge phase/N-short-description --merge
   ```
   - Never squash or rebase-merge. Use `--merge` (true merge commit).
8. **Delete branch** — after merge succeeds:
   ```bash
   git branch -d phase/N-short-description           # local
   git push origin --delete phase/N-short-description  # remote
   git checkout master && git pull origin master
   ```
9. **Update docs** — update `AGENTS.md` (Repository State) and the plan document to reflect the completed phase.
10. **Start next phase** — create new branch from updated master.

### Commit Message Convention

```
feat: brief description of change
fix: brief description of fix
docs: brief description of doc change
test: brief description of test change
refactor: brief description of refactor
```

### Branch Naming

```
phase/0-scaffolding     phase/4-agent-framework   phase/8-config-prompts
phase/1-config          phase/5-agents            phase/9-docker
phase/2-database        phase/6-orchestrator      phase/10-env-config-fix
phase/3-services        phase/7-dashboard         phase/11-logging-model-config
```

### Rules

- ❌ NEVER push directly to `master`.
- ❌ NEVER merge a PR before SonarCloud passes with zero new issues.
- ❌ NEVER merge a PR before Codex review is resolved (wait if not started yet). A Codex 👍 (thumbs-up reaction) with no written comments IS the resolved/pass state — `reviewDecision`/`reviews[]` stay empty by design; cleared to merge.
- ❌ NEVER merge a PR without updating `CHANGELOG.md`.
- ❌ NEVER squash or rebase-merge — always use `--merge` (true merge commit).
- ✅ Always delete the feature branch after successful merge.
- ✅ Always pull master after deleting branch to stay in sync.
- ❌ Never over-engineer the code. Always follow the KISS, YAGNI, and DRY principles in every analytical decision.

## Architecture (MVP)

Agentic pipeline coordinated by a DB-driven orchestrator (audio-first continuous voiceover):

```
Topic → Safety → Segment Producer → Scriptwriter → Voice Producer → Visual Director → Composer → Reviewer → Output
  G1      G2      G3/G4/G5       G6              G7                G8                G9        G10
```

- 7 agents, 10 gates (G1-G10), state persisted in SQLite.
- Agents communicate via DB state — no direct agent-to-agent calls.
- **Audio-first pipeline**: voiceover generated first (single TTS call), visuals fitted to audio timeline.
- **Beat-driven architecture**: story_beats + word-level timestamps drive visual selection and composition.
- **Sequential voice→visual**: Voice Producer must complete before Visual Director starts.
- Output package: `video.mp4` + `caption.txt` + `thumbnail.png` + `metadata.json`.
- **MVP scope:** 1 client, 1 TikTok account, Indonesian artist infotainment niche.

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language  | Python 3.11+ |
| Video     | FFmpeg 5.0+ (CPU-only, no GPU) |
| Database  | SQLite (WAL mode, advisory locks) |
| LLM       | OpenRouter API (multi-model routing) |
| Voice     | ElevenLabs / Fish Audio (auto-detect) |
| Media     | yt-dlp (primary), Pexels (fallback) |
| Research  | ScrapeCreators + Firecrawl |
| Auth      | Basic auth, 2 groups (privileged, creative/ops) |

## Documentation Structure

```
docs/
├── PRD.md                          # Product requirements (v2.3)
├── SRS.md                          # Software requirements spec (v2.3)
├── technical_design.md             # Architecture & design (v3.3)
├── requirements_traceability.md    # Traceability matrix (v2.3)
├── social-media-api-comparison.md  # Research output
├── adr/                            # Architecture Decision Records
│   ├── 0001-use-python-ffmpeg.md
│   ├── 0002-use-agentic-pipeline.md
│   └── 0003-use-ytdlp-as-mvp-media-layer.md
├── design/
│   └── evolution_plan.md           # Future-stage details (out of MVP)
├── plans/                          # Implementation plans
└── old/                            # Archived previous versions
```

**Key doc rule:** Keep product requirements, technical specs, and architecture in **separate** documents — never merge them.

### ADR Format

When making a significant decision, create an ADR in `docs/adr/NNNN-title.md` following the existing format: Context → Decision → Alternatives Considered → Consequences.

## Directories & Conventions

| Path | Purpose |
|------|---------|
| `refference/` | External reference projects (note: misspelled dir name, intentional) |
| `.firecrawl/` | Auto-generated Firecrawl research outputs — do not edit |
| `.memsearch/` | Auto-generated memsearch data directory |

- No `opencode.json` exists yet — this repo has no OpenCode-local config.

## Testing Expectations

Once code exists:
- Unit tests live in `tests/` mirroring package structure.
- Integration tests require: FFmpeg 5.0+, SQLite, API keys for OpenRouter/ElevenLabs/Pexels/ScrapeCreators/Firecrawl.
- Tests that call external APIs must use `pytest` markers to allow offline runs:
  ```bash
  .venv/bin/python3 -m pytest -m "not external and not integration" -q  # skip API-dependent + integration tests (989 pass, 2 deselected)
  ```

## Niche & Template Config

Content rules (language, tone, platform) are **data-driven, not hardcoded**:
- Niches: `niches/*.yaml`
- Templates: `templates/*.yaml`
- Changing niche or template should never require code changes.

## Codegraph MCP

use Codegraph MCP to understand code base better.
- If possible use Codegraph compare to Grep the file directly