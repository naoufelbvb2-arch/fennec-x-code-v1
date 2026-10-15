# DeepSeek compatibility precheck

Checked October 15, 2026 against approved V0 engineering baseline
`f4efe4693121e19b16c376242eec464218a44cc8`.
Implementation branch: `compat-thinking-disabled`.

## Current provider requirements

DeepSeek currently lists `deepseek-flash` and `deepseek-v4-pro` with tool calling
and both thinking/non-thinking modes. This is a documentation check, not a model
selection or live compatibility claim. See the official
[model details](https://api-docs.deepseek.com/quick_start/pricing/) and
[tool-call guide](https://api-docs.deepseek.com/guides/tool_calls/).

Thinking is enabled by default. For requests carrying tools, DeepSeek requires
prior assistant `reasoning_content` to be replayed in subsequent requests;
omitting it can cause HTTP 400. The documented disabling extension is
`{"thinking":{"type":"disabled"}}`. See the official
[thinking-mode guide](https://api-docs.deepseek.com/guides/thinking_mode/).

## Small compatibility change

- CLI: explicitly add `--disable-thinking` to the user's existing configuration.
- Python: use `ModelConfig(..., disable_thinking=True)`, or the same named option
  in `ModelConfig.from_environment(...)`.
- The default is False and sends no `thinking` field. DeepSeek host/model names
  do not trigger automatic detection, configuration or changes.
- Selection adds exactly `"thinking": {"type": "disabled"}` at the top level of
  every request, including tool-result follow-ups. `extra_body` is an SDK option;
  this standard-library adapter sends the extension directly in raw JSON.
- Only explicit booleans are accepted programmatically. No arbitrary request-body
  overrides, provider registry, new dependency or thinking-enabled option exists.

ModelGateway, Agent Core, internal message/response contracts, tool schemas,
permissions, authentication handling, URL validation, transport capture limits,
timeouts, redaction and error sanitization are unchanged. The option does not
choose a model, endpoint or credentials; those remain explicit user settings.

## Actual verification

```text
python -m pytest -q -p no:cacheprovider
374 passed in 16.21s
```

Exit 0: 374 passed, 0 failed, 0 skipped, 0 warnings. All 361 existing tests pass
unchanged, plus 13 new cases in `tests/test_thinking_option.py` covering:

- Exact outgoing JSON with/without selection for mocked DeepSeek and unrelated
  endpoints; no automatic host/model selection and no SDK-only wrapper field.
- Rejection of ambiguous non-boolean programmatic settings.
- CLI composition, actual safe fixture read, stable call IDs and tool-result
  feedback, with the option retained on every mocked request.
- Rejection of a value after the CLI boolean switch, without sending a request.

Provider tests use scripted/mocked transports; the existing autouse fixture
blocks real HTTP(S) provider connections. CLI tests pass an explicit empty
environment; no real API key was accessed, requested, created, stored or displayed.
Existing credential/security, timeout, cancellation, command permission, patch
safety and correlation regressions all pass.

Reviewed the complete source diff and new tests. Whitespace and secret-pattern
checks pass. Both approved specification documents retain their original bytes
and SHA-256 values. No credentials, environment files, caches or generated
artifacts are part of the change set.

## Changes and Git state

Modified: `sca/provider.py`, `sca/cli.py`, `README.md`.
Created: `tests/test_thinking_option.py` and this note.
Tracked diff: 3 files, 22 insertions, 2 deletions, plus these two new files.

HEAD and main remain at the approved I4 commit above. Changes are local and
uncommitted on compat-thinking-disabled, with nothing staged, merged or pushed.
No architecture document, Agent Core, ModelGateway, internal contract, original
test, historical implementation report or dependency was modified.

## Compatibility limitations and live status

The adapter does not preserve/replay `reasoning_content`; thinking-enabled tool
conversations remain unsupported. This option prepares the explicitly disabled
path only. Other endpoints must support this extension before the user selects
it; their default requests remain unchanged. If an endpoint ignores the option
and returns reasoning, its reasoning history is still not preserved.

Provider/model names and behavior can change. Actual endpoint acceptance, account
access, model output quality and live coding performance remain unverified.
Existing non-streaming Chat Completions, bearer/no-auth, trusted-project and
cooperative deadline limitations still apply.

No inference request was made, provider configuration persisted, real API key
accessed, model downloaded, server started or API cost incurred. Network use was
limited to public API documentation research. **Live DeepSeek verification still
requires separate user authorization. Full V0 acceptance remains pending.**
