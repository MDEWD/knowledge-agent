"""Destructive-only-to-fixture integration check for the MySQL Memory Runtime."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=True)
os.environ["MEMORY_STORAGE_BACKEND"] = "mysql"

from memory.runtime import MemoryCandidate, MemoryRuntime  # noqa: E402
from storage.mysql_db import get_pool  # noqa: E402


def candidate(value: str, task_type: str, *, source: str, explicitness: float) -> MemoryCandidate:
    return MemoryCandidate(
        category="profile",
        memory_type="preference",
        key="response_length",
        value=value,
        content=f"{task_type} response length is {value}",
        scope={"task_type": task_type},
        confidence=0.95,
        importance=0.9,
        explicitness=explicitness,
        source_type=source,
    )


def main() -> None:
    user_id = f"memory-smoke-{uuid.uuid4()}"
    runtime = MemoryRuntime(user_id)
    try:
        general = runtime.remember([candidate("short", "general_chat", source="explicit_user", explicitness=1.0)])
        deep = runtime.remember([candidate("detailed", "deep_research", source="explicit_user", explicitness=1.0)])
        assert general["inserted"] == 1 and deep["inserted"] == 1
        assert runtime.list_conflicts() == []

        general_recall = runtime.retrieve("回答方式", task_type="general_chat", agent_name="chat_assistant")
        deep_recall = runtime.retrieve("研究报告", task_type="deep_research", agent_name="supervisor")
        assert any(item["value"] == "short" for item in general_recall)
        assert all(item["scope"].get("task_type") != "deep_research" for item in general_recall)
        assert any(item["value"] == "detailed" for item in deep_recall)

        correction = runtime.remember([
            candidate("short", "deep_research", source="user_correction", explicitness=1.0)
        ])
        assert correction["superseded"] == 1

        uncertain = runtime.remember([
            candidate("detailed", "general_chat", source="chat_inference", explicitness=0.5)
        ])
        assert uncertain["conflicts"] == 1
        conflicts = runtime.list_conflicts()
        assert len(conflicts) == 1
        runtime.resolve_conflict(
            conflicts[0]["id"],
            int(conflicts[0]["existing_memory_id"]),
            "Keep the explicit user preference",
        )
        assert runtime.list_conflicts() == []

        observation_id = runtime.record_observation(
            "The user explicitly asked to be called Tony.",
            source_type="chat",
        )
        identity = MemoryCandidate(
            category="profile",
            memory_type="identity",
            key="preferred_name",
            value="Tony",
            content="Preferred name is Tony",
            confidence=0.99,
            importance=0.98,
            explicitness=1.0,
            source_type="explicit_user",
        )
        remembered = runtime.remember([identity], observation_id=observation_id)
        assert remembered["inserted"] == 1

        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM memory_fact_observations
                WHERE observation_id=%s
                """,
                (observation_id,),
            )
            assert cursor.fetchone()["total"] == 1
            cursor.execute(
                "SELECT COUNT(*) AS total FROM memory_usage_events WHERE user_id=%s",
                (user_id,),
            )
            assert cursor.fetchone()["total"] >= 2

        runtime.maintain()
        print("memory_v2_integration=passed")
    finally:
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM memory_conflicts WHERE user_id=%s", (user_id,))
            cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))


if __name__ == "__main__":
    main()
