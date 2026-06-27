# ADR 0028 — Central `.env` loader at every runtime entry point

**Status:** Accepted
**Date:** 2026-06-27
**Related:** ADR 0021 (audio-first continuous voiceover), ADR 0026 (contract enforcement over rebuild)

## Context

Every external service in the pipeline reads its credentials directly via
`os.getenv()` at construction time (ElevenLabs, Gemini TTS, Fish Audio, Pexels,
OpenRouter, Firecrawl, ScrapeCreators, Brave, dashboard auth/secret).
`python-dotenv`'s `load_dotenv()` populates `os.environ` from `.env` — but it
was called in exactly ONE place: the CLI entry (`clipper_agency/__main__.py`).

The Flask dashboard, retry, and resume paths construct the `Orchestrator`
without going through `__main__`, so `.env` was never loaded for them.
`os.getenv("ELEVENLABS_API_KEY")` returned `None`, Voice Producer's
`_PROVIDER_KEYS` check silently skipped ElevenLabs, and **every dashboard-driven
job fell back to Gemini TTS** (fuzzy proportional timestamps instead of
ElevenLabs char-alignment). The bug was invisible: credits were fine (8,066/
10,000 Free verified), the API worked (a separate `audio_base64` extraction
typo masked it further), and `provider_attempts` recorded only the fallback —
never the skip. The AV-drift harness (PR #78) surfaced it: every captured job
was `gemini_tts`.

`pydantic-settings` `AppSettings` (env_file=".env") loads `.env` into the
Settings *model*, but NOT into `os.environ` — so it did not help the scattered
`os.getenv()` calls in services.

## Decision

Add `clipper_agency/bootstrap.py` with a single idempotent `load_env()` that
calls `load_dotenv()` (default `override=False`, so real shell env always wins).
Wire it into EVERY runtime entry point:

1. **CLI** — `clipper_agency/__main__.py` import-time.
2. **Flask dashboard** — `clipper_agency/dashboard/app.py` import-time, before
   `app.secret_key = os.getenv("DASHBOARD_SECRET_KEY")`.
3. **`Orchestrator.__init__`** — the common chokepoint for dashboard-create,
   retry, and resume.

`load_dotenv()` is idempotent and never overrides existing env vars, so calling
it from multiple entry points (e.g. CLI → Orchestrator) is safe and cheap.

## Alternatives Considered

- **Load `.env` only in `__main__.py` (status quo)** — rejected: leaves the
  dashboard/retry/resume paths misconfigured, which is exactly the bug.
- **Move every `os.getenv()` into `AppSettings`** (pydantic typed settings,
  single source) — heavier refactor; correct long-term but out of scope for the
  Phase 0 bugfix and risks touching every service. Tracked as future cleanup.
- **Call `load_dotenv()` once at package import (`clipper_agency/__init__.py`)** —
  rejected: import-time side effects on the top-level package are surprising and
  hard to override in tests; an explicit `load_env()` at each documented entry
  point is clearer and testable (spied tests lock each chokepoint).

## Consequences

- **Positive:** every runtime entry point — CLI, dashboard, retry, resume —
  sees the same `.env`; the silent ElevenLabs-skip → Gemini-fallback class of
  bug cannot recur. `app.secret_key` is correctly populated under the dashboard.
- **Positive:** regression-locked by spied tests
  (`test_dashboard_import_triggers_load_env`,
  `test_orchestrator_init_triggers_load_env`, `test_dotenv_loading`).
- **Positive:** `override=False` preserves operator expectations: a real shell
  export always beats `.env`.
- **Negative:** `load_env()` is called from 3 places (minor duplication of the
  call); acceptable because each is a genuine, independent entry point and the
  function is a one-line idempotent delegation.
- **Note:** services still read `os.getenv()` directly. A future refactor could
  route all env access through typed `AppSettings`; until then, `bootstrap.load_env()`
  is the contract that makes those `os.getenv()` calls correct.
