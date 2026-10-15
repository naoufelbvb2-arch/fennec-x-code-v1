# SCA-V0 — Codex Implementation Task I1
## Core Skeleton + Deterministic Agent Loop

**Authority:** `SCA-V0-Core-Architecture-v0.1.md` (APPROVED, 2026-10-15).
**Current authorized phase:** I1 only.
**Status:** READY TO SEND TO CODEX. No execution is claimed by this file.

## Task

Implement **I1 only** of SCA-V0 in a **new, isolated local repository**, separate from DGCA, DGCA LITE, and the previous AI Coding Agent repository.

The goal is to establish working, testable code for the basic single-agent loop with a deterministic fake model. Do **not** implement I2, I3, I4 or future agent capabilities.

### Read first

Read the approved architecture document in full. If it is not present in the workspace, stop without modifying any files and report that the authoritative specification is missing.

### Implementation scope

1. Use Python 3.12+ and pytest with a minimal `pyproject.toml` and straightforward package structure.
2. Create small, explicit typed contracts (use standard Python types/dataclasses unless a stronger dependency is demonstrably necessary):
   - `AgentTask`, `ModelRequest`, `ModelResponse`, `ToolCall`, `ToolResult`, `TaskResult`.
   - Responses must distinguish final answer, tool calls and error; validate invalid/ambiguous responses.
   - Stable `call_id` links each call to exactly one result.
3. Create the Model Gateway interface/protocol and a **deterministic FakeModel** capable of returning a scripted sequence of responses; no network or real API integration.
4. Create the Agent Core sequential loop:
   - initialize a task and minimal in-memory session context;
   - invoke the gateway and parse response;
   - when tool calls are requested, pass them in order to a **fake/recording tool executor**, collect results and feed them back to the next model invocation;
   - when final response arrives, return a structured TaskResult;
   - enforce a configurable maximum model-round limit;
   - produce explicit error/limit states; never claim an unexecuted tool succeeded.
5. Provide a small test suite that exercises the core loop without real LLMs, filesystem modifications or subprocess commands.

### Required deterministic tests

- Immediate final answer: exactly one model invocation, no tools.
- One tool call followed by final answer: correct order, `call_id` and tool result visible on next model request.
- Multiple tool calls: processed sequentially, each result associated with the right call.
- Unknown tool, invalid arguments, or missing call id: rejected safely, without invoking the fake executor.
- Gateway error and malformed response: explicit failure, no false success.
- Reaching maximum rounds: terminates with a limit status.
- No accidental tool re-execution after an error.

The exact response and status values should be minimal, consistent, and documented in code/tests.

### Explicitly prohibited for I1

- Real LLM API adapters or credentials.
- Real filesystem search/read/write, patching, Shell, Git operations.
- CLI interaction beyond an optional minimal non-executing demo; CLI implementation belongs to I3.
- Multi-agent, subagents, Skills, memory engines, planners, plugin registry, vector databases, dashboard/UI.
- Speculative extension frameworks, premature abstraction or unrelated refactors.
- Modifying any existing DGCA/DGCA LITE/old AI Coding Agent repositories.
- Commits to remote branches, push, or PR creation without separate authorization.

### Quality and verification

- Keep module dependencies one-directional, with Agent Core importing interfaces/contracts but no provider-specific logic.
- Clear type hints, compact and readable code, descriptive exceptions/errors, no silent success paths.
- Run the test suite and show its **actual** output.
- Run `git status --short` and `git diff --check`; review changed paths.
- On completion, produce a concise implementation report with:
  1. Exact local repo/path used and branch (if a repo was initialized).
  2. Files created/modified.
  3. Contracts and loop implemented.
  4. Actual test command, passed/failed counts, and known limitations.
  5. Issues requiring decisions, if any.
  6. Explicit note: **I1 only — I2 is NOT authorized**.

### Stop condition

If a significant ambiguity blocks correct I1 implementation, do not expand scope or invent a new architecture. Implement all safely unambiguous parts, identify the narrow blocker and propose the smallest resolution.

**Success criterion:** a deterministic, repeatable **FakeModel → Agent Core → Fake Tool Executor → Agent Core → FakeModel** flow passes tests without invoking external models or touching real projects.
