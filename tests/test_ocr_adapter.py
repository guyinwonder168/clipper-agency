"""TDD tests for PaddleOCRAdapter — RED phase.

All tests mock PaddleOCR — no real model loaded.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.config.schema import OCRInspectionResult


# ---------------------------------------------------------------------------
# Helpers for building mock PaddleOCR results
# ---------------------------------------------------------------------------

_FRAME_SIZE = (1080, 1920)


def _make_ocr_result(bbox_quad, text, confidence):
    """Simulate a single PaddleOCR result entry: [quad_points, (text, confidence)].

    bbox_quad: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] — quadrilateral
    Returns: PaddleOCR-format result for one text region.
    """
    return [bbox_quad, (text, confidence)]


def _bbox_quad(x1, y1, x2, y2):
    """Convert axis-aligned rectangle to quad format PaddleOCR uses."""
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _make_mock_paddleocr_model(ocr_results):
    """Create a mock PaddleOCR instance that returns *ocr_results* on .ocr().

    PaddleOCR returns: [page0_regions] where page0_regions is a list of
    [quad, (text, conf)] entries.  This helper wraps *ocr_results* — which
    is already a list of region entries — in the outer page-list.
    """
    model = MagicMock()
    # Real PaddleOCR: model.ocr(path) → [page_regions]
    # page_regions is a list of [quad, (text, conf)] entries
    if not ocr_results:
        model.ocr.return_value = [[]]
    else:
        model.ocr.return_value = [ocr_results]
    return model


def _make_mock_paddleocr_module(model_instance):
    """Return a mock 'paddleocr' module whose PaddleOCR() returns model_instance."""

    def _mock_constructor(*args, **kwargs):
        return model_instance

    module = MagicMock()
    module.PaddleOCR = MagicMock(side_effect=_mock_constructor)
    return module


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPaddleOCRAdapterStructure:
    """Test 1: Adapter returns OCRInspectionResult with correct structure."""

    def test_inspect_returns_ocr_inspection_result(self):
        """inspect() must return an OCRInspectionResult instance."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(80, 980, 990, 1220), "INI ALASAN RUBEN", 0.96),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/image.png", timestamp_sec=4.5)

        assert isinstance(result, OCRInspectionResult)
        assert isinstance(result.provider, str)
        assert result.timestamp_sec == 4.5

    def test_returns_correct_provider_and_model_metadata(self):
        """Result includes provider and model metadata."""
        mock_model = _make_mock_paddleocr_model([])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/image.png", timestamp_sec=0.0)

        assert result.provider == "paddleocr"
        assert isinstance(result.model, str)
        assert len(result.model) > 0


class TestPaddleOCRAdapterNormalization:
    """Test 2: Text regions are normalized through normalize_text_region."""

    def test_regions_normalized_with_zone_and_area_ratio(self):
        """Each detected region has zone and area_ratio computed."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(80, 980, 990, 1220), "TEXT A", 0.96),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=1.0)

        assert len(result.regions) == 1
        region = result.regions[0]
        assert region.text == "TEXT A"
        assert region.confidence == 0.96
        assert region.timestamp_sec == 1.0
        assert region.zone in ("top", "middle", "bottom")
        assert region.area_ratio > 0
        assert region.frame_size == _FRAME_SIZE

    def test_bbox_converted_from_quad_to_rect(self):
        """PaddleOCR returns quadrilateral; adapter converts to [x1,y1,x2,y2]."""
        quad = [[100, 200], [400, 200], [400, 350], [100, 350]]
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(quad, "QUAD TEXT", 0.88),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        assert len(result.regions) == 1
        region = result.regions[0]
        # Axis-aligned bounding box: min_x, min_y, max_x, max_y
        assert region.bbox == [100, 200, 400, 350]


class TestPaddleOCRAdapterLargeAreaPreservation:
    """Test 3: Low-confidence text regions with large area are preserved."""

    def test_large_area_low_confidence_kept(self):
        """Regions with confidence < default but area larger than threshold survive."""
        # Create a very large text region covering ~25% of the frame
        quad = _bbox_quad(0, 0, 540, 960)  # 540×960 / (1080×1920) = 0.25
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(quad, "", 0.35),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=1.0)

        assert len(result.regions) == 1
        assert result.regions[0].area_ratio >= 0.20

    def test_small_area_low_confidence_filtered(self):
        """Small regions with low confidence are filtered out."""
        quad = _bbox_quad(0, 0, 50, 50)  # tiny
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(quad, "noise", 0.1),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        assert len(result.regions) == 0


class TestPaddleOCRAdapterMultipleRegions:
    """Test 4: Multiple text regions per image handled."""

    def test_multiple_regions_returned(self):
        """Adapter handles images with multiple text regions."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(80, 980, 990, 1220), "TEXT A", 0.96),
            _make_ocr_result(_bbox_quad(200, 400, 800, 500), "TEXT B", 0.85),
            _make_ocr_result(_bbox_quad(100, 100, 300, 160), "TEXT C", 0.72),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        assert len(result.regions) == 3
        texts = {r.text for r in result.regions}
        assert texts == {"TEXT A", "TEXT B", "TEXT C"}


class TestPaddleOCRAdapterEmptyImage:
    """Test 5: Empty image / no text returns empty regions."""

    def test_empty_ocr_result_returns_empty_regions(self):
        """When PaddleOCR returns no regions, result.regions is empty list."""
        mock_model = _make_mock_paddleocr_model([])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/empty.png", timestamp_sec=0.0)

        assert isinstance(result, OCRInspectionResult)
        assert result.regions == []

    def test_none_ocr_result_handled_gracefully(self):
        """If PaddleOCR returns None for a region group, no crash."""
        mock_model = _make_mock_paddleocr_model([None])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        assert result.regions == []


class TestPaddleOCRAdapterMetadata:
    """Test 6: Adapter includes provider/model metadata."""

    def test_provider_is_paddleocr(self):
        """provider field is 'paddleocr'."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(0, 0, 100, 100), "TEST", 0.9),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        assert result.provider == "paddleocr"

    def test_model_field_is_populated(self):
        """model field is a non-empty string."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(0, 0, 100, 100), "TEST", 0.9),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        assert result.model != ""
        assert isinstance(result.model, str)


class TestPaddleOCRAdapterLazyImport:
    """Test 7: PaddleOCR is lazily imported (only imported on first use)."""

    def test_module_not_imported_before_first_use(self):
        """Before any inspect() call, paddleocr is NOT in sys.modules."""
        # Ensure paddleocr is not already imported
        with patch.dict(sys.modules):
            sys.modules.pop("paddleocr", None)
            # Import the adapter module — this should NOT trigger paddleocr import
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter  # noqa: F811

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)

        # Module should NOT be imported just from constructing the adapter
        assert "paddleocr" not in sys.modules

    def test_module_imported_on_first_inspect(self):
        """On first inspect() call, paddleocr is imported."""
        # Create a mock that we can detect
        mock_model = MagicMock()
        mock_model.ocr.return_value = [[]]

        with patch.dict(sys.modules):
            sys.modules.pop("paddleocr", None)
            mock_paddleocr = MagicMock()
            mock_paddleocr.PaddleOCR.return_value = mock_model

            with patch.dict(sys.modules, {"paddleocr": mock_paddleocr}):
                from clipper_agency.core.ocr_adapter import PaddleOCRAdapter  # noqa: F811

                adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
                _result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

            # The PaddleOCR constructor should have been called
            mock_paddleocr.PaddleOCR.assert_called_once()


class TestPaddleOCRAdapterSingleton:
    """Test 8: Model is reused across calls (singleton behavior)."""

    def test_model_created_only_once(self):
        """PaddleOCR() constructor is called exactly once across multiple inspect() calls."""
        mock_model = MagicMock()
        mock_model.ocr.return_value = [[]]

        with patch.dict(sys.modules):
            sys.modules.pop("paddleocr", None)
            mock_paddleocr = MagicMock()
            mock_paddleocr.PaddleOCR.return_value = mock_model

            with patch.dict(sys.modules, {"paddleocr": mock_paddleocr}):
                from clipper_agency.core.ocr_adapter import PaddleOCRAdapter  # noqa: F811

                adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
                adapter.inspect("/fake/1.png", timestamp_sec=0.0)
                adapter.inspect("/fake/2.png", timestamp_sec=1.0)
                adapter.inspect("/fake/3.png", timestamp_sec=2.0)

            # Constructor should be called exactly once
            assert mock_paddleocr.PaddleOCR.call_count == 1

    def test_model_shared_across_adapter_instances(self):
        """Multiple adapter instances share the same PaddleOCR model."""
        mock_model = MagicMock()
        mock_model.ocr.return_value = [[]]

        with patch.dict(sys.modules):
            sys.modules.pop("paddleocr", None)
            mock_paddleocr = MagicMock()
            mock_paddleocr.PaddleOCR.return_value = mock_model

            with patch.dict(sys.modules, {"paddleocr": mock_paddleocr}):
                from clipper_agency.core.ocr_adapter import PaddleOCRAdapter  # noqa: F811

                adapter1 = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
                adapter2 = PaddleOCRAdapter(frame_size=(1920, 1080))
                adapter1.inspect("/fake/a.png", timestamp_sec=0.0)
                adapter2.inspect("/fake/b.png", timestamp_sec=1.0)

            # Constructor should be called exactly once (shared singleton)
            assert mock_paddleocr.PaddleOCR.call_count == 1

    def test_ocr_called_for_each_inspect(self):
        """Though model is singleton, ocr() is called for each inspect()."""
        mock_model = MagicMock()
        mock_model.ocr.return_value = [[]]

        with patch.dict(sys.modules):
            sys.modules.pop("paddleocr", None)
            mock_paddleocr = MagicMock()
            mock_paddleocr.PaddleOCR.return_value = mock_model

            with patch.dict(sys.modules, {"paddleocr": mock_paddleocr}):
                from clipper_agency.core.ocr_adapter import PaddleOCRAdapter  # noqa: F811

                adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
                adapter.inspect("/fake/1.png", timestamp_sec=0.0)
                adapter.inspect("/fake/2.png", timestamp_sec=1.0)

            assert mock_model.ocr.call_count == 2


class TestPaddleOCRAdapterTimestampPropagation:
    """Test 9: inspect() propagates timestamp_sec correctly."""

    def test_timestamp_sec_in_result(self):
        """timestamp_sec is set on the OCRInspectionResult."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(0, 0, 100, 100), "HI", 0.99),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=12.5)

        assert result.timestamp_sec == 12.5

    def test_timestamp_sec_propagates_to_regions(self):
        """Each region carries the correct timestamp_sec."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(10, 20, 100, 50), "A", 0.9),
            _make_ocr_result(_bbox_quad(10, 60, 100, 90), "B", 0.8),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=7.25)

        for region in result.regions:
            assert region.timestamp_sec == 7.25


class TestPaddleOCRAdapterDefaults:
    """Test default parameter behavior."""

    def test_default_frame_size(self):
        """Adapter has sensible default frame_size."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(0, 0, 100, 100), "OK", 0.95),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter()  # no args
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        assert len(result.regions) == 1
        assert result.regions[0].frame_size is not None
        assert len(result.regions[0].frame_size) == 2

    def test_default_min_confidence_threshold(self):
        """Adapter applies sensible default min_confidence threshold."""
        mock_model = _make_mock_paddleocr_model([
            _make_ocr_result(_bbox_quad(0, 0, 100, 100), "HIGH", 0.95),
            _make_ocr_result(_bbox_quad(10, 10, 40, 40), "LOW", 0.55),
        ])
        mock_module = _make_mock_paddleocr_module(mock_model)

        with patch.dict(sys.modules, {"paddleocr": mock_module}):
            from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

            adapter = PaddleOCRAdapter(frame_size=_FRAME_SIZE)
            result = adapter.inspect("/fake/img.png", timestamp_sec=0.0)

        # Default min_confidence=0.6, so only the 0.95-region survives
        texts = {r.text for r in result.regions}
        assert "HIGH" in texts
        assert "LOW" not in texts
