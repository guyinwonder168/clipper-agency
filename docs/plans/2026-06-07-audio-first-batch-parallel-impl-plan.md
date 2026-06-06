# Audio-First Batch-Parallel Implementation Plan

**Date:** 2026-06-07
**Status:** Draft
**Design Doc:** `docs/plans/2026-06-07-audio-first-continuous-voiceover-design.md`
**Approach:** Collapse Phases A-D into 2 mega-phases with maximum parallelism

---

## Why Batch-Parallel Instead of Sequential Phases

The original design specifies 4 sequential phases (A→B→C→D), each as a separate branch+PR+release. This is safe but slow (~16-20hr).

**Key insight enabling parallelism:** Agents communicate via DB state — they do NOT import each other. This means agent rewrites can run simultaneously as long as they share a common schema contract.

**Trade-off:**
- Original 4-phase: Lower risk, incremental releases, easier rollback
- Batch-parallel: ~50% faster, higher per-PR risk, single rollback point

**Recommendation:** Batch-parallel. The shared schema (Batch 0) eliminates the main coordination risk. Engine integration (Batch 2) remains the single sequential bottleneck.

---

## Dependency Graph

```
Batch 0 (Sequential)         Batch 1 (Full Parallel)         Batch 2 (Sequential)       Batch 3 (Parallel)
─────────────────            ─────────────────────           ──────────────────         ──────────────────
config/schema.py             ┌─ W-A: segment_producer ──┐    engine.py                  ┌─ W-D1: PRD.md
(all new models)             ├─ W-B: scriptwriter ──────┤    reviewer.py                ├─ W-D2: SRS.md
                             ├─ W-C: voice + elevenlabs ─┤    integration tests          ├─ W-D3: technical_design.md
                             ├─ W-D: visual_director ───┤                               ├─ W-D4: traceability.md
                             ├─ W-E: composer + subs ───┤                               └─ W-D5: README + AGENTS.md
                             └─ W-F: ADR document ──────┘
```

**Gate rule:** A batch does not start until its upstream batch is 100% complete.

---

## Batch 0 — Schema Foundation

**Duration:** ~1 hour
**Workers:** 1 (sequential)
**Gate:** All new Pydantic models added + existing tests still pass

### Task 0.1: Add All New Schema Models

**File:** `clipper_agency/config/schema.py`

**Why first:** Every agent imports Pydantic models from schema. A single worker adding all models prevents merge conflicts and ensures a consistent contract.

**Models to add (all additive — no existing models modified):**

```python
# --- Phase A: Segment Producer models ---

class VerifiedFact(BaseModel):
    fact: str
    source_url: str
    confidence: Literal["verified", "likely", "unconfirmed"]
    safe_wording: str

class UnverifiedClaim(BaseModel):
    claim: str
    label: str  # "rumor", "unconfirmed", etc.
    safe_wording: str

class AssetCandidate(BaseModel):
    type: str  # "tiktok_clip", "screenshot", "photo", "text_card"
    url: str
    reason: str

class BeatFallback(BaseModel):
    type: str  # "text_card", "ken_burns_photo", etc.
    headline: str
    image_search: str = ""

class StoryBeat(BaseModel):
    beat_id: int
    role: str  # "hook", "main_claim", "evidence", "reaction", "closing_cta"
    narration_goal: str
    spoken_point: str
    safe_wording: str
    visual_must_show: str
    visual_must_not_show: str
    overlay_text: str
    caption_keywords: list[str]
    asset_candidates: list[AssetCandidate]
    fallback: BeatFallback
    evidence_source: str = ""
    risk_note: str = ""

class FormatDecision(BaseModel):
    format: Literal[
        "single_story_deep_dive",
        "three_story_roundup",
        "two_story_highlight",
        "text_only",
    ]
    story_count: int
    rationale: str
    video_asset_ratio: float

class ReferenceStyle(BaseModel):
    format: str
    target_duration_sec: int
    hook_duration_sec: float
    avg_scene_duration_sec: float
    caption_style: str
    transition_style: str
    visual_priority: list[str]

# --- Phase B: Voiceover models ---

class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float

class VoiceoverOutput(BaseModel):
    status: str
    voiceover_path: str
    voiceover_duration_sec: float
    timestamps: list[WordTimestamp]
    provider: str

# --- Phase B: Scriptwriter narrative structure ---

class NarrativeBeat(BaseModel):
    beat_id: int
    section: str  # "hook", "story_1", "story_1_reveal", "closing_cta"
    description: str
    word_range: list[int]  # [start_word_index, end_word_index]
    overlay_text: str
    caption_keywords: list[str]

# --- Phase D: Reviewer quality models ---

class QualityCheckResult(BaseModel):
    check_name: str
    passed: bool
    details: dict
```

### Task 0.2: Verify Existing Tests Pass

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

**Gate criterion:** All existing tests pass with new models added.

---

## Batch 1 — Full Parallel Execution

**Duration:** ~2-3 hours per worker (wall-clock = longest worker)
**Workers:** 6 (simultaneous)
**Gate:** Each worker's tests pass independently

**Shared rules for all workers:**
- Import new models from `config/schema.py` (read-only, do not modify)
- Write unit tests for your agent/service/module
- Do NOT modify `engine.py` or any agent outside your scope
- Do NOT modify `config/schema.py` (Batch 0 owns it)
- Run your tests before signaling completion

---

### Worker A: Segment Producer (Rename + New Contract)

**Source Phase:** Phase A
**Estimated time:** ~2.5 hours

**Files:**
| Action | File |
|--------|------|
| RENAME | `clipper_agency/agents/researcher.py` → `clipper_agency/agents/segment_producer.py` |
| RENAME | `tests/agents/test_researcher.py` → `tests/agents/test_segment_producer.py` |
| REWRITE | `prompts/researcher.md` → `prompts/segment_producer.md` |
| UPDATE | `clipper_agency/agents/__init__.py` (update import) |

**Scope:**
1. Rename class `ResearcherAgent` → `SegmentProducerAgent`
2. Update all internal references (class name, logger name, docstrings)
3. Rewrite prompt as Segment Producer with edit blueprint instructions:
   - 5 roles: Fact Checker, Viral Analyst, Clip Scout, Story Producer, Edit Planner
   - Output story_beats with visual_must_show / visual_must_not_show
   - Format decision logic (single_story_deep_dive vs three_story_roundup)
   - Verified facts with safe_wording
   - Asset evaluation (clip count vs story count)
4. New output contract: `story_beats`, `format_decision`, `asset_candidates`, `do_not_use`, `verified_facts`, `unverified_claims`, `reference_style`
5. Keep existing safety checks, topic input, and tool usage (ScrapeCreators + Firecrawl)

**Tests:**
- `tests/agents/test_segment_producer.py`: Test new output contract, format decision logic, story_beats structure, asset evaluation
- All existing researcher tests renamed and updated to match new class/method names

**Verification:**
```bash
.venv/bin/python3 -m pytest tests/agents/test_segment_producer.py -v
```

---

### Worker B: Scriptwriter Voiceover Rewrite

**Source Phase:** Phase B (scriptwriter portion)
**Estimated time:** ~2 hours

**Files:**
| Action | File |
|--------|------|
| REWRITE | `prompts/scriptwriter.md` |
| MODIFY | `clipper_agency/agents/scriptwriter.py` |

**Scope:**
1. Remove `max_words_per_scene` formula entirely
2. New output contract: `voiceover_text`, `narrative_structure`, `hook_text_onscreen`, `caption`, `hashtags`, `estimated_duration_sec`
3. `voiceover_text` = single continuous narration, 75-110 words, no emojis, spoken-word style
4. `narrative_structure` = array of NarrativeBeat with `beat_id` + `word_range` mapping back to story_beats
5. Prompt rewrite instructions:
   - "Write for voiceover — text will be SPOKEN by TTS"
   - "No emojis, full sentences, spoken-word style"
   - "Sound like telling a friend, not reading headlines"
   - "Use safe wording from Researcher's verified_facts and unverified_claims"
   - "Map each section to a story beat from the edit blueprint"
   - Self-review quality check: score 1-10, rewrite if < 7
6. Input: receives `story_beats` + `verified_facts` + `unverified_claims` from segment producer output
7. Update `_parse_script_response()` to parse new format

**Tests:**
- `tests/agents/test_scriptwriter.py`: Test voiceover_text length (75-110 words), no emojis, narrative_structure mapping, beat_id linkage, word_range consistency

**Verification:**
```bash
.venv/bin/python3 -m pytest tests/agents/test_scriptwriter.py -v
```

---

### Worker C: Voice Producer + ElevenLabs Service

**Source Phase:** Phase B (voice producer + elevenlabs portions)
**Estimated time:** ~2.5 hours

**Files:**
| Action | File |
|--------|------|
| MODIFY | `clipper_agency/agents/voice_producer.py` |
| MODIFY | `clipper_agency/services/elevenlabs.py` |

**Scope:**

**elevenlabs.py changes:**
1. New method `generate_voice_with_timestamps(text, voice_id, voice_settings)` using `POST /v1/text-to-speech/{voice_id}/with-timestamps`
2. Character-level → word-level timestamp conversion (`chars_to_words()`)
3. Updated voice_settings: `stability=0.4`, `similarity_boost=0.75`, `style=0.7`, `use_speaker_boost=True`
4. Save audio to file + return `VoiceoverOutput` model

**voice_producer.py changes:**
1. New method `_generate_continuous_voiceover(voiceover_text)` → single TTS call
2. New method `_extract_word_timestamps()` for ElevenLabs (character grouping)
3. New method `_approximate_timestamps()` for Gemini TTS / Fish Audio fallback (FFmpeg silencedetect)
4. Output: `voiceover.mp3` + `timestamps` (list of WordTimestamp) + `duration`
5. Remove loop over scenes (was 8 calls → now 1 call)
6. Primary: ElevenLabs `/with-timestamps` → fallback: Gemini TTS with silence detection → last resort: Fish Audio

**Tests:**
- `tests/services/test_elevenlabs.py`: Test `/with-timestamps` endpoint mock, chars_to_words conversion, voice settings
- `tests/agents/test_voice_producer.py`: Test single audio generation, timestamp extraction, Gemini fallback, output contract

**Verification:**
```bash
.venv/bin/python3 -m pytest tests/services/test_elevenlabs.py tests/agents/test_voice_producer.py -v
```

---

### Worker D: Visual Director Beat-Driven Planning

**Source Phase:** Phase C (visual director portion)
**Estimated time:** ~2 hours

**Files:**
| Action | File |
|--------|------|
| REWRITE | `prompts/visual_director.md` |
| MODIFY | `clipper_agency/agents/visual_director.py` |

**Scope:**
1. Accept `story_beats` + `timestamps` + `do_not_use` as input
2. Beat-driven visual planning: for each beat, answer "Why am I showing this while the viewer hears this?"
3. Visual selection hierarchy per beat:
   - Direct source clip (TikTok/Instagram)
   - Official screenshot
   - Subject portrait with Ken Burns
   - Text card with headline
   - Generic stock (ONLY if Researcher marked beat as abstract)
4. Use `asset_candidates` from segment producer BEFORE searching Pexels
5. Validate visuals against `visual_must_show` / `visual_must_not_show` rules
6. Use exact durations from audio timestamps (not estimates)
7. LLM receives: beat durations, visual rules, asset candidates, do_not_use list, total audio duration

**Tests:**
- `tests/agents/test_visual_director.py`: Test beat-driven planning, visual hierarchy, asset candidate priority, must_show validation, do_not_use enforcement

**Verification:**
```bash
.venv/bin/python3 -m pytest tests/agents/test_visual_director.py -v
```

---

### Worker E: Composer Smart Trimming + Subtitle Engine

**Source Phase:** Phase C (composer + subtitle portions)
**Estimated time:** ~3 hours

**Files:**
| Action | File |
|--------|------|
| MODIFY | `clipper_agency/agents/composer.py` |
| MODIFY | `clipper_agency/rendering/subtitle_engine.py` |

**Scope:**

**composer.py changes:**
1. New method `_smart_trim(clip_path, target_duration_sec)`:
   - Probe clip duration with ffprobe
   - Run ffprobe scene detection → find scene boundaries
   - If boundary within ±15% of target: trim at boundary + speed-adjust
   - If no good boundary: simple trim from start + speed-adjust
   - If clip shorter: slow down max 30% or loop
2. New method `_detect_scene_boundaries(clip_path)` using ffprobe
3. Refactor `_compose()` to use single audio timeline:
   - `voiceover.mp3` = timeline anchor (never trimmed)
   - Visuals = laid over audio, trimmed/fitted to match
   - Keyword captions per beat, aligned to audio timeline
4. Remove per-scene audio concatenation logic
5. Hard cuts (primary) + crossfade (occasional) transitions

**subtitle_engine.py changes:**
1. Keyword captions instead of full sentence subtitles
2. Position: bottom of frame (standard reading position)
3. Style: large, bold, white text with dark shadow/outline
4. Duration: aligned to beat audio timeline
5. Change: new keyword at each beat boundary
6. If downloaded clip has bottom text, shift caption slightly higher

**Tests:**
- `tests/agents/test_composer.py`: Test smart trim (boundary found, no boundary, clip shorter), single audio timeline, keyword overlay positioning
- `tests/rendering/test_subtitle_engine.py`: Test keyword caption format, positioning, beat alignment

**Verification:**
```bash
.venv/bin/python3 -m pytest tests/agents/test_composer.py tests/rendering/test_subtitle_engine.py -v
```

---

### Worker F: ADR Document

**Source Phase:** Cross-cutting (all phases)
**Estimated time:** ~1 hour

**Files:**
| Action | File |
|--------|------|
| CREATE | `docs/adr/0021-audio-first-continuous-voiceover.md` |

**Scope:**
1. Context: Why audio-first, why continuous voiceover, why segment producer
2. Decision: Audio-first production pipeline with beat-driven architecture
3. Alternatives considered: Visual-first (Workflow B), per-scene TTS (current), Eleven v3
4. Consequences: Single TTS call (cost savings), sequential voice→visual (no parallelism), schema dependency

**Verification:** File exists and follows ADR format from `docs/adr/0001-use-python-ffmpeg.md`.

---

## Batch 1 Gate Criteria

Before proceeding to Batch 2, ALL workers must report:

1. **All unit tests pass** (each worker's test suite)
2. **No modification to shared files** outside worker scope
3. **New code imports from schema.py** (read-only dependency)
4. **No engine.py changes** (Batch 2 owns this)

**Gate check command:**
```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

---

## Batch 2 — Integration

**Duration:** ~2-3 hours
**Workers:** 1 (sequential)
**Gate:** Full pipeline integration test passes

### Task 2.1: Orchestrator Pipeline Reordering

**File:** `clipper_agency/orchestrator/engine.py`

**Why sequential:** `engine.py` imports ALL agents. It must be updated after all agent signatures are finalized.

**Scope:**
1. Remove parallel Voice + Visual execution (was `asyncio.gather`)
2. New sequential order: Researcher → Scriptwriter → Voice Producer → Visual Director → Composer → Reviewer
3. Pass data between agents:
   - Segment Producer → Scriptwriter: `story_beats`, `verified_facts`, `unverified_claims`
   - Scriptwriter → Voice Producer: `voiceover_text`
   - Voice Producer → Visual Director: `timestamps`, `voiceover_duration_sec`
   - Segment Producer → Visual Director: `story_beats`, `do_not_use`, `asset_candidates`
   - Voice Producer → Composer: `voiceover_path`, `timestamps`
   - Scriptwriter → Composer: `narrative_structure`
   - Visual Director → Composer: visual assets
4. Remove `story_direction["max_scenes"] = sc * 2 + 2` formula
5. Update all `_run_*` method signatures for new data flow
6. Update agent state tracking for renamed SegmentProducerAgent

### Task 2.2: Reviewer Quality Gates

**File:** `clipper_agency/agents/reviewer.py`

**Scope:**
1. Sync validation: audio duration vs visual duration (drift < 0.5s)
2. Visual relevance: no generic stock for named-person beats
3. Caption quality: keyword style (max 6 words), changes at beat boundaries
4. Fact safety: unverified claims use safe wording
5. Output: structured quality report with per-check pass/fail

### Task 2.3: Integration Tests

**File:** `tests/test_audio_first_pipeline.py` (new)

**Scope:**
- End-to-end data flow test (mocked LLM/TTS, real schema validation)
- Verify story_beats flow through all agents
- Verify timestamps flow from voice_producer → visual_director → composer
- Verify voiceover_text is single continuous text (not per-scene fragments)
- Verify pipeline order is sequential (no parallel voice+visual)

**Verification:**
```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

**Gate criterion:** All tests pass including new integration tests.

---

## Batch 3 — Documentation

**Duration:** ~1 hour
**Workers:** 5 (parallel)
**Gate:** All docs updated, consistent with implementation

### Worker D1: PRD.md Updates
- PR-02 pipeline flow (researcher → segment_producer, sequential voice→visual)
- Cost model update (87.5% fewer TTS calls)
- Caption position rules
- Reviewer quality checks

### Worker D2: SRS.md Updates
- FR-03 researcher → segment_producer
- FR-05 continuous voiceover
- FR-06 single TTS call
- FR-07 beat-driven visual
- FR-08 single audio timeline + smart trimming
- FR-09 enhanced reviewer
- Voice settings env vars

### Worker D3: technical_design.md Updates
- §3 Pipeline flow diagram (sequential order)
- §4 Agent roles table (all new contracts)
- §6 Orchestrator data flow
- §7 Content planning (segment producer role)
- Researcher output schema → Segment Producer output schema

### Worker D4: requirements_traceability.md Updates
- New fact register entries for rename
- New beat contract facts
- Voiceover contract facts
- Timestamp extraction facts
- Quality gate edge cases

### Worker D5: README.md + AGENTS.md Updates
- Pipeline diagram (sequential voice → visual)
- Project structure (researcher → segment_producer)
- Repository state section
- Test count update

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|:-----------:|:------:|------------|
| Schema.py merge conflict in Batch 1 | Low | High | Batch 0 is single-worker; Batch 1 workers read schema only |
| Agent test fixtures inconsistent | Medium | Medium | All workers use schema models for test data (single source of truth) |
| Engine.py integration breaks | Medium | High | Batch 2 is sequential with explicit gate; integration tests catch issues |
| SonarCloud flags on large PR | Medium | Low | Run `--cov` locally before push; fix incrementally on branch |
| Prompt quality varies across workers | Medium | Medium | Workers A, B, D each write their own prompt; single reviewer validates in Batch 3 |
| Rename (researcher→segment_producer) misses references | Low | Medium | Grep for all occurrences; update tests, __init__.py, docs |

---

## Execution Checklist

### Pre-Flight
- [ ] All 783 offline tests pass on current master
- [ ] Branch created: `phase/audio-first-continuous-voiceover`
- [ ] Batch 0 worker assigned

### Batch 0 — Schema
- [ ] All Pydantic models added to `config/schema.py`
- [ ] Existing tests still pass
- [ ] Gate: ✓

### Batch 1 — Parallel Workers
- [ ] Worker A (Segment Producer): tests pass
- [ ] Worker B (Scriptwriter): tests pass
- [ ] Worker C (Voice + ElevenLabs): tests pass
- [ ] Worker D (Visual Director): tests pass
- [ ] Worker E (Composer + Subtitles): tests pass
- [ ] Worker F (ADR): file created
- [ ] Full test suite: all pass
- [ ] Gate: ✓

### Batch 2 — Integration
- [ ] Engine.py pipeline reordered
- [ ] Reviewer quality gates added
- [ ] Integration tests written and passing
- [ ] Full test suite: all pass
- [ ] Coverage ≥ 93%
- [ ] Gate: ✓

### Batch 3 — Documentation
- [ ] PRD.md updated
- [ ] SRS.md updated
- [ ] technical_design.md updated
- [ ] requirements_traceability.md updated
- [ ] README.md + AGENTS.md updated
- [ ] Gate: ✓

### Release
- [ ] Push branch → open PR
- [ ] Wait for SonarCloud ✅
- [ ] Fix any SonarCloud issues
- [ ] Merge (`--merge`, no squash)
- [ ] Tag: `v2.0.0`
- [ ] GitHub Release with changelog
- [ ] Delete branch, pull master

---

## Time Estimate

| Batch | Duration | Parallelism | Wall-clock |
|-------|----------|-------------|------------|
| Batch 0 | 1h | 1 worker | 1h |
| Batch 1 | 2-3h/worker | 6 workers | ~3h |
| Batch 2 | 2-3h | 1 worker | ~3h |
| Batch 3 | 1h | 5 workers | ~1h |
| **Total** | | | **~8-10h** |

**Comparison:** Original 4 sequential phases = ~16-20hr. Batch-parallel = ~50% savings.
