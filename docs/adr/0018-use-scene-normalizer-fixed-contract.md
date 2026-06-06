# ADR 0018: Use Scene Normalizer Fixed Media Contract

**Date:** 2026-06-06
**Status:** Accepted
**Phase:** 18

## Context

Composer receives mixed media from yt-dlp, Pexels, local files, generated cards, and static images. These inputs can differ in resolution, frame rate, sample aspect ratio, codec, and duration. The old pipeline assumed assets were compatible enough for concatenation, which caused unstable FFmpeg behavior and videos without consistent motion or timing.

The project needs deterministic offline rendering with predictable 9:16 TikTok output.

## Decision

Normalize every visual scene before final composition to a fixed contract:

- 1080x1920 vertical resolution.
- 30fps constant frame rate target.
- SAR 1:1.
- H.264-compatible video stream.
- yuv420p pixel format.
- clip duration validation with flash-frame rejection.
- Ken Burns zoompan conversion for static images.
- source clip audio stripped unless explicitly intended.

Scene normalization is a Composer responsibility because Composer is the final render boundary and already controls FFmpeg diagnostics.

## Alternatives Considered

### Trust upstream asset providers

- **Pros:** Less processing.
- **Cons:** Mixed media breaks concat/xfade and creates inconsistent output.

### Normalize inside Visual Director

- **Pros:** Assets are fixed earlier.
- **Cons:** Visual Director would need rendering responsibilities and FFmpeg details; retrying Composer would not guarantee normalization.

### Normalize inside Composer

- **Pros:** One fixed render boundary, deterministic, easy to test with Composer output.
- **Cons:** Composer does more work and must persist diagnostics clearly.

## Rationale

- FFmpeg concat and xfade require compatible stream properties.
- Fixed media contracts reduce downstream branching and Sonar/security risk.
- Composer already owns the final media graph and can record provenance.
- Static images need motion to avoid dead-looking videos; Ken Burns provides lightweight deterministic motion.

## Consequences

- **Positive:** Mixed framerates and SAR no longer break composition.
- **Positive:** Static images become usable animated scenes.
- **Positive:** Final output becomes more predictable for G10 validation.
- **Negative:** Normalization adds processing time.
- **Negative:** Clip duration policy must stay aligned with timeline planning; fixed 1-5s clip assumptions are insufficient for long narration scenes without looping/extension logic.
- **Neutral:** Tier 4 will make Visual Director and Composer timeline-aware so normalized visuals can be extended to actual narration duration without cutting audio.
