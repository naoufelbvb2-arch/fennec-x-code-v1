"""Provider-independent I1 contracts and explicit boundary validation.

Task statuses: COMPLETED (loop finished), ERROR, LIMIT_REACHED.
Tool statuses: SUCCESS, ERROR. Completion alone verifies no project changes.
Mutable payloads are copied at gateway/executor boundaries by AgentCore.
"""

from dataclasses import dataclass, field
from typing import Literal


def require_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


@dataclass(frozen=True)
class AgentTask:
    instruction: str
    workspace_root: str
    session_id: str

    def __post_init__(self) -> None:
        for label in ("instruction", "workspace_root", "session_id"):
            require_text(getattr(self, label), label)
        # workspace_root is metadata only: I1 never resolves or reads it.


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool_name: str
    arguments: dict[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        require_text(self.call_id, "call_id")
        require_text(self.tool_name, "tool_name")
        if not isinstance(self.arguments, dict):
            raise ValueError("arguments must be a dictionary")


@dataclass(frozen=True)
class ToolDefinition:
    """Minimal fake-tool schema: all named arguments are required, no extras.

    Types are exact Python types (so bool does not satisfy int). This is an
    I1 test contract, not a general schema engine or real tool registry.
    """

    name: str
    description: str = ""
    argument_types: dict[str, type] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.name, "tool name")
        if not isinstance(self.argument_types, dict):
            raise ValueError("argument_types must be a dictionary")
        for name, expected_type in self.argument_types.items():
            require_text(name, "argument name")
            if not isinstance(expected_type, type):
                raise ValueError("argument_types values must be Python types")

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() != self.argument_types.keys():
            raise ValueError(f"invalid arguments for {self.name}: expected {tuple(self.argument_types)}")
        for name, expected_type in self.argument_types.items():
            if type(arguments[name]) is not expected_type:
                raise ValueError(f"invalid argument {name!r}: expected {expected_type.__name__}")


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: Literal["SUCCESS", "ERROR"]
    output: str = ""
    error: str | None = None
    truncated: bool = False

    def validate(self) -> None:
        require_text(self.call_id, "result call_id")
        if self.status not in ("SUCCESS", "ERROR"):
            raise ValueError("invalid tool result status")
        if not isinstance(self.output, str) or type(self.truncated) is not bool:
            raise ValueError("tool result requires string output and boolean truncated")
        if self.status == "ERROR":
            require_text(self.error, "tool error")
        elif self.error is not None:
            raise ValueError("successful tool result cannot contain an error")


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_result: ToolResult | None = None


@dataclass(frozen=True)
class ModelRequest:
    instructions: str
    messages: tuple[Message, ...]
    tool_definitions: tuple[ToolDefinition, ...]
    limits: dict[str, int]
    task: AgentTask


@dataclass(frozen=True)
class ModelResponse:
    """Exactly one non-empty variant is valid; Core validates on receipt.

    Validation is explicit so malformed gateway payloads can be scripted in
    tests and converted into structured failures at the actual boundary.
    """

    final_answer: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    error: str | None = None

    def validate(self) -> None:
        if not isinstance(self.tool_calls, tuple):
            raise ValueError("tool_calls must be a tuple")
        variants = (self.final_answer is not None, bool(self.tool_calls), self.error is not None)
        if sum(variants) != 1:
            raise ValueError("model response must contain exactly one of final_answer, tool_calls, error")
        if self.final_answer is not None:
            require_text(self.final_answer, "final_answer")
        if self.error is not None:
            require_text(self.error, "model error")
        for call in self.tool_calls:
            if not isinstance(call, ToolCall):
                raise ValueError("tool_calls must contain ToolCall objects")
            call.validate()


@dataclass(frozen=True)
class TaskResult:
    status: Literal["COMPLETED", "ERROR", "LIMIT_REACHED"]
    summary: str
    changed_files: tuple[str, ...] = ()
    tests_run: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    model_rounds: int = 0
    tool_results: tuple[ToolResult, ...] = ()
