import json

from clipper_agency.observability.redaction import redact_trace_payload


def test_llm_trace_redacts_api_keys_and_authorization_headers():
    payload = {
        "headers": {"Authorization": "Bearer secret-key"},
        "api_key": "sk-secret",
        "messages": [{"role": "user", "content": "ordinary content remains"}],
    }

    redacted = redact_trace_payload(payload)
    serialized = json.dumps(redacted)

    assert "secret-key" not in serialized
    assert "sk-secret" not in serialized
    assert "ordinary content remains" in serialized


def test_llm_trace_redaction_preserves_source_urls():
    payload = {
        "source_url": "https://example.com/source/story",
        "messages": [{"role": "user", "content": "source content stays visible"}],
    }

    redacted = redact_trace_payload(payload)

    assert redacted["source_url"] == "https://example.com/source/story"
    assert redacted["messages"][0]["content"] == "source content stays visible"
