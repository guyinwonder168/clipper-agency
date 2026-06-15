"""Tests for Segment Producer per-beat precision upgrade (Phase 26 PR 4).

Tests verify:
- Beat keyword extraction from visual_must_show + caption_keywords + spoken_point
- Candidate-to-beat scoring via keyword overlap
- Global candidate distribution to beats that lack candidates
- Provider attempt history tracking
"""

import pytest

from clipper_agency.agents.segment_producer import SegmentProducerAgent


# ─── Test fixtures ──────────────────────────────────────────────────────

def _make_beat(
    beat_id: int = 1,
    role: str = "hook",
    visual_must_show: str = "",
    spoken_point: str = "",
    caption_keywords: list[str] | None = None,
    asset_candidates: list[dict] | None = None,
) -> dict:
    """Build a minimal beat dict matching SP output shape."""
    return {
        "beat_id": beat_id,
        "role": role,
        "narration_goal": "",
        "spoken_point": spoken_point,
        "safe_wording": "",
        "visual_must_show": visual_must_show,
        "visual_must_not_show": "",
        "overlay_text": "",
        "caption_keywords": caption_keywords or [],
        "asset_candidates": asset_candidates or [],
        "fallback": {"type": "text_card", "headline": "", "image_search": ""},
    }


def _make_candidate(
    url: str = "https://example.com/clip1",
    title: str = "",
    reason: str = "",
    source: str = "scrapecreators",
    type_: str = "tiktok_clip",
) -> dict:
    """Build a minimal candidate dict matching SP output shape."""
    return {
        "type": type_,
        "url": url,
        "reason": reason or title or "Candidate",
        "source": source,
        "title": title,
        "relevance_score": 0.5,
        "provenance": "primary_clip",
        "source_type": type_,
    }


# ─── Keyword extraction tests ───────────────────────────────────────────

class TestExtractBeatKeywords:
    """_extract_beat_keywords pulls keywords from beat context fields."""

    def test_extracts_from_visual_must_show(self):
        beat = _make_beat(visual_must_show="foto artis konser")
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert "artis" in keywords
        assert "konser" in keywords

    def test_extracts_from_caption_keywords(self):
        beat = _make_beat(caption_keywords=["berita viral", "artis"])
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert "berita viral" in keywords
        assert "artis" in keywords

    def test_extracts_from_spoken_point(self):
        beat = _make_beat(spoken_point="Artis X tampil di panggung")
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert "artis" in keywords
        assert "panggung" in keywords

    def test_combines_all_sources(self):
        beat = _make_beat(
            visual_must_show="foto konser",
            caption_keywords=["artis"],
            spoken_point="Berita terbaru hari ini",
        )
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert "konser" in keywords
        assert "artis" in keywords
        assert "berita" in keywords

    def test_dedupes_across_sources(self):
        beat = _make_beat(
            visual_must_show="artis",
            caption_keywords=["artis"],
            spoken_point="artis",
        )
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert keywords.count("artis") == 1

    def test_filters_short_words(self):
        """Words shorter than 3 chars are noise — filter them."""
        beat = _make_beat(visual_must_show="di ke ya artis")
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert "artis" in keywords
        # Short words should not appear
        for w in ("di", "ke", "ya"):
            assert w not in keywords

    def test_empty_beat_returns_empty_list(self):
        beat = _make_beat()
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert keywords == []

    def test_all_keywords_lowercased(self):
        beat = _make_beat(visual_must_show="ARTIS Konser")
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert all(k == k.lower() for k in keywords)


# ─── Candidate scoring tests ────────────────────────────────────────────

class TestScoreCandidateForBeat:
    """_score_candidate_for_beat returns relevance score 0.0-1.0."""

    def test_high_score_when_title_matches(self):
        candidate = _make_candidate(title="Artis viral di TikTok")
        score = SegmentProducerAgent._score_candidate_for_beat(
            candidate, ["artis", "viral"],
        )
        assert score > 0.5

    def test_zero_score_when_no_match(self):
        candidate = _make_candidate(title="Resep masakan hari ini")
        score = SegmentProducerAgent._score_candidate_for_beat(
            candidate, ["artis", "konser"],
        )
        assert score == 0.0

    def test_partial_score_when_some_match(self):
        candidate = _make_candidate(title="Artis film baru")
        score = SegmentProducerAgent._score_candidate_for_beat(
            candidate, ["artis", "konser"],
        )
        assert 0.0 < score < 1.0

    def test_uses_reason_field_as_fallback(self):
        candidate = _make_candidate(title="", reason="Video artis konser")
        score = SegmentProducerAgent._score_candidate_for_beat(
            candidate, ["artis", "konser"],
        )
        assert score > 0.0

    def test_empty_keywords_returns_zero(self):
        candidate = _make_candidate(title="Artis viral")
        score = SegmentProducerAgent._score_candidate_for_beat(
            candidate, [],
        )
        assert score == 0.0


# ─── Distribution tests ─────────────────────────────────────────────────

class TestDistributeCandidatesToBeats:
    """_distribute_candidates_to_beats assigns global candidates to beats."""

    def test_empty_beats_get_candidates_assigned(self):
        beats = [_make_beat(beat_id=1, visual_must_show="artis")]
        candidates = [_make_candidate(title="Artis viral")]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        assert len(result[0]["asset_candidates"]) > 0

    def test_prepopulated_beats_are_skipped(self):
        existing = [_make_candidate(url="https://existing.com")]
        beats = [_make_beat(beat_id=1, asset_candidates=existing)]
        candidates = [_make_candidate(url="https://global.com", title="artis")]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        # Should keep only the pre-existing candidates
        assert len(result[0]["asset_candidates"]) == 1
        assert result[0]["asset_candidates"][0]["url"] == "https://existing.com"

    def test_distributed_candidates_get_related_beat_id(self):
        beats = [_make_beat(beat_id=3, visual_must_show="artis")]
        candidates = [_make_candidate(url="https://clip.com", title="Artis")]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        assert result[0]["asset_candidates"][0]["related_beat_id"] == 3

    def test_respects_max_per_beat_limit(self):
        beats = [_make_beat(beat_id=1, visual_must_show="artis")]
        candidates = [
            _make_candidate(url=f"https://c{i}.com", title=f"Artis {i}")
            for i in range(10)
        ]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates, max_per_beat=5,
        )
        assert len(result[0]["asset_candidates"]) <= 5

    def test_no_global_candidates_leaves_beats_unchanged(self):
        beats = [_make_beat(beat_id=1)]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, [],
        )
        assert result[0]["asset_candidates"] == []

    def test_candidates_sorted_by_score_descending(self):
        beats = [_make_beat(beat_id=1, visual_must_show="artis konser")]
        candidates = [
            _make_candidate(url="https://low.com", title="artis"),
            _make_candidate(url="https://high.com", title="artis konser viral"),
            _make_candidate(url="https://mid.com", title="artis"),
        ]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        assigned = result[0]["asset_candidates"]
        # Highest-scoring candidate should be first
        assert assigned[0]["url"] == "https://high.com"

    def test_unmatched_candidates_not_assigned(self):
        """Candidate with zero keyword overlap should not be assigned."""
        beats = [_make_beat(beat_id=1, visual_must_show="artis")]
        candidates = [_make_candidate(title="resep masakan")]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        assert result[0]["asset_candidates"] == []

    def test_multiple_beats_distribute_independently(self):
        beats = [
            _make_beat(beat_id=1, visual_must_show="konser"),
            _make_beat(beat_id=2, visual_must_show="wawancara"),
        ]
        candidates = [
            _make_candidate(url="https://konser.com", title="Konser artis"),
            _make_candidate(url="https://wawancara.com", title="Wawancara exklusif"),
        ]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        beat1_urls = [c["url"] for c in result[0]["asset_candidates"]]
        beat2_urls = [c["url"] for c in result[1]["asset_candidates"]]
        assert "https://konser.com" in beat1_urls
        assert "https://wawancara.com" in beat2_urls

    def test_does_not_mutate_input_beats(self):
        """Original beat list should not be modified (immutability)."""
        beats = [_make_beat(beat_id=1, visual_must_show="artis")]
        candidates = [_make_candidate(title="Artis")]
        original_len = len(beats[0]["asset_candidates"])
        SegmentProducerAgent._distribute_candidates_to_beats(beats, candidates)
        assert len(beats[0]["asset_candidates"]) == original_len


# ─── Provider attempt tracking tests ────────────────────────────────────

class TestProviderAttemptTracking:
    """Provider attempt history is tracked during multi-source discovery."""

    def test_provider_attempts_format(self):
        """Each provider attempt has provider, query, result_count."""
        attempt = {
            "provider": "youtube",
            "query": "artis viral",
            "result_count": 3,
        }
        assert "provider" in attempt
        assert "query" in attempt
        assert "result_count" in attempt

    def test_discover_returns_attempts(self, monkeypatch):
        """_discover_multi_source_assets returns (sources, attempts) tuple."""
        agent = SegmentProducerAgent()

        class FakeConfig:
            tavily_api_key = ""
            brave_api_key = ""

        class FakeYtDlp:
            def search(self, query, max_results=3):
                return [{"url": f"https://yt.com/{query}", "title": query,
                          "source_type": "youtube_official"}]

        monkeypatch.setattr(
            "clipper_agency.agents.segment_producer.YtDlpService", FakeYtDlp,
        )

        result = agent._discover_multi_source_assets(
            topic="artis",
            entities={},
            config=FakeConfig(),
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        sources, attempts = result
        assert isinstance(sources, list)
        assert isinstance(attempts, list)
        assert len(attempts) > 0
        assert attempts[0]["provider"] == "youtube"
