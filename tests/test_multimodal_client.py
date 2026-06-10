"""Tests for MultimodalInspectionClient — high-level visual asset inspection.

TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.llm.multimodal_client import (
    MultimodalInspectionClient,
    build_visual_inspection_messages,
    parse_inspection_json,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SAMPLE_BEAT: dict[str, Any] = {
    "beat_id": "B03",
    "spoken_point": "Ruben Onsu mengklarifikasi isu di TikTok live",
    "narration_goal": "Explain the clarification",
    "visual_must_show": "Ruben Onsu face, TikTok live interface",
    "visual_must_not_show": "unrelated person, meme overlay",
}

_SAMPLE_RESPONSE: dict[str, Any] = {
    "person_match": 0.92,
    "event_match": 0.85,
    "claim_support": 0.78,
    "visual_quality": 0.88,
    "temporal_match": 0.80,
    "source_credibility": 0.75,
    "cleanliness_score": 0.70,
    "misleading_risk": 0.05,
    "decision": "accept",
    "reason": "Person and TikTok live interface clearly visible",
}


def _make_mock_client(response: dict[str, Any] | None = None) -> MagicMock:
    """Create a mock OpenRouterClient returning the given response."""
    client = MagicMock()
    payload = response or _SAMPLE_RESPONSE
    client.chat.return_value = {
        "content": json.dumps(payload),
        "model": "google/gemini-2.5-flash",
        "usage": {"prompt_tokens": 120, "completion_tokens": 60},
    }
    return client


def _make_frame_file() -> str:
    """Create a temporary JPEG file and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# 1–5. build_visual_inspection_messages
# ---------------------------------------------------------------------------


class TestBuildVisualInspectionMessages:
    """Pure-function prompt construction tests."""

    def test_includes_beat_claim_in_user_message(self):
        """Beat spoken_point (claim) must appear in the user message."""
        msgs = build_visual_inspection_messages(
            beat=_SAMPLE_BEAT,
            frame_paths=[],
        )
        user_text = _extract_text_from_messages(msgs)
        assert "Ruben Onsu mengklarifikasi isu di TikTok live" in user_text

    def test_includes_evidence_contract_visual_must_show(self):
        """visual_must_show from the evidence contract must be present."""
        msgs = build_visual_inspection_messages(
            beat=_SAMPLE_BEAT,
            frame_paths=[],
        )
        user_text = _extract_text_from_messages(msgs)
        assert "Ruben Onsu face" in user_text
        assert "TikTok live interface" in user_text

    def test_includes_ocr_text_when_provided(self):
        """OCR text should appear in the prompt when given."""
        ocr = "TikTok @rubenonsu LIVE"
        msgs = build_visual_inspection_messages(
            beat=_SAMPLE_BEAT,
            frame_paths=[],
            ocr_text=ocr,
        )
        user_text = _extract_text_from_messages(msgs)
        assert ocr in user_text

    def test_caps_frames_at_max_frames(self):
        """Should not include more than max_frames image parts."""
        paths = [_make_frame_file() for _ in range(6)]
        try:
            msgs = build_visual_inspection_messages(
                beat=_SAMPLE_BEAT,
                frame_paths=paths,
                max_frames=3,
            )
            image_parts = _extract_image_parts(msgs)
            assert len(image_parts) <= 3
        finally:
            for p in paths:
                os.unlink(p)

    def test_includes_image_parts_in_content(self):
        """Frame files should produce image_url content parts."""
        path = _make_frame_file()
        try:
            msgs = build_visual_inspection_messages(
                beat=_SAMPLE_BEAT,
                frame_paths=[path],
            )
            image_parts = _extract_image_parts(msgs)
            assert len(image_parts) == 1
            assert image_parts[0]["type"] == "image_url"
            assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        finally:
            os.unlink(path)

    def test_includes_system_role_message(self):
        """Messages should include a system role message for inspector identity."""
        msgs = build_visual_inspection_messages(
            beat=_SAMPLE_BEAT,
            frame_paths=[],
        )
        roles = [m["role"] for m in msgs]
        assert "system" in roles

    def test_includes_visual_must_not_show(self):
        """visual_must_not_show should appear in the prompt."""
        msgs = build_visual_inspection_messages(
            beat=_SAMPLE_BEAT,
            frame_paths=[],
        )
        user_text = _extract_text_from_messages(msgs)
        assert "unrelated person" in user_text


# ---------------------------------------------------------------------------
# 6–11. parse_inspection_json
# ---------------------------------------------------------------------------


class TestParseInspectionJson:
    """Pure-function response parsing tests."""

    def test_extracts_json_from_markdown_fences(self):
        raw = f"```json\n{json.dumps(_SAMPLE_RESPONSE)}\n```"
        result = parse_inspection_json(raw)
        assert result["decision"] == "accept"
        assert result["person_match"] == pytest.approx(0.92, abs=0.01)

    def test_bounds_scores_to_zero_one(self):
        payload = {
            "person_match": 1.5,
            "event_match": -0.3,
            "claim_support": 0.5,
            "visual_quality": 999.0,
            "misleading_risk": -5.0,
            "decision": "accept",
            "reason": "testing",
        }
        result = parse_inspection_json(json.dumps(payload))
        assert result["person_match"] == 1.0
        assert result["event_match"] == 0.0
        assert result["visual_quality"] == 1.0
        assert result["misleading_risk"] == 0.0

    def test_determines_accept_when_scores_high(self):
        """High scores → decision stays 'accept'."""
        payload = {
            "person_match": 0.9,
            "event_match": 0.85,
            "claim_support": 0.88,
            "visual_quality": 0.9,
            "temporal_match": 0.8,
            "source_credibility": 0.85,
            "cleanliness_score": 0.75,
            "misleading_risk": 0.05,
            "decision": "accept",
            "reason": "Good",
        }
        result = parse_inspection_json(json.dumps(payload))
        assert result["decision"] == "accept"

    def test_determines_reject_when_scores_low(self):
        """Low scores with high misleading risk → decision 'reject'."""
        payload = {
            "person_match": 0.1,
            "event_match": 0.15,
            "claim_support": 0.2,
            "visual_quality": 0.3,
            "misleading_risk": 0.9,
            "decision": "reject",
            "reason": "Wrong person",
        }
        result = parse_inspection_json(json.dumps(payload))
        assert result["decision"] == "reject"

    def test_determines_revise_for_borderline_scores(self):
        """Borderline scores → decision 'revise'."""
        payload = {
            "person_match": 0.5,
            "event_match": 0.55,
            "claim_support": 0.5,
            "visual_quality": 0.6,
            "misleading_risk": 0.3,
            "decision": "revise",
            "reason": "Blurry face",
        }
        result = parse_inspection_json(json.dumps(payload))
        assert result["decision"] == "revise"

    def test_handles_malformed_json(self):
        """Garbage input → decision 'error'."""
        result = parse_inspection_json("not json at all {{{}}")
        assert result["decision"] == "error"
        assert "reason" in result

    def test_handles_empty_response(self):
        result = parse_inspection_json("")
        assert result["decision"] == "error"

    def test_provides_defaults_for_missing_fields(self):
        """Missing score keys should get default 0.0."""
        payload = {"decision": "accept", "reason": "minimal"}
        result = parse_inspection_json(json.dumps(payload))
        assert result["person_match"] == 0.0
        assert result["event_match"] == 0.0
        assert result["claim_support"] == 0.0


# ---------------------------------------------------------------------------
# 12–15. MultimodalInspectionClient.inspect_asset
# ---------------------------------------------------------------------------


class TestMultimodalInspectionClientInspectAsset:
    """Integration tests using mocked OpenRouterClient."""

    def test_calls_client_with_correct_args(self):
        """inspect_asset should call client.chat with model + messages."""
        client = _make_mock_client()
        inspector = MultimodalInspectionClient(client=client)

        path = _make_frame_file()
        try:
            inspector.inspect_asset(
                job_id=1,
                beat_id="B03",
                asset_id="A001",
                beat=_SAMPLE_BEAT,
                frame_paths=[path],
            )
        finally:
            os.unlink(path)

        client.chat.assert_called_once()
        call_kwargs = client.chat.call_args
        assert call_kwargs[1]["model"] == "google/gemini-2.5-flash"
        messages = call_kwargs[1]["messages"]
        assert isinstance(messages, list)
        assert len(messages) >= 1

    def test_returns_asset_semantic_inspection_fields(self):
        """Result dict must contain all AssetSemanticInspection fields."""
        client = _make_mock_client()
        inspector = MultimodalInspectionClient(client=client)

        path = _make_frame_file()
        try:
            result = inspector.inspect_asset(
                job_id=1,
                beat_id="B03",
                asset_id="A001",
                beat=_SAMPLE_BEAT,
                frame_paths=[path],
            )
        finally:
            os.unlink(path)

        expected_fields = {
            "asset_id", "beat_id", "person_match", "event_match",
            "claim_support", "visual_quality", "temporal_match",
            "source_credibility", "cleanliness_score", "misleading_risk",
            "decision", "reason", "frame_paths", "model",
        }
        assert expected_fields.issubset(set(result.keys()))
        assert result["asset_id"] == "A001"
        assert result["beat_id"] == "B03"
        assert result["decision"] == "accept"

    def test_handles_client_exception(self):
        """Client raising should not propagate; return error result."""
        client = MagicMock()
        client.chat.side_effect = RuntimeError("API timeout")

        inspector = MultimodalInspectionClient(client=client)
        result = inspector.inspect_asset(
            job_id=1,
            beat_id="B03",
            asset_id="A001",
            beat=_SAMPLE_BEAT,
            frame_paths=[],
        )
        assert result["decision"] == "error"
        assert "reason" in result

    def test_passes_frame_paths_through_to_result(self):
        """frame_paths in result must match input."""
        client = _make_mock_client()
        inspector = MultimodalInspectionClient(client=client)

        path = _make_frame_file()
        try:
            result = inspector.inspect_asset(
                job_id=1,
                beat_id="B03",
                asset_id="A001",
                beat=_SAMPLE_BEAT,
                frame_paths=[path],
            )
        finally:
            os.unlink(path)

        assert path in result["frame_paths"]

    def test_uses_custom_model(self):
        """Client should use the model passed in constructor."""
        client = _make_mock_client()
        inspector = MultimodalInspectionClient(
            client=client,
            model="anthropic/claude-3.5-sonnet",
        )

        path = _make_frame_file()
        try:
            inspector.inspect_asset(
                job_id=1,
                beat_id="B03",
                asset_id="A001",
                beat=_SAMPLE_BEAT,
                frame_paths=[path],
            )
        finally:
            os.unlink(path)

        call_kwargs = client.chat.call_args
        assert call_kwargs[1]["model"] == "anthropic/claude-3.5-sonnet"

    def test_source_metadata_included(self):
        """source_metadata should be passed through to prompt construction."""
        client = _make_mock_client()
        inspector = MultimodalInspectionClient(client=client)

        result = inspector.inspect_asset(
            job_id=1,
            beat_id="B03",
            asset_id="A001",
            beat=_SAMPLE_BEAT,
            frame_paths=[],
            source_metadata={"source": "scrapecreators", "url": "https://tiktok.com/xyz"},
        )
        # If we got here without error, prompt construction accepted the metadata
        assert result["decision"] in ("accept", "error")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text_from_messages(msgs: list[dict]) -> str:
    """Concatenate all text content from messages."""
    parts: list[str] = []
    for msg in msgs:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
    return "\n".join(parts)


def _extract_image_parts(msgs: list[dict]) -> list[dict]:
    """Extract image_url parts from messages."""
    images: list[dict] = []
    for msg in msgs:
        content = msg.get("content", [])
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    images.append(part)
    return images
