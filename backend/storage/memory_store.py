"""Long-term user memory with MySQL persistence and a JSON fallback."""

from __future__ import annotations

import json

from auth.context import user_data_path
from storage.mysql_db import mysql_enabled

_DEFAULT: dict = {
    "interests": [],
    "learning_goals": [],
    "gaps": [],
    "key_insights": [],
    "summary": "",
    "updated_at": "",
}

def _empty() -> dict:
    return {key: list(value) if isinstance(value, list) else value for key, value in _DEFAULT.items()}


def load() -> dict:
    if mysql_enabled():
        return _load_mysql()
    return load_legacy_file()


def load_legacy_file() -> dict:
    memory_file = user_data_path("user_memory.json")
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    if not memory_file.exists():
        return _empty()
    try:
        payload = json.loads(memory_file.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else _empty()
    except (OSError, json.JSONDecodeError):
        return _empty()


def save(mem: dict) -> None:
    if mysql_enabled():
        _save_mysql(mem)
    else:
        save_legacy_file(mem)


def save_legacy_file(mem: dict) -> None:
    memory_file = user_data_path("user_memory.json")
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def reset() -> dict:
    mem = _empty()
    if mysql_enabled():
        from memory.runtime import MemoryRuntime
        MemoryRuntime().archive_all()
    else:
        save_legacy_file(mem)
    return mem


def _load_mysql() -> dict:
    from memory.runtime import MemoryRuntime
    return MemoryRuntime().aggregate_legacy_view()


def _save_mysql(mem: dict) -> None:
    from memory.runtime import MemoryRuntime
    MemoryRuntime().replace_legacy_aggregate(mem)
