"""MediaPipe face detection runtime adapter with lazy initialization.

Provides a FaceDetector protocol implementation that wraps MediaPipe's
face detection model. The model is lazily loaded — no import at module level.
Detection returns normalized pixel bounding boxes with primary-face selection
by area (largest) and centrality (closest to image center).
"""

import threading
from typing import Protocol, runtime_checkable

from clipper_agency.config.schema import (
    FaceDetectionConfig,
    FaceInspectionResult,
    FaceRegion,
)

# Default configuration
_DEFAULT_CONFIG = FaceDetectionConfig()


@runtime_checkable
class FaceDetector(Protocol):
    """Protocol for face detection adapters.

    All face detector implementations must satisfy this interface.
    """

    def detect(self, image_path: str, timestamp_sec: float) -> FaceInspectionResult:
        """Detect faces in the given image at a specific video timestamp.

        Args:
            image_path: Filesystem path to the image to analyze.
            timestamp_sec: Video timestamp this frame was extracted at.

        Returns:
            FaceInspectionResult with provider/model metadata and detected faces.
        """
        ...


class MediaPipeFaceDetector:
    """MediaPipe face detection adapter with lazy model initialization.

    The MediaPipe model is loaded on first call to :meth:`detect` — not
    at module import time. The model is stored at class level and reused
    across all instances (singleton behavior).

    Attributes:
        min_confidence: Detection confidence threshold (default from config).
        model_selection: MediaPipe model variant (1 = full-range, 0 = short-range).
    """

    # Class-level singleton model and lock
    _model = None
    _model_lock = threading.Lock()

    def __init__(
        self,
        min_confidence: float | None = None,
        model_selection: int = 1,
    ) -> None:
        """Initialize the detector with configurable thresholds.

        Args:
            min_confidence: Faces below this score are filtered out.
                Defaults to FaceDetectionConfig.min_confidence (0.60).
            model_selection: MediaPipe model selection (1=full-range, 0=short-range).
        """
        self.min_confidence = (
            min_confidence
            if min_confidence is not None
            else _DEFAULT_CONFIG.min_confidence
        )
        self.model_selection = model_selection

    @classmethod
    def _reset_model(cls) -> None:
        """Reset the class-level model singleton (for testing only)."""
        with cls._model_lock:
            cls._model = None

    @classmethod
    def _get_model(cls, model_selection: int, min_confidence: float):
        """Lazily initialize and return the shared MediaPipe FaceDetection model.

        Uses double-checked locking for thread-safe lazy initialization.
        """
        if cls._model is None:
            with cls._model_lock:
                if cls._model is None:
                    import mediapipe as mp
                    import mediapipe.solutions.face_detection as fd_module  # type: ignore[import-untyped]

                    cls._model = fd_module.FaceDetection(
                        model_selection=model_selection,
                        min_detection_confidence=min_confidence,
                    )
        return cls._model

    def detect(self, image_path: str, timestamp_sec: float) -> FaceInspectionResult:
        """Detect faces in an image file using MediaPipe.

        Args:
            image_path: Path to the image file.
            timestamp_sec: Video timestamp the frame was extracted at.

        Returns:
            FaceInspectionResult with provider="mediapipe", model metadata,
            and a list of FaceRegion objects sorted by primary-face priority.
        """
        import cv2
        import numpy as np

        model = self._get_model(self.model_selection, self.min_confidence)

        # Load image via OpenCV → numpy array (Solutions API expects numpy)
        image = cv2.imread(image_path)
        if image is None:
            return FaceInspectionResult(
                provider="mediapipe",
                model=f"face_detection_v{self.model_selection}",
                timestamp_sec=timestamp_sec,
                faces=[],
            )
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image_height, image_width = image.shape[:2]

        # Run face detection
        results = model.process(image_rgb)

        faces: list[FaceRegion] = []

        if results.detections:
            for detection in results.detections:
                score = self._extract_score(detection)

                if score < self.min_confidence:
                    continue

                bbox = detection.location_data.relative_bounding_box

                # Convert normalized [0,1] coords → absolute pixel coords
                xmin = int(bbox.xmin * image_width)
                ymin = int(bbox.ymin * image_height)
                xmax = int((bbox.xmin + bbox.width) * image_width)
                ymax = int((bbox.ymin + bbox.height) * image_height)

                faces.append(
                    FaceRegion(
                        bbox=[xmin, ymin, xmax, ymax],
                        confidence=float(score),
                        is_primary=False,
                    )
                )

        # Select primary face if any were detected
        if faces:
            self._mark_primary(faces, image_width, image_height)

        return FaceInspectionResult(
            provider="mediapipe",
            model=f"face_detection_v{self.model_selection}",
            timestamp_sec=timestamp_sec,
            faces=faces,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_score(detection) -> float:
        """Extract confidence score from a MediaPipe Detection.

        Handles both list-based scores (older MediaPipe API) and scalar
        scores (newer API).

        Args:
            detection: A MediaPipe Detection protocol message.

        Returns:
            Float score between 0.0 and 1.0, or 0.0 if unavailable.
        """
        score = detection.score
        if isinstance(score, (list, tuple)):
            return float(score[0]) if score else 0.0
        return float(score)

    @staticmethod
    def _mark_primary(
        faces: list[FaceRegion], image_width: int, image_height: int
    ) -> None:
        """Select and mark the primary face in the list.

        Primary selection priority:
        1. Largest bounding-box area.
        2. When areas are equal, closest to the image center.

        The face with ``is_primary=True`` is mutated in-place.

        Args:
            faces: Non-empty list of FaceRegion objects (mutated in-place).
            image_width: Image width in pixels.
            image_height: Image height in pixels.
        """
        center_x = image_width / 2.0
        center_y = image_height / 2.0

        def _primary_key(face: FaceRegion) -> tuple[float, float]:
            x1, y1, x2, y2 = face.bbox
            area = (x2 - x1) * (y2 - y1)
            face_cx = (x1 + x2) / 2.0
            face_cy = (y1 + y2) / 2.0
            # Euclidean distance from image center
            dist = ((face_cx - center_x) ** 2 + (face_cy - center_y) ** 2) ** 0.5
            # Negate area for descending sort; smaller distance is better
            return (-area, dist)

        # Find the face with smallest (negated_area, distance)
        primary = min(faces, key=_primary_key)
        # Mutate in-place: Pydantic models without frozen=True support mutation
        primary.is_primary = True
