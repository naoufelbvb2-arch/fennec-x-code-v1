# Fennec X Code: I2 implementation and verification

Date: October 15, 2026. Authorized stage: I2 only.

Workspace: `C:\Users\Laptop\Desktop\fennec x code v1`.
Branch: `i2-workspace-tools`.
Approved baseline: `23cc2d84e3903d987e8758ff6508d27cab9da483`.

The existing sequential Agent Core now operates real, restricted development
tools through ToolExecutor. ModelGateway and FakeModel are unchanged. No
orchestration rewrite, live model integration or CLI was introduced.

## Files created and modified

| File | Change | Purpose |
| --- | --- | --- |
| `sca/workspace.py` | Created | Validated roots, path boundaries, UTF-8 snapshots, in-memory sessions |
| `sca/commands.py` | Created | Fixed command preparation, reduced environment, bounded process runner |
| `sca/tools.py` | Modified | Five-tool runtime, default-deny policy, task lifecycle, evidence |
| `sca/contracts.py` | Modified | Optional argument schemas and executor-produced change/test evidence |
| `sca/agent.py` | Modified | Bind task context, aggregate evidence, safe round exhaustion, optional error feedback |
| `tests/conftest.py` | Created | Disposable projects, call helper, Windows junction fallback |
| `tests/test_workspace.py` | Created | Root, traversal, sensitive-path, symlink/junction, hardlink and size tests |
| `tests/test_tools.py` | Created | Real reads/search/listing, permissions, patching, concurrency and dirty Git state |
| `tests/test_commands.py` | Created | Allowlist, environment, real pytest, timeout and output tests |
| `tests/test_agent_tools.py` | Created | FakeModel integration with real tools and Agent Core regressions |
| `tests/test_agent_loop.py` | Modified | Update final-round expectation for the I2 safety rule |
| `pyproject.toml` | Modified | Update the package description; no new dependencies |
| `README.md` | Modified | Exact tool inputs, interfaces, authorization, behavior and limitations |
| `I2-IMPLEMENTATION-REPORT.md` | Created | This report |

Both approved documents, `sca/model.py`, the I1 report, and the existing contract
and fake test files are unchanged. Original I1 test cases remain present; one
round-limit assertion deliberately reflects the authorized safety adjustment.

## Exact contracts and interfaces

- Existing `AgentTask`, `ModelRequest`, `ModelResponse`, `ToolCall`, `TaskResult`
  fields and ModelGateway's `generate(request) -> ModelResponse` are retained.
- `ToolDefinition` adds `optional_argument_types: dict[str, type] = {}` using a
  dataclass factory. Required/optional names are distinct, extras are denied,
  and exact types prevent bool-as-int argument acceptance.
- `ToolResult` adds `changed_files: tuple[str, ...] = ()` and
  `tests_run: tuple[str, ...] = ()`. Existing positional arguments/defaults work.
- `ToolExecutor.tool_definitions` and `execute(call) -> ToolResult` retain their
  signatures. The additive `begin_task(task) -> None` hook validates real task
  binding before model invocation and resets per-task context. It does no I/O in
  FakeToolExecutor. Custom external I1 executors need to implement this hook.
- `Workspace(root, max_file_bytes=1048576)` exposes `resolve(relative,
  must_exist=True)`, `read_text(relative) -> TextSnapshot`,
  `list_files(relative=".", max_results=200, max_entries=10000)` returning
  `(tuple_of_paths, truncated)`, and `start_session(task) -> SessionContext`.
- TextSnapshot contains path, UTF-8 content, SHA-256 of original bytes, file
  identity and mode. SessionContext holds root, task, initial Git status and
  observed tool results in memory.
- `ToolRuntime(workspace, authorize=None, trusted_project=False,
  timeout_seconds=10, max_output_bytes=16384)` implements ToolExecutor.
  Authorization is `Callable[[ToolCall], bool]`; literal True is required for
  each write/command. Policies receive detached calls. Missing/failed policies
  deny execution. Commands additionally require the trusted-project marker.
- `AgentCore(..., continue_on_tool_error=False)` retains the existing `run(task)`
  entry point, response validation, sequential execution, ID correlation and
  bounded model invocations. No fake-specific execution logic is present.

All five tools use fixed dispatch, with no registration or plugin framework:

| Tool | Input contract |
| --- | --- |
| `list_files` | Optional `path: str`, `max_results: int` |
| `read_file` | Required `path: str`; optional inclusive `start_line: int`, `end_line: int` |
| `search_text` | Required single-line literal `text: str`; optional `path: str`, `max_results: int` |
| `apply_patch` | Required `path: str`, `expected_sha256: str`, `edits: list` of exact `{old: str, new: str}` dictionaries |
| `run_command` | Required `argv: list[str]`; no shell, environment, executable or cwd override |

Read output includes full-file SHA-256. Search output uses `path:line:text`.
All outputs/errors retain call IDs and are byte-bounded with truncation flags.
Only successful direct patch effects populate changed-files evidence; actual
pytest execution populates tests-run evidence, including failures and timeouts.
Model final text does not manufacture either kind of evidence.

## Security and preservation checks

Tests prove valid access, root validation and mismatched-task refusal; lexical
and real-path containment; traversal, drive/UNC, alternate-stream, reserved-device
and ambiguous-component rejection; real Windows junction/symlink escape refusal;
and hardlink refusal. Listing/search omit protected and generated paths.
Known sensitive names, key extensions, Git metadata and both approved document
names are denied. Root identity is checked again on subsequent operations.

Files are UTF-8 only and bounded at 1 MiB by default; binary and oversized files
are excluded from search. Traversal is bounded at 10,000 directory entries.
Search reads at most eight times the per-file size limit per call. Output/error
strings are capped at 16 KiB by default. Read/search truncation is explicit.

Patching supports one existing regular text file and 1-20 disjoint edits. Old
spans must match once, counting overlapping occurrences. Missing, ambiguous,
overlapping, no-op, invalid, stale or read-only patches fail without changing
the target. Temporary-file preparation, fsync, preserved mode and atomic replace
are combined with content/identity checks immediately before replacement. Tests
inject a concurrent edit and verify it is retained and temporary files removed.
CRLF and unrelated user content remain intact.

In a Git workspace, a separately authorized initial `git status` must complete
before patches/other commands. Failure, denial, timeout or truncation blocks the
pending operation. The snapshot preserves evidence of pre-existing dirty and
untracked files. No tool stages, commits, resets, checks out or pushes changes.
Git status disables optional locks and fsmonitor; ancestor repositories and
linked Git worktrees are unsupported.

The command allowlist permits Python version, narrowly constrained pytest runs,
and read-only Git status. Arbitrary executables, shells, user Python code,
package installation, Git writes, pytest argument-file expansion and plugin/config
flags are denied before process launch. Executables and the installed pytest
dependency are pinned outside the workspace. The environment omits ambient
secrets, Python/Git overrides and pytest options. A fixed internal isolated
bootstrap imports the installed pytest; no user code string is accepted.

Command invocations use structured argv and `shell=False`, following
[Python's subprocess interface](https://docs.python.org/3/library/subprocess.html).
Streaming capture is bounded. Timeout/output overflow returns ERROR and requests
process-tree termination, using the `/T` behavior documented for
[Windows taskkill](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill)
or a POSIX process group. Failed/partial executions never claim test success.
Output-reader failures also return ERROR, even if the child exits with code 0;
an injected stream-read failure regression verifies this behavior.

## I1 behavior changes

1. Model instructions now refer to advertised tools without hardcoded fake-tool
   wording. ModelGateway/FakeModel are unchanged.
2. Default tool errors still stop immediately. Explicit error-feedback mode
   forwards reported results/errors to another model round, retains all errors,
   and returns ERROR even if a later final answer arrives. Escaping executor
   exceptions remain fatal. There is no automatic retry or ID reuse.
3. The final allowed model round cannot execute tools. It may complete with a
   final answer; otherwise it returns LIMIT_REACHED with prior evidence. A real
   write is never performed with no model round left to inspect the result.
4. Task context binding occurs before the first model request. Wrong roots fail
   with zero model invocations. Tool effects/tests are reported from executor
   evidence rather than left permanently empty as in I1.

## Actual automated verification

Environment: Windows, Python 3.14.4, pytest 9.0.3. Python 3.12/3.13 and POSIX
execution were not independently exercised. No dependency installation occurred.

Initial baseline command: `python -m pytest -q` -> `73 passed in 0.92s`.

Final complete-suite command:

```text
python -m pytest -q -p no:cacheprovider
```

Actual final summary:

```text
199 passed in 17.93s
```

Exit code: 0. Passed: 199. Failed: 0. Skipped: 0. Warnings: 0.
The suite retains the 73 I1 cases and adds 126 I2 cases. Required I2 coverage
includes workspace initialization, valid reads, traversal and symlink rejection,
sensitive-file protection, listing, searching, valid/invalid patches, command
allowlist/timeout, permission denial, correlation and FakeModel integration.

The integration fixture reads a Python file, applies a hash-guarded correction,
runs a real passing pytest through ToolRuntime, feeds each result into FakeModel,
and returns the observed changed-file and test evidence through Agent Core.
It never operates on this repository's implementation files.

The first test attempt was interrupted after the sandbox account could not
access pytest's existing default temp directory. Authorized elevated execution
provided access to disposable fixtures; cache writing was disabled to avoid
cross-account ownership warnings. An intermediate run had two failures: a
Windows newline-dependent fixture hash and differing Windows stat/fstat ctime
semantics. Both were corrected, with content SHA-256, inode/device, size, mtime
and mode checks retained. All final tests pass; no implementation error remains.

## Git verification and scope

The worktree started clean at the approved I1 SHA. I2 changes are uncommitted on
`i2-workspace-tools`; nothing is staged, merged or pushed. Local main and the I2
branch HEAD remain `23cc2d84e3903d987e8758ff6508d27cab9da483`. No remote history
was changed. The I1 baseline and existing user work were not overwritten.

Tracked diff summary: 6 files changed, 482 insertions, 101 deletions. Eight new
files (two implementation helpers, five test/fixture files, this report) are
untracked and reviewed separately, since ordinary Git diffs omit them. The
modified files are README, pyproject, Agent Core, contracts, tools and one
existing round-limit test. Only project-scoped paths changed.

`git diff --check` and separate new-file whitespace checks pass. Source review
and secret-pattern scans find no added credentials or environment files; Python
and pytest caches remain ignored. Per-command Git settings handle sandbox
ownership/line endings without changing global settings.

Both approved document hashes still match the originals:

| Document | SHA-256 |
| --- | --- |
| `SCA-V0-Core-Architecture-v0.1.md` | `B48D4215CFA39C13732A14421C1FF227A0AC780E522CB05AE06A71B987DB1201` |
| `SCA-V0-Codex-I1-Task.md` | `0B21040F33E62FD343D6365587534F205EB306A7B3E6650072743E274085FC15` |

## Remaining limitations

- Trusted local projects only. Test/conftest code can access the host filesystem
  or network and spawn arbitrary processes; this is not an OS sandbox.
- Process-tree termination is best effort for detached or reparented descendants.
  Timeout bounds exclude OS process-creation delays and bounded cleanup time.
- Optimistic hash/identity checks detect ordinary concurrent changes, but do not
  provide an OS-wide atomic compare-and-swap against malicious race attacks.
- Sensitive-path protection is a conservative denylist, not universal secret
  detection. Unusually named files may contain secrets in a trusted project.
- Patching edits existing UTF-8 files only. There is no file creation/deletion,
  multi-file transaction, linked-root support or linked Git worktree support.
- Tests can have side effects; changed-files evidence inventories direct patch
  operations rather than every possible effect of arbitrary project test code.
- Context is in memory. Whole-task deadlines, cancellation, persistence, CLI,
  live models and later-stage capabilities remain deferred.

I2 is complete within its authorized trusted-project scope. No I3, I4,
Subagents, Skills, advanced memory, multi-agent or plugin framework was added.
**Stop after I2. I3 requires explicit approval.**
