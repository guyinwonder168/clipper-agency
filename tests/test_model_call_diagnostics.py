"""Tests for universal model-call diagnostics."""

import json
from pathlib import Path

import pytest

from clipper_agency.core.model_diagnostics import (
    ModelCallDiagnostic,
    write_model_call_diagnostic,
)


class TestLLMModelCallDiagnostics:
    """Tests for LLM client model-call diagnostic logging."""

    def test_llm_client_writes_model_call_diagnostic_when_context_provided(self, tmp_path, mocker):
        """LLM call with diagnostic context should write a JSON diagnostic file."""
        job_dir = tmp_path / "job_99" / "agents" / "visual_director" / "model_calls"
        job_dir.mkdir(parents=True)

        diag = ModelCallDiagnostic(
            provider="openrouter",
            model="google/gemini-2.0-flash-001",
            input_payload={"messages": [{"role": "user", "content": "plan scenes"}]},
            raw_response='{"scenes": []}',
            parsed_output={"scenes": []},
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            estimated_cost_usd=0.0015,
            latency_ms=1200,
            retry_count=0,
            status="success",
            error=None,
        )

        write_model_call_diagnostic(
            output_dir=str(job_dir),
            agent="visual_director",
            purpose="scene_plan",
            diagnostic=diag,
        )

        # Should have written exactly one JSON file
        files = list(job_dir.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text())
        assert data["agent"] == "visual_director"
        assert data["purpose"] == "scene_plan"
        assert data["provider"] == "openrouter"
        assert data["model"] == "google/gemini-2.0-flash-001"
        assert data["usage"]["total_tokens"] == 150
        assert data["latency_ms"] == 1200
        assert data["status"] == "success"
        assert data["error"] is None

    def test_llm_diagnostic_includes_error_on_failure(self, tmp_path):
        """Failed model call should write diagnostic with error details."""
        job_dir = tmp_path / "job_99" / "agents" / "scriptwriter" / "model_calls"
        job_dir.mkdir(parents=True)

        diag = ModelCallDiagnostic(
            provider="openrouter",
            model="test-model",
            input_payload={},
            raw_response=None,
            parsed_output=None,
            usage={},
            estimated_cost_usd=0.0,
            latency_ms=5000,
            retry_count=2,
            status="error",
            error="HTTP 429 Rate Limited",
        )

        write_model_call_diagnostic(
            output_dir=str(job_dir),
            agent="scriptwriter",
            purpose="generate_script",
            diagnostic=diag,
        )

        files = list(job_dir.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["status"] == "error"
        assert data["error"] == "HTTP 429 Rate Limited"
        assert data["retry_count"] == 2


class TestTTSModelCallDiagnostics:
    """Tests for TTS provider model-call diagnostic logging."""

    def test_tts_provider_writes_model_call_diagnostic_when_context_provided(self, tmp_path):
        """TTS call with diagnostic context should write a JSON diagnostic file."""
        job_dir = tmp_path / "job_99" / "agents" / "voice_producer" / "model_calls"
        job_dir.mkdir(parents=True)

        diag = ModelCallDiagnostic(
            provider="elevenlabs",
            model="eleven_multilingual_v2",
            input_payload={"text_length": 450, "voice_id": "abc123"},
            raw_response=None,
            parsed_output={"duration_sec": 23.25, "file_size": 50000},
            usage={"characters": 450},
            estimated_cost_usd=0.03,
            latency_ms=8000,
            retry_count=0,
            status="success",
            error=None,
        )

        write_model_call_diagnostic(
            output_dir=str(job_dir),
            agent="voice_producer",
            purpose="tts_generation",
            diagnostic=diag,
        )

        files = list(job_dir.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text())
        assert data["agent"] == "voice_producer"
        assert data["provider"] == "elevenlabs"
        assert data["purpose"] == "tts_generation"
        assert data["parsed_output"]["duration_sec"] == 23.25
