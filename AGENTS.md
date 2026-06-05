# AGENTS.md

Project-specific instructions for AI agents working in this repository.

## Repository State

- **Greenfield project** — early implementation phase (Phases 0-19 complete).
- All 783 offline tests pass (2 pre-existing `integration`-marked tests deselected — `test_full_pipeline_smoke` requires FFmpeg + paid API keys, 1 other requires API keys). 7 agents built + Orchestrator engine + CLI interface + Web dashboard + data-driven config/prompt files + Docker deployment + pydantic-settings .env config system + structured logging + per-agent model config + test-agent CLI + configurable TTS provider (ElevenLabs/Gemini TTS/Fish Audio fallback) + artifact workspace contract + job debug dashboard/CLI + job manifest + gated pipeline hard-fail enforcement + agent state DB transitions + retry/resume/cache-reuse via dashboard/CLI + CSRF-protected retry/resume routes + FFmpeg preflight diagnostics + media probing + scene validation/normalization (30fps target, Ken Burns zoompan for images) + clip provenance tracking + generated card fallback (Pillow) + G10 deterministic validation + fixed-contract packager (S6549 safe) + template-driven rendering engine (YAML templates, 3 adapters, FFmpeg filter chains with fade/crossfade transitions, drawtext captions, Pillow thumbnails) + Composer template routing with diagnostics + E2E pipeline bugfixes (voice producer partial completion, Gemini TTS 429 backoff, SAR normalization, agent failure status checks for voice_producer/visual_director/composer, _fail_agent deduplication) + LLM-driven Visual Director (compact research data, per-scene visual planning, 3-tier image fallback Pexels→Firecrawl→gradient, text cards with relevant images, **enhanced with video production expertise — FPS rules, pacing, treatment selection, transitions, default treatment routing**) + treatment template YAML definitions (9 treatments, 5 transitions) + prompt files .txt→.md + search_photos() for PexelsService + prompt deduplication + NicheConfig schema cleanup (content_angle, search_terms, max_hashtags) + niche wiring through orchestrator + safety_rules from niche YAML + CLI niche validation + individual niche fields as prompt vars + repetitive failure patterns doc (docs/repetitive-failure-patterns.md) + 93% test coverage.

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
Before `git push`: `.venv/bin/python3 -m pytest -m "not external and not integration" -q` (all pass); `--cov=clipper_agency --cov-report=term-missing` (≥93%). Fix uncovered spots. Wait for SonarCloud ✅ before merging.

## Git Branching & PR Workflow

**Never push directly to `master`.** Every phase of work must go through a branch + PR + SonarCloud gate.

```
                         Create     Push     Open      SonarCloud   Merge    Delete
 Phase N Start ────────► branch ──► push ──► PR ────► passes? ──► PR ────► branch
                                    │         │         │           │
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
3. **Push branch** — `git push -u origin phase/N-short-description`
4. **Create PR** — via `gh pr create`:
   ```bash
   gh pr create --base master --title "Phase N: Feature Title" --body "Implements feature per the implementation plan."
   ```
5. **Wait for SonarCloud** — PR must show ✅ green from SonarCloud Quality Gate.
   - If SonarCloud fails (bugs, vulnerabilities, code smells), fix issues on the branch, push again, and wait for re-check.
   - **Do NOT merge until SonarCloud passes.**
6. **Merge** — **without squashing** (retain commit history):
   ```bash
   gh pr merge phase/N-short-description --merge
   ```
   - Never squash or rebase-merge. Use `--merge` (true merge commit).
7. **Delete branch** — after merge succeeds:
   ```bash
   git branch -d phase/N-short-description           # local
   git push origin --delete phase/N-short-description  # remote
   git checkout master && git pull origin master
   ```
8. **Update docs** — update `AGENTS.md` (Repository State) and the plan document to reflect the completed phase.
9. **Start next phase** — create new branch from updated master.

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
- ❌ NEVER merge a PR before SonarCloud passes.
- ❌ NEVER squash or rebase-merge — always use `--merge` (true merge commit).
- ✅ Always delete the feature branch after successful merge.
- ✅ Always pull master after deleting branch to stay in sync.
- ❌ Never over-engineer the code. Always follow the KISS, YAGNI, and DRY principles in every analytical decision.

## Architecture (MVP)

Agentic pipeline coordinated by a DB-driven orchestrator:

```
Topic → Safety → Researcher → Scriptwriter → Voice Producer → Visual Director → Composer → Reviewer → Output
  G1      G2      G3/G4/G5       G6              G7                G8                G9        G10
```

- 7 agents, 10 gates (G1-G10), state persisted in SQLite.
- Agents communicate via DB state — no direct agent-to-agent calls.
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
  .venv/bin/python3 -m pytest -m "not external and not integration" -q  # skip API-dependent + integration tests (568 pass, 2 deselected)
  ```

## Niche & Template Config

Content rules (language, tone, platform) are **data-driven, not hardcoded**:
- Niches: `niches/*.yaml`
- Templates: `templates/*.yaml`
- Changing niche or template should never require code changes.
