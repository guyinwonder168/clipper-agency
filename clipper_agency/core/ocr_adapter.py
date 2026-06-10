"""PaddleOCR runtime adapter with lazy import and singleton model loading.

Provides the PaddleOCRAdapter implementing the OCRAdapter Protocol, wrapping
PaddleOCR with lazy-loading, singleton caching, and normalized output through
the project's existing text_detection normalization pipeline.
"""

from __future__ import annotations

from clipper_agency.config.schema import OCRInspectionResult
from clipper_agency.core.text_detection import filter_text_regions, normalize_text_region

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_FRAME_SIZE: tuple[int, int] = (1080, 1920)
DEFAULT_MIN_CONFIDENCE: float = 0.6
DEFAULT_LARGE_AREA_RATIO: float = 0.20
PADDLEOCR_PROVIDER: str = "paddleocr"

# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PaddleOCRAdapter:
    """PaddleOCR runtime adapter with lazy import and singleton model loading.

    The PaddleOCR model is imported and instantiated only on the first call
    to inspect(). Subsequent calls reuse the same model instance (process-level
    singleton). Multiple PaddleOCRAdapter instances share the same model.

    Args:
        frame_size: Default (width, height) of frames fed to inspect().
        min_confidence: Minimum OCR confidence threshold for filtering.
        large_area_ratio: Area-ratio override — keep low-confidence regions
            whose area covers >= this fraction of the frame.
    """

    # Singleton model — shared across all PaddleOCRAdapter instances.
    _ocr: "object | None" = None

    def __init__(
        self,
        frame_size: tuple[int, int] = DEFAULT_FRAME_SIZE,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        large_area_ratio: float = DEFAULT_LARGE_AREA_RATIO,
    ) -> None:
        self._frame_size = frame_size
        self._min_confidence = min_confidence
        self._large_area_ratio = large_area_ratio

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inspect(self, image_path: str, timestamp_sec: float) -> OCRInspectionResult:
        """Run OCR on *image_path* and return a normalized OCRInspectionResult.

        Args:
            image_path: Path to the image file to inspect.
            timestamp_sec: Timestamp within the source video (carried into
                every detected region for downstream alignment).

        Returns:
            OCRInspectionResult with provider metadata and filtered,
            normalized text regions.
        """
        raw_regions = self._run_ocr(image_path)
        normalized = self._normalize(raw_regions, timestamp_sec)
        filtered = self._filter(normalized)

        return OCRInspectionResult(
            provider=PADDLEOCR_PROVIDER,
            model="paddleocr",
            timestamp_sec=timestamp_sec,
            regions=filtered,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_ocr(self, image_path: str) -> list[tuple[list[list[int]], tuple[str, float]] | None]:
        """Run raw PaddleOCR on *image_path* and return per-region results.

        Returns:
            List of ``[bbox_quad, (text, confidence)]`` entries, or an empty
            list when no text is detected.
        """
        model = self._get_ocr()
        result = model.ocr(image_path)

        # PaddleOCR returns: [page_result] where page_result is a list of
        # [bbox_quad, (text, confidence)] entries (or None for empty regions).
        if not result or not result[0]:
            return []

        return [entry for entry in result[0] if entry is not None]

    def _normalize(
        self,
        raw_regions: list[tuple[list[list[int]], tuple[str, float]]],
        timestamp_sec: float,
    ) -> list:
        """Convert raw PaddleOCR regions into normalized DetectedTextRegion list."""
        normalized = []
        for quad, (text, confidence) in raw_regions:
            # Convert quadrilateral bbox to axis-aligned [x1, y1, x2, y2]
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            rect_bbox = [min(xs), min(ys), max(xs), max(ys)]

            region = normalize_text_region(
                text=text,
                confidence=confidence,
                bbox=rect_bbox,
                frame_size=self._frame_size,
                timestamp_sec=timestamp_sec,
            )
            normalized.append(region)
        return normalized

    def _filter(self, regions: list) -> list:
        """Apply confidence + large-area filtering via text_detection module."""
        return filter_text_regions(
            regions,
            min_confidence=self._min_confidence,
            large_area_ratio=self._large_area_ratio,
        )

    @classmethod
    def _reset_model(cls) -> None:
        """Reset the singleton model. Used in tests to isolate test runs."""
        cls._ocr = None

    @classmethod
    def _get_ocr(cls) -> "object":
        """Return the process-level singleton PaddleOCR model.

        Lazy-imports and instantiates PaddleOCR on the first call.
        """
        if cls._ocr is None:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped]

            cls._ocr = PaddleOCR(use_angle_cls=True, lang="en")
        return cls._ocr
