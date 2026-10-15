"""Shared monotonic task deadline, with no tool or provider dependencies."""

from collections.abc import Callable
import math
from time import monotonic


class TaskLimitExceeded(TimeoutError):
    """No further model requests or tool side effects may be started."""


class TaskBudget:
    def __init__(self, seconds: float = 600, *, clock: Callable[[], float] = monotonic) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("task timeout must be finite and positive")
        self.seconds = seconds
        self._clock = clock
        self._deadline: float | None = None

    def start(self) -> None:
        """Called by Core for each sequential task, before workspace setup."""
        self._deadline = self._clock() + self.seconds

    def remaining(self) -> float:
        remaining = self.seconds if self._deadline is None else self._deadline - self._clock()
        if remaining <= 0:
            raise TaskLimitExceeded("Whole-task time limit reached; no further work started.")
        return remaining

    def check(self) -> None:
        self.remaining()

    def timeout(self, operation_seconds: float) -> float:
        return min(operation_seconds, self.remaining())
