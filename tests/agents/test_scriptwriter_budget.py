"""Tests for scriptwriter continuous voiceover — new output contract."""

import json

from clipper_agency.agents.scriptwriter import (
    ScriptwriterAgent,
    _contains_emoji,
    _empty_output,
    _normalize_narrative_structure,
    _validate_output,
    _word_count,
)

# ---------------------------------------------------------------------------
# Helper: build a valid LLM response for parsing tests
# ---------------------------------------------------------------------------


def _sample_voiceover_response(**overrides) -> dict:
    """Return a valid voiceover response dict suitable for JSON serialization.

    FIX-8 (ADR 0030): beats now carry ``start_cue`` (3-5 verbatim first words
    of each beat) instead of ``word_range``; the latter is backfilled by the
    normalize step from the cues. The four cues below each anchor in the
    voiceover text in spoken order, so derivation produces contiguous ranges.
    """
    base = {
        "voiceover_text": (
            "Halo guys, hari ini ada kabar besar dari dunia seleb Indonesia! "
            "Anji ternyata sudah resmi menikah lagi dengan Wina Natalia, "
            "dan ini bikin heboh banget karena nggak ada yang nyangka. "
            "Terus ada juga gossip tentang Raffi Ahmad yang katanya lagi punya "
            "project baru bareng Nagita Slavina, tapi ini belum bisa dipastikan. "
            "Dan yang paling bikin penasaran, ternyata ada artis lain yang juga "
            "lagi proses pernikahan rahasia nih, tapi namanya masih dirahasiakan. "
            "Jadi tunggu aja kelanjutannya ya, jangan lupa follow buat update "
            "gossip terbaru setiap hari!"
        ),
        "narrative_structure": [
            {
                "beat_id": 1,
                "section": "hook",
                "description": "Attention-grabbing opening",
                "start_cue": "Halo guys hari ini ada",
                "overlay_text": "KABAR BESAR SELEB",
                "caption_keywords": ["gossip", "seleb"],
            },
            {
                "beat_id": 2,
                "section": "story_1",
                "description": "Anji marriage news",
                "start_cue": "Anji ternyata sudah resmi",
                "overlay_text": "ANJI MENIKAH LAGI",
                "caption_keywords": ["Anji", "nikah"],
            },
            {
                "beat_id": 3,
                "section": "story_1_reveal",
                "description": "Raffi new project rumor",
                "start_cue": "Terus ada juga gossip tentang",
                "overlay_text": "RAFFI PROJECT BARU?",
                "caption_keywords": ["Raffi", "project"],
            },
            {
                "beat_id": 4,
                "section": "closing_cta",
                "description": "Call to action",
                "start_cue": "Jadi tunggu aja kelanjutannya",
                "overlay_text": "FOLLOW UNTUK UPDATE",
                "caption_keywords": ["follow", "update"],
            },
        ],
        "hook_text_onscreen": "KABAR BESAR HARI INI!",
        "caption": "Gosip terbaru artis Indonesia!",
        "hashtags": ["#gossip", "#artis", "#indonesia"],
        "quality_score": 8,
        "quality_notes": "Good flow, natural spoken style",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _parse_script_response tests
# ---------------------------------------------------------------------------


class TestParseScriptResponse:
    def test_parse_valid_voiceover_response(self):
        agent = ScriptwriterAgent()
        raw = json.dumps(_sample_voiceover_response())
        parsed = agent._parse_script_response(raw)
        assert parsed["voiceover_text"] != ""
        assert len(parsed["narrative_structure"]) == 4
        assert parsed["hook_text_onscreen"] == "KABAR BESAR HARI INI!"
        assert parsed["caption"] == "Gosip terbaru artis Indonesia!"
        assert len(parsed["hashtags"]) == 3

    def test_parse_returns_empty_on_invalid_json(self):
        agent = ScriptwriterAgent()
        raw = "not valid json at all"
        parsed = agent._parse_script_response(raw)
        assert parsed["voiceover_text"] == ""
        assert parsed["narrative_structure"] == []
        assert parsed["caption"] == ""

    def test_parse_handles_code_fence_wrapping(self):
        agent = ScriptwriterAgent()
        data = _sample_voiceover_response()
        raw = f"```json\n{json.dumps(data)}\n```"
        parsed = agent._parse_script_response(raw)
        assert parsed["voiceover_text"] == data["voiceover_text"]

    def test_parse_extracts_all_fields(self):
        agent = ScriptwriterAgent()
        raw = json.dumps(
            _sample_voiceover_response(
                quality_score=9,
                quality_notes="Excellent",
            )
        )
        parsed = agent._parse_script_response(raw)
        assert parsed["quality_score"] == 9
        assert parsed["quality_notes"] == "Excellent"


# ---------------------------------------------------------------------------
# Voiceover text validation tests
# ---------------------------------------------------------------------------


class TestVoiceoverTextValidation:
    def test_voiceover_is_single_continuous_string(self):
        """voiceover_text must be a single string, no scene breaks."""
        parsed = _sample_voiceover_response()
        voiceover = parsed["voiceover_text"]
        assert isinstance(voiceover, str)
        assert "\n\n" not in voiceover
        assert "---" not in voiceover
        if "\n" in voiceover:
            assert "Scene" not in voiceover.split("\n")[0]

    def test_voiceover_word_count_in_range(self):
        """voiceover_text must be 75-110 words."""
        text = _sample_voiceover_response()["voiceover_text"]
        wc = _word_count(text)
        assert 75 <= wc <= 110, f"Word count {wc} outside range 75-110"

    def test_voiceover_too_short_fails_validation(self):
        """Short voiceover text should trigger validation error."""
        short_text = "Halo guys ini terlalu pendek."
        errors = _validate_output({"voiceover_text": short_text}, min_words=75, max_words=120)
        assert any("too short" in e for e in errors)

    def test_voiceover_too_long_fails_validation(self):
        """Long voiceover text should trigger validation error."""
        long_text = " ".join(["kata"] * 120)
        errors = _validate_output({"voiceover_text": long_text}, min_words=75, max_words=110)
        assert any("too long" in e for e in errors)

    def test_valid_word_count_passes_validation(self):
        """Voiceover text in range should have no word count errors."""
        text = _sample_voiceover_response()["voiceover_text"]
        errors = _validate_output({"voiceover_text": text}, min_words=75, max_words=120)
        word_errors = [e for e in errors if "too short" in e or "too long" in e]
        assert word_errors == []


# ---------------------------------------------------------------------------
# Emoji detection tests
# ---------------------------------------------------------------------------


class TestEmojiDetection:
    def test_no_emoji_in_clean_text(self):
        assert not _contains_emoji("Halo guys ini teks biasa")

    def test_detects_common_emojis(self):
        assert _contains_emoji("Gosip terbaru! 🔥")
        assert _contains_emoji("Check this out 🎉")
        assert _contains_emoji("Love it ❤️")

    def test_emoji_validation_fails(self):
        """Voiceover text with emoji should trigger validation error."""
        errors = _validate_output({"voiceover_text": "Halo guys! 🔥 ini ada emoji"})
        assert any("emoji" in e for e in errors)

    def test_clean_text_passes_emoji_check(self):
        errors = _validate_output({"voiceover_text": "Halo guys ini tidak ada emoji"})
        emoji_errors = [e for e in errors if "emoji" in e]
        assert emoji_errors == []


# ---------------------------------------------------------------------------
# Narrative structure tests
# ---------------------------------------------------------------------------


class TestNarrativeStructure:
    def test_beat_id_maps_to_story_beats(self):
        """Each narrative_structure beat must have a beat_id."""
        parsed = _sample_voiceover_response()
        for beat in parsed["narrative_structure"]:
            assert "beat_id" in beat
            assert isinstance(beat["beat_id"], int)

    def test_word_range_indices_are_valid(self):
        """FIX-8: word_range is now DERIVED from start_cue during parsing.
        The parsed (post-normalize) structure must carry valid [start, end]
        ranges with start < end, both non-negative."""
        agent = ScriptwriterAgent()
        parsed = agent._parse_script_response(json.dumps(_sample_voiceover_response()))
        for beat in parsed["narrative_structure"]:
            rng = beat["word_range"]
            assert len(rng) == 2
            assert rng[0] >= 0
            assert rng[1] > rng[0]

    def test_normalize_adds_missing_beat_id(self):
        raw = [{"section": "hook", "word_range": [0, 10]}]
        result = _normalize_narrative_structure(raw, None)
        assert result[0]["beat_id"] == 1

    def test_normalize_adds_missing_fields(self):
        raw = [{"beat_id": 1, "section": "hook"}]
        result = _normalize_narrative_structure(raw, None)
        assert result[0]["description"] == ""
        assert result[0]["word_range"] == [0, 0]
        assert result[0]["overlay_text"] == ""
        assert result[0]["caption_keywords"] == []

    def test_normalize_preserves_existing_values(self):
        raw = [
            {
                "beat_id": 5,
                "section": "story_2",
                "description": "Test desc",
                "word_range": [10, 25],
                "overlay_text": "TEST",
                "caption_keywords": ["a", "b"],
            }
        ]
        result = _normalize_narrative_structure(raw, None)
        assert result[0]["beat_id"] == 5
        assert result[0]["description"] == "Test desc"
        assert result[0]["overlay_text"] == "TEST"


# ---------------------------------------------------------------------------
# Output contract tests
# ---------------------------------------------------------------------------


class TestOutputContract:
    def test_output_has_all_required_fields(self):
        """Output dict must contain all required keys."""
        agent = ScriptwriterAgent()
        raw = json.dumps(_sample_voiceover_response())
        parsed = agent._parse_script_response(raw)
        required_keys = [
            "voiceover_text",
            "narrative_structure",
            "hook_text_onscreen",
            "caption",
            "hashtags",
        ]
        for key in required_keys:
            assert key in parsed, f"Missing required key: {key}"

    def test_narrative_structure_is_list(self):
        parsed = _sample_voiceover_response()
        assert isinstance(parsed["narrative_structure"], list)

    def test_hashtags_is_list(self):
        parsed = _sample_voiceover_response()
        assert isinstance(parsed["hashtags"], list)

    def test_empty_output_contract(self):
        empty = _empty_output()
        assert empty["voiceover_text"] == ""
        assert empty["narrative_structure"] == []
        assert empty["caption"] == ""
        assert empty["hashtags"] == []


# ---------------------------------------------------------------------------
# Word count utility tests
# ---------------------------------------------------------------------------


class TestWordCount:
    def test_counts_words_correctly(self):
        assert _word_count("one two three") == 3

    def test_empty_string_is_zero(self):
        assert _word_count("") == 0

    def test_single_word(self):
        assert _word_count("hello") == 1

    def test_extra_whitespace_handled(self):
        assert _word_count("  hello   world  ") == 2


# ---------------------------------------------------------------------------
# Integration-style test: full parse → validate flow
# ---------------------------------------------------------------------------


class TestFullParseValidateFlow:
    def test_valid_response_passes_validation(self):
        agent = ScriptwriterAgent()
        raw = json.dumps(_sample_voiceover_response())
        parsed = agent._parse_script_response(raw)
        errors = _validate_output(parsed, min_words=75, max_words=120)
        # Sample response should be valid
        assert errors == []

    def test_invalid_response_captures_all_errors(self):
        """Short text with emoji should produce multiple validation errors."""
        agent = ScriptwriterAgent()
        data = _sample_voiceover_response(
            voiceover_text="Pendek banget 🔥",
        )
        raw = json.dumps(data)
        parsed = agent._parse_script_response(raw)
        errors = _validate_output(parsed, min_words=75, max_words=120)
        assert len(errors) >= 2  # too short + emoji


def test_validate_output_rejects_standalone_punctuation():
    """FIX-8 codex P1: standalone punctuation tokens (..., em-dash) are forbidden
    in voiceover_text so beat_anchor tokenization (strips attached punct) and the
    Voice Producer timestamp builder (whitespace split) agree on word count and
    word_range indices align 1:1 with timestamps."""
    agent = ScriptwriterAgent()
    data = _sample_voiceover_response(
        voiceover_text="Halo guys ... ternyata Anji menikah — kabar heboh",
    )
    parsed = agent._parse_script_response(json.dumps(data))
    errors = _validate_output(parsed, min_words=3, max_words=9999)
    assert any("standalone punctuation" in e for e in errors), errors


def test_validate_output_accepts_attached_punctuation():
    """Mirror: attached punctuation (comma, period) is fine — split() and
    tokenize() produce the same token COUNT, so indices stay aligned."""
    agent = ScriptwriterAgent()
    data = _sample_voiceover_response(
        voiceover_text="Halo guys, ternyata Anji menikah. Kabar heboh sekali.",
    )
    parsed = agent._parse_script_response(json.dumps(data))
    errors = _validate_output(parsed, min_words=3, max_words=9999)
    assert not any("standalone punctuation" in e for e in errors), errors
