"""Executor boundary, I1 recording fake, and I2 restricted local runtime."""

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import replace
import hashlib
import os
import re
import stat
import tempfile
from typing import Protocol

from sca.commands import CommandRunner
from sca.contracts import AgentTask, ToolCall, ToolDefinition, ToolResult
from sca.limits import TaskBudget
from sca.workspace import SessionContext, Workspace, WorkspaceError


class ToolExecutor(Protocol):
    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]: ...

    def execute(self, call: ToolCall) -> ToolResult: ...

    def begin_task(self, task: AgentTask) -> None:
        """Bind/reset one task's context before the first gateway invocation."""
        ...


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

    def begin_task(self, task: AgentTask) -> None:
        # Fake scripts/recordings keep their I1 behavior; no real workspace I/O.
        pass


AuthorizationPolicy = Callable[[ToolCall], bool]


class ToolRuntime:
    """Five fixed tools with read defaults and explicit write/command grants.

    Authorization receives a detached call. Only the literal boolean True is a
    grant. Caller-selected policies are trusted application code, never model
    instructions. A task/run uses one runtime sequentially.
    """

    def __init__(
        self,
        workspace: Workspace,
        *,
        authorize: AuthorizationPolicy | None = None,
        trusted_project: bool = False,
        timeout_seconds: float = 10,
        max_output_bytes: int = 16384,
        budget: TaskBudget | None = None,
    ) -> None:
        if type(trusted_project) is not bool:
            raise ValueError("trusted_project must be a boolean")
        self.workspace = workspace
        self.session = SessionContext(workspace_root=workspace.root)
        self._authorize = authorize
        self._trusted_project = trusted_project
        self._budget = budget
        self._runner = CommandRunner(workspace, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes, budget=budget)
        self._max_output_bytes = max_output_bytes
        self._seen_ids: set[str] = set()
        self._definitions = (
            ToolDefinition("list_files", "List safe project files recursively.", optional_argument_types={"path": str, "max_results": int}),
            ToolDefinition("read_file", "Read bounded UTF-8 text and its SHA-256.", {"path": str}, {"start_line": int, "end_line": int}),
            ToolDefinition("search_text", "Find literal, case-sensitive text in safe UTF-8 files.", {"text": str}, {"path": str, "max_results": int}),
            ToolDefinition(
                "apply_patch", "Edit one existing UTF-8 file using its current raw-byte SHA-256 from read_file. Each old span must match exactly once; edits cannot overlap. Requires user approval.",
                {"path": str, "expected_sha256": str, "edits": list},
                array_item_schemas={"edits": {
                    "type": "object", "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                    "required": ["old", "new"], "additionalProperties": False,
                }},
            ),
            ToolDefinition(
                "run_command", "Requires user approval and a trusted project. Allowed argv: ['python', '--version']; ['python', '-m', 'pytest', ...] with workspace targets and only -q, -v, -s, --disable-warnings, --maxfail=1; ['git', 'status', '--short']. No shell or other commands.",
                {"argv": list}, array_item_schemas={"argv": {"type": "string"}},
            ),
        )

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        return deepcopy(self._definitions)

    def begin_task(self, task: AgentTask) -> None:
        self.session = self.workspace.start_session(task)
        self._seen_ids.clear()

    def _require_authorization(self, call: ToolCall) -> None:
        self._check_budget()
        if self._authorize is None or self._authorize(deepcopy(call)) is not True:
            raise PermissionError(f"authorization denied for {call.tool_name}")
        # Waiting for an answer counts toward the task deadline. An old grant
        # must never start a write or command after the deadline.
        self._check_budget()

    def _check_budget(self) -> None:
        if self._budget is not None:
            self._budget.check()

    def execute(self, call: ToolCall) -> ToolResult:
        call = deepcopy(call)
        call.validate()
        if call.call_id in self._seen_ids:
            return ToolResult(call.call_id, "ERROR", error="duplicate call_id; execution was not repeated")
        self._seen_ids.add(call.call_id)
        try:
            self._check_budget()
            definition = next((item for item in self._definitions if item.name == call.tool_name), None)
            if definition is None:
                raise ValueError(f"unknown tool: {call.tool_name}")
            definition.validate_arguments(call.arguments)
            if call.tool_name in ("apply_patch", "run_command"):
                self._require_authorization(call)
            if call.tool_name == "list_files":
                result = self._list_files(call)
            elif call.tool_name == "read_file":
                result = self._read_file(call)
            elif call.tool_name == "search_text":
                result = self._search_text(call)
            elif call.tool_name == "apply_patch":
                result = self._apply_patch(call)
            else:
                result = self._run_command(call)
        except Exception as exc:
            result = ToolResult(call.call_id, "ERROR", error=f"{type(exc).__name__}: {exc}")
        # Tool output is model-visible data, bounded in UTF-8 bytes.
        raw = result.output.encode("utf-8")
        if len(raw) > self._max_output_bytes:
            result = replace(result, output=raw[:self._max_output_bytes].decode("utf-8", errors="ignore"), truncated=True)
        if result.error is not None:
            error_raw = result.error.encode("utf-8")
            if len(error_raw) > self._max_output_bytes:
                result = replace(result, error=error_raw[:self._max_output_bytes].decode("utf-8", errors="ignore"), truncated=True)
        self.session.tool_results.append(result)
        return result

    def _list_files(self, call: ToolCall) -> ToolResult:
        files, truncated = self.workspace.list_files(
            call.arguments.get("path", "."), max_results=call.arguments.get("max_results", 200),
        )
        return ToolResult(call.call_id, "SUCCESS", output="\n".join(files), truncated=truncated)

    def _read_file(self, call: ToolCall) -> ToolResult:
        snapshot = self.workspace.read_text(call.arguments["path"])
        lines = snapshot.content.splitlines(keepends=True)
        start = call.arguments.get("start_line", 1)
        end = call.arguments.get("end_line", max(len(lines), 1))
        if not 1 <= start <= end or (lines and start > len(lines)):
            raise ValueError("invalid 1-based inclusive line range")
        output = f"path: {snapshot.path}\nsha256: {snapshot.sha256}\n" + "".join(lines[start - 1:end])
        return ToolResult(call.call_id, "SUCCESS", output=output)

    def _search_text(self, call: ToolCall) -> ToolResult:
        needle = call.arguments["text"]
        if not needle or "\n" in needle or "\r" in needle or len(needle) > 4096:
            raise ValueError("search text must be a non-empty single line of at most 4096 characters")
        limit = call.arguments.get("max_results", 200)
        if not 1 <= limit <= 10000:
            raise ValueError("max_results must be between 1 and 10000")
        path = call.arguments.get("path", ".")
        resolved = self.workspace.resolve(path)
        if resolved.is_dir():
            files, truncated = self.workspace.list_files(path, max_results=10000)
        else:
            files, truncated = (path,), False
        matches: list[str] = []
        total_bytes = 0
        remaining_read_bytes = 8 * self.workspace.max_file_bytes
        for relative in files:
            self._check_budget()
            size = self.workspace.resolve(relative).stat().st_size
            if size > self.workspace.max_file_bytes:
                continue
            if size > remaining_read_bytes:
                return ToolResult(call.call_id, "SUCCESS", output="\n".join(matches), truncated=True)
            remaining_read_bytes -= size
            try:
                snapshot = self.workspace.read_text(relative)
            except WorkspaceError as exc:
                # Binaries and oversized files are excluded, never followed.
                if str(exc) not in ("binary files are not supported", "only UTF-8 text files are supported", "file exceeds maximum readable size"):
                    raise
                continue
            for number, line in enumerate(snapshot.content.splitlines(), 1):
                if needle in line:
                    entry = f"{relative}:{number}:{line}"
                    matches.append(entry)
                    total_bytes += len(entry.encode("utf-8")) + 1
                    if len(matches) >= limit or total_bytes > self._max_output_bytes:
                        return ToolResult(call.call_id, "SUCCESS", output="\n".join(matches), truncated=True)
        return ToolResult(call.call_id, "SUCCESS", output="\n".join(matches), truncated=truncated)

    def _ensure_initial_git_status(self, call: ToolCall) -> None:
        if self.session.initial_git_status is not None:
            return
        metadata = self.workspace.root / ".git"
        if not os.path.lexists(metadata):
            self.session.initial_git_status = "Not a Git repository at the workspace root."
            return
        if not self._trusted_project:
            raise PermissionError("initial Git inspection requires trusted_project=True")
        status_call = ToolCall(f"{call.call_id}:initial-status", "run_command", {"argv": ["git", "status", "--short"]})
        self._require_authorization(status_call)
        outcome = self._runner.run(status_call.arguments["argv"])
        if outcome.returncode != 0 or outcome.timed_out or outcome.truncated or outcome.capture_error:
            raise WorkspaceError("initial Git status could not be captured completely; mutation refused")
        self.session.initial_git_status = outcome.output

    def _apply_patch(self, call: ToolCall) -> ToolResult:
        path = call.arguments["path"]
        expected = call.arguments["expected_sha256"]
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise ValueError("expected_sha256 must be a 64-character SHA-256")
        edits = call.arguments["edits"]
        if not 1 <= len(edits) <= 20:
            raise ValueError("patch must contain between 1 and 20 text edits")
        snapshot = self.workspace.read_text(path)
        if not snapshot.mode & stat.S_IWUSR:
            raise PermissionError("read-only files cannot be patched")
        if snapshot.sha256 != expected.lower():
            raise WorkspaceError("file changed: expected SHA-256 does not match")
        replacements = []
        for edit in edits:
            if type(edit) is not dict or edit.keys() != {"old", "new"}:
                raise ValueError("each edit must contain exactly old and new")
            old, new = edit["old"], edit["new"]
            if not isinstance(old, str) or not isinstance(new, str) or not old or old == new:
                raise ValueError("edits require non-empty old text and a different new string")
            start = snapshot.content.find(old)
            if start == -1 or snapshot.content.find(old, start + 1) != -1:
                raise ValueError("old text must match exactly once; ambiguous or missing patch")
            replacements.append((start, start + len(old), new))
        replacements.sort()
        if any(left[1] > right[0] for left, right in zip(replacements, replacements[1:])):
            raise ValueError("overlapping edits are prohibited")
        updated = snapshot.content
        for start, end, new in reversed(replacements):
            updated = updated[:start] + new + updated[end:]
        if updated == snapshot.content:
            raise ValueError("patch has no net content change")
        raw = updated.encode("utf-8")
        if b"\0" in raw or len(raw) > self.workspace.max_file_bytes:
            raise ValueError("patched content must be bounded UTF-8 text without NUL bytes")
        self._ensure_initial_git_status(call)
        self._check_budget()
        destination = self.workspace.resolve(path)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".fennec-", suffix=".tmp", dir=destination.parent)
        temporary_relative = os.path.relpath(temporary_name, self.workspace.root).replace(os.sep, "/")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, stat.S_IMODE(snapshot.mode))
            self.workspace.resolve(temporary_relative)
            current = self.workspace.read_text(path)
            if current.sha256 != snapshot.sha256 or current.identity != snapshot.identity:
                raise WorkspaceError("file changed during patch preparation; user changes preserved")
            self.workspace.resolve(path)
            self._check_budget()
            os.replace(temporary_name, destination)
        finally:
            if os.path.lexists(temporary_name):
                safe_temporary = self.workspace.resolve(temporary_relative)
                safe_temporary.unlink()
        return ToolResult(
            call.call_id, "SUCCESS", output=f"Updated {path}\nsha256: {hashlib.sha256(raw).hexdigest()}",
            changed_files=(path,),
        )

    def _run_command(self, call: ToolCall) -> ToolResult:
        if not self._trusted_project:
            raise PermissionError("command execution requires trusted_project=True")
        argv = call.arguments["argv"]
        self._runner.prepare(argv)  # Validate before any initial-status preflight.
        if argv != ["git", "status", "--short"]:
            self._ensure_initial_git_status(call)
        outcome = self._runner.run(argv)
        if argv == ["git", "status", "--short"] and self.session.initial_git_status is None:
            if outcome.returncode == 0 and not outcome.timed_out and not outcome.truncated and not outcome.capture_error:
                self.session.initial_git_status = outcome.output
        error = outcome.capture_error
        if error is not None:
            pass
        elif outcome.timed_out:
            error = "command timeout; process termination requested; side effects may have occurred"
        elif outcome.truncated:
            error = "command output limit reached; process termination requested"
        elif outcome.returncode != 0:
            error = f"command exited with status {outcome.returncode}"
        tests_run = ()
        if argv[:3] == ["python", "-m", "pytest"]:
            label = " ".join(argv)
            tests_run = (f"{label}: {error or 'exit 0'}",)
        return ToolResult(
            call.call_id, "ERROR" if error else "SUCCESS",
            output=f"exit_code: {outcome.returncode}\n{outcome.output}", error=error,
            truncated=outcome.truncated, tests_run=tests_run,
        )
