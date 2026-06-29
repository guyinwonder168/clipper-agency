"""Tests for pipeline gate definitions (G1-G10)."""

from pathlib import Path

from clipper_agency.core.narrative_coverage import (
    validate_narrative_coverage,
)
from clipper_agency.orchestrator.gates import (
    GateAssetValidation,
    GateAudioValidation,
    GateCostEstimate,
    GateCreativeMemory,
    GateInputPreflight,
    GateNarrativeCoverage,
    GatePostResearchRisk,
    GateResearchCache,
    GateResult,
    GateScriptValidation,
    GateSourceQuality,
    GateVideoValidation,
)


def test_gate_result_model():
    r = GateResult(passed=True, severity="pass", message="OK")
    assert r.passed
    assert r.severity == "pass"
    assert r.message == "OK"
    assert r.data == {}


def test_gate_result_with_data():
    r = GateResult(True, "pass", "done", data={"key": "val"})
    assert r.data["key"] == "val"


# ── G1: Input Preflight ──────────────────────────────────────────


def test_g1_input_preflight_valid():
    gate = GateInputPreflight()
    result = gate.evaluate(topic="Ariana Grande konser Jakarta", niche_config={"name": "test"})
    assert result.passed
    assert result.severity == "pass"


def test_g1_input_preflight_empty():
    gate = GateInputPreflight()
    result = gate.evaluate(topic="", niche_config={"name": "test"})
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g1_input_preflight_whitespace():
    gate = GateInputPreflight()
    result = gate.evaluate(topic="   ", niche_config={"name": "test"})
    assert not result.passed


def test_g1_input_preflight_missing_niche():
    gate = GateInputPreflight()
    result = gate.evaluate(topic="hello")
    assert not result.passed


# ── G2: Cost Estimate ────────────────────────────────────────────


def test_g2_cost_estimate_pass():
    gate = GateCostEstimate()
    result = gate.evaluate(cached=True, niche_config={"name": "test"})
    assert result.passed
    assert result.data["estimate_cents"] > 0


def test_g2_cost_estimate_no_cache():
    gate = GateCostEstimate()
    result = gate.evaluate(cached=False)
    assert result.passed
    assert result.data["estimate_cents"] == 3.3


# ── G3: Research Cache ───────────────────────────────────────────


def test_g3_fresh_cache():
    gate = GateResearchCache()
    result = gate.evaluate(cache_entry={"freshness": "fresh"})
    assert result.passed
    assert result.severity == "pass"


def test_g3_stale_cache():
    gate = GateResearchCache()
    result = gate.evaluate(cache_entry={"freshness": "stale"})
    assert result.passed
    assert result.severity == "soft_fail"


def test_g3_no_cache():
    gate = GateResearchCache()
    result = gate.evaluate()
    assert not result.passed
    assert result.severity == "hard_fail"


# ── G4: Post-Research Risk ───────────────────────────────────────


def test_g4_no_risks():
    gate = GatePostResearchRisk()
    result = gate.evaluate(risk_flags=[])
    assert result.passed
    assert result.severity == "pass"


def test_g4_danger_keyword():
    gate = GatePostResearchRisk()
    result = gate.evaluate(risk_flags=["ilegal"])
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g4_unverified_claim():
    gate = GatePostResearchRisk()
    result = gate.evaluate(risk_flags=["unverified_claim"])
    assert result.passed
    assert result.severity == "soft_fail"


def test_g4_dict_risk_flags_danger_keyword():
    """G4 must handle list[dict] risk_flags from new SP prompt contract.

    Regression: PR #58 changed SP to emit risk_flags as list[dict]
    ({category, description}). Old gate assumed list[str] → TypeError.
    """
    gate = GatePostResearchRisk()
    result = gate.evaluate(
        risk_flags=[
            {"category": "legal", "description": "Potential defamation issue"},
        ]
    )
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g4_dict_risk_flags_unverified():
    """G4 must detect 'unverified' in dict risk_flags descriptions."""
    gate = GatePostResearchRisk()
    result = gate.evaluate(
        risk_flags=[
            {"category": "factual", "description": "Claim is unverified"},
        ]
    )
    assert result.passed
    assert result.severity == "soft_fail"


def test_g4_dict_risk_flags_clean():
    """G4 passes when dict risk_flags contain no danger keywords."""
    gate = GatePostResearchRisk()
    result = gate.evaluate(
        risk_flags=[
            {"category": "sensitivity", "description": "Minor emotional topic"},
        ]
    )
    assert result.passed
    assert result.severity == "pass"


def test_g4_mixed_str_and_dict_risk_flags():
    """G4 handles mixed list[str] + list[dict] (backward compat)."""
    gate = GatePostResearchRisk()
    result = gate.evaluate(
        risk_flags=[
            "existing string flag",
            {"category": "legal", "description": "defamation risk"},
        ]
    )
    assert not result.passed
    assert result.severity == "hard_fail"


# ── G5: Source Quality ───────────────────────────────────────────


def test_g5_two_sources():
    gate = GateSourceQuality()
    result = gate.evaluate(video_sources=["a.mp4", "b.mp4"])
    assert result.passed
    assert result.severity == "pass"


def test_g5_one_source():
    gate = GateSourceQuality()
    result = gate.evaluate(video_sources=["a.mp4"])
    assert result.passed
    assert result.severity == "soft_fail"


def test_g5_no_sources():
    gate = GateSourceQuality()
    result = gate.evaluate()
    assert not result.passed
    assert result.severity == "hard_fail"


# ── G6: Creative Memory ──────────────────────────────────────────


def test_g6_variation_available():
    gate = GateCreativeMemory()
    result = gate.evaluate(used_angles=["a"], available_angles=["a", "b", "c"])
    assert result.passed
    assert result.severity == "pass"


def test_g6_one_angle_left():
    gate = GateCreativeMemory()
    result = gate.evaluate(used_angles=["a", "b"], available_angles=["a", "b", "c"])
    assert result.passed
    assert result.severity == "soft_fail"


def test_g6_all_angles_exhausted():
    gate = GateCreativeMemory()
    result = gate.evaluate(used_angles=["a", "b", "c"], available_angles=["a", "b", "c"])
    assert not result.passed
    assert result.severity == "hard_fail"


# ── G7: Script Validation ────────────────────────────────────────


def test_g7_valid_script():
    gate = GateScriptValidation()
    result = gate.evaluate(script="Hello world.", caption="Short caption")
    assert result.passed
    assert result.severity == "pass"


def test_g7_empty_script():
    gate = GateScriptValidation()
    result = gate.evaluate(script="", caption="Some caption")
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g7_empty_caption():
    gate = GateScriptValidation()
    result = gate.evaluate(script="Hello world.", caption="")
    assert not result.passed
    assert result.severity == "soft_fail"


def test_g7_long_caption():
    gate = GateScriptValidation()
    result = gate.evaluate(script="Hello.", caption="x" * 200)
    assert result.passed
    assert result.severity == "soft_fail"


# ── G8: Audio Validation ─────────────────────────────────────────


def test_g8_missing_audio():
    gate = GateAudioValidation()
    result = gate.evaluate(audio_path="/nonexistent/audio.mp3")
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g8_empty_audio_file(tmp_path):
    path = tmp_path / "empty.mp3"
    path.write_text("")
    gate = GateAudioValidation()
    result = gate.evaluate(audio_path=str(path))
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g8_valid_audio(tmp_path):
    path = tmp_path / "audio.mp3"
    path.write_text("fake-audio-data")
    gate = GateAudioValidation()
    result = gate.evaluate(audio_path=str(path))
    assert result.passed
    assert result.severity == "pass"


# ── G9: Asset Validation ─────────────────────────────────────────


def test_g9_no_assets():
    gate = GateAssetValidation()
    result = gate.evaluate()
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g9_all_assets_valid(tmp_path):
    a = tmp_path / "a.png"
    a.write_text("img")
    b = tmp_path / "b.jpg"
    b.write_text("img")
    gate = GateAssetValidation()
    result = gate.evaluate(asset_paths=[str(a), str(b)])
    assert result.passed
    assert result.severity == "pass"


def test_g9_mixed_assets(tmp_path):
    a = tmp_path / "good.png"
    a.write_text("img")
    bad = tmp_path / "missing.png"  # never created
    gate = GateAssetValidation()
    result = gate.evaluate(asset_paths=[str(a), str(bad)])
    assert result.passed
    assert result.severity == "soft_fail"


def test_g9_no_valid_assets(tmp_path):
    bad1 = tmp_path / "missing1.png"
    bad2 = tmp_path / "missing2.png"
    gate = GateAssetValidation()
    result = gate.evaluate(asset_paths=[str(bad1), str(bad2)])
    assert not result.passed
    assert result.severity == "hard_fail"


# ── G10: Video Validation ────────────────────────────────────────


class TestGateVideoValidation:
    """Deterministic G10 output validation using ffprobe metadata."""

    def test_g10_rejects_missing_file(self, mocker):
        """G10 gate rejects when probe returns None (file missing/corrupt)."""
        mocker.patch.object(Path, "exists", return_value=True)
        mocker.patch(
            "clipper_agency.orchestrator.gates.probe_video",
            return_value=None,
        )
        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/missing.mp4")
        assert not result.passed
        assert "not found" in result.message.lower() or "unreadable" in result.message.lower()

    def test_g10_rejects_wrong_resolution(self, mocker):
        """G10 gate rejects video that is not 1080x1920."""
        mocker.patch.object(Path, "exists", return_value=True)
        mock_info = mocker.Mock(
            width=1920,
            height=1080,
            codec="h264",
            duration=30.0,
            has_audio=True,
            file_size=50000,
        )
        mocker.patch(
            "clipper_agency.orchestrator.gates.probe_video",
            return_value=mock_info,
        )

        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "resolution" in result.message.lower()

    def test_g10_rejects_wrong_duration_short(self, mocker):
        """G10 gate rejects video under 20s."""
        mocker.patch.object(Path, "exists", return_value=True)
        mock_info = mocker.Mock(
            width=1080,
            height=1920,
            codec="h264",
            duration=10.0,
            has_audio=True,
            file_size=50000,
        )
        mocker.patch(
            "clipper_agency.orchestrator.gates.probe_video",
            return_value=mock_info,
        )

        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "short" in result.message.lower() or "duration" in result.message.lower()

    def test_g10_rejects_wrong_duration_long(self, mocker):
        """G10 gate rejects video over 60s."""
        mocker.patch.object(Path, "exists", return_value=True)
        mock_info = mocker.Mock(
            width=1080,
            height=1920,
            codec="h264",
            duration=90.0,
            has_audio=True,
            file_size=50000,
        )
        mocker.patch(
            "clipper_agency.orchestrator.gates.probe_video",
            return_value=mock_info,
        )

        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "long" in result.message.lower() or "duration" in result.message.lower()

    def test_g10_rejects_no_audio(self, mocker):
        """G10 gate rejects video without audio track."""
        mocker.patch.object(Path, "exists", return_value=True)
        mock_info = mocker.Mock(
            width=1080,
            height=1920,
            codec="h264",
            duration=30.0,
            has_audio=False,
            file_size=50000,
        )
        mocker.patch(
            "clipper_agency.orchestrator.gates.probe_video",
            return_value=mock_info,
        )

        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "audio" in result.message.lower()

    def test_g10_rejects_wrong_codec(self, mocker):
        """G10 gate rejects non-h264 video."""
        mocker.patch.object(Path, "exists", return_value=True)
        mock_info = mocker.Mock(
            width=1080,
            height=1920,
            codec="vp9",
            duration=30.0,
            has_audio=True,
            file_size=50000,
        )
        mocker.patch(
            "clipper_agency.orchestrator.gates.probe_video",
            return_value=mock_info,
        )

        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert not result.passed
        assert "codec" in result.message.lower()

    def test_g10_accepts_valid_video(self, mocker):
        """G10 gate passes valid 1080x1920 h264 video with audio."""
        mocker.patch.object(Path, "exists", return_value=True)
        mock_info = mocker.Mock(
            width=1080,
            height=1920,
            codec="h264",
            duration=30.0,
            has_audio=True,
            file_size=50000,
        )
        mocker.patch(
            "clipper_agency.orchestrator.gates.probe_video",
            return_value=mock_info,
        )

        gate = GateVideoValidation()
        result = gate.evaluate(video_path="/tmp/vid.mp4")
        assert result.passed


def test_g10_missing_video():
    gate = GateVideoValidation()
    result = gate.evaluate(video_path="/nonexistent/video.mp4")
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g10_too_small_video(tmp_path):
    path = tmp_path / "tiny.mp4"
    path.write_bytes(b"X" * 512)
    gate = GateVideoValidation()
    result = gate.evaluate(video_path=str(path))
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g10_valid_video(tmp_path, mocker):
    """G10 gate passes valid video with mocked probe metadata."""
    path = tmp_path / "video.mp4"
    path.write_bytes(b"X" * 2048)
    mock_info = mocker.Mock(
        width=1080,
        height=1920,
        codec="h264",
        duration=30.0,
        has_audio=True,
        file_size=50000,
    )
    mocker.patch(
        "clipper_agency.orchestrator.gates.probe_video",
        return_value=mock_info,
    )
    gate = GateVideoValidation()
    result = gate.evaluate(video_path=str(path))
    assert result.passed
    assert result.severity == "pass"


# ── G7 (active): Narrative coverage contract (ADR 0030 / FIX-1) ──


def test_g7_narrative_coverage_pass_on_ok_result():
    coverage = validate_narrative_coverage(
        [{"word_range": [0, 9]}, {"word_range": [10, 19]}], word_count=20
    )
    result = GateNarrativeCoverage().evaluate(coverage=coverage)
    assert result.passed
    assert result.severity == "pass"
    assert result.data["reason"] == "covered"


def test_g7_narrative_coverage_hard_fail_on_job18_fixture():
    job18 = [
        {"beat_id": 1, "word_range": [0, 2]},
        {"beat_id": 2, "word_range": [3, 8]},
        {"beat_id": 3, "word_range": [9, 12]},
        {"beat_id": 4, "word_range": [13, 15]},
        {"beat_id": 5, "word_range": [16, 19]},
        {"beat_id": 6, "word_range": [20, 23]},
    ]
    coverage = validate_narrative_coverage(job18, word_count=76)
    result = GateNarrativeCoverage().evaluate(coverage=coverage)
    assert not result.passed
    assert result.severity == "hard_fail"
    assert result.data["reason"] == "narrative_not_covered"


def test_g7_narrative_coverage_pass_after_tail_repair():
    coverage = validate_narrative_coverage(
        [{"word_range": [0, 49]}, {"word_range": [50, 97]}], word_count=100
    )
    assert coverage.repaired_structure is not None
    result = GateNarrativeCoverage().evaluate(coverage=coverage)
    assert result.passed
    assert result.severity == "pass"
    assert result.data["reason"] == "covered_after_tail_repair"


def test_g7_narrative_coverage_none_coverage_hard_fails():
    """A missing coverage result is a wiring error, not a safe default.

    Silently passing would re-open the job_18 hole this gate exists to close.
    Operators bypass via DEV_RELAX_GATES=G7_NARRATIVE_COVERAGE.
    """
    result = GateNarrativeCoverage().evaluate(coverage=None)
    assert not result.passed
    assert result.severity == "hard_fail"
    assert result.data["reason"] == "narrative_not_covered"
    assert result.data["violation_type"] == "not_evaluated"
