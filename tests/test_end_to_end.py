"""V0 coding/failure gates using real restricted tools and no live provider."""

import hashlib
import json

import pytest

from sca.agent import AgentCore
from sca.contracts import AgentTask, ModelResponse, ToolCall
from sca.model import FakeModel
from sca.provider import CompatibleModel, ModelConfig
from sca.tools import ToolRuntime


@pytest.mark.parametrize("model_kind", ["fake", "mock-provider"])
@pytest.mark.parametrize("ending", ["completed", "test-failure", "permission-denied", "connection-error", "malformed", "cancelled", "command-timeout"])
def test_coding_task_and_failures_preserve_user_changes(workspace, mock_provider, provider_response, model_kind, ending):
    before = b"# Pre-existing user change: retain this comment.\ndef add(a, b):\n    return a - b\n"
    app = workspace.root / "app.py"
    app.write_bytes(before)
    notes = workspace.root / "user-notes.txt"
    notes.write_bytes(b"Unrelated uncommitted user work.\n")
    expected = "999" if ending == "test-failure" else "5"
    test = ("import time\nfrom app import add\ndef test_add():\n"
            + ("    time.sleep(30)\n" if ending == "command-timeout" else "")
            + f"    assert add(2, 3) == {expected}\n").encode()
    (workspace.root / "test_app.py").write_bytes(test)
    first_calls = (
        ToolCall("list", "list_files"),
        ToolCall("read", "read_file", {"path": "app.py"}),
        ToolCall("search", "search_text", {"text": "return a - b", "path": "app.py"}),
    )
    patch = ToolCall("patch", "apply_patch", {
        "path": "app.py", "expected_sha256": hashlib.sha256(before).hexdigest(),
        "edits": [{"old": "return a - b", "new": "return a + b"}],
    })
    command = ToolCall("test", "run_command", {"argv": ["python", "-m", "pytest", "-q"]})
    decisions = [ModelResponse(tool_calls=first_calls), ModelResponse(tool_calls=(patch,)),
                 ModelResponse(tool_calls=(command,)), ModelResponse(final_answer="Patched app.py and observed the test result.")]
    if ending == "connection-error":
        decisions[2] = ModelResponse(error="Provider connection failed; no retry attempted.")
    if ending == "malformed":
        decisions[2] = ModelResponse(final_answer="Ambiguous", tool_calls=(command,))
    permissions = []

    def authorize(call):
        permissions.append(call)
        return ending != "permission-denied"

    runtime = ToolRuntime(workspace, authorize=authorize, trusted_project=True,
                          timeout_seconds=0.3 if ending == "command-timeout" else 10)
    if model_kind == "fake":
        model = FakeModel(decisions)
        original_generate = model.generate

        def generate(request):
            if ending == "cancelled" and len(model.requests) == 2:
                raise KeyboardInterrupt
            return original_generate(request)

        model.generate = generate
        histories = lambda: model.requests
    else:
        responses = [provider_response(None, calls=[(c.call_id, c.tool_name, c.arguments) for c in first_calls]),
                     provider_response(None, calls=[(patch.call_id, patch.tool_name, patch.arguments)]),
                     provider_response(None, calls=[(command.call_id, command.tool_name, command.arguments)]),
                     provider_response("Patched app.py and observed the test result.")]
        if ending == "connection-error":
            responses[2] = ConnectionError("unit-test-token must remain private")
        if ending == "malformed":
            responses[2] = {"choices": [{"message": {"role": "assistant", "tool_calls": "invalid"}, "finish_reason": "tool_calls"}]}
        transport = mock_provider(responses)
        original_post = transport.post

        def post(*args, **kwargs):
            if ending == "cancelled" and len(transport.calls) == 2:
                raise KeyboardInterrupt
            return original_post(*args, **kwargs)

        transport.post = post
        model = CompatibleModel(ModelConfig("user-selected", "https://configured.invalid/v1"), transport)
        histories = lambda: transport.calls

    result = AgentCore(model, runtime).run(AgentTask("Find and fix add; run its test.", str(workspace.root), "e2e"))
    assert notes.read_bytes() == b"Unrelated uncommitted user work.\n"
    assert (workspace.root / "test_app.py").read_bytes() == test
    assert not list(workspace.root.glob(".fennec-*.tmp"))
    assert not list(workspace.root.rglob("*.pyc"))
    assert not (workspace.root / ".pytest_cache").exists()
    assert [item.call_id for item in result.tool_results[:3]] == ["list", "read", "search"]
    assert "app.py" in result.tool_results[0].output
    assert "return a - b" in result.tool_results[1].output
    assert "app.py:3:return a - b" in result.tool_results[2].output.replace("    ", "")
    if ending == "permission-denied":
        assert app.read_bytes() == before and result.changed_files == ()
        assert len(permissions) == 1 and result.tests_run == ()
    else:
        assert app.read_bytes() == before.replace(b"return a - b", b"return a + b")
        assert result.changed_files == ("app.py",)
    if ending == "completed":
        assert result.status == "COMPLETED"
        assert "1 passed" in result.tool_results[-1].output
        assert result.tests_run == ("python -m pytest -q: exit 0",)
        assert [call.tool_name for call in permissions] == ["apply_patch", "run_command"]
        assert len(histories()) == 4
    else:
        assert result.status == ("CANCELLED" if ending == "cancelled" else "ERROR")
        assert result.errors
        assert len(histories()) <= 3
        if ending == "test-failure":
            assert "1 failed" in result.tool_results[-1].output
            assert "status 1" in result.tests_run[0]
        elif ending == "command-timeout":
            assert "timeout" in result.tests_run[0]
        else:
            assert result.tests_run == ()
    assert "unit-test-token" not in json.dumps(result.errors)
    assert len({item.call_id for item in result.tool_results}) == len(result.tool_results)
    # The next model invocation must observe every prior correlated result.
    if model_kind == "fake":
        assert [msg.tool_result.call_id for msg in model.requests[1].messages if msg.role == "tool"] == ["list", "read", "search"]
        if len(model.requests) > 2:
            assert model.requests[2].messages[-1].tool_result.call_id == "patch"
    else:
        assert [msg["tool_call_id"] for msg in transport.calls[1]["payload"]["messages"] if msg["role"] == "tool"] == ["list", "read", "search"]
        if len(transport.calls) > 2:
            assert transport.calls[2]["payload"]["messages"][-1]["tool_call_id"] == "patch"
