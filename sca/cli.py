"""Minimal composition root and per-operation terminal authorization.

No provider is selected by default. No keys are accepted on the command line.
Automated tests inject a transport and input/output; they never contact an LLM.
"""

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
import json
import math
import os
import sys
from typing import TextIO
import unicodedata
import uuid

from sca.agent import AgentCore
from sca.contracts import AgentTask, ToolCall, ToolDefinition, ToolResult
from sca.provider import CompatibleModel, ConfigurationError, JsonTransport, ModelConfig
from sca.tools import ToolExecutor, ToolRuntime
from sca.workspace import Workspace


class Console:
    """Redact the configured credential and escape terminal control sequences."""

    def __init__(self, stream: TextIO, secret: str | None = None) -> None:
        self.stream = stream
        self.secret = secret

    def write(self, text: str) -> None:
        if self.secret:
            text = text.replace(self.secret, "[REDACTED]")
        safe = "".join(
            f"\\u{ord(char):04x}" if unicodedata.category(char) in ("Cc", "Cf") and char not in "\n\t" else char
            for char in text
        )
        self.stream.write(safe + "\n")
        self.stream.flush()


class ConsoleAuthorization:
    def __init__(self, console: Console, read: Callable[[str], str]) -> None:
        self.console = console
        self.read = read

    def __call__(self, call: ToolCall) -> bool:
        self.console.write(f"Authorization required: {call.tool_name} ({call.call_id})")
        # Show the whole concrete operation, including patch spans, before a
        # decision. JSON escaping prevents model text from forging the prompt.
        self.console.write(json.dumps(call.arguments, ensure_ascii=True, indent=2))
        self.console.write("Approve this one operation? [y/N]")
        try:
            granted = self.read("").strip().casefold() in ("y", "yes")
        except EOFError:
            granted = False
        self.console.write("Approved." if granted else "Denied.")
        return granted


class ConsoleExecutor:
    """ToolExecutor decorator for visibility; no tool selection or scheduling."""

    def __init__(self, executor: ToolExecutor, console: Console) -> None:
        self.executor = executor
        self.console = console

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        return self.executor.tool_definitions

    def begin_task(self, task: AgentTask) -> None:
        self.executor.begin_task(task)

    def execute(self, call: ToolCall) -> ToolResult:
        self.console.write(f"Tool call: {call.tool_name} ({call.call_id})")
        self.console.write(json.dumps(call.arguments, ensure_ascii=True))
        result = self.executor.execute(call)
        self.console.write(f"Tool result: {result.status} ({result.call_id})" + (" [truncated]" if result.truncated else ""))
        if result.output:
            self.console.write(result.output)
        if result.error:
            self.console.write(result.error)
        return result


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's default includes unrecognized argument values, which may
        # accidentally contain pasted credentials. Do not echo raw CLI values.
        raise ConfigurationError("Invalid CLI arguments; use --help. Credentials must be supplied through environment variables.")


def argument_parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Fennec X Code: one task, user-configured LLM, restricted local tools.", allow_abbrev=False)
    parser.add_argument("--workspace", help="Existing trusted local project directory")
    parser.add_argument("--task", help="Coding task instruction")
    parser.add_argument("--model", help="Model name (or FENNEC_MODEL); no default model")
    parser.add_argument("--api-base-url", help="Compatible API base URL (or FENNEC_API_BASE_URL); no default endpoint")
    parser.add_argument("--auth", help="none or bearer (or FENNEC_AUTH); default: none")
    parser.add_argument("--api-key-env", default="FENNEC_API_KEY", help="Environment variable containing a bearer token; used only with bearer auth")
    parser.add_argument("--trusted-project", action="store_true", help="Explicitly trust project code for command execution; every command still requires approval")
    parser.add_argument("--max-model-rounds", type=int, default=25)
    parser.add_argument("--model-timeout", type=float, default=30, help="Model socket timeout in seconds (max 600)")
    parser.add_argument("--command-timeout", type=float, default=10, help="Command timeout in seconds (max 600)")
    return parser


def main(
    argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None,
    input_fn: Callable[[str], str] | None = None, stdout: TextIO | None = None,
    stderr: TextIO | None = None, transport: JsonTransport | None = None,
) -> int:
    environment = os.environ if environ is None else environ
    out_stream = sys.stdout if stdout is None else stdout
    err_stream = sys.stderr if stderr is None else stderr
    out = Console(out_stream)
    err = Console(err_stream)
    try:
        args = argument_parser().parse_args(argv)
        # Select only the explicitly configured variable, never discover keys
        # or providers in unrelated environment variables or local files.
        secret = environment.get(args.api_key_env) if args.api_key_env else None
        out = Console(out_stream, secret)
        err = Console(err_stream, secret)
        config = ModelConfig.from_environment(
            model=args.model, api_base_url=args.api_base_url, auth=args.auth,
            api_key_env=args.api_key_env, environ=environment, timeout_seconds=args.model_timeout,
        )
        if not args.workspace or not args.task or not args.task.strip():
            raise ConfigurationError("Specify --workspace and a non-empty --task. No request sent.")
        if args.max_model_rounds < 1:
            raise ConfigurationError("--max-model-rounds must be positive.")
        if not math.isfinite(args.command_timeout) or not 0 < args.command_timeout <= 600:
            raise ConfigurationError("--command-timeout must be finite, positive and at most 600 seconds.")
        workspace = Workspace(args.workspace)
        task = AgentTask(args.task, str(workspace.root), uuid.uuid4().hex)
        authorize = ConsoleAuthorization(out, input if input_fn is None else input_fn)
        runtime = ToolRuntime(
            workspace, authorize=authorize, trusted_project=args.trusted_project,
            timeout_seconds=args.command_timeout,
        )
        gateway = CompatibleModel(config, transport=transport)
        executor = ConsoleExecutor(runtime, out)
        out.write(f"Workspace: {workspace.root}\nModel: {config.model}\nEndpoint: {config.endpoint}")
        result = AgentCore(gateway, executor, max_model_rounds=args.max_model_rounds).run(task)
        report = asdict(result)
        del report["tool_results"]  # Already displayed as activity; retain summary evidence.
        out.write("Task result:\n" + json.dumps(report, ensure_ascii=True, indent=2))
        return {"COMPLETED": 0, "ERROR": 1, "LIMIT_REACHED": 3}[result.status]
    except SystemExit as exc:
        return int(exc.code)
    except (ConfigurationError, ValueError) as exc:
        err.write(f"Configuration error: {exc}")
        return 2
    except OSError:
        err.write("Workspace or terminal access failed; check the directory and permissions. No automatic retry.")
        return 2
    except KeyboardInterrupt:
        err.write("Interrupted. Any earlier workspace changes are retained.")
        return 130
    except Exception:
        err.write("CLI operation failed; no automatic retry. Raw exceptions are suppressed to protect credentials.")
        return 1
