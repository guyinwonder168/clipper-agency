from clipper_agency.orchestrator.timeline import (
    reconcile_timeline,
    TimelineItem,
    ReconciledTimeline,
)


class TestTimelineReconciler:
    def test_basic_reconciliation(self):
        scenes = [
            {"scene": 1, "role": "opening_hook", "text": "hello", "estimated_duration_sec": 5},
            {"scene": 2, "role": "story_1", "text": "story", "estimated_duration_sec": 10},
            {"scene": 3, "role": "cta", "text": "follow", "estimated_duration_sec": 5},
        ]
        audio_meta = [
            {"scene": 1, "audio_duration_sec": 8.7, "audio_path": "s1.mp3", "provider": "el"},
            {"scene": 2, "audio_duration_sec": 12.1, "audio_path": "s2.mp3", "provider": "el"},
            {"scene": 3, "audio_duration_sec": 6.3, "audio_path": "s3.mp3", "provider": "el"},
        ]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)

        assert result.within_limit is True
        assert result.total_duration_sec == 27.1
        assert result.timeline[0].role == "opening_hook"
        assert result.timeline[0].start_sec == 0.0
        assert result.timeline[0].end_sec == 8.7
        assert result.timeline[1].start_sec == 8.7
        assert abs(result.timeline[2].start_sec - 20.8) < 0.01

    def test_exceeds_hard_limit(self):
        scenes = [{"scene": 1, "role": "opening_hook", "text": "x", "estimated_duration_sec": 1}]
        audio_meta = [{"scene": 1, "audio_duration_sec": 65.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert result.within_limit is False

    def test_fewer_audio_than_scenes(self):
        scenes = [
            {"scene": 1, "role": "opening_hook", "text": "a", "estimated_duration_sec": 5},
            {"scene": 2, "role": "story_1", "text": "b", "estimated_duration_sec": 5},
        ]
        audio_meta = [{"scene": 1, "audio_duration_sec": 5.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert result.within_limit is True
        assert len(result.timeline) == 2
        assert result.timeline[0].target_duration_sec == 5.0  # from audio
        assert result.timeline[1].target_duration_sec == 5.0  # from estimate

    def test_visual_instruction_for_opening_hook(self):
        scenes = [{"scene": 1, "role": "opening_hook", "text": "x", "estimated_duration_sec": 4}]
        audio_meta = [{"scene": 1, "audio_duration_sec": 4.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert "opening card" in result.timeline[0].visual_instruction

    def test_visual_instruction_for_cta(self):
        scenes = [{"scene": 1, "role": "cta", "text": "x", "estimated_duration_sec": 4}]
        audio_meta = [{"scene": 1, "audio_duration_sec": 4.0, "audio_path": "s1.mp3", "provider": "el"}]
        result = reconcile_timeline(scenes, audio_meta, target=55, hard=60)
        assert "cta card" in result.timeline[0].visual_instruction.lower()

    def test_empty_scenes(self):
        result = reconcile_timeline([], [], target=55, hard=60)
        assert result.within_limit is True
        assert result.total_duration_sec == 0.0
        assert result.timeline == []
