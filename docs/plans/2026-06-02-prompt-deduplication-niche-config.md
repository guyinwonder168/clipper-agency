# Phase 17: Prompt Deduplication + NicheConfig Activation ✅ COMPLETED

> **Status:** All 8 tasks implemented, tested (642 pass, 2 deselected), and merged into `master` via PR #29.
> **Branch:** `phase/17-prompt-deduplication` (deleted after merge)
> **Date:** 2026-06-03

**Goal:** Remove all hardcoded niche/identity text from prompts and agent code, replacing them with data-driven values from the niche YAML config. Make NicheConfig the single source of truth for content rules.

**Architecture:** Add `content_angle`, `search_terms`, `max_hashtags` to NicheConfig schema. Add `build_channel_description()` helper to config/loader.py. Replace hardcoded strings in prompt files and agent fallback prompts with `{channel_description}` placeholder. Orchestrator loads niche config and passes derived values (safety_rules, channel_description) to agents.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, pytest

---

### Task 1: Extend NicheConfig Schema ✅

**Files:**
- Modified: `clipper_agency/config/schema.py`
- Modified: `tests/fixtures/test_niche.yaml`
- Test: `tests/test_config_loader.py`

**Commit:** `d2e6218` — `feat: add content_angle, search_terms, max_hashtags to NicheConfig`

Added three fields to `NicheConfig`:
- `content_angle: str = "trending_artist_update"` — describes the content focus
- `search_terms: list[str]` — default empty list
- `max_hashtags: int = 5` — caps hashtag count

Updated test fixture `test_niche.yaml` with the new fields. Test `test_load_niche_includes_new_fields` passes.

---

### Task 2: Add build_channel_description() to config/loader.py ✅

**Files:**
- Modified: `clipper_agency/config/loader.py`
- Test: `tests/test_config_loader.py`

**Commit:** `0e94190` — `feat: add build_channel_description() to config/loader.py`

Added `build_channel_description(niche: NicheConfig) -> str` that builds a human-readable channel identity string from the niche config:

```python
def build_channel_description(niche: NicheConfig) -> str:
    language_map = {"id": "Indonesian", "en": "English"}
    language_name = language_map.get(niche.language, niche.language)
    angle = niche.content_angle.replace("_", " ")
    tone_map = {"casual_tiktok": "casual TikTok", "professional": "professional", "casual": "casual"}
    tone_name = tone_map.get(niche.tone, niche.tone)
    return f"a {language_name} {angle} {tone_name} channel"
```

Tests: `TestBuildChannelDescription` — 3 tests covering default, custom, and fixture-based niches.

---

### Task 3: Replace hardcoded niche text in prompt files ✅

**Files:**
- Modified: `prompts/researcher.md`
- Modified: `prompts/scriptwriter.md`
- Test: `tests/test_prompt_loader.py`

**Commit:** `ebf4862` — `feat: replace hardcoded niche text with {channel_description} in prompts`

- `prompts/researcher.md`: Line 1 now uses `{channel_description}` placeholder
- `prompts/scriptwriter.md`: Line 1 now uses `{channel_description}` placeholder
- Added 3 tests in `test_prompt_loader.py`:
  - `test_researcher_prompt_has_channel_description_placeholder`
  - `test_scriptwriter_prompt_has_channel_description_placeholder`
  - `test_no_hardcoded_niche_in_prompt_files`

---

### Task 4: Update agent fallback prompts + accept channel_description ✅

**Files:**
- Modified: `clipper_agency/agents/researcher.py`
- Modified: `clipper_agency/agents/scriptwriter.py`

**Commit:** `867224b` — `feat: agents accept channel_description, remove hardcoded niche from fallback prompts`

- `researcher.py`: `RESEARCH_PROMPT` uses `{channel_description}`, `execute()` accepts `channel_description` param, threaded through `_synthesize_research()`
- `scriptwriter.py`: `SCRIPTWRITER_PROMPT` uses `{channel_description}`, `execute()` accepts `channel_description` param
- Fallback: `channel_description or "a content creator"` in both agents

---

### Task 5: Orchestrator loads niche config and passes derived values ✅

**Files:**
- Modified: `clipper_agency/orchestrator/engine.py`

**Commit:** `baab2dc` — `feat: orchestrator loads niche config, derives safety_rules and channel_description`

- Added imports: `load_niche`, `build_channel_description`
- `run_pipeline()`: loads niche config at start, derives `safety_rules` and `channel_description`, passes to stage methods
- `run_pipeline_from()`: same pattern for retry/resume flows
- Removed hardcoded `safety_rules = ["no_defamation", "mark_rumors_as_unconfirmed"]` in both functions
- Threaded `channel_description` through `_stage_research()`, `_stage_content()`, `_run_researcher()`, `_run_scriptwriter()`, `_retry_research_stage()`, `_retry_downstream_stages()`

---

### Task 6: CLI graceful niche validation ✅

**Files:**
- Modified: `clipper_agency/__main__.py`

**Commit:** `ca9af45` — `feat: CLI validates niche exists before pipeline start`

Added try/except `load_niche(niche)` before pipeline start — graceful `FileNotFoundError` handling with clear error message and `SystemExit(1)`.

---

### Task 7: Full test suite ✅

**Result:** All **642 tests pass**, 2 deselected (same pre-existing exclusions).

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
# 642 passed, 2 deselected in 40.67s
```

---

### Task 8: Push + PR + SonarCloud ✅

- **PR:** #29 — `Phase 17: Prompt Deduplication + NicheConfig Activation`
- **Merge:** True merge commit (`--merge`), no squash
- **SonarCloud:** Passed before merge
- **Branch:** `phase/17-prompt-deduplication` deleted locally and remotely after merge
- **AGENTS.md:** Updated with Phase 17 completion state (commit `0961b3e`)

---

## Summary of Changes

| File | Change |
|------|--------|
| `config/schema.py` | Add `content_angle`, `search_terms`, `max_hashtags` to NicheConfig |
| `config/loader.py` | Add `build_channel_description()` |
| `prompts/researcher.md` | Replace hardcoded niche with `{channel_description}` |
| `prompts/scriptwriter.md` | Replace hardcoded niche with `{channel_description}` |
| `agents/researcher.py` | Accept `channel_description`, update RESEARCH_PROMPT |
| `agents/scriptwriter.py` | Accept `channel_description`, update SCRIPTWRITER_PROMPT |
| `orchestrator/engine.py` | Load niche config, derive safety_rules + channel_description |
| `__main__.py` | Graceful niche validation |
| `tests/fixtures/test_niche.yaml` | Add new fields |
| `tests/test_config_loader.py` | Tests for new fields + build_channel_description() |
| `tests/test_prompt_loader.py` | Tests for placeholder presence + no hardcoded text |
