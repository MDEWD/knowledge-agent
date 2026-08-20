"""Role-specific DeepSeek request options.

DeepSeek V4 defaults to thinking mode. Agent orchestration and structured-output
roles must opt out explicitly; otherwise reasoning can consume the response
budget before tool calls or JSON are emitted.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from agents.deep_research.cancellation import await_with_cancel


_THINKING_ROLES = {"red_team"}


def apply_role_options(kwargs: dict[str, Any], role: str) -> dict[str, Any]:
    options = dict(kwargs)
    model = str(options.get("model", "")).casefold()
    if not model.startswith("deepseek-v4-"):
        return options

    thinking_type = "enabled" if role in _THINKING_ROLES else "disabled"
    extra_body = dict(options.get("extra_body") or {})
    extra_body["thinking"] = {"type": thinking_type}
    options["extra_body"] = extra_body
    if thinking_type == "enabled":
        options.setdefault("reasoning_effort", "high")
    else:
        options.pop("reasoning_effort", None)
    return options


@dataclass(frozen=True)
class StreamedTextCompletion:
    """Text and usage collected from a Chat Completions SSE response."""

    content: str
    input_tokens: int = 0
    output_tokens: int = 0


async def collect_streamed_text_completion(
    client: Any,
    request_options: dict[str, Any],
    *,
    timeout_seconds: float,
    cancel_event: asyncio.Event | None = None,
) -> StreamedTextCompletion:
    """Collect a text-only completion over SSE.

    DeepSeek emits SSE keep-alive comments for streaming calls.  That is more
    robust through local HTTP proxies than waiting for one large chunked JSON
    body, which can be closed mid-body after a long inference.
    """

    options = dict(request_options)
    options["stream"] = True
    stream_options = dict(options.get("stream_options") or {})
    stream_options["include_usage"] = True
    options["stream_options"] = stream_options

    content_parts: list[str] = []
    input_tokens = 0
    output_tokens = 0

    async with asyncio.timeout(timeout_seconds):
        stream = await await_with_cancel(
            client.chat.completions.create(**options),
            timeout_seconds=timeout_seconds,
            cancel_event=cancel_event,
        )
        iterator = stream.__aiter__()
        while True:
            try:
                chunk = await await_with_cancel(
                    anext(iterator),
                    timeout_seconds=timeout_seconds,
                    cancel_event=cancel_event,
                )
            except StopAsyncIteration:
                break
            if chunk.choices:
                content_parts.append(chunk.choices[0].delta.content or "")
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

    return StreamedTextCompletion(
        content="".join(content_parts),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


__all__ = [
    "StreamedTextCompletion",
    "apply_role_options",
    "collect_streamed_text_completion",
]
