"""Role-specific DeepSeek request options.

DeepSeek V4 defaults to thinking mode. Agent orchestration and structured-output
roles must opt out explicitly; otherwise reasoning can consume the response
budget before tool calls or JSON are emitted.
"""
from __future__ import annotations

from typing import Any


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


__all__ = ["apply_role_options"]
