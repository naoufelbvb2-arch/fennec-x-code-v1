import os
import subprocess
import time

import pytest

from sca.tools import ToolRuntime


def test_command_requires_authorization_even_in_trusted_project(workspace, invoke):
    runtime = ToolRuntime(workspace, trusted_project=True)
    result = invoke(runtime, "run_command", {"argv": ["python", "--version"]})
    assert result.status == "ERROR"
    assert "authorization denied" in result.error


def test_command_requires_trusted_project_marker(workspace, invoke):
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    result = invoke(runtime, "run_command", {"argv": ["python", "--version"]})
    assert result.status == "ERROR"
    assert "trusted_project=True" in result.error


def test_allowlisted_version_command(workspace, invoke):
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    result = invoke(runtime, "run_command", {"argv": ["python", "--version"]}, call_id="version")
    assert result.call_id == "version"
    assert result.status == "SUCCESS"
    assert "Python 3." in result.output
    assert result.tests_run == ()


@pytest.mark.parametrize("argv", [
    "python --version", [], ["cmd", "/c", "echo hello"], ["powershell", "-Command", "echo hello"],
    ["python", "-c", "print('unsafe')"], ["python", "script.py"],
    ["python", "-m", "pip", "install", "anything"], ["git", "reset", "--hard"],
    ["git", "push"], ["git", "-c", "core.fsmonitor=unsafe", "status"],
    ["python", "-m", "pytest", "-p", "anything"], ["python", "-m", "pytest", "-c", "outside.ini"],
    ["python", "-m", "pytest", "../outside"], ["python", "-m", "pytest", "C:/outside"],
    ["python", "-m", "pytest", ".git"], ["python", "--version", ";", "whoami"],
    ["python", "--version\nwhoami"], ["python", 12],
])
def test_unapproved_commands_do_not_launch_process(workspace, invoke, monkeypatch, argv):
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)

    def forbidden(*args, **kwargs):
        pytest.fail("rejected command must not create a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = invoke(runtime, "run_command", {"argv": argv})
    assert result.status == "ERROR"
    assert result.tests_run == ()


def test_pytest_real_execution_uses_clean_environment_and_workspace(workspace, invoke, monkeypatch):
    monkeypatch.setenv("FENNEC_TEST_SECRET", "must-not-be-forwarded")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--invalid-host-option")
    monkeypatch.setenv("PYTHONPATH", "nonexistent-host-path")
    (workspace.root / "test_environment.py").write_text(
        "import os, sys\nfrom pathlib import Path\n"
        "def test_environment():\n"
        "    assert 'FENNEC_TEST_SECRET' not in os.environ\n"
        "    assert 'PYTEST_ADDOPTS' not in os.environ\n"
        "    assert 'PYTHONPATH' not in os.environ\n"
        "    assert sys.flags.isolated == 1\n"
        f"    assert Path.cwd() == Path({str(workspace.root)!r})\n",
        encoding="utf-8",
    )
    # A workspace-local module must not shadow the actual pytest executable.
    (workspace.root / "pytest.py").write_text("raise RuntimeError('shadowed pytest')", encoding="utf-8")
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)

    result = invoke(runtime, "run_command", {"argv": ["python", "-m", "pytest", "-q", "test_environment.py"]})

    assert result.status == "SUCCESS", result.error or result.output
    assert "1 passed" in result.output
    assert len(result.tests_run) == 1
    assert result.tests_run[0].endswith("exit 0")
    assert not (workspace.root / ".pytest_cache").exists()
    assert not list(workspace.root.rglob("*.pyc"))


def test_failing_test_records_actual_failure(workspace, invoke):
    (workspace.root / "test_failure.py").write_text("def test_failure():\n    assert False\n", encoding="utf-8")
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    result = invoke(runtime, "run_command", {"argv": ["python", "-m", "pytest", "-q"]})
    assert result.status == "ERROR"
    assert "1 failed" in result.output
    assert "status 1" in result.error
    assert "status 1" in result.tests_run[0]


def test_command_timeout_stops_and_reports_execution(workspace, invoke):
    (workspace.root / "test_wait.py").write_text(
        "import time\ndef test_wait():\n    time.sleep(30)\n", encoding="utf-8",
    )
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True, timeout_seconds=0.4)
    started = time.monotonic()
    result = invoke(runtime, "run_command", {"argv": ["python", "-m", "pytest", "-q"]})
    assert time.monotonic() - started < 8
    assert result.status == "ERROR"
    assert "timeout" in result.error
    assert "timeout" in result.tests_run[0]


def test_command_output_limit_terminates_instead_of_buffering_unbounded_output(workspace, invoke):
    (workspace.root / "test_output.py").write_text(
        "def test_output():\n    print('z' * 100000)\n", encoding="utf-8",
    )
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True, max_output_bytes=1024)
    result = invoke(runtime, "run_command", {"argv": ["python", "-m", "pytest", "-s", "-q"]})
    assert result.status == "ERROR"
    assert result.truncated
    assert "output limit" in result.error
    assert len(result.output.encode("utf-8")) <= 1024


def test_command_target_cannot_be_a_symlink_escape(workspace, tmp_path, directory_link, invoke):
    outside = tmp_path / "outside"
    outside.mkdir()
    directory_link(workspace.root / "escape", outside)
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    result = invoke(runtime, "run_command", {"argv": ["python", "-m", "pytest", "escape"]})
    assert result.status == "ERROR"
    assert "reparse" in result.error or "symlink" in result.error


def test_git_cannot_inspect_an_ancestor_repository(workspace, invoke):
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    result = invoke(runtime, "run_command", {"argv": ["git", "status", "--short"]})
    assert result.status == "ERROR"
    assert "workspace root" in result.error


def test_pytest_argument_files_cannot_bypass_command_allowlist(workspace, invoke, monkeypatch):
    (workspace.root / "@arguments.txt").write_text("ignored", encoding="utf-8")
    (workspace.root / "arguments.txt").write_text("-p\nunapproved_plugin\n", encoding="utf-8")
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)

    def forbidden(*args, **kwargs):
        pytest.fail("argument-file expansion must be rejected before process creation")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = invoke(runtime, "run_command", {"argv": ["python", "-m", "pytest", "@arguments.txt"]})
    assert result.status == "ERROR"
    assert "argument-file" in result.error


def test_output_capture_failure_cannot_be_reported_as_success(workspace, invoke, monkeypatch):
    original_popen = subprocess.Popen

    def failing_capture(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        if kwargs.get("stdout") == subprocess.PIPE:
            stream = process.stdout

            class BrokenReader:
                def read(self, size):
                    raise OSError("fixture capture failure")

                def close(self):
                    stream.close()

            process.stdout = BrokenReader()
        return process

    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    monkeypatch.setattr(subprocess, "Popen", failing_capture)
    result = invoke(runtime, "run_command", {"argv": ["python", "--version"]})
    assert result.status == "ERROR"
    assert "output capture failed" in result.error
