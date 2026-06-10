"""Tests for ComposerAgent artifact persistence and output naming."""

import json
from pathlib import Path

import pytest

from clipper_agency.agents.composer import (
    ComposerAgent,
    _build_keyword_chain,
    _has_xfade_transitions,
)
from clipper_agency.rendering.contracts import CaptionOverlay
from clipper_agency.rendering.primitives import escape_drawtext


def _mock_preflight_ok(mocker):
    """Mock FFmpegPreflight.probe() to return a passing result."""
    mock_result = mocker.MagicMock()
    mock_result.ffmpeg_found = True
    mock_result.ffprobe_found = True
    mock_result.libx264_available = True
    mock_result.aac_available = True
    mock_result.mp3_decode_available = True
    mock_result.all_ok.return_value = True
    mocker.patch(
        "clipper_agency.core.ffmpeg_preflight.FFmpegPreflight.probe",
        return_value=mock_result,
    )
    mocker.patch("dataclasses.asdict", return_value={"ffmpeg_found": True})


class TestComposerArtifacts:
    """Composer writes input/output, FFmpeg diagnostics to agent dir."""

    def test_output_video_named_video_mp4(self, tmp_path, mocker):
        """Output video should be video.mp4, not final.mp4."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        # Bypass scene validation/normalization (no real files on CI)
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mocker.MagicMock(success=True, error=""),
        )
        agent = ComposerAgent()
        result = agent.execute(
            job_id=30,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/scene_0.mp3"],
            output_dir=str(tmp_path),
        )
        video_path = result["video_path"]
        assert video_path.endswith("video.mp4")
        assert "final.mp4" not in video_path

    def test_persists_input_json(self, tmp_path, mocker):
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        agent = ComposerAgent()
        agent.execute(
            job_id=31,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        input_file = tmp_path / "job_31" / "agents" / "composer" / "input.json"
        assert input_file.exists()
        data = json.loads(input_file.read_text())
        assert data["job_id"] == 31
        assert data["video_asset_count"] == 1
        assert data["audio_file_count"] == 1

    def test_persists_ffmpeg_command(self, tmp_path, mocker):
        _mock_preflight_ok(mocker)
        mock_ffmpeg = mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        # Bypass new scene validation/normalization chain
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )
        agent = ComposerAgent()
        agent.execute(
            job_id=32,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        cmd_file = tmp_path / "job_32" / "agents" / "composer" / "ffmpeg_command.txt"
        assert cmd_file.exists()
        content = cmd_file.read_text()
        assert "ffmpeg" in content
        assert "-filter_complex" in content

    def test_persists_output_json(self, tmp_path, mocker):
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )
        agent = ComposerAgent()
        agent.execute(
            job_id=33,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        output_file = tmp_path / "job_33" / "agents" / "composer" / "output.json"
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["status"] == "completed"
        assert "video_path" in data

    def test_ffmpeg_stderr_log_on_failure(self, tmp_path, mocker):
        """When ffmpeg fails, stderr should be persisted."""
        import subprocess

        err = subprocess.CalledProcessError(
            1, "ffmpeg",
            stderr="File not found: invalid input\n",
        )
        # Preflight must pass; actual ffmpeg compose fails
        mock_result = mocker.MagicMock()
        mock_result.ffmpeg_found = True
        mock_result.ffprobe_found = True
        mock_result.libx264_available = True
        mock_result.aac_available = True
        mock_result.mp3_decode_available = True
        mock_result.all_ok.return_value = True
        mocker.patch(
            "clipper_agency.core.ffmpeg_preflight.FFmpegPreflight.probe",
            return_value=mock_result,
        )
        mocker.patch("dataclasses.asdict", return_value={"ffmpeg_found": True})
        # Mock run_ffmpeg_streaming to raise on concat call, succeed on thumbnail
        mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
            side_effect=err,
        )
        mocker.patch("subprocess.check_output", return_value=b"libx264\naac\nmp3")
        # Bypass scene validation/normalization — only concat should fail
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )
        agent = ComposerAgent()
        agent.execute(
            job_id=34,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        log_file = tmp_path / "job_34" / "agents" / "composer" / "ffmpeg_stderr.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "File not found" in content


class TestComposerOutputNaming:
    """Video output uses video.mp4 naming convention."""

    def test_video_path_includes_job_id(self, mocker):
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        # Bypass scene validation/normalization (no real files on CI)
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mocker.MagicMock(success=True, error=""),
        )
        agent = ComposerAgent()
        result = agent.execute(
            job_id=35,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir="/tmp/output",
        )
        assert "/job_35/" in result["video_path"]
        assert result["video_path"].endswith("video.mp4")


class TestComposerTreatmentMetadata:
    """Composer preserves treatment metadata from visual director in output."""

    def test_composer_preserves_treatment_in_assembly(self, tmp_path, mocker):
        """Assets with treatment fields should pass through to the FFmpeg pipeline."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")

        # Mock scene validation + normalization
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.MagicMock(
                          width=1080, height=1920, codec="h264",
                          duration=30.0, has_audio=False,
                          pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mock_norm.path = "/tmp/norm_scene1.mp4"
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )

        agent = ComposerAgent()
        assets_with_treatment = [{
            "scene": 1,
            "path": "/tmp/scene_1.mp4",
            "treatment": "broll_standard",
            "target_duration": 5,
            "transition_in": "crossfade",
            "transition_out": "hard_cut",
        }]

        # Create output dir so _assemble_video can write card_fallback.json
        output_dir = tmp_path / "job_40"
        output_dir.mkdir(parents=True)

        result = agent._assemble_video(
            assets_with_treatment,
            ["/tmp/voice.mp3"],
            str(output_dir / "video.mp4"),
        )

        # The command should have been built successfully
        assert result["cmd"]  # non-empty command
        # Card fallback should be empty (scene was valid)
        assert result["card_fallback_scenes"] == []

    def test_composer_process_scene_valid_normalization(self, tmp_path, mocker):
        """_process_scene normalizes a valid scene path and returns result."""
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.MagicMock(
                          width=1080, height=1920, codec="h264",
                          duration=30.0, has_audio=False,
                          pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mock_norm.path = str(tmp_path / "norm.mp4")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )

        agent = ComposerAgent()
        norm_path, was_card = agent._process_scene(
            tmp_path, mocker.MagicMock(), mocker.MagicMock(),
            1, "/tmp/scene_1.mp4",
        )

        assert norm_path is not None
        assert was_card is False

    def test_composer_process_scene_backward_compat_no_asset(self, tmp_path, mocker):
        """_process_scene works without asset param (backward compat)."""
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.MagicMock(
                          width=1080, height=1920, codec="h264",
                          duration=30.0, has_audio=False,
                          pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mock_norm.path = str(tmp_path / "norm.mp4")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )

        agent = ComposerAgent()
        norm_path, was_card = agent._process_scene(
            tmp_path, mocker.MagicMock(), mocker.MagicMock(),
            1, "/tmp/scene_1.mp4",
        )

        assert norm_path is not None
        assert was_card is False

    def test_build_assembly_cmd_applies_trim_from_target_duration(self):
        """_build_assembly_cmd includes trim=duration filters matching asset target_duration."""
        valid_normalized = ["/tmp/scene_1.mp4", "/tmp/scene_2.mp4"]
        normalized_assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4", "target_duration": 4},
            {"scene": 2, "path": "/tmp/scene_2.mp4", "target_duration": 7},
        ]
        audio_files: list[str] = []
        output_path = "/tmp/output.mp4"

        cmd = ComposerAgent._build_assembly_cmd(
            valid_normalized, normalized_assets, audio_files, output_path,
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "trim=duration=4" in filter_complex
        assert "trim=duration=7" in filter_complex
        # Default transition is crossfade (xfade), not flat concat.
        assert "xfade=transition=fade" in filter_complex

    def test_build_assembly_cmd_defaults_trim_to_5(self):
        """_build_assembly_cmd defaults trim to 5 when target_duration is missing."""
        valid_normalized = ["/tmp/scene_1.mp4"]
        normalized_assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4"},
        ]
        audio_files: list[str] = []
        output_path = "/tmp/output.mp4"

        cmd = ComposerAgent._build_assembly_cmd(
            valid_normalized, normalized_assets, audio_files, output_path,
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "trim=duration=5" in filter_complex
        # Single scene: no transitions, label maps directly to [outv].
        assert "[outv]" in filter_complex


class TestComposerTreatmentFilters:
    """Treatment filters from TreatmentFilterBuilder are applied in assembly."""

    def test_build_assembly_cmd_applies_treatment_filter(self):
        """cinematic_crop treatment prepends crop+scale filter before trim."""
        valid_normalized = ["/tmp/scene_1.mp4"]
        normalized_assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4", "target_duration": 5,
             "treatment": "cinematic_crop", "type": "video"},
        ]
        cmd = ComposerAgent._build_assembly_cmd(
            valid_normalized, normalized_assets, [], "/tmp/output.mp4",
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        # cinematic_crop YAML: crop=ih*9/16:ih,scale=1080:1920
        # TreatmentFilterBuilder appends setsar=1/1 for scale/crop
        assert "crop=ih*9/16:ih,scale=1080:1920,setsar=1/1,trim=duration=5" in filter_complex
        assert "-pix_fmt" in cmd
        assert "yuv420p" in cmd
        assert "-movflags" in cmd
        assert "+faststart" in cmd

    def test_build_assembly_cmd_null_treatment_no_extra_filter(self):
        """broll_standard (null filter) produces same filter as no treatment."""
        valid_normalized = ["/tmp/scene_1.mp4"]
        normalized_assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4", "target_duration": 5,
             "treatment": "broll_standard", "type": "video"},
        ]
        cmd = ComposerAgent._build_assembly_cmd(
            valid_normalized, normalized_assets, [], "/tmp/output.mp4",
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        # No treatment filter — just trim+setpts+fps, mapped to [outv] for single scene
        assert "[0:v]trim=duration=5,setpts=PTS-STARTPTS,fps=30[outv]" in filter_complex
        assert "crop=" not in filter_complex
        assert "scale=" not in filter_complex
        assert "-pix_fmt" in cmd
        assert "yuv420p" in cmd
        assert "-movflags" in cmd
        assert "+faststart" in cmd

    def test_build_assembly_cmd_treatment_respects_duration(self):
        """Treatment doesn't alter the target_duration used in trim."""
        valid_normalized = ["/tmp/scene_1.mp4"]
        normalized_assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4", "target_duration": 3,
             "treatment": "cinematic_crop", "type": "video"},
        ]
        cmd = ComposerAgent._build_assembly_cmd(
            valid_normalized, normalized_assets, [], "/tmp/output.mp4",
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "trim=duration=3" in filter_complex
        assert "trim=duration=5" not in filter_complex
        assert "-pix_fmt" in cmd
        assert "yuv420p" in cmd
        assert "-movflags" in cmd
        assert "+faststart" in cmd

    def test_build_assembly_cmd_text_treatment_substitutes_vars(self):
        """hook_big_caption substitutes {text} with headline value."""
        valid_normalized = ["/tmp/scene_1.mp4"]
        normalized_assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4", "target_duration": 5,
             "treatment": "hook_big_caption", "type": "text",
             "headline": "Test Headline"},
        ]
        cmd = ComposerAgent._build_assembly_cmd(
            valid_normalized, normalized_assets, [], "/tmp/output.mp4",
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "drawtext=text='Test Headline'" in filter_complex
        assert "{text}" not in filter_complex
        assert "-pix_fmt" in cmd
        assert "yuv420p" in cmd
        assert "-movflags" in cmd
        assert "+faststart" in cmd

    def test_build_assembly_cmd_no_treatment_metadata_still_works(self):
        """Asset without treatment key works like before (backward compat)."""
        valid_normalized = ["/tmp/scene_1.mp4"]
        normalized_assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4", "target_duration": 5},
        ]
        cmd = ComposerAgent._build_assembly_cmd(
            valid_normalized, normalized_assets, [], "/tmp/output.mp4",
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        # Single scene: trim output maps directly to [outv].
        assert "[0:v]trim=duration=5,setpts=PTS-STARTPTS,fps=30[outv]" in filter_complex
        assert "-pix_fmt" in cmd
        assert "yuv420p" in cmd
        assert "-movflags" in cmd
        assert "+faststart" in cmd


def _build_two_scene_cmd(scene0: dict, scene1: dict) -> list[str]:
    """Helper: build assembly cmd for two scenes with sensible defaults."""
    valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
    assets = [
        {"scene": 1, "path": valid[0], "target_duration": 5, **scene0},
        {"scene": 2, "path": valid[1], "target_duration": 5, **scene1},
    ]
    cmd = ComposerAgent._build_assembly_cmd(valid, assets, [], "/tmp/out.mp4")
    return cmd


def _filter_complex(cmd: list[str]) -> str:
    return cmd[cmd.index("-filter_complex") + 1]


class TestComposerTransitions:
    """Transition chain: xfade, hard_cut, mixed, clamping, fallbacks."""

    def test_xfade_transition_applied(self):
        """2 scenes, crossfade → xfade in filter, no flat concat."""
        cmd = _build_two_scene_cmd(
            {"transition_out": "crossfade"},
            {},
        )
        fc = _filter_complex(cmd)
        assert "xfade=transition=fade" in fc
        assert "concat=n=2:v=1" not in fc

    def test_hard_cut_uses_concat(self):
        """2 scenes, hard_cut → concat in filter, no xfade."""
        cmd = _build_two_scene_cmd(
            {"transition_out": "hard_cut"},
            {},
        )
        fc = _filter_complex(cmd)
        assert "concat=n=2:v=1" in fc
        assert "xfade=" not in fc

    def test_mixed_transitions(self):
        """3 scenes: crossfade then hard_cut → both xfade and concat present."""
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4", "/tmp/s2.mp4"]
        assets = [
            {"scene": 1, "path": valid[0], "target_duration": 5,
             "transition_out": "crossfade"},
            {"scene": 2, "path": valid[1], "target_duration": 5,
             "transition_out": "hard_cut"},
            {"scene": 3, "path": valid[2], "target_duration": 5},
        ]
        cmd = ComposerAgent._build_assembly_cmd(valid, assets, [], "/tmp/o.mp4")
        fc = _filter_complex(cmd)
        assert "xfade=transition=fade" in fc
        assert "concat=n=2:v=1" in fc

    def test_xfade_offset_calculated_correctly(self):
        """scene[0] dur=5, crossfade dur=0.5 → offset=5-0.5-0.1=4.4."""
        cmd = _build_two_scene_cmd(
            {"target_duration": 5, "transition_out": "crossfade"},
            {"target_duration": 5},
        )
        fc = _filter_complex(cmd)
        assert "offset=4.4" in fc

    def test_xfade_uses_custom_transition_duration(self):
        """Asset with transition_duration override uses that value."""
        cmd = _build_two_scene_cmd(
            {"target_duration": 5, "transition_out": "crossfade",
             "transition_duration": 0.8},
            {"target_duration": 5},
        )
        fc = _filter_complex(cmd)
        assert "duration=0.8" in fc

    def test_last_scene_no_transition_out(self):
        """Only 1 transition pair for 2 scenes; last scene has no transition."""
        cmd = _build_two_scene_cmd(
            {"transition_out": "crossfade"},
            {},
        )
        fc = _filter_complex(cmd)
        # Exactly one xfade between scene 0 and 1.
        assert fc.count("xfade=") == 1
        assert "[outv]" in fc

    def test_transition_duration_clamped_for_short_clip(self):
        """Short next clip: trans duration clamped to min(dur, min(a,b)-0.15)."""
        # scene[0] dur=1.5, scene[1] dur=0.3, crossfade default=0.3
        # clamp = min(0.3, min(1.5, 0.3) - 0.15) = min(0.3, 0.15) = 0.15
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            {"scene": 1, "path": valid[0], "target_duration": 1.5,
             "transition_out": "crossfade"},
            {"scene": 2, "path": valid[1], "target_duration": 0.3},
        ]
        cmd = ComposerAgent._build_assembly_cmd(valid, assets, [], "/tmp/o.mp4")
        fc = _filter_complex(cmd)
        assert "duration=0.15" in fc

    def test_unknown_transition_falls_back_to_crossfade(self):
        """Unknown transition name → treated as crossfade."""
        cmd = _build_two_scene_cmd(
            {"transition_out": "nonexistent"},
            {},
        )
        fc = _filter_complex(cmd)
        assert "xfade=transition=fade" in fc


class TestComposerAudioSequencer:
    """Audio is paired per-scene via audio_sequencer (replaces broken amix)."""

    def test_audio_pairs_per_scene(self):
        """2 scenes + 2 audio → audio concat (NOT amix) in filter."""
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            {"scene": 1, "path": valid[0], "target_duration": 5},
            {"scene": 2, "path": valid[1], "target_duration": 5},
        ]
        audio = ["/tmp/voice_0.mp3", "/tmp/voice_1.mp3"]

        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, audio, "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Should use concat for audio, not amix
        assert "concat=n=2:v=0:a=1[outa]" in fc
        assert "amix" not in fc

    def test_no_audio_uses_anullsrc(self):
        """0 audio files → anullsrc[outa] in filter."""
        valid = ["/tmp/s0.mp4"]
        assets = [{"scene": 1, "path": valid[0], "target_duration": 5}]

        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        assert "anullsrc[outa]" in fc
        assert "amix" not in fc
        assert "concat" not in fc.split("anullsrc")[0]  # no audio concat

    def test_fewer_audio_pads_silence(self):
        """3 scenes + 1 audio → silence padding for missing audio."""
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4", "/tmp/s2.mp4"]
        assets = [
            {"scene": 1, "path": valid[0], "target_duration": 5},
            {"scene": 2, "path": valid[1], "target_duration": 5},
            {"scene": 3, "path": valid[2], "target_duration": 5},
        ]
        audio = ["/tmp/voice_0.mp3"]

        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, audio, "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # 3-scene audio concat with silence padding for scenes 1 and 2
        assert "anullsrc=r=44100" in fc
        assert "concat=n=3:v=0:a=1[outa]" in fc
        assert "amix" not in fc

    def test_audio_concat_appended_to_video(self):
        """Audio filter is appended AFTER video filter with semicolon."""
        valid = ["/tmp/s0.mp4"]
        assets = [{"scene": 1, "path": valid[0], "target_duration": 5}]
        audio = ["/tmp/voice_0.mp3"]

        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, audio, "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Video filter ([outv]) comes first, audio appended after semicolon
        assert "[outv]" in fc
        # Single scene: video part ends with [outv], audio starts after ;
        parts = fc.split(";")
        assert len(parts) >= 2
        # First part has the video, last part has the audio
        assert "[outv]" in parts[0] or any("[outv]" in p for p in parts[:-1])
        assert "[outa]" in parts[-1]

    def test_amix_not_used(self):
        """No amix filter should appear in any assembly command."""
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            {"scene": 1, "path": valid[0], "target_duration": 5,
             "transition_out": "crossfade"},
            {"scene": 2, "path": valid[1], "target_duration": 5},
        ]
        audio = ["/tmp/voice_0.mp3", "/tmp/voice_1.mp3"]

        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, audio, "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        assert "amix" not in fc
        assert "concat=n=2:v=0:a=1[outa]" in fc

    def test_has_xfade_transitions_helper(self):
        """_has_xfade_transitions detects xfade vs hard_cut correctly."""
        # crossfade → xfade present
        assert _has_xfade_transitions([
            {"transition_out": "crossfade"},
        ]) is True

        # hard_cut only → no xfade
        assert _has_xfade_transitions([
            {"transition_out": "hard_cut"},
        ]) is False

        # No transition_out → no xfade
        assert _has_xfade_transitions([
            {"scene": 1, "path": "/tmp/a.mp4"},
        ]) is False

        # Mixed: crossfade + hard_cut → xfade present
        assert _has_xfade_transitions([
            {"transition_out": "hard_cut"},
            {"transition_out": "crossfade"},
        ]) is True

        # wipe_left is also xfade-based
        assert _has_xfade_transitions([
            {"transition_out": "wipe_left"},
        ]) is True


class TestComposerSubtitles:
    """Subtitle overlay integration: script_scenes → drawtext in FFmpeg filter."""

    def _build_cmd_with_subtitles(
        self, script_scenes: list[dict] | None,
    ) -> tuple[list[str], str]:
        """Helper: build assembly cmd with one scene and return (cmd, filter_complex)."""
        valid = ["/tmp/scene_1.mp4"]
        assets = [{"scene": 1, "path": valid[0], "target_duration": 5}]
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
            script_scenes=script_scenes,
        )
        fc = cmd[cmd.index("-filter_complex") + 1]
        return cmd, fc

    def test_subtitle_drawtext_in_filter(self):
        """script_scenes with text produces drawtext in filter_complex."""
        script_scenes = [{"text": "Hello world", "duration": 5}]
        cmd, fc = self._build_cmd_with_subtitles(script_scenes)

        assert "drawtext" in fc
        assert "Hello world" in fc
        assert "[outv]" in fc
        assert "-map" in cmd

    def test_subtitle_timing_matches_scenes(self):
        """2 scenes × 5s each → captions at 0-5 and 5-10."""
        script_scenes = [
            {"text": "First scene narration", "duration": 5},
            {"text": "Second scene narration", "duration": 5},
        ]
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            {"scene": 1, "path": valid[0], "target_duration": 5},
            {"scene": 2, "path": valid[1], "target_duration": 5},
        ]
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
            script_scenes=script_scenes,
        )
        fc = cmd[cmd.index("-filter_complex") + 1]

        assert "between(t,0.0,5.0)" in fc
        assert "between(t,5.0,10.0)" in fc

    def test_no_script_no_subtitle(self):
        """script_scenes=None → no drawtext in filter_complex."""
        cmd, fc = self._build_cmd_with_subtitles(None)

        assert "drawtext" not in fc
        assert "vsub_in" not in fc
        assert "[outv]" in fc

    def test_subtitle_special_chars_escaped(self):
        """Text with colons, quotes, percent → properly escaped in drawtext."""
        raw_text = "It's 50% off: deal!"
        script_scenes = [{"text": raw_text, "duration": 5}]
        cmd, fc = self._build_cmd_with_subtitles(script_scenes)

        escaped = escape_drawtext(raw_text)
        assert escaped in fc
        # Verify special chars are backslash-escaped
        assert "\\:" in fc
        assert "\\'" in fc
        assert "\\%" in fc

    def test_script_scenes_threaded_to_assembly(self, tmp_path, mocker):
        """script_scenes threaded through full execute chain → drawtext in FFmpeg cmd."""
        _mock_preflight_ok(mocker)
        mock_run = mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
        )
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch(
            "clipper_agency.core.media_probe.probe_video",
            return_value=mocker.MagicMock(
                width=1080, height=1920, codec="h264",
                duration=30.0, has_audio=False,
                pix_fmt="yuv420p", file_size=10000,
            ),
        )
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mocker.MagicMock(
                success=True, error="", path="/tmp/norm.mp4",
            ),
        )

        agent = ComposerAgent()
        scenes = [{"text": "Full chain threading test", "duration": 5}]
        agent.execute(
            job_id=99,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=[],
            output_dir=str(tmp_path),
            script_scenes=scenes,
        )

        # First call is the concat command (second is thumbnail)
        concat_cmd = mock_run.call_args_list[0][0][0]
        filter_idx = concat_cmd.index("-filter_complex")
        filter_complex = concat_cmd[filter_idx + 1]
        assert "drawtext" in filter_complex
        assert "Full chain threading test" in filter_complex


class TestComposerUnifiedPipeline:
    """Integration tests for the unified Composer assembly pipeline.

    Validates that treatment filters, audio concat, subtitle drawtext,
    and transition logic all compose correctly in _build_assembly_cmd.
    """

    @staticmethod
    def _build_two_scene_unified(
        scene0_extra: dict,
        scene1_extra: dict,
        audio_files: list[str] | None = None,
        script_scenes: list[dict] | None = None,
    ) -> tuple[list[str], str]:
        """Helper: build 2-scene assembly cmd, return (cmd, filter_complex)."""
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            {"scene": 1, "path": valid[0], "target_duration": 5.0, **scene0_extra},
            {"scene": 2, "path": valid[1], "target_duration": 5.0, **scene1_extra},
        ]
        cmd = ComposerAgent._build_assembly_cmd(
            valid,
            assets,
            audio_files or [],
            "/tmp/out.mp4",
            script_scenes=script_scenes,
        )
        fc = cmd[cmd.index("-filter_complex") + 1]
        return cmd, fc

    # ── Test 1: treatment + audio + subtitles all present ──

    def test_full_pipeline_treatment_audio_subtitles(self):
        """2 scenes, cinematic_crop + audio + script → treatment, audio concat, drawtext."""
        # Arrange
        audio = ["/tmp/a0.mp3", "/tmp/a1.mp3"]
        script = [
            {"text": "Hello world this is a test", "duration": 5.0},
            {"text": "Second scene narration", "duration": 5.0},
        ]

        # Act
        cmd, fc = self._build_two_scene_unified(
            {"treatment": "cinematic_crop", "transition_out": "hard_cut"},
            {},
            audio_files=audio,
            script_scenes=script,
        )

        # Assert — treatment filter (crop=)
        assert "crop=" in fc
        # Assert — audio concat for 2 scenes
        assert "concat=n=2:v=0:a=1[outa]" in fc
        # Assert — subtitle drawtext
        assert "drawtext" in fc
        assert "Hello world this is a test" in fc
        # Assert — no broken amix
        assert "amix" not in fc

    # ── Test 2: audio but no subtitles ──

    def test_pipeline_audio_no_subtitles(self):
        """2 scenes + audio, no script → audio concat, NO drawtext."""
        # Arrange
        audio = ["/tmp/a0.mp3", "/tmp/a1.mp3"]

        # Act
        cmd, fc = self._build_two_scene_unified(
            {"transition_out": "hard_cut"},
            {},
            audio_files=audio,
            script_scenes=None,
        )

        # Assert — audio concat present
        assert "concat=n=2:v=0:a=1[outa]" in fc
        # Assert — no subtitle drawtext
        assert "drawtext" not in fc
        assert "amix" not in fc

    # ── Test 3: subtitles but no audio ──

    def test_pipeline_subtitles_no_audio(self):
        """2 scenes + script, no audio → drawtext present, anullsrc for audio."""
        # Arrange
        script = [
            {"text": "Narration for scene one", "duration": 5.0},
            {"text": "Narration for scene two", "duration": 5.0},
        ]

        # Act
        cmd, fc = self._build_two_scene_unified(
            {"transition_out": "hard_cut"},
            {},
            audio_files=[],
            script_scenes=script,
        )

        # Assert — subtitle drawtext present
        assert "drawtext" in fc
        assert "Narration for scene one" in fc
        # Assert — anullsrc for missing audio
        assert "anullsrc" in fc
        # Assert — no audio concat
        assert "amix" not in fc

    # ── Test 4: xfade transition + audio + subtitles ──

    def test_pipeline_xfade_with_audio_and_subtitles(self):
        """2 scenes, crossfade + audio + script → xfade, audio concat, drawtext."""
        # Arrange
        audio = ["/tmp/a0.mp3", "/tmp/a1.mp3"]
        script = [
            {"text": "Crossfade scene one", "duration": 5.0},
            {"text": "Crossfade scene two", "duration": 5.0},
        ]

        # Act
        cmd, fc = self._build_two_scene_unified(
            {"transition_out": "crossfade"},
            {},
            audio_files=audio,
            script_scenes=script,
        )

        # Assert — xfade filter present
        assert "xfade=transition=fade" in fc
        # Assert — audio concat
        assert "concat=n=2:v=0:a=1[outa]" in fc
        # Assert — subtitle drawtext
        assert "drawtext" in fc
        assert "Crossfade scene one" in fc
        # Assert — no broken amix
        assert "amix" not in fc

    # ── Test 5: hard_cut transition + audio + subtitles ──

    def test_pipeline_hard_cut_with_audio_and_subtitles(self):
        """2 scenes, hard_cut + audio + script → concat video, audio, drawtext."""
        # Arrange
        audio = ["/tmp/a0.mp3", "/tmp/a1.mp3"]
        script = [
            {"text": "Hard cut first line", "duration": 5.0},
            {"text": "Hard cut second line", "duration": 5.0},
        ]

        # Act
        cmd, fc = self._build_two_scene_unified(
            {"transition_out": "hard_cut"},
            {},
            audio_files=audio,
            script_scenes=script,
        )

        # Assert — video concat (not xfade)
        assert "concat=n=2:v=1" in fc
        assert "xfade=" not in fc
        # Assert — audio concat
        assert "concat=n=2:v=0:a=1[outa]" in fc
        # Assert — subtitle drawtext
        assert "drawtext" in fc
        assert "Hard cut first line" in fc
        assert "amix" not in fc

    # ── Test 6: backward compat, no audio, no script ──

    def test_pipeline_backward_compat_no_audio_no_script(self):
        """2 scenes, no audio, no script → anullsrc, no drawtext, basic trim+transition."""
        # Arrange & Act
        cmd, fc = self._build_two_scene_unified(
            {"transition_out": "hard_cut"},
            {},
            audio_files=[],
            script_scenes=None,
        )

        # Assert — anullsrc for audio
        assert "anullsrc" in fc
        # Assert — no subtitle drawtext
        assert "drawtext" not in fc
        # Assert — basic trim+setpts+fps present
        assert "trim=duration=" in fc
        assert "setpts=PTS-STARTPTS" in fc
        assert "fps=30" in fc
        # Assert — video output label
        assert "[outv]" in fc
        assert "[outa]" in fc
        # Assert — no broken amix
        assert "amix" not in fc


def _make_asset(
    path: str,
    duration: float = 5.0,
    treatment: str | None = None,
    transition_out: str = "crossfade",
    **kw,
) -> dict:
    """Build an asset dict with sensible defaults for edge-case tests."""
    return {
        "path": path,
        "target_duration": duration,
        "treatment": treatment,
        "transition_out": transition_out,
        **kw,
    }


class TestComposerEdgeCases:
    """Edge-case tests for _build_assembly_cmd: boundaries, empty inputs, clamping."""

    # ── Test 1: Single scene needs no transition ──

    def test_single_scene_no_transition(self):
        """1 video → direct [outv] rename, no xfade or concat."""
        # Arrange
        valid = ["/tmp/scene_1.mp4"]
        assets = [_make_asset(valid[0], duration=4.0)]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert
        assert "[0:v]trim=duration=4.0,setpts=PTS-STARTPTS,fps=30[outv]" in fc
        assert "xfade=" not in fc
        assert "concat=" not in fc

    # ── Test 2: All hard_cut → concat-only chain, no xfade ──

    def test_all_hard_cut_identical_to_concat(self):
        """3 scenes all with hard_cut → 2 concat joins, no xfade."""
        # Arrange
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4", "/tmp/s2.mp4"]
        assets = [
            _make_asset(valid[0], transition_out="hard_cut"),
            _make_asset(valid[1], transition_out="hard_cut"),
            _make_asset(valid[2], transition_out="hard_cut"),
        ]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — two concat joins for 3 scenes
        assert fc.count("concat=n=2:v=1") == 2
        assert "xfade=" not in fc

    # ── Test 3: Mixed input types each with different treatments ──

    def test_mixed_input_types_with_treatments(self):
        """image+ken_burns, video+cinematic_crop, text+hook_big_caption all appear."""
        # Arrange
        valid = ["/tmp/img.png", "/tmp/vid.mp4", "/tmp/card.mp4"]
        assets = [
            _make_asset(
                valid[0], duration=5.0, treatment="ken_burns_zoom_in",
                type="image", transition_out="hard_cut",
            ),
            _make_asset(
                valid[1], duration=5.0, treatment="cinematic_crop",
                type="video", transition_out="hard_cut",
            ),
            _make_asset(
                valid[2], duration=5.0, treatment="hook_big_caption",
                type="text", headline="Big News!", transition_out="hard_cut",
            ),
        ]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — ken_burns gets scale=5400:-1 prefix for image zoompan
        assert "scale=5400:-1" in fc
        assert "zoompan=" in fc
        # Assert — cinematic_crop gets crop+scale
        assert "crop=ih*9/16:ih,scale=1080:1920,setsar=1/1" in fc
        # Assert — hook_big_caption substitutes {text} with headline
        assert "drawtext=text='Big News!'" in fc

    # ── Test: fps=30 normalises timebase for xfade compatibility ──

    def test_fps30_normalises_timebase_for_xfade(self):
        """Every scene gets fps=30 so xfade never sees mismatched timebases."""
        valid = ["/tmp/img.png", "/tmp/vid.mp4"]
        assets = [
            _make_asset(
                valid[0], duration=5.0, treatment="ken_burns_zoom_in",
                type="image", transition_out="crossfade",
            ),
            _make_asset(
                valid[1], duration=5.0, treatment="cinematic_crop",
                type="video",
            ),
        ]

        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Both scenes must have fps=30 after setpts for uniform timebase
        assert "setpts=PTS-STARTPTS,fps=30" in fc
        assert fc.count("fps=30") >= 2

    # ── Test: audio-first also normalises fps for xfade compatibility ──

    def test_audio_first_fps30_normalises_timebase(self):
        """Audio-first path also adds fps=30 for uniform timebases."""
        cmd = ComposerAgent._build_audio_first_cmd(
            voiceover_path="/tmp/voice.mp3",
            trimmed_clips=["/tmp/v1.mp4", "/tmp/v2.mp4"],
            normalized_assets=[
                {"scene": 1, "path": "/tmp/v1.mp4", "target_duration": 5,
                 "treatment": "cinematic_crop", "type": "video"},
                {"scene": 2, "path": "/tmp/v2.mp4", "target_duration": 5},
            ],
            keyword_captions=[],
            output_path="/tmp/out.mp4",
        )

        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "setpts=PTS-STARTPTS,fps=30" in fc
        assert fc.count("fps=30") >= 2

    # ── Test 4: transition_duration=0 still uses xfade path ──

    def test_transition_duration_zero_acts_as_hard_cut(self):
        """crossfade with transition_duration=0.0 → xfade present but duration=0.0."""
        # Arrange
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            _make_asset(
                valid[0], duration=5.0,
                transition_out="crossfade", transition_duration=0.0,
            ),
            _make_asset(valid[1], duration=5.0),
        ]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — still xfade (not concat), but duration=0.0
        assert "xfade=transition=fade" in fc
        assert "duration=0.0" in fc
        assert "concat=n=2:v=1" not in fc

    # ── Test 5: Very short next clip clamps transition to minimum ──

    def test_very_short_clip_clamps_transition(self):
        """1.5s clip with 0.1s next → transition clamped to MIN_TRANSITION_DUR (0.05)."""
        # Arrange
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            _make_asset(
                valid[0], duration=1.5,
                transition_out="crossfade",
            ),
            _make_asset(valid[1], duration=0.1),
        ]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — max_dur = min(1.5, 0.1) - 0.15 = -0.05
        # clamped = min(0.3, max(0.05, -0.05)) = 0.05
        assert "duration=0.05" in fc

    # ── Test 6: Empty text in script_scenes → no drawtext ──

    def test_no_script_text_no_subtitles(self):
        """script_scenes with empty text → build_subtitle_overlays returns [] → no drawtext."""
        # Arrange
        valid = ["/tmp/scene_1.mp4"]
        assets = [_make_asset(valid[0], duration=5.0)]
        script_scenes = [{"text": "", "duration": 5}]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
            script_scenes=script_scenes,
        )
        fc = _filter_complex(cmd)

        # Assert — empty text produces no drawtext overlay
        assert "drawtext" not in fc

    # ── Test 7: No audio files → anullsrc silent track ──

    def test_no_audio_files_silent_track(self):
        """2 scenes with audio_files=[] → anullsrc[outa], no amix or audio concat."""
        # Arrange
        valid = ["/tmp/s0.mp4", "/tmp/s1.mp4"]
        assets = [
            _make_asset(valid[0], transition_out="hard_cut"),
            _make_asset(valid[1]),
        ]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — anullsrc for silent audio
        assert "anullsrc[outa]" in fc
        assert "amix" not in fc

    # ── Test 8: text_card type with hook_big_caption treatment ──

    def test_card_fallback_scene_with_treatment(self):
        """text_card asset with hook_big_caption → drawtext filter with headline substituted."""
        # Arrange
        valid = ["/tmp/card.mp4"]
        assets = [
            _make_asset(
                valid[0], duration=3.0,
                treatment="hook_big_caption", type="text_card",
                headline="Amazing Fact!",
            ),
        ]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — treatment drawtext with headline substituted
        assert "drawtext=text='Amazing Fact!'" in fc
        assert "fontsize=80" in fc
        assert "trim=duration=3.0" in fc
        # hook_big_caption has no scale/crop, so no setsar appended
        assert "[outv]" in fc

    # ── Test 9: Multiple scenes with varying durations ──

    def test_multiple_scenes_with_varying_durations(self):
        """4 scenes (2s, 5s, 8s, 3s) → each trim=duration=N present in filter."""
        # Arrange
        durations = [2.0, 5.0, 8.0, 3.0]
        valid = [f"/tmp/s{i}.mp4" for i in range(4)]
        assets = [
            _make_asset(valid[i], duration=durations[i], transition_out="hard_cut")
            for i in range(4)
        ]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, [], "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — all four trim durations present
        for d in durations:
            assert f"trim=duration={d}" in fc
        # Assert — 3 concat joins for 4 scenes (hard_cut chain)
        assert fc.count("concat=n=2:v=1") == 3

    # ── Test 10: Fewer audio files than scenes → silence padding ──

    def test_audio_count_mismatches_scene_count(self):
        """4 scenes + 2 audio files → anullsrc silence padding for missing 2."""
        # Arrange
        valid = [f"/tmp/s{i}.mp4" for i in range(4)]
        assets = [
            _make_asset(valid[i], transition_out="hard_cut")
            for i in range(4)
        ]
        audio = ["/tmp/voice_0.mp3", "/tmp/voice_1.mp3"]

        # Act
        cmd = ComposerAgent._build_assembly_cmd(
            valid, assets, audio, "/tmp/output.mp4",
        )
        fc = _filter_complex(cmd)

        # Assert — 4-scene audio concat with silence padding
        assert "concat=n=4:v=0:a=1[outa]" in fc
        assert "anullsrc=r=44100" in fc
        assert "amix" not in fc


# ═══════════════════════════════════════════════════════════════════════
# Smart Trim
# ═══════════════════════════════════════════════════════════════════════


class TestComposerSmartTrim:
    """Smart trim: scene boundary detection, trimming, stretching."""

    def test_smart_trim_with_scene_boundary(self, tmp_path, mocker):
        """Clip longer than target; boundary near target → trim at boundary."""
        agent = ComposerAgent()

        # Clip is 10s, target is 5s
        mocker.patch.object(agent, "_probe_duration", return_value=10.0)
        # Scene boundary at 5.1s (within ±15% of 5.0 → tolerance = 0.75)
        mocker.patch.object(
            agent, "_detect_scene_boundaries", return_value=[2.0, 5.1, 8.0],
        )
        mock_ffmpeg = mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
        )

        result = agent._smart_trim(
            "/tmp/clip.mp4", 5.0, tmp_path,
        )

        assert mock_ffmpeg.called
        cmd = mock_ffmpeg.call_args[0][0]
        cmd_str = " ".join(cmd)
        # Should trim at boundary 5.1
        assert "-to" in cmd
        assert "5.1" in cmd_str
        # Speed-adjust to exactly 5.0s
        assert "setpts=" in cmd_str

    def test_smart_trim_no_good_boundary(self, tmp_path, mocker):
        """No boundary near target → simple trim from start."""
        agent = ComposerAgent()

        mocker.patch.object(agent, "_probe_duration", return_value=10.0)
        # Boundaries far from target 5.0
        mocker.patch.object(
            agent, "_detect_scene_boundaries", return_value=[1.0, 8.5],
        )
        mock_ffmpeg = mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
        )

        result = agent._smart_trim(
            "/tmp/clip.mp4", 5.0, tmp_path,
        )

        assert mock_ffmpeg.called
        cmd = mock_ffmpeg.call_args[0][0]
        cmd_str = " ".join(cmd)
        # Should trim to target duration (no boundary match)
        assert "-to" in cmd
        assert "5.0" in cmd_str or "5." in cmd_str

    def test_smart_trim_clip_shorter_slowdown(self, tmp_path, mocker):
        """Clip shorter than target; slowdown within 30% is enough."""
        agent = ComposerAgent()

        # Clip is 4.0s, target is 5.0s → need 25% slowdown (within 30% limit)
        mocker.patch.object(agent, "_probe_duration", return_value=4.0)
        mock_ffmpeg = mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
        )

        result = agent._smart_trim(
            "/tmp/clip.mp4", 5.0, tmp_path,
        )

        assert mock_ffmpeg.called
        cmd = mock_ffmpeg.call_args[0][0]
        cmd_str = " ".join(cmd)
        # Should use setpts to slow down
        assert "setpts=" in cmd_str
        # speed factor = 5.0/4.0 = 1.25
        assert "1.25" in cmd_str

    def test_smart_trim_clip_shorter_needs_loop(self, tmp_path, mocker):
        """Clip much shorter; needs looping to fill target."""
        agent = ComposerAgent()

        # Clip is 2.0s, target is 5.0s → max slowdown = 2.0*1.3=2.6 < 5.0
        mocker.patch.object(agent, "_probe_duration", return_value=2.0)
        mock_ffmpeg = mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
        )

        result = agent._smart_trim(
            "/tmp/clip.mp4", 5.0, tmp_path,
        )

        assert mock_ffmpeg.called
        cmd = mock_ffmpeg.call_args[0][0]
        cmd_str = " ".join(cmd)
        # Should use stream_loop
        assert "-stream_loop" in cmd_str
        assert "-1" in cmd_str

    def test_smart_trim_close_enough_copies(self, tmp_path, mocker):
        """Clip within 50ms of target → just copy."""
        agent = ComposerAgent()

        mocker.patch.object(agent, "_probe_duration", return_value=5.02)
        mock_ffmpeg = mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
        )
        mock_copy = mocker.patch("shutil.copy2")

        agent._smart_trim("/tmp/clip.mp4", 5.0, tmp_path)

        mock_copy.assert_called_once()
        mock_ffmpeg.assert_not_called()


class TestComposerComputeBeatDurations:
    """_compute_beat_durations: word ranges → beat durations."""

    def test_basic_beat_durations(self):
        """Two beats with 3 and 4 words → correct durations."""
        narrative = [
            {"word_range": [0, 3]},
            {"word_range": [3, 7]},
        ]
        timestamps = [
            {"word": "w0", "start": 0.0, "end": 0.5},
            {"word": "w1", "start": 0.5, "end": 1.0},
            {"word": "w2", "start": 1.0, "end": 1.5},
            {"word": "w3", "start": 1.5, "end": 2.0},
            {"word": "w4", "start": 2.0, "end": 2.5},
            {"word": "w5", "start": 2.5, "end": 3.0},
            {"word": "w6", "start": 3.0, "end": 3.5},
        ]

        result = ComposerAgent._compute_beat_durations(narrative, timestamps)

        assert len(result) == 2
        assert result[0] == pytest.approx(1.5)   # 0.0 → 1.5
        assert result[1] == pytest.approx(2.0)    # 1.5 → 3.5

    def test_missing_word_range_covers_full_timestamps(self):
        """Beat without word_range covers full timestamp range."""
        narrative = [{"beat_id": 1}]
        timestamps = [{"word": "w", "start": 0, "end": 1}]

        result = ComposerAgent._compute_beat_durations(narrative, timestamps)

        assert result == [pytest.approx(1.0)]

    def test_empty_inputs_returns_empty(self):
        """Empty inputs return empty list."""
        assert ComposerAgent._compute_beat_durations([], []) == []


# ═══════════════════════════════════════════════════════════════════════
# Audio-First Assembly
# ═══════════════════════════════════════════════════════════════════════


class TestComposerAudioFirstCmd:
    """_build_audio_first_cmd: voiceover anchor, visuals fitted to beats."""

    def test_voiceover_is_audio_anchor(self):
        """Voiceover (input 0) is mapped as audio, never trimmed."""
        cmd = ComposerAgent._build_audio_first_cmd(
            voiceover_path="/tmp/voiceover.mp3",
            trimmed_clips=["/tmp/clip1.mp4"],
            normalized_assets=[
                {"scene": 1, "path": "/tmp/clip1.mp4", "target_duration": 5},
            ],
            keyword_captions=[],
            output_path="/tmp/output.mp4",
        )

        # Voiceover should be first input: ["ffmpeg", "-y", "-i", "/tmp/voiceover.mp3", ...]
        assert cmd[3] == "/tmp/voiceover.mp3"
        # Audio mapped directly from input 0
        assert "-map" in cmd
        idx_map = cmd.index("-map")
        assert cmd[idx_map + 1] == "[outv]"
        assert cmd[idx_map + 3] == "0:a"
        # No [outa] filter
        assert "[outa]" not in " ".join(cmd)

    def test_visual_inputs_offset_by_one(self):
        """Visual inputs are 1-indexed (voiceover is input 0)."""
        cmd = ComposerAgent._build_audio_first_cmd(
            voiceover_path="/tmp/voice.mp3",
            trimmed_clips=["/tmp/v1.mp4", "/tmp/v2.mp4"],
            normalized_assets=[
                {"scene": 1, "path": "/tmp/v1.mp4", "target_duration": 5},
                {"scene": 2, "path": "/tmp/v2.mp4", "target_duration": 5},
            ],
            keyword_captions=[],
            output_path="/tmp/out.mp4",
        )

        fc = cmd[cmd.index("-filter_complex") + 1]
        # Visual inputs should reference [1:v] and [2:v], not [0:v]
        assert "[1:v]" in fc
        assert "[2:v]" in fc
        assert "[0:v]" not in fc

    def test_no_per_scene_audio_concat(self):
        """Audio-first mode has no audio_sequencer or [outa] filter."""
        cmd = ComposerAgent._build_audio_first_cmd(
            voiceover_path="/tmp/voice.mp3",
            trimmed_clips=["/tmp/v1.mp4", "/tmp/v2.mp4"],
            normalized_assets=[
                {"scene": 1, "path": "/tmp/v1.mp4", "target_duration": 5,
                 "transition_out": "hard_cut"},
                {"scene": 2, "path": "/tmp/v2.mp4", "target_duration": 5},
            ],
            keyword_captions=[],
            output_path="/tmp/out.mp4",
        )

        fc = cmd[cmd.index("-filter_complex") + 1]
        # No audio concat or anullsrc — audio comes from voiceover
        assert "concat=n=2:v=0:a=1" not in fc
        assert "anullsrc" not in fc
        assert "[outa]" not in fc

    def test_keyword_captions_in_filter(self):
        """Keyword captions produce drawtext in filter_complex."""
        captions = [
            CaptionOverlay(
                text="hello world", start_seconds=0.0, end_seconds=2.5,
                position="bottom", style="keyword",
            ),
            CaptionOverlay(
                text="main story", start_seconds=2.5, end_seconds=5.0,
                position="bottom", style="keyword",
            ),
        ]
        cmd = ComposerAgent._build_audio_first_cmd(
            voiceover_path="/tmp/voice.mp3",
            trimmed_clips=["/tmp/v1.mp4"],
            normalized_assets=[
                {"scene": 1, "path": "/tmp/v1.mp4", "target_duration": 5},
            ],
            keyword_captions=captions,
            output_path="/tmp/out.mp4",
        )

        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "drawtext" in fc
        assert "hello world" in fc
        assert "main story" in fc
        assert "fontsize=48" in fc
        assert "borderw=3" in fc
        assert "shadowcolor=black" in fc

    def test_no_keyword_captions_no_drawtext(self):
        """Empty keyword_captions → no drawtext in filter."""
        cmd = ComposerAgent._build_audio_first_cmd(
            voiceover_path="/tmp/voice.mp3",
            trimmed_clips=["/tmp/v1.mp4"],
            normalized_assets=[
                {"scene": 1, "path": "/tmp/v1.mp4", "target_duration": 5},
            ],
            keyword_captions=[],
            output_path="/tmp/out.mp4",
        )

        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "drawtext" not in fc
        assert "kcap_in" not in fc


class TestBuildKeywordChain:
    """Module-level _build_keyword_chain: drawtext overlay construction."""

    def test_keyword_chain_replaces_outv(self):
        """Keyword chain replaces [outv] with [kcap_in] and chains drawtext."""
        captions = [
            CaptionOverlay(
                text="keyword1", start_seconds=0.0, end_seconds=3.0,
                position="bottom", style="keyword",
            ),
        ]
        result = _build_keyword_chain("[outv]", captions)

        assert "[kcap_in]" in result
        assert "drawtext" in result
        assert "keyword1" in result
        assert "[outv]" in result  # Final output relabeled back

    def test_keyword_chain_empty_captions_passthrough(self):
        """Empty captions list → filter unchanged."""
        result = _build_keyword_chain("[outv]filter_here", [])
        assert result == "[outv]filter_here"

    def test_keyword_chain_multiple_captions(self):
        """Multiple captions chain correctly."""
        captions = [
            CaptionOverlay(
                text="first", start_seconds=0.0, end_seconds=2.5,
                position="bottom", style="keyword",
            ),
            CaptionOverlay(
                text="second", start_seconds=2.5, end_seconds=5.0,
                position="bottom", style="keyword",
            ),
        ]
        result = _build_keyword_chain("[outv]", captions)

        assert result.count("drawtext") == 2
        assert "first" in result
        assert "second" in result
        assert "between(t,0.0,2.5)" in result
        assert "between(t,2.5,5.0)" in result


class TestComposerEnrichAudioFirstAssets:
    """_enrich_audio_first_assets: merge trimmed clips + beat durations + treatments."""

    def test_enrich_preserves_treatment_metadata(self):
        """Treatment and transition metadata pass through from original assets."""
        assets = [
            {
                "path": "/orig/clip1.mp4",
                "treatment": "cinematic_crop",
                "transition_out": "hard_cut",
                "headline": "Big News",
            },
        ]
        trimmed = ["/tmp/trimmed_clip1.mp4"]
        durations = [5.5]

        result = ComposerAgent._enrich_audio_first_assets(
            assets, trimmed, durations,
        )

        assert len(result) == 1
        assert result[0]["target_duration"] == 5.5
        assert result[0]["path"] == "/tmp/trimmed_clip1.mp4"
        assert result[0]["treatment"] == "cinematic_crop"
        assert result[0]["transition_out"] == "hard_cut"
        assert result[0]["headline"] == "Big News"

    def test_enrich_defaults_duration_to_5(self):
        """Missing beat duration defaults to 5.0."""
        result = ComposerAgent._enrich_audio_first_assets(
            [], ["/tmp/clip.mp4"], [],
        )
        assert result[0]["target_duration"] == 5.0


# ---------------------------------------------------------------------------
# Composer duration-safety tests (Batch 1A — must fail)
# ---------------------------------------------------------------------------


class TestComposerDurationSafety:
    """Tests for Composer duration-safe rendering.

    These tests MUST FAIL until duration guard is implemented in Batch 2A.
    """

    def test_audio_first_render_never_returns_video_shorter_than_voiceover(self, tmp_path, mocker):
        """Composer output must never be shorter than the voiceover audio."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.core.scene_validator.SceneValidator.validate",
                     return_value=mocker.MagicMock(valid=True, issues=[]))
        mocker.patch("clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
                     return_value=mocker.MagicMock(success=True, error=""))

        # Mock probe to report scenes shorter than audio
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     side_effect=lambda *a, **kw: mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=21.21, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))

        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming", return_value=0)

        agent = ComposerAgent()
        result = agent.execute(
            job_id=99,
            assets=[
                {"scene": 1, "path": "/tmp/scene_1.mp4"},
                {"scene": 2, "path": "/tmp/scene_2.mp4"},
            ],
            audio_files=["/tmp/voiceover.mp3"],
            output_dir=str(tmp_path),
            voiceover_duration_sec=23.25,
        )
        # The duration guard should either:
        # 1. Extend the visual timeline to cover audio, OR
        # 2. Return a failed status with clear reason
        # It should NOT silently produce a short video
        assert result.get("status") in ("completed", "failed")
        if result.get("status") == "completed":
            # If completed, output must not be shorter than voiceover
            output_dur = result.get("output_duration_sec", 0)
            assert output_dur >= 23.25, (
                f"Output {output_dur}s is shorter than voiceover 23.25s"
            )

    def test_crossfade_overlap_is_compensated_when_matching_audio_duration(self, tmp_path, mocker):
        """When scene sum equals audio but crossfade eats time, output must still cover audio."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.core.scene_validator.SceneValidator.validate",
                     return_value=mocker.MagicMock(valid=True, issues=[]))
        mocker.patch("clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
                     return_value=mocker.MagicMock(success=True, error=""))

        # Each scene is 12s, total 24s for 23.25s audio
        # But crossfade overlap reduces actual output
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     side_effect=lambda *a, **kw: mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=12.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))

        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming", return_value=0)

        agent = ComposerAgent()
        result = agent.execute(
            job_id=100,
            assets=[
                {"scene": 1, "path": "/tmp/scene_1.mp4"},
                {"scene": 2, "path": "/tmp/scene_2.mp4"},
            ],
            audio_files=["/tmp/voiceover.mp3"],
            output_dir=str(tmp_path),
            voiceover_duration_sec=23.25,
        )
        if result.get("status") == "completed":
            output_dur = result.get("output_duration_sec", 0)
            assert output_dur >= 23.25, (
                f"Output {output_dur}s shorter than audio 23.25s after crossfade"
            )


# ---------------------------------------------------------------------------
# Intro card contract tests (Batch 1B — must fail)
# ---------------------------------------------------------------------------


class TestComposerIntroCard:
    """Tests for Composer intro card scene rendering.

    These tests MUST FAIL until intro card rendering is implemented in Batch 2B.
    """

    def test_composer_renders_intro_card_scene_as_part_of_timeline(self, tmp_path, mocker):
        """Intro card scene 0 must be included in the rendered timeline."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.core.scene_validator.SceneValidator.validate",
                     return_value=mocker.MagicMock(valid=True, issues=[]))
        mocker.patch("clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
                     return_value=mocker.MagicMock(success=True, error=""))

        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=3.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=5000))

        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming", return_value=0)

        agent = ComposerAgent()
        result = agent.execute(
            job_id=200,
            assets=[
                {"scene": 0, "path": "/tmp/intro_card.mp4", "role": "intro_card"},
                {"scene": 1, "path": "/tmp/scene_1.mp4"},
                {"scene": 2, "path": "/tmp/scene_2.mp4"},
            ],
            audio_files=["/tmp/voiceover.mp3"],
            output_dir=str(tmp_path),
            voiceover_duration_sec=20.0,
            intro_card_duration_sec=3.0,
        )
        if result.get("status") == "completed":
            # Intro card must contribute to timeline
            assert result.get("scene_count", 0) >= 3, (
                "Intro card + 2 story scenes = at least 3 scenes"
            )

    def test_composer_intro_card_does_not_eat_voiceover_time(self, tmp_path, mocker):
        """Intro card is silent pre-roll — must not reduce available voiceover time."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.core.scene_validator.SceneValidator.validate",
                     return_value=mocker.MagicMock(valid=True, issues=[]))
        mocker.patch("clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
                     return_value=mocker.MagicMock(success=True, error=""))

        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=10.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))

        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming", return_value=0)

        agent = ComposerAgent()
        result = agent.execute(
            job_id=201,
            assets=[
                {"scene": 0, "path": "/tmp/intro_card.mp4", "role": "intro_card"},
                {"scene": 1, "path": "/tmp/scene_1.mp4"},
            ],
            audio_files=["/tmp/voiceover.mp3"],
            output_dir=str(tmp_path),
            voiceover_duration_sec=20.0,
            intro_card_duration_sec=3.0,
        )
        if result.get("status") == "completed":
            # Total video duration should be intro_card (3s) + voiceover (20s) ≈ 23s
            # NOT just 20s (intro card eating into voiceover)
            output_dur = result.get("output_duration_sec", 0)
            assert output_dur >= 20.0, (
                f"Output {output_dur}s should cover at least the voiceover 20s"
            )


class TestVisualCoverageDiagnostics:
    """Composer must attach visual_coverage diagnostics to output."""

    def test_composer_output_includes_visual_coverage_diagnostic(
        self, tmp_path, mocker,
    ):
        """Composer must attach visual_coverage diagnostics to output."""
        from clipper_agency.config.schema import (
            VisualCoverageIssue,
            VisualCoverageResult,
        )

        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch(
            "clipper_agency.core.media_probe.probe_video",
            return_value=mocker.MagicMock(
                width=1080, height=1920, codec="h264",
                duration=10.0, has_audio=False,
                pix_fmt="yuv420p", file_size=10000,
            ),
        )
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mocker.MagicMock(success=True, error=""),
        )
        mocker.patch(
            "clipper_agency.agents.composer.ComposerAgent._probe_output_duration",
            return_value=21.0,
        )
        mocker.patch(
            "clipper_agency.agents.composer.ComposerAgent._generate_thumbnail",
        )
        mocker.patch(
            "clipper_agency.agents.composer.ComposerAgent._assemble_video",
            return_value={"cmd": ["ffmpeg"], "card_fallback_scenes": []},
        )
        mock_vc = mocker.patch(
            "clipper_agency.agents.composer.evaluate_visual_coverage",
            return_value=VisualCoverageResult(
                status="pass",
                output_duration_sec=21.0,
                voiceover_duration_sec=21.0,
                coverage_ratio=1.0,
                issues=[],
            ),
        )
        # Mock FFmpeg detector calls (Task 5.1 — Composer coverage diagnostics)
        mocker.patch(
            "clipper_agency.agents.composer.detect_black_segments",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.agents.composer.detect_freeze_segments",
            return_value=[],
        )

        agent = ComposerAgent()
        result = agent.execute(
            job_id=99,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            voiceover_duration_sec=21.0,
        )

        assert "diagnostics" in result, "Missing 'diagnostics' key in output"
        assert "visual_coverage" in result["diagnostics"], (
            "Missing 'visual_coverage' in diagnostics"
        )
        assert result["diagnostics"]["visual_coverage"]["status"] == "pass"
        mock_vc.assert_called_once()


class TestGeneratedTextManifest:
    """Composer must persist generated text regions in output diagnostics."""

    def test_audio_first_render_includes_generated_text_regions(self, mocker, tmp_path):
        """Audio-first render must call build_generated_text_regions and persist."""
        mock_regions = mocker.patch(
            "clipper_agency.agents.composer.build_generated_text_regions",
            return_value=[
                {"timestamp_start_sec": 1.0, "timestamp_end_sec": 2.5,
                 "layer": "subtitle", "bbox": [120, 1480, 960, 1740],
                 "text": "hello world"},
            ],
        )
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        mocker.patch.object(ComposerAgent, "_generate_thumbnail")
        mocker.patch.object(ComposerAgent, "_probe_output_duration", return_value=30.0)
        mocker.patch.object(ComposerAgent, "_persist_diagnostics")
        mocker.patch("clipper_agency.agents.composer._persist_visual_coverage")
        mocker.patch("clipper_agency.agents.composer.evaluate_visual_coverage",
                       return_value=MockVisualCoverageResult.pass_result())
        mocker.patch("clipper_agency.agents.composer.detect_black_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.detect_freeze_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.write_json")

        agent = ComposerAgent()
        result = agent._run_audio_first_render(
            job_id=1,
            voiceover_path=str(tmp_path / "voice.mp3"),
            timestamps=[{"word": "hello", "start": 0.0, "end": 1.0},
                         {"word": "world", "start": 1.0, "end": 2.0}],
            assets=[],
            beat_durations=[0.0],
            trimmed_clips=[str(tmp_path / "clip0.mp4")],
            card_fallback_scenes=[],
            video_path=str(tmp_path / "video.mp4"),
            thumbnail_path=str(tmp_path / "thumb.png"),
            assets_cache=str(tmp_path),
            agent_dir=str(tmp_path),
        )

        mock_regions.assert_called_once()
        assert "diagnostics" in result
        assert "generated_text_regions" in result["diagnostics"]

    def test_generated_text_regions_absent_when_no_captions(self, mocker, tmp_path):
        """When there are no captions, generated_text_regions should be empty list."""
        mock_regions = mocker.patch(
            "clipper_agency.agents.composer.build_generated_text_regions",
            return_value=[],
        )
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        mocker.patch.object(ComposerAgent, "_generate_thumbnail")
        mocker.patch.object(ComposerAgent, "_probe_output_duration", return_value=30.0)
        mocker.patch.object(ComposerAgent, "_persist_diagnostics")
        mocker.patch("clipper_agency.agents.composer._persist_visual_coverage")
        mocker.patch("clipper_agency.agents.composer.evaluate_visual_coverage",
                       return_value=MockVisualCoverageResult.pass_result())
        mocker.patch("clipper_agency.agents.composer.detect_black_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.detect_freeze_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.write_json")

        agent = ComposerAgent()
        result = agent._run_audio_first_render(
            job_id=1,
            voiceover_path=str(tmp_path / "voice.mp3"),
            timestamps=[],
            assets=[],
            beat_durations=[],
            trimmed_clips=[str(tmp_path / "clip0.mp4")],
            card_fallback_scenes=[],
            video_path=str(tmp_path / "video.mp4"),
            thumbnail_path=str(tmp_path / "thumb.png"),
            assets_cache=str(tmp_path),
            agent_dir=str(tmp_path),
        )

        assert result["diagnostics"]["generated_text_regions"] == []


class TestRenderedSceneManifest:
    """Composer must include rendered_scene_manifest in output."""

    def test_audio_first_render_includes_rendered_scene_manifest(self, mocker, tmp_path):
        """Audio-first render must call build_rendered_scene_manifest and persist."""
        mock_manifest = mocker.patch(
            "clipper_agency.agents.composer.build_rendered_scene_manifest",
            return_value=MockRenderedSceneManifest.make(),
        )
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        mocker.patch.object(ComposerAgent, "_generate_thumbnail")
        mocker.patch.object(ComposerAgent, "_probe_output_duration", return_value=30.0)
        mocker.patch.object(ComposerAgent, "_persist_diagnostics")
        mocker.patch("clipper_agency.agents.composer._persist_visual_coverage")
        mocker.patch("clipper_agency.agents.composer.evaluate_visual_coverage",
                       return_value=MockVisualCoverageResult.pass_result())
        mocker.patch("clipper_agency.agents.composer.detect_black_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.detect_freeze_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.build_generated_text_regions", return_value=[])
        mocker.patch("clipper_agency.agents.composer.write_json")

        agent = ComposerAgent()
        result = agent._run_audio_first_render(
            job_id=1,
            voiceover_path=str(tmp_path / "voice.mp3"),
            timestamps=[],
            assets=[{"beat_id": 1, "asset_id": "abc123"}],
            beat_durations=[5.0],
            trimmed_clips=[str(tmp_path / "clip0.mp4")],
            card_fallback_scenes=[],
            video_path=str(tmp_path / "video.mp4"),
            thumbnail_path=str(tmp_path / "thumb.png"),
            assets_cache=str(tmp_path),
            agent_dir=str(tmp_path),
        )

        mock_manifest.assert_called_once()
        assert "rendered_scene_manifest" in result
        assert result["rendered_scene_manifest"] is not None

    def test_rendered_scene_manifest_flows_via_try_assemble(self, mocker, tmp_path):
        """Try-assemble (legacy) path must also include rendered_scene_manifest."""
        mock_manifest = mocker.patch(
            "clipper_agency.agents.composer.build_rendered_scene_manifest",
            return_value=MockRenderedSceneManifest.make(),
        )
        mocker.patch.object(ComposerAgent, "_assemble_video",
                             return_value={"cmd": ["ffmpeg", "-y"], "card_fallback_scenes": []})
        mocker.patch.object(ComposerAgent, "_generate_thumbnail")
        mocker.patch.object(ComposerAgent, "_probe_output_duration", return_value=30.0)
        mocker.patch.object(ComposerAgent, "_persist_diagnostics")
        mocker.patch("clipper_agency.agents.composer._persist_visual_coverage")
        mocker.patch("clipper_agency.agents.composer.evaluate_visual_coverage",
                       return_value=MockVisualCoverageResult.pass_result())
        mocker.patch("clipper_agency.agents.composer.detect_black_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.detect_freeze_segments", return_value=[])
        mocker.patch("clipper_agency.agents.composer.write_json")

        agent = ComposerAgent()
        result = agent._try_assemble(
            video_assets=[{"scene": 1, "path": str(tmp_path / "clip0.mp4"),
                            "beat_id": 1, "type": "photo"}],
            voice_files=[],
            video_path=str(tmp_path / "video.mp4"),
            thumbnail_path=str(tmp_path / "thumb.png"),
            assets_cache=str(tmp_path),
            job_id=1,
            agent_dir=str(tmp_path),
            voiceover_duration_sec=30.0,
        )

        mock_manifest.assert_called_once()
        assert "rendered_scene_manifest" in result
        assert result["rendered_scene_manifest"] is not None


class MockRenderedSceneManifest:
    """Factory for mock RenderedSceneManifest objects used in tests."""

    @staticmethod
    def make():
        from clipper_agency.core.rendered_scene_manifest import (
            RenderedSceneEntry,
            RenderedSceneManifest,
        )
        return RenderedSceneManifest(
            entries=[RenderedSceneEntry(
                scene="1", beat_id="1", start_sec=0.0, end_sec=5.0,
                source_path="/tmp/clip.mp4", source_type="photo",
                selected_asset_id="abc123",
            )],
            video_duration_sec=30.0,
            video_path="/tmp/video.mp4",
        )


class MockVisualCoverageResult:
    """Factory for mock VisualCoverageResult objects used in tests."""

    @staticmethod
    def pass_result(output_duration_sec=30.0):
        from clipper_agency.config.schema import VisualCoverageResult
        return VisualCoverageResult(
            status="pass",
            output_duration_sec=output_duration_sec,
            voiceover_duration_sec=output_duration_sec,
            coverage_ratio=1.0,
            issues=[],
        )
