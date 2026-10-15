"""Explicit provider option only; mocked transport, no actual credentials."""

import io
import json

import pytest

from sca.cli import main
from sca.contracts import AgentTask, Message, ModelRequest
from sca.provider import CompatibleModel, ConfigurationError, ModelConfig, build_payload


@pytest.mark.parametrize("endpoint,model", [
    ("https://api.deepseek.com", "deepseek-flash"),
    ("https://configured.invalid/v1", "user-selected-model"),
])
@pytest.mark.parametrize("selected", [False, True])
def test_option_changes_only_explicit_top_level_thinking_field(mock_provider, provider_response, endpoint, model, selected):
    request = ModelRequest("Task", (Message("user", "Inspect"),), (), {}, AgentTask("Inspect", "metadata", "session"))
    config = ModelConfig(model, endpoint, disable_thinking=True) if selected else ModelConfig(model, endpoint)
    transport = mock_provider([provider_response()])

    assert CompatibleModel(config, transport).generate(request).final_answer == "Done."

    sent = transport.calls[0]
    expected = build_payload(request, model)
    if selected:
        expected["thinking"] = {"type": "disabled"}
    assert sent["payload"] == expected
    assert sent["url"] == endpoint.rstrip("/") + "/chat/completions"
    assert "Authorization" not in sent["headers"]
    assert "extra_body" not in sent["payload"]  # This transport sends raw JSON, not SDK kwargs.


@pytest.mark.parametrize("value", [None, 0, 1, "disabled", {}, []])
def test_truthy_or_ambiguous_thinking_configuration_is_rejected(value):
    with pytest.raises(ConfigurationError, match="explicit boolean"):
        ModelConfig("chosen", "https://configured.invalid/v1", disable_thinking=value)


@pytest.mark.parametrize("selected", [False, True])
def test_cli_option_survives_correlated_tool_round_trip(workspace, mock_provider, provider_response, selected):
    (workspace.root / "sample.txt").write_bytes(b"hello\n")
    transport = mock_provider([
        provider_response(None, calls=[("inspect", "read_file", {"path": "sample.txt"})]),
        provider_response("Inspected sample.txt."),
    ])
    argv = ["--workspace", str(workspace.root), "--task", "Inspect sample.txt",
            "--model", "user-selected-model", "--api-base-url", "https://configured.invalid/v1"]
    if selected:
        argv.append("--disable-thinking")
    output, errors = io.StringIO(), io.StringIO()

    assert main(argv, environ={}, transport=transport, stdout=output, stderr=errors) == 0

    assert errors.getvalue() == "" and len(transport.calls) == 2
    for sent in transport.calls:
        assert ("thinking" in sent["payload"]) is selected
        if selected:
            assert sent["payload"]["thinking"] == {"type": "disabled"}
        assert "Authorization" not in sent["headers"]
    history = transport.calls[1]["payload"]["messages"]
    assert history[-2]["tool_calls"][0]["id"] == "inspect"
    assert history[-1]["tool_call_id"] == "inspect"
    assert json.loads(history[-1]["content"])["call_id"] == "inspect"
    assert '"status": "COMPLETED"' in output.getvalue()


def test_disable_thinking_switch_does_not_accept_a_value(workspace, mock_provider):
    transport = mock_provider([])
    errors = io.StringIO()
    result = main(["--disable-thinking", "false"], environ={}, transport=transport,
                  stdout=io.StringIO(), stderr=errors)
    assert result == 2 and transport.calls == []
    assert "Invalid CLI arguments" in errors.getvalue()
