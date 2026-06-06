"""Timeline Reconciler — creates canonical timeline from script + audio metadata."""

from dataclasses import dataclass, field


@dataclass
class TimelineItem:
    """A single scene's timeline contract."""

    scene: int
    role: str
    text: str = ""
    audio_path: str = ""
    audio_duration_sec: float = 0.0
    start_sec: float = 0.0
    end_sec: float = 0.0
    target_duration_sec: float = 0.0
    visual_instruction: str = ""


@dataclass
class ReconciledTimeline:
    """Canonical timeline combining script, audio, and duration constraints."""

    timeline: list[TimelineItem] = field(default_factory=list)
    total_duration_sec: float = 0.0
    target_duration_sec: int = 55
    hard_limit_sec: int = 60
    within_limit: bool = True


def _visual_instruction_for_role(role: str) -> str:
    """Map scene role to visual director instruction."""
    if role == "opening_hook":
        return "Create an opening card with bold headline text"
    if role == "cta":
        return "Create a CTA card with follow/like prompt"
    return "Standard visual"


def reconcile_timeline(
    scenes: list[dict],
    audio_meta: list[dict],
    target: int = 55,
    hard: int = 60,
) -> ReconciledTimeline:
    """Build canonical timeline from script scenes and audio metadata.

    Prefers measured audio durations when available, falls back to
    script-estimated durations. Computes cumulative start/end times.
    Fails the timeline (within_limit=False) if total exceeds hard limit.
    """
    audio_by_scene = {a["scene"]: a for a in audio_meta}
    items: list[TimelineItem] = []
    cursor = 0.0

    for sc in scenes:
        scene_num = sc.get("scene", len(items) + 1)
        role = sc.get("role", "body")
        text = sc.get("text", "")
        audio = audio_by_scene.get(scene_num, {})
        duration = audio.get(
            "audio_duration_sec",
            sc.get("estimated_duration_sec", 5.0),
        )
        duration = max(duration, 0.5)

        items.append(
            TimelineItem(
                scene=scene_num,
                role=role,
                text=text,
                audio_path=audio.get("audio_path", ""),
                audio_duration_sec=audio.get("audio_duration_sec", 0.0),
                start_sec=cursor,
                end_sec=cursor + duration,
                target_duration_sec=duration,
                visual_instruction=_visual_instruction_for_role(role),
            )
        )
        cursor += duration

    total = round(cursor, 1)
    return ReconciledTimeline(
        timeline=items,
        total_duration_sec=total,
        target_duration_sec=target,
        hard_limit_sec=hard,
        within_limit=(total <= hard),
    )
