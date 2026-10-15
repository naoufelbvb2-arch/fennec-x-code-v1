# Fennec X Code: I3 implementation and verification

Date: October 15, 2026. Authorized scope: I3, including user-controlled providers.
Workspace: `C:\Users\Laptop\Desktop\fennec x code v1`.
Implementation branch: `i3-model-cli`.
Approved I2 baseline: `465125c261eda5c5ddc9fe9f304f9a8a4962958e`.

I3 provides a configurable model client and CLI ready to connect to an endpoint
chosen by the user. No provider was selected or provisioned. No live LLM request,
credential acquisition, account creation, hosted API deployment, model download
or model-server startup occurred. Live-model smoke testing remains deferred.

## Phase A: baseline promotion

Verified a clean worktree, local/remote main at approved I1
`23cc2d84e3903d987e8758ff6508d27cab9da483`, and local/remote i2-workspace-tools
at approved I2 `465125c261eda5c5ddc9fe9f304f9a8a4962958e`.

Before promotion, executed:

```text
python -m pytest -q -p no:cacheprovider
199 passed in 13.82s
```

Fast-forwarded main with `git merge --ff-only i2-workspace-tools`, pushed main
normally, and verified GitHub main at the approved I2 SHA. No merge commit or
history rewrite was created. Created `i3-model-cli` from that exact baseline.

## Files created and modified

| File | Change | Purpose |
| --- | --- | --- |
| `sca/provider.py` | Created | User model configuration, HTTP transport, schemas, history/response conversion, CompatibleModel |
| `sca/cli.py` | Created | CLI validation/composition, visible tools, individual permissions, credential-safe console |
| `sca/__main__.py` | Created | `python -m sca` entry point |
| `sca/contracts.py` | Modified | Optional array item schema metadata, with backward-compatible defaults |
| `sca/tools.py` | Modified | Advertise nested edit/argv shapes and explicit runtime constraints; execution unchanged |
| `pyproject.toml` | Modified | Packaged `fennec-x-code` entry point; no new dependencies |
| `tests/conftest.py` | Modified | Mock provider responses/transports and an automatic guard against live HTTP connections |
| `tests/test_provider.py` | Created | Configuration, request/schema conversion, parsing, errors, transport and credential tests |
| `tests/test_cli.py` | Created | CLI arguments, approvals/denials, activity, exit states and integration |
| `README.md` | Modified | I3 configuration, interfaces, usage and compatibility limits |
| `docs/I3-LIVE-SMOKE.md` | Created | Optional manual smoke procedure; deferred and never auto-discovered/executed |
| `I3-IMPLEMENTATION-REPORT.md` | Created | This verification record |

Agent Core, ModelGateway/FakeModel, Workspace, command execution, and all
pre-existing test case files remain unchanged in Git. Both approved documents
and the historical I1/I2 reports are preserved.

## Model adapter interface

- `CompatibleModel(config: ModelConfig, transport: JsonTransport | None = None)`
  structurally implements the existing
  `ModelGateway.generate(request: ModelRequest) -> ModelResponse` protocol.
- `ModelConfig(model, api_base_url, api_key=None, timeout_seconds=30,
  max_response_bytes=1048576)` has no default model or endpoint and hides its
  credential in repr. Its environment factory reads explicit model/URL/auth
  settings and only the selected credential variable.
- `JsonTransport.post(url, headers, body, timeout=..., max_bytes=...)` is the
  narrow injectable HTTP boundary; production uses HttpTransport, tests use
  scripted responses or mocked connection objects. This is no provider registry.
- `HttpResponse(status, body)` separates transport from provider normalization.
  No response-body logging is provided.
- `tool_schema(definition)`, `build_payload(request, model)`, and
  `parse_response(body)` perform provider wire-format conversion at the gateway.

Wire compatibility targets non-streaming Chat Completions function calling,
using the official
[OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).
That protocol choice does not select a provider, account, model or paid service.

The user supplies the API base prefix; `/chat/completions` is appended. Requests
include the user-selected model, system instructions, conversation, function
schemas and automatic tool choice. Tools are omitted for a request with none.
Assistant calls use JSON argument strings and stable IDs; tool messages use
matching `tool_call_id` values and serialized ToolResult evidence. Orphaned,
duplicate or incomplete request histories are refused before network I/O.
Task workspace/session metadata is not automatically added to the wire payload.
User task text and requested file/tool content necessarily go to the chosen API.

JSON schemas retain required and optional argument names, exact scalar types,
and reject extra properties. `ToolDefinition.array_item_schemas`, defaulting to
an empty mapping, advertises `argv` string items and patch `{old,new}` objects.
Existing constructors and runtime argument validation remain compatible. No
tool-name-specific schema logic was placed in the gateway.

Response parsing validates one completed assistant choice and normalizes it to
one final answer, tool-call tuple or explicit error. It rejects malformed JSON,
duplicate JSON keys, non-finite numbers (including overflow), missing/duplicate
call IDs, invalid argument JSON, unsupported call types and refused/incomplete
turns. Text accompanying a valid tool turn is treated as a preface, not a final
answer. Nullable unused legacy fields are tolerated, but actual legacy function
calls are not executed. Unknown tools and argument constraints still pass
through the existing Core/runtime safety boundaries before any execution.

HTTP is one attempt with bounded capture, verified TLS for HTTPS, no redirects
or ambient proxies, and socket operation timeouts. The 2 MiB request cap and
configured response cap are enforced. Inherited HTTP debug logging is disabled.
HTTP error bodies are not read/logged; fixed status/timeout/transport messages
avoid exposing raw provider bodies, headers or exception strings. No automatic
retry can duplicate a provider request or tool operation.

## User configuration and CLI

Supported entry points: `python -m sca` and the packaged `fennec-x-code` script.
Installation is not needed for the former; no package installation was performed.

| Setting | Flag | Environment/default |
| --- | --- | --- |
| Workspace | `--workspace PATH` | Required existing project |
| Task | `--task TEXT` | Required non-empty instruction |
| Model | `--model NAME` | `FENNEC_MODEL`; no fallback model |
| API base | `--api-base-url URL` | `FENNEC_API_BASE_URL`; no fallback endpoint |
| Auth mode | `--auth none` / `--auth bearer` | `FENNEC_AUTH`, default none |
| Credential variable | `--api-key-env NAME` | Default FENNEC_API_KEY, sent only with bearer auth |
| Project trust | `--trusted-project` | False by default; never bypasses prompts |
| Model rounds | `--max-model-rounds N` | Default 25 |
| Model socket timeout | `--model-timeout SECONDS` | Default 30, positive/finite, max 600 |
| Command timeout | `--command-timeout SECONDS` | Default 10, positive/finite, max 600 |

Flags override corresponding environment settings. No unrelated provider key
variables, local credential files or dotenv files are discovered. Unauthenticated
local endpoints need no API key. Bearer authentication requires a selected
non-empty, header-safe environment value and HTTPS or a loopback HTTP endpoint.
URLs containing credentials, query data or fragments are rejected. No literal
API-key argument is accepted; abbreviated CLI options are disabled.

Missing model/endpoint configuration stops with a clear message before workspace
setup or a request. Workspace, task and numeric options are validated before the
gateway runs. The CLI displays selected endpoint/model, tool requests/results
with IDs, truncation, and a final structured status/summary/change/test/error
report. Existing TaskResult status meanings and evidence sources are retained.

ConsoleAuthorization shows full concrete sensitive-operation arguments. Only an
explicit y/yes grants that one call; other answers and EOF deny it. No approvals
are cached and no approve-all flag exists. Git-status preflight has its own
approval. Commands additionally require --trusted-project and remain within the
existing allowlist. ConsoleExecutor decorates the existing ToolExecutor solely
for activity display; it performs no planning, selection or scheduling.

The configured credential is redacted from console output (including final
model text), and terminal/bidi controls are escaped. Argument errors do not echo
potentially pasted credentials. CLI exit codes are 0 completed, 1 failed,
2 configuration/access error, 3 round limit, and 130 interruption. Prior changes
are retained on failure or interruption.

## Actual verification

Environment: Windows, Python 3.14.4, pytest 9.0.3. No new dependencies installed.

Final complete-suite command:

```text
python -m pytest -q -p no:cacheprovider
```

Actual final output:

```text
........................................................................ [ 22%]
........................................................................ [ 45%]
........................................................................ [ 67%]
........................................................................ [ 90%]
...............................                                          [100%]
319 passed in 18.43s
```

Exit code 0; 319 passed, 0 failed, 0 skipped, 0 warnings. The original 199 I1/I2
cases pass unchanged; 120 I3 cases verify provider request construction, nested
schemas, parsing, correlation, provider errors, authentication configuration,
CLI validation, per-call approval/denial, and integration.

Provider tests use scripted transport responses or mocked HTTP connection
objects. An autouse guard fails any actual HTTP(S) connection attempt through
the provider transport. No real endpoint, authentication credential or paid API
is required. Real file/command tests operate only on disposable trusted fixtures.
One complete CLI integration reads a Python file, requests an approved hash-bound
patch, runs an approved real pytest fixture, receives correlated results through
the wire adapter, and returns observed change/test evidence. Read-only calls
need no approval; denial, EOF and trust-marker tests prove fail-closed behavior.

Additional direct checks: `python -m sca --help` exits 0 without a model request.
An invocation with an explicitly empty configuration returns 2 and states:
`LLM configuration missing: set --model/FENNEC_MODEL and --api-base-url/FENNEC_API_BASE_URL. No request sent.`

The first development run found one new-test failure: argparse abbreviation
could interpret --api-key as --api-key-env. Disabling abbreviations fixed it.
All subsequent checks passed. LF endings of edited files were kept consistent
with baseline blobs to avoid unrelated Windows checkout line-ending changes.
No implementation error remains; live-model behavior is deliberately unverified.

## Live-model verification

Not run. No provider/model was chosen, configured, installed or provisioned by
this work. No live LLM requests or charge-incurring smoke test occurred.
`docs/I3-LIVE-SMOKE.md` provides optional manual read-only and coding/test checks.
It is a runbook, not an automatically executed test. The user must select the
provider/configuration and explicitly approve live requests before it is used.
The primary deliverable is readiness to connect under existing security rules,
not a claim that an unselected endpoint has been verified end to end.

## Architecture compatibility and remaining limitations

The existing four boundaries remain: CLI -> Agent Core -> Model Gateway / Tool
Runtime / Workspace & Context. sca/agent.py and sca/model.py have no I3 changes.
The gateway implements the current protocol and returns the existing contracts.
The only contract addition is optional array-item schema metadata; existing I1/I2
constructors retain their defaults. Tool execution, permission checks, path
boundaries and Core stop/error/round behavior are unchanged. The console wrapper
implements the already-approved I2 begin_task/definitions/execute interface.

- Compatibility is limited to non-streaming text Chat Completions function
  calling. Responses API, legacy calls, multimodal content, non-bearer schemes,
  provider-specific features and endpoints requiring query authentication or
  API-version parameters are unsupported.
- Chosen endpoint/model compatibility and live coding performance remain
  unverified. Models without tool calling cannot satisfy the intended loop.
- Timeout bounds are per socket operation and command execution, not a complete
  task deadline. Provider-side token/cost controls are not provisioned by this
  client. There is no automatic retry or streaming/cancellation framework.
- Existing I2 trusted-project limits remain: no OS/network sandbox, best-effort
  descendant termination, conservative sensitive-path denylist and optimistic
  patch concurrency checks rather than an OS-wide compare-and-swap guarantee.
- Tool errors remain fail-fast in the CLI. Final model summaries are untrusted
  text; observed patch/test fields are evidence, not proof of every model claim.
- Sessions remain in memory. Python 3.12/3.13 and POSIX execution were not
  independently exercised in this Windows verification run.

## Git and document preservation

Main was intentionally advanced only to approved I2, locally and on GitHub.
The I2 branch remains at its approved commit. I3 work is local and uncommitted
on i3-model-cli: nothing staged, merged into main, or pushed as I3.

Tracked diff summary: 5 files changed, 146 insertions, 8 deletions. Seven new
files (adapter, CLI, module entry point, two test modules, manual smoke runbook,
this report) are reviewed separately because ordinary Git diffs omit untracked
files. No existing tests were removed or weakened. Source/whitespace checks and
secret-pattern scans pass; caches/generated files remain ignored.

Both approved documents retain their original SHA-256 values:

| Document | SHA-256 |
| --- | --- |
| `SCA-V0-Core-Architecture-v0.1.md` | `B48D4215CFA39C13732A14421C1FF227A0AC780E522CB05AE06A71B987DB1201` |
| `SCA-V0-Codex-I1-Task.md` | `0B21040F33E62FD343D6365587534F205EB306A7B3E6650072743E274085FC15` |

No subagents, Skills system, advanced memory, provider/plugin registry, desktop
interface or unrelated refactors were added. No I3 merge or I4 work occurred.
**Stop after I3. Further stages require explicit approval.**
