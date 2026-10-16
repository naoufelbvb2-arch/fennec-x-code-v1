# FENNEC X CODE — V0 FINAL ACCEPTANCE & FREEZE

## 01. Project Identity & Approved Baseline

| Item | Accepted record |
| --- | --- |
| Project | Fennec X Code |
| Release | V0 |
| Acceptance date | October 15, 2026 |
| Approved implementation commit | `cf3eb5479f30afdc86d88f436bc6787f7c3dcfd3` |
| Status | **V0 ACCEPTED — Verified Baseline** |
| Scope | Local, user-controlled, single-agent coding assistant for trusted projects |
| Repository | [fennec-x-code-v1](https://github.com/naoufelbvb2-arch/fennec-x-code-v1) |

Acceptance covers the tested V0 functionality and the reported live scenarios
recorded here. It is not unrestricted production approval, security certification,
or a guarantee of general coding-agent performance.

The implementation SHA identifies the accepted source tree before this separate
documentation-only freeze commit. The user explicitly authorized the acceptance
record and its publication directly to main. This workflow adds only this file;
it changes no implementation, test, interface, or approved specification.

## 02. Frozen V0 Architecture

The approved architecture retains four logical components:

| Component | Responsibility | Boundary |
| --- | --- | --- |
| Model Gateway | Build provider requests, convert tool schemas, normalize responses and provider errors | Does not execute tools or modify project files; implements `generate(ModelRequest) -> ModelResponse` |
| Agent Core | Run one sequential task, validate model/tool-call batches, correlate results, enforce limits, and return execution evidence | Uses existing contracts and gateway/executor interfaces; contains no provider-specific request logic or tool implementations |
| Tool Runtime | Advertise the five tools, validate inputs, enforce permissions, execute restricted operations, and return `ToolResult` | Does not call the model or plan the task; implements `tool_definitions`, `begin_task(task)`, and `execute(call)` |
| Workspace & Context | Validate the project root and paths, provide bounded file snapshots and in-memory task/session evidence | Does not invoke the model or execute system commands independently of Tool Runtime |

The CLI composes these components: User/CLI -> Agent Core -> Model Gateway,
Tool Runtime, and Workspace & Context. Tool Runtime uses workspace and restricted
command helpers. Shared contracts and the monotonic task-budget helper preserve
these boundaries; they do not add an orchestration framework or fifth component.

The existing CLI is the V0 user interface: `python -m sca` or the packaged
`fennec-x-code` entry point. Users explicitly choose the workspace, task, model,
endpoint, and authentication mode. No provider or model is automatically selected.

| Implemented tool | Restricted V0 behavior |
| --- | --- |
| `list_files` | List bounded, safe project paths |
| `read_file` | Read bounded UTF-8 text or line ranges and report a content hash |
| `search_text` | Search literal text within safe, bounded project files |
| `apply_patch` | Apply limited, hash-bound text edits to an existing file with concurrency checks |
| `run_command` | Execute approved testing/inspection argument lists with time/output limits and no free-form shell |

Safe reads follow existing defaults. Every write and command requires explicit
authorization for that operation. Command execution additionally requires an
explicitly trusted project; trust does not supply approval. Git preflight
inspection has its own permission check. No tool automatically commits, pushes,
installs dependencies, or resets user changes.

## 03. Implementation Milestones

The following are cumulative suite totals at each milestone. They are not
independent quantities and must not be added together.

| Milestone | Scope | Passing suite total | Actual Git implementation commit | Repository evidence |
| --- | --- | --- | --- | --- |
| I1 | Deterministic Agent Core | 73 | `23cc2d84e3903d987e8758ff6508d27cab9da483` | [I1 report](I1-IMPLEMENTATION-REPORT.md) |
| I2 | Restricted Workspace & Tools | 199 | `465125c261eda5c5ddc9fe9f304f9a8a4962958e` | [I2 report](I2-IMPLEMENTATION-REPORT.md) |
| I3 | Configurable Model Gateway & CLI | 319 | `7eea29d86ead894a86905028a4601dca5a222dff` | [I3 report](I3-IMPLEMENTATION-REPORT.md) |
| I4 | Reliability & Final Engineering Verification | 361 | `f4efe4693121e19b16c376242eec464218a44cc8` | [I4 report](I4-IMPLEMENTATION-REPORT.md) |
| DeepSeek Compatibility | Optional non-thinking mode | 374 | `cf3eb5479f30afdc86d88f436bc6787f7c3dcfd3` | [Compatibility precheck](docs/DEEPSEEK-COMPATIBILITY-PRECHECK.md) |

Commit identities and order were checked against repository history. Historical
reports remain intact as records of their original verification and publication
state. Their earlier statements that live verification or full acceptance was
pending are retained; the later user-supplied live results are recorded below.

## 04. Final Verification Evidence

Automated, live-model, and independent post-task evidence have different origins.
The live results in B–D were supplied by the user in the final acceptance brief.
This documentation workflow did not perform or repeat those live interactions or
the user's independent fixture test. No screenshots, live traces, or independent
fixture artifacts were found among tracked repository files; this report records
the supplied observations without claiming those underlying artifacts are committed.

### A. Automated Verification

The final previously reported regression command was:

```text
python -m pytest -q -p no:cacheprovider
```

Its previously reported result was:

```text
374 passed in 20.00s
```

That execution was performed and reported by Codex in the user's Windows
environment during compatibility promotion. It is historical execution evidence,
not a claim that the reviewing assistant independently reran those tests.

The separately required documentation-only freeze rerun was performed by Codex
after creating this report, using the same command on the Windows environment:

```text
374 passed in 16.28s
```

Exit code 0: 374 passed, 0 failed, 0 skipped, 0 warnings. This is a new automated
regression check for the documentation-only operation, not independent live-model
or post-task fixture verification. No production source or tests were modified.

### B. Live DeepSeek Read-Only Test

User-reported observed results:

| Observation | Reported result |
| --- | --- |
| Provider | DeepSeek |
| Model | `deepseek-flash` |
| Mode | Explicit thinking disabled |
| API interaction | Successful real API interaction |
| Tool activity | Model invoked `read_file` for `app.py`; tool result returned successfully |
| Continuation | Model continued after receiving the result and produced a final answer |
| Task status | `COMPLETED` |
| Model rounds | 2 |
| Changed files | None |
| Commands or tests executed | None |
| Reported errors | None |

This supports live connection and one read/tool-result continuation in the
reported configuration. It does not demonstrate write or command behavior by itself.

### C. Live DeepSeek Coding Test

The user reported a live coding task in a disposable Python project with a bug
that subtracted instead of adding. The model requested a bounded `apply_patch`;
the user explicitly approved the modification, and `app.py` was modified.
The model then requested `run_command`; the user separately approved execution,
and pytest reported one passing test.

| Observation | Reported result |
| --- | --- |
| Project | Disposable Python project |
| Defect | Subtraction instead of addition |
| Patch | Bounded `apply_patch`, explicitly approved by the user |
| Modified file | `app.py` |
| Test execution | Model requested `run_command`; user explicitly approved |
| Pytest outcome | One passing test |
| Task status | `COMPLETED` |
| Model rounds | 4 |
| Reported task errors | None |

This supports the complete reported edit/test task under explicit user
control. Model completion alone is not the acceptance evidence; the reported
tool effects, actual pytest execution, and independent check below also matter.

### D. Independent User Verification

Outside the agent loop, the user independently reported this exact `app.py`
content after the coding task:

```python
def add(a, b):
    return a + b
```

The user independently executed pytest and reported:

```text
1 passed in 0.42s
```

This is the user's post-task verification, distinct from the agent's own
`run_command` result and from the repository regression suite. It was not rerun
or independently inspected by this documentation workflow.

## 05. Acceptance Gates

PASS means supported within the cited tested/reported scope. It does not imply
universal correctness, all-provider compatibility, or coverage of untested failures.

| Gate | Status | Supporting evidence and scope |
| --- | --- | --- |
| Core execution and termination | PASS — tested scope | Deterministic Core tests cover final answers, bounded rounds, task deadlines, errors, and cancellation; reported live tasks terminate |
| Workspace and restricted tools | PASS — trusted-project scope | Automated root/path, protected-file, link, read/search/patch and command restriction tests; reported disposable live project |
| Real LLM connection | PASS — reported DeepSeek configuration | User reports successful DeepSeek `deepseek-flash` interaction with thinking explicitly disabled |
| Tool-call execution and correlation | PASS — tested/reported paths | Automated stable-ID and follow-up-history checks; reported live read result reaches the model and it continues |
| User-controlled sensitive-operation approval | PASS — tested/reported paths | Automated approval/denial and separate-operation checks; user reports approving the live patch and command separately |
| Code modification | PASS — reported bounded task | Reported authorized `app.py` patch and independently reported final addition implementation |
| Real test execution | PASS — reported fixture | Agent-invoked pytest reports one pass; user separately reports `1 passed in 0.42s` |
| Error and timeout handling | PASS — automated tested scope | Regression cases cover provider/tool failures, permission denial, deadlines, cancellation and command cleanup; not a claim of live coverage of every failure |
| Automated regression testing | PASS | Previously reported 374-case suite and required documentation-only freeze rerun recorded in 04.A |
| Independent post-task verification | PASS — user-reported | User verified final file content and separately ran pytest outside the agent loop |

The user's supplied live evidence completes the previously deferred live
verification for these scenarios. This acceptance does not retroactively claim
that earlier implementation stages performed live tests.

## 06. Supported Scope & Known Limitations

- V0 supports one sequential coding agent, one active task, and one trusted local
  project at a time. It uses a user-configured compatible LLM endpoint.
- Writes and commands require user approval. There is no automatic unrestricted
  execution and no OS-level sandbox. Hostile project/test code can access host
  resources or the network; the command allowlist does not guarantee protection
  against such code. Only trusted local projects are supported.
- Task deadlines are cooperative. Provider/command waits are capped, but blocked
  terminal input is checked when it returns; DNS, filesystem/OS calls and cleanup
  can exceed the nominal deadline. Subprocess-tree cleanup is best effort,
  particularly for detached or reparented descendants.
- File changes use optimistic content-hash/identity checks and atomic replacement,
  not an OS-wide compare-and-swap guarantee against malicious races. Patches are
  limited to existing bounded UTF-8 files; no multi-file transaction is provided.
- File reads, searches, directory traversal, model requests/responses and tool
  outputs are bounded. Truncation and incomplete command capture must not be
  interpreted as complete success. Protected-path checks are a conservative
  denylist, not universal secret detection.
- An interrupted tool can have uncertain effects. Observed change/test fields
  are execution evidence; model summaries do not manufacture evidence, and
  arbitrary command side effects are not fully inventoried.
- Sessions remain in memory. V0 includes no persistent advanced memory,
  Subagents, Skills, multi-agent coordination, plugin framework, or desktop UI.
- Reliable performance on large software repositories is not established.
  Live testing is limited to the selected DeepSeek configuration and the reported
  read-only and small coding scenarios. Other providers/models and broad coding
  performance have not been established by this acceptance.
- The adapter supports non-streaming text Chat Completions with bearer/no auth.
  Thinking-enabled tool conversations remain unsupported because
  `reasoning_content` is not preserved. The live configuration explicitly disabled
  thinking; the option remains user-selected and absent from default requests.
- Automated verification was performed on Windows with Python 3.14.4 and pytest
  9.0.3. All supported Python versions and operating systems have not been
  independently validated; Python 3.12/3.13 and POSIX are not established here.

Successful V0 acceptance is limited functional acceptance. It is not general
coding-agent capability validation or production security certification.

## 07. Official V0 Freeze Declaration

**FENNEC X CODE V0 — ACCEPTED AND FROZEN BASELINE**

The approved implementation baseline is:

```text
cf3eb5479f30afdc86d88f436bc6787f7c3dcfd3
```

This SHA identifies the accepted source implementation before adding the final
documentation-only commit. The freeze commit must have this exact parent and
add only `V0-FINAL-ACCEPTANCE-REPORT.md`; it does not replace or obscure the
implementation SHA. Its assigned documentation commit SHA is reported after
publication rather than embedded as a self-referential value in this file.

Existing source code, interfaces, security constraints, tests, approved reports,
and architecture documents are unchanged by this freeze operation. Both approved
specification files were verified byte-identical to the accepted Git baseline and
retain their original SHA-256 values:

| Approved specification | SHA-256 |
| --- | --- |
| `SCA-V0-Core-Architecture-v0.1.md` | `B48D4215CFA39C13732A14421C1FF227A0AC780E522CB05AE06A71B987DB1201` |
| `SCA-V0-Codex-I1-Task.md` | `0B21040F33E62FD343D6365587534F205EB306A7B3E6650072743E274085FC15` |

Further work must preserve the accepted V0 baseline through Git history,
regression tests, and explicit review. No reset, rebase, forced push, specification
rewrite, or automatic merge is part of this acceptance operation.

No live LLM request, live API-key access/configuration, provider provisioning,
model/dependency installation, or additional implementation is performed by this
documentation-only workflow. The earlier live observations are evidence supplied
by the user, not new actions authorized by this document.

## 08. Transition to Future Development

V0 foundational engineering is complete within the accepted scope above.
Further capabilities belong to a separately planned development phase following
**Build → Verify → Stabilize → Extend**.

New features require explicit specification, implementation, verification and
regression review while preserving the V0 baseline. V1 architecture and feature
selection are neither authorized nor frozen by this report. No V1 features,
architectural components or implementation tasks are defined here.

**Stop after publication of this documentation-only acceptance and freeze record.**
