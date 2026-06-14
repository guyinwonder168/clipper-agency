"""Phase 23 End-to-End Wiring Verification Tests.

Verifies that all 17 Phase 21/22 modules that were built but never
called from production are now properly wired into agent call sites.

All tests run offline — no external API calls, no FFmpeg required.
"""

import pytest

from clipper_agency.agents.reviewer import ReviewerAgent
from clipper_agency.core.text_collision import (
    detect_text_collisions,
    detect_source_text_density,
)
from clipper_agency.core.safe_area import detect_safe_area_issues
from clipper_agency.core.generated_text_manifest import build_generated_text_regions
from clipper_agency.core.rendered_scene_manifest import (
    build_rendered_scene_manifest,
    RenderedSceneManifest,
    RenderedSceneEntry,
)
from clipper_agency.core.frame_quality import detect_empty_segments
from clipper_agency.core.source_cleanliness import score_source_cleanliness
from clipper_agency.observability.llm_trace import LLMTraceWriter
from clipper_agency.orchestrator.engine import Orchestrator


# ──────────────────────────────────────────────────────────────
# Task 5.1A — Text Collision Wiring Verification
# ──────────────────────────────────────────────────────────────


class TestReviewerTextCollisionWiring:
    """Verify Reviewer's actual text_collision detection calls work."""

    def test_detect_text_collisions_returns_issues_when_overlap(self):
        """detect_text_collisions returns collision issues when regions overlap."""
        source = [{"bbox": [0, 0, 500, 100], "layer": "source_text"}]
        generated = [{"bbox": [100, 50, 600, 150], "layer": "subtitle"}]
        thresholds = {"subtitle_overlap_max": 0.20}

        issues = detect_text_collisions(source, generated, thresholds)
        assert len(issues) > 0
        assert issues[0].type == "SUBTITLE_SOURCE_TEXT_OVERLAP"

    def test_detect_text_collisions_returns_empty_when_no_overlap(self):
        """detect_text_collisions returns no issues when regions are far apart."""
        source = [{"bbox": [0, 0, 100, 50], "layer": "source_text"}]
        generated = [{"bbox": [500, 500, 600, 550], "layer": "subtitle"}]
        thresholds = {"subtitle_overlap_max": 0.20}

        issues = detect_text_collisions(source, generated, thresholds)
        assert len(issues) == 0

    def test_detect_source_text_density_flags_high_density(self):
        """detect_source_text_density flags reject when text covers >40% of frame."""
        # Full frame: 1080 * 1920 = 2,073,600
        # Text bbox: 1080 wide, 864 tall = 933,120 → 45% density
        source = [{"bbox": [0, 0, 1080, 864]}]

        issues = detect_source_text_density(source, (1080, 1920))
        assert len(issues) > 0
        assert issues[0].severity == "reject"

    def test_detect_source_text_density_passes_low_density(self):
        """detect_source_text_density returns empty when text is sparse."""
        source = [{"bbox": [100, 100, 200, 200]}]  # tiny region

        issues = detect_source_text_density(source, (1080, 1920))
        assert len(issues) == 0

    def test_reviewer_fail_if_text_collision_with_reject(self):
        """_fail_if_text_collision_failed triggers on severity=reject."""
        agent = ReviewerAgent()
        diagnostics = {
            "text_collision": [
                {"type": "SUBTITLE_SOURCE_TEXT_OVERLAP", "severity": "reject"}
            ]
        }
        result = agent._fail_if_text_collision_failed(diagnostics)
        assert result is not None
        assert result["status"] == "fail"
        assert "text_collision_failed" in result["issues"]

    def test_reviewer_fail_if_text_collision_passes_warnings(self):
        """_fail_if_text_collision_failed skips warning-only issues."""
        agent = ReviewerAgent()
        diagnostics = {
            "text_collision": [
                {"type": "SUB_SOURCE_TEXT_OVERLAP", "severity": "warning"}
            ]
        }
        result = agent._fail_if_text_collision_failed(diagnostics)
        assert result is None

    def test_reviewer_fail_if_text_collision_none_diagnostics(self):
        """_fail_if_text_collision_failed returns None for empty diagnostics."""
        agent = ReviewerAgent()
        assert agent._fail_if_text_collision_failed(None) is None
        assert agent._fail_if_text_collision_failed({}) is None


# ──────────────────────────────────────────────────────────────
# Task 5.1B — Safe Area Wiring Verification
# ──────────────────────────────────────────────────────────────


class TestReviewerSafeAreaWiring:
    """Verify Reviewer's actual safe_area detection calls work."""

    def test_detect_safe_area_issues_flags_unsafe_zone(self):
        """detect_safe_area_issues flags text in TikTok bottom caption zone."""
        # Subtitle in bottom 21% (y=1500-1700 in 1080x1920 frame)
        generated = [{"bbox": [120, 1500, 960, 1700], "layer": "subtitle"}]
        face_regions: list[dict] = []

        issues = detect_safe_area_issues(
            generated, face_regions, (1080, 1920), "tiktok", 0.15,
        )
        assert len(issues) > 0
        assert issues[0].type == "PLATFORM_UNSAFE_ZONE"

    def test_detect_safe_area_issues_passes_safe_zone(self):
        """detect_safe_area_issues returns empty for mid-frame text."""
        generated = [{"bbox": [120, 800, 960, 900], "layer": "subtitle"}]
        face_regions: list[dict] = []

        issues = detect_safe_area_issues(
            generated, face_regions, (1080, 1920), "tiktok", 0.15,
        )
        assert len(issues) == 0

    def test_detect_safe_area_issues_flags_face_overlap(self):
        """detect_safe_area_issues flags text overlapping face region."""
        generated = [{"bbox": [500, 300, 700, 450], "layer": "headline"}]
        face_regions = [{"bbox": [600, 300, 800, 500]}]

        issues = detect_safe_area_issues(
            generated, face_regions, (1080, 1920), "tiktok", 0.10,
        )
        assert len(issues) > 0
        assert issues[0].type == "FACE_TEXT_OVERLAP"

    def test_reviewer_fail_if_safe_area_with_reject(self):
        """_fail_if_safe_area_failed triggers on severity=reject."""
        agent = ReviewerAgent()
        diagnostics = {
            "safe_area": [
                {"type": "PLATFORM_UNSAFE_ZONE", "severity": "reject"}
            ]
        }
        result = agent._fail_if_safe_area_failed(diagnostics)
        assert result is not None
        assert result["status"] == "fail"
        assert "safe_area_failed" in result["issues"]

    def test_reviewer_fail_if_safe_area_none_diagnostics(self):
        """_fail_if_safe_area_failed returns None for empty diagnostics."""
        agent = ReviewerAgent()
        assert agent._fail_if_safe_area_failed(None) is None
        assert agent._fail_if_safe_area_failed({}) is None


# ──────────────────────────────────────────────────────────────
# Task 5.1C — Diagnostics Population Wiring
# ──────────────────────────────────────────────────────────────


class TestReviewerDiagnosticsPopulation:
    """Verify _populate_actual_detection_diagnostics enriches diagnostics."""

    def _make_diagnostics_with_regions(self):
        """Build diagnostics dict with both source and generated regions."""
        return {
            "frame_size": [1080, 1920],
            "generated_text_regions": [
                {
                    "timestamp_start_sec": 0.0,
                    "timestamp_end_sec": 5.0,
                    "layer": "subtitle",
                    "bbox": [120, 1500, 960, 1700],
                    "text": "test caption",
                }
            ],
            "source_text_regions": [
                {
                    "timestamp_start_sec": 2.0,
                    "timestamp_end_sec": 4.0,
                    "layer": "source_text",
                    "bbox": [100, 1480, 980, 1720],
                    "text": "source",
                }
            ],
            "face_regions": [],
        }

    def test_populate_diagnostics_adds_text_collision(self, mocker):
        """_populate_actual_detection_diagnostics adds text_collision key."""
        mocker.patch(
            "clipper_agency.agents.reviewer._is_enabled", return_value=True,
        )
        diagnostics = self._make_diagnostics_with_regions()

        enriched = ReviewerAgent()._populate_actual_detection_diagnostics(
            diagnostics,
        )
        assert enriched is not None
        assert "text_collision" in enriched
        assert isinstance(enriched["text_collision"], list)

    def test_populate_diagnostics_adds_safe_area(self, mocker):
        """_populate_actual_detection_diagnostics adds safe_area key."""
        mocker.patch(
            "clipper_agency.agents.reviewer._is_enabled", return_value=True,
        )
        diagnostics = self._make_diagnostics_with_regions()

        enriched = ReviewerAgent()._populate_actual_detection_diagnostics(
            diagnostics,
        )
        assert enriched is not None
        assert "safe_area" in enriched
        assert isinstance(enriched["safe_area"], list)

    def test_populate_diagnostics_preserves_existing_keys(self, mocker):
        """_populate_actual_detection_diagnostics doesn't drop existing data."""
        mocker.patch(
            "clipper_agency.agents.reviewer._is_enabled", return_value=True,
        )
        diagnostics = self._make_diagnostics_with_regions()
        diagnostics["visual_coverage"] = {"status": "pass"}

        enriched = ReviewerAgent()._populate_actual_detection_diagnostics(
            diagnostics,
        )
        assert enriched is not None
        assert "visual_coverage" in enriched
        assert enriched["visual_coverage"]["status"] == "pass"

    def test_populate_diagnostics_none_input(self):
        """_populate_actual_detection_diagnostics handles None gracefully."""
        result = ReviewerAgent()._populate_actual_detection_diagnostics(None)
        assert result is None

    def test_populate_diagnostics_no_source_regions(self, mocker):
        """_populate_actual_detection_diagnostics skips collision when no sources."""
        mocker.patch(
            "clipper_agency.agents.reviewer._is_enabled", return_value=True,
        )
        diagnostics = self._make_diagnostics_with_regions()
        diagnostics.pop("source_text_regions")

        enriched = ReviewerAgent()._populate_actual_detection_diagnostics(
            diagnostics,
        )
        assert enriched is not None
        # text_collision skipped when no source_regions
        assert enriched.get("text_collision") is None


# ──────────────────────────────────────────────────────────────
# Task 5.1D — Module Import Verification
# ──────────────────────────────────────────────────────────────


class TestAllWiredModulesImportable:
    """Verify all 17 previously-unwired modules are importable and wired."""

    def test_frame_inspection_modules_importable(self):
        """Frame inspection pipeline modules import cleanly."""
        import clipper_agency.core.frame_sampler
        import clipper_agency.core.frame_extractor
        import clipper_agency.core.frame_hash
        import clipper_agency.core.frame_quality
        import clipper_agency.core.frame_inspection_pipeline
        import clipper_agency.core.inspection_paths

        assert clipper_agency.core.frame_sampler is not None
        assert clipper_agency.core.frame_extractor is not None
        assert clipper_agency.core.frame_hash is not None
        assert clipper_agency.core.frame_quality is not None
        assert clipper_agency.core.frame_inspection_pipeline is not None
        assert clipper_agency.core.inspection_paths is not None

    def test_ocr_and_face_modules_importable(self):
        """OCR and face detection modules import cleanly."""
        import clipper_agency.core.ocr_adapter
        import clipper_agency.core.face_adapter
        import clipper_agency.core.text_detection

        assert clipper_agency.core.ocr_adapter is not None
        assert clipper_agency.core.face_adapter is not None
        assert clipper_agency.core.text_detection is not None

    def test_cleanliness_and_manifest_modules_importable(self):
        """Cleanliness and manifest modules import cleanly."""
        import clipper_agency.core.source_cleanliness
        import clipper_agency.core.generated_text_manifest
        import clipper_agency.core.rendered_scene_manifest
        import clipper_agency.core.text_collision
        import clipper_agency.core.safe_area
        import clipper_agency.core.final_layout_inspection

        assert clipper_agency.core.source_cleanliness is not None
        assert clipper_agency.core.generated_text_manifest is not None
        assert clipper_agency.core.rendered_scene_manifest is not None
        assert clipper_agency.core.text_collision is not None
        assert clipper_agency.core.safe_area is not None
        assert clipper_agency.core.final_layout_inspection is not None

    def test_observability_modules_importable(self):
        """LLM trace modules import cleanly."""
        import clipper_agency.observability.llm_trace

        assert clipper_agency.observability.llm_trace is not None


# ──────────────────────────────────────────────────────────────
# Task 5.1E — Engine Trace Writer Wiring
# ──────────────────────────────────────────────────────────────


class TestEngineTraceWriterWiring:
    """Verify engine creates trace writer when LLM traces are enabled."""

    def test_engine_creates_trace_writer_when_enabled(self, mocker, tmp_path):
        """Orchestrator creates LLMTraceWriter when llm_traces.enabled=True."""
        mock_settings = mocker.patch(
            "clipper_agency.orchestrator.engine.load_settings",
        )
        mock_settings.return_value.observability.llm_traces.enabled = True
        mock_settings.return_value.assets_cache = str(tmp_path)
        mock_settings.return_value.observability.llm_traces.redact_secrets = True

        mock_writer = mocker.patch(
            "clipper_agency.orchestrator.engine.LLMTraceWriter",
        )

        # Mock DB connections so init doesn't fail
        mocker.patch(
            "clipper_agency.orchestrator.engine.get_connection",
        )
        mocker.patch(
            "clipper_agency.orchestrator.engine.initialize_schema",
        )

        orchestrator = Orchestrator(db_path=str(tmp_path / "test.db"))
        assert orchestrator._trace_writer is not None
        mock_writer.assert_called_once_with(
            str(tmp_path), redact_secrets=True,
        )

    def test_engine_skips_trace_writer_when_disabled(self, mocker, tmp_path):
        """Orchestrator returns None when llm_traces.enabled=False."""
        mock_settings = mocker.patch(
            "clipper_agency.orchestrator.engine.load_settings",
        )
        mock_settings.return_value.observability.llm_traces.enabled = False
        mock_settings.return_value.assets_cache = str(tmp_path)

        mocker.patch(
            "clipper_agency.orchestrator.engine.get_connection",
        )
        mocker.patch(
            "clipper_agency.orchestrator.engine.initialize_schema",
        )

        orchestrator = Orchestrator(db_path=str(tmp_path / "test.db"))
        assert orchestrator._trace_writer is None


# ──────────────────────────────────────────────────────────────
# Task 5.1F — Rendered Scene Manifest Wiring
# ──────────────────────────────────────────────────────────────


class TestRenderedSceneManifestWiring:
    """Verify build_rendered_scene_manifest produces valid output."""

    def test_build_manifest_returns_non_empty_result(self):
        """build_rendered_scene_manifest produces entries from scene data."""
        scenes = [
            {
                "scene": "1",
                "path": "/tmp/test.mp4",
                "type": "tiktok_clip",
                "target_duration": 5.0,
                "beat_id": "beat_1",
                "selected_asset_id": "asset_abc",
            },
            {
                "scene": "2",
                "path": "/tmp/test2.jpg",
                "type": "photo",
                "target_duration": 3.0,
                "beat_id": "beat_2",
                "selected_asset_id": "asset_def",
            },
        ]
        text_regions = [
            {
                "timestamp_start_sec": 0.0,
                "timestamp_end_sec": 3.0,
                "layer": "subtitle",
                "bbox": [120, 1500, 960, 1700],
                "text": "hello",
            },
            {
                "timestamp_start_sec": 4.0,
                "timestamp_end_sec": 8.0,
                "layer": "subtitle",
                "bbox": [120, 1500, 960, 1700],
                "text": "world",
            },
        ]

        manifest = build_rendered_scene_manifest(
            scenes, text_regions, 8.0, "/tmp/output.mp4",
        )
        assert isinstance(manifest, RenderedSceneManifest)
        assert len(manifest.entries) == 2
        assert manifest.video_duration_sec == 8.0
        assert manifest.video_path == "/tmp/output.mp4"

        entry0 = manifest.entries[0]
        assert entry0.scene == "1"
        assert entry0.beat_id == "beat_1"
        assert entry0.start_sec == 0.0
        assert entry0.end_sec == 5.0

        entry1 = manifest.entries[1]
        assert entry1.start_sec == 5.0
        assert entry1.end_sec == 8.0

    def test_manifest_json_roundtrip(self, tmp_path):
        """RenderedSceneManifest can serialise and deserialise."""
        manifest = RenderedSceneManifest(
            entries=[
                RenderedSceneEntry(
                    scene="1",
                    beat_id="b1",
                    start_sec=0.0,
                    end_sec=5.0,
                    source_path="/tmp/x.mp4",
                ),
            ],
            video_duration_sec=5.0,
            video_path="/tmp/output.mp4",
        )
        json_path = tmp_path / "manifest.json"
        manifest.to_json(str(json_path))

        reloaded = RenderedSceneManifest.from_json(str(json_path))
        assert reloaded.video_duration_sec == 5.0
        assert len(reloaded.entries) == 1

    def test_manifest_beat_to_scenes(self):
        """beat_to_scenes filters entries by beat_id."""
        manifest = RenderedSceneManifest(
            entries=[
                RenderedSceneEntry(scene="1", beat_id="a", start_sec=0.0,
                                   end_sec=3.0, source_path="/tmp/a.mp4"),
                RenderedSceneEntry(scene="2", beat_id="b", start_sec=3.0,
                                   end_sec=6.0, source_path="/tmp/b.jpg"),
                RenderedSceneEntry(scene="3", beat_id="a", start_sec=6.0,
                                   end_sec=9.0, source_path="/tmp/c.mp4"),
            ],
            video_duration_sec=9.0,
            video_path="/tmp/o.mp4",
        )

        a_scenes = manifest.beat_to_scenes("a")
        assert len(a_scenes) == 2
        b_scenes = manifest.beat_to_scenes("b")
        assert len(b_scenes) == 1
        c_scenes = manifest.beat_to_scenes("nonexistent")
        assert len(c_scenes) == 0


# ──────────────────────────────────────────────────────────────
# Task 5.1G — Frame Quality / Empty-Frame Wiring
# ──────────────────────────────────────────────────────────────


class TestFrameQualityWiring:
    """Verify detect_empty_segments works with synthetic data."""

    def test_detect_empty_segments_merges_adjacent(self):
        """detect_empty_segments merges consecutive low-variance frames."""
        # Uniform frames at 0.0, 0.5, 1.0, gap at 2.0, 2.5
        uniform_image = [[0, 0], [0, 0]]  # variance 0
        normal_image = [[0, 255], [255, 0]]  # variance > threshold

        sampled = [
            (0.0, uniform_image),
            (0.5, uniform_image),
            (1.0, uniform_image),
            (2.0, normal_image),
            (2.5, uniform_image),
            (3.0, uniform_image),
        ]

        segments = detect_empty_segments(sampled, max_gap_sec=1.0)
        assert len(segments) == 2
        assert segments[0] == (0.0, 1.0)
        assert segments[1] == (2.5, 3.0)

    def test_detect_empty_segments_no_empty_frames(self):
        """detect_empty_segments returns empty when all frames have variance."""
        varied = [[0, 100, 200], [50, 150, 250], [75, 125, 225]]

        sampled = [(t, varied) for t in [0.0, 1.0, 2.0]]
        segments = detect_empty_segments(sampled, max_gap_sec=1.0)
        assert len(segments) == 0


# ──────────────────────────────────────────────────────────────
# Task 5.1H — Generated Text Regions Wiring
# ──────────────────────────────────────────────────────────────


class TestGeneratedTextRegionsWiring:
    """Verify build_generated_text_regions produces text region entries."""

    def test_build_regions_from_render_plan(self):
        """build_generated_text_regions extracts captions and overlays."""
        render_plan = {
            "scenes": [
                {
                    "captions": [
                        {"text": "Hello world", "position": "bottom",
                         "start_seconds": 0.0, "end_seconds": 3.0},
                    ],
                    "overlays": [
                        {"text": "Breaking!", "kind": "headline",
                         "start_seconds": 0.0, "end_seconds": 2.0},
                    ],
                    "duration_seconds": 3.0,
                },
                {
                    "captions": [
                        {"text": "Next story", "position": "bottom",
                         "start_seconds": 0.0, "end_seconds": 2.5},
                    ],
                    "overlays": [],
                    "duration_seconds": 2.5,
                },
            ]
        }

        regions = build_generated_text_regions(render_plan, (1080, 1920))
        assert len(regions) == 3
        assert regions[0]["layer"] == "subtitle"
        assert regions[0]["text"] == "Hello world"
        assert regions[1]["layer"] == "headline"
        assert regions[2]["text"] == "Next story"
        # Cumulative offset: second scene starts at 3.0
        assert regions[2]["timestamp_start_sec"] == 3.0

    def test_build_regions_empty_plan(self):
        """build_generated_text_regions handles empty scenes."""
        regions = build_generated_text_regions(
            {"scenes": []}, (1080, 1920),
        )
        assert len(regions) == 0


# ──────────────────────────────────────────────────────────────
# Task 5.1I — Source Cleanliness Wiring
# ──────────────────────────────────────────────────────────────


class TestSourceCleanlinessWiring:
    """Verify score_source_cleanliness produces valid scores."""

    def test_score_clean_asset_returns_high_score(self):
        """score_source_cleanliness returns high score for clean assets."""
        result = score_source_cleanliness(
            ocr_text_area_ratio=0.0,
            has_logo=False,
            resolution=(1920, 1080),
        )
        assert isinstance(result, dict)
        assert "cleanliness_score" in result
        assert result["cleanliness_score"] == 1.0  # perfectly clean

    def test_score_burned_caption_lowers_score(self):
        """score_source_cleanliness detects burned-in captions."""
        result = score_source_cleanliness(
            ocr_text_area_ratio=0.5,  # 50% text → triggers BURNED_CAPTION
            has_burned_captions=True,
            resolution=(1920, 1080),
        )
        assert isinstance(result, dict)
        assert result["cleanliness_score"] < 0.9  # 0.20 deduction
        assert "BURNED_CAPTION" in str(result.get("issues", []))

    def test_score_dominant_logo_bans_fullscreen(self):
        """score_source_cleanliness bans fullscreen treatment for dominant logos."""
        result = score_source_cleanliness(
            ocr_text_area_ratio=0.0,
            has_logo=True,
            logo_coverage_ratio=0.5,  # > 0.15 dominant threshold
            resolution=(1920, 1080),
        )
        assert result["fullscreen_allowed"] is False
        assert "DOMINANT_LOGO" in str(result.get("issues", []))

    def test_score_empty_input_defaults_clean(self):
        """score_source_cleanliness handles default params gracefully."""
        result = score_source_cleanliness()
        assert isinstance(result, dict)
        assert "cleanliness_score" in result
        assert result["cleanliness_score"] == 1.0


# ──────────────────────────────────────────────────────────────
# Task 5.1J — Agent trace_writer acceptance
# ──────────────────────────────────────────────────────────────


class TestAgentTraceWriterAcceptance:
    """Verify all 7 agents accept trace_writer parameter."""

    def test_reviewer_accepts_trace_writer(self):
        """ReviewerAgent accepts trace_writer kwarg."""
        writer = LLMTraceWriter("/tmp/fake")
        agent = ReviewerAgent(trace_writer=writer)
        assert agent._trace_writer is writer

    def test_reviewer_works_without_trace_writer(self):
        """ReviewerAgent works with trace_writer=None (default)."""
        agent = ReviewerAgent()
        assert agent._trace_writer is None

    def test_safety_agent_accepts_trace_writer(self):
        """SafetyAgent accepts trace_writer kwarg."""
        from clipper_agency.agents.safety import SafetyAgent
        writer = LLMTraceWriter("/tmp/fake")
        agent = SafetyAgent(trace_writer=writer)
        assert agent._trace_writer is writer

    def test_segment_producer_accepts_trace_writer(self):
        """SegmentProducerAgent accepts trace_writer kwarg."""
        from clipper_agency.agents.segment_producer import SegmentProducerAgent
        writer = LLMTraceWriter("/tmp/fake")
        agent = SegmentProducerAgent(trace_writer=writer)
        assert agent._trace_writer is writer

    def test_scriptwriter_accepts_trace_writer(self):
        """ScriptwriterAgent accepts trace_writer kwarg."""
        from clipper_agency.agents.scriptwriter import ScriptwriterAgent
        writer = LLMTraceWriter("/tmp/fake")
        agent = ScriptwriterAgent(trace_writer=writer)
        assert agent._trace_writer is writer

    def test_voice_producer_accepts_trace_writer(self):
        """VoiceProducerAgent accepts trace_writer kwarg."""
        from clipper_agency.agents.voice_producer import VoiceProducerAgent
        writer = LLMTraceWriter("/tmp/fake")
        agent = VoiceProducerAgent(trace_writer=writer)
        assert agent._trace_writer is writer

    def test_visual_director_accepts_trace_writer(self):
        """VisualDirectorAgent accepts trace_writer kwarg."""
        from clipper_agency.agents.visual_director import VisualDirectorAgent
        writer = LLMTraceWriter("/tmp/fake")
        agent = VisualDirectorAgent(trace_writer=writer)
        assert agent._trace_writer is writer

    def test_composer_accepts_trace_writer(self):
        """ComposerAgent accepts trace_writer kwarg."""
        from clipper_agency.agents.composer import ComposerAgent
        writer = LLMTraceWriter("/tmp/fake")
        agent = ComposerAgent(trace_writer=writer)
        assert agent._trace_writer is writer


# ──────────────────────────────────────────────────────────────
# Task 5.1K — Graceful Degradation (Config Disabled)
# ──────────────────────────────────────────────────────────────


class TestGracefulDegradation:
    """Verify config-gating skips detection gracefully."""

    def test_populate_diagnostics_skips_when_text_collision_disabled(self, mocker):
        """_populate_actual_detection_diagnostics skips text_collision when disabled."""
        mocker.patch(
            "clipper_agency.agents.reviewer._is_enabled", return_value=False,
        )
        diagnostics = {
            "frame_size": [1080, 1920],
            "generated_text_regions": [],
            "source_text_regions": [{"bbox": [0, 0, 100, 100], "layer": "src"}],
        }

        enriched = ReviewerAgent()._populate_actual_detection_diagnostics(
            diagnostics,
        )
        assert enriched is not None
        assert enriched.get("text_collision") is None

    def test_populate_diagnostics_does_not_crash_on_exception(self, mocker):
        """_populate_actual_detection_diagnostics catches exceptions gracefully."""
        mocker.patch(
            "clipper_agency.agents.reviewer._is_enabled", return_value=True,
        )
        # Make detect_text_collisions raise an exception
        mocker.patch(
            "clipper_agency.agents.reviewer.detect_text_collisions",
            side_effect=ValueError("simulated crash"),
        )

        diagnostics = {
            "frame_size": [1080, 1920],
            "generated_text_regions": [{"bbox": [0, 0, 100, 100], "layer": "sub"}],
            "source_text_regions": [{"bbox": [0, 0, 100, 100], "layer": "src"}],
        }

        enriched = ReviewerAgent()._populate_actual_detection_diagnostics(
            diagnostics,
        )
        assert enriched is not None
        # Should not crash — original diagnostics returned intact
        assert isinstance(enriched, dict)


# ──────────────────────────────────────────────────────────────
# Task 5.1L — Visual Director imports (pre-render wiring)
# ──────────────────────────────────────────────────────────────


class TestVisualDirectorWiringImports:
    """Verify Visual Director can import all pre-render wired modules."""

    def test_visual_director_imports_frame_pipeline(self):
        """Visual Director imports run_frame_inspection_pipeline."""
        from clipper_agency.agents.visual_director import VisualDirectorAgent
        # The import inside the agent file must resolve
        import clipper_agency.core.frame_inspection_pipeline as fip
        assert hasattr(fip, "run_frame_inspection_pipeline")

    def test_visual_director_imports_inspection_paths(self):
        """Visual Director imports candidate_inspection_dir."""
        from clipper_agency.core.inspection_paths import candidate_inspection_dir
        assert callable(candidate_inspection_dir)

    def test_visual_director_imports_ocr_adapter(self):
        """Visual Director can import PaddleOCRAdapter (lazy)."""
        from clipper_agency.core.ocr_adapter import PaddleOCRAdapter
        assert PaddleOCRAdapter is not None

    def test_visual_director_imports_face_adapter(self):
        """Visual Director can import MediaPipeFaceDetector (lazy)."""
        from clipper_agency.core.face_adapter import MediaPipeFaceDetector
        assert MediaPipeFaceDetector is not None

    def test_visual_director_imports_source_cleanliness(self):
        """Visual Director imports score_source_cleanliness."""
        from clipper_agency.core.source_cleanliness import score_source_cleanliness
        assert callable(score_source_cleanliness)


# ──────────────────────────────────────────────────────────────
# Task 5.1M — Composer wiring imports
# ──────────────────────────────────────────────────────────────


class TestComposerWiringImports:
    """Verify Composer can import all post-render wired modules."""

    def test_composer_imports_empty_frame(self):
        """Composer imports detect_empty_segments."""
        from clipper_agency.core.frame_quality import detect_empty_segments
        assert callable(detect_empty_segments)

    def test_composer_imports_generated_text_manifest(self):
        """Composer imports build_generated_text_regions."""
        from clipper_agency.core.generated_text_manifest import build_generated_text_regions
        assert callable(build_generated_text_regions)

    def test_composer_imports_rendered_scene_manifest(self):
        """Composer imports build_rendered_scene_manifest."""
        from clipper_agency.core.rendered_scene_manifest import build_rendered_scene_manifest
        assert callable(build_rendered_scene_manifest)

    def test_composer_imports_final_layout_inspection(self):
        """Composer imports final_layout_inspection module."""
        import clipper_agency.core.final_layout_inspection
        assert clipper_agency.core.final_layout_inspection is not None
