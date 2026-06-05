"""Tests for audio_sequencer — build_audio_video_concat pure function."""

from clipper_agency.rendering.audio_sequencer import build_audio_video_concat


# ---------------------------------------------------------------------------
# Mode A: audio+video paired concat
# ---------------------------------------------------------------------------


def test_pairs_audio_to_video_mode_a():
    """3 scenes + 3 audio files, no xfade → concat=n=3:v=1:a=1."""
    # Arrange
    labels = ["t0", "t1", "t2"]

    # Act
    result = build_audio_video_concat(labels, num_video_inputs=3, audio_file_count=3)

    # Assert
    filter_str, outv, outa = result
    assert "[t0][3:a][t1][4:a][t2][5:a]concat=n=3:v=1:a=1[outv][outa]" == filter_str
    assert outv == "outv"
    assert outa == "outa"


# ---------------------------------------------------------------------------
# Mode B: audio-only concat (xfade handles video)
# ---------------------------------------------------------------------------


def test_audio_only_concat_mode_b():
    """3 scenes + 3 audio files, xfade=True → concat=n=3:a=1 only."""
    # Arrange
    labels = ["t0", "t1", "t2"]

    # Act
    result = build_audio_video_concat(
        labels, num_video_inputs=3, audio_file_count=3, has_xfade=True
    )

    # Assert
    filter_str, outv, outa = result
    assert "[3:a][4:a][5:a]concat=n=3:v=0:a=1[outa]" == filter_str
    assert outv == ""
    assert outa == "outa"


# ---------------------------------------------------------------------------
# No audio fallback
# ---------------------------------------------------------------------------


def test_no_audio_returns_anullsrc():
    """Zero audio files → returns anullsrc fallback."""
    # Arrange
    labels = ["t0", "t1"]

    # Act
    result = build_audio_video_concat(labels, num_video_inputs=2, audio_file_count=0)

    # Assert
    filter_str, outv, outa = result
    assert filter_str == "anullsrc"
    assert outv == ""
    assert outa == "outa"


# ---------------------------------------------------------------------------
# Fewer audio files than scenes → silence padding
# ---------------------------------------------------------------------------


def test_fewer_audio_pads_silence():
    """3 scenes + 1 audio file → scenes 2,3 padded with anullsrc."""
    # Arrange
    labels = ["t0", "t1", "t2"]

    # Act
    result = build_audio_video_concat(labels, num_video_inputs=3, audio_file_count=1)

    # Assert
    filter_str, outv, outa = result
    # Scene 0 uses [3:a], scenes 1-2 use padded silence
    assert "anullsrc=r=44100[asilence1];" in filter_str
    assert "anullsrc=r=44100[asilence2];" in filter_str
    assert "[t0][3:a][t1][asilence1][t2][asilence2]" in filter_str
    assert "concat=n=3:v=1:a=1[outv][outa]" in filter_str
    assert outv == "outv"
    assert outa == "outa"


# ---------------------------------------------------------------------------
# More audio files than scenes → truncation
# ---------------------------------------------------------------------------


def test_more_audio_truncates():
    """2 scenes + 5 audio files → only first 2 audio inputs used."""
    # Arrange
    labels = ["t0", "t1"]

    # Act
    result = build_audio_video_concat(labels, num_video_inputs=2, audio_file_count=5)

    # Assert
    filter_str, outv, outa = result
    assert "[t0][2:a][t1][3:a]concat=n=2:v=1:a=1[outv][outa]" == filter_str
    assert outv == "outv"
    assert outa == "outa"


# ---------------------------------------------------------------------------
# Single scene
# ---------------------------------------------------------------------------


def test_single_scene_mode_a():
    """1 scene + 1 audio → concat=n=1:v=1:a=1."""
    # Arrange
    labels = ["t0"]

    # Act
    result = build_audio_video_concat(labels, num_video_inputs=1, audio_file_count=1)

    # Assert
    filter_str, outv, outa = result
    assert "[t0][1:a]concat=n=1:v=1:a=1[outv][outa]" == filter_str
    assert outv == "outv"
    assert outa == "outa"


# ---------------------------------------------------------------------------
# Output labels correctness
# ---------------------------------------------------------------------------


def test_output_labels_correct():
    """Mode A returns ('outv', 'outa'), Mode B returns ('', 'outa')."""
    # Arrange
    labels = ["t0", "t1"]

    # Act
    mode_a = build_audio_video_concat(labels, num_video_inputs=2, audio_file_count=2)
    mode_b = build_audio_video_concat(
        labels, num_video_inputs=2, audio_file_count=2, has_xfade=True
    )

    # Assert — Mode A
    assert mode_a[1] == "outv"
    assert mode_a[2] == "outa"

    # Assert — Mode B
    assert mode_b[1] == ""
    assert mode_b[2] == "outa"


# ---------------------------------------------------------------------------
# Pure function: deterministic output
# ---------------------------------------------------------------------------


def test_is_pure_function():
    """Same inputs always produce same output (idempotency)."""
    # Arrange
    labels = ["t0", "t1", "t2"]

    # Act
    result1 = build_audio_video_concat(labels, num_video_inputs=3, audio_file_count=3)
    result2 = build_audio_video_concat(labels, num_video_inputs=3, audio_file_count=3)

    # Assert
    assert result1 == result2
