# ADR 0029 — Adopt the official `elevenlabs` Python SDK for the TTS path

**Status:** Accepted
**Date:** 2026-06-28
**Related:** ADR 0021 (audio-first continuous voiceover), ADR 0028 (central `.env` loader — surfaced the silent ElevenLabs-skip → Gemini-fallback bug class)

## Context

The ElevenLabs TTS service (`clipper_agency/services/elevenlabs.py`) was
hand-rolled on top of `httpx` `POST /v1/text-to-speech/{voice_id}` and
`/with-timestamps`. The response parsing was string-dict-based:

```python
alignment = data.get("alignment", {})
chars = alignment.get("chars", [])           # <-- fragile string key
starts = alignment.get("character_start_times_seconds", [])
ends   = alignment.get("character_end_times_seconds", [])
```

This shape is brittle: a single wrong key name silently yields an empty list
instead of raising. The historical manifestation was exactly this — the live
`/with-timestamps` payload uses `characters` (plural) in newer SDK/API
surfaces, while the parsing code read `chars`. Empty timestamps then propagated
downstream into fuzzy/gemini-style proportional word timestamps, degrading the
audio-first AV-sync contract with no visible error. ADR 0028 fixed the *env*
half of this bug (the silent skip), but the *key-typo* half remained as long as
parsing was dict-string-based. Repeated drift incidents (job_8, job_12) and the
AV-drift harness (PR #78) showed the dict-parsing surface keeps costing
debugging time.

The ElevenLabs team ships a first-party Python SDK (`elevenlabs` on PyPI) that
returns **typed Pydantic models** for every response. Adopting it removes the
string-dict surface entirely: there is no `data.get("...")` left to typo.

## Decision

Migrate `clipper_agency/services/elevenlabs.py` to the official
`elevenlabs` Python SDK (`elevenlabs==2.54.0`, pinned). Specifically:

- Construct one client per service: `ElevenLabs(api_key=self.api_key)`.
- Replace the `/with-timestamps` `httpx` call with
  `client.text_to_speech.convert_with_timestamps(voice_id=..., model_id=...,
  text=..., voice_settings=VoiceSettings(...))`, which returns a single typed
  `AudioWithTimestampsResponse`.
- Replace the plain `text-to-speech` `httpx` call with
  `client.text_to_speech.convert(...)` (returns a typed `Iterator[bytes]`,
  materialized into one buffer).
- Build a typed `VoiceSettings(...)` from the existing `_voice_settings_from_env()`
  knobs (kept as the env-config source of truth).
- Read alignment via the typed ATTRIBUTES
  `response.alignment.characters` / `.character_start_times_seconds` /
  `.character_end_times_seconds` (the SDK never exposes the `chars` key here),
  then project onto the existing `{"char","start","end"}` list shape.
- Decode audio via `base64.b64decode(response.audio_base_64)` — the SDK exposes
  audio as a base64 STRING, not bytes.

The PUBLIC service contract is UNCHANGED so `voice_producer.py` is untouched:

- `generate_voice(text, voice_id, output_path) -> str`
- `generate_voice_with_timestamps(text, voice_id, voice_settings=None) ->
  tuple[bytes, list[{"char","start","end"}]]`

## Verified SDK shapes (introspected at runtime against `elevenlabs==2.54.0`)

- `from elevenlabs import ElevenLabs, VoiceSettings` — both importable from the
  package root.
- `client.text_to_speech.convert_with_timestamps(...)` returns a single typed
  `AudioWithTimestampsResponse` (NOT a stream).
- `AudioWithTimestampsResponse` fields: `audio_base_64: str`,
  `alignment: Optional[CharacterAlignmentResponseModel]`,
  `normalized_alignment: Optional[CharacterAlignmentResponseModel]`.
- `CharacterAlignmentResponseModel` fields: `characters: list[str]`,
  `character_start_times_seconds: list[float]`,
  `character_end_times_seconds: list[float]` (seconds-based, end times
  included directly — no duration math required).
- `VoiceSettings` fields (all Optional): `stability`, `similarity_boost`,
  `style`, `use_speaker_boost`, `speed`.
- `client.text_to_speech.convert(...)` returns `Iterator[bytes]`.

> NOTE: an older `Alignment` model (`chars` / `char_start_times_ms` /
> `char_durations_ms`, ms-based) still exists in the SDK package but is NOT
> the type used by `AudioWithTimestampsResponse.alignment`. The migration
> deliberately targets the seconds-based `CharacterAlignmentResponseModel`.

## Alternatives Considered

- **Keep hand-rolled `httpx`, just fix the `chars`→`characters` key** —
  rejected: patches one symptom of a whole bug class. Any future key drift
  (renames, snake_case changes, nested reshapes) would reintroduce the same
  silent-empty failure mode. Typed responses remove the class, not one instance.
- **Hand-roll `httpx` but validate the JSON against a Pydantic model** —
  rejected: this is what the SDK already does, with a model maintained upstream.
  Re-implementing it duplicates effort and risks drift from the canonical schema.
- **Defer until Phase 2 (typed errors / retry/backoff)** — rejected: the
  Phase 1 win (kill the silent-empty-timestamps bug class) is independent of
  and unblocks Phase 2 (typed errors are what enable precise retry/backoff).

## Consequences

- **Positive:** the `chars` vs `characters` key-typo bug class is permanently
  eliminated — alignment is accessed via typed attributes, not string keys.
- **Positive:** typed `VoiceSettings` and typed errors (Phase 2) replace opaque
  `httpx.HTTPStatusError` handling, enabling precise retry/backoff on rate
  limits and auth failures in a follow-up PR.
- **Positive:** public service contract is unchanged; `voice_producer.py` and
  the wider pipeline are byte-identical at the integration boundary.
- **Positive:** one less bespoke HTTP client in the codebase; the SDK handles
  base URL, headers (`xi-api-key`), timeout, and serialization canonically.
- **Negative:** new pinned runtime dependency `elevenlabs==2.54.0` (+ transitive
  `websockets==16.0`). No conflict with the existing `pydantic` 2.13.4 /
  `httpx` 0.28.1 / `pydantic-settings` 2.14.1 stack — both already satisfy the
  SDK's constraints (`pydantic>=1.9.2`, `httpx>=0.21.2`).
- **Negative:** the SDK exposes audio as a base64 STRING, so the service still
  calls `base64.b64decode` once. Trivial, and the same decode the old code did.
- **Note:** `websockets` is a transitive dep of the SDK (used for its
  realtime/conversational surfaces, not by our TTS path); pinned for
  deterministic installs.
- **Note:** this ADR is Phase 1 of a 3-phase SDK adoption (Phase 2 = typed
  errors + retry/backoff + chunked-fallback fix; Phase 3 = voice listing +
  `voice_id` preflight).
