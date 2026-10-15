import hashlib
import io
import json

import pytest

from sca import cli
from sca.provider import HttpResponse


def arguments(workspace, *extra):
    return ["--workspace", str(workspace.root), "--task", "Inspect and fix the project",
            "--model", "user-selected-model", "--api-base-url", "https://configured.invalid/v1", *extra]


def run(args, transport, *, environ=None, answers=()):
    output, errors = io.StringIO(), io.StringIO()
    approved = iter(answers)

    def read(prompt):
        try:
            return next(approved)
        except StopIteration:
            raise EOFError from None

    status = cli.main(args, transport=transport, environ={} if environ is None else environ,
                      input_fn=read, stdout=output, stderr=errors)
    return status, output.getvalue(), errors.getvalue()


def test_no_config_stops_before_workspace_or_network(monkeypatch, mock_provider):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing model configuration must stop before workspace initialization")

    monkeypatch.setattr(cli, "Workspace", forbidden)
    transport = mock_provider([])
    status, output, error = run([], transport)
    assert status == 2
    assert "LLM configuration missing" in error
    assert "--model" in error and "--api-base-url" in error
    assert transport.calls == []


@pytest.mark.parametrize("extra", [
    ["--max-model-rounds", "0"], ["--max-model-rounds", "wrong"],
    ["--model-timeout", "0"], ["--model-timeout", "nan"], ["--command-timeout", "inf"],
    ["--command-timeout", "-1"], ["--auth", "unsupported"], ["--auth", "bearer"],
    ["--api-base-url", "not-a-url"], ["--model", ""], ["--task", "   "],
    ["--workspace", ""], ["--unknown", "pasted-private-value"],
])
def test_argument_validation_never_sends_provider_request(workspace, mock_provider, extra):
    transport = mock_provider([])
    status, output, error = run(arguments(workspace, *extra), transport)
    assert status == 2
    assert "Configuration error" in error
    assert "pasted-private-value" not in output + error
    assert transport.calls == []


def test_cli_does_not_accept_api_keys_as_arguments(workspace, mock_provider):
    status, output, error = run(arguments(workspace, "--api-key", "pasted-private-value"), mock_provider([]))
    assert status == 2
    assert "pasted-private-value" not in output + error
    assert "environment variables" in error


def test_help_describes_explicit_configuration_and_does_not_call_provider(capsys):
    assert cli.main(["--help"], environ={}) == 0
    help_text = capsys.readouterr().out
    assert "--api-base-url" in help_text and "--api-key-env" in help_text
    assert "--trusted-project" in help_text


def test_read_activity_and_call_id_visible_without_permission_prompt(workspace, mock_provider, provider_response):
    (workspace.root / "sample.txt").write_bytes(b"hello\n")
    transport = mock_provider([
        provider_response(None, calls=[("read-1", "read_file", {"path": "sample.txt"})]),
        provider_response("Inspected the file."),
    ])
    status, output, error = run(arguments(workspace), transport)
    assert status == 0 and error == ""
    assert "Tool call: read_file (read-1)" in output
    assert "Tool result: SUCCESS (read-1)" in output
    assert "hello" in output and '"status": "COMPLETED"' in output
    assert "Authorization required" not in output
    feedback = transport.calls[1]["payload"]["messages"][-1]
    assert feedback["role"] == "tool" and feedback["tool_call_id"] == "read-1"
    assert json.loads(feedback["content"])["call_id"] == "read-1"


@pytest.mark.parametrize("answer,allowed", [("",False),("no",False),("true",False),("yes",True),("y",True),(" YES ",True)])
def test_write_requires_explicit_per_call_approval(workspace, mock_provider, provider_response, answer, allowed):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"before\n")
    patch = {"path": "sample.txt", "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
             "edits": [{"old": "before", "new": "after"}]}
    transport = mock_provider([
        provider_response(None, calls=[("patch-1", "apply_patch", patch)]), provider_response("Done."),
    ])
    status, output, error = run(arguments(workspace), transport, answers=[answer])
    assert error == ""
    assert status == (0 if allowed else 1)
    assert target.read_bytes() == (b"after\n" if allowed else b"before\n")
    assert "Authorization required: apply_patch" in output
    assert '"old": "before"' in output and '"new": "after"' in output
    assert len(transport.calls) == (2 if allowed else 1)
    assert ("Approved." if allowed else "Denied.") in output


def test_eof_denies_sensitive_operation(workspace, mock_provider, provider_response):
    transport = mock_provider([provider_response(None, calls=[("command", "run_command", {"argv": ["python", "--version"]})])])
    status, output, error = run(arguments(workspace, "--trusted-project"), transport)
    assert status == 1 and "Denied." in output
    assert "authorization denied" in output


def test_approval_is_not_reused_for_next_sensitive_call(workspace, mock_provider, provider_response):
    transport = mock_provider([provider_response(None, calls=[
        ("first", "run_command", {"argv": ["python", "--version"]}),
        ("second", "run_command", {"argv": ["python", "--version"]}),
    ])])
    status, output, error = run(arguments(workspace, "--trusted-project"), transport, answers=["yes", "no"])
    assert status == 1
    assert output.count("Approve this one operation?") == 2
    assert "Tool result: SUCCESS (first)" in output and "Tool result: ERROR (second)" in output


def test_command_approval_does_not_implicitly_establish_project_trust(workspace, mock_provider, provider_response):
    transport = mock_provider([provider_response(None, calls=[("command", "run_command", {"argv": ["python", "--version"]})])])
    status, output, error = run(arguments(workspace), transport, answers=["yes"])
    assert status == 1 and "trusted_project=True" in output


def test_cli_adapter_agent_real_tools_integration(workspace, mock_provider, provider_response):
    before = b"def add(a, b):\n    return a - b\n"
    (workspace.root / "app.py").write_bytes(before)
    (workspace.root / "test_app.py").write_bytes(b"from app import add\ndef test_add():\n    assert add(2, 3) == 5\n")
    patch = {"path": "app.py", "expected_sha256": hashlib.sha256(before).hexdigest(),
             "edits": [{"old": "return a - b", "new": "return a + b"}]}
    transport = mock_provider([
        provider_response(None, calls=[("read", "read_file", {"path": "app.py"})]),
        provider_response(None, calls=[("patch", "apply_patch", patch)]),
        provider_response(None, calls=[("tests", "run_command", {"argv": ["python", "-m", "pytest", "-q"]})]),
        provider_response("Updated app.py and ran its test."),
    ])
    status, output, error = run(arguments(workspace, "--trusted-project"), transport, answers=["yes", "yes"])
    assert status == 0 and error == ""
    assert b"return a + b" in (workspace.root / "app.py").read_bytes()
    assert "1 passed" in output and '"changed_files": [' in output
    assert "python -m pytest -q: exit 0" in output
    assert len(transport.calls) == 4
    assert [item["payload"]["messages"][-1].get("tool_call_id") for item in transport.calls[1:]] == ["read", "patch", "tests"]
    assert output.count("Authorization required") == 2


def test_provider_failure_is_visible_without_credentials_or_retries(workspace, mock_provider):
    secret = "unit-test-token"
    transport = mock_provider([HttpResponse(401, secret.encode())])
    status, output, error = run(arguments(workspace, "--auth", "bearer"), transport, environ={"FENNEC_API_KEY": secret})
    assert status == 1 and '"status": "ERROR"' in output
    assert "authentication failed" in output
    assert secret not in output + error
    assert len(transport.calls) == 1


def test_final_text_redacts_configured_key(workspace, mock_provider, provider_response):
    secret = "unit-test-token"
    transport = mock_provider([provider_response(f"Never log {secret}.")])
    status, output, error = run(arguments(workspace, "--auth", "bearer"), transport, environ={"FENNEC_API_KEY": secret})
    assert status == 0
    assert secret not in output + error and "[REDACTED]" in output


def test_console_escapes_terminal_and_bidi_controls():
    stream = io.StringIO()
    cli.Console(stream, "unit-test-token").write("unit-test-token\x1b[2J\rspoof\u202e")
    output = stream.getvalue()
    assert "unit-test-token" not in output
    assert "\x1b" not in output and "\r" not in output and "\u202e" not in output
    assert "\\u001b" in output and "\\u202e" in output


def test_limit_exit_code_does_not_execute_last_round_tool(workspace, mock_provider, provider_response):
    transport = mock_provider([provider_response(None, calls=[("list", "list_files", {})])])
    status, output, error = run(arguments(workspace, "--max-model-rounds", "1"), transport)
    assert status == 3 and '"status": "LIMIT_REACHED"' in output
    assert "Tool call:" not in output


def test_unknown_provider_tool_does_not_reach_runtime(workspace, mock_provider, provider_response):
    transport = mock_provider([provider_response(None, calls=[("unknown", "shell", {"command": "unsafe"})])])
    status, output, error = run(arguments(workspace), transport)
    assert status == 1 and "unknown tool" in output
    assert "Tool call:" not in output


def test_cli_keyboard_interrupt_exits_without_retry(workspace, mock_provider):
    transport = mock_provider([])

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    transport.post = interrupted
    status, output, error = run(arguments(workspace), transport)
    assert status == 130
    assert "earlier workspace changes are retained" in error
