"""Per-beat caption-window derivation (PR 13).

The contract (pinned by PR 13) rolls word-level timestamps up to a per-beat
window: ``{beat_id: (word_range[0].start, word_range[1].end)}`` where
``word_range`` is INCLUSIVE (``word_range[1]`` is the LAST word, not past it).

This is the AV-drift caption window — the audio window the composer aligns a
beat's visuals to. Note this differs from the ADR-0020 canonical timeline
(``build_canonical_timeline``), which uses the *next beat's* first-word start as
the end edge. For AV-drift we want the beat's own audio span, so we roll up the
inclusive word_range directly rather than calling the canonical builder.
"""

from __future__ import annotations

from clipper_agency.diagnostics.planned import read_ts


def derive_caption_windows(
    narrative_structure: list[dict],
    timestamps: list[dict],
) -> dict[int, tuple[float, float]]:
    """Map each ``beat_id`` to its caption window
    ``(word_range[0].start, word_range[1].end)``.

    Returns an empty dict if either input is empty.
    """
    if not narrative_structure or not timestamps:
        return {}

    windows: dict[int, tuple[float, float]] = {}
    for beat in narrative_structure:
        beat_id = beat.get("beat_id", len(windows) + 1)
        w0, w1 = beat["word_range"]
        start = read_ts(timestamps, w0, "start")
        end = read_ts(timestamps, w1, "end")
        windows[beat_id] = (start, end)
    return windows
