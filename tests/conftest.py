"""I2 fixtures isolate real operations in pytest temporary projects."""

import itertools
import os
from pathlib import Path

import pytest

from sca.contracts import ToolCall
from sca.tools import ToolRuntime
from sca.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return Workspace(root)


@pytest.fixture
def runtime(workspace):
    return ToolRuntime(workspace)


@pytest.fixture
def invoke():
    ids = itertools.count(1)

    def execute(runtime, name, arguments=None, *, call_id=None):
        result = runtime.execute(ToolCall(call_id or f"test-{next(ids)}", name, arguments or {}))
        result.validate()
        return result

    return execute


@pytest.fixture
def directory_link():
    def create(link: Path, target: Path) -> None:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            # Junctions require no Windows symlink privilege. The runtime
            # rejects both kinds of reparse point; no shell is used here.
            import _winapi
            _winapi.CreateJunction(str(target), str(link))

    return create
