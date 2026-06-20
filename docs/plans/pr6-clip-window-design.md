# PR 6 — Source Transcript & Clip-Window Selector (Minimal Contract-First)

**Status:** LOCKED (design + necessity workflow, 2026-06-19)
**Branch:** `phase/26-pr6-clip-window`
**Parent plan:** [`2026-06-15-phase26-production-correctness-asset-qualification.md`](./2026-06-15-phase26-production-correctness-asset-qualification.md) §PR 6
**Needs:** PR 5 (MERGED) — the qualification boundary delivers qualified source videos.
**Version:** stays `v2.3.0` (PR 10 owns the `v2.4.0` bump).

---

## 1. Scope Verdict — Minimal Contract-First (option b)

PR 6 ships the **data-flow contract** (`source_start_sec`/`source_end_sec`) end-to-end, **Composer trims from the validated window**, and a **pluggable `WindowSelector`** with a conservative keyword-overlap default. The **transcript/whisper backend is DEFERRED** to post-v2.4.0.

Why not full-whisper (a): no transcript infra exists (grep-empty); whisper = forbidden GPU + heavy greenfield dep (torch/faster-whisper) + non-hermetic model download; the v2.4.0 release gate does NOT require clip-windowing. Fails ADR 0026.

Why not defer-the-whole-PR (c): PR 6 is the phase's one genuinely-new feature; the PR 5 qualification seam is clean + additive (it filters ORIGINAL candidate dicts, so a new field survives to VD untouched); Composer already owns `_probe_duration` + `_detect_scene_boundaries` + `_find_best_cut_point` to reuse. The contract is cheap and unblocks the future backend behind a stable selector interface.

**Honest gap (documented, not hidden):** verification criterion 2 ("trimmed segment matches the beat's spoken point") needs transcript *timing* to localize a spoken point to a timestamp — keyword overlap cannot. PR 6 v1 therefore ships `ClipWindow(0.0, None)` (full clip from zero = today's behavior) for most candidates. Criteria 1 (window within bounds), 3 (outputs source_start_sec/end_sec), and 4 (Composer uses source_start_sec in the FFmpeg trim) are fully delivered. Over-shipping a false-precision offset heuristic would be worse (renders the wrong sub-segment).

## 2. Data Contract

`AssetCandidate` (`clipper_agency/config/schema.py:269`) gains two optional fields — **additive, backward-compatible** (defaults preserve today's from-zero behavior):
```python
source_start_sec: float = 0.0
source_end_sec: float | None = None   # None => to end of source
```

Propagation (4 hops, each additive):
1. **Qualification boundary** (`engine._apply_asset_qualification`, after the kept-candidate filter): for each kept VIDEO candidate invoke the selector; attach `source_start_sec`/`source_end_sec` to the kept dict. Rides the PR 5 immutable rewrite (`{**beat_dict, "asset_candidates": kept}`).
2. **VD action** (`_candidate_to_action`, `visual_director.py:1133` tiktok_clip branch + any video action): copy the two fields into the action dict.
3. **VD exec** (`_exec_tiktok_clip` → result; passthrough tuple at `visual_director.py:619-630`): add the two keys so they reach the Composer asset.
4. **Composer enrich** (`_enrich_audio_first_assets` field tuple, `composer.py:1340-1342`): add the two keys so they reach `_collect_beat_clips` (`asset = assets[i]`).

Units: wall-clock seconds in the **downloaded local file** (the only frame Composer sees; `_probe_duration` probes the local path).

**Default window (always in-bounds):** `source_start_sec=0.0, source_end_sec=None` ⇒ Composer trims from 0 to end. Byte-identical to today. No selector failure can produce an out-of-bounds window because the default IS the full-clip window.

## 3. Window Selector — new `clipper_agency/core/clip_window.py`

```python
class WindowSelector(Protocol):
    def select_window(self, candidate: dict, beat, source_duration_sec: float | None) -> ClipWindow: ...

@dataclass(frozen=True)
class ClipWindow:
    source_start_sec: float
    source_end_sec: float | None  # None => to end of source
```

**`KeywordOverlapWindowSelector`** (the ONLY selector shipped in PR 6) — pure string scoring, no I/O, no ML:
- score = normalized keyword overlap of `beat.caption_keywords + spoken_point + narration_goal` vs `candidate.title + desc + reason`.
- Conservative v1: returns `ClipWindow(0.0, None)` regardless of score (proves the seam + bounds-contract without overfitting fragile text-match to arbitrary offsets). A wrong window is worse than the full clip.
- Non-video types (image/card) → `ClipWindow(0.0, None)` by construction.
- Output is **always within bounds** by construction (start=0.0, end=None).

**Bounds contract:** selector output is trusted-but-revalidated. Composer clamps in `_smart_trim` (defense-in-depth against a future buggy transcript selector). This is where verification criterion 1 ("window within bounds") is enforced, at the render boundary where `_probe_duration` already exists.

**Transcript backend (DEFERRED):** a future `TranscriptWindowSelector` implementing the same Protocol, behind `settings.clip_window_backend = "keyword"|"transcript"`, using faster-whisper (CTranslate2 int8 — never torch/openai-whisper). No whisper import, no torch dep, no model file in this PR.

## 4. Composer Change (pre-trim path)

1. `_smart_trim` (`composer.py:1166`) gains `source_start_sec: float = 0.0, source_end_sec: float | None = None`. **BOUNDS CLAMP here** (verification point): `start = max(0, min(source_start_sec, dur-eps))`; `end = min(source_end_sec or dur, dur)`; degenerate (`end <= start`) ⇒ full clip `(0, dur)`.
2. `_trim_long_clip` (`composer.py:1214`): `'-ss','0'` → `'-ss', start`; `-to` bounded by `end`; `speed_factor` over the effective window.
3. `_stretch_short_clip` (`composer.py:1233/1243`): add `'-ss', start` before `-t`/loop in both branches.
4. `_process_existing_scene` (`composer.py:1579`): pass `asset.get("source_start_sec", 0.0)`, `asset.get("source_end_sec")` into `_smart_trim` (asset is in scope via `_collect_beat_clips` `asset = assets[i]`).

**NOT touched:** the audio-first filtergraph `trim=duration={duration}` (`composer.py:1406/1411`) operates on post-trim files — the offset belongs in the pre-trim step only. Touching it would double-apply the offset (rejected).

## 5. TDD Slice Table

| # | Slice | Kind | Delta |
|---|-------|------|-------|
| 1 | Schema + ClipWindow contract | production | `AssetCandidate.source_start_sec/end_sec` (`schema.py:269`); frozen `ClipWindow` in new `core/clip_window.py`. Zero behavior change. |
| 2 | WindowSelector Protocol + keyword default | production | `WindowSelector` Protocol + `KeywordOverlapWindowSelector` in `clip_window.py`. Pure string scoring; always in-bounds; no ML. |
| 3 | Wire selector into qualification boundary | production | `engine._apply_asset_qualification` — invoke selector on kept video candidates, attach window. Selector injectable/mocked in tests. |
| 4 | Thread window through VD action+asset | production | `_candidate_to_action` + `_exec_tiktok_clip` + passthrough tuple (`visual_director.py:619-630`). |
| 5 | Composer enrich whitelist + bounds clamp | production | `_enrich_audio_first_assets` field tuple; `_smart_trim` signature + clamp. |
| 6 | Composer FFmpeg `-ss` wiring | production | `_trim_long_clip`/`_stretch_short_clip` `-ss`; `_process_existing_scene` threading. |
| 7 | Selector unit tests | test | `tests/core/test_clip_window.py` — determinism, non-video→full-clip, always-in-bounds, Protocol swap-in. |
| 8 | Composer bounds + `-ss` regression | test | `tests/agents/test_composer_clip_window.py` — `-ss` in cmd, clamp, None-end, degenerate→full-clip. |
| 9 | Qualification-seam integration test | test | extend `tests/core/test_asset_qualification_seam.py` — window carried to rewritten beat; cache-key parity preserved. |
| 10 | Docs + CHANGELOG | production | CHANGELOG `[Unreleased]`; `technical_design` clip-window section; `requirements_traceability` mapping; ADR note: transcript deferred. |
| 11 | Transcript/whisper backend | **DEFERRED** | post-v2.4.0. faster-whisper behind config flag. Blocked: ADR 0026, GPU forbidden, non-hermetic, gate doesn't need it. |
| 12 | yt-dlp auto-caption path | **DEFERRED** | post-v2.4.0. YouTube-only; TikTok/Pexels caption-poor. Folds into slice 11. |
| 13 | Keyframe-precise window snapping | **DEFERRED** | small follow-up once a non-zero window exists. |

## 6. Risks

- **Bounds violation (highest):** future transcript selector could return `start >= dur` or `end <= start`. → Composer re-clamps in `_smart_trim`; degenerate ⇒ full clip. Tests cover clamp + degenerate (slice 8).
- **Inspection-cache parity (PR 5 invariant):** window fields must NOT enter `compute_asset_content_hash` or VD re-inspection forks. Slice 9 asserts hash parity (same pattern PR 5 uses for `relevance_score`/`title`).
- **Hermetic testing:** default selector is pure string math (no I/O). Composer `-ss` tests mock `run_ffmpeg_streaming` + `_probe_duration`. The ~2031-test offline suite stays green.
- **Default under-delivers on criterion 2:** documented honestly (above); semantic localization waits for the deferred backend.

## 7. ADR 0026 Compliance

COMPLIANT. The data-flow contract does not exist today (grep-verified zero occurrences) — building it is contract enforcement, not a rebuild. Composer reuses `_probe_duration`, `_detect_scene_boundaries`, `_find_best_cut_point`, and the existing FFmpeg trim builders — PR 6 adds only the `-ss` offset + bounds clamp. The qualification seam is PR 5's already-open additive filter. NO new heavy dependency (no torch/whisper/model files) — keeps CPU-only + hermetic. Default window `(0.0, None)` is byte-identical to current behavior, so PR 6 cannot regress the offline suite or the golden set. The genuinely-greenfield parts (transcript generation, semantic windower) are DEFERRED per ADR 0026's out-of-scope clause + the GPU prohibition.
