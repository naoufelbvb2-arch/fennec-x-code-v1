# Fennec X Code: I4 final engineering verification

Date: October 15, 2026. Workspace: `C:\Users\Laptop\Desktop\fennec x code v1`.
Branch: `i4-final-verification`.
Approved I3 baseline / current HEAD: `7eea29d86ead894a86905028a4601dca5a222dff`.

**Result: deterministic engineering verification passes. Full V0 acceptance is
not claimed. Live-model verification is explicitly deferred and was not run.**

## 1. Baseline verification

Verified a clean initial worktree on i3-model-cli, its local/GitHub commit at the
approved I3 SHA, and main at approved I2. Re-ran the complete existing suite:

```text
python -m pytest -q -p no:cacheprovider
319 passed in 7.26s
```

Only after that passed, switched to main, fast-forwarded to approved I3, pushed
normally, and created i4-final-verification. Independently verified GitHub main
and i3-model-cli both at `7eea29d86ead894a86905028a4601dca5a222dff`.
No history was rewritten. No I4 changes were merged into main or published.

## 2. Files modified and created

| File | Change | Reason |
| --- | --- | --- |
| `sca/agent.py` | Modified | Task deadlines and structured cancellation retaining observed evidence |
| `sca/cli.py` | Modified | Share deadline, validate --task-timeout, display cancellation with exit 130 |
| `sca/commands.py` | Modified | Cap commands by remaining task time; protect reader startup with cleanup |
| `sca/contracts.py` | Modified | Add CANCELLED to documented/typed TaskResult statuses |
| `sca/provider.py` | Modified | Cap requests by task time; whole-exchange watchdog and socket cleanup |
| `sca/tools.py` | Modified | Deadline checkpoints after permissions, during search and before patch commit |
| `sca/workspace.py` | Modified | Optional deadline checks for text reads and directory scans |
| `README.md` | Modified | Document I4 behavior, composition, limits and deferred acceptance |
| `sca/limits.py` | Created | Small shared monotonic deadline primitive |
| `tests/test_reliability.py` | Created | 28 focused reliability/CLI cases |
| `tests/test_end_to_end.py` | Created | 14 complete coding-task and failure scenarios |
| `I4-IMPLEMENTATION-REPORT.md` | Created | This verification and acceptance record |

All original I1/I2/I3 tests and fixtures remain unchanged. ModelGateway,
FakeModel, tool schemas, command allowlist, dependencies, historical reports and
both approved documents remain unchanged. No unrelated files were modified.

## 3. Issues discovered and fixes implemented

### Missing whole-task deadline

The approved architecture specifies an initial ten-minute task limit. I3 had a
round limit and per-operation timeouts, but no whole-task elapsed-time check.
A deterministic fake-clock regression demonstrated that a final answer arriving
after 601 seconds was incorrectly accepted as COMPLETED.

Added TaskBudget with a default 600-second monotonic deadline. Core starts it
before executor task setup, checks model/tool boundaries, refuses late final
answers and stops between sequential calls. Expiry produces LIMIT_REACHED with
prior tool/change/test evidence. CLI shares the same instance with all real
components and exposes a positive, finite --task-timeout option. Requests and
commands receive the smaller of their own timeout and remaining task time.

Permission wait time counts: the runtime rechecks after a grant, preventing an
old answer from starting a write/command after expiry. Directory iteration and
search have checkpoints. Patches check before replacement, and safe temporary
cleanup still works after expiry. Regression tests verify these boundaries.

This is cooperative deadline enforcement, not a hard real-time guarantee.
A blocked terminal input is checked when it returns and remains interruptible
with Ctrl+C. DNS, filesystem calls, process creation and cleanup cannot all be
forcibly preempted. A custom gateway/executor must cooperate with the budget;
Core cannot safely terminate arbitrary Python code. These limits remain open.

### Cancellation discarded the structured task result

Previously KeyboardInterrupt escaped Core; CLI returned 130 with a generic
message, losing accumulated structured evidence. The pre-fix regression run
confirmed this escape and was interrupted by pytest after the deadline failure.

Core now returns CANCELLED, retaining completed tool results and observed
changed_files/tests_run. An interrupted in-flight tool receives one correlated
ERROR with an explicitly uncertain outcome; no result or side effect is invented
as successful. Its call ID and uncertainty also appear in TaskResult.errors,
which the CLI displays. CLI preserves exit 130 and the interruption message.
No rollback, retry, or cancellation orchestration framework was added.

### Socket inactivity timeout did not bound a trickling exchange

The existing HTTP timeout bounded individual socket waits. A server sending
occasional bytes could prolong headers/body capture beyond that timeout.

Added a daemon watchdog for the HTTP exchange that shuts down the active socket
at expiry, cancels itself on every exit, and normalizes expiry to a sanitized
timeout. It retains the socket reference when HTTPConnection transfers ownership
to an HTTPResponse for Connection: close. Mocked timer/socket tests cover normal
and detached connection ownership and shutdown-induced read errors. No actual
endpoint or socket connection was used for this verification.

### Reader startup occurred outside subprocess cleanup protection

An interrupt during Thread.start happened before the runner's try/finally, so a
launched command could outlive the interrupted call. Moved startup inside cleanup
protection and avoided joining a thread that never started. A regression injects
KeyboardInterrupt at startup of a real disposable pytest child, verifies the
child is reaped and stdout closes. Existing command timeout/output-limit tests
continue to pass. Process-tree termination remains best effort at OS level.

## 4. Contracts and architectural compatibility

- ModelGateway.generate(ModelRequest) -> ModelResponse and ToolExecutor's
  definitions/begin_task/execute protocol are unchanged.
- TaskResult.status gains CANCELLED. Existing COMPLETED, ERROR and LIMIT_REACHED
  meanings, fields and evidence aggregation are preserved. CLI maps CANCELLED
  to 130; either round or task expiry maps to 3.
- TaskBudget(seconds=600, clock=monotonic) provides start(), remaining(), check()
  and timeout(operation_seconds). TaskLimitExceeded has fixed, credential-free
  text. Core resets the deadline for each sequential task.
- AgentCore accepts optional max_task_seconds=600 and budget=None. Real gateway,
  runtime, command runner and workspace accept optional budget= parameters.
  Programmatic callers should share one budget, as CLI does; Core alone only
  controls its own checkpoints around custom implementations.
- The helper contains no project-component imports or orchestration. Core has
  no direct provider/workspace/command implementation imports; gateway never
  invokes tools; runtime/workspace never invoke the model. Direct import checks
  verify these boundaries. No new framework or agent capability was introduced.

## 5. End-to-end and failure verification

Each complete scenario runs against a disposable trusted Python project with
a pre-existing user comment and an unrelated uncommitted notes file.
Both FakeModel and the compatible adapter with scripted provider responses:

1. List the project, read app.py and search for the defective arithmetic.
2. Return correlated results to the next model round.
3. Request and apply a separately authorized SHA-256-bound patch.
4. Request and execute separately authorized pytest when that path is reached.
5. Feed observed results back and return a structured TaskResult.

The success path verifies actual passing child-test output and precise evidence.
The six failure variants cover failed pytest, denied patch, connection failure,
malformed model response, cancellation after an observed patch, and command
timeout. Each verifies prior user content/notes remain intact, failed operations
do not become success, no automatic retry occurs, and patch/test caches or
temporary artifacts are not left in the fixture. Existing tests additionally
cover traversal, links, protected files, concurrent changes, invalid patches,
call/result correlation, unknown tools, shell rejection and invalid arguments.

## 6. Actual test results

Environment: Windows; Python 3.14.4; pytest 9.0.3. No dependencies installed.

After the initial fixes, the affected regression selection passed 247 tests in
5.73s, and the first new I4 selection passed 37 tests in 4.92s. The expanded suite
then passed 360 tests in 12.48s. Final cancellation-report review added one case.

Final complete-suite command and actual output:

```text
python -m pytest -q -p no:cacheprovider
........................................................................ [ 19%]
........................................................................ [ 39%]
........................................................................ [ 59%]
........................................................................ [ 79%]
........................................................................ [ 99%]
.                                                                        [100%]
361 passed in 12.16s
```

Exit 0: **361 passed, 0 failed, 0 skipped, 0 warnings**. All 319 original cases
pass unchanged, plus 42 I4 cases. python -m sca --help also exits 0 and advertises
the deadline option without any model request. No code changed after this final
suite; only this report was added.

## 7. Security verification

- Credentials still come only from the user's selected environment variable;
  no credentials/provider/endpoint are selected or created by I4.
- Existing token repr hiding, console redaction, terminal-control escaping,
  suppressed HTTP debug logging, fixed provider errors, and unread HTTP error
  bodies are retained and regression-tested. New watchdog code emits no logs.
- URL validation, verified TLS, rejection of credential/query/fragment URLs,
  loopback-only cleartext bearer auth, no redirects/proxies/retries are retained.
- Response validation, whole-batch tool validation, stable/unique call IDs,
  fail-fast defaults and final-round side-effect rejection continue to pass.
- Every write/command still needs explicit authorization; trust never supplies
  approval. Shell execution remains disabled, argv/command allowlist unchanged,
  subprocess environment restricted and output capture bounded.
- Both approved documents were compared byte-for-byte to I3 Git blobs and their
  original SHA-256 hashes. No architecture document was edited.
- Reviewed all changed/new files, whitespace and exact Git path set. Secret/key
  pattern checks identify no real credential material; literal test tokens are
  synthetic fixtures. No environment files, generated artifacts or caches are
  in the change set. Existing ignored runtime caches are not publication files.
- The existing autouse guard blocks real HTTP(S) provider connections. Provider
  responses, timer/socket behavior and errors are mocked. Real command execution
  only runs known disposable trusted fixtures. No live LLM test was attempted.

## 8. V0 acceptance gates and remaining limitations

| Gate | Deterministic status | Qualification |
| --- | --- | --- |
| G1 Core | PASS | Termination, final rounds, time limits, failures, cancellation, correlation |
| G2 Workspace/Tools | PASS | Restricted trusted-project reads/search/patch/commands and rejection cases |
| G3 Coding Task | PASS with FakeModel/mocks | Real disposable patch and pytest verified; live-model portion DEFERRED |
| G4 Failure/Safety | PASS for tested paths | Prior changes retained; cooperative/OS timing limitations remain |
| G5 Regression | PASS | All 361 tests; original tests untouched; complete diff/path review |
| Required live-model verification | DEFERRED / NOT RUN | User provider selection and explicit authorization still required |
| Full V0 acceptance | PENDING | Cannot be declared without live-model verification |

Only trusted local projects are supported. This is not an OS/network sandbox;
trusted pytest code can access the host/network. Detached descendants may evade
best-effort termination. Optimistic patch checks are not an OS-wide compare-and-
swap guarantee. An interrupted tool may have unobserved effects; manual inspection
is needed in that case. Command side effects beyond direct patches are not fully
inventoried. Summaries remain untrusted model text, while change/test fields are
observed execution evidence. Sessions stay in memory. No new persistence layer
was added. Python 3.12/3.13 and POSIX were not independently exercised here.
The adapter remains non-streaming text Chat Completions with bearer/no auth;
real endpoint/model compatibility and model-driven coding performance are unverified.

No provider was chosen/configured, key generated, account created, model installed
or downloaded, server started, paid inference run, or live API request made.
The existing optional live smoke runbook remains deferred until user authorization.

## 9. Final Git state

Current branch: i4-final-verification.
HEAD / approved baseline: `7eea29d86ead894a86905028a4601dca5a222dff`.
Local and GitHub main remain at that approved I3 commit. I3 branch is unchanged.

I4 changes are local and uncommitted: 8 modified files and 4 new files listed
above, nothing staged. No I4 commit exists yet; this HEAD SHA identifies the
verified starting baseline, not a claim that I4 was committed. No I4 push or
merge was performed. Tracked diff: 8 files, 241 insertions, 104 deletions; new
helper, two test modules and this report are additional untracked files.

Original approved document SHA-256 values, verified unchanged:

```text
SCA-V0-Core-Architecture-v0.1.md
B48D4215CFA39C13732A14421C1FF227A0AC780E522CB05AE06A71B987DB1201
SCA-V0-Codex-I1-Task.md
0B21040F33E62FD343D6365587534F205EB306A7B3E6650072743E274085FC15
```

No subagents, Skills system, advanced memory, plugin framework, multi-agent
coordination, desktop UI, or additional agent capability was implemented.
**Stop after I4 verification. Full V0 acceptance and further work remain pending
explicit user authorization and the required live-model evidence.**
