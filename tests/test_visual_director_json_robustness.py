"""Tests for Visual Director LLM-planning JSON robustness.

Regression lock for job_17: xiaomi/mimo-v2.5 returned near-valid JSON
with a stray brace miscount in a nested ``fallback`` object, which the
old single-shot ``json.loads`` could not recover — collapsing the job
into a 0-assets G9 hard-fail. These tests pin two layers of defense:

1. ``response_format={"type": "json_object"}`` is passed on the VD
   planning LLM call (prevent the malformed-JSON class at the source).
2. ``_parse_scenes_json`` salvages near-valid JSON via ``json_repair``
   when the primary ``json.loads`` fails (survive the malformed-JSON
   class for models whose JSON mode is only best-effort).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from clipper_agency.agents.visual_director import VisualDirectorAgent

# ---------------------------------------------------------------------------
# Real job_17 failure fixture — the exact malformed payload that killed job_17.
# Scene 5's fallback object has its closing brace concatenated onto the
# ``search_query`` value (``injured"}`` then ``}``), which is the stray-brace
# class. Kept compact but faithful to the real failure shape.
# ---------------------------------------------------------------------------

JOB_17_MALFORMED_CONTENT = (
    "```json\n"
    "{\n"
    '  "scenes": [\n'
    "    {\n"
    '      "scene_number": 1,\n'
    '      "beat_id": 1,\n'
    '      "role": "hook",\n'
    '      "treatment": "hook_big_caption",\n'
    '      "target_duration": 3.5,\n'
    '      "action": {"type": "tiktok_clip", "source_url": "https://x/1"},\n'
    '      "fallback": {"type": "text_card", "headline": "BREAKING"}\n'
    "    },\n"
    "    {\n"
    '      "scene_number": 5,\n'
    '      "beat_id": 5,\n'
    '      "role": "evidence",\n'
    '      "treatment": "broll_standard",\n'
    '      "target_duration": 5.0,\n'
    '      "action": {"type": "tiktok_clip", "source_url": "https://x/5"},\n'
    '      "fallback": {\n'
    '        "type": "pexels_image",\n'
    '        "search_query": "indonesian man beard injured"}\n'
    "      }\n"
    "    }\n"
    "  ]\n"
    "}\n"
    "```"
)


class TestParseScenesJsonSalvage:
    """The json-repair salvage net recovers near-valid VD planning JSON."""

    def test_valid_json_parses_directly(self) -> None:
        content = json.dumps({"scenes": [{"scene_number": 1, "role": "hook"}]})
        scenes = VisualDirectorAgent._parse_scenes_json(content)
        assert len(scenes) == 1
        assert scenes[0]["role"] == "hook"

    def test_fenced_json_is_unwrapped(self) -> None:
        content = '```json\n{"scenes": [{"scene_number": 1}]}\n```'
        scenes = VisualDirectorAgent._parse_scenes_json(content)
        assert len(scenes) == 1

    def test_job17_stray_brace_is_salvaged(self) -> None:
        """Regression lock: the exact job_17 malformation must recover."""
        # Sanity: the fixture really is malformed (primary parse must fail).
        stripped = JOB_17_MALFORMED_CONTENT.strip().strip("```json").strip("```").strip()
        with pytest.raises(json.JSONDecodeError):
            json.loads(stripped)

        scenes = VisualDirectorAgent._parse_scenes_json(JOB_17_MALFORMED_CONTENT)
        assert len(scenes) == 2
        assert scenes[0]["role"] == "hook"
        assert scenes[1]["role"] == "evidence"
        # The recovered scene-5 fallback retains its search_query.
        assert scenes[1]["fallback"]["type"] == "pexels_image"
        assert scenes[1]["fallback"]["search_query"] == "indonesian man beard injured"

    def test_trailing_comma_is_salvaged(self) -> None:
        content = '{"scenes": [{"scene_number": 1},]}'
        scenes = VisualDirectorAgent._parse_scenes_json(content)
        assert len(scenes) == 1

    def test_empty_scenes_key_returns_empty_list(self) -> None:
        content = '{"scenes": []}'
        assert VisualDirectorAgent._parse_scenes_json(content) == []

    def test_missing_scenes_key_returns_empty_list(self) -> None:
        content = '{"other": 1}'
        assert VisualDirectorAgent._parse_scenes_json(content) == []

    def test_non_list_scenes_routes_to_fallback(self) -> None:
        """json_repair fixes SYNTAX, not SCHEMA: a recovered payload whose
        `scenes` is a dict (or any non-list) must route to fallback ([]) —
        returning it truthy would break _normalize_beat_plan downstream.
        (Codex P2 review.)"""
        # Valid JSON, but `scenes` is a dict, not a list.
        content = '{"scenes": {"scene_number": 1}}'
        assert VisualDirectorAgent._parse_scenes_json(content) == []

    def test_unsalvageable_garbage_raises(self) -> None:
        # Truly broken (no JSON structure at all) must still raise so the
        # caller's try/except logs + degrades as before.
        with pytest.raises(json.JSONDecodeError):
            VisualDirectorAgent._parse_scenes_json("this is not json at all ::::")


class TestResponseFormatPassedOnPlanning:
    """VD planning must request json_object mode (prevent malformed JSON)."""

    @pytest.fixture()
    def agent(self) -> VisualDirectorAgent:
        # Disable trace writer so the untraced chat() path is exercised.
        agent = VisualDirectorAgent(trace_writer=None)
        return agent

    def test_response_format_passed_on_plan_with_llm(
        self,
        agent: VisualDirectorAgent,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def _fake_get_agent_config(_name: str) -> dict:
            return {"model": "xiaomi/mimo-v2.5", "temperature": 0.5, "max_completion_tokens": 1024}

        mock_llm = MagicMock()
        mock_llm.chat.return_value = {
            "content": json.dumps({"scenes": []}),
            "model": "m",
            "usage": {},
        }

        def _capture_chat(**kwargs):
            captured.update(kwargs)
            return mock_llm.chat.return_value

        mock_llm.chat.side_effect = _capture_chat

        monkeypatch.setattr("clipper_agency.config.loader.get_agent_config", _fake_get_agent_config)
        monkeypatch.setattr(
            "clipper_agency.llm.client.OpenRouterClient", lambda trace_writer=None: mock_llm
        )

        result = agent._plan_with_llm(scenes=[], compact_data={}, job_id=17)

        assert mock_llm.chat.called
        call_kwargs = mock_llm.chat.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}
        # {"scenes": []} recovers to an empty plan, which the entry point
        # converts to None so the caller routes to the deterministic fallback
        # (an empty plan is not a usable plan — the job_17 failure class).
        assert result is None

    def test_response_format_passed_on_plan_beats(
        self,
        agent: VisualDirectorAgent,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_llm = MagicMock()
        # Return malformed JSON so we also exercise the salvage path here.
        mock_llm.chat.return_value = {
            "content": JOB_17_MALFORMED_CONTENT,
            "model": "m",
            "usage": {},
        }

        monkeypatch.setattr(
            "clipper_agency.config.loader.get_agent_config",
            lambda _n: {"model": "xiaomi/mimo-v2.5", "temperature": 0.5},
        )
        monkeypatch.setattr(
            "clipper_agency.llm.client.OpenRouterClient", lambda trace_writer=None: mock_llm
        )

        result = agent._plan_beats_with_llm(
            parsed_beats=[],
            beat_durations={},
            do_not_use=[],
            voiceover_duration_sec=10.0,
            topic="t",
            job_id=17,
        )

        call_kwargs = mock_llm.chat.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}
        # Salvage recovered the 2 scenes from the job_17-shaped payload.
        assert result is not None
        assert len(result) == 2
