# Scene Normalizer Framerate Fix — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix FFmpeg concat hang caused by mixed framerates — normalize all scenes to 30fps and convert still images to animated video clips with Ken Burns zoompan effect.

**Architecture:** Two-part fix in `SceneNormalizer`: (1) add `-r 30` to video normalization pipeline to unify framerate, (2) add image-to-video path that uses `zoompan` filter to create 5-second animated clips at 30fps from JPEG/PNG inputs. Add `fps` field to `VideoInfo` dataclass for framerate detection.

**Tech Stack:** Python 3.11+, FFmpeg (zoompan, scale, pad, setsar), ffprobe (r_frame_rate), pytest + mocker

**Branch:** `fix/scene-normalizer-framerate` (already created from latest master)

**Root Cause:** `SceneNormalizer` only normalizes resolution (1080×1920) and SAR — it does NOT normalize framerate. After normalization, scenes had mixed FPS (25/30/50) and image-to-video scenes were only 0.04s (1 frame). FFmpeg `concat` with mixed framerates causes massive frame duplication → appears hung.

---

## Chunk 1: Framerate Detection + Video Normalization

### Task 1: Add `fps` field to `VideoInfo` dataclass

**Files:**
- Modify: `clipper_agency/core/media_probe.py:12-24` (VideoInfo dataclass)
- Modify: `clipper_agency/core/media_probe.py:67-108` (probe_video function)
- Test: `tests/test_media_probe.py`

- [x] **Step 1: Write the failing test**

Add to `tests/test_media_probe.py`:

```python
def test_probe_video_extracts_fps(self, tmp_path):
    """ffprobe returns r_frame_rate as part of video stream metadata."""
    mock_output = json.dumps({
        "streams": [{
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "sample_aspect_ratio": "1:1",
            "r_frame_rate": "30/1",
        }],
        "format": {"duration": "10.5"},
    }).encode()
    mocker.patch("subprocess.check_output", return_value=mock_output)
    # Need tmp file to exist for stat
    f = tmp_path / "video.mp4"
    f.write_bytes(b"x" * 100)

    info = probe_video(str(f), str(tmp_path))
    assert info is not None
    assert info.fps == 30
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_media_probe.py::TestMediaProbe::test_probe_video_extracts_fps -v`
Expected: FAIL — `VideoInfo` has no `fps` field

- [x] **Step 3: Add `fps` field to `VideoInfo` and parse `r_frame_rate` from probe**

In `media_probe.py`, add `fps: int = 30` field to `VideoInfo` dataclass:

```python
@dataclass(frozen=True)
class VideoInfo:
    """Immutable video metadata extracted via ffprobe."""
    path: str
    width: int
    height: int
    codec: str
    pix_fmt: str
    duration: float | None
    has_audio: bool = False
    file_size: int = 0
    sample_aspect_ratio: str = "1:1"
    fps: int = 30
```

In `probe_video()`, parse `r_frame_rate` from video stream after the SAR block:

```python
    # --- framerate ---
    fps = 30  # default
    r_frame_rate = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = r_frame_rate.split("/")
        if int(den) > 0:
            fps = int(int(num) / int(den))
    except (ValueError, ZeroDivisionError):
        fps = 30
```

Add `fps=fps` to the `VideoInfo(...)` constructor call.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_media_probe.py::TestMediaProbe::test_probe_video_extracts_fps -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add clipper_agency/core/media_probe.py tests/test_media_probe.py
git commit -m "feat: add fps field to VideoInfo, parse r_frame_rate from ffprobe"
```

---

### Task 2: Add `-r 30` to video normalization pipeline

**Files:**
- Modify: `clipper_agency/core/scene_normalizer.py:56-76` (FFmpeg command builder)
- Test: `tests/test_scene_normalizer.py`

- [x] **Step 1: Write the failing test**

Add to `tests/test_scene_normalizer.py`:

```python
def test_normalize_sets_framerate_to_30(self, tmp_path, mocker):
    """All video output must be 30fps for TikTok concat compatibility."""
    mock_ffmpeg = mocker.patch(
        "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
        return_value="",
    )

    input_file = tmp_path / "in.mp4"
    input_file.write_bytes(b"x" * 10000)

    normalizer = SceneNormalizer()
    normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

    cmd_args = " ".join(mock_ffmpeg.call_args[0][0])
    assert "-r" in cmd_args
    # Find the value after -r
    cmd_list = mock_ffmpeg.call_args[0][0]
    r_index = cmd_list.index("-r")
    assert cmd_list[r_index + 1] == "30"
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py::TestSceneNormalizer::test_normalize_sets_framerate_to_30 -v`
Expected: FAIL — `-r 30` not in command

- [x] **Step 3: Add `-r 30` to the FFmpeg command**

In `scene_normalizer.py`, add `-r`, `30` after `-an` in the `cmd` list:

```python
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-vf",
            (
                f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}"
                ":force_original_aspect_ratio=decrease,"
                f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1"
            ),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r", "30",
            "-an",
            "-map_metadata",
            "-1",
            output_path,
        ]
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py::TestSceneNormalizer::test_normalize_sets_framerate_to_30 -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add clipper_agency/core/scene_normalizer.py tests/test_scene_normalizer.py
git commit -m "feat: add -r 30 to scene normalizer for framerate unification"
```

---

### Task 3: Do NOT skip normalization when FPS differs from 30

**Files:**
- Modify: `clipper_agency/core/scene_normalizer.py:40-54` (skip-check logic)
- Test: `tests/test_scene_normalizer.py`

Currently, the skip check only looks at resolution + SAR. It should also check that fps is already 30. If a 1080×1920 SAR 1:1 video is 50fps, it still needs normalization to `-r 30`.

- [x] **Step 1: Write the failing test**

```python
def test_normalize_does_not_skip_when_fps_not_30(self, tmp_path, mocker):
    """Clip already 1080x1920 SAR 1:1 but 50fps must still be normalized."""
    mocker.patch("clipper_agency.core.media_probe.probe_video",
                  return_value=mocker.Mock(
                      width=1080, height=1920,
                      sample_aspect_ratio="1:1",
                      fps=50))

    mock_ffmpeg = mocker.patch(
        "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
        return_value="",
    )

    input_file = tmp_path / "in.mp4"
    input_file.write_bytes(b"x" * 10000)

    normalizer = SceneNormalizer()
    result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

    assert result.success is True
    mock_ffmpeg.assert_called_once()
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py::TestSceneNormalizer::test_normalize_does_not_skip_when_fps_not_30 -v`
Expected: FAIL — normalizer skips because resolution+SAR match, mock_ffmpeg not called

- [x] **Step 3: Update skip-check to include fps**

In `scene_normalizer.py`, update the skip condition:

```python
            sar_ok = info.sample_aspect_ratio == "1:1"
            fps_ok = getattr(info, "fps", 30) == 30
            if (
                info
                and info.width == self.TARGET_WIDTH
                and info.height == self.TARGET_HEIGHT
                and sar_ok
                and fps_ok
            ):
                return NormalizeResult(path=input_path, success=True)
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py::TestSceneNormalizer::test_normalize_does_not_skip_when_fps_not_30 -v`
Expected: PASS

- [x] **Step 5: Run existing tests to verify no regressions**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py -v`
Expected: ALL PASS (8 tests now)

- [x] **Step 6: Commit**

```bash
git add clipper_agency/core/scene_normalizer.py tests/test_scene_normalizer.py
git commit -m "feat: skip normalization only when fps is already 30"
```

---

## Chunk 2: Image-to-Video with Ken Burns Zoompan

### Task 4: Add image-to-video conversion path in `SceneNormalizer`

**Files:**
- Modify: `clipper_agency/core/scene_normalizer.py` (add `_is_image()` + `_normalize_image()`)
- Test: `tests/test_scene_normalizer.py`

Images (.jpg, .jpeg, .png, .webp) need a completely different FFmpeg pipeline:
- `zoompan` filter for Ken Burns animation (slow zoom in)
- `-t 5` for 5-second duration
- `-r 30` for 30fps output
- Scale+pad to 1080×1920 within the zoompan filter

- [x] **Step 1: Write the failing test**

```python
def test_normalize_image_uses_zoompan(self, tmp_path, mocker):
    """Image files (.jpg/.png) get zoompan Ken Burns animation, 5s at 30fps."""
    mock_ffmpeg = mocker.patch(
        "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
        return_value="",
    )

    input_file = tmp_path / "scene_1.jpg"
    input_file.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 10000)  # JPEG-ish bytes

    normalizer = SceneNormalizer()
    result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

    assert result.success is True
    mock_ffmpeg.assert_called_once()
    cmd_list = mock_ffmpeg.call_args[0][0]
    cmd_args = " ".join(cmd_list)

    assert "zoompan" in cmd_args
    assert "-t" in cmd_list
    t_index = cmd_list.index("-t")
    assert cmd_list[t_index + 1] == "5"
```

```python
def test_normalize_image_ken_burns_zoom_in(self, tmp_path, mocker):
    """Default zoompan direction is zoom-in (scale goes from 1.0 to 1.2)."""
    mock_ffmpeg = mocker.patch(
        "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
        return_value="",
    )

    input_file = tmp_path / "scene_1.png"
    input_file.write_bytes(b"\x89PNG" + b"x" * 10000)  # PNG-ish bytes

    normalizer = SceneNormalizer()
    result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

    assert result.success is True
    cmd_args = " ".join(mock_ffmpeg.call_args[0][0])
    # zoompan=z='min(zoom+0.001,1.2)' means slow zoom in from 1.0 to 1.2
    assert "zoom+0.001" in cmd_args
```

```python
def test_normalize_image_png_detected(self, tmp_path, mocker):
    """PNG files are also detected as images."""
    mock_ffmpeg = mocker.patch(
        "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
        return_value="",
    )

    input_file = tmp_path / "image.png"
    input_file.write_bytes(b"x" * 100)

    normalizer = SceneNormalizer()
    result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

    assert result.success is True
    mock_ffmpeg.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py::TestSceneNormalizer::test_normalize_image_uses_zoompan tests/test_scene_normalizer.py::TestSceneNormalizer::test_normalize_image_ken_burns_zoom_in tests/test_scene_normalizer.py::TestSceneNormalizer::test_normalize_image_png_detected -v`
Expected: ALL FAIL — no image detection path

- [x] **Step 3: Implement image detection + zoompan normalization**

Add to `scene_normalizer.py`:

```python
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_IMAGE_DURATION = 5  # seconds per image scene
_KEN_BURNS_FRAMES = 150  # 5s * 30fps


class SceneNormalizer:
    # ... existing code ...

    @staticmethod
    def _is_image(path: str) -> bool:
        """Return True if the file extension indicates a still image."""
        return Path(path).suffix.lower() in _IMAGE_EXTENSIONS

    def _normalize_image(self, input_path: str, output_path: str) -> NormalizeResult:
        """Convert still image to 5s 30fps 1080x1920 video with Ken Burns zoompan."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-vf",
            (
                f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}"
                ":force_original_aspect_ratio=decrease,"
                f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                f"zoompan=z='min(zoom+0.001,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={_KEN_BURNS_FRAMES}:s={self.TARGET_WIDTH}x{self.TARGET_HEIGHT}:fps=30,"
                "setsar=1"
            ),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-t", str(_IMAGE_DURATION),
            "-an",
            "-map_metadata", "-1",
            output_path,
        ]

        try:
            logger.debug(
                "Normalizer: image→video %s (ken burns, %ds)",
                Path(input_path).name, _IMAGE_DURATION,
            )
            stderr_text = run_ffmpeg_streaming(cmd, timeout=_NORMALIZE_TIMEOUT, label="image-normalize")
            return NormalizeResult(path=output_path, success=True, stderr=stderr_text)
        except FileNotFoundError:
            return NormalizeResult(path=input_path, success=False, error="FFmpeg not found")
        except subprocess.TimeoutExpired:
            return NormalizeResult(path=input_path, success=False, error=f"FFmpeg timed out ({_NORMALIZE_TIMEOUT}s)")
        except subprocess.CalledProcessError as e:
            return NormalizeResult(path=input_path, success=False, error=f"FFmpeg exit code {e.returncode}", stderr=e.stderr or "")
```

Then update `normalize()` to route images to `_normalize_image()`:

```python
    def normalize(self, input_path: str, output_path: str) -> NormalizeResult:
        if not os.path.isfile(input_path):
            return NormalizeResult(path=input_path, success=False, error=f"Input not found: {input_path}")

        # Image path — always process with zoompan
        if self._is_image(input_path):
            return self._normalize_image(input_path, output_path)

        # Video path — probe and maybe skip
        # ... existing probe + video normalization code ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py -v`
Expected: ALL PASS (11 tests now: 8 original + 3 new)

- [x] **Step 5: Commit**

```bash
git add clipper_agency/core/scene_normalizer.py tests/test_scene_normalizer.py
git commit -m "feat: image-to-video conversion with Ken Burns zoompan animation"
```

---

### Task 5: Increase normalizer timeout for zoompan

**Files:**
- Modify: `clipper_agency/core/scene_normalizer.py` (timeout for images)

Zoompan is CPU-intensive. A 5-second clip at 1080×1920 takes longer than 120s on slow machines.

- [x] **Step 1: Update timeout constants**

At the top of `scene_normalizer.py`, change:

```python
_NORMALIZE_TIMEOUT = 120  # seconds
_IMAGE_NORMALIZE_TIMEOUT = 300  # seconds — zoompan is CPU-intensive
```

Update `_normalize_image()` to use the longer timeout:

```python
            stderr_text = run_ffmpeg_streaming(cmd, timeout=_IMAGE_NORMALIZE_TIMEOUT, label="image-normalize")
```

- [x] **Step 2: Run all normalizer tests**

Run: `.venv/bin/python3 -m pytest tests/test_scene_normalizer.py -v`
Expected: ALL PASS

- [x] **Step 3: Commit**

```bash
git add clipper_agency/core/scene_normalizer.py
git commit -m "chore: increase image normalization timeout for zoompan CPU load"
```

---

## Chunk 3: Integration Verification

### Task 6: Run full offline test suite + verify no regressions

**Files:** No code changes — verification only.

- [x] **Step 1: Run full offline test suite** — 669 passed, 2 deselected ✅
- [x] **Step 2: Run coverage check** — ≥93% ✅
- [x] **Step 3: Commit adjustments + coverage tests** — PR #33 merged ✅

---

### Task 7: Push branch + create PR

- [x] **Step 1: Push branch** — `fix/scene-normalizer-framerate` pushed ✅
- [x] **Step 2: Create PR** — PR #32 created, reviewed, SonarCloud fixed ✅
- [x] **Step 3: SonarCloud green + merge** — PR #32 merged; PR #33 (review fix: fps flooring) merged; both branches deleted ✅

**Tier 1 complete.** Merged to master at `32e895e`.

---

## Summary of Changes

| File | Change |
|------|--------|
| `clipper_agency/core/media_probe.py` | Add `fps: int = 30` field, parse `r_frame_rate` from ffprobe |
| `clipper_agency/core/scene_normalizer.py` | Add `-r 30` for videos; add `_is_image()` + `_normalize_image()` for images with zoompan; update skip-check to include fps |
| `tests/test_media_probe.py` | Add test for fps extraction |
| `tests/test_scene_normalizer.py` | Add 4 tests: framerate flag, fps-aware skip, image zoompan, Ken Burns params, PNG detection |

**Expected new test count:** +4 tests (from 7 → 11 in test_scene_normalizer, +1 in test_media_probe)
