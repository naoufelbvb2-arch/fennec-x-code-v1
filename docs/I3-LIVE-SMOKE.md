# Optional I3 live-model smoke procedure

Status: deferred; not executed during implementation or automated testing.
Do not run this procedure until the user selects/configures a compatible
provider and explicitly approves live requests, including any associated costs.
It never selects or provisions a provider, creates keys, downloads a model or
starts a server. Automated tests do not import or execute this procedure.

1. Select an endpoint supporting non-streaming Chat Completions and function
   tool calls. Set `FENNEC_MODEL` to the exact chosen model and
   `FENNEC_API_BASE_URL` to that endpoint's API base. There are no fallback values.
2. Choose `FENNEC_AUTH=none` for a compatible unauthenticated local endpoint, or
   `FENNEC_AUTH=bearer` and provide the token using `FENNEC_API_KEY` (or select a
   custom variable with `--api-key-env`). Do not put tokens in task text, CLI
   arguments, URLs, repository files, logs or chat. Remote bearer auth requires
   HTTPS; loopback HTTP is supported. Keep TLS certificate verification enabled.
3. Use a disposable trusted project, outside this repository, containing an
   `app.py` that has no secrets. Choose its absolute path explicitly.
4. After approving a live request, run the following, replacing the path:

   ```powershell
   python -m sca --workspace 'C:\path\to\disposable-project' --task 'Read app.py using read_file and summarize it. Do not modify files or run commands.'
   ```

   Expected evidence: the configured endpoint/model is shown, the model requests
   `read_file`, the result retains its call ID, a later request contains that tool
   result, and the CLI prints a final task result. Workspace files stay unchanged.
   No sensitive operation should be approved for this initial read-only task.

5. An optional second test can use a small known bug and a local pytest fixture
   in that same disposable project. Explicitly authorize another live task and
   use `--trusted-project` with a task to read the code, make one limited fix,
   run `python -m pytest -q`, then report observed results. Review each patch's
   old/new spans and hash before replying `yes`. Approve the actual test argv
   separately. In a Git project, initial Git-status inspection needs its own
   approval. Trust never bypasses the per-operation prompts.
6. Inspect the final files independently and rerun the fixture test yourself.
   Record provider/model (no credentials), final task status, actual changed
   paths, test outcome and any compatibility errors. A model's final text alone
   does not prove edits or test success. Never publish request headers or tokens.

Exit code 0 means the agent loop completed, not that every statement in the
model's summary is independently verified. Failures stop without automatic
gateway/tool retries. Refuse unexpected operations. Test code can access the
host and network; only trusted local projects are supported.

If no provider is configured, the CLI must report missing configuration and
stop without making a request. Live verification remains unclaimed until this
procedure is deliberately run and its evidence recorded.
