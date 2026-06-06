# Tier 4: Timeline-Aware Agent Orchestration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an Orchestrator-owned canonical timeline contract so every downstream agent obeys one shared timing source-of-truth instead of guessing durations independently.

**Architecture:** Researcher extends its existing LLM synthesis to include `content_direction` (format recommendation + story selection). Orchestrator validates that direction deterministically, enforces word/time budgets on Scriptwriter, measures actual audio durations from Voice Producer, then creates a canonical timeline via a new `TimelineReconciler` service. Visual Director and Composer consume the timeline instead of raw script/asset durations. G10 duration limits become configurable. Retry paths are fixed to pass `script_scenes` + timeline artifacts.

**Tech Stack:** Python data‑classes, PyYAML for config, `ffprobe` for audio duration, existing OpenRouter/FFmpeg stack.

---

## Batch 0 — Foundation (parallel: 3 tasks, zero shared files)

### Task 0a: Content Planning Config Schema

**Files:**
- Modify: `clipper_agency/config/schema.py` (add `ContentPlanningConfig` model)
- Modify: `niches/indonesian_artists.yaml` (add `content_planning` block)

**Step 1: Write the failing test**

Create `tests/config/test_content_planning_schema.py`:

```python
from clipper_agency.config.schema import ContentPlanningConfig


class TestContentPlanningConfig:
    def test_defaults(self):
        cfg = ContentPlanningConfig()
        assert cfg.default_format == "three_story_roundup"
        assert cfg.max_stories_per_video == 3
        assert cfg.target_duration_sec == 55
        assert cfg.hard_limit_sec == 60
        assert cfg.estimated_words_per_second == 2.0

    def test_override_from_dict(self):
        cfg = ContentPlanningConfig(**{
            "default_format": "single_story_deep",
            "max_stories_per_video": 1,
            "target_duration_sec": 50,
            "hard_limit_sec": 55,
            "estimated_words_per_second": 1.8,
        })
        assert cfg.default_format == "single_story_deep"
        assert cfg.target_duration_sec == 50

    def test_enforces_positive(self):
        from pydantic import ValidationError
        try:
            ContentPlanningConfig(target_duration_sec=-1)
        except ValidationError:
            pass  # expected
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python3 -m pytest tests/config/test_content_planning_schema.py -v
```
Expected: FAIL — `ContentPlanningConfig` not defined.

**Step 3: Write minimal implementation**

Add to `clipper_agency/config/schema.py`:

```python
from pydantic import BaseModel, Field


class ContentPlanningConfig(BaseModel):
    default_format: str = Field("three_story_roundup")
    max_stories_per_video: int = Field(3, ge=1, le=10)
    target_duration_sec: int = Field(55, ge=20, le=300)
    hard_limit_sec: int = Field(60, ge=20, le=300)
    estimated_words_per_second: float = Field(2.0, ge=0.5, le=5.0)
```

Add to `AppSettings`:

```python
    content_planning: ContentPlanningConfig = Field(
        default_factory=ContentPlanningConfig
    )
```

**Step 4: Run test to verify it passes**

```bash
.venv/bin/python3 -m pytest tests/config/test_content_planning_schema.py -v
```
Expected: 3 passed.

**Step 5: Update `niches/indonesian_artists.yaml`**

```yaml
content_planning:
  default_format: three_story_roundup
  max_stories_per_video: 3
  target_duration_sec: 55
  hard_limit_sec: 60
  estimated_words_per_second: 2.0
```

**Step 6: Test niche YAML loads config**

```python
def test_niche_loads_content_planning():
    from clipper_agency.config.loader import load_niche_config
    niche = load_niche_config("indonesian_artists")
    cp = niche.get("content_planning", {})
    assert cp.get("default_format") == "three_story_roundup"
    assert cp.get("max_stories_per_video") == 3
```

**Step 7: Commit**

```bash
git add clipper_agency/config/schema.py niches/indonesian_artists.yaml tests/config/test_content_planning_schema.py
git commit -m "feat(config): add ContentPlanningConfig schema and niche defaults"
```

---

### Task 0b: Researcher Content Direction

**Files:**
- Modify: `clipper_agency/agents/researcher.py` (extend synthesis prompt, parse `content_direction`)
- Create: `tests/agents/test_researcher_content_direction.py`

**Step 1: Write the failing test**

```python
import json
from unittest.mock import MagicMock, patch

from clipper_agency.agents.researcher import ResearcherAgent


class TestResearcherContentDirection:
    def test_parse_content_direction_from_llm_response(self):
        agent = ResearcherAgent()
        raw = json.dumps({
            "research_brief": "Three safe stories found.",
            "content_direction": {
                "recommended_format": "three_story_roundup",
                "reason": "Three distinct stories with similar viral potential.",
                "selected_story_count": 3,
                "selected_stories": ["story_a", "story_b", "story_c"],
                "content_angle": "fast gossip roundup",
                "risk_notes": ["Use cautious wording for unverified claims."],
            },
        })
        result = agent._parse_synthesis_response(raw)
        assert result["content_direction"]["recommended_format"] == "three_story_roundup"
        assert result["content_direction"]["selected_story_count"] == 3
        assert len(result["content_direction"]["selected_stories"]) == 3
        assert "risk_notes" in result["content_direction"]

    def test_missing_content_direction_returns_none(self):
        agent = ResearcherAgent()
        raw = json.dumps({"research_brief": "Just a brief. No direction."})
        result = agent._parse_synthesis_response(raw)
        assert result.get("content_direction") is None
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python3 -m pytest tests/agents/test_researcher_content_direction.py -v
```
Expected: FAIL — `_parse_synthesis_response` doesn't exist yet.

**Step 3: Implement `_parse_synthesis_response` in `researcher.py`**

Add method:

```python
def _parse_synthesis_response(self, content: str) -> dict[str, Any]:
    try:
        stripped = content.strip().strip("```json").strip("```").strip()
        data = json.loads(stripped)
        return {
            "research_brief": data.get("research_brief", ""),
            "content_direction": data.get("content_direction"),
        }
    except (json.JSONDecodeError, KeyError):
        return {"research_brief": content, "content_direction": None}
```

Update `_synthesize_research` to use new parser:

```python
    response = llm.chat(...)
    parsed = self._parse_synthesis_response(response["content"])
    return {
        "research_brief": parsed["research_brief"],
        "content_direction": parsed.get("content_direction"),
        "source_count": len(sources),
    }
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_researcher_content_direction.py -v
```
Expected: 2 passed.

**Step 5: Update Researcher prompt in `RESEARCH_PROMPT`**

Add to prompt template (after "Return a concise research brief..."):

```
5. Content direction — recommend the best approach for this content:
   return a "content_direction" field with:
     - "recommended_format": one of "three_story_roundup", "single_story_deep", or "rapid_bulletin"
     - "reason": brief explanation
     - "selected_story_count": number (1-6)
     - "selected_stories": list of story slugs or headlines
     - "content_angle": suggested angle for Scriptwriter
     - "risk_notes": any safety/caution notes
```

**Step 6: Commit**

```bash
git add clipper_agency/agents/researcher.py tests/agents/test_researcher_content_direction.py
git commit -m "feat(researcher): add content_direction to LLM synthesis output"
```

---

### Task 0c: Voice Producer Audio Duration Metadata

**Files:**
- Modify: `clipper_agency/agents/voice_producer.py` (measure duration with ffprobe, return `audio_metadata`)
- Create: `tests/agents/test_voice_producer_duration_metadata.py`

**Step 1: Write the failing test**

```python
import json
import os
from unittest.mock import patch

from clipper_agency.agents.voice_producer import VoiceProducerAgent


class TestVoiceProducerDurationMetadata:
    def test_build_audio_metadata(self, tmp_path):
        """_build_audio_metadata creates per-scene duration records."""
        agent = VoiceProducerAgent()
        output_dir = str(tmp_path)
        voices_dir = os.path.join(output_dir, "voices")
        os.makedirs(voices_dir)
        for i in range(1, 4):
            path = os.path.join(voices_dir, f"scene_{i}.mp3")
            with open(path, "wb") as f:
                f.write(b"\x00" * 1024)

        meta = agent._build_audio_metadata(output_dir, scene_count=3)
        assert len(meta) == 3
        assert meta[0]["scene"] == 1
        assert "audio_duration_sec" in meta[0]
        assert "audio_path" in meta[0]
        assert "provider" in meta[0]

    def test_missing_audio_returns_empty(self):
        agent = VoiceProducerAgent()
        meta = agent._build_audio_metadata("/nonexistent", scene_count=3)
        assert meta == []

    @patch("subprocess.run")
    def test_parse_ffprobe_duration(self, mock_run, tmp_path):
        """_probe_audio_duration returns float seconds or 0.0 on failure."""
        agent = VoiceProducerAgent()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps({
            "format": {"duration": "12.345"}
        })
        dur = agent._probe_audio_duration("/fake/audio.mp3")
        assert dur == 12.345
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python3 -m pytest tests/agents/test_voice_producer_duration_metadata.py -v
```
Expected: FAIL — methods don't exist.

**Step 3: Implement in `voice_producer.py`**

Add `_build_audio_metadata` method:

```python
def _build_audio_metadata(self, output_dir: str, scene_count: int, provider: str = "") -> list[dict]:
    voices_dir = os.path.join(output_dir, "voices")
    meta_list: list[dict] = []
    for i in range(1, scene_count + 1):
        path = os.path.join(voices_dir, f"scene_{i}.mp3")
        duration = self._probe_audio_duration(path)
        meta_list.append({
            "scene": i,
            "audio_path": path,
            "audio_duration_sec": duration,
            "provider": provider,
        })
    return meta_list
```

Add `_probe_audio_duration` method:

```python
import json
import subprocess


def _probe_audio_duration(self, filepath: str) -> float:
    if not os.path.exists(filepath):
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", filepath],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0.0
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0.0))
    except Exception:
        return 0.0
```

Update `execute` return dict to include `audio_metadata`:

```python
    audio_meta = self._build_audio_metadata(output_dir, scene_count, provider)
    result = {
        "status": "completed",
        "audio_files": audio_files,
        "audio_metadata": audio_meta,
        ...
    }
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_voice_producer_duration_metadata.py -v
```
Expected: 3 passed.

**Step 5: Commit**

```bash
git add clipper_agency/agents/voice_producer.py tests/agents/test_voice_producer_duration_metadata.py
git commit -m "feat(voice_producer): add audio duration metadata with ffprobe"
```

---

## Batch 0 — Verification

```bash
.venv/bin/python3 -m pytest tests/config/test_content_planning_schema.py tests/agents/test_researcher_content_direction.py tests/agents/test_voice_producer_duration_metadata.py -v
```

Expected: 8 passed total. Coverage must not drop. Then full suite:

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all existing 783 tests still pass, plus 8 new.

---

## Batch 1 — Orchestrator Services (sequential: each touches orchestrator)

### Task 1a: Format Validator

**Files:**
- Create: `clipper_agency/orchestrator/validator.py`
- Modify: `clipper_agency/orchestrator/engine.py` (call validator after Researcher)
- Create: `tests/orchestrator/test_format_validator.py`

**Step 1: Write the failing test**

```python
import pytest
from clipper_agency.orchestrator.validator import (
    ContentPlanningConfig,
    validate_content_direction,
    ValidationError,
)


class TestFormatValidator:
    def test_valid_direction_passes(self):
        cfg = ContentPlanningConfig()
        direction = {
            "recommended_format": "three_story_roundup",
            "selected_story_count": 3,
            "selected_stories": ["a", "b", "c"],
        }
        result = validate_content_direction(direction, cfg)
        assert result["format"] == "three_story_roundup"
        assert result["story_count"] == 3

    def test_unknown_format_falls_back_to_default(self):
        cfg = ContentPlanningConfig(default_format="three_story_roundup")
        direction = {"recommended_format": "unknown_format"}
        result = validate_content_direction(direction, cfg)
        assert result["format"] == "three_story_roundup"

    def test_too_many_stories_clamped(self):
        cfg = ContentPlanningConfig(max_stories_per_video=3)
        direction = {
            "recommended_format": "three_story_roundup",
            "selected_story_count": 10,
            "selected_stories": ["a"] * 10,
        }
        result = validate_content_direction(direction, cfg)
        assert result["story_count"] == 3
        assert len(result["stories"]) == 3

    def test_missing_direction_uses_fallback(self):
        cfg = ContentPlanningConfig()
        result = validate_content_direction(None, cfg)
        assert result["format"] == "three_story_roundup"
        assert result["story_count"] == 3
        assert result["fallback"] is True

    def test_empty_stories_uses_fallback(self):
        cfg = ContentPlanningConfig(max_stories_per_video=3)
        direction = {
            "recommended_format": "three_story_roundup",
            "selected_story_count": 0,
            "selected_stories": [],
        }
        result = validate_content_direction(direction, cfg)
        assert result["story_count"] == 3  # fallback
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_format_validator.py -v
```
Expected: FAIL — module doesn't exist.

**Step 3: Implement `clipper_agency/orchestrator/validator.py`**

```python
from dataclasses import dataclass, field
from clipper_agency.config.schema import ContentPlanningConfig

VALID_FORMATS = {"three_story_roundup", "single_story_deep", "rapid_bulletin"}


@dataclass
class ContentDirectionResult:
    format: str
    story_count: int
    stories: list[str] = field(default_factory=list)
    content_angle: str = ""
    fallback: bool = False


def validate_content_direction(
    direction: dict | None,
    config: ContentPlanningConfig,
) -> ContentDirectionResult:
    if direction is None:
        return ContentDirectionResult(
            format=config.default_format,
            story_count=config.max_stories_per_video,
            fallback=True,
        )
    fmt = direction.get("recommended_format", "")
    if fmt not in VALID_FORMATS:
        fmt = config.default_format
    count = direction.get("selected_story_count", 0) or config.max_stories_per_video
    count = min(max(1, count), config.max_stories_per_video)
    stories = list(direction.get("selected_stories", []) or [])
    stories = stories[:count]
    return ContentDirectionResult(
        format=fmt,
        story_count=count,
        stories=stories,
        content_angle=direction.get("content_angle", ""),
        fallback=(direction is not None and count != direction.get("selected_story_count", 0)),
    )
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_format_validator.py -v
```
Expected: 5 passed.

**Step 5: Integrate into Orchestrator engine**

In `engine.py`, after Researcher stage, call:

```python
cp_config = load_settings().content_planning
direction = researcher_output.get("content_direction")
validated = validate_content_direction(direction, cp_config)
# store validated in job context for downstream use
```

**Step 6: Commit**

```bash
git add clipper_agency/orchestrator/validator.py clipper_agency/orchestrator/engine.py tests/orchestrator/test_format_validator.py
git commit -m "feat(orchestrator): add format validator for content direction"
```

---

### Task 1b: Script Duration Gate

**Files:**
- Create: `clipper_agency/orchestrator/duration_gate.py`
- Create: `tests/orchestrator/test_duration_gate.py`
- Modify: `clipper_agency/orchestrator/engine.py`

**Step 1: Write the failing test**

```python
from clipper_agency.orchestrator.duration_gate import (
    estimate_script_duration_sec,
    check_script_duration_budget,
    DurationBudget,
)


class TestScriptDurationGate:
    def test_estimate_from_word_count(self):
        scenes = [
            {"word_count": 10, "text": "short"},
            {"word_count": 22, "text": "medium"},
            {"word_count": 10, "text": "cta"},
        ]
        dur = estimate_script_duration_sec(scenes, words_per_sec=2.0, pause_buffer=0.5)
        # (10+22+10)/2.0 + 0.5*3 = 21 + 1.5 = 22.5
        assert dur == 22.5

    def test_missing_word_count_falls_back_to_text_tokens(self):
        scenes = [{"text": "short intro text here"}]
        dur = estimate_script_duration_sec(scenes, words_per_sec=2.0, pause_buffer=0.5)
        assert dur > 0

    def test_within_budget_passes(self):
        budget = DurationBudget(target=55, hard=60)
        result = check_script_duration_budget(estimated_sec=45, budget=budget)
        assert result["pass"] is True
        assert result["reason"] == "within_target"

    def test_exceeds_target_but_not_hard_warns(self):
        budget = DurationBudget(target=55, hard=60)
        result = check_script_duration_budget(estimated_sec=57, budget=budget)
        assert result["pass"] is True
        assert result["reason"] == "exceeds_target"

    def test_exceeds_hard_limit_fails(self):
        budget = DurationBudget(target=55, hard=60)
        result = check_script_duration_budget(estimated_sec=65, budget=budget)
        assert result["pass"] is False
        assert "exceeds_hard_limit" in result["reason"]
```

**Step 2: Run test**

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_duration_gate.py -v
```
Expected: FAIL — module doesn't exist.

**Step 3: Implement `clipper_agency/orchestrator/duration_gate.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DurationBudget:
    target: int
    hard: int


def estimate_script_duration_sec(
    scenes: list[dict],
    words_per_sec: float = 2.0,
    pause_buffer: float = 0.5,
) -> float:
    total_words = 0
    scene_count = len(scenes)
    for s in scenes:
        wc = s.get("word_count")
        if wc is None or wc <= 0:
            text = s.get("text", "")
            wc = len(text.split()) if text else 0
        total_words += wc
    return (total_words / words_per_sec) + (pause_buffer * scene_count)


def check_script_duration_budget(
    estimated_sec: float,
    budget: DurationBudget,
) -> dict:
    if estimated_sec <= budget.target:
        return {"pass": True, "reason": "within_target"}
    if estimated_sec <= budget.hard:
        return {"pass": True, "reason": "exceeds_target"}
    return {"pass": False, "reason": "exceeds_hard_limit"}
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_duration_gate.py -v
```
Expected: 5 passed.

**Step 5: Integrate into orchestrator after Scriptwriter**

```python
from clipper_agency.orchestrator.duration_gate import (
    DurationBudget, estimate_script_duration_sec, check_script_duration_budget,
)

cp_config = load_settings().content_planning
budget = DurationBudget(target=cp_config.target_duration_sec, hard=cp_config.hard_limit_sec)
estimated = estimate_script_duration_sec(script_output["script"], words_per_sec=cp_config.estimated_words_per_second)
gate = check_script_duration_budget(estimated, budget)
if not gate["pass"]:
    # fail job early
    ...
```

**Step 6: Commit**

```bash
git add clipper_agency/orchestrator/duration_gate.py clipper_agency/orchestrator/engine.py tests/orchestrator/test_duration_gate.py
git commit -m "feat(orchestrator): add script duration gate before TTS"
```

---

### Task 1c: Timeline Reconciler

**Files:**
- Create: `clipper_agency/orchestrator/timeline.py`
- Create: `tests/orchestrator/test_timeline_reconciler.py`

**Step 1: Write the failing test**

```python
from clipper_agency.orchestrator.timeline import (
    reconcile_timeline,
    TimelineItem,
    ReconciledTimeline,
)


class TestTimelineReconciler:
    def test_basic_reconciliation(self):
        scenes = [
            {"scene": 1, "role": "opening_hook", "text": "hello", "estimated_duration_sec": 5},
            {"scene": 2, "role": "story_1", "text": "story", "estimated_duration_sec": 10},
            {"scene": 3, "role": "cta", "text": "follow", "estimated_duration_sec": 5},
        ]
        audio_meta = [
            {"scene": 1, "audio_duration_sec": 8.7, "audio_path": "s1.mp3", "provider": "el"},
            {"scene": 2, "audio_duration_sec": 12.1, "audio_path": "s2.mp3", "provider": "el"},
            {"scene": 3, "audio_duration_sec": 6.3, "audio_path": "s3.mp3", "provider": "el"},
        ]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)

        assert result.within_limit is True
        assert result.total_duration_sec == 27.1
        assert result.timeline[0].role == "opening_hook"
        assert result.timeline[0].start_sec == 0.0
        assert result.timeline[0].end_sec == 8.7
        assert result.timeline[1].start_sec == 8.7
        assert result.timeline[2].start_sec == 20.8

    def test_exceeds_hard_limit(self):
        scenes = [{"scene": 1, "role": "opening_hook", "text": "x", "estimated_duration_sec": 1}]
        audio_meta = [{"scene": 1, "audio_duration_sec": 65.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert result.within_limit is False

    def test_fewer_audio_than_scenes(self):
        scenes = [
            {"scene": 1, "role": "opening_hook", "text": "a", "estimated_duration_sec": 5},
            {"scene": 2, "role": "story_1", "text": "b", "estimated_duration_sec": 5},
        ]
        audio_meta = [{"scene": 1, "audio_duration_sec": 5.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert result.within_limit is True
        assert len(result.timeline) == 2
        assert result.timeline[0].target_duration_sec == 5.0  # from audio
        assert result.timeline[1].target_duration_sec == 5.0  # from estimate

    def test_visual_instruction_for_opening_hook(self):
        scenes = [{"scene": 1, "role": "opening_hook", "text": "x", "estimated_duration_sec": 4}]
        audio_meta = [{"scene": 1, "audio_duration_sec": 4.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert "opening card" in result.timeline[0].visual_instruction

    def test_visual_instruction_for_cta(self):
        scenes = [{"scene": 1, "role": "cta", "text": "x", "estimated_duration_sec": 4}]
        audio_meta = [{"scene": 1, "audio_duration_sec": 4.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert "cta card" in result.timeline[0].visual_instruction.lower()
```

**Step 2: Run test**

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_timeline_reconciler.py -v
```
Expected: FAIL — module doesn't exist.

**Step 3: Implement `clipper_agency/orchestrator/timeline.py`**

```python
from dataclasses import dataclass, field


@dataclass
class TimelineItem:
    scene: int
    role: str
    text: str = ""
    audio_path: str = ""
    audio_duration_sec: float = 0.0
    start_sec: float = 0.0
    end_sec: float = 0.0
    target_duration_sec: float = 0.0
    visual_instruction: str = ""


@dataclass
class ReconciledTimeline:
    timeline: list[TimelineItem] = field(default_factory=list)
    total_duration_sec: float = 0.0
    target_duration_sec: int = 55
    hard_limit_sec: int = 60
    within_limit: bool = True


def _visual_instruction_for_role(role: str) -> str:
    if role == "opening_hook":
        return "opening card"
    if role == "cta":
        return "cta card"
    return "standard visual"


def reconcile_timeline(
    scenes: list[dict],
    audio_meta: list[dict],
    target: int = 55,
    hard: int = 60,
) -> ReconciledTimeline:
    audio_by_scene = {a["scene"]: a for a in audio_meta}
    items: list[TimelineItem] = []
    cursor = 0.0

    for sc in scenes:
        scene_num = sc.get("scene", len(items) + 1)
        role = sc.get("role", "body")
        text = sc.get("text", "")
        audio = audio_by_scene.get(scene_num, {})
        duration = audio.get("audio_duration_sec", sc.get("estimated_duration_sec", 5.0))
        duration = max(duration, 0.5)

        items.append(TimelineItem(
            scene=scene_num,
            role=role,
            text=text,
            audio_path=audio.get("audio_path", ""),
            audio_duration_sec=audio.get("audio_duration_sec", 0.0),
            start_sec=cursor,
            end_sec=cursor + duration,
            target_duration_sec=duration,
            visual_instruction=_visual_instruction_for_role(role),
        ))
        cursor += duration

    total = round(cursor, 1)
    return ReconciledTimeline(
        timeline=items,
        total_duration_sec=total,
        target_duration_sec=target,
        hard_limit_sec=hard,
        within_limit=(total <= hard),
    )
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_timeline_reconciler.py -v
```
Expected: 6 passed.

**Step 5: Integrate into Orchestrator engine**

After Voice Producer stage, before Visual Director, call:

```python
timeline = reconcile_timeline(
    script_output["script"],
    voice_output.get("audio_metadata", []),
    target=cp_config.target_duration_sec,
    hard=cp_config.hard_limit_sec,
)
if not timeline.within_limit:
    # fail job — exceed hard limit
    ...
# Store or pass timeline to Visual Director
```

**Step 6: Commit**

```bash
git add clipper_agency/orchestrator/timeline.py clipper_agency/orchestrator/engine.py tests/orchestrator/test_timeline_reconciler.py
git commit -m "feat(orchestrator): add Timeline Reconciler with canonical timeline"
```

---

## Batch 1 — Verification

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_format_validator.py tests/orchestrator/test_duration_gate.py tests/orchestrator/test_timeline_reconciler.py -v
```

Expected: 16 passed.

---

## Batch 2 — Agent Contract Updates (parallel: 3 tasks, zero shared files)

### Task 2a: Scriptwriter Budget Obedience

**Files:**
- Modify: `clipper_agency/agents/scriptwriter.py` (prompt adds role, word_count; parse new fields)
- Create: `tests/agents/test_scriptwriter_budget.py`

**Step 1: Write the failing test**

```python
import json
from clipper_agency.agents.scriptwriter import ScriptwriterAgent


class TestScriptwriterBudget:
    def test_parse_scene_with_role_and_budget(self):
        agent = ScriptwriterAgent()
        raw = json.dumps({
            "script": [
                {
                    "scene": 1,
                    "role": "opening_hook",
                    "text": "HOT GOSSIP ARTIS HARI INI!",
                    "word_count": 5,
                    "estimated_duration_sec": 3.0,
                },
                {
                    "scene": 2,
                    "role": "story_1",
                    "text": "Anji resmi nikah lagi dengan Wina Natalia.",
                    "word_count": 8,
                    "estimated_duration_sec": 5.0,
                },
            ],
            "caption": "Gosip terbaru! 🔥",
            "hashtags": ["#gossip", "#artis"],
            "estimated_duration": 20,
        })
        parsed = agent._parse_script_response(raw)
        assert parsed["script"][0]["role"] == "opening_hook"
        assert parsed["script"][0]["word_count"] == 5
        assert "estimated_duration_sec" in parsed["script"][0]

    def test_missing_role_defaults_to_body(self):
        agent = ScriptwriterAgent()
        raw = json.dumps({
            "script": [
                {"scene": 1, "text": "Hello", "word_count": 3},
            ],
            "caption": "",
            "hashtags": [],
            "estimated_duration": 10,
        })
        parsed = agent._parse_script_response(raw)
        assert parsed["script"][0]["role"] == "body"
```

**Step 2: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_scriptwriter_budget.py -v
```
Expected: FAIL — "body" not returned.

**Step 3: Update `_parse_script_response` and prompt**

Update prompt to include role, word_count, estimated_duration_sec per scene:

```
  "script": [
    {"scene": 1, "role": "opening_hook", "text": "...", "word_count": 10, "estimated_duration_sec": 5.0},
    ...
  ],
```

Update parser:

```python
    for sc in data.get("script", []):
        if "role" not in sc:
            sc["role"] = "body"
        if "estimated_duration_sec" not in sc and "duration" in sc:
            sc["estimated_duration_sec"] = sc.pop("duration")
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_scriptwriter_budget.py -v
```
Expected: 2 passed.

**Step 5: Commit**

```bash
git add clipper_agency/agents/scriptwriter.py tests/agents/test_scriptwriter_budget.py
git commit -m "feat(scriptwriter): add role, word_count, estimated_duration_sec per scene"
```

---

### Task 2b: Visual Director Timeline-Aware Planning

**Files:**
- Modify: `clipper_agency/agents/visual_director.py` (consume `timeline` kwarg)
- Create: `tests/agents/test_visual_director_timeline_aware.py`

**Step 1: Write the failing test**

```python
from clipper_agency.agents.visual_director import VisualDirectorAgent


class TestVisualDirectorTimelineAware:
    def test_execute_receives_timeline_kwarg(self):
        """If timeline is present, Visual Director uses it for durations."""
        agent = VisualDirectorAgent()
        # verify that _resolve_scene_durations prefers timeline
        timeline = [
            {
                "scene": 1,
                "role": "opening_hook",
                "text": "hello",
                "target_duration_sec": 8.7,
                "visual_instruction": "opening card",
                "audio_path": "s1.mp3",
                "audio_duration_sec": 8.7,
                "start_sec": 0.0,
                "end_sec": 8.7,
            },
            {
                "scene": 2,
                "role": "cta",
                "text": "bye",
                "target_duration_sec": 5.3,
                "visual_instruction": "cta card",
                "audio_path": "s2.mp3",
                "audio_duration_sec": 5.3,
                "start_sec": 8.7,
                "end_sec": 14.0,
            },
        ]
        scenes = agent._resolve_scene_data(
            script=[{"scene": 1, "text": "hello", "duration": 3}],
            timeline_data=timeline,
        )
        assert len(scenes) == 2
        assert scenes[0]["target_duration"] == 8.7
        assert scenes[0]["role"] == "opening_hook"
        assert scenes[1]["role"] == "cta"

    def test_no_timeline_falls_back_to_script(self):
        agent = VisualDirectorAgent()
        scenes = agent._resolve_scene_data(
            script=[{"scene": 1, "text": "hello", "duration": 5}],
            timeline_data=None,
        )
        assert len(scenes) == 1
        assert scenes[0].get("target_duration", scenes[0].get("duration")) == 5
```

**Step 2: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_timeline_aware.py -v
```
Expected: FAIL.

**Step 3: Implement `_resolve_scene_data` in `visual_director.py`**

```python
def _resolve_scene_data(self, script, timeline_data=None):
    if timeline_data:
        # use timeline as primary source
        return [
            {
                "scene": t.get("scene", i + 1),
                "role": t.get("role", "body"),
                "text": t.get("text", ""),
                "target_duration": t.get("target_duration_sec", 5),
            }
            for i, t in enumerate(timeline_data)
        ]
    # fallback to original script
    return [
        {
            "scene": s.get("scene", i + 1),
            "role": s.get("role", "body"),
            "text": s.get("text", ""),
            "target_duration": s.get("duration", s.get("target_duration", 5)),
        }
        for i, s in enumerate(script)
    ]
```

Update `execute` to call `_resolve_scene_data`:

```python
    timeline_data = kwargs.get("timeline")
    scenes_for_planning = self._resolve_scene_data(script, timeline_data)
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_timeline_aware.py -v
```
Expected: 2 passed.

**Step 5: Commit**

```bash
git add clipper_agency/agents/visual_director.py tests/agents/test_visual_director_timeline_aware.py
git commit -m "feat(visual_director): consume reconciled timeline for durations"
```

---

### Task 2c: Composer Timeline-Obedient Rendering

**Files:**
- Modify: `clipper_agency/agents/composer.py` (consume `timeline` kwarg, use timeline durations)
- Create: `tests/agents/test_composer_timeline_obedient.py`

**Step 1: Write the failing test**

```python
from clipper_agency.agents.composer import ComposerAgent


class TestComposerTimelineObedient:
    def test_resolve_asset_durations_from_timeline(self):
        agent = ComposerAgent()
        timeline = [
            {
                "scene": 1,
                "role": "opening_hook",
                "target_duration_sec": 8.7,
                "audio_path": "/tmp/s1.mp3",
            },
            {
                "scene": 2,
                "role": "cta",
                "target_duration_sec": 5.3,
                "audio_path": "/tmp/s2.mp3",
            },
        ]
        # default assets might have different durations
        default_assets = [
            {"scene": 1, "target_duration": 3},
            {"scene": 2, "target_duration": 5},
        ]
        resolved = agent._apply_timeline_to_assets(default_assets, timeline)
        assert resolved[0]["target_duration"] == 8.7
        assert resolved[1]["target_duration"] == 5.3

    def test_no_timeline_preserves_original_durations(self):
        agent = ComposerAgent()
        assets = [{"scene": 1, "target_duration": 5}]
        resolved = agent._apply_timeline_to_assets(assets, None)
        assert resolved[0]["target_duration"] == 5

    def test_timeline_pairs_correct_audio_files(self):
        agent = ComposerAgent()
        timeline = [
            {"scene": 1, "audio_path": "/real/s1.mp3"},
            {"scene": 2, "audio_path": "/real/s2.mp3"},
        ]
        audio_map = agent._build_timeline_audio_map(timeline)
        assert audio_map[0] == "/real/s1.mp3"
        assert audio_map[1] == "/real/s2.mp3"
```

**Step 2: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_composer_timeline_obedient.py -v
```
Expected: FAIL — methods don't exist.

**Step 3: Implement in `composer.py`**

```python
def _apply_timeline_to_assets(self, assets, timeline):
    if not timeline:
        return assets
    resolved = []
    for i, asset in enumerate(assets):
        new_asset = dict(asset)
        if i < len(timeline):
            td = timeline[i].get("target_duration_sec")
            if td is not None:
                new_asset["target_duration"] = td
            new_asset["role"] = timeline[i].get("role", asset.get("role", "body"))
        resolved.append(new_asset)
    return resolved


def _build_timeline_audio_map(self, timeline):
    return {i: t.get("audio_path", "") for i, t in enumerate(timeline)}
```

Update `execute` to accept timeline and apply:

```python
    timeline = kwargs.get("timeline")
    assets = self._apply_timeline_to_assets(assets, timeline)
```

And use `_build_timeline_audio_map` in `_execute_assembly` for audio file pairing.

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/agents/test_composer_timeline_obedient.py -v
```
Expected: 3 passed.

**Step 5: Commit**

```bash
git add clipper_agency/agents/composer.py tests/agents/test_composer_timeline_obedient.py
git commit -m "feat(composer): obey timeline durations and audio pairing"
```

---

## Batch 2 — Verification

```bash
.venv/bin/python3 -m pytest tests/agents/test_scriptwriter_budget.py tests/agents/test_visual_director_timeline_aware.py tests/agents/test_composer_timeline_obedient.py -v
```

Expected: 7 passed.

---

## Batch 3 — Integration & Hardening (sequential)

### Task 3a: Retry Path Fix + G10 Configurable Limit

**Files:**
- Modify: `clipper_agency/orchestrator/engine.py` (_retry_composer_stage, _retry_visual_director_stage, G10 validation)
- Modify: `clipper_agency/agents/composer.py` (confirm `script_scenes` is used in subtitle generation)
- Create: `tests/orchestrator/test_retry_timeline.py`

**Step 1: Write failing test for retry path**

```python
from unittest.mock import MagicMock, patch
from clipper_agency.orchestrator.engine import OrchestratorEngine


class TestRetryTimeline:
    def test_retry_composer_passes_script_scenes(self, tmp_path):
        engine = OrchestratorEngine()
        with patch.object(engine, "_reconstruct_upstream_outputs") as mock_reco:
            mock_reco.return_value = (
                {"assets": [], "scene_plan": []},  # visual output
                {"audio_files": [], "audio_metadata": []},  # voice output
                {"script": []},  # script output  ← must be present!
            )
            with patch.object(engine, "_run_composer") as mock_run:
                engine._retry_composer_stage(
                    conn=MagicMock(),
                    job_id=2,
                    visual_output={"assets": []},
                    voice_output={"audio_files": []},
                    output_dir=str(tmp_path),
                    assets_cache=str(tmp_path),
                )
                call_kwargs = mock_run.call_args[1]
                assert "script_scenes" in call_kwargs

    def test_g10_uses_configurable_limit(self):
        from clipper_agency.orchestrator.engine import _validate_g10_configurable
        result = _validate_g10_configurable(duration_sec=55, hard_limit=60)
        assert result["pass"] is True

        result = _validate_g10_configurable(duration_sec=62, hard_limit=60)
        assert result["pass"] is False
```

**Step 2: Implement `_reconstruct_upstream_outputs` to include script output**

In `engine.py`:

```python
def _reconstruct_upstream_outputs(self, conn, job_id, ...):
    ...
    script_output = self._load_completed_agent_output(conn, job_id, "scriptwriter")
    return visual_output, voice_output, script_output
```

Update `_retry_composer_stage` to receive and pass script_scenes:

```python
def _retry_composer_stage(self, conn, job_id, ...):
    visual_output, voice_output, script_output = self._reconstruct_upstream_outputs(...)
    compose_output = self._run_composer(
        ...,
        script_scenes=script_output.get("script", []),
    )
```

Same fix for `_retry_visual_director_stage`:

```python
    # pass timeline if available
    script_output = self._load_completed_agent_output(conn, job_id, "scriptwriter")
    voice_output = self._load_completed_agent_output(conn, job_id, "voice_producer")
```

**Step 3: Implement configurable G10**

```python
def _validate_g10_configurable(duration_sec, hard_limit):
    """Deterministic validation with configurable limit."""
    ok = duration_sec > 0.0 and duration_sec <= hard_limit
    return {
        "pass": ok,
        "duration_sec": duration_sec,
        "hard_limit_sec": hard_limit,
        "reason": "within_limit" if ok else "exceeds_hard_limit",
    }
```

In gate G10 check:

```python
cp_config = load_settings().content_planning
limit = cp_config.hard_limit_sec  # instead of hardcoded 60
```

**Step 4: Run test**

```bash
.venv/bin/python3 -m pytest tests/orchestrator/test_retry_timeline.py -v
```
Expected: 2 passed.

**Step 5: Commit**

```bash
git add clipper_agency/orchestrator/engine.py tests/orchestrator/test_retry_timeline.py
git commit -m "fix(orchestrator): pass script_scenes in retry; configurable G10 duration limit"
```

---

### Task 3b: Integration & Regression Tests

**Files:**
- Create: `tests/integration/test_tier4_timeline_e2e.py`
- Modify: `tests/agents/test_agents_composer.py` (adds timeline-obedient test)

**Step 1: Write integration test**

```python
import pytest


@pytest.mark.integration
class TestTimelineEndToEnd:
    def test_timeline_reconciler_to_composer_flow(self, tmp_path, monkeypatch):
        """Full flow: script + audio meta → timeline → composer render plan."""
        from clipper_agency.orchestrator.timeline import reconcile_timeline
        from clipper_agency.agents.composer import ComposerAgent

        # 1. reconcile
        scenes = [
            {"scene": 1, "role": "opening_hook", "text": "hello", "estimated_duration_sec": 5},
        ]
        audio_meta = [
            {"scene": 1, "audio_duration_sec": 8.7, "audio_path": "s1.mp3", "provider": "el"},
        ]
        timeline = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert timeline.within_limit

        # 2. composer applies
        agent = ComposerAgent()
        assets = [{"scene": 1, "target_duration": 3}]
        resolved = agent._apply_timeline_to_assets(assets, timeline.timeline)
        assert resolved[0]["target_duration"] == 8.7

    def test_overlong_audio_fails_before_visual_director(self):
        """60s+ audio must fail at Timeline Reconciler, not after Visual Director."""
        from clipper_agency.orchestrator.timeline import reconcile_timeline
        scenes = [
            {"scene": 1, "role": "opening_hook", "text": "!", "estimated_duration_sec": 1},
            {"scene": 2, "role": "story_1", "text": "!", "estimated_duration_sec": 1},
            {"scene": 3, "role": "story_2", "text": "!", "estimated_duration_sec": 1},
            {"scene": 4, "role": "story_3", "text": "!", "estimated_duration_sec": 1},
            {"scene": 5, "role": "cta", "text": "!", "estimated_duration_sec": 1},
        ]
        audio_meta = [
            {"scene": i, "audio_duration_sec": 15.0, "audio_path": f"s{i}.mp3", "provider": "el"}
            for i in range(1, 6)
        ]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert result.total_duration_sec == 75.0
        assert result.within_limit is False
```

**Step 2: Run test**

```bash
.venv/bin/python3 -m pytest tests/integration/test_tier4_timeline_e2e.py -v
```
Expected: 2 passed.

**Step 3: Run full suite and verify no regressions**

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
.venv/bin/python3 -m pytest tests/integration/test_tier4_timeline_e2e.py -v
```

Expected: all existing 783 + all new tests pass. Coverage ≥93%.

**Step 4: Commit**

```bash
git add tests/integration/test_tier4_timeline_e2e.py
git commit -m "test: add Tier 4 integration and regression tests"
```

---

## Batch 3 — Final Verification

```bash
.venv/bin/python3 -m pytest -m "not external" --cov=clipper_agency --cov-report=term-missing -q
```

Expected: all pass, coverage ≥93%.

---

## Summary

| Batch | Tasks | Files | New Tests | Risk |
|-------|-------|-------|-----------|------|
| **B0** (parallel) | Config, Researcher, VoiceProd | 4 modify + 3 test files | 8 | Low — isolated |
| **B1** (sequential) | Validator, DurationGate, Timeline | 1 new module + 3 test files | 16 | Medium — touches orchestrator |
| **B2** (parallel) | Scriptwriter, VisualDir, Composer | 3 modify + 3 test files | 7 | Low — isolated |
| **B3** (sequential) | Retry, G10, Integration | 1 modify + 2 test files | 4 | Low — integration hardening |

**Total: ~35 new tests expected. Estimated wall-clock time: 2-3 hours with parallel CoderAgents.**

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-06-06-tier4-implementation-plan.md`. Two execution options:

1. **Subagent-Driven (this session)** — I dispatch fresh CoderAgent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
