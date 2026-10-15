import pytest

from sca.agent import AgentCore
from sca.contracts import AgentTask, ToolDefinition
from sca.model import FakeModel
from sca.tools import FakeToolExecutor


@pytest.mark.parametrize("field", ["instruction", "workspace_root", "session_id"])
@pytest.mark.parametrize("invalid", ["", "   ", None, 123])
def test_task_requires_nonempty_metadata(field, invalid) -> None:
    values = {"instruction": "Task", "workspace_root": "metadata-only", "session_id": "s1"}
    values[field] = invalid
    with pytest.raises(ValueError, match=field):
        AgentTask(**values)


def test_duplicate_tool_names_rejected_at_configuration_boundary() -> None:
    executor = FakeToolExecutor([ToolDefinition("echo"), ToolDefinition("echo")])
    with pytest.raises(ValueError, match="tool names must be unique"):
        AgentCore(FakeModel([]), executor)


@pytest.mark.parametrize("arguments", [{"count": True}, {"count": "1"}, {}, {"count": 1, "extra": 2}])
def test_fake_argument_schema_requires_exact_names_and_types(arguments) -> None:
    definition = ToolDefinition("count", argument_types={"count": int})
    with pytest.raises(ValueError, match="invalid argument"):
        definition.validate_arguments(arguments)


def test_fake_argument_schema_accepts_exact_type() -> None:
    ToolDefinition("count", argument_types={"count": int}).validate_arguments({"count": 1})


@pytest.mark.parametrize("schema", [{"text": "str"}, {"": str}, []])
def test_invalid_fake_tool_schema_rejected(schema) -> None:
    with pytest.raises(ValueError):
        ToolDefinition("echo", argument_types=schema)
