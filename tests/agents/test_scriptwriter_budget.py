"""Tests for scriptwriter budget obedience — role, word_count, estimated_duration_sec."""

import json

from clipper_agency.agents.scriptwriter import ScriptwriterAgent


class TestScriptwriterBudget:
    def test_parse_scene_with_role_and_budget(self):
        agent = ScriptwriterAgent()
        raw = json.dumps({
            "script": [
                {
                    "scene": 1,
                    "role": "opening_hook",
                    "text": "HOT GOSSIP ARTIS HARI INI!",
                    "word_count": 5,
                    "estimated_duration_sec": 3.0,
                },
                {
                    "scene": 2,
                    "role": "story_1",
                    "text": "Anji resmi nikah lagi dengan Wina Natalia.",
                    "word_count": 8,
                    "estimated_duration_sec": 5.0,
                },
            ],
            "caption": "Gosip terbaru! 🔥",
            "hashtags": ["#gossip", "#artis"],
            "estimated_duration": 20,
        })
        parsed = agent._parse_script_response(raw)
        assert parsed["script"][0]["role"] == "opening_hook"
        assert parsed["script"][0]["word_count"] == 5
        assert "estimated_duration_sec" in parsed["script"][0]

    def test_missing_role_defaults_to_body(self):
        agent = ScriptwriterAgent()
        raw = json.dumps({
            "script": [
                {"scene": 1, "text": "Hello", "word_count": 3},
            ],
            "caption": "",
            "hashtags": [],
            "estimated_duration": 10,
        })
        parsed = agent._parse_script_response(raw)
        assert parsed["script"][0]["role"] == "body"

    def test_missing_word_count_computed(self):
        agent = ScriptwriterAgent()
        raw = json.dumps({
            "script": [
                {"scene": 1, "text": "Hello world test"},
            ],
            "caption": "",
            "hashtags": [],
            "estimated_duration": 10,
        })
        parsed = agent._parse_script_response(raw)
        assert parsed["script"][0]["word_count"] == 3

    def test_duration_migrated_to_estimated_duration_sec(self):
        agent = ScriptwriterAgent()
        raw = json.dumps({
            "script": [
                {"scene": 1, "text": "Hello", "duration": 5.0},
            ],
            "caption": "",
            "hashtags": [],
            "estimated_duration": 10,
        })
        parsed = agent._parse_script_response(raw)
        assert parsed["script"][0]["estimated_duration_sec"] == 5.0
        assert parsed["script"][0]["duration"] == 5.0  # backward compat: kept
