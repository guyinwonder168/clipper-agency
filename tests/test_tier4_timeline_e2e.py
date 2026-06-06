"""Tier 4 integration tests — timeline reconciler to composer flow."""

import pytest

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.orchestrator.timeline import reconcile_timeline


@pytest.mark.integration
class TestTimelineEndToEnd:
    def test_timeline_reconciler_to_composer_flow(self):
        """Full flow: script + audio meta → timeline → composer render plan."""
        scenes = [
            {
                "scene": 1,
                "role": "opening_hook",
                "text": "hello",
                "estimated_duration_sec": 5,
            },
        ]
        audio_meta = [
            {
                "scene": 1,
                "audio_duration_sec": 8.7,
                "audio_path": "s1.mp3",
                "provider": "el",
            },
        ]
        timeline = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert timeline.within_limit

        # Composer applies timeline to assets
        agent = ComposerAgent()
        assets = [{"scene": 1, "target_duration": 3}]
        resolved = agent._apply_timeline_to_assets(assets, timeline.timeline)
        assert resolved[0]["target_duration"] == 8.7

    def test_overlong_audio_fails_before_visual_director(self):
        """60s+ audio must fail at Timeline Reconciler, not after Visual Director."""
        scenes = [
            {"scene": i, "role": r, "text": "!", "estimated_duration_sec": 1}
            for i, r in enumerate(
                ["opening_hook", "story_1", "story_2", "story_3", "cta"], 1,
            )
        ]
        audio_meta = [
            {
                "scene": i,
                "audio_duration_sec": 15.0,
                "audio_path": f"s{i}.mp3",
                "provider": "el",
            }
            for i in range(1, 6)
        ]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert result.total_duration_sec == 75.0
        assert result.within_limit is False
