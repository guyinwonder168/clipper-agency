"""MediaPipe face detection runtime adapter (Tasks API) with lazy initialization.

Provides a FaceDetector protocol implementation that wraps MediaPipe's **Tasks
API** face detector (``mediapipe.tasks.python.vision.face_detector``). This
replaces the legacy ``mediapipe.solutions.face_detection`` API, which was removed
in ``mediapipe>=0.11`` and pinned ``protobuf<5`` — incompatible with the project's
``protobuf==7.x`` / ``numpy==2.x`` stack. The Tasks API works with current
MediaPipe releases.

The BlazeFace short-range model is downloaded once and cached under ``data/``
(gitignored). Detection returns absolute pixel bounding boxes with primary-face
selection by area (largest) and centrality (closest to image center).

Degrades gracefully: if MediaPipe is absent or the model cannot be fetched, the
adapter logs the failure ONCE and returns empty results on every subsequent call
— it never raises per-frame (which was the source of the ``ModuleNotFoundError``
log storm when the package was missing).
"""

import logging
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from clipper_agency.config.schema import (
    FaceDetectionConfig,
    FaceInspectionResult,
    FaceRegion,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = FaceDetectionConfig()

# BlazeFace short-range — the only face_detector task model MediaPipe ships.
# Cached under data/ (gitignored) on first use; fixed app-owned path (not
# user-controlled) per the S6549 path-traversal lesson.
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
_MODEL_CACHE_PATH = Path("data/models/face_detection/blaze_face_short_range.tflite")
_MODEL_NAME = "face_detection_short_range"


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


def _ensure_model_cached() -> Path:
    """Download the BlazeFace model to the cache dir if not already present.

    Returns the local path to the cached ``.tflite``. Raises on network/HTTP
    failure so the caller can mark the adapter unavailable and degrade.
    """
    if _MODEL_CACHE_PATH.exists():
        return _MODEL_CACHE_PATH
    _MODEL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading MediaPipe face-detection model to %s", _MODEL_CACHE_PATH)
    with httpx.Client(timeout=60) as client:
        resp = client.get(_MODEL_URL)
        resp.raise_for_status()
    _MODEL_CACHE_PATH.write_bytes(resp.content)
    return _MODEL_CACHE_PATH


class MediaPipeFaceDetector:
    """MediaPipe face detection adapter (Tasks API) with lazy model init.

    The detector is loaded on first call to :meth:`detect` — not at module
    import time. It is stored at class level and reused across all instances
    (singleton behavior).

    Attributes:
        min_confidence: Detection confidence threshold (default from config).
        model_selection: Legacy compatibility param (MediaPipe Tasks ships only
            the short-range BlazeFace model; this is retained for API parity and
            is otherwise informational).
    """

    # Class-level singleton model, lock, and unavailable flag.
    _model = None
    _model_lock = threading.Lock()
    _unavailable = False

    def __init__(
        self,
        min_confidence: float | None = None,
        model_selection: int = 1,
    ) -> None:
        """Initialize the detector with configurable thresholds.

        Args:
            min_confidence: Faces below this score are filtered out.
                Defaults to FaceDetectionConfig.min_confidence (0.60).
            model_selection: Retained for API parity (legacy solutions param).
        """
        self.min_confidence = (
            min_confidence if min_confidence is not None else _DEFAULT_CONFIG.min_confidence
        )
        self.model_selection = model_selection

    @classmethod
    def _reset_model(cls) -> None:
        """Reset the class-level model singleton (for testing only)."""
        with cls._model_lock:
            cls._model = None
            cls._unavailable = False

    @classmethod
    def _get_model(cls, min_confidence: float):
        """Lazily initialize and return the shared Tasks-API FaceDetector.

        Returns ``None`` (and marks the adapter unavailable) if MediaPipe is
        missing or the model cannot be initialized — so callers degrade to empty
        results instead of raising per call.
        """
        if cls._unavailable:
            return None
        if cls._model is None:
            with cls._model_lock:
                if cls._model is None and not cls._unavailable:
                    try:
                        cls._model = cls._build_model(min_confidence)
                    except Exception as exc:  # noqa: BLE001 — degrade on any init failure
                        cls._unavailable = True
                        logger.warning(
                            "MediaPipe face detection unavailable (%s); "
                            "returning empty face results.",
                            exc,
                        )
                        return None
        return cls._model

    @staticmethod
    def _build_model(min_confidence: float):
        """Import MediaPipe Tasks API + create the FaceDetector singleton."""
        from mediapipe.tasks.python.core import base_options as base_options_module
        from mediapipe.tasks.python.vision import face_detector as fd_module

        model_path = _ensure_model_cached()
        options = fd_module.FaceDetectorOptions(
            base_options=base_options_module.BaseOptions(
                model_asset_path=str(model_path),
            ),
            min_detection_confidence=min_confidence,
        )
        return fd_module.FaceDetector.create_from_options(options)

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

        model = self._get_model(self.min_confidence)
        if model is None:
            return FaceInspectionResult(
                provider="mediapipe",
                model="face_detection_unavailable",
                timestamp_sec=timestamp_sec,
                faces=[],
            )

        # mediapipe is imported lazily here (after the availability check) so a
        # missing/unavailable model degrades to empty instead of raising.
        import mediapipe as mp

        # Load image via OpenCV → numpy array (needed for dimensions + RGB convert)
        image = cv2.imread(image_path)
        if image is None:
            return FaceInspectionResult(
                provider="mediapipe",
                model=_MODEL_NAME,
                timestamp_sec=timestamp_sec,
                faces=[],
            )
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image_height, image_width = image.shape[:2]

        # Tasks API expects an mp.Image built from the RGB numpy array.
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
        result = model.detect(mp_image)

        faces: list[FaceRegion] = []
        for detection in getattr(result, "detections", None) or []:
            score = self._extract_score(detection)
            if score < self.min_confidence:
                continue

            # Tasks API bounding_box is ABSOLUTE pixels (origin_x/y + width/height)
            # — no normalization math needed (unlike the legacy solutions API).
            bb = detection.bounding_box
            xmin = int(bb.origin_x)
            ymin = int(bb.origin_y)
            xmax = int(bb.origin_x + bb.width)
            ymax = int(bb.origin_y + bb.height)

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
            model=_MODEL_NAME,
            timestamp_sec=timestamp_sec,
            faces=faces,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_score(detection) -> float:
        """Extract the confidence score from a Tasks-API Detection.

        The Tasks face_detector exposes scores on ``detection.categories``;
        the face detector emits a single category whose ``score`` is the
        confidence. Returns the max category score, or 0.0 if unavailable.
        """
        categories = getattr(detection, "categories", None) or []
        scores = [getattr(c, "score", 0.0) for c in categories]
        return float(max(scores)) if scores else 0.0

    @staticmethod
    def _mark_primary(faces: list[FaceRegion], image_width: int, image_height: int) -> None:
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
