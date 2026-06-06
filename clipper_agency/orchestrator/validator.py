"""Format Validator — validates content_direction from Researcher."""

from dataclasses import dataclass, field

from clipper_agency.config.schema import ContentPlanningConfig

VALID_FORMATS = {"three_story_roundup", "single_story_deep", "rapid_bulletin"}


@dataclass
class ContentDirectionResult:
    """Validated content direction for downstream agents."""

    format: str = ""
    story_count: int = 3
    stories: list[str] = field(default_factory=list)
    content_angle: str = ""
    fallback: bool = False


def validate_content_direction(
    direction: dict | None,
    config: ContentPlanningConfig,
) -> ContentDirectionResult:
    """Validate and normalize Researcher's content_direction.

    Returns a ContentDirectionResult with clamped values and fallback
    handling for missing or invalid direction data.
    """
    if direction is None:
        return ContentDirectionResult(
            format=config.default_format,
            story_count=config.max_stories_per_video,
            fallback=True,
        )

    fmt = direction.get("recommended_format", "")
    if fmt not in VALID_FORMATS:
        fmt = config.default_format

    raw_count = direction.get("selected_story_count", 0) or 0
    count = min(max(1, raw_count), config.max_stories_per_video)
    if raw_count == 0:
        count = config.max_stories_per_video

    stories = list(direction.get("selected_stories", []) or [])
    stories = stories[:count]

    return ContentDirectionResult(
        format=fmt,
        story_count=count,
        stories=stories,
        content_angle=direction.get("content_angle", ""),
        fallback=(raw_count != count),
    )
