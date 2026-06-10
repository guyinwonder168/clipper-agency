"""Tests for LLM trace persistence in text and multimodal clients."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from clipper_agency.llm.client import OpenRouterClient
from clipper_agency.llm.multimodal_client import MultimodalInspectionClient
from clipper_agency.observability.llm_trace import LLMTraceWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure OPENROUTER_API_KEY is set for all tests in this module."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-for-tracing-tests")


@pytest.fixture()
def mock_httpx_response() -> MagicMock:
    """Create a mock successful httpx response."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"verdict": "pass", "score": 90}'}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }
    mock_resp.text = '{"choices": []}'
    mock_resp.raise_for_status = MagicMock()
    mock_resp.request = MagicMock()
    return mock_resp


@pytest.fixture()
def trace_writer(tmp_path: Path) -> LLMTraceWriter:
    return LLMTraceWriter(cache_root=str(tmp_path), redact_secrets=False)


# ---------------------------------------------------------------------------
# Text client tests
# ---------------------------------------------------------------------------


class TestOpenRouterClientTracing:
    """Trace integration for OpenRouterClient.chat_traced()."""

    def test_text_client_traces_full_lifecycle(
        self, mock_httpx_response: MagicMock, trace_writer: LLMTraceWriter, tmp_path: Path,
    ) -> None:
        client = OpenRouterClient(trace_writer=trace_writer)

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_httpx_response

            result = client.chat_traced(
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
                job_id=42,
                agent="scriptwriter",
                task="write_script",
            )

        # Verify the chat result is returned unchanged
        assert result["content"] == '{"verdict": "pass", "score": 90}'
        assert result["model"] == "test-model"
        assert result["usage"]["total_tokens"] == 150

        # Find the trace directory
        trace_root = tmp_path / "job_42" / "llm_traces" / "scriptwriter"
        assert trace_root.exists()
        call_dir = list(trace_root.iterdir())[0]

        # Verify artifacts exist
        assert (call_dir / "request.json").exists()
        assert (call_dir / "response.json").exists()
        assert (call_dir / "metadata.json").exists()

        # Verify metadata content
        metadata = json.loads((call_dir / "metadata.json").read_text())
        assert metadata["job_id"] == 42
        assert metadata["agent"] == "scriptwriter"
        assert metadata["task"] == "write_script"
        assert metadata["provider"] == "openrouter"
        assert metadata["model"] == "test-model"

        # Verify request content
        request = json.loads((call_dir / "request.json").read_text())
        assert any("Hello" in str(m) for m in request["messages"])

        # Verify response content
        response = json.loads((call_dir / "response.json").read_text())
        assert response["usage"]["total_tokens"] == 150

    def test_text_client_no_trace_when_writer_is_none(
        self, mock_httpx_response: MagicMock, tmp_path: Path,
    ) -> None:
        client = OpenRouterClient(trace_writer=None)

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_httpx_response

            result = client.chat_traced(
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
                job_id=1,
                agent="test",
                task="test",
            )

        assert result["content"] == '{"verdict": "pass", "score": 90}'
        # No trace directories should be created
        llm_traces = tmp_path / "llm_traces"
        assert not llm_traces.exists()

    def test_text_client_existing_chat_unchanged(
        self, mock_httpx_response: MagicMock, tmp_path: Path,
    ) -> None:
        client = OpenRouterClient(trace_writer=None)

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_httpx_response

            result = client.chat(
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
            )

        # Original chat() works unchanged
        assert result["content"] == '{"verdict": "pass", "score": 90}'
        assert result["model"] == "test-model"
        assert result["usage"]["total_tokens"] == 150


# ---------------------------------------------------------------------------
# Multimodal client tests
# ---------------------------------------------------------------------------


class TestMultimodalClientTracing:
    """Trace integration for MultimodalInspectionClient.inspect_asset()."""

    @pytest.fixture()
    def mock_llm_client(self) -> MagicMock:
        client = MagicMock()
        client.chat.return_value = {
            "content": json.dumps({
                "person_match": 0.9, "event_match": 0.8,
                "claim_support": 0.7, "visual_quality": 0.85,
                "temporal_match": 0.75, "source_credibility": 0.8,
                "cleanliness_score": 0.6, "misleading_risk": 0.1,
                "decision": "accept", "reason": "Good match",
            }),
            "model": "test-mm-model",
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        }
        return client

    def test_multimodal_client_traces_inspection(
        self, mock_llm_client: MagicMock, trace_writer: LLMTraceWriter, tmp_path: Path,
    ) -> None:
        mm = MultimodalInspectionClient(
            client=mock_llm_client,
            model="test-mm-model",
            trace_writer=trace_writer,
        )

        with patch(
            "clipper_agency.llm.multimodal_client._encode_image",
            return_value="data:image/jpeg;base64,AAAA",
        ):
            result = mm.inspect_asset(
                job_id=5,
                beat_id="b1",
                asset_id="a1",
                beat={"spoken_point": "Test claim"},
                frame_paths=["/tmp/frame1.jpg"],
            )

        assert result["decision"] == "accept"

        # Verify trace artifacts created
        trace_root = tmp_path / "job_5" / "llm_traces" / "visual_director"
        assert trace_root.exists()
        call_dir = list(trace_root.iterdir())[0]

        metadata = json.loads((call_dir / "metadata.json").read_text())
        assert metadata["agent"] == "visual_director"
        assert metadata["task"] == "candidate_inspection"
        assert metadata["job_id"] == 5

        assert (call_dir / "request.json").exists()
        assert (call_dir / "response.json").exists()
        assert (call_dir / "parsed_response.json").exists()

    def test_multimodal_client_tracing_failure_doesnt_break_inspection(
        self, mock_llm_client: MagicMock, tmp_path: Path,
    ) -> None:
        broken_writer = MagicMock(spec=LLMTraceWriter)
        broken_writer.start_call.side_effect = RuntimeError("disk full")

        mm = MultimodalInspectionClient(
            client=mock_llm_client,
            model="test-mm-model",
            trace_writer=broken_writer,
        )

        with patch(
            "clipper_agency.llm.multimodal_client._encode_image",
            return_value="data:image/jpeg;base64,AAAA",
        ):
            result = mm.inspect_asset(
                job_id=6,
                beat_id="b1",
                asset_id="a1",
                beat={"spoken_point": "Test claim"},
                frame_paths=["/tmp/frame1.jpg"],
            )

        # Inspection still completes despite trace failure
        assert result["decision"] == "accept"


# ---------------------------------------------------------------------------
# Correlation and request content tests
# ---------------------------------------------------------------------------


class TestTraceCorrelationFields:
    """Verify trace metadata has all required correlation fields."""

    def test_trace_includes_correlation_fields(
        self, mock_httpx_response: MagicMock, trace_writer: LLMTraceWriter, tmp_path: Path,
    ) -> None:
        client = OpenRouterClient(trace_writer=trace_writer)

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_httpx_response

            client.chat_traced(
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
                job_id=99,
                agent="reviewer",
                task="quality_check",
            )

        trace_root = tmp_path / "job_99" / "llm_traces" / "reviewer"
        call_dir = list(trace_root.iterdir())[0]
        metadata = json.loads((call_dir / "metadata.json").read_text())

        required_fields = ["job_id", "agent", "task", "call_id", "model", "provider"]
        for field in required_fields:
            assert field in metadata, f"Missing correlation field: {field}"
        assert metadata["job_id"] == 99
        assert metadata["agent"] == "reviewer"
        assert metadata["task"] == "quality_check"
        assert metadata["provider"] == "openrouter"

    def test_trace_request_contains_messages(
        self, mock_httpx_response: MagicMock, trace_writer: LLMTraceWriter, tmp_path: Path,
    ) -> None:
        client = OpenRouterClient(trace_writer=trace_writer)
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Write a script about cats."},
        ]

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_httpx_response

            client.chat_traced(
                model="test-model",
                messages=messages,
                job_id=10,
                agent="scriptwriter",
                task="write_script",
            )

        trace_root = tmp_path / "job_10" / "llm_traces" / "scriptwriter"
        call_dir = list(trace_root.iterdir())[0]
        request = json.loads((call_dir / "request.json").read_text())

        assert len(request["messages"]) == 2
        assert request["messages"][0]["role"] == "system"
        assert request["messages"][0]["content"] == "You are helpful."
        assert request["messages"][1]["content"] == "Write a script about cats."
