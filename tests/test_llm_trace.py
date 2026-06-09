import json

from clipper_agency.observability.llm_trace import LLMTraceMetadata, LLMTraceWriter


def build_trace_writer(tmp_path):
    return LLMTraceWriter(cache_root=tmp_path)


def make_trace_handle(writer):
    return writer.start_call(
        job_id=5,
        agent="reviewer",
        task="final_editorial_review",
        provider="openrouter",
        model="gemini-2.5-flash",
        prompt_template_id="reviewer.md",
        prompt_version="sha256:test",
    )


def trace_file(handle, filename):
    return handle.trace_dir / filename


def test_llm_trace_metadata_exposes_required_fields():
    metadata = LLMTraceMetadata(
        call_id="call-1",
        job_id=5,
        agent="reviewer",
        task="final_editorial_review",
        provider="openrouter",
        model="gemini-2.5-flash",
        prompt_template_id="reviewer.md",
        prompt_version="sha256:test",
        request_timestamp="2026-06-09T00:00:00Z",
        response_timestamp=None,
        provider_request_id=None,
        retry_count=0,
        latency_sec=None,
        tokens_in=None,
        tokens_out=None,
        cost=None,
        finish_reason=None,
        parse_status="pending",
        schema_validation_status="pending",
    )

    assert metadata.model_dump()["call_id"] == "call-1"
    assert metadata.model_dump()["schema_validation_status"] == "pending"


def test_llm_trace_persists_resolved_request_and_raw_response(tmp_path):
    writer = build_trace_writer(tmp_path)

    handle = writer.start_call(
        job_id=5,
        agent="reviewer",
        task="final_editorial_review",
        provider="openrouter",
        model="gemini-2.5-flash",
        prompt_template_id="reviewer.md",
        prompt_version="sha256:test",
    )

    request_path = writer.persist_request(
        handle,
        messages=[
            {"role": "system", "content": "You are a reviewer."},
            {"role": "user", "content": "Review this video package."},
        ],
        parameters={"temperature": 0.2},
    )
    response_path = writer.persist_response(
        handle,
        raw_response={"content": '{"verdict":"fail"}'},
        usage={"prompt_tokens": 100, "completion_tokens": 10},
        provider_metadata={"request_id": "gen-123"},
    )

    assert request_path.exists()
    assert response_path.exists()
    assert "Review this video package" in request_path.read_text()
    assert json.loads(response_path.read_text())["raw_response"]["content"] == '{"verdict":"fail"}'
    assert request_path == tmp_path / "job_5" / "llm_traces" / "reviewer" / handle.call_id / "request.json"


def test_llm_trace_persists_raw_parsed_and_validation_as_separate_layers(tmp_path):
    writer = build_trace_writer(tmp_path)
    handle = make_trace_handle(writer)

    writer.persist_response(handle, {"content": "```json\n{\"score\":40}\n```"}, {}, {})
    writer.persist_parsed_response(handle, {"score": 40})
    writer.persist_validation(
        handle,
        {
            "json_parse": "passed_after_markdown_strip",
            "schema_validation": "passed",
        },
    )

    assert trace_file(handle, "response.json").exists()
    assert trace_file(handle, "parsed_response.json").exists()
    assert trace_file(handle, "validation.json").exists()
    assert json.loads(trace_file(handle, "parsed_response.json").read_text())["parsed_result"] == {"score": 40}
