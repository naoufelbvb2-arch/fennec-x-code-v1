"""Model Gateway protocol and deterministic, entirely local fake."""

from collections.abc import Sequence
from copy import deepcopy
from typing import Protocol, cast

from sca.contracts import ModelRequest, ModelResponse


class ModelGateway(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...


class FakeModel:
    """Consume one scripted item per invocation and record request snapshots.

    Exception items simulate gateway failure. Other non-response objects are
    intentionally allowed for malformed-response tests. Exhaustion is an error;
    the fake never invents a successful answer or repeats the last response.
    """

    def __init__(self, responses: Sequence[object]) -> None:
        self._responses = iter(deepcopy(responses))
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(deepcopy(request))
        try:
            item = next(self._responses)
        except StopIteration:
            raise RuntimeError("FakeModel script exhausted") from None
        if isinstance(item, Exception):
            raise item
        return cast(ModelResponse, item)
