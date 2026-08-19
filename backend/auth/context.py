"""Request-scoped user identity shared by storage and Agent runtimes."""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Iterator

from config import DATA_PATH, DEFAULT_USER_ID

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def get_current_user_id() -> str:
    """Return the authenticated user, or the legacy local identity off-request."""
    return _current_user_id.get() or DEFAULT_USER_ID


def bind_user(user_id: str) -> Token:
    if not user_id:
        raise ValueError("user_id is required")
    return _current_user_id.set(user_id)


def reset_user(token: Token) -> None:
    _current_user_id.reset(token)


@contextmanager
def user_scope(user_id: str) -> Iterator[None]:
    token = bind_user(user_id)
    try:
        yield
    finally:
        reset_user(token)


def user_storage_key(user_id: str | None = None) -> str:
    """Create a filesystem-safe, non-reversible tenant directory key."""
    value = user_id or get_current_user_id()
    readable = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:24] or "user"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}"


def user_data_path(*parts: str, user_id: str | None = None) -> Path:
    value = user_id or get_current_user_id()
    if value == DEFAULT_USER_ID:
        return DATA_PATH.joinpath(*parts)
    return DATA_PATH.joinpath("users", user_storage_key(value), *parts)
