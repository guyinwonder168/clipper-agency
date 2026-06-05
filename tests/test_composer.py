"""Tests for ComposerAgent artifact persistence and output naming."""

import json
from pathlib import Path

import pytest

from clipper_agency.agents.composer import ComposerAgent, _has_xfade_transitions
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
        # No treatment filter — just trim+setpts, mapped to [outv] for single scene
        assert "[0:v]trim=duration=5,setpts=PTS-STARTPTS[outv]" in filter_complex
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
        assert "[0:v]trim=duration=5,setpts=PTS-STARTPTS[outv]" in filter_complex
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
        """scene[0] dur=5, crossfade dur=0.3 → offset=5-0.3-0.1=4.6."""
        cmd = _build_two_scene_cmd(
            {"target_duration": 5, "transition_out": "crossfade"},
            {"target_duration": 5},
        )
        fc = _filter_complex(cmd)
        assert "offset=4.6" in fc

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
        assert "concat=n=2:a=1[outa]" in fc
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
        assert "concat=n=3:a=1[outa]" in fc
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
        assert "concat=n=2:a=1[outa]" in fc

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
        assert "concat=n=2:a=1[outa]" in fc
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
        assert "concat=n=2:a=1[outa]" in fc
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
        assert "concat=n=2:a=1[outa]" in fc
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
        assert "concat=n=2:a=1[outa]" in fc
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
        # Assert — basic trim+setpts present
        assert "trim=duration=" in fc
        assert "setpts=PTS-STARTPTS" in fc
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
        assert "[0:v]trim=duration=4.0,setpts=PTS-STARTPTS[outv]" in fc
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
        assert "concat=n=4:a=1[outa]" in fc
        assert "anullsrc=r=44100" in fc
        assert "amix" not in fc
