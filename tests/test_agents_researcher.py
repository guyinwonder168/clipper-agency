"""Backward-compatible re-export wrapper for renamed test module.

The tests for ResearcherAgent have been moved to test_agents_segment_producer.py.
This file re-imports all test classes so existing test runners still discover them.
"""

from tests.test_agents_segment_producer import (  # noqa: F401
    TestSegmentProducerAggregateData as TestResearcherAggregateData,
    TestSegmentProducerExecute as TestResearcherExecute,
    TestSegmentProducerName as TestResearcherName,
    TestSegmentProducerNewContract,
    TestSegmentProducerSynthesize as TestResearcherSynthesize,
)
