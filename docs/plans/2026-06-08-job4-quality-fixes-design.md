# Job #4 Quality Fixes Design

## Goal

Fix the Job #4 failure pattern where a valid Segment Producer asset was not used, the final video became shorter than the voiceover, and the Reviewer passed the output despite visible quality issues.

## Background

Job #4 exposed several audio-first pipeline weaknesses:

- Segment Producer provided relevant Ruben/Sarwendah and Sarwendah apology assets.
- Visual Director scene planning ended with a broken action: `{"type": "tiktok_clip"}` with no `source_url`.
- Current `_deduplicate_llm_plan_urls()` removes duplicate URLs but does not replace them.
- Composer rendered a final video shorter than the voiceover, truncating the last words.
- Reviewer passed the output despite hard metadata evidence that video duration was shorter than audio duration.

The design keeps the core audio-first architecture: Scriptwriter creates the story, Voice Producer creates the real audio timeline, downstream visuals follow the actual audio duration.

## Duration Semantics

Current config already has:

```yaml
content_planning:
  target_duration_sec: 55
  hard_limit_sec: 60
```

Clarified meaning:

- `target_duration_sec`: soft Scriptwriter guidance only.
- `hard_limit_sec`: hard final output safety cap.
- `voiceover_duration_sec`: runtime source of truth for downstream Visual Director, Composer, and Reviewer.

The final video does not need to equal `target_duration_sec`. It must cover `voiceover_duration_sec` and remain under `hard_limit_sec`.

Optional later cleanup: alias or rename to `target_script_duration_sec` and `max_final_duration_sec` while keeping backward compatibility.

## Visual Asset Portfolio and Resolver

Segment Producer should provide a richer ranked asset portfolio per story beat. Important beats should target:

- at least 2 video candidates,
- at least 1 screenshot/image candidate,
- 1 explicit text-card fallback.

Candidate ranking should consider subject match, spoken-point match, recency, engagement, source reliability, safety risk, and duplicate status.

For ScrapeCreators TikTok keyword search results, Segment Producer should preserve the canonical TikTok URL and prefer direct media download fields when available. Official response fields include:

- `download_no_watermark_addr`,
- `download_addr`,
- `play_addr`,
- `share_url`,
- `url`,
- `video_urls`.

Asset candidates should keep `url` as the canonical/provenance URL and set `download_url` for the preferred media URL. Selection order:

```text
download_no_watermark_addr
-> existing download_url logic / download_addr / best video_urls entry
-> play_addr
-> share_url
-> url
```

When `download_no_watermark_addr` exists, `download_url` should use it and mark `download_url_type = "no_watermark"`. When it is absent, preserve current download URL behavior.

Visual Director should still be allowed to choose creatively, but a deterministic resolver must validate and repair the plan before download. The resolver handles:

1. Missing `source_url` recovery from the same beat's `asset_candidates`.
2. Duplicate URL replacement using next-best same-beat candidate.
3. Candidate type normalization, for example `video + TikTok URL -> tiktok_clip`.
4. Downloader preference for `download_url` when present, while keeping `url` for provenance and deduplication.
5. Explicit fallback only when no candidate works.
6. Optional reuse of the same URL with a different trim window when it is the only relevant asset.

The final resolved plan must never contain:

```json
{ "type": "tiktok_clip" }
```

It must contain a valid `source_url` or become an explicit fallback action with a reason.

## Composer Duration-Safe Render

Composer should render the visual timeline first, probe the real duration, then mux audio only after duration checks pass.

Flow:

1. Render silent visual timeline from planned scenes, cards, captions, transitions, and crossfades.
2. Probe `visual_timeline.mp4` with ffprobe.
3. Compare visual duration against `voiceover_duration_sec`.
4. If visual duration is shorter, extend visuals safely.
5. Mux voiceover with the repaired visual timeline.

Acceptable extension strategies:

- extend final CTA card,
- freeze last frame,
- extend text card duration,
- reduce or compensate crossfade overlap,
- add explicit outro card.

Hard rule: final video must never truncate audio.

## Reviewer Programmatic Hard Gates

Reviewer should not rely on an LLM pretending to watch/listen. First layer review should be deterministic and fail on metadata violations:

- `video_duration >= audio_duration`,
- scene count is non-zero,
- no broken `tiktok_clip` action,
- caption end time does not exceed video duration,
- fallback was not used while a valid candidate was available,
- final output has audio and video streams.

Optional multimodal review can be added later using a video-capable model. Current estimated Gemini video review cost is low with Flash, but programmatic checks should catch hard failures first.

## Universal Model-Call Diagnostics

Diagnostics should apply to every model-using agent/service, not only Visual Director:

- Safety,
- Segment Producer,
- Scriptwriter,
- Voice Producer / TTS,
- Visual Director,
- Reviewer,
- future multimodal reviewer.

Each model call should persist prompt/input payload, model/provider, raw response, parsed output, validation result, token/cost metadata when available, latency, retry count, status, and error details.

This makes failures traceable across:

```text
prompt/input -> raw response -> parsed output -> normalized output -> final artifact
```

## Explicit Intro Card Contract

The 3-second intro card should be explicit rather than implicit. Recommended ownership: Visual Director creates a `scene 0` / `intro_card` action with `duration=3.0`, and Composer renders it like any other scene.

## Expected Outcome

The fixes should prevent Job #4-style failures by ensuring:

- duplicate URLs are replaced, not deleted,
- Sarwendah/Ruben beats can recover alternate relevant assets,
- final video duration covers the voiceover,
- Reviewer fails hard metadata problems,
- raw model behavior is traceable for future debugging.
