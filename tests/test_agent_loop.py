"""I1 acceptance tests: all tasks, responses and tool outcomes stay in memory."""

import builtins
import io
import os
import socket
import subprocess

import pytest

from sca.agent import AgentCore
from sca.contracts import AgentTask, ModelResponse, ToolCall, ToolDefinition, ToolResult
from sca.model import FakeModel
from sca.tools import FakeToolExecutor


TASK = AgentTask("Explain this fake task.", "nonexistent-workspace-metadata", "session-1")
ECHO = ToolDefinition("echo", "A fake text tool", {"text": str})


def call(call_id: str = "c1", text: str = "hello") -> ToolCall:
    return ToolCall(call_id, "echo", {"text": text})


def test_immediate_final_answer() -> None:
    model = FakeModel([ModelResponse(final_answer="Done.")])
    executor = FakeToolExecutor()

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "COMPLETED"
    assert result.summary == "Done."
    assert result.model_rounds == len(model.requests) == 1
    assert executor.calls == []
    assert result.tool_results == result.errors == ()
    assert result.changed_files == result.tests_run == ()
    request = model.requests[0]
    assert request.task == TASK
    assert request.messages[0].role == "user"
    assert request.messages[0].content == TASK.instruction
    assert request.instructions
    assert request.limits == {"max_model_rounds": 25}


def test_one_tool_result_visible_in_next_model_request() -> None:
    requested = call()
    outcome = ToolResult("c1", "SUCCESS", output="hello")
    model = FakeModel([
        ModelResponse(tool_calls=(requested,)),
        ModelResponse(final_answer="Received hello."),
    ])
    executor = FakeToolExecutor([ECHO], [outcome])

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "COMPLETED"
    assert result.model_rounds == len(model.requests) == 2
    assert executor.calls == [requested]
    assert result.tool_results == (outcome,)
    assert [message.role for message in model.requests[1].messages] == ["user", "assistant", "tool"]
    assert model.requests[1].messages[1].tool_calls == (requested,)
    assert model.requests[1].messages[2].tool_result == outcome
    assert model.requests[1].tool_definitions == (ECHO,)
    assert len(model.requests[0].messages) == 1


def test_multiple_tools_execute_sequentially_before_next_model_round() -> None:
    events: list[str] = []

    class RecordingModel(FakeModel):
        def generate(self, request):
            events.append("model")
            return super().generate(request)

    class RecordingExecutor(FakeToolExecutor):
        def execute(self, requested):
            events.append(requested.call_id)
            return super().execute(requested)

    calls = (call("first", "one"), call("second", "two"))
    outcomes = (ToolResult("first", "SUCCESS", "one"), ToolResult("second", "SUCCESS", "two"))
    model = RecordingModel([ModelResponse(tool_calls=calls), ModelResponse(final_answer="Done.")])
    executor = RecordingExecutor([ECHO], outcomes)

    result = AgentCore(model, executor).run(TASK)

    assert events == ["model", "first", "second", "model"]
    assert result.status == "COMPLETED"
    assert executor.calls == list(calls)
    assert result.tool_results == outcomes
    assert tuple(message.tool_result for message in model.requests[1].messages[2:]) == outcomes


@pytest.mark.parametrize("bad_call", [
    ToolCall("c1", "unknown", {}),
    ToolCall("c1", "echo", {}),
    ToolCall("c1", "echo", {"text": 7}),
    ToolCall("c1", "echo", {"text": "hello", "extra": True}),
    ToolCall("c1", "echo", ["hello"]),
    ToolCall("", "echo", {"text": "hello"}),
    ToolCall(None, "echo", {"text": "hello"}),
    ToolCall("c1", "", {}),
])
def test_invalid_call_rejected_without_executor_invocation(bad_call) -> None:
    model = FakeModel([ModelResponse(tool_calls=(bad_call,))])
    executor = FakeToolExecutor([ECHO])

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "ERROR"
    assert result.errors
    assert len(model.requests) == 1
    assert executor.calls == []
    assert result.tool_results == ()


@pytest.mark.parametrize("bad_tail", [call("c1"), ToolCall("c2", "unknown", {})])
def test_entire_batch_validated_before_any_execution(bad_tail) -> None:
    model = FakeModel([ModelResponse(tool_calls=(call(), bad_tail))])
    executor = FakeToolExecutor([ECHO])

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "ERROR"
    assert executor.calls == []


def test_duplicate_id_across_rounds_never_reexecutes_tool() -> None:
    model = FakeModel([ModelResponse(tool_calls=(call(),)), ModelResponse(tool_calls=(call(),))])
    executor = FakeToolExecutor([ECHO], [ToolResult("c1", "SUCCESS", "hello")])

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "ERROR"
    assert "duplicate call_id" in result.errors[0]
    assert executor.calls == [call()]
    assert len(result.tool_results) == 1


@pytest.mark.parametrize("response, expected_error", [
    (RuntimeError("gateway unavailable"), "Gateway failure"),
    (ModelResponse(error="provider rejected request"), "Model error"),
    (ModelResponse(), "Malformed response"),
    (ModelResponse(final_answer="Done", error="failed"), "Malformed response"),
    (ModelResponse(final_answer="Done", tool_calls=(call(),)), "Malformed response"),
    (ModelResponse(tool_calls=(call(),), error="failed"), "Malformed response"),
    (ModelResponse(final_answer=" "), "Malformed response"),
    (ModelResponse(final_answer=123), "Malformed response"),
    (ModelResponse(error=""), "Malformed response"),
    (ModelResponse(tool_calls=None), "Malformed response"),
    (ModelResponse(tool_calls=[call()]), "Malformed response"),
    (ModelResponse(tool_calls=("not a ToolCall",)), "Malformed response"),
    ({"final_answer": "unparsed provider data"}, "Malformed response"),
    (None, "Malformed response"),
])
def test_gateway_error_and_malformed_response_fail_explicitly(response, expected_error) -> None:
    model = FakeModel([response, ModelResponse(final_answer="Must not be reached.")])
    executor = FakeToolExecutor([ECHO])

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "ERROR"
    assert expected_error in result.errors[0]
    assert len(model.requests) == 1
    assert executor.calls == []
    assert result.changed_files == result.tests_run == ()


@pytest.mark.parametrize("outcome", [
    ToolResult("c1", "ERROR", error="fake tool failed"),
    RuntimeError("outcome uncertain"),
    ToolResult("wrong-id", "SUCCESS", "hello"),
    ToolResult("c1", "SUCCESS", error="contradictory"),
    ToolResult("c1", "ERROR"),
    ToolResult("c1", "other"),
    ToolResult("c1", "SUCCESS", output=42),
    ToolResult("c1", "SUCCESS", truncated="yes"),
    None,
])
def test_executor_errors_stop_without_retry_or_later_batch_execution(outcome) -> None:
    model = FakeModel([
        ModelResponse(tool_calls=(call(), call("c2"))),
        ModelResponse(final_answer="Must not become success."),
    ])
    executor = FakeToolExecutor([ECHO], [outcome, ToolResult("c2", "SUCCESS")])

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "ERROR"
    assert result.errors
    assert executor.calls == [call()]
    assert len(model.requests) == 1
    assert len(result.tool_results) == 1
    assert result.tool_results[0].call_id == "c1"
    assert result.tool_results[0].status == "ERROR"


def test_gateway_failure_after_execution_preserves_result_without_retry() -> None:
    model = FakeModel([
        ModelResponse(tool_calls=(call(),)), RuntimeError("connection lost"),
        ModelResponse(final_answer="Must not be reached."),
    ])
    outcome = ToolResult("c1", "SUCCESS", "hello")
    executor = FakeToolExecutor([ECHO], [outcome])

    result = AgentCore(model, executor).run(TASK)

    assert result.status == "ERROR"
    assert result.model_rounds == len(model.requests) == 2
    assert executor.calls == [call()]
    assert result.tool_results == (outcome,)


def test_maximum_model_rounds_stops_loop() -> None:
    model = FakeModel([
        ModelResponse(tool_calls=(call("c1"),)),
        ModelResponse(tool_calls=(call("c2"),)),
        ModelResponse(final_answer="Beyond limit."),
    ])
    outcomes = [ToolResult("c1", "SUCCESS"), ToolResult("c2", "SUCCESS")]
    executor = FakeToolExecutor([ECHO], outcomes)

    result = AgentCore(model, executor, max_model_rounds=2).run(TASK)

    assert result.status == "LIMIT_REACHED"
    assert result.model_rounds == len(model.requests) == 2
    # I2 safety change: the final round cannot execute an unreviewable batch.
    assert executor.calls == [call("c1")]
    assert result.tool_results == tuple(outcomes[:1])
    assert result.errors
    assert model.requests[1].limits == {"max_model_rounds": 2}


def test_final_answer_on_last_allowed_round_completes() -> None:
    result = AgentCore(
        FakeModel([ModelResponse(final_answer="Done")]), FakeToolExecutor(), max_model_rounds=1,
    ).run(TASK)
    assert result.status == "COMPLETED"


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_invalid_round_configuration_rejected(limit) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        AgentCore(FakeModel([]), FakeToolExecutor(), max_model_rounds=limit)


def test_final_answer_cannot_fabricate_execution_evidence() -> None:
    model = FakeModel([ModelResponse(final_answer="Changed app.py; all tests passed.")])
    result = AgentCore(model, FakeToolExecutor()).run(TASK)
    assert result.status == "COMPLETED"  # Loop completion, not verification of model text.
    assert result.changed_files == result.tests_run == result.tool_results == ()


def test_new_run_has_fresh_session_context_and_call_ids() -> None:
    model = FakeModel([
        ModelResponse(tool_calls=(call(),)), ModelResponse(final_answer="First"),
        ModelResponse(tool_calls=(call(),)), ModelResponse(final_answer="Second"),
    ])
    executor = FakeToolExecutor([ECHO], [ToolResult("c1", "SUCCESS"), ToolResult("c1", "SUCCESS")])
    agent = AgentCore(model, executor)
    first = agent.run(TASK)
    second_task = AgentTask("Another task", "another-metadata-root", "session-2")
    second = agent.run(second_task)
    assert first.status == second.status == "COMPLETED"
    assert first.model_rounds == second.model_rounds == 2
    assert len(first.tool_results) == len(second.tool_results) == 1
    assert len(model.requests[2].messages) == 1
    assert model.requests[2].task == second_task


def test_loop_needs_no_files_network_or_subprocesses(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("I1 must stay in memory")

    model = FakeModel([ModelResponse(tool_calls=(call(),)), ModelResponse(final_answer="Done")])
    executor = FakeToolExecutor([ECHO], [ToolResult("c1", "SUCCESS", "hello")])
    agent = AgentCore(model, executor)
    with monkeypatch.context() as guards:
        for target, name in (
            (builtins, "open"), (io, "open"), (os, "open"), (os, "system"),
            (socket, "socket"), (socket, "create_connection"),
            (subprocess, "Popen"), (subprocess, "run"),
        ):
            guards.setattr(target, name, forbidden)
        result = agent.run(TASK)
    assert result.status == "COMPLETED"
