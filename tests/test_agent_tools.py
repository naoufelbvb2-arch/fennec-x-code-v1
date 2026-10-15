import hashlib

import pytest

from sca.agent import AgentCore
from sca.contracts import AgentTask, ModelResponse, ToolCall, ToolDefinition, ToolResult
from sca.model import FakeModel
from sca.tools import FakeToolExecutor, ToolRuntime


def test_fake_model_operates_real_read_patch_and_test_tools(workspace):
    before = "def add(a, b):\n    return a - b\n"
    (workspace.root / "app.py").write_bytes(before.encode("utf-8"))
    (workspace.root / "test_app.py").write_text(
        "from app import add\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8",
    )
    calls = (
        ToolCall("read", "read_file", {"path": "app.py"}),
        ToolCall("patch", "apply_patch", {
            "path": "app.py", "expected_sha256": hashlib.sha256(before.encode()).hexdigest(),
            "edits": [{"old": "return a - b", "new": "return a + b"}],
        }),
        ToolCall("test", "run_command", {"argv": ["python", "-m", "pytest", "-q"]}),
    )
    model = FakeModel([
        *(ModelResponse(tool_calls=(requested,)) for requested in calls),
        ModelResponse(final_answer="Updated app.py and ran its test."),
    ])
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    task = AgentTask("Fix add and run its test", str(workspace.root), "real-tools")

    result = AgentCore(model, runtime).run(task)

    assert result.status == "COMPLETED", result.errors
    assert result.model_rounds == 4
    assert result.changed_files == ("app.py",)
    assert len(result.tests_run) == 1
    assert result.tests_run[0].endswith("exit 0")
    assert [item.call_id for item in result.tool_results] == ["read", "patch", "test"]
    assert all(item.status == "SUCCESS" for item in result.tool_results)
    assert "1 passed" in result.tool_results[-1].output
    assert runtime.session.task == task
    assert runtime.session.tool_results == list(result.tool_results)
    for number in range(1, 4):
        feedback = model.requests[number].messages[-1].tool_result
        assert feedback.call_id == calls[number - 1].call_id
    assert "fake tools" not in model.requests[0].instructions


def test_task_root_mismatch_stops_before_model_invocation(workspace, tmp_path):
    model = FakeModel([ModelResponse(final_answer="Should not run")])
    result = AgentCore(model, ToolRuntime(workspace)).run(AgentTask("Task", str(tmp_path), "wrong-root"))
    assert result.status == "ERROR"
    assert result.model_rounds == 0
    assert "does not match" in result.errors[0]
    assert model.requests == []


def test_final_round_cannot_write_or_request_authorization(workspace):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"hello")
    authorizations = []
    runtime = ToolRuntime(workspace, authorize=lambda requested: authorizations.append(requested) or True)
    requested = ToolCall("patch", "apply_patch", {
        "path": "sample.txt", "expected_sha256": hashlib.sha256(b"hello").hexdigest(),
        "edits": [{"old": "hello", "new": "changed"}],
    })
    model = FakeModel([ModelResponse(tool_calls=(requested,))])
    task = AgentTask("Task", str(workspace.root), "last-round")
    result = AgentCore(model, runtime, max_model_rounds=1).run(task)
    assert result.status == "LIMIT_REACHED"
    assert result.tool_results == result.changed_files == ()
    assert runtime.session.tool_results == []
    assert authorizations == []
    assert target.read_bytes() == b"hello"


def test_opt_in_feedback_preserves_error_and_never_claims_success(workspace):
    model = FakeModel([
        ModelResponse(tool_calls=(ToolCall("missing", "read_file", {"path": "missing.txt"}),)),
        ModelResponse(final_answer="The file is absent."),
    ])
    runtime = ToolRuntime(workspace)
    task = AgentTask("Inspect", str(workspace.root), "feedback")
    result = AgentCore(model, runtime, continue_on_tool_error=True).run(task)
    assert result.status == "ERROR"
    assert len(model.requests) == 2
    assert model.requests[1].messages[-1].tool_result.status == "ERROR"
    assert model.requests[1].messages[-1].tool_result.call_id == "missing"
    assert len(result.errors) == 1
    assert len(runtime.session.tool_results) == 1


def test_executor_exception_remains_fatal_even_with_feedback_enabled():
    executor = FakeToolExecutor([ToolDefinition("fake")], [RuntimeError("uncertain outcome")])
    model = FakeModel([
        ModelResponse(tool_calls=(ToolCall("once", "fake"),)),
        ModelResponse(final_answer="Must not be reached"),
    ])
    result = AgentCore(model, executor, continue_on_tool_error=True).run(AgentTask("Task", "metadata", "session"))
    assert result.status == "ERROR"
    assert len(executor.calls) == len(model.requests) == 1


def test_failed_test_evidence_survives_agent_error(workspace):
    (workspace.root / "test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    model = FakeModel([ModelResponse(tool_calls=(ToolCall("test", "run_command", {"argv": ["python", "-m", "pytest", "-q"]}),))])
    result = AgentCore(model, runtime).run(AgentTask("Test", str(workspace.root), "failure"))
    assert result.status == "ERROR"
    assert "status 1" in result.tests_run[0]
    assert len(model.requests) == 1


@pytest.mark.parametrize("value", [1, "yes", None])
def test_feedback_configuration_is_explicit_boolean(value):
    with pytest.raises(ValueError, match="boolean"):
        AgentCore(FakeModel([]), FakeToolExecutor(), continue_on_tool_error=value)
