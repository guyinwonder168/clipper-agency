# Job #3 Coordination Fixes Implementation Plan ✅ IMPLEMENTED

> **Status:** Implemented. All 8 tasks completed — Composer beat-ID alignment (tests/agents/test_composer_timeline_obedient.py), full-duration coverage, full narration subtitles, Visual Director beat-driven contract (tests/agents/test_visual_director_beat_driven.py), Segment Producer richer asset candidates with asset_candidates expansion, duplicate prevention with URL replacement + llmPlanUrl dedup, and Job #3 regression fixture. All offline tests pass.
>
> **For Claude:** DO NOT implement this plan. It has already been completed.

**Goal:** Fix Job #3's broken audio-first output by enforcing beat-ID contracts, full voiceover duration coverage, full narration subtitles, and safe asset candidate expansion through Segment Producer.

**Architecture:** Segment Producer owns research and candidate asset discovery. Scriptwriter and Voice Producer own narration and timing. Visual Director selects visuals only from beat-aligned candidates and must not invent beats. Composer is the final defensive timeline executor and must align by `beat_id`, never list index.

**Tech Stack:** Python 3.11, Pydantic, SQLite pipeline state, Firecrawl/ScrapeCreators/Pexels services, FFmpeg, pytest.

---

## Parallel Execution Overview

This plan is designed for batch-parallel execution. Tasks are grouped by dependency boundaries so independent changes can run simultaneously without editing the same files.

### Batch 1 — Independent Core Fixes

Run these in parallel:

| Task | Area | Files | Depends On |
| --- | --- | --- | --- |
| 1 | Composer beat-ID alignment | `clipper_agency/agents/composer.py`, `tests/agents/test_composer_timeline_obedient.py` | none |
| 3 | Full narration subtitles | `clipper_agency/rendering/subtitle_engine.py`, `tests/test_subtitle_engine.py` | none |
| 5 | Segment Producer asset candidates | `clipper_agency/config/schema.py`, `clipper_agency/agents/segment_producer.py`, `clipper_agency/services/firecrawl_service.py`, `tests/test_agents_segment_producer.py` | none |

### Batch 2 — Dependent Timeline and Selection Fixes

Run after Batch 1 completes:

| Task | Area | Files | Depends On |
| --- | --- | --- | --- |
| 2 | Composer full-duration coverage | `clipper_agency/agents/composer.py`, `tests/agents/test_composer_timeline_obedient.py` | Task 1 |
| 4 | Visual Director beat contract | `clipper_agency/agents/visual_director.py`, `tests/agents/test_visual_director_beat_driven.py` | Task 5 useful but not required |

### Batch 3 — Integration Fixes

Run after Batch 2 completes:

| Task | Area | Files | Depends On |
| --- | --- | --- | --- |
| 6 | Visual Director candidate selection + duplicate prevention | `clipper_agency/agents/visual_director.py`, `tests/agents/test_visual_director_beat_driven.py` | Tasks 4, 5 |
| 7 | Job #3 regression fixture | `tests/agents/test_composer_timeline_obedient.py` | Tasks 1, 2 |

### Batch 4 — Validation

Run after all implementation tasks complete:

| Task | Area | Depends On |
| --- | --- | --- |
| 8 | Full offline suite + retry verification | Tasks 1-7 |

---

## Contract Invariants

Every task must preserve these invariants:

1. **Voiceover timestamps are the timeline source of truth.**
2. **Scriptwriter narrative beats are the beat source of truth.**
3. **Segment Producer asset candidates are visual metadata only.** They must not change script text, voiceover, timing, or beat count.
4. **Visual Director may select visuals but may not invent, remove, reorder, or retime beats.**
5. **Composer must defensively align by `beat_id`, never list index.**
6. **Final rendered video must cover the full voiceover duration.**
7. **Default captions must be full narration subtitles, not keyword-only captions.**

---

## Batch 1 / Task 1 — Composer Beat-ID Alignment

**Parallel:** Yes, with Tasks 3 and 5.

**Goal:** Composer must never match visual assets to narrative beats by list index.

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Test: `tests/agents/test_composer_timeline_obedient.py`

### Step 1: Write failing test

Add to `tests/agents/test_composer_timeline_obedient.py`:

```python
def test_audio_first_aligns_assets_by_beat_id_and_ignores_phantom_beat(self):
    agent = ComposerAgent()
    narrative = [
        {"beat_id": 1, "word_range": [0, 2]},
        {"beat_id": 2, "word_range": [2, 4]},
        {"beat_id": 9, "word_range": [4, 6]},
    ]
    assets = [
        {"beat_id": 1, "path": "/tmp/beat1.mp4"},
        {"beat_id": 2, "path": "/tmp/beat2.mp4"},
        {"beat_id": 8, "path": "/tmp/phantom.mp4"},
        {"beat_id": 9, "path": "/tmp/cta.mp4"},
    ]

    aligned = agent._align_assets_to_narrative_beats(narrative, assets)

    assert [item["beat_id"] for item in aligned] == [1, 2, 9]
    assert aligned[2]["path"] == "/tmp/cta.mp4"
```

### Step 2: Run test to verify failure

```bash
.venv/bin/python3 -m pytest tests/agents/test_composer_timeline_obedient.py::TestComposerTimelineObedient::test_audio_first_aligns_assets_by_beat_id_and_ignores_phantom_beat -v
```

Expected: fail because `_align_assets_to_narrative_beats` does not exist.

### Step 3: Implement helper

Add to `ComposerAgent` in `clipper_agency/agents/composer.py`:

```python
@staticmethod
def _align_assets_to_narrative_beats(
    narrative_structure: list[dict],
    assets: list[dict],
) -> list[dict]:
    """Align visual assets to narrative beats by beat_id, ignoring phantom assets."""
    assets_by_beat_id = {
        asset.get("beat_id"): asset
        for asset in assets
        if asset.get("beat_id") is not None
    }
    aligned: list[dict] = []
    for beat in narrative_structure:
        beat_id = beat.get("beat_id")
        asset = dict(assets_by_beat_id.get(beat_id, {}))
        asset["beat_id"] = beat_id
        aligned.append(asset)
    return aligned
```

### Step 4: Wire helper into audio-first path

In `_try_audio_first_assemble()`, compute aligned assets before `_collect_beat_clips()`:

```python
aligned_assets = self._align_assets_to_narrative_beats(
    narrative_structure,
    assets,
)
```

Pass `aligned_assets` instead of `assets` into:
- `_collect_beat_clips(...)`
- `_run_audio_first_render(...)`

### Step 5: Verify task tests

```bash
.venv/bin/python3 -m pytest tests/agents/test_composer_timeline_obedient.py -q
```

Expected: pass.

### Step 6: Commit

```bash
git add clipper_agency/agents/composer.py tests/agents/test_composer_timeline_obedient.py
git commit -m "fix: align composer assets by beat id"
```

---

## Batch 2 / Task 2 — Composer Full Voiceover Duration Coverage

**Parallel:** Yes, with Task 4 after Task 1 completes.

**Goal:** Beat durations must cover skipped gap words, trailing audio, and transition overlap so final video duration matches voiceover duration.

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Test: `tests/agents/test_composer_timeline_obedient.py`

### Step 1: Write failing test

Add to `tests/agents/test_composer_timeline_obedient.py`:

```python
def test_beat_durations_cover_full_voiceover_with_gaps_and_trailing_audio(self):
    narrative = [
        {"beat_id": 1, "word_range": [0, 2]},
        {"beat_id": 2, "word_range": [3, 5]},
        {"beat_id": 9, "word_range": [6, 7]},
    ]
    timestamps = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.5, "end": 1.0},
        {"word": "gap", "start": 1.0, "end": 1.5},
        {"word": "c", "start": 1.5, "end": 2.0},
        {"word": "d", "start": 2.0, "end": 2.5},
        {"word": "gap2", "start": 2.5, "end": 3.0},
        {"word": "cta", "start": 3.0, "end": 3.5},
        {"word": "tail", "start": 3.5, "end": 5.0},
    ]

    durations = ComposerAgent._compute_beat_durations(narrative, timestamps)

    assert sum(durations) == pytest.approx(5.0)
```

If `pytest` is not already imported in the file, add `import pytest`.

### Step 2: Run test to verify failure

```bash
.venv/bin/python3 -m pytest tests/agents/test_composer_timeline_obedient.py::TestComposerTimelineObedient::test_beat_durations_cover_full_voiceover_with_gaps_and_trailing_audio -v
```

Expected: fail because current implementation only sums beat word spans.

### Step 3: Implement voiceover-covering durations

Modify `_compute_beat_durations()` so each beat duration is:

```text
current beat first word start → next beat first word start
```

For the final beat:

```text
current beat first word start → final timestamp end
```

This covers words skipped between beat ranges and the trailing voiceover after the final beat range.

### Step 4: Add transition-overlap inflation helper

Add a small helper in `ComposerAgent`:

```python
@staticmethod
def _inflate_durations_for_transitions(
    durations: list[float],
    transition_duration: float = 0.5,
) -> list[float]:
    if not durations:
        return []
    inflated = list(durations)
    for index in range(len(inflated) - 1):
        inflated[index] += transition_duration
    return inflated
```

Use this only when building render durations for xfade assembly, not when asserting logical voiceover coverage.

### Step 5: Wire inflated durations into render path

In `_try_audio_first_assemble()` or `_run_audio_first_render()`, use logical durations for diagnostics and inflated durations for scene `target_duration` passed to FFmpeg.

### Step 6: Verify task tests

```bash
.venv/bin/python3 -m pytest tests/agents/test_composer_timeline_obedient.py -q
```

Expected: pass.

### Step 7: Commit

```bash
git add clipper_agency/agents/composer.py tests/agents/test_composer_timeline_obedient.py
git commit -m "fix: cover full voiceover duration in composer"
```

---

## Batch 1 / Task 3 — Full Narration Subtitles

**Parallel:** Yes, with Tasks 1 and 5.

**Goal:** Default captions must be full narration subtitles based on word timestamps, not keyword-only beat captions.

**Files:**
- Modify: `clipper_agency/rendering/subtitle_engine.py`
- Modify: `clipper_agency/agents/composer.py`
- Test: `tests/test_subtitle_engine.py`

### Step 1: Write failing test

Add to `tests/test_subtitle_engine.py`:

```python
def test_build_word_subtitle_captions_uses_narration_words_not_keywords():
    timestamps = [
        {"word": "Yuk", "start": 0.0, "end": 0.3},
        {"word": "intip", "start": 0.3, "end": 0.7},
        {"word": "berita", "start": 0.7, "end": 1.1},
        {"word": "viral", "start": 1.1, "end": 1.5},
    ]

    result = build_word_subtitle_captions(timestamps, max_words=2)

    assert [c.text for c in result] == ["Yuk intip", "berita viral"]
    assert result[0].style == "subtitle"
    assert result[0].position == "bottom"
    assert result[0].start_seconds == 0.0
    assert result[-1].end_seconds == 1.5
```

Update imports in the test file to include `build_word_subtitle_captions`.

### Step 2: Run test to verify failure

```bash
.venv/bin/python3 -m pytest tests/test_subtitle_engine.py::test_build_word_subtitle_captions_uses_narration_words_not_keywords -v
```

Expected: fail because function does not exist.

### Step 3: Implement subtitle builder

Add to `clipper_agency/rendering/subtitle_engine.py`:

```python
def build_word_subtitle_captions(
    timestamps: list[dict],
    max_words: int = 6,
    hook_duration: float = 0.0,
) -> list[CaptionOverlay]:
    """Build full narration subtitle captions from word-level timestamps."""
    if not timestamps:
        return []

    overlays: list[CaptionOverlay] = []
    for start in range(0, len(timestamps), max_words):
        chunk = timestamps[start:start + max_words]
        if not chunk:
            continue
        start_seconds = _ts_value(chunk[0], "start", 0.0)
        end_seconds = _ts_value(chunk[-1], "end", start_seconds)
        if start_seconds < hook_duration:
            continue
        text = " ".join(str(_ts_value(word, "word", "")) for word in chunk).strip()
        if not text or end_seconds <= start_seconds:
            continue
        overlays.append(CaptionOverlay(
            text=text,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            position="bottom",
            style="subtitle",
        ))
    return overlays
```

If `_ts_value()` currently assumes float return values, split text access into a separate helper or inline dict/object access to keep typing clean.

### Step 4: Switch Composer default

In `clipper_agency/agents/composer.py`, change import:

```python
from clipper_agency.rendering.subtitle_engine import (
    build_keyword_captions,
    build_subtitle_overlays,
    build_word_subtitle_captions,
)
```

In `_run_audio_first_render()`, replace keyword caption construction with:

```python
subtitle_captions = build_word_subtitle_captions(
    timestamps,
    hook_duration=beat_durations[0] if beat_durations else 0.0,
)
```

Pass `subtitle_captions` to `_build_audio_first_cmd()`.

Keep `build_keyword_captions()` available for future optional emphasis mode.

### Step 5: Verify task tests

```bash
.venv/bin/python3 -m pytest tests/test_subtitle_engine.py -q
```

Expected: pass.

### Step 6: Commit

```bash
git add clipper_agency/rendering/subtitle_engine.py clipper_agency/agents/composer.py tests/test_subtitle_engine.py
git commit -m "feat: render full narration subtitles"
```

---

## Batch 2 / Task 4 — Visual Director Beat Contract Validation

**Parallel:** Yes, with Task 2 after Batch 1 completes.

**Goal:** Visual Director output must be normalized to Scriptwriter/Segment Producer narrative beat IDs. It must not invent phantom beats.

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Test: `tests/agents/test_visual_director_beat_driven.py`

### Step 1: Write failing test

Add to `tests/agents/test_visual_director_beat_driven.py`:

```python
def test_llm_plan_is_normalized_to_allowed_beat_ids():
    agent = VisualDirectorAgent()
    allowed = [1, 2, 9]
    plan = [
        {"scene_number": 1, "beat_id": 1},
        {"scene_number": 2, "beat_id": 2},
        {"scene_number": 8, "beat_id": 8},
        {"scene_number": 9, "beat_id": 9},
    ]

    normalized = agent._normalize_beat_plan(plan, allowed)

    assert [item["beat_id"] for item in normalized] == [1, 2, 9]
```

### Step 2: Run test to verify failure

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py::test_llm_plan_is_normalized_to_allowed_beat_ids -v
```

Expected: fail because helper does not exist.

### Step 3: Implement `_normalize_beat_plan()`

Add to `VisualDirectorAgent`:

```python
@staticmethod
def _normalize_beat_plan(plan: list[dict], allowed_beat_ids: list[int]) -> list[dict]:
    """Keep only allowed beat IDs and preserve narrative beat order."""
    by_beat_id = {
        item.get("beat_id", item.get("scene_number")): item
        for item in plan
    }
    normalized: list[dict] = []
    for beat_id in allowed_beat_ids:
        item = dict(by_beat_id.get(beat_id, {}))
        item.setdefault("scene_number", beat_id)
        item["beat_id"] = beat_id
        normalized.append(item)
    return normalized
```

### Step 4: Wire into `_run_beat_driven_planning()`

After choosing LLM/fallback plan:

```python
allowed_beat_ids = [beat.beat_id for beat in parsed_beats]
plan = self._normalize_beat_plan(plan, allowed_beat_ids)
```

### Step 5: Verify task tests

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py -q
```

Expected: pass.

### Step 6: Commit

```bash
git add clipper_agency/agents/visual_director.py tests/agents/test_visual_director_beat_driven.py
git commit -m "fix: enforce visual director beat contract"
```

---

## Batch 1 / Task 5 — Segment Producer Asset Candidate Expansion

**Parallel:** Yes, with Tasks 1 and 3.

**Goal:** Segment Producer must provide several candidate images/videos from ScrapeCreators and Firecrawl in the brief output, as visual metadata only.

**Files:**
- Modify: `clipper_agency/config/schema.py`
- Modify: `clipper_agency/agents/segment_producer.py`
- Modify: `clipper_agency/services/firecrawl_service.py`
- Test: `tests/test_agents_segment_producer.py`

### Step 1: Extend `AssetCandidate`

In `clipper_agency/config/schema.py`, change `AssetCandidate` to:

```python
class AssetCandidate(BaseModel):
    """A candidate visual asset found during research."""

    type: str
    url: str = ""
    reason: str
    source: str = ""
    page_url: str = ""
    title: str = ""
    relevance_score: float = 0.0
    provenance: str = ""
    related_beat_id: int | None = None
    story_id: str = ""
    license_status: str = "unknown"
```

### Step 2: Add failing candidate extraction test

Add to `tests/test_agents_segment_producer.py`:

```python
def test_segment_producer_builds_asset_candidates_from_firecrawl_and_scrapecreators():
    agent = SegmentProducerAgent()

    candidates = agent._build_asset_candidates_from_sources(
        firecrawl_data=[
            {
                "title": "Sarwendah update",
                "url": "https://news.example/a",
                "description": "context",
            },
        ],
        scrapecreators_data=[
            {
                "title": "TikTok clip",
                "url": "https://tiktok.com/@u/video/1",
            },
        ],
    )

    assert any(c["source"] == "scrapecreators" for c in candidates)
    assert any(c["source"] == "firecrawl" for c in candidates)
    assert all("url" in c for c in candidates)
```

### Step 3: Run test to verify failure

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py::test_segment_producer_builds_asset_candidates_from_firecrawl_and_scrapecreators -v
```

Expected: fail because helper does not exist.

### Step 4: Implement helper

Add to `SegmentProducerAgent`:

```python
@staticmethod
def _build_asset_candidates_from_sources(
    firecrawl_data: list[dict],
    scrapecreators_data: list[dict],
) -> list[dict]:
    """Build visual asset candidates from raw research sources."""
    candidates: list[dict] = []
    for item in scrapecreators_data:
        url = item.get("url", "")
        if not url:
            continue
        candidates.append({
            "type": "tiktok_clip",
            "url": url,
            "reason": item.get("title") or item.get("desc") or "ScrapeCreators video candidate",
            "source": "scrapecreators",
            "page_url": url,
            "title": item.get("title", ""),
            "relevance_score": 0.9,
            "provenance": "primary_clip",
            "license_status": "unknown",
        })
    for item in firecrawl_data:
        url = item.get("url", "")
        if not url:
            continue
        candidates.append({
            "type": "screenshot",
            "url": url,
            "reason": item.get("description") or item.get("title") or "Firecrawl supporting context",
            "source": "firecrawl",
            "page_url": url,
            "title": item.get("title", ""),
            "relevance_score": 0.7,
            "provenance": "supporting_context",
            "license_status": "unknown",
        })
    return candidates
```

### Step 5: Merge discovered candidates into output

In `execute()` after source gathering:

```python
discovered_candidates = self._build_asset_candidates_from_sources(
    firecrawl_data,
    scrapecreators_data,
)
```

When building `result`, merge LLM and discovered candidates without duplicate URLs:

```python
asset_candidates = self._merge_asset_candidates(
    synthesis.get("asset_candidates", []),
    discovered_candidates,
)
```

Add helper:

```python
@staticmethod
def _merge_asset_candidates(*candidate_groups: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    merged: list[dict] = []
    for group in candidate_groups:
        for candidate in group:
            url = candidate.get("url", "")
            key = url or json.dumps(candidate, sort_keys=True)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            merged.append(candidate)
    return merged
```

Use the merged `asset_candidates` in result and persisted output.

### Step 6: Persist normalized asset candidates

In `_persist_contract_artifacts()`, write:

```text
normalized/asset_candidates.json
```

Include it in `research_contract.json` as:

```python
"asset_candidates": output.get("asset_candidates", []),
"asset_candidates_path": str(asset_candidates_path),
```

### Step 7: Verify task tests

```bash
.venv/bin/python3 -m pytest tests/test_agents_segment_producer.py -q
```

Expected: pass.

### Step 8: Commit

```bash
git add clipper_agency/config/schema.py clipper_agency/agents/segment_producer.py clipper_agency/services/firecrawl_service.py tests/test_agents_segment_producer.py
git commit -m "feat: expand segment producer asset candidates"
```

---

## Batch 3 / Task 6 — Visual Director Candidate Selection and Duplicate Prevention

**Parallel:** Yes, with Task 7 after Tasks 4 and 5 complete.

**Goal:** Visual Director should use Segment Producer candidates, prefer relevant Firecrawl/ScrapeCreators candidates before generic Pexels, and avoid duplicate candidate URLs across beats.

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Test: `tests/agents/test_visual_director_beat_driven.py`

### Step 1: Add Firecrawl candidate test

```python
def test_visual_director_prefers_firecrawl_candidate_before_pexels():
    agent = VisualDirectorAgent()
    beat = StoryBeat(**_make_beat(
        asset_candidates=[
            {
                "type": "screenshot",
                "url": "https://news.example/story",
                "reason": "Relevant article image candidate",
                "source": "firecrawl",
            },
        ],
    ))

    action = agent._select_visual_for_beat(beat, [])

    assert action["type"] == "pexels_image"
    assert action["source_url"] == "https://news.example/story"
```

### Step 2: Add duplicate URL test

```python
def test_visual_director_skips_duplicate_candidate_urls():
    agent = VisualDirectorAgent()
    duplicate_url = "https://tiktok.com/@u/video/1"
    beat = StoryBeat(**_make_beat(
        asset_candidates=[
            {"type": "tiktok_clip", "url": duplicate_url, "reason": "duplicate"},
            {"type": "screenshot", "url": "https://news.example/a", "reason": "alternate"},
        ],
    ))

    action = agent._select_visual_for_beat(beat, [duplicate_url])

    assert action.get("source_url") != duplicate_url
```

### Step 3: Run tests to verify failure if needed

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py -q
```

Expected: new behavior may partially pass for screenshots, but duplicate handling should be verified.

### Step 4: Update candidate priority

In `_select_visual_for_beat()`, keep priority:

1. `tiktok_clip`
2. `screenshot`, `article_image`, `firecrawl_image`
3. Pexels image search
4. text card

Use `do_not_use` as selected/blocked URL set.

### Step 5: Add duplicate tracking during fallback planning

In `_plan_beats_fallback()`, maintain:

```python
used_urls: set[str] = set(do_not_use)
```

After choosing an action with `source_url`, add it to `used_urls` before the next beat.

Do not add trim-window complexity in this task. If no distinct candidate exists, fall back to screenshot/Pexels/card.

### Step 6: Verify task tests

```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director_beat_driven.py -q
```

Expected: pass.

### Step 7: Commit

```bash
git add clipper_agency/agents/visual_director.py tests/agents/test_visual_director_beat_driven.py
git commit -m "fix: select distinct beat asset candidates"
```

---

## Batch 3 / Task 7 — Job #3 Regression Fixture

**Parallel:** Yes, with Task 6 after Tasks 1 and 2 complete.

**Goal:** Prevent the Job #3 failure pattern from returning.

**Files:**
- Test: `tests/agents/test_composer_timeline_obedient.py`

### Step 1: Add Job #3 shape test

```python
def test_job_3_shape_ignores_phantom_beat_and_keeps_cta(self):
    agent = ComposerAgent()
    narrative = [
        {"beat_id": 1, "word_range": [0, 10]},
        {"beat_id": 2, "word_range": [11, 23]},
        {"beat_id": 3, "word_range": [24, 30]},
        {"beat_id": 4, "word_range": [31, 40]},
        {"beat_id": 5, "word_range": [41, 45]},
        {"beat_id": 6, "word_range": [46, 53]},
        {"beat_id": 7, "word_range": [54, 58]},
        {"beat_id": 9, "word_range": [59, 71]},
    ]
    assets = [
        {"beat_id": beat_id, "path": f"/tmp/beat_{beat_id}.mp4"}
        for beat_id in [1, 2, 3, 4, 5, 6, 7, 8, 9]
    ]

    aligned = agent._align_assets_to_narrative_beats(narrative, assets)

    assert [item["beat_id"] for item in aligned] == [1, 2, 3, 4, 5, 6, 7, 9]
    assert aligned[-1]["path"] == "/tmp/beat_9.mp4"
    assert all(item["beat_id"] != 8 for item in aligned)
```

### Step 2: Add duration coverage assertion

Extend the test or add a second one with representative timestamps ending at `43.45` and assert:

```python
assert sum(ComposerAgent._compute_beat_durations(narrative, timestamps)) == pytest.approx(43.45)
```

### Step 3: Run task test

```bash
.venv/bin/python3 -m pytest tests/agents/test_composer_timeline_obedient.py -q
```

Expected: pass.

### Step 4: Commit

```bash
git add tests/agents/test_composer_timeline_obedient.py
git commit -m "test: add job 3 coordination regression"
```

---

## Batch 4 / Task 8 — Full Offline Validation and Pipeline Retry

**Parallel:** No. Final validation only.

**Goal:** Prove all batch changes integrate correctly.

### Step 1: Run full offline tests

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected:

```text
1008+ passed, 4 deselected
```

If this fails, stop. Report failure, propose fix, and request approval before changing code.

### Step 2: Retry Job #3 from Visual Director

```bash
.venv/bin/python3 -m clipper_agency job-retry 3 --from visual_director --use-cache
```

Expected:
- `logs/run-job_3.log` updates.
- Final video duration is approximately the voiceover duration.
- CTA beat 9 is rendered.
- Phantom beat 8 is ignored.
- Full narration subtitles are shown.
- Duplicate scene reuse is reduced or replaced by alternate candidate/card fallback.

### Step 3: Inspect artifacts

Check:

```text
data/assets/cache/job_3/agents/visual_director/scene_plan.json
data/assets/cache/job_3/agents/composer/output.json
data/outputs/job_3/video.mp4
logs/run-job_3.log
```

### Step 4: Commit validation docs if needed

Only commit docs/artifact notes if a maintained doc needs updating. Do not commit generated media artifacts unless explicitly requested.

---

## Execution Notes for Parallel Agents

When dispatching subagents:

1. Give each subagent only one task from this plan.
2. Tell each subagent which batch it is in.
3. Tell Batch 1 subagents not to edit files outside their task file list.
4. Wait for all Batch 1 tasks before starting Batch 2.
5. Wait for all Batch 2 tasks before starting Batch 3.
6. Run Batch 4 in the main session.

Recommended Batch 1 dispatch:

```text
Agent A → Task 1 Composer beat-ID alignment
Agent B → Task 3 Full narration subtitles
Agent C → Task 5 Segment Producer asset candidate expansion
```

Recommended Batch 2 dispatch:

```text
Agent D → Task 2 Composer full-duration coverage
Agent E → Task 4 Visual Director beat contract validation
```

Recommended Batch 3 dispatch:

```text
Agent F → Task 6 Visual Director candidate selection + duplicate prevention
Agent G → Task 7 Job #3 regression fixture
```

---

## Success Criteria

This implementation is complete only when:

1. Composer aligns visuals by `beat_id`.
2. Composer ignores phantom beat 8 and includes beat 9 CTA.
3. Composer duration planning covers full voiceover duration.
4. Full narration subtitles render by default from word timestamps.
5. Segment Producer outputs expanded visual candidates from ScrapeCreators and Firecrawl.
6. Visual Director selects candidates without changing voiceover/timeline contracts.
7. Duplicate candidate URL reuse is avoided when alternatives exist.
8. Job #3 regression tests pass.
9. Full offline test suite passes.
10. Retried Job #3 produces a video close to voiceover length with CTA and subtitles.
