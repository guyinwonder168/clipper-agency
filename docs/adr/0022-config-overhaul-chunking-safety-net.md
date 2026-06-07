# ADR 0022: Config Overhaul + TTS Chunking Safety Net + Hook Dedup

**Date:** 2026-06-07
**Status:** Accepted
**Supersedes:** ADR 0007 (Per-Agent Model Config)

## Context

ADR 0021 introduced the audio-first architecture. During implementation and testing, three systemic issues emerged:

1. **Dead config hierarchy** — `ConfigHierarchy` in `hierarchy.py` defined per-agent model/temperature/max_tokens but no file imported it. Agents hardcoded values directly in LLM calls, causing `max_tokens` truncation (segment_producer 1024 → `story_beats=[]` → 67-word script → 27s video instead of 60s).

2. **No TTS overflow protection** — When script text exceeds a TTS provider's character budget, the call fails silently or truncates. No fallback mechanism existed.

3. **Duplicate hook text** — CardGenerator baked hook text into a PNG card AND keyword captions drew the same text as drawtext overlay, causing visual duplication during the first 3 seconds.

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

### Hook Card Dedup (#11)

Pass `hook_duration` to `build_keyword_captions()` — skip any caption that starts before `hook_duration`. The hook card already displays the text visually.

## Alternatives Considered

### Keep hardcoded max_tokens
- **Pros:** No new code, simple.
- **Cons:** Already caused truncation bug. Values are guesses. Models have different limits.

### Always chunk TTS
- **Pros:** No overflow ever.
- **Cons:** Unnecessary complexity + latency for MVP. TikTok ≤60s ≈ 150 words ≈ 1,000 chars — well under all limits.

### Suppress hook text in CardGenerator instead
- **Pros:** Fewer changes.
- **Cons:** Hook card is the correct visual for the opening. Better to suppress the duplicate caption overlay.

## Consequences

- **Positive:** Single source of truth for agent config — one change in hierarchy.py propagates everywhere.
- **Positive:** Auto-determined max_completion_tokens from OpenRouter — no more truncation from hardcoded guesses.
- **Positive:** `reasoning_effort: "none"` prevents invisible thinking tokens.
- **Positive:** TTS chunking safety net prevents silent failures on long scripts.
- **Positive:** No more duplicate text during hook window.
- **Negative:** OpenRouter API dependency for model metadata (mitigated: cached locally, 7-day TTL, graceful fallback to None).
- **Neutral:** Model cache adds ~1s to first pipeline run (subsequent runs use cache).
