"""Pure audio-sequencing primitives for per-scene audio pairing in FFmpeg filter graphs.

All functions are side-effect-free: same input always produces same output,
no mutation, no I/O.
"""

from __future__ import annotations


def build_audio_video_concat(
    scene_labels: list[str],
    num_video_inputs: int,
    audio_file_count: int,
    has_xfade: bool = False,
) -> tuple[str, str, str]:
    """Build per-scene audio+video concat filter string.

    Args:
        scene_labels: Output labels from the video filter chain
            (e.g. ``["t0", "t1", "t2"]``).
        num_video_inputs: Total number of ``-i`` video inputs; audio
            input indices start at this value.
        audio_file_count: Number of audio files available.
        has_xfade: ``True`` when the video chain uses xfade transitions
            (video is already handled; concat audio only).

    Returns:
        ``(filter_string, output_video_label, output_audio_label)``.

        * Mode A (``has_xfade=False``): paired audio+video concat —
          ``output_video_label="outv"``, ``output_audio_label="outa"``.
        * Mode B (``has_xfade=True``): audio-only concat —
          ``output_video_label=""``, ``output_audio_label="outa"``.
        * No audio files: returns ``("anullsrc", "", "outa")``.
    """
    num_scenes = len(scene_labels)

    # No audio at all — caller uses anullsrc directly
    if audio_file_count == 0:
        return ("anullsrc", "", "outa")

    audio_start = num_video_inputs
    effective_audio = min(audio_file_count, num_scenes)

    # Build preamble (silence sources) and audio references
    preamble = ""
    audio_refs: list[str] = []
    for i in range(num_scenes):
        if i < effective_audio:
            audio_refs.append(f"[{audio_start + i}:a]")
        else:
            silence_label = f"asilence{i}"
            preamble += f"anullsrc=r=44100[{silence_label}];"
            audio_refs.append(f"[{silence_label}]")

    # Mode A: interleave video labels with audio references
    if not has_xfade:
        pairs: list[str] = []
        for i in range(num_scenes):
            pairs.append(f"[{scene_labels[i]}]")
            pairs.append(audio_refs[i])
        filter_str = (
            preamble
            + "".join(pairs)
            + f"concat=n={num_scenes}:v=1:a=1[outv][outa]"
        )
        return (filter_str, "outv", "outa")

    # Mode B: audio-only concat (video handled by xfade chain)
    filter_str = (
        preamble
        + "".join(audio_refs)
        + f"concat=n={num_scenes}:v=0:a=1[outa]"
    )
    return (filter_str, "", "outa")
