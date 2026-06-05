# Composer Treatment & Transition Engine — Full Tier 3 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce TikTok-upload-quality video by fixing ALL Composer output issues: voice clashing, missing subtitles, per-scene narration sync, treatment filters, and xfade transitions. Every pain point from job_2 output must be resolved.

**Pain Points Solved:**

| # | Pain Point | Root Cause | Batch | Fix |
|---|-----------|------------|-------|-----|
| PP1 | Voice clashing — all audio plays simultaneously | `amix=inputs=N` starts all at time 0 | B3 | Per-scene `concat` with audio tracks |
| PP2 | No subtitles — script text exists but never rendered | No subtitle logic anywhere | B4 | SubtitleEngine generates timed drawtext from script |
| PP3 | Per-scene narration not synced to video | `amix` ignores scene boundaries | B3 | Scene-audio pair `concat=n=N:v=1:a=1` |
| PP4 | Treatments/transitions not applied | `_build_assembly_cmd()` has no treatment logic | B0-B2 | TreatmentFilterBuilder + xfade chain |
| PP5 | Missing production flags | No `-pix_fmt yuv420p` / `-movflags +faststart` | B1 | Add to FFmpeg output flags |

**Tech Stack:** Python 3.11+, FFmpeg 5.0+ (xfade requires FFmpeg 4.3+), PyYAML (already a dep), pytest

**Research reference:** `docs/research/ffmpeg-visual-techniques.md`

---

## Architecture Overview

```
                        BATCH DEPENDENCY GRAPH

  B0 Foundation ─────────────────────────────────────────────┐
  (3 parallel)                                               │
  ├─ 0A TreatmentConfig YAML Loader                          │
  ├─ 0B TreatmentFilterBuilder                               │
  └─ 0C Template Validation Tests                            │
          │                                                  │
          ▼                                                  │
  B1 Treatment Filters in Composer ──────────────────────────┤
  (Sequential)                                               │
          │                                                  │
          ▼                                                  │
  B2 xfade Transition Engine ────────────────────────────────┤
  (Sequential)                                               │
          │                                                  │
          ▼                                                  │
  B3 Audio Sequencer ────────────────────────────────────────┤
  (2 parallel)                                               │
  ├─ 3A Audio Sequencer module                               │
  └─ 3B Audio integration in Composer                        │
          │                                                  │
          ▼                                                  │
  B4 Subtitle Engine ────────────────────────────────────────┤
  (2 parallel)                                               │
  ├─ 4A SubtitleEngine module                                │
  └─ 4B Script passthrough in Orchestrator                   │
          │                                                  │
          ▼                                                  │
  B5 Composer Unified Refactor ──────────────────────────────┤
  (Sequential — wires B2+B3+B4 together)                     │
          │                                                  │
          ▼                                                  │
  B6 Production Polish ──────────────────────────────────────┤
  (2 parallel)                                               │
  ├─ 6A Hook overlay + production validation                 │
  └─ 6B Edge cases + coverage                                │
          │                                                  │
          ▼                                                  │
  B7 Final Validation ◄──────────────────────────────────────┘
```

---

## Research Reference

The research document `docs/research/ffmpeg-visual-techniques.md` defines the FFmpeg filter patterns used throughout this implementation. Key excerpts:

**Image treatment pattern (from Example 1):**
```
[0:v]scale=5400:-1,zoompan=z='...':d=150:s=1080x1920:fps=30,fps=30,trim=duration=5[s0];
[s0][s1]xfade=transition=fade:duration=0.5:offset=4.5[outv]
```

**Mixed concat+xfade chain (from Example 4):**
```
[n0][n1]concat=n=2:v=1[v1];
[v1][n2]xfade=transition=fade:duration=0.3:offset=7.7[v2];
[v2][n3]concat=n=2:v=1[outv]
```

**Per-scene audio+video concat (the fix for PP1+PP3):**
```
# Each scene gets its own audio track paired with video
[0:v]trim=duration=5,setpts=PTS-STARTPTS[v0];
[1:v]trim=duration=5,setpts=PTS-STARTPTS[v1];
[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]
```

**Critical pitfalls (research doc lines 533-541):**
- `-pix_fmt yuv420p` — Always add after xfade for player compatibility
- `-movflags +faststart` — Always add for MP4 output
- `setsar=1/1` — After any scale/crop, prevent SAR distortion
- 0.1s safety margin — Subtract from xfade offset to prevent running past clip end
- Transition duration < shortest clip — Validate or FFmpeg errors

---

## Current Code State (Pre-Implementation)

### `composer.py:_build_assembly_cmd()` (lines 496-550) — THE BROKEN METHOD
```python
# CURRENT: Per-scene — NO treatment filters
[i:v]trim=duration=X,setpts=PTS-STARTPTS[ti]

# CURRENT: Video — simple concat, NO transitions
concat=n=N:v=1[outv]

# CURRENT: Audio — BROKEN: plays ALL audio simultaneously from time 0
amix=inputs=N:duration=first[outa]

# CURRENT: Output — MISSING: -pix_fmt yuv420p, -movflags +faststart
```

### `rendering/engine.py` (329 lines) — EXISTS but UNUSED by Composer
- `_build_drawtext(caption, time_offset)` — timed drawtext with `enable='between(t,start,end)'`
- `_build_transition_chain()` — supports cut/fade/crossfade
- `_collect_caption_offsets()` — flattens scene captions with absolute offsets
- **Audio: Uses `anullsrc` (silent)** — no real audio support
- **This engine is NOT used by ComposerAgent.** Composer has its own `_build_assembly_cmd()`.

### `rendering/contracts.py` — CaptionOverlay + RenderScene + RenderPlan
- `CaptionOverlay(text, start_seconds, end_seconds, position, style)`
- `RenderScene(source_path, duration_seconds, captions, overlays, transition, ...)`

### Orchestrator Data Flow
```python
# orchestrator/engine.py lines 293-296
compose_output = self._run_composer(
    job_id=job_id,
    assets=visual_output.get("assets", []),        # visual director scenes
    audio_files=voice_output.get("audio_files", []), # voice producer per-scene files
    output_dir=output_dir, assets_cache=assets_cache,
)
# NOTE: script_output.get("script", []) is NOT passed to composer — MUST FIX
```

---

## Batch 0 — Foundation (Parallel: 3 tasks, zero file overlap)

### Task 0A: TreatmentConfig — YAML loader for `templates/treatments.yaml`

**Files:**
- Create: `clipper_agency/rendering/treatment_config.py`
- Test: `tests/test_treatment_config.py`

**Responsibility:** Load and validate the YAML, expose `get_treatment(name)` and `get_transition(name)` lookups with frozen dataclasses (`TreatmentDef`, `TransitionDef`). Expose `target_fps` and `pacing` from `fps_rules` and `pacing_rules` sections.

- [ ] **Step 1: Write failing test** — 9 test cases covering: loading all 9+ treatments, field access, null filter for `broll_standard`, transition defs, `hard_cut` null filter, unknown name returns None, fps_rules, pacing_rules, custom path constructor
- [ ] **Step 2: Run** — expect `ModuleNotFoundError`
- [ ] **Step 3: Implement** — `TreatmentDef(frozen)`, `TransitionDef(frozen)`, `TreatmentConfig(path)` with internal `yaml.safe_load()`. Reference implementation exists in the original plan lines 128-208.
- [ ] **Step 4: Verify** — All 9 tests pass
- [ ] **Step 5: Commit as** `feat: add TreatmentConfig YAML loader`

---

### Task 0B: TreatmentFilterBuilder — per-scene FFmpeg filter string generation

**Files:**
- Create: `clipper_agency/rendering/treatment_filters.py`
- Test: `tests/test_treatment_filters.py`

**Responsibility:** Given an asset dict and a `TreatmentConfig`, build the FFmpeg filter string for that treatment.

**Variable substitution:**
| Variable | Source | Example |
|----------|--------|---------|
| `{frames}` | `int(duration * fps)` | `150` (5s@30fps) |
| `{text}` | `asset.get("headline", "")` | `"Breaking News"` |
| `{duration}` | `asset.get("target_duration", 5)` | `5` |
| `{start_time}` | cumulative offset param | `4.0` |

**Input-type rules:**
- `image`: Prepend `scale=5400:-1,` for zoompan pixel room (research doc: "pre-scale to 5x target width")
- `video`: Apply filter as-is; `null` filter -> return `"null"`
- `text`: `drawtext` with `{text}` substitution
- Add `,setsar=1/1` after any scale/crop (research pitfall #4)

- [ ] **Step 1: Write failing test** — 13 cases: frames substitution, text substitution, text default, duration substitution, start_time, image pre-scale, video no pre-scale, null returns "null", unknown returns "null", slow_motion setpts, text_card_reveal alpha, lower_third drawtext, cinematic_crop crop
- [ ] **Step 2: Run** — expect `ModuleNotFoundError`
- [ ] **Step 3: Implement** — `TreatmentFilterBuilder(config).build(asset, start_time=0.0) -> str`. Reference implementation exists in the original plan lines 352-405.
- [ ] **Step 4: Verify** — All 13 tests pass
- [ ] **Step 5: Commit as** `feat: add TreatmentFilterBuilder for per-scene filter strings`

---

### Task 0C: Expand treatment template validation tests

**Files:**
- Modify: `tests/test_treatment_templates.py` (existing, 7 tests)

**Add tests:** All xfade transitions have `{duration}` and `{offset}` vars; image treatments use `zoompan`; fps_rules present; pacing_rules have hook_window

- [ ] **Step 1: Read existing** `tests/test_treatment_templates.py`
- [ ] **Step 2: Add 4 validation tests**
- [ ] **Step 3: Run** — All 11 tests pass
- [ ] **Step 4: Commit as** `test: expand treatment template validation with TreatmentConfig`

---

## Batch 1 — Treatment Filters in Composer (Sequential, depends on Batch 0)

### Task 1: Integrate treatments into `_build_assembly_cmd()`

**Files:**
- Modify: `clipper_agency/agents/composer.py` (~30 lines changed)
- Test: `tests/test_composer.py`

**What changes:** The per-scene filter graph changes from:
```
[i:v]trim=duration=X,setpts=PTS-STARTPTS[ti]
```
To:
```
[i:v]{treatment_filter},trim=duration=X,setpts=PTS-STARTPTS[ti]
```

When treatment_filter is "null" -> no extra filter (backward compatible). Also add `-pix_fmt yuv420p` and `-movflags +faststart` to the FFmpeg output args (needed for xfade in Batch 2, safe to add now per research pitfalls #1/#2).

**Implementation approach:**
- Add module-level lazy singleton for `TreatmentConfig` + `TreatmentFilterBuilder` (avoids per-call YAML re-parsing)
- In the per-input loop: call `builder.build(asset)` and prepend result to trim filter chain when not "null"
- Keep existing trim logic unchanged

- [ ] **Step 1: Write failing tests** — 5 cases:
  - `test_build_assembly_cmd_applies_treatment_filter` — cinematic_crop appears in filter graph
  - `test_build_assembly_cmd_null_treatment_no_extra_filter` — broll_standard keeps original trim behavior
  - `test_build_assembly_cmd_treatment_respects_duration` — trim duration unchanged
  - `test_build_assembly_cmd_text_treatment_substitutes_vars` — headline appears in drawtext
  - `test_build_assembly_cmd_no_treatment_metadata_still_works` — backward compat
- [ ] **Step 2: Implement** in `composer.py:_build_assembly_cmd()`
- [ ] **Step 3: Run** `pytest tests/test_composer.py -v` — All existing + 5 new pass
- [ ] **Step 4: Run full suite** — 699+ pass, 93%+ coverage
- [ ] **Step 5: Commit as** `feat: integrate treatment filters into Composer assembly`

---

## Batch 2 — xfade Transition Engine (Sequential, depends on Batch 1)

### Task 2: Replace concat with xfade chain per transition metadata

**Files:**
- Modify: `clipper_agency/agents/composer.py` (`_build_assembly_cmd()`, significant refactor)
- Test: `tests/test_composer.py`

**Core algorithm** (sequential chain, research Example 4 pattern):

1. Generate per-scene labeled outputs (treatment + trim -> `s0`, `s1`, ... `sN`)
2. Start: `current_label = "s0"`, `cumulative_duration = scene[0].duration`
3. For i = 1 to N-1:
   - Look up `transition_out` of scene i-1 -> `TransitionDef`
   - If xfade (filter != null):
     - `offset = cumulative_duration - trans_duration - 0.1` (safety margin)
     - Clamp trans_duration if > `min(prev_dur, next_dur) - 0.15`
     - Generate: `[current_label][s{i}]xfade=...:duration={d}:offset={o}[x{i}]`
     - `current_label = "x{i}"`, update cumulative_duration
   - If hard_cut (filter == null):
     - Generate: `[current_label][s{i}]concat=n=2:v=1[c{i}]`
     - `current_label = "c{i}"`, `cumulative_duration += duration`
4. Final `current_label` = filter graph output

**Transition metadata:**
- Scene N's `transition_out` controls transition between N and N+1
- `transition_in` is preserved but unused (no "in" concept in xfade)
- Last scene: no transition applied
- Missing metadata -> default `crossfade`
- `transition_duration` field in asset overrides template default

**FFmpeg flags:** Ensure `-pix_fmt yuv420p` and `-movflags +faststart` are present (added in Batch 1)

- [ ] **Step 1: Write failing tests** — 8 cases:
  - `test_build_assembly_cmd_applies_xfade_transition` — `xfade=` in filter_complex, no concat
  - `test_build_assembly_cmd_hard_cut_uses_concat` — `concat=` present, no xfade
  - `test_build_assembly_cmd_mixed_transitions` — both concat AND xfade in 3-scene filter graph
  - `test_xfade_offset_calculated_correctly` — `offset=4.6` for 5s clip + 0.3s transition + 0.1 safety
  - `test_xfade_uses_transition_duration_from_metadata` — custom duration in asset used
  - `test_last_scene_no_transition_out` — only 1 xfade for 2 scenes (last has no out)
  - `test_transition_duration_clamped_to_shortest_clip` — 1s transition on 2s clip -> clamped
  - `test_xfade_unknown_transition_falls_back_to_default` — graceful degradation
- [ ] **Step 2: Implement** refactored filter graph builder in `_build_assembly_cmd()`
- [ ] **Step 3: Run** `pytest tests/test_composer.py -v` — All existing + 8 new pass
- [ ] **Step 4: Run full suite** — 699+ pass, 93%+ coverage
- [ ] **Step 5: Commit as** `feat: add xfade transition engine with mixed concat/xfade support`

---

## Batch 3 — Audio Sequencer (Parallel: 2 tasks, depends on B2)

> **Solves PP1 (voice clashing) + PP3 (per-scene narration sync)**

### Current Broken Audio (composer.py lines 527-534)
```python
# BROKEN: All audio plays simultaneously from time 0
audio_inputs = "".join(f"[{num_videos + i}:a]" for i in range(len(audio_files)))
f";{audio_inputs}amix=inputs={len(audio_files)}:duration=first[outa]"
```

### Fix: Per-Scene Audio+Video Concat
```python
# FIXED: Each scene's audio paired with its video, concatenated sequentially
# [v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]
```

The voice producer already outputs per-scene files at `data/assets/cache/job_{id}/agents/voice_producer/voices/scene_1.mp3` through `scene_N.mp3`. The fix is pairing each audio file with its corresponding video scene in a single `concat` operation.

### Task 3A: Audio Sequencer module

**Files:**
- Create: `clipper_agency/rendering/audio_sequencer.py`
- Test: `tests/test_audio_sequencer.py`

**Responsibility:** Pure function that builds the per-scene audio+video concat filter string.

**API:**
```python
def build_audio_video_concat(
    scene_labels: list[str],        # e.g. ["s0", "s1", "s2"]
    num_video_inputs: int,           # number of -i video inputs
    audio_file_count: int,           # number of audio files
) -> tuple[str, str, str]:
    """Returns (filter_parts_str, output_video_label, output_audio_label).

    Example output for 3 scenes with 3 audio files:
    "[s0][3:a][s1][4:a][s2][5:a]concat=n=3:v=1:a=1[outv][outa]"
    output_video_label = "outv"
    output_audio_label = "outa"
    """
```

**Edge cases:**
- No audio files -> generate `anullsrc` (silent) as fallback
- Fewer audio files than scenes -> pad missing with `anullsrc` per scene
- More audio files than scenes -> truncate to scene count
- Single scene -> no concat needed, direct label

- [ ] **Step 1: Write failing tests** — 8 cases:
  - `test_pairs_audio_to_video` — 3 scenes + 3 audio -> `concat=n=3:v=1:a=1`
  - `test_no_audio_generates_silence` — 0 audio files -> `anullsrc`
  - `test_fewer_audio_than_scenes_pads_silence` — 3 scenes + 2 audio -> pad scene 3 with silence
  - `test_more_audio_truncates` — 2 scenes + 3 audio -> use only first 2
  - `test_single_scene_no_concat` — 1 scene + 1 audio -> direct mapping
  - `test_audio_input_indices_offset_by_video_count` — audio indices start at `num_video_inputs`
  - `test_output_labels_correct` — returns `("outv", "outa")`
  - `test_audio_sequencer_is_pure` — same inputs always produce same output
- [ ] **Step 2: Run** — expect `ModuleNotFoundError`
- [ ] **Step 3: Implement** — Pure function, no file I/O, no side effects
- [ ] **Step 4: Verify** — All 8 tests pass
- [ ] **Step 5: Commit as** `feat: add AudioSequencer for per-scene audio pairing`

---

### Task 3B: Integrate audio sequencer into Composer

**Files:**
- Modify: `clipper_agency/agents/composer.py` (`_build_assembly_cmd()`)
- Test: `tests/test_composer.py`

**What changes:** Replace the `amix` filter with `build_audio_video_concat()` output.

```python
# BEFORE (BROKEN):
audio_inputs = "".join(f"[{num_videos + i}:a]" for i in range(len(audio_files)))
f";{audio_inputs}amix=inputs={len(audio_files)}:duration=first[outa]"

# AFTER (FIXED):
from clipper_agency.rendering.audio_sequencer import build_audio_video_concat
audio_filter, video_out, audio_out = build_audio_video_concat(
    scene_labels=scene_labels,
    num_video_inputs=num_videos,
    audio_file_count=len(audio_files),
)
```

**Important:** When xfade transitions are used, `concat` can't be used for audio+video together (xfade outputs a merged video stream). In this case, use the concat for audio-only alongside the xfade video chain. The audio_sequencer must handle both modes:
- **Mode A (no xfade):** `concat=n=N:v=1:a=1` — paired audio+video
- **Mode B (with xfade):** Audio gets its own `concat=n=N:a=1[outa]`, video uses xfade chain

- [ ] **Step 1: Write failing tests** — 6 cases:
  - `test_assembly_uses_concat_audio_when_all_hard_cut` — `concat` with `:a=1`
  - `test_assembly_uses_separate_audio_concat_when_xfade` — audio `concat` separate from video xfade
  - `test_assembly_no_audio_uses_silence` — `anullsrc` in filter graph
  - `test_assembly_audio_matches_scene_count` — 5 scenes + 5 audio files
  - `test_assembly_audio_fewer_files_pads` — 5 scenes + 3 audio files -> padded
  - `test_assembly_preserves_existing_video_chain` — video chain unchanged by audio integration
- [ ] **Step 2: Implement** in `composer.py:_build_assembly_cmd()`
- [ ] **Step 3: Run** `pytest tests/test_composer.py -v`
- [ ] **Step 4: Run full suite** — 699+ pass, 93%+ coverage
- [ ] **Step 5: Commit as** `feat: integrate per-scene audio sequencing into Composer`

---

## Batch 4 — Subtitle Engine (Parallel: 2 tasks, depends on nothing new)

> **Solves PP2 (no subtitles)**

### Task 4A: SubtitleEngine module

**Files:**
- Create: `clipper_agency/rendering/subtitle_engine.py`
- Test: `tests/test_subtitle_engine.py`

**Responsibility:** Convert script text per scene into timed `CaptionOverlay` objects that can be rendered as FFmpeg drawtext filters.

**API:**
```python
from clipper_agency.rendering.contracts import CaptionOverlay

def build_subtitle_overlays(
    scenes: list[dict],  # scriptwriter output: [{"text": "...", "duration": 5.0}, ...]
    words_per_caption: int = 6,
) -> list[CaptionOverlay]:
    """Convert scene texts to timed caption overlays.

    Each scene's text is split into chunks of `words_per_caption` words.
    Each chunk gets a start/end time calculated from the scene's duration.
    Returns a flat list of CaptionOverlay with absolute timestamps.
    """
```

**Timing calculation:**
- Scene N starts at `sum(scene[i].duration for i in range(N))`
- Scene N's text is split into chunks of `words_per_caption` words
- Each chunk's duration = `scene_duration / number_of_chunks`
- Chunk k starts at `scene_start + k * chunk_duration`

**Subtitle styling (TikTok-optimized):**
- Font: `fontsize=36` (readable on mobile)
- Position: bottom center (`x=(w-tw)/2:y=h-th-80`)
- Style: white text with black border (`fontcolor=white:borderw=3:bordercolor=black`)
- Enable: `enable='between(t,start,end)'`

**Uses existing infrastructure:**
- `rendering/primitives.py:escape_drawtext()` — escapes FFmpeg special chars
- `rendering/primitives.py:make_caption_overlays()` — similar logic, can reuse patterns
- `rendering/contracts.py:CaptionOverlay` — existing Pydantic model

- [ ] **Step 1: Write failing tests** — 10 cases:
  - `test_single_scene_single_caption` — 5 words, 5s -> 1 overlay spanning 0-5s
  - `test_single_scene_split_captions` — 12 words, 6s, wpc=6 -> 2 overlays, 3s each
  - `test_multi_scene_absolute_timing` — 2 scenes, second scene captions start after first
  - `test_empty_scene_text_skipped` — scene with empty text produces no overlays
  - `test_special_chars_escaped` — quotes, colons, apostrophes in text
  - `test_words_per_caption_splits_correctly` — 18 words, wpc=6 -> 3 chunks
  - `test_caption_overlay_has_all_fields` — text, start_seconds, end_seconds, position, style
  - `test_default_words_per_caption_is_6` — uses default when not specified
  - `test_scene_with_no_duration_defaults_to_5` — graceful default
  - `test_single_word_caption` — 1 word still produces an overlay
- [ ] **Step 2: Run** — expect `ModuleNotFoundError`
- [ ] **Step 3: Implement** — Pure function, uses `CaptionOverlay` contract
- [ ] **Step 4: Verify** — All 10 tests pass
- [ ] **Step 5: Commit as** `feat: add SubtitleEngine for timed caption overlays`

---

### Task 4B: Script passthrough in Orchestrator

**Files:**
- Modify: `clipper_agency/orchestrator/engine.py` (~10 lines changed)
- Test: `tests/test_orchestrator.py`

**What changes:** Pass `script_output` to `_run_composer()` so the Composer can generate subtitles.

**Current flow (orchestrator/engine.py line 293-296):**
```python
compose_output = self._run_composer(
    job_id=job_id,
    assets=visual_output.get("assets", []),
    audio_files=voice_output.get("audio_files", []),
    output_dir=output_dir, assets_cache=assets_cache,
)
```

**New flow:**
```python
compose_output = self._run_composer(
    job_id=job_id,
    assets=visual_output.get("assets", []),
    audio_files=voice_output.get("audio_files", []),
    script_scenes=script_output.get("script", []),  # NEW: pass script text
    output_dir=output_dir, assets_cache=assets_cache,
)
```

This requires:
1. `_stage_composition()` extracts `script_output.get("script", [])`
2. `_run_composer()` accepts new `script_scenes` parameter
3. `ComposerAgent.execute()` accepts and stores `script_scenes`
4. Backward compatible: `script_scenes` defaults to `[]`

- [ ] **Step 1: Write failing test** — verify Composer receives script_scenes
- [ ] **Step 2: Implement** parameter threading in orchestrator + composer signature
- [ ] **Step 3: Run** `pytest tests/test_orchestrator.py tests/test_composer.py -v`
- [ ] **Step 4: Run full suite** — 699+ pass, 93%+ coverage
- [ ] **Step 5: Commit as** `feat: pass script text through to Composer for subtitles`

---

## Batch 5 — Composer Unified Refactor (Sequential, depends on B2+B3+B4)

### Task 5: Wire treatments + audio + subtitles + transitions into unified assembly

**Files:**
- Modify: `clipper_agency/agents/composer.py` (major refactor of `_build_assembly_cmd()`)
- Test: `tests/test_composer.py`

**What changes:** The `_build_assembly_cmd()` method now uses ALL the pieces built in B0-B4:

```
Per-scene treatment filters (B0/B1)
    + xfade/concat transition chain (B2)
    + per-scene audio pairing (B3)
    + timed subtitle drawtext (B4)
    = Production-grade TikTok video
```

**New `_build_assembly_cmd()` structure:**

```
1. Per-scene: treatment_filter + trim -> labeled scene outputs [s0]...[sN]
2. Transition chain: xfade/concat -> unified video stream [vout]
3. Audio chain: per-scene concat -> [aout]  (parallel to video if xfade)
4. Subtitle chain: timed drawtext on [vout] -> [vout_with_subs]
5. Output: -map [vout_with_subs] -map [aout] + production flags
```

**Subtitle integration with xfade:**
- After xfade chain produces final video label, apply subtitle drawtext filters
- Each `CaptionOverlay` becomes a `drawtext=...:enable='between(t,start,end)'` filter chained onto the video output
- Use existing `rendering/engine.py:_build_drawtext()` pattern as reference

**The method signature expands:**
```python
@staticmethod
def _build_assembly_cmd(
    valid_normalized: list[str],
    normalized_assets: list[dict],
    audio_files: list[str],
    script_scenes: list[dict],  # NEW: for subtitle generation
    output_path: str,
) -> list[str]:
```

- [ ] **Step 1: Write failing tests** — 6 integration cases:
  - `test_full_pipeline_treatment_audio_subtitles` — all 3 subsystems active in filter graph
  - `test_pipeline_audio_no_subtitles` — audio works without script text
  - `test_pipeline_subtitles_no_audio` — subtitles render with silent audio
  - `test_pipeline_xfade_with_audio_and_subtitles` — the full production case
  - `test_pipeline_hard_cut_with_audio_and_subtitles` — concat-based production case
  - `test_pipeline_backward_compat_no_audio_no_script` — original behavior preserved
- [ ] **Step 2: Implement** unified `_build_assembly_cmd()` refactoring
- [ ] **Step 3: Run** `pytest tests/test_composer.py -v` — All existing + new pass
- [ ] **Step 4: Run full suite** — 699+ pass, 93%+ coverage
- [ ] **Step 5: Commit as** `feat: unify treatment+audio+subtitle+transition in Composer assembly`

---

## Batch 6 — Production Polish (Parallel: 2 tasks, depends on B5)

### Task 6A: Hook overlay + production validation

**Files:**
- Modify: `clipper_agency/rendering/subtitle_engine.py` (add hook overlay support)
- Test: `tests/test_subtitle_engine.py`

**Hook overlay for `hook_big_caption` treatment:**
- First 3 seconds of video get a large hook caption overlay
- Text comes from first scene's headline or hook text
- Uses `pacing_rules.hook_window` from `treatments.yaml` (default: 3s)
- Styling: larger font (fontsize=72), bold, centered, with animation

**Production validation checklist (TikTok requirements):**

| Requirement | Value | Verified By |
|------------|-------|-------------|
| Resolution | 1080x1920 (9:16) | SceneNormalizer |
| FPS | 30 | fps_rules |
| Video codec | H.264 (libx264) | FFmpeg flags |
| Audio codec | AAC 128k | FFmpeg flags |
| SAR | 1:1 | SceneNormalizer |
| Pixel format | yuv420p | B1 addition |
| Faststart | +faststart | B1 addition |
| Subtitles | Timed drawtext | B4/B5 |
| Audio sync | Per-scene concat | B3/B5 |
| Max duration | 180s (TikTok) | Validate in Composer |

- [ ] **Step 1: Write failing tests** — 4 cases:
  - `test_hook_overlay_first_3_seconds` — hook caption only in first 3s
  - `test_hook_overlay_uses_first_scene_headline` — text from scene 1
  - `test_production_validation_passes_valid_output` — all TikTok checks pass
  - `test_production_validation_flags_missing_faststart` — catches missing flag
- [ ] **Step 2: Implement** hook overlay + validation function
- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit as** `feat: add hook overlay and TikTok production validation`

---

### Task 6B: Edge cases + dead code cleanup + coverage

**Files:**
- Modify: `tests/test_composer.py` (edge case tests)
- Modify: `clipper_agency/agents/composer.py` (remove dead code)

**Edge cases:**
- Single-scene pipeline (no transitions needed)
- All hard_cut -> filter graph identical to pre-xfade concat path
- Mixed image/video/text input types with treatments
- Card fallback scene with treatment metadata
- Transition duration = 0 (instant, effectively hard_cut)
- Very short clip (1.5s) with minimum transition
- All 9 treatments listed in `treatments.yaml` appear somewhere in tests
- No script text -> no subtitles, no crash
- No audio files -> silent audio track
- Audio file missing for one scene -> pad with silence

**Cleanup:** `_build_filter()` (lines 383-410) is dead production code replaced by `_build_assembly_cmd()`. Remove it and update any tests that reference it directly.

- [ ] **Step 1: Write edge case tests**
- [ ] **Step 2: Remove `_build_filter()` and fix affected tests**
- [ ] **Step 3: Run full suite**
- [ ] **Step 4: Commit as** `test: add edge case tests, remove dead _build_filter`

---

### Task 6C: Slow-motion treatment support (Deferred)

**Not implemented in Tier 3.** `setpts=2.0*PTS` changes clip duration (2x source = output), which conflicts with the trim-based approach. The trim duration would need to double. This requires special handling in the filter graph. Document as known limitation.

---

## Batch 7 — Final Validation (Sequential, depends on B6)

### Task 7: Full test suite validation + coverage + integration check

- [ ] **Step 1:** Run `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
  - Expect: All 699+ existing pass + ~50 new tests pass
- [ ] **Step 2:** Check coverage >= 93%: `.venv/bin/python3 -m pytest --cov=clipper_agency --cov-report=term-missing`
- [ ] **Step 3:** Fix any coverage gaps in new modules (treatment_config, treatment_filters, audio_sequencer, subtitle_engine)
- [ ] **Step 4:** Verify new modules have >= 90% individual coverage
- [ ] **Step 5:** `git diff --stat master` — review all changes
- [ ] **Step 6:** Commit as `test: final coverage validation for Tier 3`

---

## Summary

| Batch | Tasks | Parallel? | Files | Pain Points | Est. commits |
|-------|-------|:---------:|-------|:-----------:|:---:|
| **B0** | TreatmentConfig + TreatmentFilterBuilder + template validation | **3 parallel** | 3 new, 1 existing | PP4 | 3 |
| **B1** | Treatment filter integration in Composer | Sequential | composer.py + tests | PP4, PP5 | 1 |
| **B2** | xfade transition engine | Sequential | composer.py + tests | PP4 | 1 |
| **B3** | Audio Sequencer module + integration | **2 parallel** | 1 new, composer.py + tests | PP1, PP3 | 2 |
| **B4** | SubtitleEngine + script passthrough | **2 parallel** | 1 new, orchestrator + composer + tests | PP2 | 2 |
| **B5** | Composer unified refactor | Sequential | composer.py + tests | All PP | 1 |
| **B6** | Hook overlay + edge cases + cleanup | **2 parallel** | subtitle_engine, composer.py, tests | Polish | 3 |
| **B7** | Final validation | Sequential | tests | Verification | 1 |

**Total: ~14 commits, 4 new modules, 6+ test files, 699+ tests passing**

### New Modules Created

| Module | Path | Responsibility |
|--------|------|----------------|
| `treatment_config.py` | `clipper_agency/rendering/` | YAML loader for treatment/transition definitions |
| `treatment_filters.py` | `clipper_agency/rendering/` | Per-scene FFmpeg filter string generation |
| `audio_sequencer.py` | `clipper_agency/rendering/` | Per-scene audio+video concat filter builder |
| `subtitle_engine.py` | `clipper_agency/rendering/` | Script text to timed CaptionOverlay conversion |

### Risk Items

- **slow_motion treatment:** Deferred — `setpts=2.0*PTS` conflicts with trim+duration contract
- **xfade + audio interaction:** When xfade is used, audio can't use `concat=v=1:a=1` because xfade merges video streams. Audio must have its own `concat=n=N:a=1` running in parallel. Task 3B handles both modes.
- **Image treatment double-processing:** SceneNormalizer already applies zoompan. Treatment filters for images are informational at assembly — the normalizer's zoompan provides the base.
- **Transition on very short clips (<=2s):** Clamped per research pitfall #7. Some transitions may be effectively hard_cut if clamped to near-zero.
- **FFmpeg filter graph complexity:** The unified chain (treatment + trim + xfade + audio + subtitles) creates complex filter graphs. Each stage uses labeled outputs to keep it composable. Test thoroughly.

### Execution Order for Parallel Batching

```
Phase 1: B0 (3 parallel tasks) ──────────────────────────── ~2 hours
Phase 2: B1 (sequential) ────────────────────────────────── ~1 hour
Phase 3: B2 (sequential) ────────────────────────────────── ~2 hours
Phase 4: B3 + B4 (4 parallel tasks) ─────────────────────── ~2 hours
Phase 5: B5 (sequential — wires everything) ─────────────── ~2 hours
Phase 6: B6 (2 parallel tasks) ──────────────────────────── ~2 hours
Phase 7: B7 (validation) ────────────────────────────────── ~1 hour
                                                          Total: ~12 hours
```

### Verification

After Batch 7 completes:
```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q  # 750+ pass
.venv/bin/python3 -m pytest --cov=clipper_agency --cov-report=term-missing  # >=93%
git diff --stat master  # review all changes
```

Then run a full pipeline job to verify the end-to-end output has:
1. No voice clashing (one narration at a time)
2. Timed subtitles matching the script
3. Per-scene narration synced to video
4. Treatment filters applied (ken burns, cinematic crop, etc.)
5. Smooth transitions between scenes (crossfade, hard cut)
6. Production-grade MP4 ready for TikTok upload
