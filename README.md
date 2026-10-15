# Fennec X Code

I1 provides a deterministic Agent Core. I2 adds Workspace & Context and five
restricted local tools through the same executor boundary. The approved
`SCA-V0-Core-Architecture-v0.1.md` and `SCA-V0-Codex-I1-Task.md` remain unchanged.

Requires Python >=3.12. Runtime code uses only the standard library. The test
extra requires pytest 8 or 9; command test execution also requires an installed
pytest outside the target workspace. No dependencies are installed by the tools.

Run the complete I1 and I2 suite from this directory:

```powershell
python -m pytest -q -p no:cacheprovider
```

Tests use disposable pytest projects, including real file operations and child
pytest processes. They require access to the system temp directory. Windows
link tests use junctions if creating a symbolic link requires extra privileges.

## Modules and interfaces

- `sca/contracts.py`: the six required dataclasses, messages, and tool schemas.
- `sca/model.py`: unchanged `ModelGateway.generate(request) -> ModelResponse`
  and scripted FakeModel. No live provider or network integration.
- `sca/workspace.py`: `Workspace(root, max_file_bytes=1048576)`, safe
  `resolve`, `read_text`, `list_files`, and `start_session(task)`. Text snapshots
  retain raw-byte SHA-256, content, identity and mode. SessionContext holds the
  task, workspace, initial Git status and tool results in memory.
- `sca/tools.py`: `ToolExecutor.tool_definitions`, `execute(call) -> ToolResult`,
  and the additive `begin_task(task) -> None` lifecycle hook. FakeToolExecutor's
  hook does no I/O. ToolRuntime's hook binds the task to the workspace and resets
  per-task evidence/IDs before the gateway is called. Custom I1 executors need
  to provide this hook; execution and tool-definition signatures are unchanged.
- `sca/commands.py`: fixed command allowlist and bounded process runner. It
  performs no task orchestration and exposes no plugin registration mechanism.
- `sca/agent.py`: `AgentCore(gateway, executor, max_model_rounds=25,
  continue_on_tool_error=False).run(task) -> TaskResult`.

Dependencies flow from Agent Core to interfaces and contracts; the tool runtime
uses workspace and command helpers, and those helpers never invoke the model.
`ToolDefinition` now supports `optional_argument_types` alongside required exact
types. Unknown arguments are rejected. `ToolResult` adds optional tuple fields
`changed_files` and `tests_run`; Core aggregates this executor evidence rather
than parsing claims in model text. Existing constructors keep their defaults.

## Tool inputs and results

All paths are relative, use `/`, and stay inside the validated workspace.
Results preserve the call ID and return `SUCCESS` or `ERROR`, text output,
optional error text, and a truncation flag. Model-visible output/error strings
are capped at 16 KiB by default; a cap may cut a line. Partial read/search output
is marked truncated. Partial command output is an explicit error.

| Tool | Required arguments | Optional arguments | Behavior |
| --- | --- | --- | --- |
| `list_files` | None | `path: str = "."`, `max_results: int = 200` | Recursive sorted relative files; excludes protected/generated paths and links |
| `read_file` | `path: str` | `start_line: int = 1`, `end_line: int = final line` | UTF-8 text, path and full-file raw-byte SHA-256; line ranges are inclusive |
| `search_text` | `text: str` | `path: str = "."`, `max_results: int = 200` | Literal case-sensitive single-line search; returns `path:line:text` |
| `apply_patch` | `path: str`, `expected_sha256: str`, `edits: list` | None | One existing file; 1-20 `{old: str, new: str}` edits matched against the original content |
| `run_command` | `argv: list[str]` | None | Authorized allowlisted command in the fixed workspace root |

File reads/patch results are limited to 1 MiB by default. Listings inspect at most
10,000 directory entries. Search reads at most eight times the file-size limit
per invocation and excludes binary, non-UTF-8 and oversized files. Both listing
and search have result limits; truncation is conservative at a result boundary.

## Authorization and commands

`ToolRuntime(workspace, authorize=None, trusted_project=False,
timeout_seconds=10, max_output_bytes=16384)` allows safe reads by default.
Writes and every command require a trusted, application-injected
`Callable[[ToolCall], bool]`. Only literal `True` authorizes the detached call;
missing, denying, non-boolean or failing policies fail closed. Model text cannot
set policy, trust, executable paths, environment, timeouts or output limits.

Commands additionally require `trusted_project=True`. Accepted argv forms:

- `["python", "--version"]`.
- `["python", "-m", "pytest", ...]`, with existing safe workspace targets and
  only `-q`, `-v`, `-s`, `--disable-warnings`, `--maxfail=1` flags.
- `["git", "status", "--short"]`, only for a normal `.git` directory at the
  workspace root. Ancestor repositories and linked Git worktrees are refused.

User-supplied shell, Python `-c`, arbitrary scripts/modules, pytest argument
files, arbitrary pytest options, package installation, Git writes and network
commands are rejected before process creation. Executable paths are pinned
outside the workspace. Subprocesses use structured argv, `shell=False`, closed
stdin, a reduced environment, disabled pytest plugin autoload and fixed pytest
configuration. An internal fixed Python bootstrap imports the verified pytest
installation in isolated mode; it accepts no caller-supplied Python code.

Before a patch or command in a Git workspace, the runtime requires separate
authorization for its initial read-only Git-status preflight. This records
pre-existing dirty paths without staging/resetting anything. Denied, failed,
timed-out or truncated preflight blocks the pending operation. Non-Git roots
record that fact without running Git. A direct authorized Git status can supply
the initial snapshot. Git-status inspection itself does not take optional locks.

The runner bounds capture while reading and terminates on timeout or output
overflow. Windows termination requests the process tree with native `taskkill`;
POSIX uses a process group. Pytest runs record actual exit/failure/timeout
evidence. Failed tests never become reported success.

## Workspace and patch safety

The root must exist, remain the same directory, and have no linked ancestors.
Traversal, absolute/drive/UNC paths, alternate data streams, reserved devices,
ambiguous components, symlinks, junctions/reparse points and hardlinked files are
refused. Protected names include `.git`, known credential/config locations,
`.env*`, secret/credential files, private-key extensions, generated directories,
and both approved specification filenames. This is a conservative denylist,
not a detector of every possible secret in arbitrary source files.

Patches require the current SHA-256, exactly one occurrence of every old span
(including overlapping occurrences), disjoint edits, bounded UTF-8 content and
a net content change. They preserve line endings and unrelated text. Immediately
before replacement, the runtime compares content hash and file identity again.
Replacement uses a sibling temporary file, flush/fsync, preserved mode and
atomic replace; rejected patches leave the target unchanged and clean up
temporary files. Read-only files, creation/deletion/rename and multi-file patch
transactions are unsupported. Existing user edits are retained rather than
reset or reconstructed from Git.

## I1 behavior changes and remaining scope

The model instruction now refers to advertised tools without naming fakes.
Default tool-error behavior remains fail-fast. Explicitly enabling
`continue_on_tool_error` feeds reported errors back into the next request, but
keeps them in the final ERROR status; exceptions escaping the executor remain
fatal. IDs cannot repeat and no tools or gateways are automatically retried.

The final allowed model round may return a final answer, but cannot execute a
tool batch because no model round remains to inspect its results. It returns
`LIMIT_REACHED` with the earlier evidence. This intentionally tightens I1's
last-round behavior; the existing limit test and new regression tests cover it.

Only trusted local projects are supported. Project tests/conftest can execute
arbitrary code, access the host/network and spawn processes. This runtime is not
an OS sandbox; environment filtering and an allowlist do not change that.
Process-tree termination is best effort, especially for detached/reparented
children. Optimistic patch rechecks detect ordinary concurrent edits but do not
provide an OS-wide compare-and-swap guarantee against malicious race attacks.
Command side effects other than direct patch operations are not inventoried in
`changed_files`. Sessions are in memory; cancellation and a whole-task wall-clock
deadline remain deferred. No I3, I4, live LLM, CLI, subagents, Skills, planners,
plugins, advanced memory or multi-agent features are implemented.

**Stop after I2. I3 requires explicit authorization.**
