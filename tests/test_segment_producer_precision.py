"""Tests for Segment Producer per-beat precision upgrade (Phase 26 PR 4).

Tests verify:
- Beat keyword extraction from visual_must_show + caption_keywords + spoken_point
- Candidate-to-beat scoring via keyword overlap
- Global candidate distribution to beats (merge, not skip)
- Entity + risk_flags parsing from LLM synthesis
- Stop-word filtering for cleaner keyword extraction
- Per-beat search query building
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


# ─── Entity + risk_flags parsing tests ──────────────────────────────────

class TestParseSynthesisEntities:
    """_parse_synthesis_response extracts entities + risk_flags from LLM output."""

    @staticmethod
    def _agent():
        return SegmentProducerAgent()

    def test_extracts_entities_when_present(self):
        """LLM returns structured entities — parser must capture them."""
        llm_output = '''```json
        {
            "research_brief": "Brief",
            "story_beats": [],
            "entities": [
                {"name": "Artis X", "type": "person"},
                {"name": "Konser Y", "type": "event", "date": "2025-01-01"}
            ]
        }
        ```'''
        result = self._agent()._parse_synthesis_response(llm_output)
        assert "entities" in result
        assert isinstance(result["entities"], list)
        assert len(result["entities"]) == 2
        assert result["entities"][0]["name"] == "Artis X"

    def test_extracts_risk_flags_when_present(self):
        """LLM returns top-level risk_flags — parser must capture them."""
        llm_output = '''```json
        {
            "research_brief": "Brief",
            "story_beats": [],
            "risk_flags": [
                {"category": "legal", "description": "Unverified allegation"},
                {"category": "safety", "description": "Sensitive topic"}
            ]
        }
        ```'''
        result = self._agent()._parse_synthesis_response(llm_output)
        assert "risk_flags" in result
        assert isinstance(result["risk_flags"], list)
        assert len(result["risk_flags"]) == 2
        assert result["risk_flags"][0]["category"] == "legal"

    def test_defaults_entities_empty_when_absent(self):
        """When LLM omits entities, parser returns empty list."""
        llm_output = '{"research_brief": "Brief", "story_beats": []}'
        result = self._agent()._parse_synthesis_response(llm_output)
        assert result["entities"] == []

    def test_defaults_risk_flags_empty_when_absent(self):
        """When LLM omits risk_flags, parser returns empty list."""
        llm_output = '{"research_brief": "Brief", "story_beats": []}'
        result = self._agent()._parse_synthesis_response(llm_output)
        assert result["risk_flags"] == []

    def test_existing_fields_still_parsed(self):
        """Adding entities + risk_flags should not break existing fields."""
        llm_output = '''{
            "research_brief": "Brief",
            "story_beats": [{"beat_id": 1, "visual_must_show": "artis"}],
            "entities": [{"name": "X"}],
            "risk_flags": [],
            "verified_facts": [{"fact": "test"}]
        }'''
        result = self._agent()._parse_synthesis_response(llm_output)
        assert result["research_brief"] == "Brief"
        assert len(result["story_beats"]) == 1
        assert len(result["verified_facts"]) == 1
        assert result["entities"] == [{"name": "X"}]


# ─── Distribution merge tests ───────────────────────────────────────────

class TestDistributeMergeNotSkip:
    """Beats with existing candidates should MERGE, not skip distribution."""

    def test_merges_global_into_beat_with_existing_candidates(self):
        """4e fix: beats with LLM candidates should also get global candidates."""
        existing = [_make_candidate(url="https://llm.com", title="LLM pick")]
        beats = [_make_beat(
            beat_id=1, visual_must_show="artis", asset_candidates=existing,
        )]
        candidates = [_make_candidate(
            url="https://global.com", title="Artis viral",
        )]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        assigned_urls = [c["url"] for c in result[0]["asset_candidates"]]
        assert "https://llm.com" in assigned_urls
        assert "https://global.com" in assigned_urls

    def test_distributed_candidates_get_distribution_score(self):
        """4e fix: score must be persisted on candidate for debugging."""
        beats = [_make_beat(beat_id=1, visual_must_show="artis konser")]
        candidates = [_make_candidate(title="Artis konser viral")]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        assigned = result[0]["asset_candidates"]
        assert len(assigned) > 0
        assert "distribution_score" in assigned[0]
        assert assigned[0]["distribution_score"] > 0.0

    def test_min_threshold_filters_noise(self):
        """4e fix: candidates scoring below 0.1 should be rejected."""
        beats = [_make_beat(beat_id=1, visual_must_show="artis konser viral")]
        # Only 1 of 3 keywords matched = 0.33 score — should pass
        weak = _make_candidate(url="https://weak.com", title="artis")
        # 0 of 3 keywords matched = 0.0 score — should be filtered
        noise = _make_candidate(url="https://noise.com", title="resep masakan")
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, [weak, noise],
        )
        urls = [c["url"] for c in result[0]["asset_candidates"]]
        assert "https://weak.com" in urls
        assert "https://noise.com" not in urls

    def test_dedupes_when_merging_llm_and_global(self):
        """Same URL in both LLM and global should not produce duplicates."""
        shared_url = "https://shared.com"
        existing = [_make_candidate(url=shared_url, title="Artis")]
        beats = [_make_beat(
            beat_id=1, visual_must_show="artis", asset_candidates=existing,
        )]
        candidates = [_make_candidate(url=shared_url, title="Artis")]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates,
        )
        urls = [c["url"] for c in result[0]["asset_candidates"]]
        assert urls.count(shared_url) == 1

    def test_global_candidates_get_slots_when_beat_full(self):
        """Interleave: when existing fills max_per_beat, globals still get in.

        Regression for CodeReviewer finding: append-after-then-slice was
        a no-op when existing >= max_per_beat. Interleave ensures diversity.
        """
        existing = [
            _make_candidate(url=f"https://llm{i}.com", title="artis")
            for i in range(5)
        ]
        beats = [_make_beat(
            beat_id=1, visual_must_show="artis", asset_candidates=existing,
        )]
        candidates = [_make_candidate(
            url="https://global.com", title="artis viral",
        )]
        result = SegmentProducerAgent._distribute_candidates_to_beats(
            beats, candidates, max_per_beat=5,
        )
        urls = [c["url"] for c in result[0]["asset_candidates"]]
        assert "https://global.com" in urls
        assert len(urls) == 5


# ─── Stop-word filtering tests ──────────────────────────────────────────

class TestStopWordFiltering:
    """_extract_beat_keywords filters common stop words."""

    def test_filters_indonesian_stop_words(self):
        """Common Indonesian stop words should be filtered."""
        beat = _make_beat(
            visual_must_show="yang di ke ini ada dengan artis",
            spoken_point="itu juga untuk pada artis",
        )
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert "artis" in keywords
        for stop in ("yang", "ini", "itu", "juga", "untuk", "pada", "dengan"):
            assert stop not in keywords, f"Stop word '{stop}' should be filtered"

    def test_filters_english_stop_words(self):
        """Common English stop words should be filtered."""
        beat = _make_beat(
            visual_must_show="the and with that this artis",
        )
        keywords = SegmentProducerAgent._extract_beat_keywords(beat)
        assert "artis" in keywords
        for stop in ("the", "and", "with", "that", "this"):
            assert stop not in keywords


# ─── Per-beat search query tests ────────────────────────────────────────

class TestPerBeatSearchQueries:
    """_build_search_queries should derive queries from beat context."""

    def test_builds_queries_from_beats(self):
        """When beat context provided, queries should include beat keywords."""
        agent = SegmentProducerAgent()
        beats = [
            _make_beat(
                beat_id=1,
                visual_must_show="konser artis",
                spoken_point="Artis tampil di konser",
            ),
            _make_beat(
                beat_id=2,
                visual_must_show="wawancara",
                spoken_point="Wawancara exklusif",
            ),
        ]
        queries = agent._build_search_queries(
            topic="artis viral", entities={}, beats=beats,
        )
        # Should include topic + at least one beat-derived query
        assert len(queries) >= 2
        assert "artis viral" in queries

    def test_topic_only_when_no_beats(self):
        """Without beats, falls back to topic + entity queries (backward compat)."""
        agent = SegmentProducerAgent()
        queries = agent._build_search_queries(
            topic="artis", entities={}, beats=None,
        )
        assert queries == ["artis"]

    def test_respects_max_queries(self):
        """Query count should be bounded (avoid overloading providers)."""
        agent = SegmentProducerAgent()
        beats = [
            _make_beat(beat_id=i, visual_must_show=f"topic{i}")
            for i in range(10)
        ]
        queries = agent._build_search_queries(
            topic="artis", entities=[], beats=beats,
        )
        assert len(queries) <= 5


# ─── Codex P1/P2 regression tests (data flow propagation) ─────────────


class TestEntitiesRiskFlagsPropagation:
    """Verify entities + risk_flags flow from parse → synthesize → execute.

    Regression tests for Codex P1 finding: _synthesize_research() omitted
    entities/risk_flags from its return dict, causing empty artifacts.
    """

    @staticmethod
    def _mock_chat(content: str) -> dict:
        return {"content": content, "model": "test", "usage": {}}

    def test_synthesize_propagates_entities(self, mocker):
        """_synthesize_research() must include entities in return dict."""
        import json
        payload = json.dumps({
            "research_brief": "Brief",
            "story_beats": [],
            "entities": [{"name": "Artis", "type": "location"}],
            "risk_flags": [],
        })
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(payload),
        )
        agent = SegmentProducerAgent()
        result = agent._synthesize_research(
            {"sources": []}, "topic", [],
        )
        assert result["entities"] == [{"name": "Artis", "type": "location"}]

    def test_synthesize_propagates_risk_flags(self, mocker):
        """_synthesize_research() must include risk_flags in return dict."""
        import json
        payload = json.dumps({
            "research_brief": "Brief",
            "story_beats": [],
            "entities": [],
            "risk_flags": [{"type": "unverified_claim", "detail": "X"}],
        })
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(payload),
        )
        agent = SegmentProducerAgent()
        result = agent._synthesize_research(
            {"sources": []}, "topic", [],
        )
        assert result["risk_flags"] == [{"type": "unverified_claim", "detail": "X"}]

    def test_synthesize_defaults_entities_empty_when_missing(self, mocker):
        """When LLM omits entities, default to empty list (not KeyError)."""
        import json
        payload = json.dumps({"research_brief": "Brief", "story_beats": []})
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(payload),
        )
        agent = SegmentProducerAgent()
        result = agent._synthesize_research(
            {"sources": []}, "topic", [],
        )
        assert result["entities"] == []
        assert result["risk_flags"] == []


class TestEntitiesAsArray:
    """Verify _build_search_queries accepts entities as list (not dict).

    Regression test for Codex P2 finding: parser produces entities as
    array but _build_search_queries expected dict shape.
    """

    def test_entities_as_list_produces_entity_queries(self):
        """entities=[{name:...}] should produce '{name} {topic}' queries."""
        agent = SegmentProducerAgent()
        queries = agent._build_search_queries(
            topic="artis",
            entities=[{"name": " Rafi Ahmad", "type": "person"}],
        )
        # Should include topic + entity-based query
        assert len(queries) >= 2
        assert any("Rafi Ahmad" in q for q in queries)

    def test_entities_as_empty_list_returns_topic_only(self):
        """entities=[] should return just [topic]."""
        agent = SegmentProducerAgent()
        queries = agent._build_search_queries(topic="artis", entities=[])
        assert queries == ["artis"]

    def test_entities_as_list_of_strings(self):
        """entities as list of plain strings should also work."""
        agent = SegmentProducerAgent()
        queries = agent._build_search_queries(
            topic="artis", entities=["Rafi Ahmad", "Nagita Slavina"],
        )
        assert len(queries) >= 2
