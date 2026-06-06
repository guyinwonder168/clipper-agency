"""Tests for Visual Director timeline-aware scene resolution."""

from clipper_agency.agents.visual_director import VisualDirectorAgent


class TestVisualDirectorTimelineAware:
    def test_execute_receives_timeline_kwarg(self):
        """If timeline is present, Visual Director uses it for durations."""
        agent = VisualDirectorAgent()
        timeline = [
            {
                "scene": 1,
                "role": "opening_hook",
                "text": "hello",
                "target_duration_sec": 8.7,
                "visual_instruction": "opening card",
                "audio_path": "s1.mp3",
                "audio_duration_sec": 8.7,
                "start_sec": 0.0,
                "end_sec": 8.7,
            },
            {
                "scene": 2,
                "role": "cta",
                "text": "bye",
                "target_duration_sec": 5.3,
                "visual_instruction": "cta card",
                "audio_path": "s2.mp3",
                "audio_duration_sec": 5.3,
                "start_sec": 8.7,
                "end_sec": 14.0,
            },
        ]
        scenes = agent._resolve_scene_data(
            script=[{"scene": 1, "text": "hello", "duration": 3}],
            timeline_data=timeline,
        )
        assert len(scenes) == 2
        assert scenes[0]["target_duration"] == 8.7
        assert scenes[0]["role"] == "opening_hook"
        assert scenes[1]["role"] == "cta"

    def test_no_timeline_falls_back_to_script(self):
        agent = VisualDirectorAgent()
        scenes = agent._resolve_scene_data(
            script=[{"scene": 1, "text": "hello", "duration": 5}],
            timeline_data=None,
        )
        assert len(scenes) == 1
        assert scenes[0].get("target_duration", scenes[0].get("duration")) == 5

    def test_empty_timeline_falls_back_to_script(self):
        agent = VisualDirectorAgent()
        scenes = agent._resolve_scene_data(
            script=[{"scene": 1, "text": "hello", "duration": 5}],
            timeline_data=[],
        )
        assert len(scenes) == 1
        assert scenes[0].get("target_duration", scenes[0].get("duration")) == 5
