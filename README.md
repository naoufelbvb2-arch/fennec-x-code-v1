# Fennec X Code

I1 provides a deterministic Agent Core. I2 adds Workspace & Context and five
restricted local tools. I3 adds a user-configured compatible model adapter and
CLI through those same boundaries. I4 verifies complete tasks and hardens task
deadlines, interruption reporting, and timeout cleanup. The approved
`SCA-V0-Core-Architecture-v0.1.md` and `SCA-V0-Codex-I1-Task.md` remain unchanged.

Requires Python >=3.12. Runtime code uses only the standard library. The test
extra requires pytest 8 or 9; command test execution also requires an installed
pytest outside the target workspace. No dependencies are installed by the tools.

Run the complete I1, I2, I3 and I4 suite from this directory:

```powershell
python -m pytest -q -p no:cacheprovider
```

Tests use disposable pytest projects, including real file operations and child
pytest processes. They require access to the system temp directory. Windows
link tests use junctions if creating a symbolic link requires extra privileges.

## Modules and interfaces

- `sca/contracts.py`: the six required dataclasses, messages, and tool schemas.
- `sca/model.py`: unchanged `ModelGateway.generate(request) -> ModelResponse`
  and scripted FakeModel.
- `sca/provider.py`: `CompatibleModel(config, transport=None)` implements that
  protocol with non-streaming Chat Completions requests. Transport is injectable;
  tests mock responses and prohibit real provider HTTP connections.
- `sca/cli.py`: minimal composition root, console activity and one-operation
  authorization prompts. `python -m sca` runs it without package installation;
  the packaged entry point is `fennec-x-code`.
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
  continue_on_tool_error=False, max_task_seconds=600, budget=None).run(task)
  -> TaskResult`.
- `sca/limits.py`: `TaskBudget(seconds=600, clock=monotonic)` and
  `TaskLimitExceeded`. A shared monotonic deadline primitive, without provider,
  workspace or tool dependencies. It performs no orchestration.

Dependencies flow from Agent Core to interfaces and contracts; the tool runtime
uses workspace and command helpers, and those helpers never invoke the model.
`ToolDefinition` now supports `optional_argument_types` alongside required exact
types. Unknown arguments are rejected. `ToolResult` adds optional tuple fields
`changed_files` and `tests_run`; Core aggregates this executor evidence rather
than parsing claims in model text. Existing constructors keep their defaults.
I3 adds optional `ToolDefinition.array_item_schemas` metadata for provider array
items, so patch edit objects and argv strings have meaningful JSON schemas.
It leaves existing argument validation and execution signatures intact.

## User-selected model configuration

No model, provider or API endpoint is selected by default. Missing configuration
prints a clear message and stops before any request. Fennec does not create
accounts/keys, install providers, download models, start servers or provision
hosted services. No live-model test was run during I3 implementation.

Supply these settings yourself, using CLI flags or environment variables:

| Setting | CLI | Environment | Default |
| --- | --- | --- | --- |
| Model | `--model` | `FENNEC_MODEL` | Required, none selected |
| API base URL | `--api-base-url` | `FENNEC_API_BASE_URL` | Required, none selected |
| Authentication | `--auth none` or `--auth bearer` | `FENNEC_AUTH` | `none` |
| Credential variable name | `--api-key-env NAME` | Reads the selected variable only | `FENNEC_API_KEY`, only sent with bearer auth |

The URL is an API base, including any required prefix such as `/v1`; the adapter
appends `/chat/completions`. CLI settings override their corresponding environment
settings. Credentials come from the selected environment variable, never an API
key command-line argument or an automatically read configuration/environment file.
Unrelated provider environment variables are not discovered. Local compatible
endpoints can use `--auth none` without any credential. Bearer auth requires HTTPS
or a loopback HTTP endpoint. URL userinfo, queries and fragments are rejected.

For an endpoint supporting the `thinking` extension, explicitly select
`--disable-thinking` to send `{"thinking":{"type":"disabled"}}` at the top
level of every request. Programmatic callers use
`ModelConfig(..., disable_thinking=True)`. The default omits the field, including
for DeepSeek URLs; no provider/model is detected or selected automatically.
There is no thinking-enabled option: this adapter does not preserve
`reasoning_content` across tool turns. See the
[DeepSeek compatibility precheck](docs/DEEPSEEK-COMPATIBILITY-PRECHECK.md) for
documented requirements and verification limitations. No live test is authorized
by selecting this option.

Once you have deliberately selected/configured your provider, invoke a task with
`python -m sca --workspace PATH --task "Your instruction"`, adding model, URL and
auth flags if you did not configure them in the environment. `--help` lists all
options. The CLI shows the selected endpoint/model, tool calls, correlated
results, final status, observed changed files, tests and errors. The selected
credential is redacted from console output, and terminal control characters in
model/tool text are escaped. Raw HTTP bodies/transport exceptions are never logged.

Safe reads require no prompt. Every write and command shows its concrete
arguments and requires a separate `y`/`yes`; all other replies or EOF deny it.
There is no approve-all flag. Git preflight commands require their own approval.
Commands also require `--trusted-project`; that flag does not approve commands
automatically. Use disposable trusted projects for smoke tests.

`--max-model-rounds` defaults to 25, `--model-timeout` to 30 seconds per HTTP
exchange, `--command-timeout` to 10 seconds, and `--task-timeout` to 600 seconds.
Exit statuses are 0 for a completed loop, 1 for failure, 2 for configuration/access
errors, 3 for a round/task limit, and 130 for interruption. Core returns a
structured `CANCELLED` result retaining earlier tool/change/test evidence; an
interrupted tool has a correlated error describing its uncertain outcome.
Earlier changes are retained, and interrupted operations are never retried.

The CLI shares one TaskBudget with Core, gateway, runtime, runner and workspace.
Core starts it for each task before executor setup, checks it at model/tool
boundaries, and refuses late final answers. Provider/command waits are capped by
remaining time. HTTP capture has a watchdog that shuts down the active socket,
including a response that trickles bytes. File scans have deadline checkpoints;
patching checks again immediately before replacement and still cleans temporary
files after expiry. A delayed permission answer cannot authorize work after the
deadline. Programmatic composition should pass the same `budget=` instance to
these components; Core alone cannot preempt an arbitrary custom implementation.

Deadline enforcement is cooperative around synchronous local operations. A
terminal prompt is interruptible with Ctrl+C, but expiry is checked when input
returns; it does not forcibly dismiss a blocked prompt. DNS resolution, filesystem
system calls and process-tree cleanup can outlast the nominal deadline. This is
not a hard real-time execution guarantee.

The adapter sends JSON function schemas, serializes assistant calls followed by
their `tool_call_id` results, and normalizes final answers/tool calls/errors.
Malformed JSON, duplicate keys/IDs, non-finite numbers, refused/incomplete turns
and malformed calls fail explicitly before tool execution. A tool-turn preface
is not treated as a final answer. HTTP errors, timeouts and failed connections
are sanitized and never retried; redirects are not followed. TLS verification is
enabled, ambient proxy configuration is not used, and response capture is bounded
to 1 MiB (request bodies to 2 MiB). Streaming, Responses API, tool-free models,
non-bearer authentication and provider-specific features are outside this adapter.

The wire format follows the official
[OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).
Compatibility must still be verified with your chosen provider. The optional
[manual smoke procedure](docs/I3-LIVE-SMOKE.md) is deferred until you select and
configure a provider and explicitly approve live requests.

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
`changed_files`. Sessions remain in memory. Live-model behavior is unverified
until a provider is selected and testing is explicitly authorized. Automated
verification uses FakeModel and mocked responses only; full V0 acceptance is
pending that live verification. No subagents, Skills, planners, plugins,
advanced memory or multi-agent features are implemented.

See `I4-IMPLEMENTATION-REPORT.md` for the verification record and acceptance gates.
**Stop after I4 verification. Further work requires explicit authorization.**
