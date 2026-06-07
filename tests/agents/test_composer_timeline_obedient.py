from clipper_agency.agents.composer import ComposerAgent


class TestComposerTimelineObedient:
    def test_resolve_asset_durations_from_timeline(self):
        agent = ComposerAgent()
        timeline = [
            {
                "scene": 1,
                "role": "opening_hook",
                "target_duration_sec": 8.7,
                "audio_path": "/tmp/s1.mp3",
            },
            {
                "scene": 2,
                "role": "cta",
                "target_duration_sec": 5.3,
                "audio_path": "/tmp/s2.mp3",
            },
        ]
        default_assets = [
            {"scene": 1, "target_duration": 3},
            {"scene": 2, "target_duration": 5},
        ]
        resolved = agent._apply_timeline_to_assets(default_assets, timeline)
        assert resolved[0]["target_duration"] == 8.7
        assert resolved[1]["target_duration"] == 5.3

    def test_no_timeline_preserves_original_durations(self):
        agent = ComposerAgent()
        assets = [{"scene": 1, "target_duration": 5}]
        resolved = agent._apply_timeline_to_assets(assets, None)
        assert resolved[0]["target_duration"] == 5

    def test_timeline_pairs_correct_audio_files(self):
        agent = ComposerAgent()
        timeline = [
            {"scene": 1, "audio_path": "/real/s1.mp3"},
            {"scene": 2, "audio_path": "/real/s2.mp3"},
        ]
        audio_map = agent._build_timeline_audio_map(timeline)
        assert audio_map[0] == "/real/s1.mp3"
        assert audio_map[1] == "/real/s2.mp3"

    def test_empty_timeline_returns_original_assets(self):
        agent = ComposerAgent()
        assets = [{"scene": 1, "target_duration": 5}]
        resolved = agent._apply_timeline_to_assets(assets, [])
        assert resolved[0]["target_duration"] == 5

    def test_build_audio_map_empty_timeline(self):
        agent = ComposerAgent()
        audio_map = agent._build_timeline_audio_map(None)
        assert audio_map == {}

    def test_audio_first_aligns_assets_by_beat_id_and_ignores_phantom_beat(self):
        agent = ComposerAgent()
        narrative = [
            {"beat_id": 1, "word_range": [0, 2]},
            {"beat_id": 2, "word_range": [2, 4]},
            {"beat_id": 9, "word_range": [4, 6]},
        ]
        assets = [
            {"beat_id": 1, "path": "/tmp/beat1.mp4"},
            {"beat_id": 2, "path": "/tmp/beat2.mp4"},
            {"beat_id": 8, "path": "/tmp/phantom.mp4"},
            {"beat_id": 9, "path": "/tmp/cta.mp4"},
        ]

        aligned = agent._align_assets_to_narrative_beats(narrative, assets)

        assert [item["beat_id"] for item in aligned] == [1, 2, 9]
        assert aligned[2]["path"] == "/tmp/cta.mp4"
