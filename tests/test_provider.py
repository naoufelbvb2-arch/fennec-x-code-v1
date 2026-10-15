from copy import deepcopy
import http.client
import json
import socket

import pytest

from sca.contracts import AgentTask, Message, ModelRequest, ToolCall, ToolDefinition, ToolResult
from sca.provider import (
    CompatibleModel, ConfigurationError, HttpResponse, HttpTransport, ModelConfig,
    build_payload, parse_response, tool_schema,
)
from sca.tools import ToolRuntime


TASK = AgentTask("Task", "workspace-metadata", "session-metadata")


def request(*messages, definitions=()):
    return ModelRequest("Instructions", messages or (Message("user", "Task"),), tuple(definitions), {"max_model_rounds": 25}, TASK)


def config(**overrides):
    return ModelConfig(**{"model": "user-chosen-model", "api_base_url": "https://configured.invalid/custom/v1", **overrides})


def test_no_implicit_provider_model_or_credentials():
    with pytest.raises(ConfigurationError, match="configuration missing"):
        ModelConfig.from_environment(environ={"OPENAI_API_KEY": "unrelated-test-value"})


def test_explicit_flags_override_environment_without_discovering_providers():
    selected = ModelConfig.from_environment(
        model="selected", api_base_url="http://127.0.0.1:8765/v1", auth="none",
        environ={"FENNEC_MODEL": "ambient", "FENNEC_API_BASE_URL": "https://ambient.invalid", "FENNEC_API_KEY": "ignored-test-token"},
    )
    assert selected.model == "selected"
    assert selected.endpoint == "http://127.0.0.1:8765/v1/chat/completions"
    assert selected.api_key is None


def test_user_environment_selects_model_endpoint_and_custom_key_variable():
    selected = ModelConfig.from_environment(environ={
        "FENNEC_MODEL": "chosen", "FENNEC_API_BASE_URL": "https://configured.invalid/v1/",
        "FENNEC_AUTH": "bearer", "MY_LLM_TOKEN": "unit-test-token",
    }, api_key_env="MY_LLM_TOKEN")
    assert selected.model == "chosen"
    assert selected.api_key == "unit-test-token"
    assert selected.endpoint.endswith("/v1/chat/completions")
    assert "unit-test-token" not in repr(selected)


@pytest.mark.parametrize("url", [
    "", "provider.invalid/v1", "file:///data", "ftp://configured.invalid", "https://",
    "https://user:password@configured.invalid/v1", "https://user@configured.invalid",
    "https://configured.invalid?key=value", "https://configured.invalid/#fragment",
    "https://configured.invalid:invalid", "https://configured.invalid:0", "https://configured.invalid:99999",
    "https://configured.invalid/space path", "https://configured.invalid/\nheader",
])
def test_invalid_or_credential_bearing_urls_rejected(url):
    with pytest.raises(ConfigurationError):
        config(api_base_url=url)


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 601])
def test_invalid_timeouts_rejected(timeout):
    with pytest.raises(ConfigurationError):
        config(timeout_seconds=timeout)


@pytest.mark.parametrize("auth,environ", [
    ("bearer", {}), ("unknown", {}), ("bearer", {"FENNEC_API_KEY": "bad\ntoken"}),
])
def test_authentication_configuration_fails_safely(auth, environ):
    with pytest.raises(ConfigurationError):
        ModelConfig.from_environment(model="chosen", api_base_url="https://configured.invalid", auth=auth, environ=environ)


def test_remote_cleartext_bearer_refused_but_loopback_supported():
    with pytest.raises(ConfigurationError, match="HTTPS"):
        config(api_base_url="http://remote.invalid/v1", api_key="unit-test-token")
    for url in ("http://localhost:8765/v1", "http://127.0.0.1:8765/v1", "http://[::1]:8765/v1"):
        assert config(api_base_url=url, api_key="unit-test-token").api_key


def test_runtime_schema_conversion_retains_optional_and_nested_arguments(workspace):
    definitions = {item.name: item for item in ToolRuntime(workspace).tool_definitions}
    patch = tool_schema(definitions["apply_patch"])["function"]["parameters"]
    assert patch["additionalProperties"] is False
    assert patch["required"] == ["path", "expected_sha256", "edits"]
    assert patch["properties"]["edits"]["items"] == {
        "type": "object", "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
        "required": ["old", "new"], "additionalProperties": False,
    }
    command = tool_schema(definitions["run_command"])["function"]["parameters"]
    assert command["properties"]["argv"] == {"type": "array", "items": {"type": "string"}}
    read = tool_schema(definitions["read_file"])["function"]["parameters"]
    assert read["required"] == ["path"]
    assert read["properties"]["start_line"] == {"type": "integer"}


@pytest.mark.parametrize("value_type,wire_type", [(str,"string"),(int,"integer"),(float,"number"),(bool,"boolean"),(list,"array"),(dict,"object")])
def test_generic_tool_argument_types_convert(value_type, wire_type):
    schema = tool_schema(ToolDefinition("test", argument_types={"value": value_type}))
    assert schema["function"]["parameters"]["properties"]["value"]["type"] == wire_type


def test_request_construction_correlates_calls_and_results_without_task_metadata():
    calls = (ToolCall("first", "echo", {"text": "one"}), ToolCall("second", "echo", {"text": "two"}))
    payload = build_payload(request(
        Message("user", "Task"), Message("assistant", tool_calls=calls),
        Message("tool", tool_result=ToolResult("first", "SUCCESS", "one")),
        Message("tool", tool_result=ToolResult("second", "ERROR", error="denied", truncated=True)),
        definitions=(ToolDefinition("echo", argument_types={"text": str}),),
    ), "chosen")
    assert payload["model"] == "chosen"
    assert payload["stream"] is False
    assert payload["tool_choice"] == "auto"
    assert payload["messages"][0] == {"role": "system", "content": "Instructions"}
    assert payload["messages"][2]["tool_calls"][0]["id"] == "first"
    assert json.loads(payload["messages"][2]["tool_calls"][0]["function"]["arguments"]) == {"text": "one"}
    assert payload["messages"][3]["tool_call_id"] == "first"
    feedback = json.loads(payload["messages"][4]["content"])
    assert feedback["status"] == "ERROR" and feedback["truncated"]
    assert "workspace-metadata" not in json.dumps(payload)
    assert "session-metadata" not in json.dumps(payload)


@pytest.mark.parametrize("messages", [
    (Message("tool", tool_result=ToolResult("orphan", "SUCCESS")),),
    (Message("assistant", tool_calls=(ToolCall("missing", "fake"),)),),
    (Message("assistant", tool_calls=(ToolCall("same", "fake"), ToolCall("same", "fake"))),),
])
def test_invalid_history_rejected_without_request(mock_provider, messages):
    transport = mock_provider([])
    response = CompatibleModel(config(), transport).generate(request(*messages))
    assert response.error
    assert transport.calls == []


def test_transport_receives_explicit_endpoint_model_and_optional_auth(mock_provider, provider_response):
    for key in (None, "unit-test-token"):
        transport = mock_provider([provider_response()])
        response = CompatibleModel(config(api_key=key), transport).generate(request())
        assert response.final_answer == "Done."
        sent = transport.calls[0]
        assert sent["url"] == "https://configured.invalid/custom/v1/chat/completions"
        assert sent["payload"]["model"] == "user-chosen-model"
        assert sent["timeout"] == 30
        assert sent["max_bytes"] == 1024 * 1024
        assert ("Authorization" in sent["headers"]) == (key is not None)
        if key:
            assert sent["headers"]["Authorization"] == f"Bearer {key}"
        assert "Authorization" not in json.dumps(sent["payload"])


def test_response_parsing_normalizes_tool_calls_and_discards_nonfinal_preface(provider_response):
    payload = provider_response("I'll inspect the file.", calls=[("call-1", "read_file", {"path": "app.py"})])
    response = parse_response(json.dumps(payload).encode())
    assert response.final_answer is None
    assert response.tool_calls == (ToolCall("call-1", "read_file", {"path": "app.py"}),)


def test_unused_nullable_legacy_field_does_not_break_compatible_responses(provider_response):
    payload = provider_response()
    payload["choices"][0]["message"].update(function_call=None, refusal=None, tool_calls=None)
    assert parse_response(json.dumps(payload).encode()).final_answer == "Done."


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(choices=[]),
    lambda p: p["choices"].append(deepcopy(p["choices"][0])),
    lambda p: p["choices"][0].update(finish_reason="length"),
    lambda p: p["choices"][0].update(finish_reason="content_filter"),
    lambda p: p["choices"][0].update(finish_reason=None),
    lambda p: p["choices"][0]["message"].update(role="user"),
    lambda p: p["choices"][0]["message"].update(content=[]),
    lambda p: p["choices"][0]["message"].update(content=""),
    lambda p: p["choices"][0]["message"].update(refusal="refused"),
    lambda p: p["choices"][0]["message"].update(refusal=False),
    lambda p: p["choices"][0]["message"].update(function_call={"name": "unsupported"}),
    lambda p: p["choices"][0]["message"].update(tool_calls={}),
    lambda p: p.update(error={"message": "private provider message"}),
])
def test_malformed_refused_and_incomplete_responses_fail(provider_response, mutation):
    payload = provider_response()
    mutation(payload)
    response = parse_response(json.dumps(payload).encode())
    assert response.error
    assert response.final_answer is None and response.tool_calls == ()
    assert "private provider message" not in response.error


@pytest.mark.parametrize("change", [
    {"id": ""}, {"id": None}, {"type": "other"}, {"function": None},
    {"function": {"name": "fake", "arguments": {}}},
    {"function": {"name": "fake", "arguments": "[]"}},
    {"function": {"name": "fake", "arguments": "{"}},
    {"function": {"name": "fake", "arguments": '{"path":"a","path":"b"}'}},
    {"function": {"name": "fake", "arguments": '{"value":NaN}'}},
    {"function": {"name": "fake", "arguments": '{"value":1e999}'}},
])
def test_malformed_tool_calls_reject_entire_response(provider_response, change):
    payload = provider_response(None, calls=[("valid", "fake", {}), ("bad", "fake", {})])
    payload["choices"][0]["message"]["tool_calls"][1].update(change)
    response = parse_response(json.dumps(payload).encode())
    assert response.error and response.tool_calls == ()


def test_duplicate_call_ids_are_malformed(provider_response):
    payload = provider_response(None, calls=[("same", "fake", {}), ("same", "fake", {})])
    assert parse_response(json.dumps(payload).encode()).error


@pytest.mark.parametrize("body", [b"not-json", b"\xff", b"[]", b'{"choices":[],"choices":[]}', b'{}'])
def test_invalid_wire_bodies_return_explicit_error(body):
    assert parse_response(body).error


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 429, 500, 503])
def test_provider_http_errors_hide_body_and_never_retry(mock_provider, status):
    transport = mock_provider([HttpResponse(status, b'unit-test-token private body')])
    response = CompatibleModel(config(api_key="unit-test-token"), transport).generate(request())
    assert response.error and f"HTTP {status}" in response.error
    assert "unit-test-token" not in response.error and "private body" not in response.error
    assert len(transport.calls) == 1


@pytest.mark.parametrize("error", [TimeoutError("unit-test-token"), socket.timeout("unit-test-token"), ConnectionError("unit-test-token"), OSError("unit-test-token"), RuntimeError("unit-test-token")])
def test_connection_timeout_and_transport_errors_are_sanitized(mock_provider, error):
    transport = mock_provider([error])
    response = CompatibleModel(config(api_key="unit-test-token"), transport).generate(request())
    assert response.error and "unit-test-token" not in response.error
    assert len(transport.calls) == 1


def test_transport_response_size_limit(mock_provider):
    response = CompatibleModel(config(max_response_bytes=128), mock_provider([HttpResponse(200, b"x" * 129)])).generate(request())
    assert "size limit" in response.error


def test_http_transport_uses_post_timeout_no_redirect_and_closes(monkeypatch, provider_response):
    observed = {}
    raw = json.dumps(provider_response()).encode()

    class Connection:
        debuglevel = 1

        def __init__(self, host, port, *, timeout):
            observed.update(host=host, port=port, timeout=timeout)

        def request(self, method, path, *, body, headers):
            assert self.debuglevel == 0
            observed.update(method=method, path=path, body=body, headers=headers)

        def getresponse(self):
            return type("Response", (), {"status": 200, "read": lambda self, limit: raw})()

        def close(self):
            observed["closed"] = True

    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    result = HttpTransport().post("https://configured.invalid/v1/chat/completions", {}, b"{}", timeout=7, max_bytes=1024)
    assert result.body == raw
    assert observed == {"host": "configured.invalid", "port": None, "timeout": 7, "method": "POST",
                        "path": "/v1/chat/completions", "body": b"{}", "headers": {}, "closed": True}


def test_http_transport_never_reads_redirect_or_error_bodies(monkeypatch):
    observed = []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            observed.append("request")

        def getresponse(self):
            def forbidden(*args):
                pytest.fail("Provider error body must not be read")
            return type("Response", (), {"status": 302, "read": forbidden})()

        def close(self):
            observed.append("close")

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    response = HttpTransport().post("http://localhost:8765/chat/completions", {}, b"{}", timeout=1, max_bytes=128)
    assert response.status == 302 and response.body == b""
    assert observed == ["request", "close"]


def test_http_capture_limit_is_bounded_and_connection_closed(monkeypatch):
    observed = []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            def read(response, limit):
                observed.append(limit)
                return b"x" * limit
            return type("Response", (), {"status": 200, "read": read})()

        def close(self):
            observed.append("closed")

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    with pytest.raises(ValueError, match="limit"):
        HttpTransport().post("http://localhost/chat/completions", {}, b"{}", timeout=1, max_bytes=128)
    assert observed == [129, "closed"]
