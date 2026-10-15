"""User-configured Chat Completions adapter; no provider/model provisioning.

All network I/O is behind an injectable transport. Configuration/construction
does no I/O. Errors use fixed messages, never raw provider bodies or exceptions.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import http.client
import ipaddress
import json
import math
import re
import socket
import threading
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from sca.contracts import ModelRequest, ModelResponse, ToolCall, ToolDefinition, require_text
from sca.limits import TaskBudget, TaskLimitExceeded


class ConfigurationError(ValueError):
    """Missing or unsafe user configuration; no request should be sent."""


@dataclass(frozen=True)
class ModelConfig:
    model: str
    api_base_url: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 30
    max_response_bytes: int = 1024 * 1024
    disable_thinking: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip() or any(ord(c) < 32 for c in self.model):
            raise ConfigurationError("Configure a non-empty model name with --model or FENNEC_MODEL.")
        if not isinstance(self.api_base_url, str) or not self.api_base_url or any(c.isspace() or ord(c) < 32 for c in self.api_base_url):
            raise ConfigurationError("Configure an HTTP(S) API base URL with --api-base-url or FENNEC_API_BASE_URL.")
        try:
            parsed = urlsplit(self.api_base_url)
            valid = parsed.scheme in ("http", "https") and parsed.hostname and parsed.port != 0
            if not valid or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
                raise ValueError
        except ValueError:
            raise ConfigurationError("API base URL must be HTTP(S), with a host and no credentials, query or fragment.") from None
        if self.api_key is not None:
            if not isinstance(self.api_key, str) or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", self.api_key):
                raise ConfigurationError("Bearer credentials must be a non-empty header-safe token supplied through the selected environment variable.")
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = parsed.hostname.casefold() == "localhost"
            if parsed.scheme == "http" and not loopback:
                raise ConfigurationError("Bearer authentication requires HTTPS or a loopback endpoint.")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (float, int)) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 600:
            raise ConfigurationError("Model timeout must be finite, positive and at most 600 seconds.")
        if type(self.max_response_bytes) is not int or not 128 <= self.max_response_bytes <= 4 * 1024 * 1024:
            raise ConfigurationError("Response limit must be between 128 and 4194304 bytes.")
        if type(self.disable_thinking) is not bool:
            raise ConfigurationError("disable_thinking must be an explicit boolean.")

    @property
    def endpoint(self) -> str:
        parsed = urlsplit(self.api_base_url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/chat/completions", "", ""))

    @classmethod
    def from_environment(
        cls, *, model: str | None = None, api_base_url: str | None = None,
        auth: str | None = None, api_key_env: str = "FENNEC_API_KEY",
        environ: Mapping[str, str], timeout_seconds: float = 30,
        disable_thinking: bool = False,
    ) -> "ModelConfig":
        selected_model = model if model is not None else environ.get("FENNEC_MODEL")
        selected_url = api_base_url if api_base_url is not None else environ.get("FENNEC_API_BASE_URL")
        if not selected_model or not selected_url:
            raise ConfigurationError("LLM configuration missing: set --model/FENNEC_MODEL and --api-base-url/FENNEC_API_BASE_URL. No request sent.")
        selected_auth = auth if auth is not None else environ.get("FENNEC_AUTH", "none")
        if selected_auth not in ("none", "bearer"):
            raise ConfigurationError("Authentication must be none or bearer.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
            raise ConfigurationError("--api-key-env must name an environment variable.")
        key = None
        if selected_auth == "bearer":
            key = environ.get(api_key_env)
            if not key:
                raise ConfigurationError("Bearer authentication is selected, but its API-key environment variable is empty.")
        return cls(selected_model, selected_url, key, timeout_seconds, disable_thinking=disable_thinking)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = field(repr=False)


class JsonTransport(Protocol):
    def post(self, url: str, headers: Mapping[str, str], body: bytes, *, timeout: float, max_bytes: int) -> HttpResponse: ...


class HttpTransport:
    """One POST, verified TLS, no redirects, ambient proxies, or retries.

    A watchdog bounds the whole HTTP exchange, including a trickling response.
    DNS resolution and OS resource cleanup are not forcibly preemptible.
    """

    def post(self, url: str, headers: Mapping[str, str], body: bytes, *, timeout: float, max_bytes: int) -> HttpResponse:
        parsed = urlsplit(url)
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
        # Do not inherit process-wide HTTP debug logging: it prints raw headers.
        connection.debuglevel = 0
        expired = threading.Event()
        active_socket = None

        def abort() -> None:
            expired.set()
            # shutdown interrupts a read even when getresponse() owns a file
            # wrapper around the socket. Never print exception/header data.
            sock = getattr(connection, "sock", None) or active_socket
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        watchdog = threading.Timer(timeout, abort)
        watchdog.daemon = True
        try:
            watchdog.start()
            connection.request("POST", parsed.path or "/", body=body, headers=dict(headers))
            active_socket = getattr(connection, "sock", None)
            response = connection.getresponse()
            # Error bodies may echo credentials. Do not read, decode or log them.
            data = response.read(max_bytes + 1) if 200 <= response.status < 300 else b""
            if expired.is_set():
                raise TimeoutError
            if len(data) > max_bytes:
                raise ValueError("Response limit exceeded")
            return HttpResponse(response.status, data)
        except Exception:
            if expired.is_set():
                raise TimeoutError from None
            raise
        finally:
            watchdog.cancel()
            connection.close()


def tool_schema(definition: ToolDefinition) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", definition.name):
        raise ValueError("Invalid provider function name")
    types = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
    properties = {}
    for name, value_type in (definition.argument_types | definition.optional_argument_types).items():
        if value_type not in types:
            raise ValueError("Unsupported provider argument type")
        schema = {"type": types[value_type]}
        if value_type is list:
            schema["items"] = deepcopy(definition.array_item_schemas.get(name, {}))
        properties[name] = schema
    return {"type": "function", "function": {
        "name": definition.name, "description": definition.description,
        "parameters": {"type": "object", "properties": properties,
                       "required": list(definition.argument_types), "additionalProperties": False},
    }}


def build_payload(request: ModelRequest, model: str) -> dict[str, object]:
    """Translate internal history without transmitting workspace/session IDs."""
    messages: list[dict[str, object]] = [{"role": "system", "content": request.instructions}]
    pending: set[str] = set()
    seen: set[str] = set()
    for message in request.messages:
        if message.role == "tool":
            result = message.tool_result
            if result is None or result.call_id not in pending:
                raise ValueError("Orphaned or duplicate tool result")
            result.validate()
            pending.remove(result.call_id)
            messages.append({"role": "tool", "tool_call_id": result.call_id,
                             "content": json.dumps(asdict(result), ensure_ascii=True, allow_nan=False)})
        elif message.role == "assistant" and message.tool_calls:
            if pending:
                raise ValueError("Missing tool results")
            calls = []
            for call in message.tool_calls:
                call.validate()
                if call.call_id in seen:
                    raise ValueError("Duplicate call ID in request history")
                seen.add(call.call_id)
                pending.add(call.call_id)
                calls.append({"id": call.call_id, "type": "function", "function": {
                    "name": call.tool_name, "arguments": json.dumps(call.arguments, allow_nan=False),
                }})
            messages.append({"role": "assistant", "content": message.content or None, "tool_calls": calls})
        elif message.role in ("user", "assistant"):
            if pending:
                raise ValueError("Missing tool results")
            messages.append({"role": message.role, "content": message.content})
        else:
            raise ValueError("Invalid message role")
    if pending:
        raise ValueError("Missing tool results")
    payload: dict[str, object] = {"model": model, "messages": messages, "stream": False}
    if request.tool_definitions:
        payload.update(tools=[tool_schema(item) for item in request.tool_definitions], tool_choice="auto")
    return payload


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _json_loads(value: str | bytes) -> object:
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_invalid_constant, parse_float=_finite_float)


def parse_response(body: bytes) -> ModelResponse:
    """Normalize one completed assistant turn; reject partial/ambiguous data."""
    try:
        payload = _json_loads(body)
        if not isinstance(payload, dict) or payload.get("error") is not None:
            raise ValueError
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant" or message.get("refusal"):
            raise ValueError
        if message.get("function_call") is not None:
            raise ValueError
        if message.get("refusal") is not None and not isinstance(message["refusal"], str):
            raise ValueError
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError
        calls = message.get("tool_calls")
        if calls is not None and not isinstance(calls, list):
            raise ValueError
        if choice.get("finish_reason") == "tool_calls":
            if not isinstance(calls, list) or not calls:
                raise ValueError
            normalized = []
            ids = set()
            for item in calls:
                if not isinstance(item, dict) or item.get("type") != "function":
                    raise ValueError
                function = item.get("function")
                if not isinstance(function, dict) or not isinstance(function.get("arguments"), str):
                    raise ValueError
                arguments = _json_loads(function["arguments"])
                call = ToolCall(item.get("id"), function.get("name"), arguments)
                call.validate()
                if call.call_id in ids:
                    raise ValueError
                ids.add(call.call_id)
                normalized.append(call)
            response = ModelResponse(tool_calls=tuple(normalized))
        elif choice.get("finish_reason") == "stop" and not calls:
            response = ModelResponse(final_answer=content)
        else:
            raise ValueError
        response.validate()
        return response
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return ModelResponse(error="Malformed, refused or incomplete provider response; no tool executed.")


class CompatibleModel:
    """ModelGateway implementation for a user-selected compatible endpoint."""

    def __init__(self, config: ModelConfig, transport: JsonTransport | None = None, *, budget: TaskBudget | None = None) -> None:
        self.config = config
        self._budget = budget
        self._transport = transport if transport is not None else HttpTransport()

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._budget is not None:
            self._budget.check()
        try:
            payload = build_payload(request, self.config.model)
            if self.config.disable_thinking:
                payload["thinking"] = {"type": "disabled"}
            body = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
            if len(body) > 2 * 1024 * 1024:
                return ModelResponse(error="Model request exceeds the 2 MiB limit.")
        except (ValueError, TypeError, RecursionError):
            return ModelResponse(error="Invalid model request or unsupported tool schema; no request sent.")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key is not None:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            timeout = self.config.timeout_seconds if self._budget is None else self._budget.timeout(self.config.timeout_seconds)
            response = self._transport.post(
                self.config.endpoint, headers, body, timeout=timeout,
                max_bytes=self.config.max_response_bytes,
            )
            if self._budget is not None:
                self._budget.check()
            if not isinstance(response, HttpResponse) or type(response.status) is not int or not isinstance(response.body, bytes):
                return ModelResponse(error="Invalid provider transport response.")
            if not 200 <= response.status < 300:
                if response.status in (401, 403):
                    label = "Provider authentication failed"
                elif 300 <= response.status < 400:
                    label = "Provider redirect refused; configure the final API base URL"
                else:
                    label = "Provider request failed"
                return ModelResponse(error=f"{label} (HTTP {response.status}); no retry attempted.")
            if len(response.body) > self.config.max_response_bytes:
                return ModelResponse(error="Provider response exceeds the configured size limit.")
            return parse_response(response.body)
        except TaskLimitExceeded:
            raise
        except (TimeoutError, socket.timeout):
            if self._budget is not None:
                self._budget.check()
            return ModelResponse(error="Provider connection or read timed out; no retry attempted.")
        except Exception:
            if self._budget is not None:
                self._budget.check()
            # Exception text can contain headers, credentials or raw bodies.
            return ModelResponse(error="Provider connection, response capture or transport failed; no retry attempted.")
