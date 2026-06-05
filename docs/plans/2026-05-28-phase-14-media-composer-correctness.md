# Phase 14: Media Composer Correctness — Implementation Plan ✅ COMPLETED

> **Status:** Completed — merged via PR #17 (`1f36918`) on master. All 12 subtasks implemented: FFmpeg preflight, media probing, scene validation/normalization, clip provenance, generated card fallback, card-to-video, composer assembly, output packaging validation, deterministic G10, fixed-contract packager with S6549-safe path sandbox.

**Goal:** Make generated videos satisfy MVP media requirements reliably — correct resolution, valid clips, generated card fallback, proper audio mixing, and deterministic output validation.

**Architecture:** 12 subtasks building from FFmpeg environment probing through scene normalization, generated card fallback, audio assembly, output packaging, and deterministic G10 validation. **Hard cuts / concat only in Phase 14; animated transitions (xfade, fade) deferred to Phase 15.**

**Tech Stack:** Python 3.11+, FFmpeg 5.0+, Pillow (for generated cards)

**Design Decision:** Hard cuts / concat only. Animated transitions (xfade, fade, acrossfade) deferred to Phase 15 per roadmap — Phase 14 goal is structural correctness, Phase 15 handles creative rendering with templates.

---

### Task 1: FFmpeg capability probe

**Files:**
- Create: `clipper_agency/core/ffmpeg_preflight.py`
- Test: `tests/test_ffmpeg_preflight.py`

**Step 1: Write the failing test**

```python
# tests/test_ffmpeg_preflight.py
import subprocess
import pytest
from clipper_agency.core.ffmpeg_preflight import FFmpegPreflight, FFmpegPreflightResult

class TestFFmpegPreflight:
    def test_probe_returns_result_with_all_checks(self, mocker):
        mocker.patch("subprocess.run", return_value=subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout="ffmpeg version 5.1", stderr=""))
        mocker.patch("subprocess.check_output", return_value=b"libx264\naac\nmp3")

        result = FFmpegPreflight.probe()

        assert isinstance(result, FFmpegPreflightResult)
        assert result.ffmpeg_found is True
        assert result.libx264_available is True
        assert result.aac_available is True
        assert result.mp3_decode_available is True

    def test_probe_ffmpeg_missing(self, mocker):
        mocker.patch("subprocess.run", side_effect=FileNotFoundError)
        result = FFmpegPreflight.probe()
        assert result.ffmpeg_found is False
        assert not result.all_ok()

    def test_probe_missing_codec_flags(self, mocker):
        mocker.patch("subprocess.run", return_value=subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout="", stderr=""))
        mocker.patch("subprocess.check_output", return_value=b"some other codec")
        result = FFmpegPreflight.probe()
        assert result.libx264_available is False
        assert not result.all_ok()
```

**Step 2:** Run test to verify it fails: `pytest tests/test_ffmpeg_preflight.py -v` → FAIL (module not found)

**Step 3:** Implement `clipper_agency/core/ffmpeg_preflight.py`:

```python
"""FFmpeg preflight probe — checks binary presence and required codecs."""
import subprocess
from dataclasses import dataclass

@dataclass
class FFmpegPreflightResult:
    ffmpeg_found: bool = False
    ffprobe_found: bool = False
    libx264_available: bool = False
    aac_available: bool = False
    mp3_decode_available: bool = False

    def all_ok(self) -> bool:
        return all([
            self.ffmpeg_found, self.ffprobe_found,
            self.libx264_available, self.aac_available,
            self.mp3_decode_available,
        ])

class FFmpegPreflight:
    @staticmethod
    def probe() -> FFmpegPreflightResult:
        result = FFmpegPreflightResult()
        # Check ffmpeg + ffprobe existence
        for tool, attr in [("ffmpeg", "ffmpeg_found"), ("ffprobe", "ffprobe_found")]:
            try:
                subprocess.run([tool, "-version"], capture_output=True, check=True, timeout=10)
                setattr(result, attr, True)
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass

        # Check codec support via ffmpeg -codecs
        try:
            codecs = subprocess.check_output(
                ["ffmpeg", "-codecs"], stderr=subprocess.DEVNULL, timeout=10,
            ).decode()
            result.libx264_available = "libx264" in codecs
            result.aac_available = "aac" in codecs
            result.mp3_decode_available = "mp3" in codecs
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        return result
```

**Step 4:** `pytest tests/test_ffmpeg_preflight.py -v` → PASS

**Step 5:** Commit
```bash
git add tests/test_ffmpeg_preflight.py clipper_agency/core/ffmpeg_preflight.py
git commit -m "feat: add FFmpeg preflight probe for codec availability"
```

---

### Task 2: Persist FFmpeg preflight diagnostics

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Modify: `tests/test_agents_composer.py`

**Step 1: Write the failing test**

Add to `tests/test_agents_composer.py`:
```python
class TestComposerPreflight:
    def test_execute_runs_preflight_and_persists_diagnostics(self, tmp_path, mocker):
        mocker.patch("subprocess.run")
        agent = ComposerAgent()
        mocker.patch.object(
            agent, "_run_preflight",
            return_value={"ffmpeg_found": True, "all_ok": True},
        )
        result = agent.execute(
            job_id=99,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )
        preflight_file = tmp_path / "job_99" / "agents" / "composer" / "preflight.json"
        assert preflight_file.exists()
        assert result["status"] == "completed"

    def test_execute_fails_when_preflight_not_ok(self, tmp_path, mocker):
        agent = ComposerAgent()
        mocker.patch.object(
            agent, "_run_preflight",
            return_value={"ffmpeg_found": False, "all_ok": False},
        )
        result = agent.execute(
            job_id=98,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=[],
            output_dir=str(tmp_path),
        )
        assert result["status"] == "failed"
        assert "preflight" in str(result).lower()
```

**Step 2:** Run tests → FAIL

**Step 3:** Add `_run_preflight()` to `ComposerAgent` in `clipper_agency/agents/composer.py` — call it at the top of `execute()`, persist result as `preflight.json`. Return failure if `all_ok()` is False.

**Step 4:** Run tests → PASS

**Step 5:** Commit
```bash
git add tests/test_agents_composer.py clipper_agency/agents/composer.py
git commit -m "feat: add preflight diagnostics persistence to ComposerAgent"
```

---

### Task 3: Media probing utilities

**Files:**
- Create: `clipper_agency/core/media_probe.py`
- Test: `tests/test_media_probe.py`

**Step 1: Write the failing test**

```python
# tests/test_media_probe.py
class TestProbeVideo:
    def test_probe_returns_resolution_codec_duration(self, tmp_path, mocker):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{"codec_type": "video", "width": 720, "height": 1280,
                         "codec_name": "h264", "pix_fmt": "yuv420p"}],
            "format": {"duration": "5.0"},
        }))
        from clipper_agency.core.media_probe import probe_video
        info = probe_video(str(video))
        assert info.width == 720
        assert info.height == 1280
        assert info.codec == "h264"
        assert info.duration == 5.0

    def test_probe_returns_none_for_missing_file(self):
        from clipper_agency.core.media_probe import probe_video
        info = probe_video("/nonexistent/video.mp4")
        assert info is None
```

**Step 2:** `pytest tests/test_media_probe.py -v` → FAIL

**Step 3:** Implement `clipper_agency/core/media_probe.py` — `probe_video(path) -> VideoInfo | None` using `ffprobe -v quiet -print_format json -show_format -show_streams`. Dataclass with: width, height, codec, pix_fmt, duration, has_audio, file_size.

**Step 4:** `pytest tests/test_media_probe.py -v` → PASS

**Step 5:** Commit
```bash
git add tests/test_media_probe.py clipper_agency/core/media_probe.py
git commit -m "feat: add ffprobe-based media probing utility"
```

---

### Task 4: Scene validation

**Files:**
- Create: `clipper_agency/core/scene_validator.py`
- Test: `tests/test_scene_validator.py`

**Step 1: Write the failing test**

```python
# tests/test_scene_validator.py
from clipper_agency.core.scene_validator import SceneValidator, SceneValidationResult

class TestSceneValidator:
    def test_valid_scene_passes(self, tmp_path):
        scene = tmp_path / "scene_1.mp4"
        scene.write_bytes(b"x" * 10000)
        result = SceneValidator.validate(str(scene))
        assert result.valid is True

    def test_missing_file_fails(self, tmp_path):
        result = SceneValidator.validate(str(tmp_path / "missing.mp4"))
        assert result.valid is False
        assert any("not found" in i.lower() for i in result.issues)

    def test_zero_byte_file_fails(self, tmp_path):
        scene = tmp_path / "empty.mp4"
        scene.write_bytes(b"")
        result = SceneValidator.validate(str(scene))
        assert result.valid is False
        assert any("empty" in i.lower() or "zero" in i.lower() for i in result.issues)

    def test_tiny_file_fails(self, tmp_path):
        scene = tmp_path / "tiny.mp4"
        scene.write_bytes(b"x" * 10)
        result = SceneValidator.validate(str(scene))
        assert result.valid is False
        assert any("small" in i.lower() or "corrupt" in i.lower() for i in result.issues)
```

**Step 2:** Run → FAIL

**Step 3:** Implement `SceneValidator.validate(path, min_bytes=1024)` — checks existence, non-zero, min size. Returns `SceneValidationResult(valid, issues)`.

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 5: Scene normalization

**Files:**
- Create: `clipper_agency/core/scene_normalizer.py`
- Test: `tests/test_scene_normalizer.py`

**Step 1: Write the failing test**

- `test_normalize_scales_to_1080x1920` — ffprobe mocked to return non-9:16 input, verify ffmpeg command uses `scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2`
- `test_normalize_already_1080x1920_skips` — already correct resolution, no normalize needed
- `test_normalize_strips_audio_from_source` — verify `-an` in ffmpeg args
- `test_normalize_output_is_h264_yuv420p` — verify `-c:v libx264 -pix_fmt yuv420p`
- `test_normalize_handles_missing_input` — returns error

**Step 2:** Run → FAIL

**Step 3:** Implement `SceneNormalizer.normalize(input_path, output_path)` — runs ffmpeg to produce 1080x1920 h264 yuv420p with audio stripped, metadata stripped via `-map_metadata -1`. Uses `scale + pad` filter for letterboxing.

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 6: Clip provenance tracking

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Modify: `tests/test_agents_visual.py`

**Step 1: Write the failing test**

Add test: `test_provenance_includes_source_dimensions_and_origin` — mocks ffprobe to return 720x1280, verifies `provenance.json` contains `original_width`, `original_height`, `source`, `normalized` fields for each scene.

**Step 2:** Run → FAIL

**Step 3:** Update Visual Director's `_download_assets()` to run `probe_video()` on each downloaded scene, enrich the `provenance.json` with per-scene: source (tiktok/pexels/none), original dimensions, file size, download timestamp.

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 7: Generated card fallback (PNG)

**Files:**
- Create: `clipper_agency/core/card_generator.py`
- Test: `tests/test_card_generator.py`

**Step 1: Write the failing test**

```python
from clipper_agency.core.card_generator import CardGenerator, CardType

class TestCardGenerator:
    def test_generate_card_creates_1080x1920_png(self, tmp_path):
        gen = CardGenerator()
        output = tmp_path / "card.png"
        gen.generate(CardType.HEADLINE, "Test Title", str(output))
        assert output.exists()
        from PIL import Image
        img = Image.open(output)
        assert img.size == (1080, 1920)
        assert output.stat().st_size > 1024

    def test_all_card_types_generate_valid_images(self, tmp_path):
        gen = CardGenerator()
        for ct in CardType:
            output = tmp_path / f"card_{ct.name}.png"
            gen.generate(ct, "Sample text", str(output))
            assert output.exists()
            assert output.stat().st_size > 0
```

**Step 2:** Run → FAIL

**Step 3:** Implement `CardGenerator` using Pillow — generates 1080x1920 PNG with simple layout per card type (headline, fact, context, cta). Uses niche/template colors from config. Text centered with wrapping.

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 8: Convert cards into video scenes

**Files:**
- Create: `clipper_agency/core/card_to_video.py`
- Test: `tests/test_card_to_video.py`

**Step 1: Write the failing test**

- `test_convert_card_to_5s_video` — generates a PNG card, converts to 5s MP4, verifies output exists, verifies ffmpeg uses `-loop 1 -t 5` and silent audio `-f lavfi -i anullsrc`
- `test_converted_video_is_1080x1920` — mocked ffprobe returns correct resolution

**Step 2:** Run → FAIL

**Step 3:** Implement `card_to_video(png_path, output_mp4, duration=5)` — runs ffmpeg: `-loop 1 -i {png} -f lavfi -i anullsrc -t {duration} -c:v libx264 -pix_fmt yuv420p -shortest {output}`

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 9: Composer scene assembly with card fallback

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Modify: `tests/test_agents_composer.py`

**Step 1: Write the failing test**

- `test_assemble_inserts_card_videos_for_empty_scenes` — assets list has scene_1 path empty, scene_2 valid, scene_3 path empty. Verifies 2 cards are generated and inserted, final concat uses card videos for empty slots.
- `test_assemble_skips_card_fallback_when_all_valid` — all scenes have valid paths, no cards generated.
- `test_assemble_normalizes_scenes_before_concat` — verifies `SceneNormalizer.normalize` is called for each scene before concat.

**Step 2:** Run → FAIL

**Step 3:** Update `ComposerAgent._assemble_video()`:
1. Stage each clip: normalize → write to temp directory
2. For scenes with empty/missing paths: generate card → convert to video → normalize → write temp
3. Run concat/amix on the normalized temp files
4. Track which scenes used card fallback in output metadata

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 10: Audio assembly and mixing

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Modify: `tests/test_agents_composer.py`

**Step 1: Write the failing test**

- `test_audio_aligns_to_scenes` — 3 scenes, 2 voice files → verify amix includes correct input count, verify voice audio starts at correct scene timestamp
- `test_no_background_music_by_default` — verify no extra audio inputs beyond voice files
- `test_silent_audio_for_scenes_without_voice` — scene missing voice gets silent padding
- `test_disallow_copyrighted_tiktok_audio` — verify no TikTok audio sources in the audio track

**Step 2:** Run → FAIL

**Step 3:** Update `_build_filter()` and `_assemble_video()`:
- Match voice files to scenes by scene_id index
- Insert silent audio (`anullsrc`) for scenes without matching voice
- No background music by default (no copyrighted TikTok audio)
- Use `amix` with `duration=first` for voice mixing

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 11: Final output package validation

**Files:**
- Modify: `clipper_agency/output/packager.py`
- Modify: `tests/test_output_packager.py`

**Step 1: Write the failing test**

- `test_package_validates_video_resolution` — packager calls ffprobe, rejects video not 1080x1920
- `test_package_validates_video_duration` — rejects <20s or >60s
- `test_package_validates_audio_track_present` — rejects video without audio
- `test_package_validates_codec` — rejects non-h264
- `test_package_creates_all_expected_files` — verifies `video.mp4`, `caption.txt`, `thumbnail.png`, `metadata.json` all present

**Step 2:** Run → FAIL

**Step 3:** Add `_validate_output_media(video_path)` to `OutputPackager` — uses `probe_video()` to check resolution (1080x1920), duration (20-60s), codec (h264), has audio. Returns `ValidationResult`. Call before copy in `package()`.

**Step 4:** Run → PASS

**Step 5:** Commit

---

### Task 12: Deterministic G10 output validation

**Files:**
- Modify: `clipper_agency/orchestrator/gates.py`
- Modify: `tests/test_gates.py`

**Step 1: Write the failing test**

Add to `tests/test_gates.py`:
```python
class TestGateVideoValidation:
    def test_g10_rejects_wrong_resolution(self, mocker):
        mocker.patch("clipper_agency.orchestrator.gates.probe_video",
                     return_value=MockVideoInfo(width=1920, height=1080, codec="h264",
                                                duration=30.0, has_audio=True))
        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "resolution" in result.message.lower() or "1080x1920" in result.message.lower()

    def test_g10_rejects_wrong_duration(self, mocker):
        mocker.patch("clipper_agency.orchestrator.gates.probe_video",
                     return_value=MockVideoInfo(width=1080, height=1920, codec="h264",
                                                duration=10.0, has_audio=True))
        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "duration" in result.message.lower()

    def test_g10_rejects_no_audio(self, mocker):
        mocker.patch("clipper_agency.orchestrator.gates.probe_video",
                     return_value=MockVideoInfo(width=1080, height=1920, codec="h264",
                                                duration=30.0, has_audio=False))
        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "audio" in result.message.lower()

    def test_g10_accepts_valid_video(self, mocker):
        mocker.patch("clipper_agency.orchestrator.gates.probe_video",
                     return_value=MockVideoInfo(width=1080, height=1920, codec="h264",
                                                duration=30.0, has_audio=True))
        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert result.passed
```

**Step 2:** Run → FAIL

**Step 3:** Rewrite `GateVideoValidation.evaluate()` to use `probe_video()` from `clipper_agency.core.media_probe`. Check: file exists, size > 1KB, resolution == 1080x1920, codec == h264, duration 20-60s, has audio track, metadata stripped. Return hard_fail with specific message for each violation.

**Step 4:** Run → PASS. Run full G10 gate test suite → all green.

**Step 5:** Commit
```bash
git add tests/test_gates.py clipper_agency/orchestrator/gates.py
git commit -m "feat: deterministic G10 video validation with ffprobe checks"
```

---

## Acceptance Criteria (all 12 tasks complete)

- [x] Composer no longer fails on mixed source dimensions
- [x] Valid source clips normalized to 1080x1920 before concat
- [x] Invalid/too-short clips rejected or replaced with generated cards
- [x] Final `video.mp4` passes G10 deterministic validation
- [x] `thumbnail.png`, `caption.txt`, and `metadata.json` generated consistently
- [x] FFmpeg stderr and command logs persisted for failed renders
- [x] Preflight diagnostics persisted per job
- [x] Clip provenance tracked (source, original dimensions, download timestamp)
- [x] No copyrighted TikTok audio embedded in output

## Explicit Deferrals to Phase 15

| Capability | Why deferred |
|---|---|
| Animated transitions (xfade, fade) | Phase 14 uses hard cuts/concat only — structural correctness first |
| Template loader (`templates/*.yaml`) | Phase 15 scope |
| Card color/font from niche config | Phase 14 uses sensible defaults; Phase 15 applies template styling |
| Template-driven thumbnail generation | Phase 14 thumbnail from video first frame; Phase 15 uses templates |
| Voice-aligned scene captions | Phase 14 captions from scriptwriter output; Phase 15 times them to audio |
| Animation overlays (lower thirds, text) | Phase 15 creative rendering |
