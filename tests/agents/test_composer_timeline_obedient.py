import pytest

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

    def test_beat_durations_cover_full_voiceover_with_gaps_and_trailing_audio(self):
        narrative = [
            {"beat_id": 1, "word_range": [0, 2]},
            {"beat_id": 2, "word_range": [3, 5]},
            {"beat_id": 9, "word_range": [6, 7]},
        ]
        timestamps = [
            {"word": "a", "start": 0.0, "end": 0.5},
            {"word": "b", "start": 0.5, "end": 1.0},
            {"word": "gap", "start": 1.0, "end": 1.5},
            {"word": "c", "start": 1.5, "end": 2.0},
            {"word": "d", "start": 2.0, "end": 2.5},
            {"word": "gap2", "start": 2.5, "end": 3.0},
            {"word": "cta", "start": 3.0, "end": 3.5},
            {"word": "tail", "start": 3.5, "end": 5.0},
        ]

        durations = ComposerAgent._compute_beat_durations(narrative, timestamps)

        assert sum(durations) == pytest.approx(5.0)

    def test_inflate_durations_for_transitions_adds_padding(self):
        base = [3.0, 4.0, 5.0]
        inflated = ComposerAgent._inflate_durations_for_transitions(base, 0.5)

        assert inflated[0] == 3.5
        assert inflated[1] == 4.5
        assert inflated[2] == 5.0  # last beat unchanged

    def test_inflate_durations_empty_list(self):
        assert ComposerAgent._inflate_durations_for_transitions([], 0.5) == []


class TestJob3RegressionFixture:
    """Regression tests encoding the exact Job #3 failure pattern.

    Job #3 had 5 root causes:
    1. Phantom beat 8 from Visual Director not in narrative
    2. Composer matched by index, dropping CTA (beat 9)
    3. Duration gap: 28.7s video vs 43.45s voiceover
    4. Keyword captions instead of full subtitles
    5. Duplicate clips across beats
    """

    def test_job_3_shape_ignores_phantom_beat_and_keeps_cta(self):
        """Composer must ignore phantom beat 8 and keep CTA beat 9."""
        agent = ComposerAgent()
        narrative = [
            {"beat_id": 1, "word_range": [0, 10]},
            {"beat_id": 2, "word_range": [11, 23]},
            {"beat_id": 3, "word_range": [24, 30]},
            {"beat_id": 4, "word_range": [31, 40]},
            {"beat_id": 5, "word_range": [41, 45]},
            {"beat_id": 6, "word_range": [46, 53]},
            {"beat_id": 7, "word_range": [54, 58]},
            {"beat_id": 9, "word_range": [59, 71]},
        ]
        assets = [
            {"beat_id": beat_id, "path": f"/tmp/beat_{beat_id}.mp4"}
            for beat_id in [1, 2, 3, 4, 5, 6, 7, 8, 9]
        ]

        aligned = agent._align_assets_to_narrative_beats(narrative, assets)

        assert [item["beat_id"] for item in aligned] == [1, 2, 3, 4, 5, 6, 7, 9]
        assert aligned[-1]["path"] == "/tmp/beat_9.mp4"
        assert all(item["beat_id"] != 8 for item in aligned)

    def test_job_3_durations_cover_full_voiceover(self):
        """Beat durations must sum to full voiceover length (43.45s)."""
        # Simulate 72 words spanning 43.45s
        timestamps = []
        word_duration = 43.45 / 72
        for i in range(72):
            start = round(i * word_duration, 3)
            end = round((i + 1) * word_duration, 3)
            timestamps.append({"word": f"w{i}", "start": start, "end": end})

        narrative = [
            {"beat_id": 1, "word_range": [0, 10]},
            {"beat_id": 2, "word_range": [11, 23]},
            {"beat_id": 3, "word_range": [24, 30]},
            {"beat_id": 4, "word_range": [31, 40]},
            {"beat_id": 5, "word_range": [41, 45]},
            {"beat_id": 6, "word_range": [46, 53]},
            {"beat_id": 7, "word_range": [54, 58]},
            {"beat_id": 9, "word_range": [59, 71]},
        ]

        durations = ComposerAgent._compute_beat_durations(narrative, timestamps)

        assert sum(durations) == pytest.approx(43.45, abs=0.1)
        assert len(durations) == 8  # 8 beats, no phantom beat 8
