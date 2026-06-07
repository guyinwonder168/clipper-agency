# ADR 0021: Audio-First Continuous Voiceover Architecture

**Date:** 2026-06-07
**Status:** Accepted
**Phase:** Architecture Redesign (v2.0.0)

## Context

The current pipeline produces videos where audio and visuals are desynchronized. Root causes:

1. **Agents work in isolation** — Voice Producer and Visual Director run in parallel with no shared timeline, so visuals cannot align to audio they haven't heard yet.
2. **Per-scene TTS calls are expensive and disjoint** — 8 separate TTS calls per video create pacing gaps between scenes, concatenation artifacts, and inconsistent delivery tone.
3. **Visual Director guesses durations** — It plans scenes using estimated durations from the Scriptwriter's `max_words_per_scene` formula, which does not match real TTS timing.
4. **Scriptwriter produces fragments, not narration** — Per-scene headline fragments (3 words each) instead of continuous spoken-word voiceover text. Emojis in output break TTS engines.
5. **Researcher outputs research notes, not edit blueprints** — Downstream agents lack actionable visual instructions, asset candidates, and beat-level timing guidance.

The core insight: in an automated TTS pipeline, FFmpeg can adapt visuals (trim, speed-adjust) to match audio, but TTS cannot adapt audio to match visuals. Audio must come first.

## Decision

Adopt an **audio-first continuous voiceover** architecture with the following changes:

### 1. Audio-First Production Pipeline

Generate the complete voiceover FIRST, then fit visuals to the audio timeline. The voiceover (`voiceover.mp3`) becomes the immutable timeline anchor — it is never trimmed or sped up. All visuals are adjusted to match.

### 2. Continuous Voiceover (Single TTS Call)

Replace 8 per-scene TTS calls with **1 continuous TTS call** for the entire script. This produces a single `voiceover.mp3` with word-level timestamps via ElevenLabs `/with-timestamps` (character-level alignment grouped into words in code).

- **87.5% TTS cost reduction** (8 calls → 1 call).
- Natural speech pacing with no gaps or concatenation artifacts.
- Model: `eleven_multilingual_v2` (stable, production-ready, 10k char limit, SSML supported).

### 3. Beat-Driven Architecture

Introduce **story beats** as the primary data contract flowing through the pipeline. Each beat carries:

- `beat_id`, `role` (hook, main_claim, evidence, reaction, closing_cta)
- `visual_must_show` / `visual_must_not_show` rules
- `asset_candidates` with reasons
- `overlay_text` (short keyword caption, 3-6 words)
- `caption_keywords` for visual overlay
- `narration_goal`, `safe_wording`, `risk_note`

### 4. Segment Producer (Researcher Evolution)

Rename Researcher → **Segment Producer** with expanded responsibilities: Fact Checker, Viral Analyst, Clip Scout, Story Producer, and Edit Planner. Outputs an edit blueprint with story beats, format decision, verified facts, asset candidates, and a `do_not_use` list — structured instructions for every downstream agent.

### 5. Sequential Voice → Visual Pipeline

Remove parallel Voice Producer + Visual Director execution. Voice Producer must complete BEFORE Visual Director starts, because Visual Director needs exact audio durations from timestamps.

```
Topic → Safety → Segment Producer → Scriptwriter → Voice Producer → Visual Director → Composer → Reviewer → Package
```

### 6. Smart Scene Trimming

Composer detects scene boundaries in downloaded clips via ffprobe and trims at natural transition points rather than blindly cutting from the start. Speed adjustment up to ±20% (imperceptible) or slow-down up to 30%.

### 7. Keyword Captions

Replace full-sentence subtitles with short keyword captions (e.g., "RAMAI DIBAHAS", "AKHIRNYA KLARIFIKASI"). Positioned at bottom of frame, changed at each beat boundary, aligned to audio timeline.

## Alternatives Considered

### Visual-first (Workflow B)

Film/edit footage first, then write script to match, record voiceover last.

- **Pros:** Traditional production approach; human VO artists can watch video and adapt pace.
- **Cons:** Requires human voice actors who can adapt delivery to visuals. API-based TTS cannot watch video or adjust pace. Does not work for automated pipelines.

### Per-scene TTS (current approach)

Generate separate audio for each scene, then concatenate.

- **Pros:** Scene-level control, easier per-scene debugging, familiar per-scene mental model.
- **Cons:** 8× cost; pacing gaps between scenes; concatenation artifacts at boundaries; inconsistent delivery tone across calls; each call introduces latency.

### ElevenLabs v3 (Turbo v3 / Eleven v3)

Newer model with native audio tags (`[excited]`, `[whisper]`).

- **Pros:** Better emotional range, built-in natural language audio tags, potentially better timing.
- **Cons:** Alpha/preview status with unstable API; 5,000 char limit (vs 10,000 for v2); less stable voice consistency; limited language support for Indonesian.
- **Mitigation:** Plan as future upgrade path once API stabilizes.

### Parallel voice + visual generation

Generate audio and visuals simultaneously for faster pipeline.

- **Pros:** Faster wall-clock pipeline execution.
- **Cons:** Visuals cannot align to audio they haven't heard yet. Visual Director would need to guess durations, reintroducing the desynchronization problem this ADR solves.

## Rationale

- **Audio-first is the industry standard** for narration-driven content in agency production. Voiceover is recorded first, then visuals are cut to match.
- **TTS is fixed-rate** — it reads text at a consistent pace and cannot adapt to visuals. But FFmpeg CAN adapt visuals (trim, speed-adjust, loop). The flexible component must follow the rigid one.
- **Single TTS call eliminates inter-scene gaps** — no silence between concatenated audio files, no volume/tone mismatches.
- **Word-level timestamps enable precise alignment** — ElevenLabs `/with-timestamps` returns character-level timing that groups into accurate word boundaries.
- **Beat contract creates shared understanding** — every agent receives structured, actionable instructions instead of vague direction.
- **Cost reduction is immediate and significant** — 87.5% fewer TTS credits per video with no quality loss.

## Consequences

- **Positive:** 87.5% TTS cost reduction (8 calls → 1 call per video).
- **Positive:** Perfect audio-visual synchronization — visuals are always fitted to actual audio timeline, never the reverse.
- **Positive:** Natural speech pacing from continuous narration instead of disjointed per-scene fragments.
- **Positive:** Segment Producer provides structured edit blueprint for all downstream agents — eliminates vague direction.
- **Positive:** Word-level timestamps enable precise visual-audio alignment at the beat level.
- **Negative:** Sequential voice → visual execution adds ~30s to pipeline (Voice Producer must finish before Visual Director starts; no parallelism at that stage).
- **Negative:** Single `schema.py` dependency — all agents import from one module, requiring careful batch coordination during implementation.
- **Negative:** Voice actor cannot adapt to visual pacing — audio is fixed once generated. If audio is too long/short, FFmpeg `atempo` (±15%) is the only adjustment available.
- **Neutral:** Gemini TTS and Fish Audio fallback providers do not return timestamps — require FFmpeg `silencedetect` for approximate timing (less precise but functional).
- **Neutral:** ElevenLabs v3 upgrade path remains available as a future improvement once API stabilizes.
