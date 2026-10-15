"""The I1 executor boundary and recording fake; no real tools are provided."""

from collections.abc import Sequence
from copy import deepcopy
from typing import Protocol

from sca.contracts import ToolCall, ToolDefinition, ToolResult


class ToolExecutor(Protocol):
    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]: ...

    def execute(self, call: ToolCall) -> ToolResult: ...


class FakeToolExecutor:
    """Record calls in order, returning only explicitly scripted outcomes.

    Core validates calls before invoking execute. This fake performs no file,
    command, network, or Git operations and never retries an execution.
    """

    def __init__(
        self,
        tool_definitions: Sequence[ToolDefinition] = (),
        results: Sequence[ToolResult | Exception] = (),
    ) -> None:
        self._tool_definitions = tuple(deepcopy(tool_definitions))
        self._results = iter(deepcopy(results))
        self.calls: list[ToolCall] = []

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        return deepcopy(self._tool_definitions)

    def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(deepcopy(call))
        try:
            item = next(self._results)
        except StopIteration:
            raise RuntimeError("FakeToolExecutor script exhausted") from None
        if isinstance(item, Exception):
            raise item
        return item
