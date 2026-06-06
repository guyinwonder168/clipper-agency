"""Tests for canonical path helpers."""

from clipper_agency.core.paths import (
    agent_dir,
    agent_input_file,
    agent_output_file,
    gate_result_file,
    job_cache_dir,
    job_final_output_dir,
    researcher_brief_file,
    researcher_contract_file,
    segment_producer_brief_file,
    segment_producer_contract_file,
    visual_scene_file,
    voice_scene_file,
)


def test_job_cache_dir_uses_assets_cache():
    assert job_cache_dir("data/assets/cache", 125) == "data/assets/cache/job_125"


def test_agent_paths_are_under_job_cache():
    assert agent_dir("data/assets/cache", 125, "researcher") == (
        "data/assets/cache/job_125/agents/researcher"
    )
    assert agent_input_file("data/assets/cache", 125, "safety") == (
        "data/assets/cache/job_125/agents/safety/input.json"
    )
    assert agent_output_file("data/assets/cache", 125, "safety") == (
        "data/assets/cache/job_125/agents/safety/output.json"
    )


def test_researcher_specific_paths():
    assert researcher_brief_file("data/assets/cache", 125) == (
        "data/assets/cache/job_125/agents/segment_producer/research_brief.md"
    )
    assert researcher_contract_file("data/assets/cache", 125) == (
        "data/assets/cache/job_125/agents/segment_producer/research_contract.json"
    )


def test_segment_producer_specific_paths():
    assert segment_producer_brief_file("data/assets/cache", 125) == (
        "data/assets/cache/job_125/agents/segment_producer/research_brief.md"
    )
    assert segment_producer_contract_file("data/assets/cache", 125) == (
        "data/assets/cache/job_125/agents/segment_producer/research_contract.json"
    )


def test_researcher_paths_alias_segment_producer_paths():
    """Legacy researcher_* functions are aliases for segment_producer_* functions."""
    assert researcher_brief_file("data/assets/cache", 125) == (
        segment_producer_brief_file("data/assets/cache", 125)
    )
    assert researcher_contract_file("data/assets/cache", 125) == (
        segment_producer_contract_file("data/assets/cache", 125)
    )


def test_voice_and_visual_asset_paths():
    assert voice_scene_file("data/assets/cache", 125, 1) == (
        "data/assets/cache/job_125/agents/voice_producer/voices/scene_1.mp3"
    )
    assert visual_scene_file("data/assets/cache", 125, 1) == (
        "data/assets/cache/job_125/agents/visual_director/scenes/scene_1.mp4"
    )


def test_gate_and_final_output_paths_are_separate():
    assert gate_result_file("data/assets/cache", 125, "G1_input_preflight") == (
        "data/assets/cache/job_125/gates/G1_input_preflight.json"
    )
    assert job_final_output_dir("data/outputs", 125) == "data/outputs/job_125"
