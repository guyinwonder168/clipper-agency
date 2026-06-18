"""PR 6 — Composer clip-window ``-ss`` wiring + bounds clamp (design slices 5, 6, 8).

``_smart_trim`` honors ``source_start_sec``/``source_end_sec``: it clamps the window to
source bounds (degenerate => full clip), then ``_trim_long_clip``/``_stretch_short_clip``
emit ``-ss <start>`` in the FFmpeg command. PR 6 v1 always sends the full-clip window
``(0.0, None)``, so these tests inject non-zero windows to verify the plumbing + clamp
(verification criterion 1: window within bounds; criterion 4: Composer uses source_start_sec).
Hermetic — ``run_ffmpeg_streaming`` + duration/scene probes are mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from clipper_agency.agents import composer as composer_mod
from clipper_agency.agents.composer import ComposerAgent


class TestSmartTrimClipWindow:
    def _run_smart_trim(
        self,
        tmp_path: Path,
        dur: float,
        target: float,
        source_start_sec: float = 0.0,
        source_end_sec: float | None = None,
    ) -> list[list[str]]:
        composer = ComposerAgent()
        clip = tmp_path / "src.mp4"
        clip.write_bytes(b"x")
        cmds: list[list[str]] = []
        with (
            patch.object(composer, "_probe_duration", return_value=dur),
            patch.object(composer, "_detect_scene_boundaries", return_value=[]),
            patch.object(composer, "_find_best_cut_point", return_value=target),
            patch.object(
                composer_mod,
                "run_ffmpeg_streaming",
                side_effect=lambda cmd, **_kw: cmds.append(list(cmd)),
            ),
        ):
            composer._smart_trim(
                str(clip),
                target,
                tmp_path,
                source_start_sec=source_start_sec,
                source_end_sec=source_end_sec,
            )
        return cmds

    @staticmethod
    def _ss_value(cmd: list[str]) -> float:
        assert "-ss" in cmd, f"expected -ss in cmd: {cmd}"
        return float(cmd[cmd.index("-ss") + 1])

    def test_trim_cmd_uses_source_start(self, tmp_path: Path) -> None:
        cmds = self._run_smart_trim(tmp_path, dur=30.0, target=5.0, source_start_sec=5.0)
        assert cmds, "expected a trim command"
        assert self._ss_value(cmds[0]) == 5.0

    def test_start_clamped_within_source_bounds(self, tmp_path: Path) -> None:
        cmds = self._run_smart_trim(tmp_path, dur=30.0, target=5.0, source_start_sec=5.0)
        start = self._ss_value(cmds[0])
        assert 0.0 <= start <= 30.0

    def test_stretch_path_also_uses_source_start(self, tmp_path: Path) -> None:
        # target exceeds the window length => _stretch_short_clip path; -ss still applied.
        cmds = self._run_smart_trim(tmp_path, dur=30.0, target=50.0, source_start_sec=5.0)
        assert cmds, "expected a stretch command"
        assert self._ss_value(cmds[0]) == 5.0

    def test_degenerate_window_falls_back_to_full_clip(self, tmp_path: Path) -> None:
        # end <= start => degenerate => full clip from zero.
        cmds = self._run_smart_trim(
            tmp_path,
            dur=20.0,
            target=4.0,
            source_start_sec=10.0,
            source_end_sec=8.0,
        )
        assert self._ss_value(cmds[0]) == 0.0

    def test_start_beyond_duration_clamps_to_full_clip(self, tmp_path: Path) -> None:
        # start far beyond duration clamps to dur-eps => degenerate => full clip (start 0).
        cmds = self._run_smart_trim(tmp_path, dur=10.0, target=3.0, source_start_sec=100.0)
        assert self._ss_value(cmds[0]) == 0.0

    def test_default_window_is_zero_start(self, tmp_path: Path) -> None:
        # PR 6 v1 default (0.0, None) => -ss 0.0 (today's from-zero behavior).
        cmds = self._run_smart_trim(tmp_path, dur=30.0, target=5.0)
        assert self._ss_value(cmds[0]) == 0.0
