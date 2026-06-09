"""Tests for multimodal provider protocol and OpenRouter implementation."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.core.multimodal_provider import (
    MultimodalProvider,
    OpenRouterMultimodalProvider,
    build_inspection_prompt,
    encode_image_as_data_uri,
    parse_inspection_response,
)


# ---------------------------------------------------------------------------
# 1. build_inspection_prompt
# ---------------------------------------------------------------------------


class TestBuildInspectionPrompt:
    """build_inspection_prompt includes beat claim, OCR text, and source metadata."""

    def test_includes_spoken_point(self):
        beat = {"spoken_point": "Ruben Onsu klarifikasi isu", "beat_id": "B01"}
        prompt = build_inspection_prompt(beat, "", {})
        assert "Ruben Onsu klarifikasi isu" in prompt

    def test_includes_ocr_text(self):
        ocr = "TikTok @user123 Breaking News"
        prompt = build_inspection_prompt({}, ocr, {})
        assert ocr in prompt

    def test_includes_source_metadata(self):
        meta = {"source": "scrapecreators", "url": "https://tiktok.com/xyz"}
        prompt = build_inspection_prompt({}, "", meta)
        assert "scrapecreators" in prompt
        assert "https://tiktok.com/xyz" in prompt

    def test_includes_six_inspection_questions(self):
        prompt = build_inspection_prompt({}, "", {})
        assert "person" in prompt.lower()
        assert "event" in prompt.lower()
        assert "claim" in prompt.lower()
        assert "mislead" in prompt.lower()
        assert "source text" in prompt.lower() or "logo" in prompt.lower()
        assert "evidence" in prompt.lower() or "context" in prompt.lower()


# ---------------------------------------------------------------------------
# 2–4. parse_inspection_response
# ---------------------------------------------------------------------------


class TestParseInspectionResponse:
    """JSON extraction from LLM responses."""

    def test_extracts_json_from_markdown_fences(self):
        payload = {
            "person_match": 0.9,
            "event_match": 0.8,
            "claim_support": 0.7,
            "visual_quality": 0.85,
            "misleading_risk": 0.1,
            "decision": "accept",
            "reason": "Good match",
        }
        raw = f"```json\n{json.dumps(payload)}\n```"
        result = parse_inspection_response(raw)
        assert result["decision"] == "accept"
        assert result["person_match"] == 0.9

    def test_bounds_scores_to_zero_one(self):
        payload = {
            "person_match": 1.5,
            "event_match": -0.3,
            "claim_support": 0.5,
            "visual_quality": 0.5,
            "misleading_risk": 2.0,
            "decision": "accept",
            "reason": "ok",
        }
        raw = json.dumps(payload)
        result = parse_inspection_response(raw)
        assert result["person_match"] == 1.0
        assert result["event_match"] == 0.0
        assert result["misleading_risk"] == 1.0

    def test_handles_malformed_json(self):
        raw = "This is not JSON at all"
        result = parse_inspection_response(raw)
        assert result["decision"] == "error"

    def test_handles_empty_string(self):
        result = parse_inspection_response("")
        assert result["decision"] == "error"

    def test_extracts_plain_json_without_fences(self):
        payload = {"decision": "reject", "reason": "bad", "person_match": 0.1}
        result = parse_inspection_response(json.dumps(payload))
        assert result["decision"] == "reject"
        assert result["person_match"] == 0.1


# ---------------------------------------------------------------------------
# 5. encode_image_as_data_uri
# ---------------------------------------------------------------------------


class TestEncodeImageAsDataUri:
    """File-to-data-URI encoding."""

    def test_reads_file_and_produces_correct_prefix(self):
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 10  # minimal JPEG header
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name
        try:
            uri = encode_image_as_data_uri(path)
            assert uri.startswith("data:image/jpeg;base64,")
            b64_part = uri.split(",", 1)[1]
            decoded = base64.b64decode(b64_part)
            assert decoded == content
        finally:
            os.unlink(path)

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            encode_image_as_data_uri("/nonexistent/path.jpg")


# ---------------------------------------------------------------------------
# 6–8. OpenRouterMultimodalProvider.inspect_asset
# ---------------------------------------------------------------------------

_SAMPLE_BEAT = {
    "beat_id": "B01",
    "spoken_point": "Ruben Onsu klarifikasi",
    "narration_goal": "Explain the situation",
}

_SAMPLE_RESPONSE = {
    "person_match": 0.9,
    "event_match": 0.85,
    "claim_support": 0.8,
    "visual_quality": 0.7,
    "temporal_match": 0.75,
    "source_credibility": 0.8,
    "cleanliness_score": 0.6,
    "misleading_risk": 0.1,
    "decision": "accept",
    "reason": "Person and event match well",
}


def _make_mock_client(response: dict[str, Any] | None = None) -> MagicMock:
    """Create a mock client that returns the given response dict."""
    client = MagicMock()
    payload = response or _SAMPLE_RESPONSE
    client.chat.return_value = {
        "content": json.dumps(payload),
        "model": "google/gemini-2.5-flash",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    return client


def _make_frame_file() -> str:
    """Create a temp JPEG file and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
    f.close()
    return f.name


class TestOpenRouterMultimodalProviderInspectAsset:
    """inspect_asset integration with mock client."""

    def test_calls_client_with_correct_message_structure(self):
        client = _make_mock_client()
        provider = OpenRouterMultimodalProvider(client=client)
        frame_path = _make_frame_file()
        try:
            provider.inspect_asset(
                beat=_SAMPLE_BEAT,
                frame_paths=[frame_path],
                ocr_regions=[],
                source_metadata={"source": "tiktok"},
            )
        finally:
            os.unlink(frame_path)

        client.chat.assert_called_once()
        call_kwargs = client.chat.call_args
        messages = call_kwargs[1]["messages"] if "messages" in call_kwargs[1] else call_kwargs[0][1]
        # First message should be user role with multimodal content
        msg = messages[0]
        assert msg["role"] == "user"
        # Content should be a list (multimodal format)
        assert isinstance(msg["content"], list)
        # At least one text part
        text_parts = [p for p in msg["content"] if p.get("type") == "text"]
        assert len(text_parts) >= 1
        # At least one image part
        image_parts = [p for p in msg["content"] if p.get("type") == "image_url"]
        assert len(image_parts) >= 1

    def test_returns_parsed_asset_semantic_inspection_fields(self):
        client = _make_mock_client()
        provider = OpenRouterMultimodalProvider(client=client)
        frame_path = _make_frame_file()
        try:
            result = provider.inspect_asset(
                beat=_SAMPLE_BEAT,
                frame_paths=[frame_path],
                ocr_regions=[],
                source_metadata={},
            )
        finally:
            os.unlink(frame_path)

        assert result["decision"] == "accept"
        assert result["person_match"] == 0.9
        assert result["event_match"] == 0.85
        assert result["claim_support"] == 0.8
        assert result["model"] == "google/gemini-2.5-flash"
        assert frame_path in result["frame_paths"]

    def test_handles_client_exception_gracefully(self):
        client = MagicMock()
        client.chat.side_effect = RuntimeError("API timeout")
        provider = OpenRouterMultimodalProvider(client=client, max_retries=0)
        result = provider.inspect_asset(
            beat=_SAMPLE_BEAT,
            frame_paths=[],
            ocr_regions=[],
            source_metadata={},
        )
        assert result["decision"] == "error"
        assert result["reason"]  # non-empty reason


# ---------------------------------------------------------------------------
# 9. Retry on transient failure
# ---------------------------------------------------------------------------


class TestRetryOnTransientFailure:
    """Provider retries on transient errors then succeeds."""

    @patch("clipper_agency.core.multimodal_provider.time.sleep")
    def test_retries_on_failure_then_succeeds(self, mock_sleep):
        client = MagicMock()
        good_response = {
            "content": json.dumps({
                "person_match": 0.8,
                "event_match": 0.7,
                "claim_support": 0.6,
                "visual_quality": 0.75,
                "misleading_risk": 0.2,
                "decision": "accept",
                "reason": "OK",
            }),
            "model": "google/gemini-2.5-flash",
            "usage": {},
        }
        client.chat.side_effect = [
            RuntimeError("transient 503"),
            RuntimeError("transient 429"),
            good_response,
        ]
        provider = OpenRouterMultimodalProvider(client=client, max_retries=2)
        result = provider.inspect_asset(
            beat=_SAMPLE_BEAT,
            frame_paths=[],
            ocr_regions=[],
            source_metadata={},
        )
        assert result["decision"] == "accept"
        assert client.chat.call_count == 3


# ---------------------------------------------------------------------------
# 10. Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """Any class implementing MultimodalProvider works."""

    def test_custom_provider_satisfies_protocol(self):
        class DummyProvider:
            def inspect_asset(
                self,
                beat: dict,
                frame_paths: list[str],
                ocr_regions: list[dict],
                source_metadata: dict,
            ) -> dict:
                return {
                    "asset_id": "test",
                    "beat_id": beat.get("beat_id", ""),
                    "person_match": 0.5,
                    "event_match": 0.5,
                    "claim_support": 0.5,
                    "visual_quality": 0.5,
                    "temporal_match": 0.5,
                    "source_credibility": 0.5,
                    "cleanliness_score": 0.5,
                    "misleading_risk": 0.5,
                    "decision": "accept",
                    "reason": "dummy",
                    "frame_paths": frame_paths,
                    "model": "dummy",
                }

        provider: MultimodalProvider = DummyProvider()
        result = provider.inspect_asset(
            beat={"beat_id": "B01"},
            frame_paths=["/tmp/x.jpg"],
            ocr_regions=[],
            source_metadata={},
        )
        assert result["decision"] == "accept"

    def test_openrouter_provider_satisfies_protocol(self):
        client = _make_mock_client()
        provider: MultimodalProvider = OpenRouterMultimodalProvider(client=client)
        assert isinstance(provider, MultimodalProvider)
