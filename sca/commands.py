"""Small command allowlist and bounded subprocess capture for trusted projects.

No caller-selected executable, shell, environment or working directory. Tests
can execute arbitrary project code: authorization is not an OS/network sandbox.
"""

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from sca.limits import TaskBudget
from sca.workspace import Workspace, WorkspaceError, _is_link


@dataclass(frozen=True)
class CommandOutcome:
    output: str
    returncode: int
    timed_out: bool = False
    truncated: bool = False
    capture_error: str | None = None


class CommandRunner:
    def __init__(self, workspace: Workspace, *, timeout_seconds: float = 10, max_output_bytes: int = 16384, budget: TaskBudget | None = None) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be positive and at most 600")
        if type(max_output_bytes) is not int or not 128 <= max_output_bytes <= 1024 * 1024:
            raise ValueError("max_output_bytes must be between 128 and 1048576")
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self._budget = budget
        self._python = str(Path(sys.executable).resolve(strict=True))
        pytest_spec = importlib.util.find_spec("pytest")
        self._pytest_site = (
            str(Path(pytest_spec.origin).resolve(strict=True).parent.parent)
            if pytest_spec and pytest_spec.origin and pytest_spec.submodule_search_locations else None
        )
        located_git = shutil.which("git")
        self._git = str(Path(located_git).resolve(strict=True)) if located_git else None
        for executable in (self._python, self._git):
            if executable and Path(executable).is_relative_to(workspace.root):
                raise WorkspaceError("command executables must be outside the workspace")
            if executable and os.name == "nt" and Path(executable).suffix.lower() != ".exe":
                raise WorkspaceError("only native executables may be launched on Windows")

    def prepare(self, argv: list[str]) -> list[str]:
        if type(argv) is not list or not argv or len(argv) > 64:
            raise ValueError("argv must be a non-empty list of at most 64 strings")
        if any(not isinstance(arg, str) or not arg or len(arg) > 1024 or any(ord(char) < 32 for char in arg) for arg in argv):
            raise ValueError("argv contains an invalid argument")
        if argv == ["python", "--version"]:
            return [self._python, "-I", "--version"]
        if argv[:3] == ["python", "-m", "pytest"]:
            if self._pytest_site is None or Path(self._pytest_site).is_relative_to(self.workspace.root):
                raise ValueError("pytest must be installed outside the workspace")
            flags = {"-q", "-v", "-s", "--disable-warnings", "--maxfail=1"}
            for arg in argv[3:]:
                if arg in flags:
                    continue
                if arg.startswith(("-", "@")):
                    raise ValueError("pytest option or argument-file expansion is not allowlisted")
                self.workspace.resolve(arg)
            # Fixed application code, never caller-provided Python code. Pin
            # the installed dependency directory before importing pytest; -I
            # excludes the workspace and untrusted Python environment settings.
            bootstrap = (
                "import sys; sys.path.insert(0, sys.argv.pop(1)); "
                "import pytest; raise SystemExit(pytest.main(sys.argv[1:]))"
            )
            return [
                self._python, "-I", "-B", "-c", bootstrap, self._pytest_site,
                "-c", os.devnull,
                "--rootdir", str(self.workspace.root), "-p", "no:cacheprovider",
                "-o", "pythonpath=.", *argv[3:],
            ]
        if argv == ["git", "status", "--short"]:
            metadata = self.workspace.root / ".git"
            if not metadata.is_dir() or _is_link(metadata.lstat()):
                raise WorkspaceError("git inspection requires a normal .git directory at the workspace root")
            if self._git is None:
                raise ValueError("git executable is unavailable")
            return [
                self._git, "--no-optional-locks", "--no-pager",
                "-c", f"safe.directory={self.workspace.root.as_posix()}",
                "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                "status", "--short", "--untracked-files=all", "--ignore-submodules=all",
            ]
        raise ValueError("command is not allowlisted")

    def environment(self) -> dict[str, str]:
        # Intentionally do not forward API keys, credentials, Python/Git
        # overrides, pytest options, proxy variables or the user's HOME.
        result = {
            name: os.environ[name]
            for name in ("SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR")
            if name in os.environ
        }
        result.update({
            "PATH": os.pathsep.join(dict.fromkeys(str(Path(path).parent) for path in (self._python, self._git) if path)),
            "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        })
        return result

    @staticmethod
    def _kill_tree(process: subprocess.Popen) -> None:
        if os.name == "nt":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            try:
                subprocess.run(
                    [str(Path(system_root) / "System32" / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    shell=False, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()

    def run(self, argv: list[str]) -> CommandOutcome:
        prepared = self.prepare(argv)
        self.workspace.resolve(".")
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            if os.name == "nt" else {"start_new_session": True}
        )
        captured = bytearray()
        capture_errors: list[str] = []
        overflow = threading.Event()
        finished = threading.Event()
        timeout = self.timeout_seconds if self._budget is None else self._budget.timeout(self.timeout_seconds)
        deadline = time.monotonic() + timeout
        process = subprocess.Popen(
            prepared, cwd=self.workspace.root, env=self.environment(), shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, **options,
        )
        assert process.stdout is not None

        def drain() -> None:
            try:
                while block := process.stdout.read(4096):
                    remaining = self.max_output_bytes - len(captured)
                    captured.extend(block[:remaining])
                    if len(block) > remaining:
                        overflow.set()
                        break
            except OSError as exc:
                capture_errors.append(f"command output capture failed: {exc}")
            finally:
                finished.set()

        reader = threading.Thread(target=drain, daemon=True)
        timed_out = False
        try:
            reader.start()
            while not (process.poll() is not None and finished.is_set()):
                if overflow.is_set() or capture_errors:
                    self._kill_tree(process)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._kill_tree(process)
                    break
                finished.wait(min(0.02, remaining))
                if finished.is_set() and process.poll() is None:
                    time.sleep(min(0.01, remaining))
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                self._kill_tree(process)
                process.wait(timeout=5)
            if reader.ident is not None:
                reader.join(timeout=1)
            if not reader.is_alive():
                process.stdout.close()
        return CommandOutcome(
            output=bytes(captured).decode("utf-8", errors="replace"),
            returncode=process.returncode, timed_out=timed_out, truncated=overflow.is_set(),
            capture_error=capture_errors[0] if capture_errors else None,
        )
