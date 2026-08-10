"""Protocol-safe runtime for OpenAI-compatible function calls.

The public interface deliberately returns the assistant message and all of its
tool responses as one immutable turn result.  Callers can append
``turn.messages`` in one operation, avoiding the invalid history shape where a
system/user message is inserted before every ``tool_call_id`` has a response.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Mapping

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Any]
EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A registered handler plus its JSON-schema and execution policy."""

    handler: ToolHandler
    parameters: Mapping[str, Any] | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_call_id: str
    name: str
    status: Literal["success", "error", "timeout"]
    content: str


@dataclass(frozen=True, slots=True)
class ToolRuntimeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
        }


@dataclass(frozen=True, slots=True)
class ToolTurnResult:
    messages: tuple[dict[str, Any], ...]
    results: tuple[ToolExecutionResult, ...]
    usage: ToolRuntimeUsage


@dataclass(frozen=True, slots=True)
class ResponsesToolTurnResult:
    """One protocol-complete Responses API tool turn.

    ``input_items`` contains the model output items followed immediately by one
    ``function_call_output`` for every function call.  It can therefore be
    appended atomically to the next stateless Responses API request.
    ``messages`` mirrors the same turn in Chat Completions format for logging,
    evidence compression and provider-independent checkpoints.
    """

    input_items: tuple[dict[str, Any], ...]
    messages: tuple[dict[str, Any], ...]
    results: tuple[ToolExecutionResult, ...]
    usage: ToolRuntimeUsage


class ToolRuntime:
    """Validate and execute a complete assistant function-calling turn.

    Handlers can be synchronous or asynchronous.  Every serialized tool call
    produces exactly one adjacent ToolMessage, including unknown tools,
    malformed arguments, schema failures, timeouts and handler exceptions.
    """

    def __init__(
        self,
        tools: Mapping[str, ToolDefinition | ToolHandler] | None = None,
        *,
        default_timeout_seconds: float = 120.0,
        event_sink: EventSink | None = None,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        self._tools: dict[str, ToolDefinition] = {}
        self.default_timeout_seconds = default_timeout_seconds
        self.event_sink = event_sink
        for name, definition in (tools or {}).items():
            self.register(name, definition)

    def register(
        self,
        name: str,
        definition: ToolDefinition | ToolHandler,
    ) -> None:
        if not name:
            raise ValueError("tool name cannot be empty")
        normalized = (
            definition
            if isinstance(definition, ToolDefinition)
            else ToolDefinition(handler=definition)
        )
        if not callable(normalized.handler):
            raise TypeError(f"handler for tool {name!r} must be callable")
        if normalized.timeout_seconds is not None and normalized.timeout_seconds <= 0:
            raise ValueError(f"timeout for tool {name!r} must be positive")
        self._tools[name] = normalized

    async def execute_turn(
        self,
        assistant_message: Any,
        *,
        usage: Any = None,
    ) -> ToolTurnResult:
        assistant_payload, calls = self._serialize_assistant(assistant_message)
        messages: list[dict[str, Any]] = [assistant_payload]
        results: list[ToolExecutionResult] = []

        for call in calls:
            result = await self._execute_call(call)
            results.append(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                }
            )

        input_tokens, output_tokens = _extract_usage(usage)
        return ToolTurnResult(
            messages=tuple(messages),
            results=tuple(results),
            usage=ToolRuntimeUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=len(calls),
            ),
        )

    async def execute_response(self, response: Any) -> ResponsesToolTurnResult:
        """Execute every function call emitted by a Responses API response.

        DeepSeek's Responses endpoint is stateless, so callers must explicitly
        return both the original output items and all matching tool outputs.
        Keeping that assembly inside ToolRuntime prevents partial tool turns
        from leaking into the next request.
        """

        assistant_payload, calls, response_items = _serialize_response(response)
        messages: list[dict[str, Any]] = [assistant_payload]
        input_items = list(response_items)
        results: list[ToolExecutionResult] = []

        for call in calls:
            result = await self._execute_call(call)
            results.append(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                }
            )
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": result.tool_call_id,
                    "output": result.content,
                }
            )

        input_tokens, output_tokens = _extract_usage(_field(response, "usage"))
        return ResponsesToolTurnResult(
            input_items=tuple(input_items),
            messages=tuple(messages),
            results=tuple(results),
            usage=ToolRuntimeUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=len(calls),
            ),
        )

    def assemble_turn(
        self,
        assistant_message: Any,
        responses: Mapping[str, str],
        *,
        usage: Any = None,
    ) -> ToolTurnResult:
        """Atomically assemble externally executed tool results.

        Useful for orchestrators that need custom scheduling (for example,
        parallel research followed by a dependent refine call) while still
        delegating the OpenAI message invariant to this Module.
        """
        assistant_payload, calls = self._serialize_assistant(assistant_message)
        messages: list[dict[str, Any]] = [assistant_payload]
        results: list[ToolExecutionResult] = []
        for call in calls:
            if call["id"] in responses:
                result = ToolExecutionResult(
                    call["id"], call["name"], "success", str(responses[call["id"]]),
                )
            else:
                result = ToolExecutionResult(
                    call["id"],
                    call["name"],
                    "error",
                    json.dumps({
                        "ok": False,
                        "error": {
                            "type": "unhandled_tool_call",
                            "message": f"No result supplied for tool {call['name']!r}",
                        },
                    }, ensure_ascii=False),
                )
            results.append(result)
            messages.append({
                "role": "tool",
                "tool_call_id": result.tool_call_id,
                "content": result.content,
            })
        input_tokens, output_tokens = _extract_usage(usage)
        return ToolTurnResult(
            messages=tuple(messages),
            results=tuple(results),
            usage=ToolRuntimeUsage(input_tokens, output_tokens, len(calls)),
        )

    def _serialize_assistant(
        self, message: Any
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": _field(message, "content") or "",
        }
        reasoning = _field(message, "reasoning_content")
        if reasoning is not None:
            payload["reasoning_content"] = reasoning

        calls: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for index, raw_call in enumerate(_field(message, "tool_calls") or []):
            function = _field(raw_call, "function") or {}
            call_id = str(_field(raw_call, "id") or f"runtime-call-{index}")
            if call_id in seen_ids:
                logger.warning("Ignoring duplicate tool_call_id %s", call_id)
                continue
            seen_ids.add(call_id)
            calls.append(
                {
                    "id": call_id,
                    "name": str(_field(function, "name") or ""),
                    "arguments": str(_field(function, "arguments") or "{}"),
                }
            )

        if calls:
            payload["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": call["arguments"],
                    },
                }
                for call in calls
            ]
        return payload, calls

    async def _execute_call(self, call: dict[str, str]) -> ToolExecutionResult:
        call_id, name = call["id"], call["name"]
        await self._emit(
            {
                "type": "tool_start",
                "tool_call_id": call_id,
                "tool": name,
                "arguments": call["arguments"],
            }
        )
        definition = self._tools.get(name)
        if definition is None:
            return await self._failure(
                call_id,
                name,
                "error",
                "unknown_tool",
                f"Tool {name!r} is not registered",
            )

        try:
            arguments = json.loads(call["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
            if definition.parameters is not None:
                _validate_schema(arguments, definition.parameters)
            _validate_signature(definition.handler, arguments)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return await self._failure(
                call_id, name, "error", "invalid_arguments", str(exc)
            )

        timeout = definition.timeout_seconds or self.default_timeout_seconds
        try:
            value = await asyncio.wait_for(
                _invoke(definition.handler, arguments), timeout=timeout
            )
        except TimeoutError:
            return await self._failure(
                call_id,
                name,
                "timeout",
                "timeout",
                f"Tool {name!r} exceeded {timeout:g} seconds",
            )
        except Exception as exc:
            logger.exception("Tool %s (%s) failed", name, call_id)
            return await self._failure(
                call_id, name, "error", "tool_error", str(exc)
            )

        content = _content(value)
        await self._emit(
            {
                "type": "tool_finish",
                "tool_call_id": call_id,
                "tool": name,
                "status": "success",
            }
        )
        return ToolExecutionResult(call_id, name, "success", content)

    async def _failure(
        self,
        call_id: str,
        name: str,
        status: Literal["error", "timeout"],
        error_type: str,
        message: str,
    ) -> ToolExecutionResult:
        content = json.dumps(
            {
                "ok": False,
                "error": {"type": error_type, "message": message},
            },
            ensure_ascii=False,
        )
        await self._emit(
            {
                "type": "tool_finish",
                "tool_call_id": call_id,
                "tool": name,
                "status": status,
                "error_type": error_type,
            }
        )
        return ToolExecutionResult(call_id, name, status, content)

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            result = self.event_sink(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Telemetry must never make a valid tool protocol turn invalid.
            logger.exception("ToolRuntime event sink failed")


async def _invoke(handler: ToolHandler, arguments: dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(handler):
        return await handler(**arguments)
    value = await asyncio.to_thread(handler, **arguments)
    if inspect.isawaitable(value):
        return await value
    return value


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _plain(value: Any) -> Any:
    """Convert SDK response models to JSON-compatible Python values."""

    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _plain(model_dump(exclude_none=True))
    if hasattr(value, "__dict__"):
        return {
            key: _plain(child)
            for key, child in vars(value).items()
            if not key.startswith("_") and child is not None
        }
    return value


def _serialize_response(
    response: Any,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    """Normalize Responses API output for execution and stateless replay."""

    response_items: list[dict[str, Any]] = []
    calls: list[dict[str, str]] = []
    text_parts: list[str] = []
    seen_ids: set[str] = set()

    for index, raw_item in enumerate(_field(response, "output") or []):
        item = _plain(raw_item)
        if not isinstance(item, dict):
            continue
        response_items.append(item)
        item_type = str(item.get("type", ""))
        if item_type == "function_call":
            call_id = str(
                item.get("call_id") or item.get("id") or f"responses-call-{index}"
            )
            if call_id in seen_ids:
                logger.warning("Ignoring duplicate Responses call_id %s", call_id)
                continue
            seen_ids.add(call_id)
            calls.append(
                {
                    "id": call_id,
                    "name": str(item.get("name") or ""),
                    "arguments": str(item.get("arguments") or "{}"),
                }
            )
        elif item_type == "message":
            content = item.get("content") or []
            if isinstance(content, str):
                text_parts.append(content)
            else:
                for part in content:
                    if isinstance(part, Mapping) and part.get("type") in {
                        "output_text",
                        "text",
                    }:
                        text_parts.append(str(part.get("text") or ""))

    output_text = _field(response, "output_text")
    content = str(output_text) if output_text else "".join(text_parts)
    assistant_payload: dict[str, Any] = {
        "role": "assistant",
        "content": content,
    }
    if calls:
        assistant_payload["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
            }
            for call in calls
        ]
    return assistant_payload, calls, response_items


def _extract_usage(usage: Any) -> tuple[int, int]:
    def number(*names: str) -> int:
        for name in names:
            value = _field(usage, name)
            if value is not None:
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    return 0
        return 0

    return number("input_tokens", "prompt_tokens"), number(
        "output_tokens", "completion_tokens"
    )


def _validate_signature(handler: ToolHandler, arguments: dict[str, Any]) -> None:
    try:
        inspect.signature(handler).bind(**arguments)
    except ValueError:
        # Some C-extension callables do not expose a signature.
        return
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str = "arguments") -> None:
    """Validate the JSON-schema subset used by OpenAI tool definitions."""
    expected = schema.get("type")
    type_checks: dict[str, tuple[type, ...]] = {
        "object": (dict,),
        "array": (list,),
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "null": (type(None),),
    }
    if expected in type_checks:
        valid = isinstance(value, type_checks[expected])
        if expected in {"integer", "number"} and isinstance(value, bool):
            valid = False
        if not valid:
            raise ValueError(f"{path} must be {expected}")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = [key for key in value if key not in properties]
            if extras:
                raise ValueError(f"{path} has unexpected fields: {', '.join(extras)}")
        for key, child in value.items():
            if key in properties:
                _validate_schema(child, properties[key], f"{path}.{key}")

    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, child in enumerate(value):
            _validate_schema(child, schema["items"], f"{path}[{index}]")


__all__ = [
    "ResponsesToolTurnResult",
    "ToolDefinition",
    "ToolExecutionResult",
    "ToolRuntime",
    "ToolRuntimeUsage",
    "ToolTurnResult",
]
