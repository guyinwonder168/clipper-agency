# SonarCloud 7-Issue Batch Fix Plan ✅ COMPLETED

> **Status:** All 7 issues fixed across PRs #18 (S6549), #19 (S1481), and #20 (S2077). SonarCloud QG green on master.

> Companion to the Phase 15a implementation. Fixes all 7 open SonarCloud issues (4 unique files + 1 config + 1 test) in one parallel batch.

**Goal:** Close all 7 open SonarCloud issues remaining after PR 2 merge (`056f743`) so master is SonarCloud-clean before PR 3 (Composer integration).

**Source:** https://sonarcloud.io/project/issues?issueStatuses=OPEN%2CCONFIRMED&sinceLeakPeriod=true&id=guyinwonder168_clipper-agency

---

## Skills & Context Required Per Batch

All CoderAgents dispatched in this plan MUST load these skills before starting:

| Skill | When needed | Purpose |
|-------|-------------|---------|
| `verification-before-completion` | ALL batches | No completion claim without fresh test evidence |
| `test-driven-development` | Agents 1–4 (code fixes) | TDD red-green flow where fixes touch production code |
| `code-quality.md` context | Agents 1–4 | Modular, functional, S6549-OWASP-safe patterns |
| `test-coverage.md` context | Agent 5 (test fix) | AAA pattern, deterministic tests |
| AGENTS.md S6549 lesson | Agents 2, 3 | Follow Phase 14 learned patterns (fixed-contract paths, `resolve()` + `relative_to()` containment) |

**Verification agent reference:** Load `verification-before-completion` before ANY success claim. Run `.venv/bin/python3 -m pytest -m "not external and not integration" -q`.

---

## The 7 Issues

| # | File | Line(s) | Rule | Severity | Type | Description |
|---|------|---------|------|----------|------|-------------|
| 1 | `clipper_agency/core/ytdlp.py` | L45 | `pythonsecurity:S2077` | High | Hotspot | User-controlled URL reaching `subprocess.run()` |
| 2 | `clipper_agency/output/packager.py` | L72, L82, L95 | `pythonsecurity:S6549` | Critical | Vulnerability | Path constructed from user-controlled data (3 locations) |
| 3 | `clipper_agency/core/pexels.py` | L71–73 | `pythonsecurity:S6549` | Critical | Vulnerability | Path constructed from user-controlled data |
| 4 | `clipper_agency/rendering/engine.py` | TBD | `python:S1481` | Minor | Code Smell | Unused local variable `thumbnail_path` |
| 5 | `tests/test_config.py` | TBD | `python:S1244` | Major | Bug | Float equality comparison (not `isclose`/`approx`) |
| 6 | `pyproject.toml` | — | `python:S6351` | Major | Reliability | Missing lock file (`uv.lock` or `poetry.lock`) |

> **Notes:**
> - Issue 1 (ytdlp.py) is a **pre-existing hotspot**, not introduced by Phase 15a.
> - Issue 4 (engine.py) is the **only Phase 15a-introduced** issue (from T9 render engine).
> - Issue 6 (pyproject.toml) may be a **false positive** — project uses `setuptools`, not `uv`/`poetry`.
> - Issues 2-3 are S6549 patterns identical to what was resolved in Phase 14.

---

## Dependencies

| Issue | File | Depends on |
|-------|------|-----------|
| 1 — ytdlp.py hotspot | `clipper_agency/core/ytdlp.py` | — (independent file) |
| 2 — packager.py S6549 (×3) | `clipper_agency/output/packager.py` | — (independent file) |
| 3 — pexels.py S6549 | `clipper_agency/core/pexels.py` | — (independent file) |
| 4 — engine.py unused var | `clipper_agency/rendering/engine.py` | — (independent file) |
| 5 — test_config.py float eq | `tests/test_config.py` | — (independent file) |
| 6 — pyproject.toml no lock | `pyproject.toml` | — (independent file) |

All 6 files are **fully independent** — no shared imports, no sequential dependencies. All can be fixed in one parallel batch.

---

## Batch 1 — All 6 fixes (parallel)

**Dispatch six agents simultaneously.** All share the same branch:

**Branch:** `phase/15a-sonar-fixes` (created from latest `master`)

```
                    Agent 1: ytdlp.py hotspot
                    Agent 2: packager.py S6549 (×3)
                    Agent 3: pexels.py S6549
                    Agent 4: engine.py unused var
                    Agent 5: test_config.py float eq
                    Agent 6: pyproject.toml lock file
```

---

### Agent 1 — ytdlp.py hotspot (pythonsecurity:S2077)

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - verification-before-completion  (no completion claim without fresh evidence)
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /media/eddy/hdd/Project/clipper agency/AGENTS.md  (S6549 lesson)

  Branch: phase/15a-sonar-fixes

  Fix the SonarCloud "pythonsecurity:S2077" hotspot in clipper_agency/core/ytdlp.py
  around L45: user-controlled URL reaches subprocess.run().

  Current code (L32-54) already:
    - Parses URL with urlparse()
    - Validates http/https scheme
    - Reconstructs safe_url from components (drops fragment)
    - Uses subprocess.run() with list (not shell=True)

  SonarCloud still flags because the static analyzer cannot verify urlparse
  reconstruction is sufficient for safety.

  Fix approach:
    - Add a URL validation helper that further validates the hostname
      (non-empty, no null bytes, no internal whitespace, valid format)
    - Validate the path component before reconstruction
    - Add a SaferProxy comment block at the hotspot site explaining the
      layered validation (urlparse → scheme check → hostname check →
      path check → subprocess list invocation)
    - This is a pre-existing pattern from Phase 3 (ytdlp integration).
      Document that this is an intentional design, not a vulnerability.

  IMPORTANT:
    - Do NOT skip existing tests.
    - Run pytest tests/test_ytdlp.py (or wherever ytdlp tests live) to verify
      the existing tests still pass.
    - Commit message: "fix: harden ytdlp URL validation for S2077 hotspot"

  Return: commit hash, test count passing.
```

---

### Agent 2 — packager.py S6549 (3 locations)

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development
    - verification-before-completion
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
    - /media/eddy/hdd/Project/clipper agency/AGENTS.md  (S6549 lesson — fixed contract paths)

  Branch: phase/15a-sonar-fixes

  Fix all 3 SonarCloud "pythonsecurity:S6549" issues in
  clipper_agency/output/packager.py (around L72, L82, L95):
  "Path constructed from user-controlled data."

  The AGENTS.md Phase 14 lesson says the pattern that worked was:
    - Use fixed contract paths: Path(output_dir) / f"job_{job_id}" / "video.mp4"
    - Packager should only validate/probe its OWN fixed-contract path,
      not open arbitrary caller-provided paths.
    - Use pathlib.Path.resolve() + relative_to() containment in
      clipper_agency/core/safe_paths.py before filesystem calls.

  Fix approach:
    1. Read clipper_agency/core/safe_paths.py to understand existing
       path safety patterns (resolve, relative_to containment check).
    2. In packager.py, introduce a helper that resolves and validates
       the output path against a known-safe base directory (configured
       output root, NOT caller-provided arbitrary paths).
    3. Use Path.resolve() on the output path, then verify it stays
       within the configured output root via relative_to().
    4. Add regression tests in tests/test_output_packager.py that:
       - Verify paths outside the output root are rejected.
       - Verify fixed job-owned paths are used (matching Phase 14 lesson).

  IMPORTANT:
    - Follow the AGENTS.md S6549 lesson EXACTLY — same pattern that
      succeeded in Phase 14 for fixed contract paths.
    - FIX the issue, do NOT suppress it with #NOSONAR.
    - Run all existing packager tests to verify no regressions.
    - Commit message: "fix: harden packager path construction per S6549 safe contract"

  Return: commit hash, all test results (packager tests + full offline regression).
```

---

### Agent 3 — pexels.py S6549

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development
    - verification-before-completion
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
    - /media/eddy/hdd/Project/clipper agency/AGENTS.md  (S6549 lesson — fixed contract paths)

  Branch: phase/15a-sonar-fixes

  Fix the SonarCloud "pythonsecurity:S6549" issue in
  clipper_agency/core/pexels.py around L71-73:
  "Path constructed from user-controlled data."

  Current code already has a path.relative_to(base) containment check,
  but the Path(base) / filename construction before the check still
  triggers the static analyzer.

  Fix approach:
    1. Read clipper_agency/core/safe_paths.py for existing patterns.
    2. Follow the AGENTS.md S6549 lesson: use Path.resolve() +
       relative_to() containment BEFORE constructing the output path.
    3. Validate the filename against a whitelist pattern (alphanumeric,
       dots, hyphens only) before joining to base.
    4. Add a regression test proving outside paths are rejected and
       contained paths are accepted.

  IMPORTANT:
    - FIX the issue, do NOT suppress with #NOSONAR.
    - Ensure existing pexels tests pass.
    - Commit message: "fix: harden pexels download path per S6549 safe contract"

  Return: commit hash, test count passing.
```

---

### Agent 4 — engine.py unused variable

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development
    - verification-before-completion
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md

  Branch: phase/15a-sonar-fixes

  Fix the SonarCloud "python:S1481" (Minor code smell) in
  clipper_agency/rendering/engine.py:
  "Remove unused local variable thumbnail_path."

  1. Read clipper_agency/rendering/engine.py
  2. Find the unused local variable `thumbnail_path`.
  3. Remove it (or if it serves a documentation purpose as a
     self-documenting intermediate, rename it to `_thumbnail_path`
     or extract into a comment).
  4. Run existing engine tests to verify nothing breaks:
     .venv/bin/python3 -m pytest tests/test_rendering_engine.py -v

  IMPORTANT:
    - This is the ONLY Phase 15a-introduced issue.
    - Minimal change — do NOT refactor adjacent code.
    - Commit message: "fix: remove unused thumbnail_path variable in render engine"

  Return: commit hash, test count passing.
```

---

### Agent 5 — test_config.py float equality

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - test-driven-development
    - verification-before-completion
  CONTEXT REQUIRED (Read tool before coding):
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/test-coverage.md
    - /home/eddy/distrobox/box-go-debian-home/.config/opencode/context/core/standards/code-quality.md

  Branch: phase/15a-sonar-fixes

  Fix the SonarCloud "python:S1244" (Major Bug) in tests/test_config.py:
  "Do not perform equality checks with floating point values."

  1. Read tests/test_config.py fully.
  2. Find ALL float equality comparisons (e.g., `assert result == 0.5`).
  3. Replace with pytest.approx():
     - `assert result == pytest.approx(0.5)`
     - Or use `math.isclose()` for non-pytest assertions.
  4. Run the test file to verify fixes:
     .venv/bin/python3 -m pytest tests/test_config.py -v
  5. Run full offline suite to verify no regressions.

  IMPORTANT:
    - Fix ALL float comparisons in the file, not just the first one.
    - Do NOT change test logic — only the comparison method.
    - Commit message: "fix: use pytest.approx for float comparisons in test_config"

  Return: commit hash, test count passing.
```

---

### Agent 6 — pyproject.toml missing lock file

```
Prompt:
  SKILLS REQUIRED (load before starting):
    - verification-before-completion

  Branch: phase/15a-sonar-fixes

  Fix the SonarCloud "python:S6351" (Major Reliability) in pyproject.toml:
  "Missing lock file (uv.lock or poetry.lock)."

  This project uses setuptools (not uv or poetry), so the lock file rule
  may be a false positive. Verify:

  1. Read pyproject.toml to confirm build system:
     - If `[build-system]` uses `setuptools` → false positive.
       Add a comment in pyproject.toml explaining:
       ```
       # This project uses setuptools (not uv/poetry), so no lock file is expected.
       # See AGENTS.md for virtualenv management via .venv/.
       ```
     - If it actually uses `uv` or `poetry` → generate the lock file.
  2. Read requirements.txt to confirm the dependency management method.
  3. Do NOT add a new dependency manager. This is a greenfield Python
     project with virtualenv-based installs.

  If the issue is a false positive, add the explanatory comment to
  pyproject.toml AND document in AGENTS.md that SonarCloud S6351 is
  not applicable because we use setuptools + requirements.txt.

  Commit message: "docs: document setuptools-based build system (no lock file required)"

  Return: commit hash, what was changed.
```

---

**Wait for ALL six agents to complete before proceeding.**

---

## Batch 2 — Verification + PR

Run locally (orchestrator role — load `verification-before-completion` before claiming success):

```bash
# Step 1: Verify all individual fix tests still pass
.venv/bin/python3 -m pytest \
  tests/test_ytdlp.py \
  tests/test_output_packager.py \
  tests/test_pexels.py \
  tests/test_rendering_engine.py \
  tests/test_config.py \
  -v

# Step 2: Full offline regression suite
.venv/bin/python3 -m pytest -m "not external and not integration" -q

# Step 3: Check git log for all 6 commits
git log --oneline -10

# Step 4: Push branch
git push -u origin phase/15a-sonar-fixes

# Step 5: Create PR
gh pr create --base master \
  --title "Phase 15a: Fix 7 SonarCloud issues (S2077, S6549, S1481, S1244, S6351)" \
  --body "Closes all 7 remaining SonarCloud open issues.

## Issues Fixed
1. **S2077 (ytdlp.py)** — Harden URL validation with hostname/path checks
2. **S6549 (packager.py ×3)** — Fixed-contract paths per Phase 14 AGENTS.md lesson
3. **S6549 (pexels.py)** — Resolve+containment before path construction
4. **S1481 (engine.py)** — Remove unused thumbnail_path variable
5. **S1244 (test_config.py)** — Replace float == with pytest.approx()
6. **S6351 (pyproject.toml)** — Document setuptools-based build (no lock file needed)

## Verification
- All targeted tests pass
- Full offline suite: 550+ tests pass"
```

Expected: All offline tests pass → PR open → SonarCloud green on all counts → merge.

---

## Summary

| Batch | Agents | Files fixed | Skills per agent |
|-------|--------|-------------|-----------------|
| Batch 1 | 6 parallel agents | 6 independent files | TDD + verification (Agents 1–5), verification-only (Agent 6) |
| Batch 2 | Orchestrator (local) | Verification + PR | `verification-before-completion` |
| **Total** | **2 batches** | 6 files, 7 issues | — |

**Post-merge target:** SonarCloud shows **0 open issues**, `master` is clean for PR 3 (Composer integration).

Orchestrator (you, coordinating): loads `dispatching-parallel-agents` for batch dispatch, `verification-before-completion` for merge gate.
