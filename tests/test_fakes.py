import pytest

from sca.agent import AgentCore
from sca.contracts import AgentTask, ModelResponse, ToolCall, ToolDefinition, ToolResult
from sca.model import FakeModel
from sca.tools import FakeToolExecutor


TASK = AgentTask("Task", "metadata-only", "session")


def test_exhausted_model_script_fails_instead_of_inventing_success() -> None:
    model = FakeModel([])
    result = AgentCore(model, FakeToolExecutor()).run(TASK)
    assert result.status == "ERROR"
    assert "FakeModel script exhausted" in result.errors[0]
    assert len(model.requests) == 1


def test_exhausted_executor_script_fails_and_records_one_attempt() -> None:
    requested = ToolCall("c1", "fake")
    executor = FakeToolExecutor([ToolDefinition("fake")])
    result = AgentCore(FakeModel([ModelResponse(tool_calls=(requested,))]), executor).run(TASK)
    assert result.status == "ERROR"
    assert "FakeToolExecutor script exhausted" in result.errors[0]
    assert executor.calls == [requested]
    assert result.tool_results[0].call_id == "c1"


def test_script_and_request_snapshots_do_not_alias_mutable_call_arguments() -> None:
    requested = ToolCall("c1", "echo", {"text": "original"})
    model = FakeModel([ModelResponse(tool_calls=(requested,)), ModelResponse(final_answer="Done")])
    definition = ToolDefinition("echo", argument_types={"text": str})
    executor = FakeToolExecutor([definition], [ToolResult("c1", "SUCCESS", "original")])
    requested.arguments["text"] = "changed after scripting"

    AgentCore(model, executor).run(TASK)

    assert executor.calls[0].arguments == {"text": "original"}
    executor.calls[0].arguments["text"] = "changed after execution"
    assert model.requests[1].messages[1].tool_calls[0].arguments == {"text": "original"}
    definition.argument_types["text"] = int
    assert model.requests[0].tool_definitions[0].argument_types == {"text": str}


def test_fake_executor_exception_is_not_swallowed_by_the_fake() -> None:
    executor = FakeToolExecutor(results=[RuntimeError("failure")])
    with pytest.raises(RuntimeError, match="failure"):
        executor.execute(ToolCall("c1", "fake"))
    assert len(executor.calls) == 1
