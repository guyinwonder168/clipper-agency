"""Tests for ComposerAgent."""

import json
import os
from pathlib import Path

import pytest

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.core.scene_validator import SceneValidationResult
from clipper_agency.core.scene_normalizer import NormalizeResult


# ═══════════════════════════════════════════════════════════════════════
# Task 11: Template rendering routing
# ═══════════════════════════════════════════════════════════════════════


class TestComposerTemplateRouting:
    """Task 11: Composer routes through template renderer when template_name is given."""

    def test_composer_uses_template_renderer_when_template_name_provided(
        self, tmp_path, monkeypatch,
    ):
        """Composer routes to template renderer when template_name is given."""
        # Mock subprocess for preflight (ffmpeg / ffprobe version checks)
        monkeypatch.setattr(
            "clipper_agency.agents.composer.subprocess.run",
            lambda *args, **kwargs: type("R", (), {
                "returncode": 0, "stdout": "ffmpeg version 5.1", "stderr": "",
            })(),
        )
        monkeypatch.setattr(
            "clipper_agency.agents.composer.subprocess.check_output",
            lambda *args, **kwargs: b"libx264\naac\nmp3",
        )

        calls = {}

        def fake_render_plan(plan, output_path, diagnostics_dir):
            calls["template_name"] = plan.template_name
            calls["output_path"] = str(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake_video")
            thumb = diagnostics_dir / "thumbnails" / "news_card.png"
            thumb.parent.mkdir(parents=True, exist_ok=True)
            thumb.write_bytes(b"fake_png")
            return type("Result", (), {
                "video_path": output_path,
                "thumbnail_path": thumb,
                "diagnostics_dir": diagnostics_dir,
            })()

        monkeypatch.setattr(
            "clipper_agency.agents.composer.render_plan", fake_render_plan,
        )

        from clipper_agency.agents.composer import ComposerAgent

        result = ComposerAgent().execute(
            job_id=789,
            assets=[{"path": str(tmp_path / "clip.mp4"), "scene": 1}],
            audio_files=[],
            output_dir=str(tmp_path / "outputs"),
            assets_cache=str(tmp_path / "cache"),
            caption="Halo dunia",
            template_name="news_card",
        )

        assert calls["template_name"] == "news_card"
        assert str(calls["output_path"]).endswith("job_789/video.mp4")
        assert result["template_name"] == "news_card"
        assert result["status"] == "completed"

    def test_composer_skips_template_renderer_when_no_template_name(
        self, tmp_path, monkeypatch,
    ):
        """Composer uses existing pipeline when no template_name."""
        # Mock subprocess for preflight (ffmpeg / ffprobe version checks)
        import subprocess as sp_mod

        mock_run = monkeypatch.setattr(
            "clipper_agency.agents.composer.subprocess.run",
            lambda *args, **kwargs: type("R", (), {
                "returncode": 0, "stdout": "ffmpeg version 5.1", "stderr": "",
            })(),
        )
        monkeypatch.setattr(
            "clipper_agency.agents.composer.subprocess.check_output",
            lambda *args, **kwargs: b"libx264\naac\nmp3",
        )

        from clipper_agency.agents.composer import ComposerAgent

        agent = ComposerAgent()
        # Mock _assemble_video and _generate_thumbnail so we bypass real ffmpeg
        monkeypatch.setattr(
            agent,
            "_assemble_video",
            lambda *args, **kw: {"cmd": ["ffmpeg"], "card_fallback_scenes": []},
        )
        monkeypatch.setattr(
            agent, "_generate_thumbnail", lambda *args, **kw: None,
        )

        result = agent.execute(
            job_id=790,
            assets=[{"path": str(tmp_path / "clip.mp4"), "scene": 1}],
            audio_files=[],
            output_dir=str(tmp_path / "outputs"),
        )

        assert result["status"] == "completed"
        # No template_name in result since existing path doesn't set it
        assert result.get("template_name") is None


class TestComposerName:
    """Agent name property."""

    def test_composer_agent_name(self):
        agent = ComposerAgent()
        assert agent.agent_name == "composer"


class TestComposerBuildFilter:
    """FFmpeg filter graph construction."""

    def test_build_filter_creates_concat_and_overlay(self):
        agent = ComposerAgent()
        assets = [
            {"scene": 1, "path": "/tmp/scene_1.mp4"},
            {"scene": 2, "path": "/tmp/scene_2.mp4"},
        ]
        audio_files = ["/tmp/scene_0.mp3", "/tmp/scene_1.mp3"]
        filter_str = agent._build_filter(assets, audio_files)
        assert "concat" in filter_str
        assert "amix" in filter_str
        assert "[outv]" in filter_str


class TestComposerExecute:
    """Full execute() with mocked subprocess."""

    def test_execute_returns_output_paths(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mocker.patch("subprocess.check_output", return_value=b"libx264\naac\nmp3")
        agent = ComposerAgent()
        # Mock assembly to avoid real scene validation/normalization
        mocker.patch.object(
            agent, "_assemble_video",
            return_value={"cmd": ["ffmpeg", "-y", "out.mp4"],
                          "card_fallback_scenes": []},
        )
        mocker.patch.object(agent, "_generate_thumbnail", return_value=None)
        result = agent.execute(
            job_id=5,
            assets=[
                {"scene": 1, "path": "/tmp/scene_1.mp4"},
                {"scene": 2, "path": "/tmp/scene_2.mp4"},
            ],
            audio_files=["/tmp/scene_0.mp3", "/tmp/scene_1.mp3"],
            output_dir="/tmp/output",
        )
        assert result["status"] == "completed"
        assert result["video_path"].endswith(".mp4")
        assert result["thumbnail_path"].endswith(".png")
        # preflight calls subprocess.run twice (ffmpeg -version, ffprobe -version);
        # assembly and thumbnail are mocked
        assert mock_run.call_count == 2

    def test_execute_ffmpeg_video_command(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mocker.patch("subprocess.check_output", return_value=b"libx264\naac\nmp3")
        agent = ComposerAgent()
        mock_assemble = mocker.patch.object(
            agent, "_assemble_video",
            return_value={"cmd": ["ffmpeg"], "card_fallback_scenes": []},
        )
        mocker.patch.object(agent, "_generate_thumbnail", return_value=None)
        agent.execute(
            job_id=5,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/scene_0.mp3"],
            output_dir="/tmp/output",
        )
        # Verify _assemble_video was called with correct args
        assert mock_assemble.called
        call_args = mock_assemble.call_args[0]
        # call_args[0] = assets list, call_args[1] = audio_files
        assert len(call_args[0]) == 1  # 1 asset
        assert len(call_args[1]) == 1  # 1 audio file

    def test_execute_handles_empty_inputs(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mocker.patch("subprocess.check_output", return_value=b"libx264\naac\nmp3")
        agent = ComposerAgent()
        result = agent.execute(
            job_id=5,
            assets=[],
            audio_files=[],
            output_dir="/tmp/output",
        )
        assert result["status"] == "completed"
        # Preflight calls subprocess.run for ffmpeg + ffprobe version checks,
        # but assembly should not be called (empty inputs)
        assert mock_run.call_count == 2  # only preflight calls

    def test_execute_handles_ffmpeg_failure(self, mocker):
        mocker.patch("subprocess.run", side_effect=Exception("ffmpeg not found"))
        agent = ComposerAgent()
        result = agent.execute(
            job_id=5,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/scene_0.mp3"],
            output_dir="/tmp/output",
        )
        assert result["status"] == "failed"
        assert "error" in result
        assert "ffmpeg" in result["error"].lower()

    def test_execute_thumbnail_uses_first_frame(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mocker.patch("subprocess.check_output", return_value=b"libx264\naac\nmp3")
        agent = ComposerAgent()
        mocker.patch.object(
            agent, "_assemble_video",
            return_value={"cmd": ["ffmpeg"], "card_fallback_scenes": []},
        )
        mock_thumb = mocker.patch.object(agent, "_generate_thumbnail")
        result = agent.execute(
            job_id=5,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/scene_0.mp3"],
            output_dir="/tmp/output",
        )
        # Verify thumbnail was called with first-frame params
        assert mock_thumb.called
        call_args = mock_thumb.call_args[0]
        assert result["video_path"] == call_args[0]

    def test_build_filter_no_video_assets_returns_null(self):
        """Line 60: empty assets list returns 'null' filter string."""
        agent = ComposerAgent()
        result = agent._build_filter([], [])
        assert result == "null"

    def test_build_filter_no_audio_uses_silent_source(self):
        """Line 77: no audio files → uses anullsrc for silent audio."""
        agent = ComposerAgent()
        assets = [{"scene": 1, "path": "/tmp/scene_1.mp4"}]
        result = agent._build_filter(assets, [])
        assert "anullsrc[outa]" in result
        assert "concat" in result

    def test_assemble_video_empty_inputs_returns_early(self, mocker):
        """Line 86: no video inputs → early return, no ffmpeg call."""
        mock_ffmpeg = mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        agent = ComposerAgent()
        agent._assemble_video([], [], "/tmp/output.mp4")
        mock_ffmpeg.assert_not_called()


class TestComposerPreflight:
    """ComposerAgent.execute() runs FFmpeg preflight and persists diagnostics."""

    def test_execute_runs_preflight_and_persists_diagnostics(self, tmp_path, mocker):
        """ComposerAgent.execute() persists preflight.json diagnostics."""
        # Mock subprocess so FFmpegPreflight.probe() doesn't actually run
        mocker.patch(
            "subprocess.run",
            return_value=mocker.Mock(returncode=0, stdout="ffmpeg version 5.1", stderr=""),
        )
        mocker.patch(
            "subprocess.check_output", return_value=b"libx264\naac\nmp3"
        )

        from clipper_agency.agents.composer import ComposerAgent

        agent = ComposerAgent()
        mocker.patch.object(
            agent, "_assemble_video",
            return_value={"cmd": ["ffmpeg", "-y", "out.mp4"],
                          "card_fallback_scenes": []},
        )
        mocker.patch.object(agent, "_generate_thumbnail", return_value=None)

        assets_dir = tmp_path / "assets_cache"
        assets_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        result = agent.execute(
            job_id=99,
            assets=[{"scene": 1, "path": str(assets_dir / "scene_1.mp4")}],
            audio_files=[str(audio_dir / "voice.mp3")],
            output_dir=str(output_dir),
            assets_cache=str(assets_dir),
        )

        preflight_file = output_dir / "job_99" / "agents" / "composer" / "preflight.json"
        assert preflight_file.exists()
        assert result["status"] == "completed"

    def test_execute_fails_when_preflight_not_ok(self, tmp_path, mocker):
        """ComposerAgent.execute() fails when FFmpeg preflight fails."""
        # Mock subprocess to simulate missing ffmpeg
        mocker.patch("subprocess.run", side_effect=FileNotFoundError)

        from clipper_agency.agents.composer import ComposerAgent

        agent = ComposerAgent()

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = agent.execute(
            job_id=98,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=[],
            output_dir=str(output_dir),
            assets_cache=str(tmp_path),
        )
        assert result["status"] == "failed"
        assert any("preflight" in str(v).lower() for v in result.values())


# ═══════════════════════════════════════════════════════════════════════
# Task 9: Composer scene assembly with card fallback
# ═══════════════════════════════════════════════════════════════════════


class TestComposerCardFallback:
    """Task 9: Composer scene assembly with card fallback for missing clips."""

    def test_assemble_inserts_card_videos_for_empty_scenes(self, tmp_path, mocker):
        """Assets with empty/missing paths get card video fallback inserted."""
        agent = ComposerAgent()

        valid_scene = tmp_path / "scene_2.mp4"
        valid_scene.write_bytes(b"valid mp4 data" * 100)

        # Mock SceneValidator: scene 1 & 3 invalid, scene 2 valid
        mock_validate = mocker.patch(
            "clipper_agency.agents.composer.SceneValidator.validate"
        )

        def validate_side_effect(path, min_bytes=1024):
            if not path or "scene_1" in str(path) or "scene_3" in str(path):
                return SceneValidationResult(
                    path=str(path), valid=False,
                    issues=["missing or invalid"],
                )
            return SceneValidationResult(
                path=str(path), valid=True, issues=[],
            )

        mock_validate.side_effect = validate_side_effect

        # Mock CardGenerator
        mock_card_gen_cls = mocker.patch(
            "clipper_agency.agents.composer.CardGenerator"
        )
        mock_card_gen = mock_card_gen_cls.return_value

        # Mock card_to_video to return success
        mock_ctv = mocker.patch("clipper_agency.agents.composer.card_to_video")

        def ctv_side_effect(png_path, output_mp4, duration=5):
            # Write a dummy output file to make path valid
            Path(output_mp4).write_bytes(b"card video data" * 100)
            from clipper_agency.core.card_to_video import CardVideoResult
            return CardVideoResult(path=output_mp4, success=True)

        mock_ctv.side_effect = ctv_side_effect

        # Mock SceneNormalizer
        mock_norm_cls = mocker.patch(
            "clipper_agency.agents.composer.SceneNormalizer"
        )
        mock_norm = mock_norm_cls.return_value

        def norm_side_effect(input_path, output_path):
            import shutil
            if os.path.exists(input_path):
                shutil.copy(input_path, output_path)
            else:
                Path(output_path).write_bytes(b"normalized data" * 100)
            return NormalizeResult(path=output_path, success=True)

        mock_norm.normalize = mocker.Mock(side_effect=norm_side_effect)

        # Mock run_ffmpeg_streaming for final concat
        mock_run = mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")

        assets = [
            {"scene": 1, "path": ""},
            {"scene": 2, "path": str(valid_scene)},
            {"scene": 3, "path": ""},
        ]

        output_path = str(tmp_path / "output.mp4")
        result = agent._assemble_video(assets, [], output_path)

        # Cards should be generated for scenes 1 and 3 (2 empty paths)
        assert mock_card_gen.generate.call_count == 2
        assert mock_ctv.call_count == 2

        # Final ffmpeg concat should be called
        assert mock_run.called

        # Check card_fallback_scenes in result
        assert result["card_fallback_scenes"] == [1, 3]

        # Check card fallback metadata file
        metadata_path = tmp_path / "card_fallback.json"
        assert metadata_path.exists()
        meta = json.loads(metadata_path.read_text())
        assert 1 in meta["card_fallback_scenes"]
        assert 3 in meta["card_fallback_scenes"]

    def test_assemble_skips_card_fallback_when_all_valid(self, tmp_path, mocker):
        """No cards generated when all scenes have valid paths."""
        agent = ComposerAgent()

        valid_scene = tmp_path / "scene_1.mp4"
        valid_scene.write_bytes(b"valid mp4 data" * 100)

        # Mock SceneValidator: all scenes valid
        mocker.patch(
            "clipper_agency.agents.composer.SceneValidator.validate",
            return_value=SceneValidationResult(
                path=str(valid_scene), valid=True, issues=[],
            ),
        )

        # Mock CardGenerator
        mock_card_gen_cls = mocker.patch(
            "clipper_agency.agents.composer.CardGenerator"
        )
        mock_card_gen = mock_card_gen_cls.return_value

        # Mock card_to_video
        mock_ctv = mocker.patch("clipper_agency.agents.composer.card_to_video")

        # Mock SceneNormalizer
        mock_norm_cls = mocker.patch(
            "clipper_agency.agents.composer.SceneNormalizer"
        )
        mock_norm = mock_norm_cls.return_value

        def norm_side_effect(input_path, output_path):
            import shutil
            shutil.copy(input_path, output_path)
            return NormalizeResult(path=output_path, success=True)

        mock_norm.normalize = mocker.Mock(side_effect=norm_side_effect)

        # Mock run_ffmpeg_streaming for concat
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")

        assets = [
            {"scene": 1, "path": str(valid_scene)},
            {"scene": 2, "path": str(valid_scene)},
        ]

        output_path = str(tmp_path / "output.mp4")
        result = agent._assemble_video(assets, [], output_path)

        # No cards should be generated
        mock_card_gen.generate.assert_not_called()
        mock_ctv.assert_not_called()

        # No card fallback scenes tracked
        assert result["card_fallback_scenes"] == []

    def test_assemble_normalizes_scenes_before_concat(self, tmp_path, mocker):
        """SceneNormalizer.normalize is called for each scene before concat."""
        agent = ComposerAgent()

        valid_scene = tmp_path / "scene_1.mp4"
        valid_scene.write_bytes(b"valid mp4 data" * 100)

        # All scenes valid
        mocker.patch(
            "clipper_agency.agents.composer.SceneValidator.validate",
            return_value=SceneValidationResult(
                path=str(valid_scene), valid=True, issues=[],
            ),
        )

        # Mock SceneNormalizer to track calls
        mock_norm_cls = mocker.patch(
            "clipper_agency.agents.composer.SceneNormalizer"
        )
        mock_norm = mock_norm_cls.return_value

        normed_outputs = []

        def norm_side_effect(input_path, output_path):
            import shutil
            shutil.copy(input_path, output_path)
            normed_outputs.append(output_path)
            return NormalizeResult(path=output_path, success=True)

        mock_norm.normalize = mocker.Mock(side_effect=norm_side_effect)

        # Mock run_ffmpeg_streaming for final concat — capture the command
        mock_ffmpeg = mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")

        assets = [
            {"scene": 1, "path": str(valid_scene)},
            {"scene": 2, "path": str(valid_scene)},
        ]

        output_path = str(tmp_path / "output.mp4")
        agent._assemble_video(assets, [], output_path)

        # Normalize should be called twice (once per scene)
        assert mock_norm.normalize.call_count == 2

        # Final concat command should NOT use original scene paths
        call_args = mock_ffmpeg.call_args[0][0]
        call_str = " ".join(call_args)
        for orig in [str(valid_scene)]:
            assert orig not in call_str, (
                f"Original scene path {orig} leaked into ffmpeg command"
            )

        # Final concat should use the normalized output paths
        for nout in normed_outputs:
            assert nout in call_str, (
                f"Normalized output {nout} not in ffmpeg command"
            )

    def test_execute_includes_card_fallback_in_output(self, tmp_path, mocker):
        """execute() returns card_fallback_scenes in its output dict."""
        # Mock preflight
        mocker.patch(
            "subprocess.run",
            return_value=mocker.Mock(returncode=0, stdout="ffmpeg", stderr=""),
        )
        mocker.patch(
            "subprocess.check_output", return_value=b"libx264\naac\nmp3"
        )

        agent = ComposerAgent()

        # Mock _assemble_video to simulate card fallback
        mocker.patch.object(
            agent, "_assemble_video",
            return_value={"cmd": ["ffmpeg"], "card_fallback_scenes": [1, 3]},
        )
        mocker.patch.object(agent, "_generate_thumbnail", return_value=None)

        valid_scene = tmp_path / "scene_2.mp4"
        valid_scene.write_bytes(b"valid" * 100)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = agent.execute(
            job_id=99,
            assets=[
                {"scene": 1, "path": ""},
                {"scene": 2, "path": str(valid_scene)},
                {"scene": 3, "path": ""},
            ],
            audio_files=[],
            output_dir=str(output_dir),
            assets_cache=str(tmp_path),
        )

        assert result["status"] == "completed"
        assert result["card_fallback_scenes"] == [1, 3]


# ═══════════════════════════════════════════════════════════════════════
# Task 10: Audio assembly and mixing
# ═══════════════════════════════════════════════════════════════════════


class TestComposerAudioAssembly:
    """Task 10: Audio assembly — alignment, silent padding, no TikTok audio."""

    def test_audio_aligns_correct_input_count(self):
        """amix uses correct input count matching audio file count."""
        agent = ComposerAgent()
        assets = [
            {"scene": 1, "path": "/tmp/s1.mp4"},
            {"scene": 2, "path": "/tmp/s2.mp4"},
            {"scene": 3, "path": "/tmp/s3.mp4"},
        ]
        audio_files = ["/tmp/v0.mp3", "/tmp/v1.mp3"]

        filt = agent._build_filter(assets, audio_files)

        assert "amix=inputs=2" in filt
        assert "duration=first" in filt

    def test_no_background_music_by_default(self):
        """No extra audio inputs beyond voice files — no bg music."""
        agent = ComposerAgent()
        assets = [
            {"scene": 1, "path": "/tmp/s1.mp4"},
            {"scene": 2, "path": "/tmp/s2.mp4"},
        ]
        audio_files = ["/tmp/voice_0.mp3", "/tmp/voice_1.mp3"]

        filt = agent._build_filter(assets, audio_files)

        # Should have exactly 2 video inputs + 2 audio inputs = 4 total -i refs
        # amix=inputs=2 confirms exactly 2 audio inputs
        assert "amix=inputs=2" in filt

    def test_silent_audio_for_scenes_without_voice(self):
        """Scenes without matching voice get anullsrc silent audio."""
        agent = ComposerAgent()
        assets = [
            {"scene": 1, "path": "/tmp/s1.mp4"},
            {"scene": 2, "path": "/tmp/s2.mp4"},
        ]
        audio_files = ["/tmp/voice_0.mp3"]

        filt = agent._build_filter(assets, audio_files)

        assert "amix=inputs=1" in filt
        # Even with fewer voice files than scenes, audio is handled
        assert "[outa]" in filt

    def test_disallow_copyrighted_tiktok_audio(self, tmp_path, mocker):
        """Audio inputs should only be voice files, not TikTok audio sources."""
        agent = ComposerAgent()

        valid_scene = tmp_path / "scene_1.mp4"
        valid_scene.write_bytes(b"valid mp4 data" * 100)

        mocker.patch(
            "clipper_agency.agents.composer.SceneValidator.validate",
            return_value=SceneValidationResult(
                path=str(valid_scene), valid=True, issues=[],
            ),
        )
        mock_norm = mocker.patch(
            "clipper_agency.agents.composer.SceneNormalizer"
        )
        mock_norm.return_value.normalize = mocker.Mock(
            return_value=NormalizeResult(path=str(valid_scene), success=True),
        )

        mock_run = mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")

        assets = [
            {"scene": 1, "path": str(valid_scene)},
        ]

        # Valid: voice files only — no TikTok audio
        voice_files = ["/tmp/voice_0.mp3", "/tmp/voice_1.mp3"]
        output_path = str(tmp_path / "out.mp4")
        agent._assemble_video(assets, voice_files, output_path)

        call_args = mock_run.call_args[0][0]
        call_str = " ".join(call_args)

        # TikTok audio patterns must not appear
        forbidden = ["tiktok", "original_sound", "music", "bgm"]
        for pattern in forbidden:
            assert pattern not in call_str.lower(), (
                f"Forbidden audio pattern '{pattern}' found in ffmpeg args"
            )


# ═══════════════════════════════════════════════════════════════════════
# Task 12: Persist Composer template diagnostics
# ═══════════════════════════════════════════════════════════════════════


class TestComposerTemplateDiagnostics:
    """Task 12: Composer persists template diagnostics in diagnostics_dir."""

    def test_composer_persists_template_diagnostics(self, tmp_path, monkeypatch):
        """Composer writes template_config.json and returns diagnostics_dir."""
        # Mock subprocess for preflight
        monkeypatch.setattr(
            "clipper_agency.agents.composer.subprocess.run",
            lambda *args, **kwargs: type("R", (), {
                "returncode": 0, "stdout": "ffmpeg version 5.1", "stderr": "",
            })(),
        )
        monkeypatch.setattr(
            "clipper_agency.agents.composer.subprocess.check_output",
            lambda *args, **kwargs: b"libx264\naac\nmp3",
        )

        captured = {}

        def fake_render_plan(plan, output_path, diagnostics_dir):
            """Simulate engine writing render_plan.json."""
            captured["diagnostics_dir"] = diagnostics_dir
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            # Engine writes render_plan.json
            (diagnostics_dir / "render_plan.json").write_text(
                json.dumps({"template_name": plan.template_name})
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake_video")
            thumb = diagnostics_dir / "thumbnails" / "news_card.png"
            thumb.parent.mkdir(parents=True, exist_ok=True)
            thumb.write_bytes(b"fake_png")
            return type("Result", (), {
                "video_path": output_path,
                "thumbnail_path": thumb,
            })()

        monkeypatch.setattr(
            "clipper_agency.agents.composer.render_plan", fake_render_plan,
        )

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        output_dir = tmp_path / "outputs"

        result = ComposerAgent().execute(
            job_id=42,
            assets=[{"path": str(tmp_path / "clip.mp4"), "scene": 1}],
            audio_files=[],
            output_dir=str(output_dir),
            assets_cache=str(cache_dir),
            template_name="news_card",
            caption="Test caption",
        )

        composer_dir = cache_dir / "job_42" / "agents" / "composer"

        # render_plan.json — written by engine, verify composer path produces it
        assert (composer_dir / "render_plan.json").exists(), (
            "render_plan.json should exist in diagnostics_dir"
        )

        # template_config.json — NEW: written by composer
        assert (composer_dir / "template_config.json").exists(), (
            "template_config.json should exist in diagnostics_dir"
        )
        config = json.loads((composer_dir / "template_config.json").read_text())
        assert config["name"] == "news_card"
        assert config["type"] == "news_card"

        # diagnostics_dir in result dict — NEW
        assert result["diagnostics_dir"] == str(composer_dir), (
            f"Expected diagnostics_dir={composer_dir}, got {result.get('diagnostics_dir')}"
        )

        # input.json — already written by existing flow
        assert (composer_dir / "input.json").exists(), (
            "input.json should exist in diagnostics_dir"
        )

        # output.json — already written by existing flow
        assert (composer_dir / "output.json").exists(), (
            "output.json should exist in diagnostics_dir"
        )

        assert result["status"] == "completed"
