"""I2 fixtures isolate real operations in pytest temporary projects."""

import itertools
import http.client
import json
import os
from pathlib import Path

import pytest

from sca.contracts import ToolCall
from sca.tools import ToolRuntime
from sca.workspace import Workspace


@pytest.fixture(autouse=True)
def no_live_provider_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Automated tests must not contact an LLM endpoint")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", forbidden)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", forbidden)


@pytest.fixture
def provider_response():
    def response(content="Done.", *, calls=None, finish=None):
        message = {"role": "assistant", "content": content}
        if calls is not None:
            message["tool_calls"] = [
                {"id": call_id, "type": "function", "function": {
                    "name": name, "arguments": json.dumps(arguments),
                }} for call_id, name, arguments in calls
            ]
        return {"choices": [{"message": message, "finish_reason": finish or ("tool_calls" if calls else "stop")}]}

    return response


@pytest.fixture
def mock_provider():
    from sca.provider import HttpResponse

    class ScriptedTransport:
        def __init__(self, responses):
            self.responses = iter(responses)
            self.calls = []

        def post(self, url, headers, body, *, timeout, max_bytes):
            self.calls.append({"url": url, "headers": dict(headers), "payload": json.loads(body),
                               "timeout": timeout, "max_bytes": max_bytes})
            item = next(self.responses)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, HttpResponse):
                return item
            return HttpResponse(200, json.dumps(item).encode("utf-8"))

    return ScriptedTransport


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
