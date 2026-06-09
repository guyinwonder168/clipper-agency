"""TDD tests for MediaPipe face detection runtime adapter.

All tests mock MediaPipe — no real model loaded, no paid API calls.
"""

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

from clipper_agency.config.schema import (
    FaceDetectionConfig,
    FaceInspectionResult,
)
from clipper_agency.core.face_adapter import (
    FaceDetector,
    MediaPipeFaceDetector,
)

# ---------------------------------------------------------------------------
# Mock factories — construct mock MediaPipe Detection objects
# ---------------------------------------------------------------------------


def _mock_detection(xmin, ymin, width, height, score):
    """Return a mock MediaPipe Detection with relative_bounding_box."""
    det = MagicMock()
    bbox = MagicMock()
    bbox.xmin = xmin
    bbox.ymin = ymin
    bbox.width = width
    bbox.height = height
    det.location_data.relative_bounding_box = bbox
    det.score = [score]  # score is a list in MediaPipe detection
    return det


def _mock_detection_single_score(xmin, ymin, width, height, score):
    """Return a mock Detection where score is a single float (newer API)."""
    det = MagicMock()
    bbox = MagicMock()
    bbox.xmin = xmin
    bbox.ymin = ymin
    bbox.width = width
    bbox.height = height
    det.location_data.relative_bounding_box = bbox
    det.score = score  # single float
    return det


def _mock_mp_image(width=1920, height=1080):
    """Return a mock mp.Image with dimensions."""
    img = MagicMock()
    img.width = width
    img.height = height
    return img


def _mock_process_result(detections):
    """Return a mock FaceDetection.process() result."""
    result = MagicMock()
    result.detections = detections
    return result


# ---------------------------------------------------------------------------
# Core helper: set up structured fake mediapipe modules in sys.modules
# ---------------------------------------------------------------------------


@contextmanager
def _fake_mediapipe():
    """Context manager that sets up fake mediapipe modules in sys.modules.

    Yields ``(mock_image_cls, mock_fd_module)`` so tests can configure
    the fake ``mp.Image`` and ``FaceDetection`` with appropriate return values.

    On exit, all ``mediapipe*`` keys are removed from ``sys.modules``.
    """
    saved = {}
    for key in list(sys.modules):
        if key.startswith("mediapipe"):
            saved[key] = sys.modules.pop(key)

    mock_mp = MagicMock()
    mock_image_cls = MagicMock()
    mock_fd_module = MagicMock()
    mock_solutions = MagicMock()

    mock_mp.Image = mock_image_cls
    mock_mp.solutions = mock_solutions
    mock_solutions.face_detection = mock_fd_module

    sys.modules["mediapipe"] = mock_mp
    sys.modules["mediapipe.solutions"] = mock_solutions
    sys.modules["mediapipe.solutions.face_detection"] = mock_fd_module

    # Reset the class-level model so each test starts fresh
    MediaPipeFaceDetector._reset_model()

    try:
        yield mock_image_cls, mock_fd_module
    finally:
        for key in list(sys.modules):
            if key.startswith("mediapipe"):
                del sys.modules[key]
        sys.modules.update(saved)


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
        # Ensure mediapipe is removed if already loaded
        for key in list(sys.modules):
            if key.startswith("mediapipe"):
                del sys.modules[key]

        # Re-import the adapter fresh
        if "clipper_agency.core.face_adapter" in sys.modules:
            del sys.modules["clipper_agency.core.face_adapter"]

        from clipper_agency.core import face_adapter as fresh_module

        msg = "mediapipe must NOT be imported at module level"
        assert "mediapipe" not in sys.modules, msg
        assert not hasattr(fresh_module, "mp"), "mp must not be at module level"

    def test_mediapipe_is_lazily_imported_on_first_detect(self):
        """mediapipe is imported (via sys.modules lookup) only when detect() is called."""
        for key in list(sys.modules):
            if key.startswith("mediapipe"):
                del sys.modules[key]
        if "clipper_agency.core.face_adapter" in sys.modules:
            del sys.modules["clipper_agency.core.face_adapter"]

        from clipper_agency.core.face_adapter import MediaPipeFaceDetector as MFD

        MFD._reset_model()
        assert "mediapipe" not in sys.modules

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = _mock_mp_image()
            mock_model = MagicMock()
            mock_model.process.return_value = _mock_process_result([])
            mock_fd.FaceDetection.return_value = mock_model

            detector = MFD()
            _ = detector.detect("/fake/img.jpg", 0.0)

            # Lazy init was triggered: FaceDetection constructor called
            assert mock_fd.FaceDetection.called, "Lazy model init should be triggered by detect()"


# ---------------------------------------------------------------------------
# Test: Basic detection
# ---------------------------------------------------------------------------


class TestBasicDetection:
    def test_returns_face_inspection_result_with_faces(self):
        """A single high-confidence detection produces one FaceRegion."""
        detection = _mock_detection(0.1, 0.1, 0.3, 0.3, 0.95)
        mp_img = _mock_mp_image(800, 600)
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("faces.jpg", 3.5)

        assert isinstance(result, FaceInspectionResult)
        assert len(result.faces) == 1
        assert result.timestamp_sec == 3.5

    def test_multiple_faces_detected_and_returned(self):
        """Three faces above threshold → all three returned."""
        detections = [
            _mock_detection(0.1, 0.1, 0.2, 0.2, 0.90),
            _mock_detection(0.5, 0.1, 0.3, 0.3, 0.85),
            _mock_detection(0.2, 0.6, 0.25, 0.25, 0.80),
        ]
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result(detections)

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("crowd.jpg", 0.0)

        assert len(result.faces) == 3

    def test_empty_image_no_faces(self):
        """No detections → empty faces list, not an error."""
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

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
            _mock_detection(0.1, 0.1, 0.2, 0.2, 0.95),  # keep
            _mock_detection(0.5, 0.5, 0.2, 0.2, 0.45),  # filter
            _mock_detection(0.3, 0.3, 0.2, 0.2, 0.59),  # filter (below 0.60)
        ]
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result(detections)

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

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
            _mock_detection(0.1, 0.1, 0.2, 0.2, 0.95),
            _mock_detection(0.5, 0.5, 0.2, 0.2, 0.75),  # below 0.80
        ]
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result(detections)

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

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
        # Face 1: 0.3*0.3 area (normalized) → smaller
        # Face 2: 0.5*0.5 area (normalized) → larger → primary
        detections = [
            _mock_detection(0.1, 0.1, 0.3, 0.3, 0.90),
            _mock_detection(0.3, 0.3, 0.5, 0.5, 0.85),
        ]
        mp_img = _mock_mp_image(1000, 1000)
        mock_result = _mock_process_result(detections)

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("faces.jpg", 0.0)

        assert len(result.faces) == 2
        primary = [f for f in result.faces if f.is_primary]
        assert len(primary) == 1
        # Primary = face 2 (larger): x1=300, y1=300, x2=800, y2=800
        assert primary[0].bbox == [300, 300, 800, 800]

    def test_primary_face_by_centrality_when_areas_equal(self):
        """When areas are equal, the face closest to center wins."""
        # Both faces same size (0.2 x 0.2)
        # Face 1 centered at (0.15, 0.15) → far from center (0.5, 0.5)
        # Face 2 centered at (0.6, 0.6) → closer to center → primary
        detections = [
            _mock_detection(0.05, 0.05, 0.2, 0.2, 0.90),
            _mock_detection(0.5, 0.5, 0.2, 0.2, 0.90),
        ]
        mp_img = _mock_mp_image(2000, 2000)
        mock_result = _mock_process_result(detections)

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("faces.jpg", 0.0)

        primary = [f for f in result.faces if f.is_primary]
        assert len(primary) == 1
        # Face 2 is closer to center
        assert primary[0].bbox == [1000, 1000, 1400, 1400]

    def test_single_face_is_always_primary(self):
        """A single detected face is marked as primary."""
        detection = _mock_detection(0.2, 0.2, 0.4, 0.4, 0.90)
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert len(result.faces) == 1
        assert result.faces[0].is_primary is True


# ---------------------------------------------------------------------------
# Test: Bounding box normalization
# ---------------------------------------------------------------------------


class TestBBoxNormalization:
    def test_normalized_coords_converted_to_pixel(self):
        """MediaPipe normalized (0-1) coords → absolute pixel coords."""
        # bbox at normalized (0.1, 0.2) size (0.3, 0.4) on 800x600 image
        detection = _mock_detection(0.1, 0.2, 0.3, 0.4, 0.95)
        mp_img = _mock_mp_image(800, 600)
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        xmin = int(0.1 * 800)  # 80
        ymin = int(0.2 * 600)  # 120
        xmax = int((0.1 + 0.3) * 800)  # 320
        ymax = int((0.2 + 0.4) * 600)  # 360
        assert result.faces[0].bbox == [xmin, ymin, xmax, ymax]

    def test_various_image_sizes(self):
        """BBox normalization works across different image dimensions."""
        sizes = [(640, 480), (1920, 1080), (720, 1280)]
        for w, h in sizes:
            detection = _mock_detection(0.0, 0.0, 1.0, 1.0, 0.95)
            mp_img = _mock_mp_image(w, h)
            mock_result = _mock_process_result([detection])

            with _fake_mediapipe() as (mock_image, mock_fd):
                mock_image.create_from_file.return_value = mp_img
                mock_model = MagicMock()
                mock_model.process.return_value = mock_result
                mock_fd.FaceDetection.return_value = mock_model

                detector = MediaPipeFaceDetector()
                result = detector.detect("face.jpg", 0.0)

            assert result.faces[0].bbox == [0, 0, w, h], f"Failed for {w}x{h}"


# ---------------------------------------------------------------------------
# Test: Provider/model metadata
# ---------------------------------------------------------------------------


class TestProviderMetadata:
    def test_result_includes_provider_and_model(self):
        """FaceInspectionResult carries provider and model metadata."""
        detection = _mock_detection(0.1, 0.1, 0.2, 0.2, 0.90)
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert result.provider == "mediapipe"
        assert "face_detection" in result.model
        assert result.model != ""


# ---------------------------------------------------------------------------
# Test: Timestamp propagation
# ---------------------------------------------------------------------------


class TestTimestampPropagation:
    def test_detect_propagates_timestamp_sec(self):
        """timestamp_sec is carried through to FaceInspectionResult."""
        detection = _mock_detection(0.1, 0.1, 0.2, 0.2, 0.90)
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()

            for ts in [0.0, 2.5, 59.123, 120.0]:
                result = detector.detect("face.jpg", ts)
                assert result.timestamp_sec == ts, f"Failed at timestamp {ts}"


# ---------------------------------------------------------------------------
# Test: Model singleton / reuse
# ---------------------------------------------------------------------------


class TestModelReuse:
    def test_model_is_reused_across_calls(self):
        """The MediaPipe model is created once and reused (singleton behavior)."""
        detection = _mock_detection(0.1, 0.1, 0.2, 0.2, 0.90)
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            detector.detect("a.jpg", 0.0)
            detector.detect("b.jpg", 1.0)
            detector.detect("c.jpg", 2.0)

        # FaceDetection constructor called only once
        assert mock_fd.FaceDetection.call_count == 1

    def test_model_singleton_respected_across_detector_instances(self):
        """Multiple MediaPipeFaceDetector instances share the same class-level model."""
        detection = _mock_detection(0.1, 0.1, 0.2, 0.2, 0.90)
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            d1 = MediaPipeFaceDetector()
            d2 = MediaPipeFaceDetector()
            d1.detect("a.jpg", 0.0)
            d2.detect("b.jpg", 1.0)

        assert mock_fd.FaceDetection.call_count == 1


# ---------------------------------------------------------------------------
# Test: Score extraction (list vs scalar)
# ---------------------------------------------------------------------------


class TestScoreExtraction:
    def test_score_list_extracted_as_first_element(self):
        """When detection.score is a list, the first element is used."""
        detection = _mock_detection(0.1, 0.1, 0.2, 0.2, 0.93)  # wrapped to [0.93]
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert len(result.faces) == 1
        assert result.faces[0].confidence == 0.93

    def test_scalar_score_used_directly(self):
        """When detection.score is a scalar float, it is used as-is."""
        detection = _mock_detection_single_score(0.1, 0.1, 0.2, 0.2, 0.87)
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        assert len(result.faces) == 1
        assert result.faces[0].confidence == 0.87


# ---------------------------------------------------------------------------
# Test: No identity recognition
# ---------------------------------------------------------------------------


class TestNoIdentityRecognition:
    def test_face_regions_have_no_identity_data(self):
        """FaceRegion only has bbox, confidence, is_primary — no identity fields."""
        detection = _mock_detection(0.1, 0.1, 0.2, 0.2, 0.95)
        mp_img = _mock_mp_image()
        mock_result = _mock_process_result([detection])

        with _fake_mediapipe() as (mock_image, mock_fd):
            mock_image.create_from_file.return_value = mp_img
            mock_model = MagicMock()
            mock_model.process.return_value = mock_result
            mock_fd.FaceDetection.return_value = mock_model

            detector = MediaPipeFaceDetector()
            result = detector.detect("face.jpg", 0.0)

        face = result.faces[0]
        # FaceRegion fields are only: bbox, confidence, is_primary
        assert set(face.model_dump().keys()) == {"bbox", "confidence", "is_primary"}


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
