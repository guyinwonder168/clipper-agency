# Phase 17: Prompt Deduplication + NicheConfig Activation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all hardcoded niche/identity text from prompts and agent code, replacing them with data-driven values from the niche YAML config. Make NicheConfig the single source of truth for content rules.

**Architecture:** Add `content_angle`, `search_terms`, `max_hashtags` to NicheConfig schema. Add `build_channel_description()` helper to config/loader.py. Replace hardcoded strings in prompt files and agent fallback prompts with `{channel_description}` placeholder. Orchestrator loads niche config and passes derived values (safety_rules, channel_description) to agents.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, pytest

**Branch:** `phase/17-prompt-deduplication` (already created from master)

---

### Task 1: Extend NicheConfig Schema

**Files:**
- Modify: `clipper_agency/config/schema.py:40-48`
- Modify: `tests/fixtures/test_niche.yaml`
- Test: `tests/test_config_loader.py`

**Step 1: Write the failing test**

Add to `tests/test_config_loader.py` in `TestLoadNiche`:

```python
def test_load_niche_includes_new_fields(self, fixtures_dir):
    """NicheConfig should parse content_angle, search_terms, max_hashtags."""
    niche = load_niche("test_niche", niches_dir=fixtures_dir)
    assert niche.content_angle == "trending_artist_update"
    assert niche.search_terms == ["viral", "trending"]
    assert niche.max_hashtags == 5
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_config_loader.py::TestLoadNiche::test_load_niche_includes_new_fields -v`
Expected: FAIL — `NicheConfig` has no field `content_angle`

**Step 3: Update test fixture**

Add the new fields to `tests/fixtures/test_niche.yaml`:

```yaml
name: indonesian_artists
language: "id"
tone: casual_tiktok
video_length:
  target: 30
  hard_limit: 60
safety_rules:
  - no_defamation
  - no_sara
  - mark_rumors_as_unconfirmed
caption_style: short_with_hashtags
content_angle: trending_artist_update
search_terms:
  - viral
  - trending
max_hashtags: 5
```

**Step 4: Update NicheConfig schema**

In `clipper_agency/config/schema.py`, add three fields to `NicheConfig`:

```python
class NicheConfig(BaseModel):
    """Niche profile — content rules and constraints."""

    name: str
    language: str = "id"
    tone: str = "casual_tiktok"
    video_length: VideoLengthConfig = Field(default_factory=VideoLengthConfig)
    safety_rules: list[str] = Field(default_factory=list)
    caption_style: str = "short_with_hashtags"
    content_angle: str = "trending_artist_update"
    search_terms: list[str] = Field(default_factory=list)
    max_hashtags: int = 5
```

**Step 5: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_config_loader.py::TestLoadNiche -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add clipper_agency/config/schema.py tests/fixtures/test_niche.yaml tests/test_config_loader.py
git commit -m "feat: add content_angle, search_terms, max_hashtags to NicheConfig"
```

---

### Task 2: Add build_channel_description() to config/loader.py

**Files:**
- Modify: `clipper_agency/config/loader.py`
- Test: `tests/test_config_loader.py`

**Step 1: Write the failing test**

Add a new test class to `tests/test_config_loader.py`:

```python
class TestBuildChannelDescription:
    """build_channel_description() — builds identity string from NicheConfig."""

    def test_builds_description_from_niche_config(self, fixtures_dir):
        niche = load_niche("test_niche", niches_dir=fixtures_dir)
        desc = build_channel_description(niche)
        assert "Indonesian" in desc
        assert "artist infotainment" in desc
        assert "TikTok" in desc or "tiktok" in desc

    def test_default_niche_builds_description(self):
        niche = load_niche("indonesian_artists")
        desc = build_channel_description(niche)
        assert desc  # non-empty
        assert "Indonesian" in desc

    def test_custom_niche_builds_description(self):
        niche = NicheConfig(
            name="tech_reviews",
            language="en",
            tone="professional",
            content_angle="latest_gadget_reviews",
        )
        desc = build_channel_description(niche)
        assert desc  # non-empty
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_config_loader.py::TestBuildChannelDescription -v`
Expected: FAIL — `build_channel_description` not imported

**Step 3: Implement build_channel_description()**

Add to `clipper_agency/config/loader.py`:

```python
def build_channel_description(niche: NicheConfig) -> str:
    """Build a human-readable channel identity string from niche config.

    Used to inject into agent prompts so they know what channel they write for,
    without hardcoding niche identity in prompt files.
    """
    language_map = {
        "id": "Indonesian",
        "en": "English",
    }
    language_name = language_map.get(niche.language, niche.language)

    # Convert content_angle like "trending_artist_update" to "trending artist update"
    angle = niche.content_angle.replace("_", " ")

    # Map tone to readable form
    tone_map = {
        "casual_tiktok": "casual TikTok",
        "professional": "professional",
        "casual": "casual",
    }
    tone_name = tone_map.get(niche.tone, niche.tone)

    return f"a {language_name} {angle} {tone_name} channel"
```

Update the import in the test file to include `build_channel_description`.

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_config_loader.py::TestBuildChannelDescription -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add clipper_agency/config/loader.py tests/test_config_loader.py
git commit -m "feat: add build_channel_description() to config/loader.py"
```

---

### Task 3: Replace hardcoded niche text in prompt files

**Files:**
- Modify: `prompts/researcher.md`
- Modify: `prompts/scriptwriter.md`
- Test: `tests/test_prompt_loader.py`

**Step 1: Update prompts/researcher.md**

Replace the entire file:

```markdown
You are a research agent for {channel_description}.

Research the provided topic and produce a concise brief with:
1. Key facts that can be verified
2. Unverified claims clearly labeled as rumors or unconfirmed
3. Relevant context for social media audiences
4. Suggested angles for a short-form video

Prioritize accuracy, source awareness, and cautious wording over sensationalism.
```

Changes: line 1 replaced with `{channel_description}` placeholder, line 3 removed "Indonesian" (now generic).

**Step 2: Update prompts/scriptwriter.md**

Replace the entire file:

```markdown
You are a TikTok scriptwriter creating engaging scripts for {channel_description}.

Given a research brief and topic, create:
1. A scene-by-scene TikTok script (hook, body, CTA)
2. An engaging caption
3. Relevant hashtags

Format your response as JSON:
{{
  "script": [{{"scene": 1, "text": "...", "duration": estimated_seconds}}, ...],
  "caption": "...",
  "hashtags": ["#tag1", "#tag2"],
  "estimated_duration": total_seconds
}}

Guidelines:
- Hook within first 3 seconds
- Keep total duration under 90 seconds
- Use casual, engaging tone
- Include a strong CTA (call to action)

Safety rules to follow:
{safety_rules_text}
```

Changes: line 1 replaced with `{channel_description}`, line 19 removed "Indonesian".

**Step 3: Write test for placeholder presence**

Add to `tests/test_prompt_loader.py`:

```python
def test_researcher_prompt_has_channel_description_placeholder():
    """researcher.md must contain {channel_description} placeholder."""
    from clipper_agency.agents.prompts import PROMPTS_DIR
    content = (PROMPTS_DIR / "researcher.md").read_text()
    assert "{channel_description}" in content


def test_scriptwriter_prompt_has_channel_description_placeholder():
    """scriptwriter.md must contain {channel_description} placeholder."""
    from clipper_agency.agents.prompts import PROMPTS_DIR
    content = (PROMPTS_DIR / "scriptwriter.md").read_text()
    assert "{channel_description}" in content


def test_no_hardcoded_niche_in_prompt_files():
    """No prompt file should contain 'Indonesian artist infotainment'."""
    from clipper_agency.agents.prompts import PROMPTS_DIR
    for md_file in PROMPTS_DIR.glob("*.md"):
        content = md_file.read_text()
        assert "Indonesian artist infotainment" not in content, (
            f"{md_file.name} still contains hardcoded niche text"
        )
```

**Step 4: Run tests**

Run: `.venv/bin/python3 -m pytest tests/test_prompt_loader.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add prompts/researcher.md prompts/scriptwriter.md tests/test_prompt_loader.py
git commit -m "feat: replace hardcoded niche text with {channel_description} in prompts"
```

---

### Task 4: Update agent fallback prompts + accept channel_description

**Files:**
- Modify: `clipper_agency/agents/researcher.py` (RESEARCH_PROMPT + execute())
- Modify: `clipper_agency/agents/scriptwriter.py` (SCRIPTWRITER_PROMPT + execute())

**Step 1: Update researcher.py RESEARCH_PROMPT**

Replace lines 35-49 in `clipper_agency/agents/researcher.py`:

```python
RESEARCH_PROMPT = """You are a research assistant for {channel_description}.
Analyze the provided search results and create a concise research brief.

Rules to follow:
{rules_text}

Search results:
{sources_text}

Return a concise research brief that covers:
1. Key facts and verified information
2. Trending angles and viral potential
3. Content suggestions for short-form video
4. Any risks or sensitive topics to handle carefully
"""
```

Changes: "TikTok content creator" → `{channel_description}`, "TikTok" in item 3 → "short-form video".

**Step 2: Update researcher.py execute() signature**

In `execute()` (line 63), add `channel_description` parameter:

```python
def execute(
    self,
    job_id: int,
    topic: str = "",
    safety_rules: list[str] | None = None,
    channel_description: str = "",
    max_results: int = 5,
    output_dir: str = "",
    assets_cache: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
```

In `_synthesize_research()` call (line 178), pass `channel_description`.

Update `_synthesize_research()` signature and prompt formatting (lines 251-304):

```python
def _synthesize_research(
    self,
    aggregated: dict[str, Any],
    topic: str,
    safety_rules: list[str],
    channel_description: str = "",
) -> dict[str, Any]:
```

In the LLM call, update the format:

```python
"content": RESEARCH_PROMPT.format(
    channel_description=channel_description or "a content creator",
    rules_text=rules_text, sources_text=sources_text
),
```

**Step 3: Update scriptwriter.py SCRIPTWRITER_PROMPT**

Replace lines 16-39 in `clipper_agency/agents/scriptwriter.py`:

```python
SCRIPTWRITER_PROMPT = """You are a TikTok scriptwriter creating engaging scripts for {channel_description}.

Given a research brief and topic, create:
1. A scene-by-scene TikTok script (hook, body, CTA)
2. An engaging caption
3. Relevant hashtags

Format your response as JSON:
{{
  "script": [{{"scene": 1, "text": "...", "duration": estimated_seconds}}, ...],
  "caption": "...",
  "hashtags": ["#tag1", "#tag2"],
  "estimated_duration": total_seconds
}}

Guidelines:
- Hook within first 3 seconds
- Keep total duration under 90 seconds
- Use casual, engaging tone
- Include a strong CTA (call to action)

Safety rules to follow:
{safety_rules_text}
"""
```

Changes: "Indonesian artist infotainment channel" → `{channel_description}`, "Indonesian" removed from tone guideline.

**Step 4: Update scriptwriter.py execute() signature**

In `execute()` (line 49), add `channel_description` parameter:

```python
def execute(
    self,
    job_id: int,
    topic: str = "",
    research_brief: str = "",
    safety_rules: list[str] | None = None,
    channel_description: str = "",
    assets_cache: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
```

Update the prompt formatting (line 80):

```python
"content": prompt.format(
    channel_description=channel_description or "a content creator",
    safety_rules_text=safety_rules_text,
),
```

**Step 5: Run existing agent tests to verify nothing breaks**

Run: `.venv/bin/python3 -m pytest tests/ -k "researcher or scriptwriter" -v --timeout=30`
Expected: ALL PASS (agents use `**kwargs` so new param is harmless)

**Step 6: Commit**

```bash
git add clipper_agency/agents/researcher.py clipper_agency/agents/scriptwriter.py
git commit -m "feat: agents accept channel_description, remove hardcoded niche from fallback prompts"
```

---

### Task 5: Orchestrator loads niche config and passes derived values

**Files:**
- Modify: `clipper_agency/orchestrator/engine.py`

This is the critical wiring task. The orchestrator must:
1. Call `load_niche(niche)` at pipeline start
2. Derive `safety_rules` from niche config (not hardcoded)
3. Build `channel_description` via `build_channel_description(niche)`
4. Pass `channel_description` to researcher and scriptwriter calls

**Step 1: Add imports at top of engine.py**

Add to imports section:

```python
from clipper_agency.config.loader import load_niche, build_channel_description
```

**Step 2: Update run_pipeline() — replace hardcoded safety_rules**

In `run_pipeline()` (line 302), after `logger.info("Pipeline START: ...")`, add niche loading:

```python
        logger.info("Pipeline START: niche='%s'", niche)

        # Load niche configuration — single source of truth
        niche_config = load_niche(niche)
        safety_rules = niche_config.safety_rules
        channel_description = build_channel_description(niche_config)
```

Remove line 336: `safety_rules = ["no_defamation", "mark_rumors_as_unconfirmed"]`

Pass `channel_description` to `_stage_research()` and `_stage_content()`.

**Step 3: Thread channel_description through stage methods**

Update `_stage_research()` signature:

```python
def _stage_research(
    self, conn: Any, job_id: int, topic: str,
    safety_rules: list[str], channel_description: str,
    assets_cache: str, output_dir: str,
) -> dict[str, Any]:
```

Update `self._run_researcher()` call to pass `channel_description`.

Update `_stage_content()` signature similarly, threading `channel_description` through to `_run_content_scriptwriter()` → `_run_scriptwriter()`.

Update `_run_scriptwriter()` call to include `channel_description=channel_description`.

**Step 4: Update run_pipeline_from() — replace second hardcoded safety_rules**

In `run_pipeline_from()` (line 688), replace:

```python
        safety_rules = ["no_defamation", "mark_rumors_as_unconfirmed"]
```

With:

```python
        niche_config = load_niche(niche)
        safety_rules = niche_config.safety_rules
        channel_description = build_channel_description(niche_config)
```

Thread `channel_description` through `_retry_research_stage()` and `_retry_downstream_stages()` similarly.

**Step 5: Run orchestrator tests**

Run: `.venv/bin/python3 -m pytest tests/ -k "orchestrator or engine" -v --timeout=30`
Expected: ALL PASS (may need to update test mocks to handle `load_niche` call)

**Step 6: Commit**

```bash
git add clipper_agency/orchestrator/engine.py
git commit -m "feat: orchestrator loads niche config, derives safety_rules and channel_description"
```

---

### Task 6: CLI graceful niche validation

**Files:**
- Modify: `clipper_agency/__main__.py:85-105`

**Step 1: Add niche validation before pipeline**

In the `run()` command, add a try/except around `load_niche()`:

```python
def run(topic: str, niche: str, db: str | None, output_dir: str | None, dry_run: bool) -> None:
    """Run the full pipeline for a topic."""
    click.echo(f"Clipper Agency — Topic: {topic}")
    click.echo(f"Niche: {niche}")

    # Validate niche exists before starting pipeline
    try:
        load_niche(niche)
    except FileNotFoundError:
        click.echo(f"Error: Niche '{niche}' not found. Check available niches in niches/ directory.")
        raise SystemExit(1)

    if dry_run:
        click.echo("Dry run: input valid. Pipeline execution coming soon...")
        return

    resolved_db = db or _db_path()
    resolved_output = output_dir or _output_dir()
    ...
```

Add import: `from clipper_agency.config.loader import load_niche`

**Step 2: Test the validation**

Run: `.venv/bin/python3 -m pytest tests/ -k "cli or main" -v --timeout=30`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add clipper_agency/__main__.py
git commit -m "feat: CLI validates niche exists before pipeline start"
```

---

### Task 7: Full test suite + new tests

**Files:**
- Test: `tests/test_config_loader.py` (updated)
- Test: `tests/test_prompt_loader.py` (updated)
- Test: existing orchestrator/agent tests

**Step 1: Run full offline test suite**

Run: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
Expected: ALL PASS (633+ tests)

**Step 2: If any tests fail, investigate and fix**

Common issues:
- Tests that mock `load_niche()` may need updating
- Tests that assert on specific prompt content may need updating
- Tests that check hardcoded safety_rules values need updating

**Step 3: Commit any test fixes**

```bash
git add tests/
git commit -m "test: update tests for niche-driven config"
```

---

### Task 8: Push + PR + SonarCloud

**Step 1: Push branch**

```bash
git push -u origin phase/17-prompt-deduplication
```

**Step 2: Create PR**

```bash
gh pr create --base master --title "Phase 17: Prompt Deduplication + NicheConfig Activation" --body "Removes all hardcoded niche/identity text from prompts and agent code. Makes NicheConfig the single source of truth for content rules, safety rules, and channel identity.

Changes:
- NicheConfig: add content_angle, search_terms, max_hashtags
- config/loader.py: add build_channel_description()
- prompts/researcher.md, scriptwriter.md: {channel_description} placeholder
- agents/researcher.py, scriptwriter.py: accept channel_description
- orchestrator/engine.py: load_niche(), derive safety_rules + channel_description
- CLI: graceful niche validation

All 633+ offline tests pass."
```

**Step 3: Wait for SonarCloud to pass. Fix any issues on the branch.**

**Step 4: Merge (after SonarCloud green)**

```bash
gh pr merge phase/17-prompt-deduplication --merge
git branch -d phase/17-prompt-deduplication
git push origin --delete phase/17-prompt-deduplication
git checkout master && git pull origin master
```

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
