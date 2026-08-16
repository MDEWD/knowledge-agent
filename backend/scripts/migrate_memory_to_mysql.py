"""Import legacy JSON memory and DeepResearch history into MySQL.

The source files are intentionally retained as backups. Running this command
multiple times is safe: aggregate memory is replaced and research sessions are
upserted by ID.
"""

from __future__ import annotations

import json
import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=True)
os.environ["MEMORY_STORAGE_BACKEND"] = "mysql"

from config import DATA_PATH  # noqa: E402
from storage.deep_research_history import upsert_session  # noqa: E402
from memory.runtime import MemoryCandidate, MemoryRuntime  # noqa: E402
from storage.mysql_db import get_pool  # noqa: E402


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read legacy file: {path.name}") from exc


def main() -> None:
    if not os.environ.get("MYSQL_PASSWORD"):
        raise RuntimeError("MYSQL_PASSWORD is missing from backend/.env")

    # Fail fast before touching source data.
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE() AS database_name")
        database_name = cursor.fetchone()["database_name"]

    memory = _read_json(DATA_PATH / "user_memory.json", {})
    if isinstance(memory, dict) and memory:
        candidates = []
        mapping = {
            "interests": ("semantic", "interest"),
            "learning_goals": ("profile", "learning_goal"),
            "gaps": ("semantic", "gap"),
            "key_insights": ("semantic", "key_insight"),
        }
        for field_name, (category, memory_type) in mapping.items():
            for value in memory.get(field_name) or []:
                content = str(value).strip()
                if not content:
                    continue
                candidates.append(MemoryCandidate.from_dict({
                    "category": category,
                    "type": memory_type,
                    "key": f"{memory_type}:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:24]}",
                    "value": content,
                    "content": content,
                    "confidence": 0.7,
                    "importance": 0.7,
                    "explicitness": 0.5,
                    "source_type": "legacy_memory",
                }))
        summary = str(memory.get("summary") or "").strip()
        if summary:
            candidates.append(MemoryCandidate.from_dict({
                "category": "profile",
                "type": "summary",
                "key": "profile_summary",
                "value": summary,
                "content": summary,
                "confidence": 0.7,
                "importance": 0.8,
                "explicitness": 0.5,
                "source_type": "legacy_memory",
            }))
        MemoryRuntime().remember(candidates)

    sessions = _read_json(DATA_PATH / "deep_research_history.json", [])
    migrated_sessions = 0
    migrated_turns = 0
    for session in sessions if isinstance(sessions, list) else []:
        if not isinstance(session, dict) or not session.get("id"):
            continue
        upsert_session(session)
        migrated_sessions += 1
        migrated_turns += len(session.get("turns") or [])

    print(f"database={database_name}")
    print(f"memory_imported={bool(memory)}")
    print(f"research_sessions_imported={migrated_sessions}")
    print(f"research_turns_imported={migrated_turns}")
    print("legacy_json_retained=true")


if __name__ == "__main__":
    main()
