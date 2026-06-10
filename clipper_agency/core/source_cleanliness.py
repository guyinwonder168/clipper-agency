"""Source cleanliness scoring for asset suitability assessment.

Determines if media is clean enough for fullscreen use or needs special
treatment (picture-in-picture, cropping, replacement, text card fallback).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OCR_TEXT_AREA_THRESHOLD = 0.20
LOGO_DOMINANT_THRESHOLD = 0.15
RESOLUTION_MIN_WIDTH = 1280
RESOLUTION_MIN_HEIGHT = 720

ISSUE_BURNED_CAPTION = "BURNED_CAPTION"
ISSUE_DOMINANT_LOGO = "DOMINANT_LOGO"
ISSUE_MINOR_LOGO = "MINOR_LOGO"
ISSUE_FACE_OBSTRUCTION = "FACE_OBSTRUCTION"
ISSUE_LOW_RESOLUTION = "LOW_RESOLUTION"

TREATMENT_FULLSCREEN = "fullscreen"
TREATMENT_PIP = "picture_in_picture"
TREATMENT_REPLACE_ASSET = "replace_asset"
TREATMENT_CROPPED_FULLSCREEN = "cropped_fullscreen"
TREATMENT_TEXT_CARD_FALLBACK = "text_card_fallback"

# Score deductions per issue type.
SCORE_DEDUCTION_BURNED_CAPTION = 0.20
SCORE_DEDUCTION_DOMINANT_LOGO = 0.30
SCORE_DEDUCTION_MINOR_LOGO = 0.10
SCORE_DEDUCTION_FACE_OBSTRUCTION = 0.25
SCORE_DEDUCTION_LOW_RESOLUTION = 0.15


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_source_cleanliness(
    ocr_text_area_ratio: float = 0.0,
    has_logo: bool = False,
    logo_coverage_ratio: float = 0.0,
    safe_crop_available: bool = False,
    face_obstructed: bool = False,
    resolution: tuple[int, int] = (1920, 1080),
    has_burned_captions: bool = False,
) -> dict:
    """Score source cleanliness and determine allowed treatments.

    Args:
        ocr_text_area_ratio: Fraction of frame covered by OCR text (0.0-1.0).
        has_logo: Whether a logo/watermark was detected.
        logo_coverage_ratio: Fraction of frame covered by the logo (0.0-1.0).
        safe_crop_available: Whether the frame can be safely cropped.
        face_obstructed: Whether faces are partially covered by overlays.
        resolution: Source resolution as (width, height).
        has_burned_captions: Whether hardcoded subtitles are present.

    Returns:
        dict with keys:
        - cleanliness_score: float 0.0-1.0 (higher = cleaner)
        - issues: list of issue code strings
        - fullscreen_allowed: bool
        - allowed_treatments: list of treatment name strings
    """
    issues: list[str] = []
    deduction = 0.0
    fullscreen_allowed = True

    # --- Rule 1: OCR text area ---
    if ocr_text_area_ratio > OCR_TEXT_AREA_THRESHOLD or has_burned_captions:
        issues.append(ISSUE_BURNED_CAPTION)
        deduction += SCORE_DEDUCTION_BURNED_CAPTION

    # --- Rules 2, 3, 4: Logo / watermark ---
    logo_issue: str | None = None
    if has_logo and logo_coverage_ratio > LOGO_DOMINANT_THRESHOLD:
        # Rule 2: Dominant logo — fullscreen banned
        logo_issue = ISSUE_DOMINANT_LOGO
        deduction += SCORE_DEDUCTION_DOMINANT_LOGO
        fullscreen_allowed = False
    elif has_logo and logo_coverage_ratio > 0:
        # Rules 3 & 4: Minor logo
        logo_issue = ISSUE_MINOR_LOGO
        deduction += SCORE_DEDUCTION_MINOR_LOGO
        if not safe_crop_available:
            # Rule 4: No safe crop — fullscreen banned
            fullscreen_allowed = False
        # Rule 3: safe_crop_available → fullscreen stays allowed

    if logo_issue is not None:
        issues.append(logo_issue)

    # --- Rule 5: Face obstruction ---
    if face_obstructed:
        issues.append(ISSUE_FACE_OBSTRUCTION)
        deduction += SCORE_DEDUCTION_FACE_OBSTRUCTION
        fullscreen_allowed = False

    # --- Rule 6: Low resolution ---
    if resolution[0] < RESOLUTION_MIN_WIDTH or resolution[1] < RESOLUTION_MIN_HEIGHT:
        issues.append(ISSUE_LOW_RESOLUTION)
        deduction += SCORE_DEDUCTION_LOW_RESOLUTION

    # --- Compute score ---
    cleanliness_score = max(0.0, 1.0 - deduction)
    cleanliness_score = round(cleanliness_score, 4)

    # --- Determine allowed treatments ---
    allowed_treatments = _determine_treatments(
        fullscreen_allowed=fullscreen_allowed,
        has_logo=has_logo,
        safe_crop_available=safe_crop_available,
    )

    return {
        "cleanliness_score": cleanliness_score,
        "issues": issues,
        "fullscreen_allowed": fullscreen_allowed,
        "allowed_treatments": allowed_treatments,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _determine_treatments(
    fullscreen_allowed: bool,
    has_logo: bool,
    safe_crop_available: bool,
) -> list[str]:
    """Build the list of allowed treatment names.

    Rules:
    - picture_in_picture, text_card_fallback, replace_asset: always available.
    - cropped_fullscreen: available when safe_crop_available is True, OR when
      there is no logo issue preventing cropping (clean source, or non-logo issues).
    - fullscreen: available only when fullscreen_allowed is True.
    """
    treatments: list[str] = [
        TREATMENT_PIP,
        TREATMENT_TEXT_CARD_FALLBACK,
        TREATMENT_REPLACE_ASSET,
    ]

    if fullscreen_allowed:
        treatments.append(TREATMENT_FULLSCREEN)

    # cropped_fullscreen: always available unless a logo issue explicitly
    # prevents it (dominant logo can't be cropped, minor logo without safe
    # crop area can't be cropped either).
    if safe_crop_available or not has_logo:
        treatments.append(TREATMENT_CROPPED_FULLSCREEN)

    return treatments
