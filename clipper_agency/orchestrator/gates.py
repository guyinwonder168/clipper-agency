"""Pipeline gates (G1-G10) — validation checkpoints for job processing."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clipper_agency.core.media_probe import probe_video
from clipper_agency.core.narrative_coverage import NarrativeCoverageResult


@dataclass
class GateResult:
    """Result of a gate evaluation."""

    passed: bool
    severity: str  # "pass" | "soft_fail" | "hard_fail"
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class BaseGate:
    """Base class for pipeline gates."""

    def evaluate(self, **kwargs: Any) -> GateResult:
        raise NotImplementedError


# ════════════════════════════════════════════════════════════════════
# G1: Input Preflight — validate topic before any processing
# ════════════════════════════════════════════════════════════════════


class GateInputPreflight(BaseGate):
    """G1: Validate topic input before any processing."""

    def evaluate(
        self,
        topic: str = "",
        niche_config: dict | None = None,
        source_url: str | None = None,
        **kwargs,
    ) -> GateResult:
        if not topic or not topic.strip():
            return GateResult(False, "hard_fail", "Topic cannot be empty")
        if niche_config is None:
            return GateResult(False, "hard_fail", "Niche config required")
        return GateResult(True, "pass", "Input valid", data={"topic": topic.strip()})


# ════════════════════════════════════════════════════════════════════
# G2: Cost Estimate — lightweight credit/cost estimate
# ════════════════════════════════════════════════════════════════════


class GateCostEstimate(BaseGate):
    """G2: Lightweight cost + credit estimate."""

    BASE_COST_CENTS = 3.3  # Budget East total in cents

    def evaluate(
        self, cached: bool = False, niche_config: dict | None = None, **kwargs
    ) -> GateResult:
        estimated_cents = self.BASE_COST_CENTS if not cached else self.BASE_COST_CENTS * 0.7
        return GateResult(
            True,
            "pass",
            f"Est. cost: ${estimated_cents / 100:.4f}",
            data={"estimate_cents": estimated_cents},
        )


# ════════════════════════════════════════════════════════════════════
# G3: Research Cache — check cache TTL / freshness
# ════════════════════════════════════════════════════════════════════


class GateResearchCache(BaseGate):
    """G3: Check research cache TTL."""

    def evaluate(self, cache_entry: dict | None = None, **kwargs) -> GateResult:
        if cache_entry and cache_entry.get("freshness") == "fresh":
            return GateResult(True, "pass", "Fresh cache available", data=cache_entry)
        if cache_entry and cache_entry.get("freshness") == "stale":
            return GateResult(True, "soft_fail", "Stale cache - reusing", data=cache_entry)
        return GateResult(False, "hard_fail", "No valid cache - research needed")


# ════════════════════════════════════════════════════════════════════
# G4: Post-Research Risk — check for dangerous content
# ════════════════════════════════════════════════════════════════════


class GatePostResearchRisk(BaseGate):
    """G4: Post-research risk check."""

    DANGER_KEYWORDS = ["ilegal", "banned", "defamation", "sara"]

    @staticmethod
    def _normalize_flags(flags: list) -> str:
        """Extract searchable text from risk flags (str or dict entries)."""
        texts: list[str] = []
        for f in flags:
            if isinstance(f, dict):
                texts.append(f"{f.get('category', '')} {f.get('description', '')}")
            else:
                texts.append(str(f))
        return " ".join(texts).lower()

    def evaluate(self, risk_flags: list | None = None, **kwargs) -> GateResult:
        flags = risk_flags or []
        combined = self._normalize_flags(flags)
        if any(kw in combined for kw in self.DANGER_KEYWORDS):
            return GateResult(
                False, "hard_fail", "High-risk content detected", data={"risk_flags": flags}
            )
        if "unverified" in combined:
            return GateResult(
                True,
                "soft_fail",
                "Unverified claims - use cautious wording",
                data={"risk_flags": flags},
            )
        return GateResult(True, "pass", "No risks detected")


# ════════════════════════════════════════════════════════════════════
# G5: Source Quality — check available video sources
# ════════════════════════════════════════════════════════════════════


class GateSourceQuality(BaseGate):
    """G5: Source quality check."""

    def evaluate(self, video_sources: list | None = None, **kwargs) -> GateResult:
        sources = video_sources or []
        if len(sources) >= 2:
            return GateResult(True, "pass", f"{len(sources)} sources available")
        if len(sources) == 1:
            return GateResult(True, "soft_fail", "Only 1 source - use Pexels fallback")
        return GateResult(False, "hard_fail", "No usable sources")


# ════════════════════════════════════════════════════════════════════
# G6: Creative Memory — check angle exhaustion
# ════════════════════════════════════════════════════════════════════


class GateCreativeMemory(BaseGate):
    """G6: Creative memory check."""

    def evaluate(
        self,
        used_angles: list[str] | None = None,
        available_angles: list[str] | None = None,
        **kwargs,
    ) -> GateResult:
        used = set(used_angles or [])
        available = set(available_angles or [])
        remaining = available - used
        if len(remaining) >= 2:
            return GateResult(
                True, "pass", "Variation available", data={"remaining_angles": list(remaining)}
            )
        if len(remaining) == 1:
            return GateResult(True, "soft_fail", "Only 1 angle left")
        return GateResult(False, "hard_fail", "All angles exhausted")


# ════════════════════════════════════════════════════════════════════
# G7: Script Validation — check script + caption quality
# ════════════════════════════════════════════════════════════════════


class GateScriptValidation(BaseGate):
    """G7: Script validation."""

    def evaluate(self, script: str = "", caption: str = "", **kwargs) -> GateResult:
        if not script.strip():
            return GateResult(False, "hard_fail", "Empty script")
        if not caption.strip():
            return GateResult(False, "soft_fail", "Empty caption - auto-generate")
        if len(caption) > 150:
            return GateResult(True, "soft_fail", "Caption >150 chars - trim needed")
        return GateResult(True, "pass", "Script and caption valid")


# ════════════════════════════════════════════════════════════════════
# G7 (active): Narrative coverage contract (ADR 0030 / FIX-1)
# ════════════════════════════════════════════════════════════════════


class GateNarrativeCoverage(BaseGate):
    """G7: Narrative coverage contract (ADR 0030 / FIX-1).

    Asserts that ``narrative_structure`` word_range indices fully cover
    [0, word_count-1] (contiguously, in-bounds). The bounds/contiguity/
    coverage math and eligible in-place tail repair live in the pure
    ``clipper_agency.core.narrative_coverage`` module; this gate is the thin
    adapter that turns a ``NarrativeCoverageResult`` into a ``GateResult``.

    Repair contract: the engine MUST apply ``coverage.repaired_structure``
    to ``script_output['narrative_structure']`` BEFORE evaluating this gate,
    so a repaired structure yields ok=True / severity='pass' (not soft_fail —
    ``_enforce_gate`` only aborts on hard_fail, and in-place repair is a
    corrected pass, not a degrade).

    Recorded under the DISTINCT label ``G7_narrative_coverage`` so it does
    not collide with the existing ``GateScriptValidation`` (script/caption
    quality, recorded under ``G7_script_validation``). Relax it explicitly
    via ``DEV_RELAX_GATES=G7_NARRATIVE_COVERAGE``.
    """

    # Stable machine reason emitted in GateResult.data['reason'] on hard_fail.
    # FIX-5 routes repair on this exact token; do not rename without updating
    # repair_router.GATE_FAILURE_REPAIR_MAP.
    FAILURE_REASON = "narrative_not_covered"

    def evaluate(
        self,
        coverage: "NarrativeCoverageResult | None" = None,
        **kwargs: Any,
    ) -> GateResult:
        # A missing coverage result is a WIRING error, not a safe default.
        # Silently passing here would re-open the exact job_18 hole this gate
        # exists to close (under-covered narrative reaching Voice Producer).
        # Fail loud; operators bypass via DEV_RELAX_GATES=G7_NARRATIVE_COVERAGE.
        if coverage is None:
            return GateResult(
                False,
                "hard_fail",
                "NarrativeCoverageResult not supplied to G7 gate (wiring error)",
                data={"reason": self.FAILURE_REASON, "violation_type": "not_evaluated"},
            )

        if coverage.ok:
            return GateResult(
                True,
                "pass",
                coverage.reason,
                data={"reason": coverage.reason, **coverage.details},
            )

        return GateResult(
            False,
            "hard_fail",
            coverage.reason,
            data={"reason": self.FAILURE_REASON, **coverage.details},
        )


# ════════════════════════════════════════════════════════════════════
# G8: Audio Validation — check generated audio file
# ════════════════════════════════════════════════════════════════════


class GateAudioValidation(BaseGate):
    """G8: Audio validation."""

    def evaluate(self, audio_path: str | None = None, **kwargs) -> GateResult:
        if not audio_path or not Path(audio_path).exists():
            return GateResult(False, "hard_fail", "Audio file missing")
        size = Path(audio_path).stat().st_size
        if size == 0:
            return GateResult(False, "hard_fail", "Audio file is empty")
        return GateResult(True, "pass", "Audio valid")


# ════════════════════════════════════════════════════════════════════
# G9: Asset Validation — check visual assets
# ════════════════════════════════════════════════════════════════════


class GateAssetValidation(BaseGate):
    """G9: Asset validation."""

    @staticmethod
    def _filter_text_card_paths(
        asset_paths: list[str],
        assets: list[dict],
    ) -> list[str] | None:
        """Remove text_card/none assets with empty paths.

        Returns None when all paths are filtered (all text cards).
        """
        skip_indices = {
            i
            for i, a in enumerate(assets)
            if not a.get("path", "") and a.get("source", "") in ("text_card", "none")
        }
        if not skip_indices:
            return asset_paths
        filtered = [p for i, p in enumerate(asset_paths) if i not in skip_indices]
        return filtered if filtered else None

    def evaluate(
        self, asset_paths: list[str] | None = None, assets: list[dict] | None = None, **kwargs
    ) -> GateResult:
        paths = asset_paths or []
        if not paths:
            return GateResult(False, "hard_fail", "No assets")
        # Filter out text_card/none assets with empty paths —
        # Composer generates card fallbacks for these.
        if assets:
            filtered = self._filter_text_card_paths(paths, assets)
            if filtered is None:
                return GateResult(True, "pass", "All assets are text cards (no downloads needed)")
            paths = filtered
        valid = [p for p in paths if Path(p).exists() and Path(p).stat().st_size > 0]
        if not valid:
            return GateResult(False, "hard_fail", "No valid assets")
        if len(valid) < len(paths):
            return GateResult(True, "soft_fail", f"{len(valid)}/{len(paths)} assets valid")
        return GateResult(True, "pass", "All assets valid")


# ════════════════════════════════════════════════════════════════════
# G10: Video Output Validation — check final video
# ════════════════════════════════════════════════════════════════════


class GateVideoValidation(BaseGate):
    """G10: Deterministic video output validation using ffprobe metadata.

    Checks resolution (1080x1920), codec (h264), duration (20-60s),
    and audio track presence.
    """

    REQUIRED_WIDTH = 1080
    REQUIRED_HEIGHT = 1920
    REQUIRED_CODEC = "h264"
    MIN_DURATION = 20
    DEFAULT_MAX_DURATION = 60
    # FIX-2 (audio-as-master): tolerance for AUDIO_NOT_TRUNCATED. Audio stream
    # may be marginally shorter than the source voiceover due to encoder
    # padding/rounding; only flag truncation beyond this half-second gap.
    AUDIO_TRUNC_TOL_SEC = 0.5

    def _check_duration_only(
        self,
        duration_sec: float,
        hard_limit_sec: int | None = None,
    ) -> GateResult | None:
        """Check just the duration against limits.

        Returns None on pass, GateResult on fail.
        """
        max_duration = hard_limit_sec if hard_limit_sec is not None else self.DEFAULT_MAX_DURATION
        if duration_sec < self.MIN_DURATION:
            return GateResult(
                False,
                "hard_fail",
                f"Video too short: {duration_sec:.1f}s, minimum {self.MIN_DURATION}s",
            )
        if duration_sec > max_duration:
            return GateResult(
                False,
                "hard_fail",
                f"Video too long: {duration_sec:.1f}s, maximum {max_duration}s",
            )
        return None

    def evaluate(
        self,
        video_path: str | None = None,
        hard_limit_sec: int | None = None,
        voiceover_duration_sec: float | None = None,
        **kwargs,
    ) -> GateResult:
        if not video_path or not Path(video_path).exists():
            return GateResult(False, "hard_fail", "Video file missing")

        info = probe_video(video_path, Path(video_path).parent)
        if info is None:
            return GateResult(
                False,
                "hard_fail",
                "Video file not found or unreadable by ffprobe",
            )

        if info.width != self.REQUIRED_WIDTH or info.height != self.REQUIRED_HEIGHT:
            return GateResult(
                False,
                "hard_fail",
                f"Wrong resolution: {info.width}x{info.height}, "
                f"expected {self.REQUIRED_WIDTH}x{self.REQUIRED_HEIGHT}",
            )

        if info.codec != self.REQUIRED_CODEC:
            return GateResult(
                False,
                "hard_fail",
                f"Wrong codec: {info.codec}, expected {self.REQUIRED_CODEC}",
            )

        if info.duration is None:
            return GateResult(
                False,
                "hard_fail",
                "Video duration unknown — cannot validate",
            )

        duration_fail = self._check_duration_only(info.duration, hard_limit_sec)
        if duration_fail is not None:
            return duration_fail

        if not info.has_audio:
            return GateResult(
                False,
                "hard_fail",
                "No audio track found",
            )

        # FIX-2 (audio-as-master, ADR 0030): AUDIO_NOT_TRUNCATED — independently
        # re-probe the audio STREAM duration (not the container duration, which
        # is -shortest/-t-equalized and hides the job_18 truncation). The audio
        # stream is the master; if it is shorter than the source voiceover by
        # more than the tolerance, the audio was truncated. Skipped (pass) when
        # voiceover_duration_sec is None (legacy callers) or the audio-stream
        # duration is unavailable in the ffprobe metadata.
        if (
            voiceover_duration_sec
            and info.audio_duration is not None
            and info.audio_duration < voiceover_duration_sec - self.AUDIO_TRUNC_TOL_SEC
        ):
            return GateResult(
                False,
                "hard_fail",
                f"AUDIO_NOT_TRUNCATED: audio stream {info.audio_duration:.2f}s "
                f"< voiceover {voiceover_duration_sec:.2f}s "
                f"- {self.AUDIO_TRUNC_TOL_SEC}s tolerance",
                data={
                    "reason": "audio_truncated",
                    "audio_sec": info.audio_duration,
                    "voiceover_sec": voiceover_duration_sec,
                },
            )

        return GateResult(True, "pass", "Video valid")
