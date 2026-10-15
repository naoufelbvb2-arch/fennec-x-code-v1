# Fennec X Code

I1 implements a deterministic, in-memory Agent Core foundation in this existing
project root. Authority: `SCA-V0-Core-Architecture-v0.1.md` and
`SCA-V0-Codex-I1-Task.md`. Both approved documents are preserved unchanged.

Requires Python 3.12+. Runtime dependencies: standard library only. Tests require
pytest 8 or 9 (declared in the `test` optional dependency).

Run from this directory with pytest already available:

```powershell
python -m pytest -q
```

The package can also be installed using the standard `pyproject.toml` build
configuration; no installation is needed to run the tests from the project root.

## Files and boundaries

- `sca/contracts.py`: typed dataclasses for tasks, requests, responses, calls,
  results, messages and minimal fake-tool definitions.
- `sca/model.py`: `ModelGateway.generate(request) -> ModelResponse` protocol and
  scripted `FakeModel`; each invocation records a detached request snapshot.
- `sca/tools.py`: `ToolExecutor.tool_definitions` and `execute(call) -> ToolResult`
  protocol, plus a scripted, recording `FakeToolExecutor`.
- `sca/agent.py`: `AgentCore(gateway, executor, max_model_rounds=25).run(task)`;
  contains no fake-specific logic. Context, counters, and IDs are local to a run.
- `tests/`: deterministic contract, fake, and Agent Loop acceptance tests.

Dependencies flow from Agent Core to the gateway/executor interfaces and shared
contracts; contracts import no other package modules. No workspace or CLI module
is needed in I1. `AgentTask.workspace_root` is metadata and is never accessed.

## Loop and status semantics

The first request contains the task, instructions, user message, advertised fake
tool definitions and model-round limit. A response has exactly one non-empty
variant: `final_answer`, `tool_calls`, or `error`. Core validates this boundary.

Tool batches are validated in full before any executor invocation. Names must be
advertised; argument names and exact Python types must match the minimal schema;
each call ID must be non-empty and unique throughout the task. Calls execute
sequentially. Assistant calls and correlated tool results enter the next request.
Every executed call has exactly one recorded result. A rejected batch executes
nothing; later calls in a failed batch are never attempted.

Task statuses:

- `COMPLETED`: a valid final answer ended the loop without an execution error.
  The summary is model text, not proof of project changes or passing tests.
- `ERROR`: invalid response/call, gateway error, failed tool, invalid executor
  result, or exhausted script. Errors and all prior tool evidence are retained.
- `LIMIT_REACHED`: the configured number of model invocations was consumed
  without a final answer. Tools requested in the last round still execute once.

Tool statuses are `SUCCESS` or `ERROR`. Results preserve `call_id`, output, error
and the `truncated` flag. A malformed/mismatched result or executor exception is
recorded as an error against the original call ID, with no invented success.
The first error terminates the run. There are no retries. Script exhaustion
fails explicitly rather than repeating the previous item.

`TaskResult` includes status, summary, changed files, tests run, errors, model
round count and tool results. `changed_files` and `tests_run` remain empty in I1:
the runtime cannot perform or verify either operation. Automated verification
of this implementation is separate from those per-task fields.

## Scope

The runtime and deterministic tests use no real LLMs, credentials, filesystem
tools, subprocesses, shell, Git, or external projects. Repository setup and
verification commands are development operations only. A guard test exercises
the loop with file opening, networking and command execution disabled.

Time limits, output-size enforcement, cancellation, permissions, workspace
access, real tools, persistence, live providers and CLI integration belong to
later authorized stages. There are no subagents, Skills, planners, plugin
systems or advanced memory features.

**I1 only — I2 is NOT authorized.**
