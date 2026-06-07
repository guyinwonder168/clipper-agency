# Audio-First Continuous Voiceover Design

**Date:** 2026-06-07
**Status:** Approved
**Author:** OpenAgent + User + ChatGPT Review Integration

## Problem Statement

Pipeline produces videos where audio and visuals are desynchronized AND content quality is poor. Root causes:

1. **Researcher** acts as a news summarizer, not an edit planner — outputs research notes instead of edit blueprints
2. **Scriptwriter** produces per-scene headline fragments (3 words each) instead of voiceover narration
3. **Voice Producer** makes 8 separate TTS calls → robotic, disconnected audio, emojis break TTS
4. **Visual Director** plans in isolation — doesn't know audio timeline, receives vague direction
5. **Composer** concatenates independently — no shared reference between agents
6. **Reviewer** checks format only, not creative quality

### The Core Insight

The Researcher must evolve from "research assistant" into a **Segment Producer** that creates an edit blueprint. Currently it outputs:

> "This topic is trending and could be made into a short-form video."

It should output:

> "Scene 1 needs this visual, for this reason, at this duration, with this asset."

Once the Researcher produces actionable beat maps, every downstream agent benefits.

## Design Decision: Audio-First Continuous Voiceover + Edit Blueprint Architecture

### Agency Production Standard

Real agencies use **audio-first production** for narration-driven content:
1. Creative brief defines edit plan (angle, beats, visual intent)
2. Script written for voiceover (full sentences, no emojis, spoken-word style)
3. Voiceover recorded first → becomes timeline anchor
4. Visuals planned against audio timeline using the creative brief
5. Editor syncs visuals to audio

Our pipeline uses TTS (not human VO artists). TTS reads text at a fixed rate and cannot adapt to visuals. But FFmpeg CAN adapt visuals (trim, speed up, slow down). Therefore audio-first is the correct approach for automated TTS pipelines.

**Workflow B** (visual-first, VO last) exists for human VO artists who can watch the video and adjust pace. This does not apply to API-based TTS.

### Approach A vs B (ElevenLabs model)

| Aspect | Option A: Multilingual v2 | Option B: Eleven v3 |
|--------|--------------------------|---------------------|
| Stability | ✅ Stable, production-ready | ❌ Alpha/preview |
| Audio tags `[excited]` | ❌ Not supported | ✅ Supported |
| SSML `<break>` | ✅ Supported | ❌ Not supported |
| Char limit | 10,000 | 5,000 |
| Word timestamps | ✅ `/with-timestamps` | ✅ `/with-timestamps` |
| Voice stability | ✅ Consistent | ⚠️ Less stable |

**Decision: Option A** — keep Multilingual v2 + SSML for stability. V3 as future upgrade.

---

## Section 1: Researcher — Segment Producer with Edit Blueprint

*Combines our design (creative direction + asset awareness) with ChatGPT's insight (story beats, visual instructions, edit blueprint).*

### Current Behavior (too weak)

Researcher gathers ScrapeCreators + Firecrawl data, produces a research brief with content suggestions. No visual planning, no asset evaluation, no edit decisions.

### New Behavior: 5 Roles in One Agent

The Researcher must act as:

1. **Fact Checker** — Verify facts, label verified vs unverified vs rumor
2. **Viral Analyst** — Identify WHY the story is clickable (shock, conflict, curiosity gap)
3. **Clip Scout** — Find video clips, images, screenshots, not just articles
4. **Story Producer** — Decide the exact angle and emotional driver
5. **Edit Planner** — Output per-beat visual + narration instructions

### New Output Contract

```json
{
  "topic_brief": "Short verified summary of the topic",

  "angle": {
    "main_angle": "Why this story matters now",
    "viewer_hook": "What makes people stop scrolling",
    "emotional_driver": "shock | curiosity | sympathy | conflict | surprise | scandal | comeback",
    "risk_level": "low | medium | high"
  },

  "format_decision": {
    "format": "single_story_deep_dive | three_story_roundup | two_story_highlight",
    "story_count": 1,
    "rationale": "Only 1 video clip available out of 3 stories; deep dive is more engaging",
    "video_asset_ratio": 0.33
  },

  "verified_facts": [
    {
      "fact": "Ruben Onsu posted a clarification video on Instagram",
      "source_url": "https://...",
      "confidence": "verified | likely | unconfirmed",
      "safe_wording": "Ruben Onsu diduga memposting video klarifikasi"
    }
  ],

  "unverified_claims": [
    {
      "claim": "They are officially separated",
      "label": "rumor",
      "safe_wording": "Ramai disebut telah berpisah, namun belum ada konfirmasi resmi"
    }
  ],

  "reference_style": {
    "format": "fast infotainment explainer",
    "target_duration_sec": 35,
    "hook_duration_sec": 2.5,
    "avg_scene_duration_sec": 3,
    "caption_style": "large keyword captions, bottom-center (standard reading position)",
    "transition_style": "hard cuts with occasional punch zoom",
    "visual_priority": [
      "direct source clip",
      "official screenshot",
      "subject photo with Ken Burns",
      "text card with headline",
      "stock fallback (abstract topics only)"
    ]
  },

  "story_beats": [
    {
      "beat_id": 1,
      "role": "hook",
      "narration_goal": "Make viewer curious immediately",
      "spoken_point": "Ruben Onsu finally speaks up about the controversy",
      "safe_wording": "Lagi ramai dibahas nih soal...",
      "visual_must_show": "Ruben Onsu face or the viral clip moment",
      "visual_must_not_show": "random people, unrelated city, generic stock",
      "overlay_text": "RAMAI DIBAHAS",
      "caption_keywords": ["RUBEN", "KLARIFIKASI"],
      "asset_candidates": [
        {
          "type": "tiktok_clip",
          "url": "https://...",
          "reason": "Shows Ruben speaking directly to camera"
        }
      ],
      "fallback": {
        "type": "text_card",
        "headline": "RUBON BICARA",
        "image_search": "Ruben Onsu portrait close up"
      },
      "evidence_source": "https://...",
      "risk_note": "Use 'diduga' or 'ramai disebut', not definitive accusation"
    }
  ],

  "do_not_use": [
    "generic Pexels city footage for named-person stories",
    "unrelated luxury/car/money visuals",
    "wrong artist photo",
    "visuals implying guilt without verified source",
    "slow empty b-roll for hook scenes"
  ],

  "video_sources": [
    {"url": "...", "desc": "Ruben Onsu clarification video", "type": "tiktok_clip"}
  ],

  "context_sources": [
    {"title": "Article about the drama", "description": "..."}
  ]
}
```

### Format Decision Matrix

| Stories found | Video clips | Decision | Format |
|:---:|:---:|---|---|
| 3 | 3+ | Multi-story roundup | `three_story_roundup` |
| 3 | 2 | 2-story with best clips | `two_story_highlight` |
| 3 | 1 | Deep dive on the 1 with video | `single_story_deep_dive` |
| 3 | 0 | All-stock or abort | `text_only` or skip |
| 1 | 1 | Single story deep dive | `single_story_deep_dive` |

### Visual Hierarchy Rules

For celebrity/news/gossip content, fallback priority:
1. **Exact TikTok/source clip** (real footage of the subject)
2. **Official social media screenshot** (Instagram post, tweet)
3. **Subject portrait** with Ken Burns motion
4. **Text card** with relevant headline
5. **Generic stock** — ONLY for abstract topics, NEVER for named-person stories

### Caption Style Rules

Use short keyword captions, NOT full sentence subtitles:
- ✅ Good: "RAMAI DIBAHAS", "AKHIRNYA KLARIFIKASI", "NETIZEN CURIGA"
- ❌ Bad: Long sentences covering half the screen

### Scene Duration Guide

| Beat type | Target duration |
|-----------|:---:|
| Hook card | 2-3s |
| Main claim | 3-4s |
| Evidence/reveal | 3-5s |
| Reaction/comment | 2-3s |
| CTA/end | 2-3s |
| **Total target** | **30-45s** |

### Code Changes

- `researcher.py`: Restructure output to new contract with story_beats
- `researcher.py`: Add format decision logic based on video/story ratio
- `researcher.py`: Add asset evaluation (clip count vs story count)
- `prompts/researcher.md`: Rewrite as Segment Producer with edit blueprint instructions
- `config/schema.py`: Add `StoryBeat` and `FormatDecision` models

---

## Section 2: Scriptwriter — Voiceover Writer

### Current Output (per-scene fragments)

```json
{
  "script": [
    {"scene": 1, "role": "opening_hook", "text": "Gosip terbaru! 🔥", "word_count": 3}
  ],
  "caption": "...",
  "hashtags": [...]
}
```

### New Output (continuous voiceover from story beats)

```json
{
  "hook_text_onscreen": "RAMAI DIBAHAS",
  "voiceover_text": "Lagi ramai dibahas nih... Ruben Onsu akhirnya bicara soal kontroversi ini... (75-110 words continuous narration, no emojis, spoken-word style)",
  "narrative_structure": [
    {"beat_id": 1, "section": "hook", "description": "Tease the story",
     "word_range": [0, 12],
     "overlay_text": "RAMAI DIBAHAS",
     "caption_keywords": ["RUBEN", "KLARIFIKASI"]},
    {"beat_id": 2, "section": "story_1", "description": "The controversy",
     "word_range": [13, 40],
     "overlay_text": "AKHIRNYA BICARA",
     "caption_keywords": ["KONTROVERSI", "VIRAL"]},
    {"beat_id": 3, "section": "story_1_reveal", "description": "The plot twist",
     "word_range": [41, 65],
     "overlay_text": "TERNYATA BEGINI",
     "caption_keywords": ["FAKTA", "TERUNGKAP"]},
    {"beat_id": 4, "section": "closing_cta", "description": "Call to action",
     "word_range": [66, 85],
     "overlay_text": "FOLLOW untuk update",
     "caption_keywords": ["FOLLOW", "UPDATE"]}
  ],
  "caption": "...",
  "hashtags": ["#gosip", ...],
  "estimated_duration_sec": 35
}
```

### Key Changes

- `voiceover_text` = single continuous narration, 75-110 words, no emojis, spoken-word style
- `narrative_structure` = scene markers mapped to story beats with word ranges
- `hook_text_onscreen` = text overlay for first 2-3 seconds
- `overlay_text` per beat = short keyword caption (3-6 words), NOT full subtitles
- `caption_keywords` per beat = visual overlay keywords
- `max_words_per_scene` formula REMOVED — replaced by total word budget
- Script duration target: **30-45 seconds, 75-110 words**
- `beat_id` links back to Researcher's story_beats for visual instructions

### Prompt Changes

- Remove per-scene word limit formula
- Add instruction: "Write for voiceover — text will be SPOKEN by TTS"
- Add instruction: "No emojis, full sentences, spoken-word style"
- Add instruction: "Sound like telling a friend, not reading headlines"
- Add instruction: "Use safe wording from Researcher's verified_facts and unverified_claims"
- Add instruction: "Map each section to a story beat from the Researcher's edit blueprint"
- Add self-review quality check: score 1-10, rewrite if < 7

### Code Changes

- `scriptwriter.py`: Remove `max_words_per_scene` formula
- `scriptwriter.py`: Update `_parse_script_response()` to parse new format
- `scriptwriter.py`: Map narrative_structure to Researcher's beat_ids
- `prompts/scriptwriter.md`: Rewrite for voiceover-first approach

---

## Section 3: Voice Producer — Single Audio Mode

### Current Flow

Voice Producer loops through 8 scenes → 8 separate TTS calls → 8 MP3 files.

### New Flow

Voice Producer gets `voiceover_text` → 1 TTS call → 1 `voiceover.mp3` + word-level timestamps.

### Verified API Contracts

**ElevenLabs `/with-timestamps`** (primary):
- Endpoint: `POST /v1/text-to-speech/{voice_id}/with-timestamps`
- Model: `eleven_multilingual_v2`
- Returns: JSON with `audio_base64` + character-level alignment
  - `characters[]` — individual characters
  - `character_start_times_seconds[]` — start time per character
  - `character_end_times_seconds[]` — end time per character
- Character-level → must group into words in code
- 10,000 char limit
- SSML `<break time="1.5s"/>` supported for pauses

**Gemini TTS** (fallback):
- Model: `gemini-3.1-flash-tts-preview`
- Returns: raw PCM only (s16le, 24000Hz, mono)
- **NO timestamps** — must use silence detection for approximate timing
- 32k token context, Indonesian supported
- Must convert PCM → WAV → MP3 via FFmpeg

**Fish Audio** (last resort):
- Unknown timestamp support, treat same as Gemini TTS

### Voice Settings (ElevenLabs, configurable via .env)

```python
"voice_settings": {
    "stability": 0.4,            # lower = more expressive
    "similarity_boost": 0.75,    # close adherence to voice
    "style": 0.7,                # style exaggeration for engaging delivery
    "use_speaker_boost": True,   # clearer voice
}
```

### Output Contract

```json
{
  "status": "completed",
  "voiceover_path": "voices/voiceover.mp3",
  "voiceover_duration_sec": 34.5,
  "timestamps": [
    {"word": "Halo", "start": 0.12, "end": 0.45},
    {"word": "semuanya", "start": 0.46, "end": 0.98}
  ],
  "provider": "elevenlabs"
}
```

### Timestamp Conversion (ElevenLabs)

Character-level → word-level grouping:

```python
def chars_to_words(characters, starts, ends):
    words = []
    current_word = ""
    word_start = None
    for char, start, end in zip(characters, starts, ends):
        if char == " ":
            if current_word:
                words.append({"word": current_word, "start": word_start, "end": start})
            current_word = ""
            word_start = None
        else:
            if not current_word:
                word_start = start
            current_word += char
    if current_word:
        words.append({"word": current_word, "start": word_start, "end": ends[-1]})
    return words
```

### Approximate Timestamps (Gemini TTS / Fish Audio)

When no timestamps available from provider:
1. Generate single `voiceover.mp3`
2. Use FFmpeg `silencedetect` to find natural pauses
3. Map sentence boundaries to pause positions

### Cost Impact

8 TTS calls → 1 TTS call = **87.5% fewer TTS API credits** per video.

### Code Changes

- `voice_producer.py`: New method `_generate_continuous_voiceover()`
- `voice_producer.py`: New method `_extract_word_timestamps()` for ElevenLabs
- `voice_producer.py`: New method `_approximate_timestamps()` for Gemini/Fish fallback
- `elevenlabs.py`: New method `generate_voice_with_timestamps()` using `/with-timestamps`
- `elevenlabs.py`: Add `style` and `use_speaker_boost` to voice_settings

---

## Section 4: Visual Director — Audio-Aware Beat-Driven Planning

### Current Problem

Visual Director plans in isolation — doesn't know audio timeline, receives vague direction, picks generic visuals.

### New Flow

Visual Director receives:
1. **Story beats** from Researcher (visual instructions per beat)
2. **Timestamps** from Voice Producer (exact audio durations)
3. **Asset candidates** from Researcher (where to find clips)

### Input Contract

```python
visual_director.execute(
    story_beats=[
        {
            "beat_id": 1,
            "role": "hook",
            "visual_must_show": "Ruben Onsu face or viral clip",
            "visual_must_not_show": "random people, unrelated city",
            "asset_candidates": [{"type": "tiktok_clip", "url": "..."}],
            "fallback": {"type": "text_card", "headline": "RUBON BICARA"},
            "target_duration_sec": 4.2,  # from timestamps
        }
    ],
    timestamps=[...],     # from Voice Producer
    voiceover_text="...", # from Scriptwriter
    do_not_use=[...],     # from Researcher
)
```

### Visual Selection Rules

For each beat, Visual Director must answer:
> "Why am I showing this while the viewer hears this sentence?"

If no clear answer exists → reject the visual, use fallback.

**Per-beat visual hierarchy (from Researcher's reference_style):**
1. Direct source clip (TikTok/Instagram of the subject)
2. Official screenshot (social media post, article)
3. Subject portrait with Ken Burns motion
4. Text card with headline + relevant image
5. Generic stock — ONLY if Researcher marked beat as abstract

### LLM Planning Enhancement

The Visual Director LLM now receives:
- Exact duration per beat (from audio timestamps, not estimates)
- `visual_must_show` / `visual_must_not_show` rules per beat
- `asset_candidates` with reasons
- `do_not_use` list
- Total audio duration (hard constraint)

### Code Changes

- `visual_director.py`: Accept `story_beats` + `timestamps` + `do_not_use`
- `visual_director.py`: Validate visuals against `visual_must_show` rules
- `visual_director.py`: Use `asset_candidates` from Researcher before searching Pexels
- `prompts/visual_director.md`: Add beat-driven planning with visual rules

---

## Section 5: Composer — Single Audio Timeline with Smart Scene Trimming

### Current Flow

Composer receives per-scene audio files + visual assets → concatenates scene-by-scene.

### New Flow

Composer receives `voiceover.mp3` + `timestamps` + visual assets + `overlay_text` per beat → syncs visuals to audio timeline + overlays short keyword captions.

### Smart Scene Trimming

Instead of blindly trimming clips from the start, Composer detects scene boundaries and cuts at natural points:

**Trimming flow per visual clip:**

1. Target duration from audio timeline (exact, from word timestamps)
2. Probe clip duration with ffprobe
3. Run ffprobe scene detection → find scene boundaries
4. Find nearest boundary to target duration
5. Trim at boundary + speed-adjust to exact target

**Decision tree:**

```
If scene boundary found within ±15% of target:
  → Trim at boundary + speed-adjust to exact target

If NO good boundary found:
  → Fall back to simple trim from start + speed-adjust

If clip shorter than target:
  → Slow down (max 30%) or loop
```

**Speed change limits:**
- Speed up max 20% (imperceptible)
- Slow down max 30% (acceptable for b-roll)
- Beyond limits → use alternative approach

### Caption Overlay

Use short keyword captions from `overlay_text`, NOT full sentence subtitles:
- Position: bottom of frame (standard reading position users expect)
- Style: large, bold, white text with dark shadow/outline
- Duration: aligned to beat audio timeline
- Change: new keyword at each beat boundary
- Note: if downloaded clip has bottom captions/watermarks, position our caption just above them (~20% from bottom)

### Downloaded Clip Watermark/Caption Handling

Downloaded TikTok clips may contain:
- Original watermarks (top corners, bouncing)
- Karaoke-style running captions (center)
- Original hardcoded subtitles (bottom)

**Strategy for MVP:** Leave them. Our voiceover replaces original audio. Original visual elements show authenticity. Our caption overlays go at the **bottom** of frame (standard reading position). If downloaded clip already has bottom text, shift our caption slightly higher to avoid overlap.

### Audio Timeline as Anchor

```
voiceover.mp3 = timeline anchor (always full duration, never trimmed)
visuals = laid over audio, trimmed/fitted to match
captions = keyword overlays per beat, aligned to audio timeline
transitions = hard cuts (primary) + crossfade (occasional)
```

### Code Changes

- `composer.py`: New method `_smart_trim()` with scene detection
- `composer.py`: New method `_detect_scene_boundaries()` using ffprobe
- `composer.py`: Refactor `_compose()` to use single audio timeline
- `composer.py`: Add keyword caption overlay from `overlay_text` per beat
- `composer.py`: Remove per-scene audio concatenation logic
- `subtitle_engine.py`: Update for short keyword captions instead of full subtitles

---

## Section 6: Orchestrator Pipeline Reordering

### Current Pipeline Order

```
Topic → Safety → Researcher → Scriptwriter → [Voice Producer || Visual Director] → Composer → Reviewer → Package
```

### New Pipeline Order

```
Topic → Safety → Researcher → Scriptwriter → Voice Producer → Visual Director → Composer → Reviewer → Package
```

Voice Producer must finish BEFORE Visual Director starts (Visual Director needs audio timestamps for exact durations).

### Orchestrator Data Flow

```python
# Researcher → full edit blueprint
research_output = run_researcher(topic, ...)
# Contains: story_beats, format_decision, asset_candidates, do_not_use

# Scriptwriter → continuous voiceover from beats
script_output = run_scriptwriter(
    story_beats=research_output["story_beats"],
    verified_facts=research_output["verified_facts"],
    ...
)
# Contains: voiceover_text, narrative_structure, caption_keywords

# Voice Producer → single audio + timestamps
voice_output = run_voice_producer(
    voiceover_text=script_output["voiceover_text"],
)
# Contains: voiceover.mp3, timestamps, duration

# Visual Director → beat-driven visuals with exact durations
visual_output = run_visual_director(
    story_beats=research_output["story_beats"],
    timestamps=voice_output["timestamps"],
    do_not_use=research_output["do_not_use"],
    asset_candidates=research_output["asset_candidates"],
)
# Contains: visual assets mapped to audio timeline

# Composer → single audio timeline with smart trimming
composer_output = run_composer(
    voiceover_path=voice_output["voiceover_path"],
    timestamps=voice_output["timestamps"],
    assets=visual_output["assets"],
    narrative_structure=script_output["narrative_structure"],
)
# Contains: video.mp4

# Reviewer → quality validation
review_output = run_reviewer(
    story_beats=research_output["story_beats"],
    video_path=composer_output["video_path"],
    voiceover_duration=voice_output["voiceover_duration_sec"],
)
# Contains: pass/fail with quality checks
```

### Code Changes

- `engine.py`: Remove parallel Voice + Visual execution
- `engine.py`: Add sequential Voice → Visual dependency
- `engine.py`: Pass story_beats through pipeline
- `engine.py`: Pass timestamps from Voice to Visual to Composer
- `engine.py`: Remove `story_direction["max_scenes"] = sc * 2 + 2` formula
- `engine.py`: Update all `_run_*` method signatures for new data flow

---

## Section 7: Reviewer — Quality Gate Enhancement

### Current Behavior

Reviewer checks format only (video exists, caption exists, thumbnail exists).

### New Quality Checks

```json
{
  "sync_validation": {
    "audio_duration_sec": 34.5,
    "visual_duration_sec": 34.8,
    "drift_sec": 0.3,
    "pass": true,
    "rule": "drift < 0.5s"
  },
  "visual_relevance": {
    "checks": [
      "No generic stock for named-person beats",
      "Every beat has a visual that matches narration",
      "No visual_must_not_show violations"
    ],
    "pass": true
  },
  "caption_quality": {
    "checks": [
      "Captions are short keywords (not full sentences)",
      "Captions change at beat boundaries",
      "No caption longer than 6 words"
    ],
    "pass": true
  },
  "fact_safety": {
    "checks": [
      "Unverified claims use safe wording",
      "No definitive accusations without sources",
      "Risk notes respected"
    ],
    "pass": true
  }
}
```

### Code Changes

- `reviewer.py`: Add sync validation (audio vs visual duration)
- `reviewer.py`: Add visual relevance check (generic stock usage)
- `reviewer.py`: Add caption quality check (keyword style, not full sentences)
- `reviewer.py`: Add fact safety check (safe wording for unverified claims)

---

## Summary of All Changes

### Files Modified

| File | Changes |
|------|---------|
| `prompts/researcher.md` | Rewrite as Segment Producer with edit blueprint |
| `clipper_agency/agents/researcher.py` | New output contract, format decision, story beats, asset evaluation |
| `prompts/scriptwriter.md` | Rewrite for voiceover-first from story beats |
| `clipper_agency/agents/scriptwriter.py` | New output format, remove per-scene formula, beat mapping |
| `clipper_agency/agents/voice_producer.py` | Single audio mode, timestamp extraction |
| `clipper_agency/agents/visual_director.py` | Beat-driven planning, visual rules, audio-aware durations |
| `clipper_agency/agents/composer.py` | Smart scene trimming, single audio timeline, keyword captions |
| `clipper_agency/agents/reviewer.py` | Quality gates: sync, visual relevance, caption, fact safety |
| `clipper_agency/orchestrator/engine.py` | Pipeline reordering, story_beats data flow |
| `clipper_agency/services/elevenlabs.py` | `/with-timestamps` endpoint, voice settings |
| `clipper_agency/config/schema.py` | StoryBeat, FormatDecision models, voice settings |
| `clipper_agency/rendering/subtitle_engine.py` | Keyword captions instead of full subtitles |

### Data Flow (Before → After)

```
BEFORE:
  Researcher → research_brief + source_urls
  Scriptwriter → per-scene text fragments (3 words each)
  Voice Producer → 8 separate MP3 files
  Visual Director → plans with guessed durations, vague direction
  Composer → concatenates independently, full sentence subtitles
  Reviewer → checks format only

AFTER:
  Researcher → story_beats + format_decision + asset_candidates + do_not_use
  Scriptwriter → voiceover_text + narrative_structure + caption_keywords
  Voice Producer → 1 voiceover.mp3 + word timestamps
  Visual Director → beat-driven visuals with exact durations + visual rules
  Composer → smart-trims visuals to audio timeline + keyword captions
  Reviewer → sync + visual relevance + caption quality + fact safety
```

### Edge Cases

| Edge Case | Mitigation |
|-----------|-----------|
| TTS audio too long/short | FFmpeg atempo ±15% speed adjustment |
| Single point of TTS failure | Already our reality — first scene failure stops pipeline |
| Word timestamp inaccuracy | ElevenLabs character-level grouping is proven accurate |
| Clip longer than beat duration | Smart scene trimming at boundaries |
| Clip shorter than beat duration | Slow down max 30% or loop |
| Downloaded clip has watermarks/captions | Leave them (authenticity), our captions go at top |
| Researcher finds no video clips | Format = `text_only` or skip job |
| Researcher finds fewer clips than stories | Deep dive format instead of roundup |
| Generic stock used for named-person story | Visual Director rejects per `do_not_use` rules |
| Unverified claim stated as fact | Reviewer catches, Scriptwriter uses `safe_wording` |

### Cost Impact

| Component | Before | After | Change |
|-----------|--------|-------|--------|
| TTS API calls | 8 per video | 1 per video | **-87.5%** |
| LLM calls | Same | Same | No change |
| Total cost per video | Baseline | Lower | **Significant savings** |

---

## Implementation Phases

### Phase A: Segment Producer Upgrade (Researcher → Segment Producer)

**Foundation of the entire new architecture.** Every downstream agent depends on its output.

This phase INCLUDES the rename from Phase 0 — no separate rename phase needed.

**Code changes:**
- Rename `researcher.py` → `segment_producer.py` (class name, imports, tests, prompts, docs)
- Rewrite prompt as Segment Producer with edit blueprint instructions
- New output contract: story_beats, format_decision, asset_candidates, do_not_use
- Format decision logic based on video/story ratio
- Visual instructions per beat (visual_must_show, visual_must_not_show)
- Verified facts with safe wording, unverified claims labeled
- Add `StoryBeat` and `FormatDecision` models to `config/schema.py`
- All existing tests pass (renamed), new tests for new contract

**Documentation updates (part of this phase):**
- Create ADR: `docs/adr/0021-audio-first-continuous-voiceover.md` (context, decision, alternatives, consequences)
- Update `docs/PRD.md`: PR-02 pipeline flow (researcher → segment_producer), PR-29 update
- Update `docs/SRS.md`: FR-03 researcher → segment_producer, env var rename
- Update `docs/technical_design.md`: §3 pipeline flow, §4 agent roles table, researcher output schema
- Update `docs/requirements_traceability.md`: new fact register entries for rename + beat contract
- Update `README.md`: pipeline diagram, project structure (researcher → segment_producer)
- Update `AGENTS.md`: repository state, relevant files list

**Release:**
- Version bump: `v1.4.0`
- Git tag: `v1.4.0`
- GitHub Release with changelog

### Phase B: Scriptwriter + Voice Producer (Audio-First Pipeline)

Unblocks usable audio output. Scriptwriter consumes Segment Producer's story_beats.

**Code changes:**
- Rewrite scriptwriter prompt for voiceover-first from story beats
- Remove `max_words_per_scene` formula, use total word budget (75-110 words)
- New output format: voiceover_text + narrative_structure + caption_keywords
- Refactor voice producer to single-audio mode (1 TTS call instead of 8)
- Add ElevenLabs `/with-timestamps` endpoint + word-level timestamp extraction
- Gemini TTS fallback with silence-detection approximate timestamps
- Voice settings: stability=0.4, similarity_boost=0.75, style=0.7, use_speaker_boost=True

**Documentation updates (part of this phase):**
- Update ADR 0021 with scriptwriter + voice producer decision details
- Update `docs/PRD.md`: cost model (87.5% fewer TTS calls), voice section
- Update `docs/SRS.md`: FR-05 (continuous voiceover), FR-06 (single TTS call), new voice settings
- Update `docs/technical_design.md`: §4 agent roles (scriptwriter, voice producer), §7 content planning
- Update `docs/requirements_traceability.md`: new facts for voiceover contract, timestamp extraction

**Release:**
- Version bump: `v1.5.0`
- Git tag: `v1.5.0`
- GitHub Release with changelog

### Phase C: Visual Director + Composer (Audio-Visual Sync)

Makes videos look and feel professional. Both agents now consume story_beats + timestamps.

**Code changes:**
- Visual Director beat-driven planning with audio timestamps
- Visual selection rules (must_show / must_not_use / do_not_use)
- Asset candidate priority over generic stock search
- Orchestrator pipeline reordering: Voice → Visual sequential (not parallel)
- Composer smart scene trimming (FFmpeg scene detection + boundary cuts)
- Single audio timeline (voiceover.mp3 as anchor)
- Keyword caption overlays at bottom of frame
- Remove per-scene audio concatenation logic

**Documentation updates (part of this phase):**
- Update ADR 0021 with visual director + composer + pipeline reordering decisions
- Update `docs/PRD.md`: PR-02 pipeline order change, caption position
- Update `docs/SRS.md`: FR-07 (beat-driven visual), FR-08 (single audio timeline, smart trimming)
- Update `docs/technical_design.md`: §3 pipeline order, §4 visual director, §4 composer, §6 orchestrator
- Update `docs/requirements_traceability.md`: new edge cases for smart trimming, timeline sync
- Update `README.md`: pipeline diagram (sequential voice → visual)

**Release:**
- Version bump: `v1.6.0`
- Git tag: `v1.6.0`
- GitHub Release with changelog

### Phase D: Quality Gates (Reviewer Enhancement)

Safety net to prevent bad videos from publishing.

**Code changes:**
- Sync validation per beat (audio vs visual duration drift)
- Visual relevance checks (no generic stock for named-person stories)
- Caption quality checks (keyword style, not full sentences)
- Fact safety checks (safe wording for unverified claims)

**Documentation updates (part of this phase):**
- Update ADR 0021 with reviewer quality gate decisions
- Update `docs/PRD.md`: PR-02 reviewer quality checks
- Update `docs/SRS.md`: FR-09 enhanced reviewer, new quality check FRs
- Update `docs/technical_design.md`: §4 reviewer role, quality check schemas
- Update `docs/requirements_traceability.md`: new quality gate edge cases
- Update `README.md`: final status update, test count

**Release:**
- Version bump: `v2.0.0` (major version — architecture redesign complete)
- Git tag: `v2.0.0`
- GitHub Release with comprehensive changelog

### Phase Execution Rules

Each phase follows the same workflow:

1. **Create branch** from master: `phase/{letter}-{description}`
2. **Implement** code + tests (TDD)
3. **Update docs** (ADR + PRD + SRS + technical_design + traceability + README)
4. **Run full offline test suite**: `.venv/bin/python3 -m pytest -m "not external and not integration" -q`
5. **Push branch** → open PR → wait for SonarCloud
6. **Merge** (`--merge`, no squash) → delete branch
7. **Tag release** with version bump + GitHub Release
8. **Pull master** → start next phase

Each phase is independently testable and deployable. Phase A is the foundation. Phase B unblocks audio. Phase C adds polish. Phase D adds safety. Phase D marks v2.0.0 — architecture redesign complete.
