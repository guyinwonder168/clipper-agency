# Phase 15a Batch Execution Plan ✅ COMPLETED

> **Status:** All 3 PRs merged to master. 17 tasks executed across 3 sequential PRs with parallel batches.

> Companion to `docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md`.  
> Groups the 17 TDD tasks into parallel batches per PR to reduce sequential wall-clock time.

**Goal:** Execute Phase 15a template rendering in 3 sequential PRs, each with internal parallel batches.

## Skills & Context Required Per Batch

All CoderAgents dispatched in this plan MUST load these skills before starting:

| Skill | When needed | Purpose |
|-------|-------------|---------|
| `test-driven-development` | ALL CoderAgent dispatches (T1–T4, T6–T9, T11–T13) | Enforces TDD red-green-refactor flow |
| `verification-before-completion` | ALL batches | No completion claim without fresh test evidence |
| `dispatching-parallel-agents` | Orchestrator (coordinating batches) | Parallel dispatch pattern for independent tasks |
| `code-quality.md` context | ALL code tasks | Modular, functional, immutability, small functions |
| `test-coverage.md` context | ALL test tasks | AAA pattern, deterministic/independent/fast tests |
| `documentation.md` context | T14, T15, T16 only | Concise, high-signal docs, keep sections separate |

**Skill loading in CoderAgent prompts**: Every CoderAgent prompt below includes an explicit `SKILLS REQUIRED` section listing what to load before starting work.

---

## PR 1 — Template Foundation

Branch: `phase/15a-template-foundation`

```
                    T1 (templates.py)
                       │
      ┌────────────────┴────────────────┐
      │                                 │
   T3 (primitives.py)            T4 (thumbnails.py)
      │                                 │
      └────────────────┬────────────────┘
                       │
                  T5 (verification + PR)
```

### Dependencies

| Task | File(s) created | Depends on |
|------|----------------|------------|
| T1 | `clipper_agency/rendering/templates.py`, `tests/test_rendering_templates.py` | — |
| T2 | `clipper_agency/rendering/contracts.py`, `tests/test_rendering_contracts.py` | — |
| T3 | `clipper_agency/rendering/primitives.py`, `tests/test_rendering_primitives.py` | T1 + T2 |
| T4 | `clipper_agency/rendering/thumbnails.py`, `tests/test_rendering_thumbnails.py` | T2 |
| T5 | (verification only) | T1 + T2 + T3 + T4 |

### Batch 1.1 — T1 + T2 (parallel, independent files) ✅

**Dispatch two CoderAgents simultaneously:**

#### Agent A — T1: Template Loader

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development  (enforce red-green-refactor TDD flow)
    - verification-before-completion  (no completion claim without fresh test evidence)
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
  TASK REFERENCE:
    - docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md (Task 1)
  
  Execute Task 1 (template loader) from the implementation plan exactly.
  Branch: phase/15a-template-foundation
  
  Summary of what to build:
  - Create clipper_agency/rendering/__init__.py (empty)
  - Create clipper_agency/rendering/templates.py with:
    - TemplateLoadError(ValueError)
    - TemplateLayout(BaseModel): resolution, background_color, title_font_size, subtitle_font_size, caption_position, caption_style, clip_duration
    - TemplateTransition(BaseModel): type, duration
    - RenderTemplateConfig(BaseModel): name, type, style, description, layout, transitions
    - load_render_template(template_name, templates_dir) -> RenderTemplateConfig
      * Validate name against ^[a-z][a-z0-9_]*$
      * Build path as templates_dir / f"{template_name}.yaml"
      * Use yaml.safe_load + model_validate
  - Create tests/test_rendering_templates.py with tests for valid config, unknown name, path-like name, missing file, invalid schema
  
  TDD flow:
  1. Write failing test → 2. Run to verify fail → 3. Implement → 4. Run to verify pass → 5. Commit
  
  Use .venv/bin/python3 -m pytest for all test runs.
  Commit message: "feat: add render template loader"
  
  Return: confirmation of commit hash, test count passing.
```

#### Agent B — T2: Render Contracts

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development  (enforce red-green-refactor TDD flow)
    - verification-before-completion  (no completion claim without fresh test evidence)
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
  TASK REFERENCE:
    - docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md (Task 2)
  
  Execute Task 2 (render contracts) from the implementation plan exactly.
  Branch: phase/15a-template-foundation
  
  Summary of what to build:
  - Create clipper_agency/rendering/contracts.py with:
    - CaptionOverlay(text, start_seconds, end_seconds, position="bottom", style="default")
    - VisualOverlay(text, kind="lower_third", start_seconds=0.0, end_seconds=None)
    - RenderScene(source_path, duration_seconds, captions=[], overlays=[], transition="cut")
    - ThumbnailConfig(title, subtitle=None, template_name, output_path=None)
    - RenderPlan(template_name, scenes, thumbnail=None, metadata={})
    - RenderResult(video_path, thumbnail_path, render_plan_path=None, diagnostics_dir=None)
    All with Pydantic validation (positive durations, non-negative times, end > start)
  - Create tests/test_rendering_contracts.py with tests for serialization, boundary validation, negative time rejection
  
  TDD flow:
  1. Write failing test → 2. Run to verify fail → 3. Implement → 4. Run to verify pass → 5. Commit
  
  Use .venv/bin/python3 -m pytest for all test runs.
  Commit message: "feat: add render contract models"
  
  Return: confirmation of commit hash, test count passing.
```

**Wait for BOTH Agent A and Agent B to complete before proceeding.**

---

### Batch 1.2 — T3 + T4 (parallel, independent files) ✅

**Dispatch two CoderAgents simultaneously:**

#### Agent C — T3: Primitives

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development  (enforce red-green-refactor TDD flow)
    - verification-before-completion  (no completion claim without fresh test evidence)
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
  TASK REFERENCE:
    - docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md (Task 3)
  
  Execute Task 3 (primitives) from the implementation plan exactly.
  Branch: phase/15a-template-foundation
  Note: Tasks 1 and 2 are already committed on this branch. templates.py and contracts.py exist.
  
  Summary of what to build:
  - Create clipper_agency/rendering/primitives.py with pure functions:
    - escape_drawtext(text: str) -> str (escape FFmpeg drawtext special chars)
    - make_caption_overlays(text, duration_seconds, words_per_caption=5, position="bottom", style="default") -> list[CaptionOverlay]
    - make_lower_third(text, duration_seconds) -> VisualOverlay
    - transition_for_template(template: RenderTemplateConfig) -> str
    All deterministic, no side effects.
  - Create tests/test_rendering_primitives.py
  
  TDD flow:
  1. Write failing test → 2. Run to verify fail → 3. Implement → 4. Run to verify pass → 5. Commit
  
  Use .venv/bin/python3 -m pytest for all test runs.
  Commit message: "feat: add render primitives"
  
  Return: confirmation of commit hash, test count passing.
```

#### Agent D — T4: Thumbnails

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development  (enforce red-green-refactor TDD flow)
    - verification-before-completion  (no completion claim without fresh test evidence)
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
  TASK REFERENCE:
    - docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md (Task 4)
  
  Execute Task 4 (thumbnails) from that plan exactly.
  Branch: phase/15a-template-foundation
  Note: Tasks 1 and 2 are already committed on this branch.
  
  Summary of what to build:
  - Create clipper_agency/rendering/thumbnails.py with:
    - generate_template_thumbnail(config: ThumbnailConfig) -> Path
      * Uses existing CardGenerator from clipper_agency.core.card_generator
      * Chooses card type by template name
      * Creates parent directories
  - Create tests/test_rendering_thumbnails.py
  
  TDD flow:
  1. Write failing test → 2. Run to verify fail → 3. Implement → 4. Run to verify pass → 5. Commit
  
  Use .venv/bin/python3 -m pytest for all test runs.
  Commit message: "feat: add template thumbnail generation"
  
  Return: confirmation of commit hash, test count passing.
```

**Wait for BOTH Agent C and Agent D to complete before proceeding.**

---

### Batch 1.3 — T5: Verification + PR ✅

Run locally:

```bash
# Step 1: Targeted rendering tests
.venv/bin/python3 -m pytest \
  tests/test_rendering_templates.py \
  tests/test_rendering_contracts.py \
  tests/test_rendering_primitives.py \
  tests/test_rendering_thumbnails.py \
  -v

# Step 2: Legacy regression
.venv/bin/python3 -m pytest tests/test_card_generator.py tests/test_config_loader.py -v

# Step 3: Full offline suite
.venv/bin/python3 -m pytest -m "not external and not integration" -q

# Step 4: Create PR
git status --short
git log --oneline -10
gh pr create --base master --title "Phase 15a: Template rendering foundation" \
  --body "Adds strict template loading, render contracts, shared primitives, and template thumbnail generation."
```

Expected: all offline tests pass → PR open. Merge after SonarCloud green.

---

## PR 2 — Template Adapters + Standalone Render

Branch: `phase/15a-template-adapters` (from updated `master` after PR 1 merge)

```
      T6 (news_card adapter) ────┐
      T7 (b_roll adapter)  ──────┼─── all parallel, separate files
      T8 (rapid_update adapter) ─┘
                       │
                  T9 (engine)
                       │
                 T10 (fixtures + PR)
```

### Dependencies

| Task | File(s) | Depends on |
|------|---------|------------|
| T6 | `renderers/news_card.py`, `tests/test_rendering_adapters.py` (create) | T1 + T2 (from PR 1) |
| T7 | `renderers/b_roll_narration.py`, append to `tests/test_rendering_adapters.py` | T1 + T2 |
| T8 | `renderers/rapid_update.py`, append to `tests/test_rendering_adapters.py` | T1 + T2 |
| T9 | `clipper_agency/rendering/engine.py`, `tests/test_rendering_engine.py` | T1 + T2 (contracts/models) |
| T10 | fixture tests in `tests/test_rendering_engine.py` | T6 + T7 + T8 + T9 |

### Batch 2.1 — T6 + T7 + T8 (parallel, 3 adapters) ✅

**Dispatch three CoderAgents simultaneously.** Each creates its own adapter file and appends its tests to `tests/test_rendering_adapters.py`. All share the same skill/context requirements:

```
SKILLS REQUIRED (load before starting):
  - test-driven-development
  - verification-before-completion
CONTEXT REQUIRED (Read tool before coding):
  - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
  - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
TASK REFERENCE:
  - docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md
Branch: phase/15a-template-adapters
```

| Agent | Task | File to create | Test to create/append |
|-------|------|---------------|----------------------|
| Agent E | T6 — News Card adapter | `clipper_agency/rendering/renderers/__init__.py` + `news_card.py` | `tests/test_rendering_adapters.py` (create) |
| Agent F | T7 — B-Roll adapter | `clipper_agency/rendering/renderers/b_roll_narration.py` | `tests/test_rendering_adapters.py` (append) |
| Agent G | T8 — Rapid Update adapter | `clipper_agency/rendering/renderers/rapid_update.py` | `tests/test_rendering_adapters.py` (append) |

Agent E creates `renderers/__init__.py`; Agents F and G only create their adapter files.

**Wait for ALL three agents to complete before proceeding.**

### Batch 2.2 — T9: Engine ✅

Single CoderAgent. Same skill/context requirements as above.

```
Prompt:
  SKILLS REQUIRED: test-driven-development, verification-before-completion
  CONTEXT REQUIRED: code-quality.md, test-coverage.md
  TASK REFERENCE: docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md (Task 9)
  Branch: phase/15a-template-adapters
  Note: All adapters (T6-T8) are already committed on this branch.
  
  Create clipper_agency/rendering/engine.py and tests/test_rendering_engine.py.
  Follow TDD flow exactly.
  Return: commit hash, test count.
```

### Batch 2.3 — T10: Fixtures + Verification + PR ✅

Run locally (orchestrator role — load `verification-before-completion` before claiming success):

```bash
# Verify targeted tests
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py tests/test_rendering_engine.py -v

# Offline suite
.venv/bin/python3 -m pytest -m "not external and not integration" -q

# Create PR
gh pr create --base master --title "Phase 15a: Template adapters and render engine" \
  --body "News Card, B-Roll Narration, and Rapid Update adapters with standalone FFmpeg render engine and deterministic fixture tests."
```

---

## PR 3 — Composer Integration + Documentation

Branch: `phase/15a-composer-template-integration` (from updated `master` after PR 2 merge)

```
                 T11 (Composer routing)
                        │
                  T12 (diagnostics)
                        │
  ┌──────────┬──────────┼──────────┬──────────┐
  │          │          │          │          │
  T13        T14        T15        T16
  (metadata) (docs)     (ADR)      (traceability)
  │          │          │          │
  └──────────┴──────────┴──────────┴──────────┘
                       │
                 T17 (verification + PR)
```

### Dependencies

| Task | File(s) | Depends on |
|------|---------|------------|
| T11 | modify `composer.py`, append to `test_agents_composer.py` | — (PR 1+2 models available) |
| T12 | modify `composer.py`, append to `test_composer.py` | T11 |
| T13 | modify `orchestrator/engine.py` ± `packager.py`, test packager | T12 |
| T14 | modify docs/PRD.md, SRS.md, technical_design.md, roadmap, task-plan | T11 |
| T15 | create `docs/adr/0013-*.md` | T11 |
| T16 | modify `docs/requirements_traceability.md` | T11 |
| T17 | full verification + PR | T11–T16 all |

### Batch 3.1 — T11: Composer routing ✅

Single CoderAgent.

```
Prompt:
  SKILLS REQUIRED: test-driven-development, verification-before-completion
  CONTEXT REQUIRED: code-quality.md, test-coverage.md
  TASK REFERENCE: docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md (Task 11)
  Branch: phase/15a-composer-template-integration
  
  Modify clipper_agency/agents/composer.py to route through template renderer when template_name is provided.
  Preserve existing no-template behavior.
  TDD flow exactly.
  Return: commit hash, test count.
```

### Batch 3.2 — T12: Diagnostics ✅

Single CoderAgent. Depends on T11.

```
Prompt:
  SKILLS REQUIRED: test-driven-development, verification-before-completion
  CONTEXT REQUIRED: code-quality.md, test-coverage.md
  TASK REFERENCE: docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md (Task 12)
  Branch: phase/15a-composer-template-integration
  Note: Task 11 is already committed.
  
  Persist template diagnostics under assets_cache/job_{id}/agents/composer/.
  TDD flow exactly.
  Return: commit hash, test count.
```

### Batch 3.3 — T13 + T14 + T15 + T16 (parallel, 4 docs/metadata tasks) ✅

Dispatch four agents simultaneously. All independent files, no conflicts. Different skill/context requirements:

| Agent | Task | Skills required | Context required | Action |
|-------|------|----------------|-----------------|--------|
| Agent H | T13 — Metadata | `test-driven-development`, `verification-before-completion` | `code-quality.md`, `test-coverage.md` | Modify orchestrator/engine.py, test packager metadata |
| Agent I | T14 — Docs | `verification-before-completion` | `documentation.md` | Update PRD, SRS, technical_design, roadmap, task-plan |
| Agent J | T15 — ADR | `verification-before-completion` | `documentation.md` | Create `docs/adr/0013-*.md` |
| Agent K | T16 — Traceability | `verification-before-completion` | `documentation.md` | Update `docs/requirements_traceability.md` |

All reference: `docs/plans/2026-05-29-phase-15a-template-rendering-implementation-plan.md`
Branch: `phase/15a-composer-template-integration`

**Wait for ALL four agents to complete before proceeding.**

### Batch 3.4 — T17: Verification + PR ✅

Run locally (orchestrator role — load `verification-before-completion` before claiming success):

```bash
# Targeted rendering tests
.venv/bin/python3 -m pytest tests/test_rendering_*.py -v

# Composer + packaging tests
.venv/bin/python3 -m pytest tests/test_composer.py tests/test_agents_composer.py tests/test_output_packager.py -v

# Offline suite
.venv/bin/python3 -m pytest -m "not external and not integration" -q

# Create PR
gh pr create --base master --title "Phase 15a: Composer template rendering integration" \
  --body "Integrates template-driven rendering into Composer, persists diagnostics, updates final metadata, and documents Phase 15a traceability."
```

---

## Summary

| PR | Batches | Parallel tasks | Skills loaded per CoderAgent |
|----|---------|----------------|------------------------------|
| PR 1 ✅ | 3 | T1+T2 → T3+T4 → T5 | `test-driven-development`, `verification-before-completion`, `code-quality.md`, `test-coverage.md` |
| PR 2 ✅ | 3 | T6+T7+T8 → T9 → T10 | same as PR 1 |
| PR 3 ✅ | 4 | T11 → T12 → T13+T14+T15+T16 → T17 | T11-T13: same as PR 1; T14-T16: `documentation.md` + `verification-before-completion` |
| **Total** | **10 batches** | up to 4 parallel | — |

Orchestrator (you, coordinating batches): loads `dispatching-parallel-agents` for dispatch pattern, `verification-before-completion` for each PR merge gate.

Each PR must merge before the next starts (SonarCloud gate). Total: 3 PRs × (batches + review latency).

> **Result:** All 3 PRs merged to master. 568 offline tests pass. SonarCloud QG green. Phase 15a complete.
