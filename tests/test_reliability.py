"""I4 deadline, cancellation and partial-evidence regressions; no live model."""

import io
import json
import subprocess
import threading

import pytest

from sca.agent import AgentCore
from sca.contracts import AgentTask, Message, ModelRequest, ModelResponse, ToolCall, ToolDefinition, ToolResult
from sca.model import FakeModel
from sca.limits import TaskBudget, TaskLimitExceeded
from sca.provider import CompatibleModel, HttpTransport, ModelConfig
from sca.tools import FakeToolExecutor, ToolRuntime
from sca.workspace import Workspace


def test_late_final_answer_cannot_claim_completion(monkeypatch):
    import sca.agent as agent_module

    now = [0.0]
    monkeypatch.setattr(agent_module, "monotonic", lambda: now[0], raising=False)

    class SlowModel:
        def generate(self, request):
            now[0] = 601.0
            return ModelResponse(final_answer="Too late")

    result = AgentCore(SlowModel(), FakeToolExecutor()).run(AgentTask("Task", "metadata", "late"))
    assert result.status == "LIMIT_REACHED"
    assert "time" in result.errors[-1].lower()


def test_interrupted_gateway_returns_structured_prior_evidence():
    class InterruptedModel:
        def __init__(self):
            self.calls = 0

        def generate(self, request):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(tool_calls=(ToolCall("patch", "fake"),))
            raise KeyboardInterrupt

    executor = FakeToolExecutor([ToolDefinition("fake")], [
        ToolResult("patch", "SUCCESS", changed_files=("app.py",)),
    ])
    result = AgentCore(InterruptedModel(), executor).run(AgentTask("Task", "metadata", "cancel"))
    assert result.status == "CANCELLED"
    assert result.changed_files == ("app.py",)
    assert [item.call_id for item in result.tool_results] == ["patch"]


def test_interrupted_tool_gets_one_correlated_uncertain_result():
    class InterruptedExecutor(FakeToolExecutor):
        def execute(self, call):
            self.calls.append(call)
            raise KeyboardInterrupt

    executor = InterruptedExecutor([ToolDefinition("fake")])
    model = FakeModel([ModelResponse(tool_calls=(ToolCall("interrupted", "fake"),))])
    result = AgentCore(model, executor).run(AgentTask("Task", "metadata", "cancel-tool"))
    assert result.status == "CANCELLED"
    assert len(result.tool_results) == len(executor.calls) == 1
    assert result.tool_results[0].call_id == "interrupted"
    assert result.tool_results[0].status == "ERROR"
    assert "side effects" in result.tool_results[0].error


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_task_deadline_configuration_rejected(value):
    with pytest.raises(ValueError):
        AgentCore(FakeModel([]), FakeToolExecutor(), max_task_seconds=value)


@pytest.fixture
def budget_clock():
    now = [0.0]
    return TaskBudget(10, clock=lambda: now[0]), now


def test_deadline_stops_between_calls_and_preserves_observed_evidence(budget_clock):
    budget, now = budget_clock

    class TimedExecutor(FakeToolExecutor):
        def execute(self, call):
            result = super().execute(call)
            now[0] = 11
            return result

    executor = TimedExecutor([ToolDefinition("fake")], [
        ToolResult("one", "SUCCESS", changed_files=("app.py",)),
        ToolResult("two", "SUCCESS"),
    ])
    model = FakeModel([ModelResponse(tool_calls=(ToolCall("one", "fake"), ToolCall("two", "fake")))])
    result = AgentCore(model, executor, budget=budget).run(AgentTask("Task", "metadata", "batch"))
    assert result.status == "LIMIT_REACHED"
    assert result.changed_files == ("app.py",)
    assert [call.call_id for call in executor.calls] == ["one"]
    assert [item.call_id for item in result.tool_results] == ["one"]


def test_deadline_in_task_setup_never_calls_model(budget_clock):
    budget, now = budget_clock

    class SlowSetup(FakeToolExecutor):
        def begin_task(self, task):
            now[0] = 11

    model = FakeModel([])
    result = AgentCore(model, SlowSetup(), budget=budget).run(AgentTask("Task", "metadata", "setup"))
    assert result.status == "LIMIT_REACHED" and result.model_rounds == 0
    assert model.requests == []


def test_budget_is_restarted_for_each_sequential_task(budget_clock):
    budget, now = budget_clock

    class TimedModel:
        def generate(self, request):
            now[0] += 6
            return ModelResponse(final_answer="Done")

    core = AgentCore(TimedModel(), FakeToolExecutor(), budget=budget)
    assert core.run(AgentTask("Task", "metadata", "first")).status == "COMPLETED"
    assert core.run(AgentTask("Task", "metadata", "second")).status == "COMPLETED"
    assert now[0] == 12


def patch_arguments():
    import hashlib

    return {"path": "sample.txt", "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
            "edits": [{"old": "before", "new": "after"}]}


@pytest.mark.parametrize("operation", ["apply_patch", "run_command"])
def test_expired_approval_cannot_start_side_effects(workspace, budget_clock, monkeypatch, operation):
    budget, now = budget_clock
    target = workspace.root / "sample.txt"
    target.write_bytes(b"before\n")

    def approve_after_deadline(call):
        now[0] = 11
        return True

    def forbidden(*args, **kwargs):
        pytest.fail("An expired task must not spawn a process")

    runtime = ToolRuntime(workspace, authorize=approve_after_deadline, trusted_project=True, budget=budget)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    arguments = patch_arguments() if operation == "apply_patch" else {"argv": ["python", "--version"]}
    model = FakeModel([ModelResponse(tool_calls=(ToolCall("expired", operation, arguments),))])
    result = AgentCore(model, runtime, budget=budget).run(AgentTask("Task", str(workspace.root), "expired"))
    assert result.status == "LIMIT_REACHED"
    assert result.tool_results[0].call_id == "expired"
    assert target.read_bytes() == b"before\n" and result.changed_files == ()


def test_expiration_during_patch_preparation_cleans_temporary_file(workspace, budget_clock, monkeypatch):
    import sca.tools as tool_module

    budget, now = budget_clock
    target = workspace.root / "sample.txt"
    target.write_bytes(b"before\n")
    runtime = ToolRuntime(Workspace(workspace.root, budget=budget), authorize=lambda call: True, budget=budget)
    original_fsync = tool_module.os.fsync

    def expire(descriptor):
        original_fsync(descriptor)
        now[0] = 11

    monkeypatch.setattr(tool_module.os, "fsync", expire)
    model = FakeModel([ModelResponse(tool_calls=(ToolCall("patch", "apply_patch", patch_arguments()),))])
    result = AgentCore(model, runtime, budget=budget).run(AgentTask("Task", str(workspace.root), "patch"))
    assert result.status == "LIMIT_REACHED"
    assert target.read_bytes() == b"before\n"
    assert not list(workspace.root.glob(".fennec-*.tmp"))


def test_atomic_replace_failure_preserves_file_and_cleans_temporary_file(workspace, monkeypatch):
    import sca.tools as tool_module

    target = workspace.root / "sample.txt"
    target.write_bytes(b"before\n")

    def failed_replace(*args):
        raise OSError("fixture replace failure")

    monkeypatch.setattr(tool_module.os, "replace", failed_replace)
    result = ToolRuntime(workspace, authorize=lambda call: True).execute(ToolCall("patch", "apply_patch", patch_arguments()))
    assert result.status == "ERROR" and result.changed_files == ()
    assert target.read_bytes() == b"before\n"
    assert not list(workspace.root.glob(".fennec-*.tmp"))


def test_provider_timeout_is_capped_by_remaining_task_budget(budget_clock, mock_provider, provider_response):
    budget, now = budget_clock
    budget.start()
    now[0] = 7
    transport = mock_provider([provider_response()])
    gateway = CompatibleModel(ModelConfig("chosen", "https://configured.invalid/v1"), transport, budget=budget)
    request = ModelRequest("Task", (Message("user", "Task"),), (), {}, AgentTask("Task", "metadata", "budget"))
    assert gateway.generate(request).final_answer == "Done."
    assert transport.calls[0]["timeout"] == 3
    now[0] = 10
    with pytest.raises(TaskLimitExceeded):
        gateway.generate(request)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("closed_connection,read_error", [(False,False),(True,False),(True,True)])
def test_http_watchdog_interrupts_trickling_exchange_without_logging(monkeypatch, capsys, closed_connection, read_error):
    import sca.provider as provider_module

    events = []
    fire = []

    class Timer:
        def __init__(self, seconds, callback):
            assert seconds == 3
            fire.append(callback)

        def start(self):
            events.append("started")

        def cancel(self):
            events.append("cancelled")

    class Socket:
        def shutdown(self, how):
            events.append("shutdown")

    class Connection:
        sock = Socket()

        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            if closed_connection:
                self.sock = None  # HTTPResponse owns the socket after Connection: close.

            def read(response, limit):
                fire[0]()  # Deadline fires while the server trickles data.
                if read_error:
                    raise OSError("unit-test-token private socket error")
                return b'unit-test-token private provider body'
            return type("Response", (), {"status": 200, "read": read})()

        def close(self):
            events.append("closed")

    monkeypatch.setattr(provider_module.threading, "Timer", Timer)
    monkeypatch.setattr(provider_module.http.client, "HTTPSConnection", Connection)
    with pytest.raises(TimeoutError):
        HttpTransport().post("https://configured.invalid/v1", {"Authorization": "Bearer unit-test-token"}, b"{}", timeout=3, max_bytes=128)
    assert events == ["started", "shutdown", "cancelled", "closed"]
    assert capsys.readouterr().out == ""


def test_interrupt_during_command_reader_setup_reaps_child(workspace, monkeypatch):
    from sca.commands import CommandRunner

    (workspace.root / "test_wait.py").write_bytes(b"import time\ndef test_wait():\n    time.sleep(30)\n")
    runner = CommandRunner(workspace)
    original_popen = subprocess.Popen
    children = []

    def record(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        if kwargs.get("stdout") == subprocess.PIPE:
            children.append(process)
        return process

    def interrupted(thread):
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "Popen", record)
    monkeypatch.setattr(threading.Thread, "start", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.run(["python", "-m", "pytest", "-q"])
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stdout.closed


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_cli_rejects_invalid_task_timeout_before_request(workspace, mock_provider, timeout):
    from sca.cli import main

    transport = mock_provider([])
    errors = io.StringIO()
    assert main(["--workspace", str(workspace.root), "--task", "Task", "--model", "chosen",
                 "--api-base-url", "https://configured.invalid/v1", "--task-timeout", timeout],
                environ={}, transport=transport, stdout=io.StringIO(), stderr=errors) == 2
    assert "task timeout" in errors.getvalue() and not transport.calls


def test_cli_cancellation_has_structured_result_and_exit_130(workspace, mock_provider):
    from sca.cli import main

    transport = mock_provider([])

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    transport.post = interrupted
    output = io.StringIO()
    status = main(["--workspace", str(workspace.root), "--task", "Task", "--model", "chosen",
                   "--api-base-url", "https://configured.invalid/v1"], environ={}, transport=transport,
                  stdout=output, stderr=io.StringIO())
    assert status == 130
    result = json.loads(output.getvalue().split("Task result:\n")[1])
    assert result["status"] == "CANCELLED"


def test_command_timeout_is_capped_by_shared_budget(workspace, budget_clock):
    from sca.commands import CommandRunner

    budget, now = budget_clock
    budget.start()
    now[0] = 9.7
    (workspace.root / "test_wait.py").write_bytes(b"import time\ndef test_wait():\n    time.sleep(30)\n")
    outcome = CommandRunner(workspace, timeout_seconds=10, budget=budget).run(["python", "-m", "pytest", "-q"])
    assert outcome.timed_out and outcome.returncode != 0


def test_cli_task_deadline_returns_structured_limit_and_exit_3(workspace, mock_provider, provider_response, monkeypatch):
    import sca.cli as cli_module

    now = [0.0]
    monkeypatch.setattr(cli_module, "TaskBudget", lambda seconds: TaskBudget(seconds, clock=lambda: now[0]))
    transport = mock_provider([provider_response("Late response")])
    original_post = transport.post

    def slow(*args, **kwargs):
        now[0] = 2
        return original_post(*args, **kwargs)

    transport.post = slow
    output = io.StringIO()
    status = cli_module.main(["--workspace", str(workspace.root), "--task", "Task", "--model", "chosen",
                              "--api-base-url", "https://configured.invalid/v1", "--task-timeout", "1"],
                             environ={}, transport=transport, stdout=output, stderr=io.StringIO())
    assert status == 3 and len(transport.calls) == 1
    result = json.loads(output.getvalue().split("Task result:\n")[1])
    assert result["status"] == "LIMIT_REACHED"
    assert "Late response" not in output.getvalue()
    assert transport.calls[0]["timeout"] == 1


def test_cli_interrupted_tool_reports_its_id_and_uncertain_outcome(workspace, mock_provider, provider_response):
    from sca.cli import main

    (workspace.root / "sample.txt").write_bytes(b"before\n")
    transport = mock_provider([provider_response(None, calls=[("cancel-patch", "apply_patch", patch_arguments())])])

    def interrupted(prompt):
        raise KeyboardInterrupt

    output = io.StringIO()
    status = main(["--workspace", str(workspace.root), "--task", "Task", "--model", "chosen",
                   "--api-base-url", "https://configured.invalid/v1"], environ={}, transport=transport,
                  input_fn=interrupted, stdout=output, stderr=io.StringIO())
    result = json.loads(output.getvalue().split("Task result:\n")[1])
    assert status == 130 and result["status"] == "CANCELLED"
    assert "cancel-patch" in result["errors"][0] and "side effects" in result["errors"][0]
    assert (workspace.root / "sample.txt").read_bytes() == b"before\n"
    assert len(transport.calls) == 1
