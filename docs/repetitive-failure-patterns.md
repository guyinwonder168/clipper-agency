# Repetitive Failure Patterns — Token-Optimized Reference

## 10 Recurring Failures (Phase 12–17)

### 1. Duplicate Agent Failure Handlers
- **Pattern**: 4+ identical 10-line `if output.get("status")=="failed": log+mark+update+return` blocks (voice_producer, visual_director, composer, retry paths)
- **Fix**: Extract `_fail_agent(conn, job_id, agent_name, reason)` — one helper, all callers use it
- **Rule**: Any agent that can fail needs ONE failure handler, not N copy-pastes

### 2. Duplicate String Literals
- **Pattern**: `"Voice generation failed"` x3, `"Asset sourcing failed"` x6 across engine.py
- **Fix**: Module constants `_VOICE_GEN_FAILED`, `_ASSET_SOURCING_FAILED` at top of file
- **Rule**: Any error string used >1x = module constant

### 3. Unchecked Agent Failure → Pipeline Advances
- **Pattern**: Voice producer produces 4/8 scenes (partial), pipeline advances to Composer with missing narration. `_complete_agent()` called unconditionally.
- **Fix**: Check `output.get("status")=="failed"` BEFORE `_complete_agent()`
- **Rule**: Always check failure before advancing to next stage. Partial output is still failure.

### 4. Cognitive Complexity (SonarCloud S3776)
- **Pattern**: execute() methods exceed 15 threshold (composer 16, visual_director 19)
- **Fix**: Extract `_run_llm_planning()`/`_run_legacy_planning()` helpers; merge duplicate `if agent_dir:` blocks
- **Rule**: If execute() has nested conditionals + multiple branches, extract helpers before hitting 15

### 5. Too Many Function Params (SonarCloud S107)
- **Pattern**: `_retry_downstream_stages()` had 17 params
- **Fix**: Bundle related values into `dict[str, Any]` (5 niche values → `niche_ctx`)
- **Rule**: >5 individual scalars = bundle into dict/dataclass

### 6. Silent Defaults on Exceptional Paths (Codex P2)
- **Pattern**: Missing niche YAML → `FileNotFoundError` caught → `NicheConfig(name="")` with empty safety_rules → agents run without safeguards
- **Fix**: `return {"status":"failed", "reason": f"Niche config {niche!r} not found"}`
- **Rule**: Exceptional paths must fail hard, not silently default to unsafe state

### 7. Uncached Config on Retry (Codex P2)
- **Pattern**: Retry re-reads YAML → could get different values mid-pipeline
- **Fix**: Snapshot `niche_ctx` in `config_snapshot` at first `run_pipeline()`; retry reads snapshot
- **Rule**: Config loaded at pipeline start must be frozen — retries read snapshot, not disk

### 8. Missing API Retry (Gemini TTS 429)
- **Pattern**: Free tier 3 RPM → 429 kills voice production mid-run
- **Fix**: Exponential backoff + jitter (0.5s base, 2x, max 30s, ±25% jitter)
- **Rule**: Every external API call needs: retry count, backoff, jitter. Non-negotiable.

### 9. Missing Data Normalization Between Stages
- **Pattern**: SAR values not normalized → downstream agents get inconsistent formats
- **Fix**: Add normalization layer at stage boundary (input validation + format coercion)
- **Rule**: Every agent's output format must be validated before next agent consumes it

### 10. Coverage Gate Not Checked Before PR
- **Pattern**: Every PR hits SonarCloud coverage gate (requires ≥93% on new code). PR #29 stuck at 78.3%.
- **Fix**: Check coverage BEFORE pushing PR: `.venv/bin/python3 -m pytest --cov=clipper_agency --cov-report=term-missing -m "not external and not integration" -q`
- **Rule**: Coverage check = pre-PR step. Fix uncovered spots before `git push`.

### 11. Boundary Gate Wired Into Only the Happy Path (Codex P1, FIX-1 / ADR 0030)
- **Pattern**: A gate/contract added at an inter-stage boundary (e.g. G7 `GateNarrativeCoverage` at Scriptwriter→Voice) is wired into the normal `_stage_content` path ONLY. The retry path (`_retry_downstream_stages`), the repair path (`_rerun_upstream_cascade`), and the cache-replay path ALSO rerun the upstream stage and feed its output to the consumer with NO gate → an operator retrying after a gate failure, or an upstream repair, lets the SAME defect the gate blocks sail through on the alternate path. The gate is a half-fix: front door locked, side doors open. (In-workflow code-quality + behavior reviewers MISS this — they review the gate in isolation; only a whole-control-flow pass catches it.)
- **Fix**: Extract ONE shared enforcement helper (e.g. `_enforce_narrative_coverage`) and call it from EVERY Scriptwriter→consumer hop — `_stage_content` + `_retry_downstream_stages` + `_rerun_upstream_cascade` — so a new re-entry path cannot bypass it without re-discovering the contract. Add a regression test per re-entry path, not just the normal path.
- **Rule**: A boundary gate must fire on ALL re-entry points (normal + retry + repair + resume + cache-replay), not just the happy path. Before claiming a gate done, enumerate every consumer via CodeGraph blast-radius and assert the gate fires on each.

## AGENTS.md Rules That Would Have Prevented These

| Failure Pattern | AGENTS.md Rule |
|---|---|
| Duplicate handlers/literals | "Never over-engineer" (ironically — over-engineered copy-paste IS over-engineering) |
| Silent defaults | "Treat as design problem, not suppression" (S6549 lesson) |
| Coverage gate failing | "Wait for SonarCloud — Do NOT merge before passes" |
| Unchecked agent failure | "Every gate has pass/soft-fail/hard-fail conditions" (from ADR template) |

## Commit Pattern for Fixes
```
feat: add _fail_agent() helper, deduplicate failure handlers
fix: extract string literals to module constants
fix: hard-fail on missing niche config (was silently defaulting)
fix: snapshot niche_ctx for retry determinism
fix: add exponential backoff + jitter for Gemini TTS 429s
refactor: extract helpers, reduce cognitive complexity
refactor: bundle params into dict to fix S107
test: add coverage for uncovered paths before PR
```

## Pre-PR Checklist (token-optimized)
1. Run tests: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
2. Check coverage: `.venv/bin/python3 -m pytest --cov=clipper_agency --cov-report=term-missing -m "not external and not integration" -q`
3. Fix any uncovered spots (target ≥93%)
4. `git push`
5. Wait for SonarCloud ✅
6. `gh pr merge phase/N-short-description --merge`
7. Delete branch (local + remote)
8. Update AGENTS.md Repository State
