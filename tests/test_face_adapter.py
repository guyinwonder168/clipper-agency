"""TDD tests for MediaPipe face detection runtime adapter (Tasks API).

All tests mock MediaPipe — no real model loaded, no paid API calls, no network.
The mock layer fakes the modern Tasks API (``mediapipe.tasks.python.vision
.face_detector``) with absolute-pixel bounding boxes, matching the production
adapter in ``clipper_agency/core/face_adapter.py``.
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipper_agency.config.schema import (
    FaceDetectionConfig,
    FaceInspectionResult,
)
from clipper_agency.core import face_adapter
from clipper_agency.core.face_adapter import (
    FaceDetector,
    MediaPipeFaceDetector,
)

# ---------------------------------------------------------------------------
# Mock factories — Tasks-API Detection objects (absolute-pixel bounding_box)
# ---------------------------------------------------------------------------


def _face(xmin: int, ymin: int, xmax: int, ymax: int, score: float):
    """Return a mock Tasks-API Detection with an absolute-pixel bounding box.

    ``[xmin, ymin, xmax, ymax]`` is converted to the Tasks ``bounding_box``
    shape (``origin_x, origin_y, width, height``) plus a single category score.
    """
    det = MagicMock()
    bb = MagicMock()
    bb.origin_x = xmin
    bb.origin_y = ymin
    bb.width = xmax - xmin
    bb.height = ymax - ymin
    det.bounding_box = bb
    cat = MagicMock()
    cat.score = score
    det.categories = [cat]
    return det


def _mock_result(detections):
    """Return a mock FaceDetector.detect() result."""
    result = MagicMock()
    result.detections = detections
    return result


def _mock_cv2_image(width=1920, height=1080):
    """Return a mock numpy-like array with shape (height, width, 3)."""
    img = MagicMock()
    img.shape = (height, width, 3)
    return img


# ---------------------------------------------------------------------------
# Core helper: fake MediaPipe Tasks API modules in sys.modules
# ---------------------------------------------------------------------------


@contextmanager
def _fake_mediapipe_tasks():
    """Context manager that fakes the MediaPipe Tasks API in sys.modules.

    Yields ``mock_fd_module`` (fake ``face_detector`` module) so tests can
    configure ``FaceDetector.create_from_options``. On exit, all
    ``mediapipe*`` keys are removed from ``sys.modules``.
    """
    saved = {}
    for key in list(sys.modules):
        if key.startswith("mediapipe"):
            saved[key] = sys.modules.pop(key)

    mock_mp = MagicMock()
    mock_mp.ImageFormat.SRGB = "SRGB"
    mock_mp.Image = MagicMock()  # mp.Image(...) -> opaque image object

    mock_bo_module = MagicMock()
    mock_fd_module = MagicMock()
    # Build the tasks submodule tree with EXPLICIT attribute links so that
    # `from mediapipe.tasks.python.<pkg> import <sub>` resolves via getattr on
    # the parent mock to these submodules (not auto-created attributes).
    mock_core = MagicMock()
    mock_core.base_options = mock_bo_module
    mock_vision = MagicMock()
    mock_vision.face_detector = mock_fd_module
    mock_python = MagicMock()
    mock_python.core = mock_core
    mock_python.vision = mock_vision
    mock_tasks = MagicMock()
    mock_tasks.python = mock_python

    sys.modules["mediapipe"] = mock_mp
    sys.modules["mediapipe.tasks"] = mock_tasks
    sys.modules["mediapipe.tasks.python"] = mock_python
    sys.modules["mediapipe.tasks.python.core"] = mock_core
    sys.modules["mediapipe.tasks.python.core.base_options"] = mock_bo_module
    sys.modules["mediapipe.tasks.python.vision"] = mock_vision
    sys.modules["mediapipe.tasks.python.vision.face_detector"] = mock_fd_module

    # Reset the class-level model so each test starts fresh
    MediaPipeFaceDetector._reset_model()

    try:
        yield mock_fd_module
    finally:
        for key in list(sys.modules):
            if key.startswith("mediapipe"):
                del sys.modules[key]
        sys.modules.update(saved)


@contextmanager
def _mock_face_adapter_env(cv2_image=None):
    """Context manager combining fake Tasks mediapipe, mocked cv2, and a mocked
    model-download (no network). Yields ``(mock_fd, mock_model)``.
    """
    if cv2_image is None:
        cv2_image = _mock_cv2_image()

    mock_cv2 = MagicMock()
    mock_cv2.imread.return_value = cv2_image
    mock_cv2.COLOR_BGR2RGB = 4  # cv2 constant value
    mock_cv2.cvtColor.return_value = cv2_image

    saved_cv2 = sys.modules.get("cv2")
    sys.modules["cv2"] = mock_cv2

    def _fake_ensure_cached(_model_selection: int = 1) -> Path:
        return Path("/fake/model.tflite")

    with (
        _fake_mediapipe_tasks() as mock_fd,
        patch.object(face_adapter, "_ensure_model_cached", side_effect=_fake_ensure_cached),
    ):
        mock_model = MagicMock()
        mock_fd.FaceDetector.create_from_options.return_value = mock_model
        try:
            yield mock_fd, mock_model
        finally:
            if saved_cv2 is not None:
                sys.modules["cv2"] = saved_cv2
            else:
                sys.modules.pop("cv2", None)


# ---------------------------------------------------------------------------
# Test: Protocol compliance
# ---------------------------------------------------------------------------


class TestFaceDetectorProtocol:
    def test_mediapipe_detector_satisfies_protocol(self):
        """MediaPipeFaceDetector is a structural subtype of FaceDetector."""
        det = MediaPipeFaceDetector()
        assert isinstance(det, FaceDetector)


# ---------------------------------------------------------------------------
# Test: Lazy import
# ---------------------------------------------------------------------------


class TestLazyImport:
    def test_mediapipe_not_imported_at_module_level(self):
        """mediapipe must NOT be in sys.modules before first detect()."""
        for key in list(sys.modules):
            if key.startswith("mediapipe"):
                del sys.modules[key]
        if "clipper_agency.core.face_adapter" in sys.modules:
            del sys.modules["clipper_agency.core.face_adapter"]

        from clipper_agency.core import face_adapter as fresh_module

        msg = "mediapipe must NOT be imported at module level"
        assert "mediapipe" not in sys.modules, msg
        assert not hasattr(fresh_module, "mp"), "mp must not be at module level"

    def test_mediapipe_is_lazily_imported_on_first_detect(self):
        """mediapipe Tasks API is wired only when detect() is first called."""
        for key in list(sys.modules):
            if key.startswith("mediapipe"):
                del sys.modules[key]
        if "clipper_agency.core.face_adapter" in sys.modules:
            del sys.modules["clipper_agency.core.face_adapter"]

        from clipper_agency.core.face_adapter import MediaPipeFaceDetector as MFD

        MFD._reset_model()
        assert "mediapipe" not in sys.modules

        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([])
            detector = MFD()
            _ = detector.detect("/fake/img.jpg", 0.0)

            # Lazy init triggered: FaceDetector.create_from_options called once
            assert mock_fd.FaceDetector.create_from_options.called, (
                "Lazy model init should be triggered by detect()"
            )


# ---------------------------------------------------------------------------
# Test: Basic detection
# ---------------------------------------------------------------------------


class TestBasicDetection:
    def test_returns_face_inspection_result_with_faces(self):
        """A single high-confidence detection produces one FaceRegion."""
        with _mock_face_adapter_env(_mock_cv2_image(800, 600)) as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(80, 60, 320, 300, 0.95)])
            detector = MediaPipeFaceDetector()
            result = detector.detect("faces.jpg", 3.5)

        assert isinstance(result, FaceInspectionResult)
        assert len(result.faces) == 1
        assert result.timestamp_sec == 3.5

    def test_multiple_faces_detected_and_returned(self):
        """Three faces above threshold -> all three returned."""
        detections = [
            _face(100, 100, 300, 320, 0.90),
            _face(500, 100, 800, 420, 0.85),
            _face(200, 600, 450, 850, 0.80),
        ]
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result(detections)
            detector = MediaPipeFaceDetector()
            result = detector.detect("crowd.jpg", 0.0)

        assert len(result.faces) == 3

    def test_empty_image_no_faces(self):
        """No detections -> empty faces list, not an error."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([])
            detector = MediaPipeFaceDetector()
            result = detector.detect("empty.jpg", 0.0)

        assert result.faces == []


# ---------------------------------------------------------------------------
# Test: Confidence threshold
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    def test_faces_below_confidence_filtered_out(self):
        """Faces with score < min_confidence are excluded."""
        detections = [
            _face(100, 100, 300, 320, 0.95),  # keep
            _face(500, 500, 700, 720, 0.45),  # filter
            _face(300, 300, 500, 520, 0.59),  # filter (below 0.60)
        ]
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result(detections)
            detector = MediaPipeFaceDetector(min_confidence=0.60)
            result = detector.detect("faces.jpg", 0.0)

        assert len(result.faces) == 1
        assert result.faces[0].confidence == 0.95

    def test_default_confidence_from_config(self):
        """Default min_confidence comes from FaceDetectionConfig."""
        config = FaceDetectionConfig()
        detector = MediaPipeFaceDetector()
        assert detector.min_confidence == config.min_confidence
        assert detector.min_confidence == 0.60

    def test_custom_confidence_threshold(self):
        """Confidence threshold is configurable at construction."""
        detector = MediaPipeFaceDetector(min_confidence=0.80)
        assert detector.min_confidence == 0.80

    def test_custom_threshold_filters_correctly(self):
        """Custom threshold of 0.80 filters faces below it."""
        detections = [
            _face(100, 100, 300, 320, 0.95),
            _face(500, 500, 700, 720, 0.75),  # below 0.80
        ]
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result(detections)
            detector = MediaPipeFaceDetector(min_confidence=0.80)
            result = detector.detect("faces.jpg", 0.0)

        assert len(result.faces) == 1
        assert result.faces[0].confidence == 0.95


# ---------------------------------------------------------------------------
# Test: Primary face selection
# ---------------------------------------------------------------------------


class TestPrimaryFaceSelection:
    def test_primary_face_selected_by_largest_area(self):
        """When areas differ, the largest face is primary."""
        detections = [
            _face(100, 100, 400, 400, 0.90),  # 300x300 -> smaller
            _face(300, 300, 800, 800, 0.85),  # 500x500 -> larger -> primary
        ]
        with _mock_face_adapter_env(_mock_cv2_image(1000, 1000)) as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result(detections)
            detector = MediaPipeFaceDetector()
            result = detector.detect("faces.jpg", 0.0)

        assert len(result.faces) == 2
        primary = [f for f in result.faces if f.is_primary]
        assert len(primary) == 1
        assert primary[0].bbox == [300, 300, 800, 800]

    def test_primary_face_by_centrality_when_areas_equal(self):
        """When areas are equal, the face closest to center wins."""
        # Both 200x200; face2 is closer to the 1000x1000 center (500,500).
        detections = [
            _face(50, 50, 250, 250, 0.90),
            _face(500, 500, 700, 700, 0.90),
        ]
        with _mock_face_adapter_env(_mock_cv2_image(1000, 1000)) as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result(detections)
            detector = MediaPipeFaceDetector()
            result = detector.detect("faces.jpg", 0.0)

        primary = [f for f in result.faces if f.is_primary]
        assert len(primary) == 1
        assert primary[0].bbox == [500, 500, 700, 700]

    def test_single_face_is_always_primary(self):
        """A single detected face is marked as primary."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(200, 200, 600, 600, 0.90)])
            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert len(result.faces) == 1
        assert result.faces[0].is_primary is True


# ---------------------------------------------------------------------------
# Test: Bounding box passthrough (absolute pixels)
# ---------------------------------------------------------------------------


class TestBBoxPassthrough:
    def test_absolute_bbox_passed_through(self):
        """Tasks-API absolute-pixel bounding_box -> FaceRegion.bbox unchanged."""
        with _mock_face_adapter_env(_mock_cv2_image(800, 600)) as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(80, 120, 320, 360, 0.95)])
            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert result.faces[0].bbox == [80, 120, 320, 360]

    def test_various_image_sizes(self):
        """BBox passthrough works regardless of image dimensions."""
        sizes = [(640, 480), (1920, 1080), (720, 1280)]
        for w, h in sizes:
            with _mock_face_adapter_env(_mock_cv2_image(w, h)) as (mock_fd, mock_model):
                mock_model.detect.return_value = _mock_result([_face(0, 0, w, h, 0.95)])
                detector = MediaPipeFaceDetector()
                result = detector.detect("face.jpg", 0.0)

            assert result.faces[0].bbox == [0, 0, w, h], f"Failed for {w}x{h}"


# ---------------------------------------------------------------------------
# Test: Provider/model metadata
# ---------------------------------------------------------------------------


class TestProviderMetadata:
    def test_result_includes_provider_and_model(self):
        """FaceInspectionResult carries provider and model metadata."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert result.provider == "mediapipe"
        assert "face_detection" in result.model
        assert result.model != ""

    def test_default_model_selection_is_full_range(self):
        """Default (model_selection=1) must report the FULL-range model name."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert detector.model_selection == 1
        assert result.model == "face_detection_full_range"


# ---------------------------------------------------------------------------
# Test: Timestamp propagation
# ---------------------------------------------------------------------------


class TestTimestampPropagation:
    def test_detect_propagates_timestamp_sec(self):
        """timestamp_sec is carried through to FaceInspectionResult."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector()
            for ts in [0.0, 2.5, 59.123, 120.0]:
                result = detector.detect("face.jpg", ts)
                assert result.timestamp_sec == ts, f"Failed at timestamp {ts}"


# ---------------------------------------------------------------------------
# Test: Model singleton / reuse
# ---------------------------------------------------------------------------


class TestModelReuse:
    def test_model_is_reused_across_calls(self):
        """The FaceDetector is created once and reused (singleton behavior)."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector()
            detector.detect("a.jpg", 0.0)
            detector.detect("b.jpg", 1.0)
            detector.detect("c.jpg", 2.0)

        # create_from_options called only once
        assert mock_fd.FaceDetector.create_from_options.call_count == 1

    def test_model_singleton_respected_across_detector_instances(self):
        """Multiple MediaPipeFaceDetector instances share the class-level model."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            d1 = MediaPipeFaceDetector()
            d2 = MediaPipeFaceDetector()
            d1.detect("a.jpg", 0.0)
            d2.detect("b.jpg", 1.0)

        assert mock_fd.FaceDetector.create_from_options.call_count == 1


# ---------------------------------------------------------------------------
# Test: model_selection -> BlazeFace range mapping
# ---------------------------------------------------------------------------


class TestModelSelectionMapping:
    """model_selection must map to the correct BlazeFace model + metadata.

    Legacy solutions-API semantics: 0=short-range, 1=full-range (DEFAULT).
    """

    def test_model_selection_zero_reports_short_range(self):
        """model_selection=0 -> 'face_detection_short_range' metadata."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector(model_selection=0)
            result = detector.detect("face.jpg", 0.0)

        assert result.model == "face_detection_short_range"

    def test_model_selection_one_reports_full_range(self):
        """model_selection=1 -> 'face_detection_full_range' metadata."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector(model_selection=1)
            result = detector.detect("face.jpg", 0.0)

        assert result.model == "face_detection_full_range"

    def test_model_selection_zero_downloads_short_range_model(self):
        """model_selection=0 routes the SHORT-range URL/cache path through."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector(model_selection=0)
            detector.detect("face.jpg", 0.0)

            # The patched _ensure_model_cached was invoked with model_selection=0.
            face_adapter._ensure_model_cached.assert_called_with(0)

        # The short-range spec carries the short-range URL + cache filename.
        spec = face_adapter._resolve_model_spec(0)
        assert "blaze_face_short_range" in spec["url"]
        assert spec["cache_path"].name == "blaze_face_short_range.tflite"
        assert spec["name"] == "face_detection_short_range"

    def test_model_selection_one_downloads_full_range_model(self):
        """model_selection=1 routes the FULL-range URL/cache path through."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            detector = MediaPipeFaceDetector(model_selection=1)
            detector.detect("face.jpg", 0.0)

            # The patched _ensure_model_cached was invoked with model_selection=1.
            face_adapter._ensure_model_cached.assert_called_with(1)

        # The full-range spec carries the full-range URL + cache filename.
        spec = face_adapter._resolve_model_spec(1)
        assert "blaze_face_full_range" in spec["url"]
        assert spec["cache_path"].name == "blaze_face_full_range.tflite"
        assert spec["name"] == "face_detection_full_range"

    def test_model_selection_two_falls_back_to_full_range(self):
        """Unknown model_selection values fall back to the full-range spec."""
        spec = face_adapter._resolve_model_spec(2)
        assert spec is face_adapter._MODEL_SPECS[1]
        assert spec["name"] == "face_detection_full_range"


class TestSingletonKeyPerModelSelection:
    """The singleton must key on (model_selection, min_confidence) so a second
    range in the same process loads its own BlazeFace model."""

    def test_two_ranges_load_two_models(self):
        """Short-range and full-range detectors each build their own model."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            short = MediaPipeFaceDetector(model_selection=0)
            full = MediaPipeFaceDetector(model_selection=1)
            short.detect("a.jpg", 0.0)
            full.detect("b.jpg", 1.0)

        assert mock_fd.FaceDetector.create_from_options.call_count == 2

    def test_same_range_reuses_one_model(self):
        """Two detectors with the same range+threshold share one model."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.90)])
            d1 = MediaPipeFaceDetector(model_selection=0)
            d2 = MediaPipeFaceDetector(model_selection=0)
            d1.detect("a.jpg", 0.0)
            d2.detect("b.jpg", 1.0)

        assert mock_fd.FaceDetector.create_from_options.call_count == 1


# ---------------------------------------------------------------------------
# Test: Score extraction (Tasks categories)
# ---------------------------------------------------------------------------


class TestScoreExtraction:
    def test_score_taken_from_categories(self):
        """The confidence is the max of the detection's category scores."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.93)])
            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert len(result.faces) == 1
        assert result.faces[0].confidence == 0.93


# ---------------------------------------------------------------------------
# Test: No identity recognition
# ---------------------------------------------------------------------------


class TestNoIdentityRecognition:
    def test_face_regions_have_no_identity_data(self):
        """FaceRegion only has bbox, confidence, is_primary — no identity fields."""
        with _mock_face_adapter_env() as (mock_fd, mock_model):
            mock_model.detect.return_value = _mock_result([_face(100, 100, 300, 300, 0.95)])
            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        face = result.faces[0]
        assert set(face.model_dump().keys()) == {"bbox", "confidence", "is_primary"}


# ---------------------------------------------------------------------------
# Test: Graceful degradation (no per-frame storm)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_missing_mediapipe_returns_empty_not_raise(self):
        """If MediaPipe/model init fails, detect() returns empty + logs once.

        This is the fix for the per-frame ``ModuleNotFoundError`` log storm:
        the adapter must degrade silently after the first failure rather than
        raise on every frame.
        """

        @contextmanager
        def _no_mediapipe():
            saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("mediapipe")}
            # Ensure _build_model's `import mediapipe` raises ImportError.
            import builtins

            real_import = builtins.__import__

            def _block(name, *a, **k):
                if name.startswith("mediapipe"):
                    raise ModuleNotFoundError(f"No module named '{name}'")
                return real_import(name, *a, **k)

            builtins.__import__ = _block
            MediaPipeFaceDetector._reset_model()
            try:
                yield
            finally:
                builtins.__import__ = real_import
                sys.modules.update(saved)

        with _no_mediapipe():
            detector = MediaPipeFaceDetector()
            r1 = detector.detect("face.jpg", 0.0)
            r2 = detector.detect("face.jpg", 1.0)  # must not re-attempt / re-raise

        assert r1.faces == [] and r2.faces == []
        assert r1.model == "face_detection_unavailable"
        assert MediaPipeFaceDetector._unavailable is True


# ---------------------------------------------------------------------------
# Test: Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    def test_face_detection_config_provides_defaults(self):
        """FaceDetectionConfig provides the default provider and confidence."""
        config = FaceDetectionConfig()
        assert config.provider == "mediapipe"
        assert config.min_confidence == 0.60
        assert config.enabled is True

    def test_default_detector_uses_config_defaults(self):
        """MediaPipeFaceDetector() uses FaceDetectionConfig defaults."""
        detector = MediaPipeFaceDetector()
        assert detector.min_confidence == FaceDetectionConfig().min_confidence
