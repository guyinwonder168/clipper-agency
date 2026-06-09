# Tier 4 Design: Timeline-Aware Agent Orchestration ✅ SUPERSEDED

**Date:** 2026-06-06  
**Status:** Superseded by audio-first continuous voiceover architecture (v2.0.0)  
**Replaced by:** `docs/adr/0021-audio-first-continuous-voiceover.md`  
**Related:** `docs/PRD.md`, `docs/SRS.md`, `docs/technical_design.md`, `docs/requirements_traceability.md`, `docs/adr/0020-use-canonical-timeline-contract.md`

---

## 1. Problem

The Phase 19 Composer now supports per-scene audio sequencing, subtitles, treatment filters, and xfade transitions, but the job 2 retest exposed a cross-agent contract gap:

- Scriptwriter estimated scene durations that were too short for the amount of narration text.
- Voice Producer generated correct narration, but actual audio durations were much longer than the script estimates.
- Visual Director planned visual scene durations from script estimates, not actual voice durations.
- Composer rendered from mismatched script, voice, and visual contracts.
- Retry-from-Composer did not pass script scenes through the retry path, so subtitles were missing.
- The hardcoded 60s validation was treated as platform policy instead of an MVP business target.

This is not a Composer-only issue. The pipeline needs one canonical timing contract that all downstream agents obey.

---

## 2. Goals

1. Keep the MVP output target at 45-55s and hard-limit at 60s unless configured otherwise.
2. Avoid expensive rewrite loops after TTS whenever possible.
3. Make Researcher recommend content direction from factual crawl/search data.
4. Make Scriptwriter obey a concrete format, story count, word budget, and duration budget.
5. Measure actual voice duration before visual planning.
6. Make Visual Director plan assets from the reconciled timeline, not duration guesses.
7. Make Composer obey the timeline, script text, voice files, visual assets, opening hook, and CTA roles.
8. Preserve manual retry/cache behavior without losing script/timeline data.

## 3. Non-Goals

- No new LLM Content Planner agent for MVP.
- No automatic unbounded Scriptwriter rewrite loop.
- No audio trimming that cuts narration mid-sentence.
- No TikTok Direct Post API integration in this tier.

---

## 4. Revised Pipeline

```text
Topic
  ↓
Safety
  ↓
Researcher
  - gather facts
  - rank candidate stories
  - produce content_direction
  ↓
Orchestrator Format Validator
  - validates content_direction against niche/platform config
  - derives word/time budgets
  ↓
Scriptwriter
  - obeys selected format and budgets
  - emits scene roles and estimated durations
  ↓
Script Duration Gate
  - deterministic word-count duration estimate
  - rejects before TTS if likely too long
  ↓
Voice Producer
  - generates one voice file per scene
  - measures actual audio duration per scene
  ↓
Timeline Reconciler
  - combines content_direction + script + actual audio durations
  - creates canonical timeline
  ↓
Visual Director
  - plans visuals/treatments/transitions from timeline
  ↓
Composer
  - renders timeline-obedient video with synced audio/subtitles
  ↓
Reviewer
  ↓
Output
```

---

## 5. Component Ownership

### 5.1 Researcher: Content Direction

Researcher already uses an LLM to synthesize crawled/search data. Tier 4 extends that synthesis to include a structured `content_direction`.

Example:

```json
{
  "content_direction": {
    "recommended_format": "three_story_roundup",
    "reason": "Three safe, recent, unrelated stories have similar viral potential.",
    "selected_story_count": 3,
    "selected_stories": ["story_1", "story_2", "story_3"],
    "content_angle": "fast gossip roundup",
    "risk_notes": ["Use cautious wording for unverified claims."]
  }
}
```

Researcher recommends the direction. Orchestrator enforces product and platform constraints.

### 5.2 Orchestrator Format Validator

The validator is deterministic and config-driven. It checks:

- `recommended_format` is allowed by niche config.
- `selected_story_count` does not exceed `max_stories_per_video`.
- target duration and hard limit are available.
- word budgets fit the selected format.

MVP defaults:

```yaml
content_planning:
  default_format: three_story_roundup
  max_stories_per_video: 3
  target_duration_sec: 55
  hard_limit_sec: 60
  estimated_words_per_second: 2.0
```

### 5.3 Scriptwriter: Budget Obedience

Scriptwriter must not decide story count freely. It receives the validated content direction and budget.

Scriptwriter output must include:

```json
{
  "scene": 1,
  "role": "opening_hook",
  "text": "...",
  "word_count": 10,
  "estimated_duration_sec": 5.0
}
```

Required roles for MVP roundup:

- `opening_hook`
- `story_1`
- `story_2`
- `story_3`
- `cta`

### 5.4 Script Duration Gate

Before TTS spend, the Orchestrator estimates duration locally:

```text
estimated_seconds = word_count / estimated_words_per_second + pause_buffer
```

If the script estimate exceeds the target budget, the job fails early with a clear reason or allows one bounded rewrite only if configured. No unbounded automatic loop.

### 5.5 Voice Producer: Audio Duration Metadata

Voice Producer remains responsible for audio generation only. It must also measure each generated file with `ffprobe` and return duration metadata:

```json
{
  "scene": 1,
  "audio_path": ".../scene_1.mp3",
  "audio_duration_sec": 8.7,
  "provider": "elevenlabs"
}
```

Voice Producer should not decide video format, scene roles, or platform timing policy.

### 5.6 Orchestrator Timeline Reconciler

Timeline Reconciler is an Orchestrator-owned service, not a new LLM agent.

It combines:

- Researcher `content_direction`
- Scriptwriter scene roles/text/estimated durations
- Voice Producer actual audio durations
- niche/platform duration config

Output:

```json
{
  "timeline": [
    {
      "scene": 1,
      "role": "opening_hook",
      "text": "...",
      "audio_path": ".../scene_1.mp3",
      "audio_duration_sec": 8.7,
      "start_sec": 0.0,
      "end_sec": 8.7,
      "target_duration_sec": 8.7,
      "visual_instruction": "opening card"
    }
  ],
  "total_duration_sec": 54.2,
  "target_duration_sec": 55,
  "hard_limit_sec": 60,
  "within_limit": true
}
```

If total actual audio exceeds the hard limit, the pipeline stops before Visual Director and Composer.

### 5.7 Visual Director: Timeline-Aware Planning

Visual Director must consume the reconciled timeline.

It must:

- create an opening card/visual for `opening_hook` scenes.
- create CTA card/visual for `cta` scenes.
- match visual asset duration to `target_duration_sec`.
- select treatment and transition based on role and content.
- preserve script/timeline references in `scene_plan.json`.

### 5.8 Composer: Timeline-Obedient Rendering

Composer must treat the reconciled timeline as the source of truth.

It must:

- use timeline scene order and duration.
- pair the correct audio file with the correct visual scene.
- generate subtitles from timeline text.
- obey opening hook and CTA roles.
- apply Visual Director treatments/transitions.
- fail if timeline, audio files, or visual assets are inconsistent.

---

## 6. Gates and Failure Behavior

| Gate | New/Changed Behavior |
|------|----------------------|
| G4/G5 | Researcher output must include usable content direction or fallback format decision. |
| G7 | Script must fit word/time budget before TTS. |
| G8 | Voice duration metadata is required for every scene. Actual total duration must be checked. |
| New timeline gate | Canonical timeline must be internally consistent and within hard duration limit. |
| G9 | Visual assets must match timeline scene count and minimum duration expectations. |
| G10 | Duration hard limit is configurable. MVP target remains <=60s, but this is product policy, not universal TikTok ToS. |

Manual retry remains the only retry policy. Retry paths must reconstruct and pass the same content direction, script scenes, voice metadata, and timeline artifacts to downstream agents.

---

## 7. Artifact Contract Additions

New or expanded artifacts under `ASSETS_CACHE/job_{id}`:

```text
agents/researcher/content_direction.json
agents/scriptwriter/script.json          # add role, word_count, estimated_duration_sec
agents/voice_producer/audio_metadata.json
timeline/reconciled_timeline.json
gates/script_duration.json
gates/timeline_validation.json
```

`metadata.json` in the final package should include `total_duration_sec`, selected format, selected story count, and timeline artifact path.

---

## 8. Testing Strategy

1. Unit tests for content direction validation.
2. Unit tests for word-budget duration estimation.
3. Unit tests for audio duration metadata parsing.
4. Unit tests for Timeline Reconciler start/end time calculations.
5. Orchestrator tests proving Visual Director receives timeline, not raw duration guesses.
6. Composer tests proving subtitles and per-scene audio follow timeline.
7. Retry tests proving `job-retry --from composer --use-cache` passes script/timeline artifacts.
8. Regression test for job 2 failure shape: 6 long audio scenes must fail before Visual Director if hard limit is exceeded.

---

## 9. Open Questions

1. Should MVP allow one bounded Scriptwriter rewrite when the local duration estimate exceeds budget?
2. Should hard limit default remain 60s for all niches, or be niche-specific?
3. Should `rapid_bulletin` remain available for 5-6 headline-only stories, or deferred until after Timeline Reconciler is stable?
