# Fixes #6-#11 Implementation Plan ✅ IMPLEMENTED

> **Status:** Implemented — 4 incremental commits merged via PR #41 to master. All fixes deployed.
>
> **For Claude:** DO NOT implement this plan. It has already been completed.

**Goal:** Implement 6 pending fixes (merged into 4 commits) to finalize v2.0.0 audio-first architecture.

**Architecture:** Incremental commits — each passes the full test suite independently. Fix #6+#9 merged as config overhaul, #7+#8 merged as logging improvements.

**Tech Stack:** Python 3.11+, Pydantic, httpx, FFmpeg, pytest

**Design Doc:** `docs/plans/2026-06-07-fixes-6-11-design.md`

**ADR:** `docs/adr/0022-config-overhaul-chunking-safety-net.md` (new)

**Test Command:** `.venv/bin/python3 -m pytest -m "not external and not integration" -q`

---

## Commit 1: #11 — Hook Card / Caption Dedup

### Task 1: Write failing test for hook_duration skip

**Files:**
- Modify: `tests/test_subtitle_engine.py:268-404` (TestBuildKeywordCaptions class)

**Step 1: Write the failing test**

Add to `TestBuildKeywordCaptions` class in `tests/test_subtitle_engine.py`:

```python
def test_hook_duration_skips_first_beat_caption(self):
    """Captions during hook window are skipped — hook card already shows text."""
    narrative = [
        {"beat_id": 1, "word_range": [0, 4], "caption_keywords": ["gosip", "artis", "terhot"]},
        {"beat_id": 2, "word_range": [4, 8], "caption_keywords": ["foo", "bar"]},
    ]
    timestamps = _make_timestamps(8)

    result = build_keyword_captions(narrative, timestamps, hook_duration=2.0)

    assert len(result) == 1
    assert result[0].text == "foo bar"
    assert result[0].start_seconds == pytest.approx(2.0)

def test_hook_duration_zero_no_skip(self):
    """hook_duration=0 (default) does not skip any captions."""
    narrative = [
        {"beat_id": 1, "word_range": [0, 4], "caption_keywords": ["hello"]},
        {"beat_id": 2, "word_range": [4, 8], "caption_keywords": ["world"]},
    ]
    timestamps = _make_timestamps(8)

    result = build_keyword_captions(narrative, timestamps, hook_duration=0.0)

    assert len(result) == 2

def test_hook_duration_skips_multiple_beats(self):
    """If hook spans multiple beats, all are skipped."""
    narrative = [
        {"beat_id": 1, "word_range": [0, 4], "caption_keywords": ["first"]},
        {"beat_id": 2, "word_range": [4, 8], "caption_keywords": ["second"]},
        {"beat_id": 3, "word_range": [8, 12], "caption_keywords": ["third"]},
    ]
    timestamps = _make_timestamps(12)

    result = build_keyword_captions(narrative, timestamps, hook_duration=4.0)

    assert len(result) == 1
    assert result[0].text == "third"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_subtitle_engine.py::TestBuildKeywordCaptions::test_hook_duration_skips_first_beat_caption -v`
Expected: FAIL — `hook_duration` keyword argument not accepted

---

### Task 2: Implement hook_duration in build_keyword_captions

**Files:**
- Modify: `clipper_agency/rendering/subtitle_engine.py:69-162`

**Step 1: Add hook_duration parameter**

In `build_keyword_captions()`, add `hook_duration: float = 0.0` parameter after `height`. Then in both code paths (timestamp and fallback), add `if start_time < hook_duration: continue` before appending the overlay.

**Step 2: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_subtitle_engine.py -v`
Expected: ALL PASS (including new tests and existing tests)

---

### Task 3: Wire hook_duration in composer

**Files:**
- Modify: `clipper_agency/agents/composer.py:1271-1273`

**Step 1: Pass hook_duration from composer**

In `_run_audio_first_render()` at line 1271, change:

```python
keyword_captions = build_keyword_captions(
    narrative_structure, timestamps,
)
```

To:

```python
# Hook duration = first beat's duration (skip captions during hook card)
hook_dur = beat_durations[0] if beat_durations else 0.0
keyword_captions = build_keyword_captions(
    narrative_structure, timestamps, hook_duration=hook_dur,
)
```

**Step 2: Run full test suite**

Run: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
Expected: ALL PASS (990+)

---

### Task 4: Commit #11

```bash
git add clipper_agency/rendering/subtitle_engine.py clipper_agency/agents/composer.py tests/test_subtitle_engine.py
git commit -m "fix: suppress keyword captions during hook card window (#11)"
```

---

## Commit 2: #6+#9 — Config Overhaul

### Task 5: Write failing tests for model_cache

**Files:**
- Create: `tests/test_model_cache.py`

**Step 1: Write tests**

```python
"""Tests for config/model_cache — OpenRouter model metadata caching."""
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest


def test_get_model_metadata_returns_cached_data(tmp_path, monkeypatch):
    """get_model_metadata reads from cache file."""
    from clipper_agency.config.model_cache import get_model_metadata, _CACHE_PATH

    cache_data = {
        "fetched_at": time.time(),
        "models": {
            "test-model": {"context_length": 8192, "max_completion_tokens": 4096},
        },
    }
    cache_file = tmp_path / "model_cache.json"
    cache_file.write_text(json.dumps(cache_data))
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    result = get_model_metadata("test-model")
    assert result is not None
    assert result["max_completion_tokens"] == 4096


def test_get_model_metadata_returns_none_for_unknown(tmp_path, monkeypatch):
    """Unknown model name returns None."""
    from clipper_agency.config.model_cache import get_model_metadata

    cache_file = tmp_path / "model_cache.json"
    cache_file.write_text(json.dumps({"fetched_at": time.time(), "models": {}}))
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    assert get_model_metadata("nonexistent-model") is None


def test_refresh_model_cache_writes_file(tmp_path, monkeypatch):
    """refresh_model_cache fetches API and writes cache."""
    from clipper_agency.config.model_cache import refresh_model_cache

    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    mock_response = {
        "data": [
            {"id": "test-model", "context_length": 8192, "max_completion_tokens": 4096},
        ],
    }
    with patch("httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.return_value.json.return_value = mock_response
        mock_client.get.return_value.raise_for_status.return_value = None

        refresh_model_cache(force=True)

    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert "test-model" in data["models"]
    assert data["models"]["test-model"]["max_completion_tokens"] == 4096


def test_cache_not_refreshed_when_fresh(tmp_path, monkeypatch):
    """Cache < 7 days old is not refreshed (unless force)."""
    from clipper_agency.config.model_cache import refresh_model_cache

    cache_file = tmp_path / "model_cache.json"
    fresh_data = {"fetched_at": time.time(), "models": {}}
    cache_file.write_text(json.dumps(fresh_data))
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    with patch("httpx.Client") as mock_client_cls:
        refresh_model_cache(force=False)
        # httpx.Client should NOT be instantiated for fresh cache
        mock_client_cls.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_model_cache.py -v`
Expected: FAIL — module `config.model_cache` not found

---

### Task 6: Implement model_cache.py

**Files:**
- Create: `clipper_agency/config/model_cache.py`

**Step 1: Write the module**

```python
"""OpenRouter model metadata cache — auto-fetch, lazy-load, 7-day refresh."""

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("data/model_cache.json")
_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def get_model_metadata(model_name: str) -> dict[str, Any] | None:
    """Return cached metadata for *model_name*, or None if not found.

    Lazy-loads cache on first call.  Returns dict with keys like
    ``context_length`` and ``max_completion_tokens``.
    """
    cache = _load_cache()
    if cache is None:
        return None
    return cache.get("models", {}).get(model_name)


def refresh_model_cache(force: bool = False) -> None:
    """Fetch model list from OpenRouter and write to disk.

    Skips if cache is less than 7 days old unless *force* is True.
    """
    if not force and _cache_is_fresh():
        logger.debug("Model cache is fresh, skipping refresh")
        return

    try:
        with httpx.Client(base_url="", timeout=30) as client:
            resp = client.get(_OPENROUTER_MODELS_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Failed to refresh model cache: %s", exc)
        return

    models: dict[str, Any] = {}
    for entry in data.get("data", []):
        model_id = entry.get("id", "")
        models[model_id] = {
            "context_length": entry.get("context_length", 0),
            "max_completion_tokens": entry.get("max_completion_tokens", 0),
        }

    cache_data = {
        "fetched_at": time.time(),
        "models": models,
    }

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache_data, indent=2))
    logger.info("Model cache refreshed: %d models", len(models))


def _load_cache() -> dict[str, Any] | None:
    """Load cache from disk, triggering refresh if stale."""
    if not _CACHE_PATH.exists():
        refresh_model_cache()

    if not _CACHE_PATH.exists():
        return None

    try:
        return json.loads(_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read model cache: %s", exc)
        return None


def _cache_is_fresh() -> bool:
    """Return True if cache file exists and is less than 7 days old."""
    if not _CACHE_PATH.exists():
        return False
    try:
        data = json.loads(_CACHE_PATH.read_text())
        age = time.time() - data.get("fetched_at", 0)
        return age < _TTL_SECONDS
    except (json.JSONDecodeError, OSError):
        return False
```

**Step 2: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_model_cache.py -v`
Expected: ALL PASS

---

### Task 7: Write failing tests for get_agent_config

**Files:**
- Modify: `tests/test_config_loader.py`

**Step 1: Write tests**

Add to `tests/test_config_loader.py`:

```python
def test_get_agent_config_returns_model_and_temperature(monkeypatch):
    """get_agent_config resolves model + temperature from hierarchy."""
    from clipper_agency.config.loader import get_agent_config
    # Mock model_cache to avoid API calls
    monkeypatch.setattr(
        "clipper_agency.config.model_cache.get_model_metadata",
        lambda _: {"context_length": 8192, "max_completion_tokens": 4096},
    )
    # Mock settings to use defaults
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    result = get_agent_config("safety")
    assert result["model"] == "glm-4.7-flash"
    assert result["temperature"] == 0.1
    assert result["max_completion_tokens"] == 4096


def test_get_agent_config_env_override(monkeypatch):
    """SAFETY_MODEL env var overrides hierarchy preset."""
    from clipper_agency.config.loader import get_agent_config
    monkeypatch.setattr(
        "clipper_agency.config.model_cache.get_model_metadata",
        lambda _: {"context_length": 8192, "max_completion_tokens": 4096},
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setenv("SAFETY_MODEL", "custom-model")
    result = get_agent_config("safety")
    assert result["model"] == "custom-model"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_config_loader.py::test_get_agent_config_returns_model_and_temperature -v`
Expected: FAIL — `get_agent_config` not found

---

### Task 8: Implement get_agent_config + update hierarchy.py

**Files:**
- Modify: `clipper_agency/config/hierarchy.py:9-18` (remove max_tokens from PRESETS)
- Modify: `clipper_agency/config/loader.py` (add get_agent_config)

**Step 1: Remove max_tokens from hierarchy.py PRESETS**

Edit `clipper_agency/config/hierarchy.py` — remove `max_tokens` from every agent entry in `budget_east` preset. Only `model` and `temperature` remain.

**Step 2: Add get_agent_config to loader.py**

Add to `clipper_agency/config/loader.py`:

```python
def get_agent_config(agent_name: str) -> dict:
    """Resolve agent config: hierarchy preset → model metadata → .env overrides.

    Returns dict with keys: model, temperature, max_completion_tokens.
    """
    from clipper_agency.config.hierarchy import ConfigHierarchy
    from clipper_agency.config.model_cache import get_model_metadata

    # Map agent_name to AppSettings field name for .env overrides
    _SETTINGS_MODEL_MAP = {
        "safety": "safety_model",
        "segment_producer": "researcher_model",
        "scriptwriter": "scriptwriter_model",
        "visual_director": "visual_director_model",
        "reviewer": "reviewer_model",
    }

    hierarchy = ConfigHierarchy()
    model = hierarchy.get(agent_name, "model")
    temperature = hierarchy.get(agent_name, "temperature")

    # .env override for model
    settings = load_settings()
    settings_field = _SETTINGS_MODEL_MAP.get(agent_name)
    if settings_field:
        env_model = getattr(settings, settings_field, None)
        if env_model:
            model = env_model

    # Model metadata from cache
    max_completion_tokens = None
    if model:
        meta = get_model_metadata(model)
        if meta and meta.get("max_completion_tokens"):
            max_completion_tokens = meta["max_completion_tokens"]

    return {
        "model": model,
        "temperature": temperature if temperature is not None else 0.7,
        "max_completion_tokens": max_completion_tokens,
    }
```

**Step 3: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_config_loader.py -v`
Expected: ALL PASS

---

### Task 9: Update OpenRouterClient — max_completion_tokens + reasoning_effort

**Files:**
- Modify: `clipper_agency/llm/client.py:21-60`

**Step 1: Update chat() signature and body**

Change `chat()` method:
- Replace `max_tokens: int = 1024` with `max_completion_tokens: int | None = None`
- Build body dict without max_completion_tokens when None
- Always include `"reasoning_effort": "none"`

```python
def chat(
    self,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_completion_tokens: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    # ... (keep existing validation and logging) ...
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "reasoning_effort": "none",
    }
    if max_completion_tokens is not None:
        body["max_completion_tokens"] = max_completion_tokens
    # Merge kwargs last (allows caller overrides)
    body.update(kwargs)
    # ... (keep existing httpx call and response handling) ...
```

**Step 2: Update existing tests that assert on max_tokens**

Search tests for `max_tokens` in mock call assertions and update to `max_completion_tokens`.

Run: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
Expected: Fix any test failures from the API change, then ALL PASS

---

### Task 10: Update all 5 agents to use get_agent_config

**Files:**
- Modify: `clipper_agency/agents/safety.py:52-66`
- Modify: `clipper_agency/agents/segment_producer.py:400-423`
- Modify: `clipper_agency/agents/scriptwriter.py:163-169`
- Modify: `clipper_agency/agents/visual_director.py:348-363` AND `713-728`
- Modify: `clipper_agency/agents/reviewer.py:180-199`

**Step 1: Update each agent**

For each agent, replace the hardcoded triple with resolved config:

```python
from clipper_agency.config.loader import get_agent_config

# In execute method:
agent_cfg = get_agent_config("safety")  # or "segment_producer", etc.
response = llm.chat(
    model=agent_cfg["model"],
    temperature=agent_cfg["temperature"],
    max_completion_tokens=agent_cfg.get("max_completion_tokens"),
)
```

Remove the `settings.safety_model` (or equivalent) reference — `get_agent_config()` handles .env overrides internally.

**Step 2: Run full test suite**

Run: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
Expected: ALL PASS (990+). Fix any test failures from mock expectations.

---

### Task 11: Commit #6+#9

```bash
git add clipper_agency/config/model_cache.py clipper_agency/config/hierarchy.py \
        clipper_agency/config/loader.py clipper_agency/llm/client.py \
        clipper_agency/agents/safety.py clipper_agency/agents/segment_producer.py \
        clipper_agency/agents/scriptwriter.py clipper_agency/agents/visual_director.py \
        clipper_agency/agents/reviewer.py tests/test_model_cache.py \
        tests/test_config_loader.py tests/test_logging.py
git commit -m "feat: config overhaul — hierarchy + OpenRouter metadata + reasoning_effort (#6+#9)"
```

---

## Commit 3: #7+#8 — Logging Improvements

### Task 12: Write failing tests for logging additions

**Files:**
- Modify: `tests/test_logging.py`

**Step 1: Write tests**

```python
def test_third_party_filter_tags_library_logs():
    """Third-party logger names get [LIB] prefix."""
    from clipper_agency.core.logging import ThirdPartyLogFilter
    import logging

    filt = ThirdPartyLogFilter()
    record = logging.LogRecord("httpcore.connection", logging.DEBUG, "", 0, "msg", (), None)
    filt.filter(record)
    assert "[LIB]" in record.getMessage()


def test_third_party_filter_no_tag_for_pipeline_logs():
    """Pipeline logger names are NOT tagged."""
    from clipper_agency.core.logging import ThirdPartyLogFilter
    import logging

    filt = ThirdPartyLogFilter()
    record = logging.LogRecord("clipper_agency.agents.safety", logging.DEBUG, "", 0, "msg", (), None)
    filt.filter(record)
    assert "[LIB]" not in record.getMessage()


def test_add_job_file_handler_creates_file(tmp_path):
    """add_job_file_handler creates logs/run-job_{id}.log."""
    from clipper_agency.core.logging import add_job_file_handler, remove_job_file_handler
    import logging

    _reset_root_logger()
    setup_logging("DEBUG")
    try:
        add_job_file_handler(42, logs_dir=str(tmp_path / "logs"))
        log_file = tmp_path / "logs" / "run-job_42.log"
        assert log_file.parent.exists()
        remove_job_file_handler()
    finally:
        _reset_root_logger()
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_logging.py -v`
Expected: FAIL — `ThirdPartyLogFilter` not found

---

### Task 13: Implement ThirdPartyLogFilter + add_job_file_handler

**Files:**
- Modify: `clipper_agency/core/logging.py`

**Step 1: Add ThirdPartyLogFilter and file handler functions**

```python
class ThirdPartyLogFilter(logging.Filter):
    """Prepend [LIB] to third-party library log messages."""

    THIRD_PARTY_PREFIXES = ("httpcore.", "httpx.", "urllib3.")

    def filter(self, record: logging.LogRecord) -> bool:
        if any(record.name.startswith(p) for p in self.THIRD_PARTY_PREFIXES):
            record.msg = f"[LIB] {record.msg}"
        return True


def add_job_file_handler(job_id: int, logs_dir: str = "logs") -> None:
    """Add a FileHandler writing per-job logs to {logs_dir}/run-job_{job_id}.log."""
    from pathlib import Path

    log_dir = Path(logs_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run-job_{job_id}.log"

    handler = logging.FileHandler(str(log_file))
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    handler.addFilter(ThirdPartyLogFilter())
    logging.getLogger().addHandler(handler)


def remove_job_file_handler() -> None:
    """Remove the last FileHandler added by add_job_file_handler."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            root.removeHandler(handler)
            handler.close()
            return
```

**Step 2: Wire ThirdPartyLogFilter into setup_logging()**

In `setup_logging()`, after creating the handler, add:
```python
handler.addFilter(ThirdPartyLogFilter())
```

**Step 3: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_logging.py -v`
Expected: ALL PASS

---

### Task 14: Wire add_job_file_handler in engine.py

**Files:**
- Modify: `clipper_agency/orchestrator/engine.py:163` and `448-449`

**Step 1: Add logging hooks**

After `logger.info("Job #%d created", job_id)` at line 163, add:
```python
from clipper_agency.core.logging import add_job_file_handler, remove_job_file_handler
add_job_file_handler(job_id)
```

Before `return {"status": "completed", ...}` at line 450, add:
```python
remove_job_file_handler()
```

Also add `remove_job_file_handler()` before the failed return at line 466 (in the except block).

**Step 2: Run full test suite**

Run: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
Expected: ALL PASS

---

### Task 15: Commit #7+#8

```bash
git add clipper_agency/core/logging.py clipper_agency/orchestrator/engine.py tests/test_logging.py
git commit -m "feat: per-job log files + third-party log tagging (#7+#8)"
```

---

## Commit 4: #10 — TTS Chunking Safety Net

### Task 16: Write failing tests for chunk_text and stitch_timestamps

**Files:**
- Modify: `tests/test_voice_producer.py`

**Step 1: Write tests**

```python
def test_chunk_text_splits_at_sentence_boundaries():
    """Text is split at sentence boundaries respecting word budget."""
    from clipper_agency.agents.voice_producer import _chunk_text

    text = "First sentence here. Second sentence goes on. Third one is short."
    chunks = _chunk_text(text, chunk_size_words=4)

    assert len(chunks) >= 2
    # Each chunk should be <= 4 words (approximately)
    for chunk in chunks:
        assert len(chunk.split()) <= 8  # Allow some slack for sentence integrity


def test_chunk_text_short_text_returns_single():
    """Text shorter than chunk_size returns a single chunk."""
    from clipper_agency.agents.voice_producer import _chunk_text

    text = "Short text here."
    chunks = _chunk_text(text, chunk_size_words=250)

    assert len(chunks) == 1
    assert chunks[0] == text


def test_stitch_timestamps_adds_cumulative_offset():
    """Timestamps from later chunks get cumulative audio offset."""
    from clipper_agency.agents.voice_producer import VoiceProducerAgent

    agent = VoiceProducerAgent()
    chunk_ts = [
        [{"word": "hello", "start": 0.0, "end": 0.5}],
        [{"word": "world", "start": 0.0, "end": 0.5}],
    ]
    chunk_durations = [10.0, 10.0]

    result = agent._stitch_timestamps(chunk_ts, chunk_durations)

    assert len(result) == 2
    assert result[0]["start"] == 0.0
    assert result[1]["start"] == pytest.approx(10.0)
    assert result[1]["end"] == pytest.approx(10.5)
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_voice_producer.py::test_chunk_text_splits_at_sentence_boundaries -v`
Expected: FAIL — `_chunk_text` not found

---

### Task 17: Expose char limits from TTS services

**Files:**
- Modify: `clipper_agency/services/elevenlabs.py` — add `CHAR_LIMIT = 10_000`
- Modify: `clipper_agency/services/gemini_tts.py` — add `CHAR_LIMIT = 5_000`
- Modify: `clipper_agency/services/fish_audio.py` — add `CHAR_LIMIT = 5_000`

**Step 1: Add constants**

In each service file, add the constant at module level (after imports):

```python
# TTS character limit for this provider
CHAR_LIMIT = 10_000  # elevenlabs.py
CHAR_LIMIT = 5_000   # gemini_tts.py
CHAR_LIMIT = 5_000   # fish_audio.py
```

---

### Task 18: Implement chunking functions in voice_producer

**Files:**
- Modify: `clipper_agency/agents/voice_producer.py`

**Step 1: Add provider char limits mapping**

```python
# Provider character limits (from service constants)
_PROVIDER_CHAR_LIMITS: dict[str, int] = {
    "elevenlabs": 10_000,
    "gemini_tts": 5_000,
    "fish_audio": 5_000,
}
```

**Step 2: Add _chunk_text function**

```python
def _chunk_text(text: str, chunk_size_words: int = 250) -> list[str]:
    """Split text at sentence boundaries into chunks of ~chunk_size_words."""
    import re

    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_words = 0

    for sentence in sentences:
        words = sentence.split()
        if current_words + len(words) > chunk_size_words and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_words = 0
        current_chunk.append(sentence)
        current_words += len(words)

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text]
```

**Step 3: Add _stitch_timestamps method**

```python
def _stitch_timestamps(
    self,
    chunk_timestamps: list[list[dict]],
    chunk_durations: list[float],
) -> list[dict]:
    """Merge per-chunk timestamps with cumulative audio offsets."""
    stitched: list[dict] = []
    offset = 0.0

    for chunk_ts, duration in zip(chunk_timestamps, chunk_durations):
        for ts in chunk_ts:
            stitched.append({
                "word": ts["word"],
                "start": ts["start"] + offset,
                "end": ts["end"] + offset,
            })
        offset += duration

    return stitched
```

**Step 4: Add _concat_audio_chunks method**

```python
def _concat_audio_chunks(self, chunk_paths: list[str], output_path: str) -> str:
    """Concatenate audio chunks using FFmpeg demuxer."""
    import tempfile
    from pathlib import Path

    list_file = Path(tempfile.mktemp(suffix=".txt"))
    with open(list_file, "w") as f:
        for path in chunk_paths:
            f.write(f"file '{path}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", output_path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    list_file.unlink(missing_ok=True)
    return output_path
```

**Step 5: Add _generate_chunked_voiceover method**

```python
def _generate_chunked_voiceover(
    self,
    text: str,
    voice_id: str | None,
    job_id: int,
    assets_cache: str,
    provider: str,
) -> dict[str, Any]:
    """Generate voiceover by chunking text, generating per-chunk, then concatenating."""
    chunks = _chunk_text(text)
    logger.warning("Voice: chunking %d chars into %d chunks", len(text), len(chunks))

    chunk_paths: list[str] = []
    chunk_timestamps: list[list[dict]] = []
    chunk_durations: list[float] = []

    output_dir = os.path.dirname(self._voiceover_output_path(job_id, assets_cache))

    for i, chunk in enumerate(chunks):
        chunk_path = os.path.join(output_dir, f"chunk_{i:03d}.mp3")

        if provider == "elevenlabs":
            service = self._create_service("elevenlabs")
            audio_bytes, char_ts = service.generate_voice_with_timestamps(chunk, voice_id or "")
            with open(chunk_path, "wb") as f:
                f.write(audio_bytes)
            word_ts = self._extract_word_timestamps(char_ts, chunk)
        else:
            service = self._create_service(provider)
            service.generate_voice(chunk, voice_id or "", chunk_path)
            word_ts = self._approximate_timestamps(chunk_path, chunk)

        chunk_paths.append(chunk_path)
        chunk_timestamps.append(word_ts)
        chunk_durations.append(self._probe_audio_duration(chunk_path))

    # Concatenate audio
    final_path = self._voiceover_output_path(job_id, assets_cache)
    self._concat_audio_chunks(chunk_paths, final_path)

    # Stitch timestamps
    stitched = self._stitch_timestamps(chunk_timestamps, chunk_durations)

    return {
        "status": "success",
        "voiceover_path": final_path,
        "timestamps": stitched,
        "provider": provider,
    }
```

**Step 6: Wire pre-flight check into _generate_continuous_voiceover**

In `_generate_continuous_voiceover()`, before the provider try/except loop, add:

```python
char_limit = _PROVIDER_CHAR_LIMITS.get(provider, 5000)
```

Then inside the try block, before calling the provider:

```python
if len(text) > char_limit:
    logger.warning(
        "Voice: text (%d chars) exceeds %s limit (%d), chunking",
        len(text), provider, char_limit,
    )
    result = self._generate_chunked_voiceover(
        text, resolved_voice, job_id, assets_cache, provider,
    )
else:
    # ... existing single-call logic ...
```

**Step 7: Run full test suite**

Run: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
Expected: ALL PASS

---

### Task 19: Commit #10

```bash
git add clipper_agency/agents/voice_producer.py clipper_agency/services/elevenlabs.py \
        clipper_agency/services/gemini_tts.py clipper_agency/services/fish_audio.py \
        tests/test_voice_producer.py
git commit -m "feat: TTS chunking safety net for long scripts (#10)"
```

---

## Post-Commit: ADR Document

### Task 20: Write ADR 0022

**Files:**
- Create: `docs/adr/0022-config-overhaul-chunking-safety-net.md`

**Step 1: Write ADR**

```markdown
# ADR 0022: Config Overhaul + TTS Chunking Safety Net

**Date:** 2026-06-07
**Status:** Accepted
**Supersedes:** ADR 0007 (Per-Agent Model Config)

## Context

ADR 0021 introduced the audio-first architecture. During implementation, two systemic issues emerged:

1. **Dead config hierarchy** — `ConfigHierarchy` in `hierarchy.py` defined per-agent model/temperature/max_tokens but no file imported it. Agents hardcoded values directly in LLM calls, causing `max_tokens` truncation (segment_producer 1024 → `story_beats=[]` → 67-word script → 27s video instead of 60s).

2. **No TTS overflow protection** — When script text exceeds a TTS provider's character budget, the call fails silently or truncates. No fallback mechanism existed.

## Decision

### Config Resolution Chain (#6+#9)

Replace 10 hardcoded values across 5 agents with a single resolution chain:

```
hierarchy.py preset → model + temperature
        ↓ merge
OpenRouter model metadata → max_completion_tokens (auto-fetched, cached 7 days)
        ↓ merge
.env overrides → {AGENT}_MODEL, {AGENT}_TEMPERATURE
        ↓
get_agent_config("agent_name") → resolved config dict
```

Key rules:
- **Remove `max_tokens` from hierarchy.py** — system determines from OpenRouter model metadata (free API, no auth).
- **Always send `reasoning_effort: "none"`** — prevents invisible reasoning tokens, saves cost. Unsupported params silently ignored per OpenRouter docs.
- **Lazy-load model cache** — first call triggers fetch, 7-day TTL, auto-refresh.

### TTS Chunking as Fallback Only (#10)

Default path: single TTS call (zero overhead). Chunking activates only when text exceeds provider char budget:

- ElevenLabs Multilingual v2: 10,000 chars
- Gemini TTS: 5,000 chars (practical)
- Fish Audio: 5,000 chars (placeholder)

Chunking algorithm: sentence-boundary split → ~250 words/chunk → generate per-chunk → FFmpeg concat → stitch timestamps with cumulative offset.

## Alternatives Considered

### Keep hardcoded max_tokens
- **Pros:** No new code, simple.
- **Cons:** Already caused truncation bug. Values are guesses. Models have different limits. No way to adapt when models change.

### Set max_tokens = model max
- **Pros:** Simple, no truncation.
- **Cons:** Wastes tokens on models with 65k max_completion_tokens. Cost is per-token, so no real waste — but sends unnecessarily large values.

### Always chunk TTS
- **Pros:** No overflow ever.
- **Cons:** Unnecessary complexity + latency for MVP. TikTok ≤60s ≈ 150 words ≈ 1,000 chars — well under all limits.

## Consequences

- **Positive:** Single source of truth for agent config — one change in hierarchy.py propagates everywhere.
- **Positive:** Auto-determined max_completion_tokens from OpenRouter — no more truncation from hardcoded guesses.
- **Positive:** `reasoning_effort: "none"` saves ~20-40% per LLM call (no invisible thinking tokens).
- **Positive:** TTS chunking safety net prevents silent failures on long scripts.
- **Negative:** OpenRouter API dependency for model metadata (mitigated: cached locally, 7-day TTL, graceful fallback to None).
- **Negative:** Slightly more complex config resolution chain (3 layers instead of hardcoded values).
- **Neutral:** Model cache adds ~1s to first pipeline run (subsequent runs use cache).
```

**Step 2: Commit ADR**

```bash
git add docs/adr/0022-config-overhaul-chunking-safety-net.md
git commit -m "docs: ADR 0022 — config overhaul + TTS chunking safety net"
```

---

## Final Verification

### Task 21: Run full test suite + push

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
git push origin phase/audio-first-continuous-voiceover
```

Wait for SonarCloud to pass on PR #41.

---

## Post-Implementation Checklist

1. Re-run pipeline: `rm -rf data/assets/cache data/clipper.db data/outputs && .venv/bin/python3 -m clipper_agency run -t "Gosip artis Indonesia terbaru" -n indonesian_artists`
2. Verify: story_beats populated, captions visible, no hook duplication, per-job log at `logs/run-job_{id}.log` created, no voice truncation
3. Update `docs/fixes-pending.md` — mark all fixes as DONE
4. Update `AGENTS.md` Repository State section
5. Merge PR #41 → master (no squash)
6. Tag v2.0.0 → GitHub Release
