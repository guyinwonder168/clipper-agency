"""Backward-compatible re-export wrapper.

The ResearcherAgent has been renamed to SegmentProducerAgent.
This module re-exports the new class under the old name for
backward compatibility during the transition period (Batch 2
will remove this wrapper when engine.py is updated).
"""

from clipper_agency.agents.segment_producer import (  # noqa: F401
    MAX_CHARS_PER_SOURCE,
    MAX_SOURCE_CHARS,
    SEGMENT_PRODUCER_PROMPT as RESEARCH_PROMPT,
    SegmentProducerAgent as ResearcherAgent,
)

# Also make the module-level prompt available under the old name
# so that existing test imports continue to work.
__all__ = ["ResearcherAgent", "RESEARCH_PROMPT"]
