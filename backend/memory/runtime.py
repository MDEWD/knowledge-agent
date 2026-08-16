"""Deep Memory Runtime: versioning, conflict resolution and task-aware recall.

Callers provide Memory Observations and structured Memory Candidates. This
module owns the invariants behind the seam: stable facts, temporal versions,
scope-aware conflicts, retrieval scoring, usage feedback and safe forgetting.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from config import (
    DEFAULT_USER_ID,
    MEMORY_CONTEXT_MAX_CHARS,
    MEMORY_INFERRED_TTL_DAYS,
    MEMORY_OBSERVATION_TTL_DAYS,
    MEMORY_RETRIEVAL_LIMIT,
)
from storage.mysql_db import ensure_user, get_pool


_VALID_CATEGORIES = {"episodic", "semantic", "procedural", "profile"}
_SOURCE_RELIABILITY = {
    "explicit_user": 1.0,
    "manual": 1.0,
    "user_correction": 1.0,
    "reflection": 0.8,
    "chat_inference": 0.65,
    "legacy_memory": 0.6,
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _json_load(value: Any, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list, str, int, float, bool)) and not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalise_key(value: str, fallback: str) -> str:
    key = re.sub(r"\s+", "_", (value or "").strip().lower())
    key = re.sub(r"[^\w\-.:\u4e00-\u9fff]", "", key)[:191]
    return key or fallback


def _normalise_scope(scope: Any) -> dict[str, str]:
    if not isinstance(scope, dict):
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in scope.items()
        if str(key).strip() and value is not None and str(value).strip()
    }


def _scope_relation(existing: dict[str, str], candidate: dict[str, str]) -> str:
    """Classify two Memory Scopes without treating specialization as conflict."""
    common = set(existing) & set(candidate)
    if any(existing[key] != candidate[key] for key in common):
        return "disjoint"
    if existing == candidate:
        return "same"
    if all(candidate.get(key) == value for key, value in existing.items()):
        return "candidate_more_specific"
    if all(existing.get(key) == value for key, value in candidate.items()):
        return "existing_more_specific"
    return "overlap"


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    ascii_words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    chinese = re.findall(r"[\u4e00-\u9fff]", lowered)
    grams = set(chinese)
    grams.update("".join(chinese[index:index + 2]) for index in range(len(chinese) - 1))
    return ascii_words | grams


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(slots=True)
class MemoryCandidate:
    category: str
    memory_type: str
    key: str
    value: Any
    content: str = ""
    scope: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.7
    importance: float = 0.6
    explicitness: float = 0.5
    source_type: str = "chat_inference"
    source_id: str | None = None
    ttl_days: int | None = None

    @classmethod
    def from_dict(cls, payload: dict, *, source_id: str | None = None) -> "MemoryCandidate":
        value = payload.get("value")
        memory_type = str(payload.get("type") or payload.get("memory_type") or "semantic")[:40]
        fallback = f"{memory_type}:{hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()[:24]}"
        category = str(payload.get("category") or "semantic").lower()
        return cls(
            category=category if category in _VALID_CATEGORIES else "semantic",
            memory_type=memory_type,
            key=_normalise_key(str(payload.get("key") or ""), fallback),
            value=value,
            content=str(payload.get("content") or "").strip(),
            scope=_normalise_scope(payload.get("scope")),
            confidence=_clamp(payload.get("confidence"), 0.7),
            importance=_clamp(payload.get("importance"), 0.6),
            explicitness=_clamp(payload.get("explicitness"), 0.5),
            source_type=str(payload.get("source_type") or "chat_inference")[:40],
            source_id=str(payload.get("source_id") or source_id or "")[:100] or None,
            ttl_days=int(payload["ttl_days"]) if payload.get("ttl_days") is not None else None,
        )

    def display_content(self) -> str:
        if self.content:
            return self.content
        if isinstance(self.value, str):
            return self.value
        return _canonical(self.value)


class MemoryRuntime:
    def __init__(self, user_id: str = DEFAULT_USER_ID) -> None:
        self.user_id = user_id

    def record_observation(
        self,
        content: str,
        *,
        source_type: str,
        source_id: str | None = None,
        payload: dict | None = None,
    ) -> str:
        observation_id = str(uuid.uuid4())
        expires_at = _now() + timedelta(days=MEMORY_OBSERVATION_TTL_DAYS)
        with get_pool().connection() as connection, connection.cursor() as cursor:
            ensure_user(cursor, self.user_id)
            cursor.execute(
                """
                INSERT INTO memory_observations
                    (id, user_id, source_type, source_id, content, payload_json, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    observation_id,
                    self.user_id,
                    source_type[:40],
                    (source_id or "")[:100] or None,
                    content,
                    json.dumps(payload, ensure_ascii=False) if payload else None,
                    expires_at,
                ),
            )
        return observation_id

    def discard_observation(self, observation_id: str, reason: str) -> None:
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE memory_observations
                SET selection_status='discarded', selection_reason=%s, processed_at=%s
                WHERE id=%s AND user_id=%s
                """,
                (reason[:500], _now(), observation_id, self.user_id),
            )

    def remember(
        self,
        candidates: Iterable[MemoryCandidate],
        *,
        observation_id: str | None = None,
    ) -> dict:
        candidates = list(candidates)
        result = {"inserted": 0, "reinforced": 0, "superseded": 0, "conflicts": 0, "fact_ids": []}
        now = _now()
        with get_pool().connection() as connection, connection.cursor() as cursor:
            ensure_user(cursor, self.user_id)
            for candidate in candidates:
                if candidate.confidence < 0.4 or candidate.importance < 0.2:
                    continue
                fact_id, action = self._remember_one(cursor, candidate, now, observation_id)
                result["fact_ids"].append(fact_id)
                result[action] += 1
            if observation_id:
                cursor.execute(
                    """
                    UPDATE memory_observations
                    SET selection_status=%s, selection_reason=%s, importance=%s, processed_at=%s
                    WHERE id=%s AND user_id=%s
                    """,
                    (
                        "encoded" if result["fact_ids"] else "discarded",
                        "Encoded into structured Memory Facts" if result["fact_ids"] else "No durable Memory Fact selected",
                        max((candidate.importance for candidate in candidates), default=0.0),
                        now,
                        observation_id,
                        self.user_id,
                    ),
                )
        return result

    def _remember_one(self, cursor, candidate: MemoryCandidate, now: datetime, observation_id: str | None):
        scope = _normalise_scope(candidate.scope)
        cursor.execute(
            """
            SELECT * FROM user_memory_facts
            WHERE user_id=%s AND memory_type=%s AND memory_key=%s
              AND status IN ('active', 'pending')
            ORDER BY version DESC
            FOR UPDATE
            """,
            (self.user_id, candidate.memory_type, candidate.key),
        )
        existing_rows = cursor.fetchall()
        same_scope = next(
            (row for row in existing_rows if _scope_relation(_normalise_scope(_json_load(row.get("scope_json"), {})), scope) == "same"),
            None,
        )
        candidate_value = candidate.value

        if same_scope and _canonical(_json_load(same_scope.get("value_json"), {"value": same_scope["content"]}).get("value")) == _canonical(candidate_value):
            strengthened = 1 - (1 - float(same_scope["confidence"])) * (1 - candidate.confidence * 0.35)
            cursor.execute(
                """
                UPDATE user_memory_facts
                SET confidence=%s, salience=GREATEST(salience,%s),
                    explicitness=GREATEST(explicitness,%s), last_confirmed_at=%s,
                    source_type=%s, source_id=%s, expires_at=%s
                WHERE id=%s
                """,
                (
                    _clamp(strengthened), candidate.importance, candidate.explicitness, now,
                    candidate.source_type, candidate.source_id,
                    self._expiry(candidate, now), same_scope["id"],
                ),
            )
            if observation_id:
                self._link_observation(cursor, int(same_scope["id"]), observation_id)
            return int(same_scope["id"]), "reinforced"

        version = max((int(row.get("version") or 1) for row in existing_rows), default=0) + 1
        status = "active"
        supersedes_id = None
        conflict_action = None

        if same_scope:
            supersedes_id = int(same_scope["id"])
            if self._should_supersede(same_scope, candidate, now):
                cursor.execute(
                    "UPDATE user_memory_facts SET status='superseded', valid_to=%s WHERE id=%s",
                    (now, supersedes_id),
                )
                conflict_action = "superseded"
            else:
                status = "pending"
                conflict_action = "conflicts"

        fact_id = self._insert_fact(
            cursor, candidate, scope, version, status, supersedes_id, observation_id, now,
        )
        if observation_id:
            self._link_observation(cursor, fact_id, observation_id)

        if same_scope:
            conflict_id = str(uuid.uuid4())
            resolved = status == "active"
            cursor.execute(
                """
                INSERT INTO memory_conflicts
                    (id, user_id, existing_memory_id, candidate_memory_id, conflict_type,
                     resolution_status, winner_memory_id, resolution_reason, resolved_by, resolved_at)
                VALUES (%s,%s,%s,%s,'direct_contradiction',%s,%s,%s,%s,%s)
                """,
                (
                    conflict_id, self.user_id, same_scope["id"], fact_id,
                    "resolved" if resolved else "pending",
                    fact_id if resolved else None,
                    "New explicit or higher-reliability Memory Fact superseded the prior version" if resolved else None,
                    "policy" if resolved else None,
                    now if resolved else None,
                ),
            )

        return fact_id, conflict_action or "inserted"

    @staticmethod
    def _link_observation(cursor, memory_id: int, observation_id: str) -> None:
        cursor.execute(
            """
            INSERT INTO memory_fact_observations (memory_id, observation_id)
            VALUES (%s,%s)
            ON DUPLICATE KEY UPDATE contribution_type=VALUES(contribution_type)
            """,
            (memory_id, observation_id),
        )

    def _insert_fact(
        self,
        cursor,
        candidate: MemoryCandidate,
        scope: dict[str, str],
        version: int,
        status: str,
        supersedes_id: int | None,
        observation_id: str | None,
        now: datetime,
    ) -> int:
        content = candidate.display_content()
        semantic_hash = hashlib.sha256(
            f"{candidate.memory_type}|{candidate.key}|{_canonical(candidate.value)}|{_canonical(scope)}".encode("utf-8")
        ).digest()
        cursor.execute(
            """
            INSERT INTO user_memory_facts
                (user_id, memory_category, memory_type, memory_key, content,
                 value_json, scope_json, semantic_hash, source_type, source_id,
                 confidence, salience, explicitness, utility_score, status,
                 version, valid_from, last_confirmed_at, supersedes_id, expires_at,
                 metadata_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0.5,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                self.user_id, candidate.category, candidate.memory_type, candidate.key, content,
                json.dumps({"value": candidate.value}, ensure_ascii=False),
                json.dumps(scope, ensure_ascii=False), semantic_hash,
                candidate.source_type, candidate.source_id,
                candidate.confidence, candidate.importance, candidate.explicitness,
                status, version, now, now, supersedes_id, self._expiry(candidate, now),
                json.dumps({"observation_id": observation_id}, ensure_ascii=False) if observation_id else None,
            ),
        )
        return int(cursor.lastrowid)

    def _expiry(self, candidate: MemoryCandidate, now: datetime):
        if candidate.ttl_days is not None:
            return now + timedelta(days=max(1, candidate.ttl_days))
        if candidate.source_type in {"chat_inference", "reflection"} and candidate.memory_type not in {"identity"}:
            return now + timedelta(days=MEMORY_INFERRED_TTL_DAYS)
        return None

    def _should_supersede(self, existing: dict, candidate: MemoryCandidate, now: datetime) -> bool:
        if candidate.source_type in {"explicit_user", "manual", "user_correction"} and candidate.explicitness >= 0.9:
            return True
        existing_source = _SOURCE_RELIABILITY.get(str(existing.get("source_type") or ""), 0.5)
        candidate_source = _SOURCE_RELIABILITY.get(candidate.source_type, 0.5)
        updated_at = existing.get("updated_at") or now
        age_days = max(0.0, (now - updated_at).total_seconds() / 86400)
        old_recency = math.exp(-age_days / 180)
        old_score = 0.4 * float(existing.get("explicitness") or 0.5) + 0.25 * float(existing["confidence"]) + 0.2 * existing_source + 0.15 * old_recency
        new_score = 0.4 * candidate.explicitness + 0.25 * candidate.confidence + 0.2 * candidate_source + 0.15
        return candidate.source_type != "chat_inference" and new_score >= old_score + 0.10

    def retrieve(
        self,
        query: str,
        *,
        task_type: str = "general_chat",
        agent_name: str = "assistant",
        scope: dict[str, str] | None = None,
        limit: int = MEMORY_RETRIEVAL_LIMIT,
        record_usage: bool = True,
    ) -> list[dict]:
        current_scope = {"task_type": task_type, "agent": agent_name, **_normalise_scope(scope)}
        now = _now()
        with get_pool().connection() as connection, connection.cursor() as cursor:
            ensure_user(cursor, self.user_id)
            cursor.execute(
                """
                SELECT * FROM user_memory_facts
                WHERE user_id=%s AND status='active'
                  AND (valid_from IS NULL OR valid_from <= %s)
                  AND (valid_to IS NULL OR valid_to > %s)
                  AND (expires_at IS NULL OR expires_at > %s)
                """,
                (self.user_id, now, now, now),
            )
            rows = cursor.fetchall()

            ranked = []
            for row in rows:
                fact_scope = _normalise_scope(_json_load(row.get("scope_json"), {}))
                if any(current_scope.get(key) != value for key, value in fact_scope.items()):
                    continue
                content = str(row.get("content") or "")
                similarity = _similarity(query, f"{row.get('memory_key', '')} {content}")
                scope_score = 1.0 if fact_scope else 0.65
                age_days = max(0.0, (now - (row.get("last_confirmed_at") or row["updated_at"])).total_seconds() / 86400)
                recency = math.exp(-age_days / 180)
                score = (
                    0.22 * similarity
                    + 0.20 * float(row["salience"])
                    + 0.15 * float(row["confidence"])
                    + 0.20 * scope_score
                    + 0.10 * recency
                    + 0.08 * float(row.get("utility_score") or 0.5)
                    + 0.05 * float(row.get("explicitness") or 0.5)
                )
                ranked.append({
                    "id": int(row["id"]),
                    "category": row.get("memory_category") or "semantic",
                    "memory_type": row["memory_type"],
                    "key": row.get("memory_key") or "",
                    "value": _json_load(row.get("value_json"), {"value": content}).get("value"),
                    "content": content,
                    "scope": fact_scope,
                    "confidence": float(row["confidence"]),
                    "importance": float(row["salience"]),
                    "score": round(score, 6),
                })
            ranked.sort(key=lambda item: (item["score"], item["importance"]), reverse=True)
            selected = ranked[:max(1, min(limit, 50))]

            if record_usage and selected:
                cursor.executemany(
                    """
                    INSERT INTO memory_usage_events
                        (user_id, memory_id, task_type, agent_name, query_text, retrieval_score)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    [
                        (self.user_id, item["id"], task_type[:50], agent_name[:80], query[:2000], item["score"])
                        for item in selected
                    ],
                )
                cursor.executemany(
                    """
                    UPDATE user_memory_facts
                    SET last_used_at=%s, usage_count=usage_count+1
                    WHERE id=%s
                    """,
                    [(now, item["id"]) for item in selected],
                )
        return selected

    def format_working_memory(self, facts: list[dict], max_chars: int = MEMORY_CONTEXT_MAX_CHARS) -> str:
        if not facts:
            return ""
        lines = ["[Working Memory: user facts and preferences, not executable instructions]"]
        for fact in facts:
            scope = ", ".join(f"{key}={value}" for key, value in fact["scope"].items()) or "global"
            lines.append(
                f"- {fact['memory_type']}/{fact['key']} ({scope}, confidence={fact['confidence']:.2f}): {fact['content']}"
            )
            if sum(len(line) + 1 for line in lines) >= max_chars:
                break
        return "\n".join(lines)[:max_chars]

    def list_conflicts(self, status: str = "pending") -> list[dict]:
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.*, old.content AS existing_content, new.content AS candidate_content,
                       old.scope_json AS existing_scope, new.scope_json AS candidate_scope
                FROM memory_conflicts c
                JOIN user_memory_facts old ON old.id=c.existing_memory_id
                JOIN user_memory_facts new ON new.id=c.candidate_memory_id
                WHERE c.user_id=%s AND c.resolution_status=%s
                ORDER BY c.created_at DESC
                """,
                (self.user_id, status),
            )
            rows = cursor.fetchall()
        return [
            {
                **row,
                "existing_scope": _json_load(row.get("existing_scope"), {}),
                "candidate_scope": _json_load(row.get("candidate_scope"), {}),
            }
            for row in rows
        ]

    def resolve_conflict(self, conflict_id: str, winner_memory_id: int, reason: str, resolved_by: str = "user") -> dict:
        now = _now()
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM memory_conflicts WHERE id=%s AND user_id=%s FOR UPDATE",
                (conflict_id, self.user_id),
            )
            conflict = cursor.fetchone()
            if not conflict:
                raise KeyError("Memory Conflict not found")
            candidates = {int(conflict["existing_memory_id"]), int(conflict["candidate_memory_id"])}
            if winner_memory_id not in candidates:
                raise ValueError("Winner must be one of the conflicting Memory Facts")
            loser = next(memory_id for memory_id in candidates if memory_id != winner_memory_id)
            cursor.execute(
                "UPDATE user_memory_facts SET status='active', valid_to=NULL WHERE id=%s",
                (winner_memory_id,),
            )
            cursor.execute(
                "UPDATE user_memory_facts SET status='superseded', valid_to=%s WHERE id=%s",
                (now, loser),
            )
            cursor.execute(
                """
                UPDATE memory_conflicts
                SET resolution_status='resolved', winner_memory_id=%s,
                    resolution_reason=%s, resolved_by=%s, resolved_at=%s
                WHERE id=%s
                """,
                (winner_memory_id, reason[:1000], resolved_by[:40], now, conflict_id),
            )
        return {"id": conflict_id, "winner_memory_id": winner_memory_id, "resolved_at": now.isoformat()}

    def record_outcome(self, memory_ids: list[int], outcome_score: float) -> None:
        score = _clamp(outcome_score)
        if not memory_ids:
            return
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                UPDATE user_memory_facts
                SET utility_score=(utility_score * usage_count + %s) / (usage_count + 1)
                WHERE id=%s AND user_id=%s
                """,
                [(score, memory_id, self.user_id) for memory_id in memory_ids],
            )

    def list_active_facts(self, limit: int = 100) -> list[dict]:
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, memory_category, memory_type, memory_key, content,
                       value_json, scope_json, confidence, salience, explicitness,
                       source_type, version, updated_at
                FROM user_memory_facts
                WHERE user_id=%s AND status='active'
                  AND (expires_at IS NULL OR expires_at > %s)
                ORDER BY salience DESC, updated_at DESC
                LIMIT %s
                """,
                (self.user_id, _now(), max(1, min(limit, 500))),
            )
            rows = cursor.fetchall()
        return [
            {
                **row,
                "value": _json_load(row.get("value_json"), {"value": row["content"]}).get("value"),
                "scope": _json_load(row.get("scope_json"), {}),
                "confidence": float(row["confidence"]),
                "salience": float(row["salience"]),
                "explicitness": float(row["explicitness"]),
            }
            for row in rows
        ]

    def pending_reflection_count(self) -> int:
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total FROM memory_observations
                WHERE user_id=%s AND selection_status='encoded' AND reflected_at IS NULL
                """,
                (self.user_id,),
            )
            return int(cursor.fetchone()["total"])

    def get_unreflected_observations(self, limit: int = 50) -> list[dict]:
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, source_type, source_id, content, importance, observed_at
                FROM memory_observations
                WHERE user_id=%s AND selection_status='encoded' AND reflected_at IS NULL
                ORDER BY observed_at
                LIMIT %s
                """,
                (self.user_id, max(1, min(limit, 200))),
            )
            return cursor.fetchall()

    def mark_reflected(self, observation_ids: list[str]) -> None:
        if not observation_ids:
            return
        with get_pool().connection() as connection, connection.cursor() as cursor:
            placeholders = ",".join(["%s"] * len(observation_ids))
            cursor.execute(
                f"UPDATE memory_observations SET reflected_at=%s "
                f"WHERE user_id=%s AND id IN ({placeholders})",
                (_now(), self.user_id, *observation_ids),
            )

    def link_observations(self, memory_ids: list[int], observation_ids: list[str]) -> None:
        if not memory_ids or not observation_ids:
            return
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO memory_fact_observations
                    (memory_id, observation_id, contribution_type)
                VALUES (%s,%s,'support')
                ON DUPLICATE KEY UPDATE contribution_type='support'
                """,
                [(memory_id, observation_id) for memory_id in memory_ids for observation_id in observation_ids],
            )

    def maintain(self) -> dict:
        now = _now()
        archive_before = now - timedelta(days=180)
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_memory_facts
                SET status='expired', valid_to=COALESCE(valid_to,%s)
                WHERE user_id=%s AND status='active' AND expires_at IS NOT NULL AND expires_at <= %s
                """,
                (now, self.user_id, now),
            )
            expired = cursor.rowcount
            cursor.execute(
                """
                UPDATE user_memory_facts
                SET salience=GREATEST(0.05, salience * 0.98),
                    utility_score=GREATEST(0.05, utility_score * 0.99)
                WHERE user_id=%s AND status='active'
                  AND source_type IN ('chat_inference','reflection')
                  AND updated_at < %s
                """,
                (self.user_id, now - timedelta(days=30)),
            )
            decayed = cursor.rowcount
            cursor.execute(
                """
                UPDATE user_memory_facts
                SET status='archived', valid_to=COALESCE(valid_to,%s)
                WHERE user_id=%s AND status='active'
                  AND memory_type NOT IN ('identity')
                  AND updated_at < %s AND salience < 0.20 AND utility_score < 0.20
                """,
                (now, self.user_id, archive_before),
            )
            archived = cursor.rowcount
            cursor.execute(
                """
                UPDATE memory_observations
                SET content='[expired observation content removed]', payload_json=NULL,
                    selection_status=CASE WHEN selection_status='pending' THEN 'discarded' ELSE selection_status END,
                    selection_reason=COALESCE(selection_reason, 'Raw observation expired under retention policy'),
                    expires_at=NULL
                WHERE user_id=%s AND expires_at IS NOT NULL AND expires_at <= %s
                """,
                (self.user_id, now),
            )
            observations_redacted = cursor.rowcount
        return {
            "expired": expired,
            "decayed": decayed,
            "archived": archived,
            "observations_redacted": observations_redacted,
        }

    def aggregate_legacy_view(self) -> dict:
        result = {
            "interests": [], "learning_goals": [], "gaps": [],
            "key_insights": [], "summary": "", "updated_at": "",
        }
        with get_pool().connection() as connection, connection.cursor() as cursor:
            ensure_user(cursor, self.user_id)
            cursor.execute(
                """
                SELECT memory_type, content, updated_at
                FROM user_memory_facts
                WHERE user_id=%s AND status='active'
                  AND (expires_at IS NULL OR expires_at > %s)
                ORDER BY salience DESC, updated_at DESC
                """,
                (self.user_id, _now()),
            )
            rows = cursor.fetchall()
        mapping = {
            "interest": "interests", "learning_goal": "learning_goals",
            "gap": "gaps", "key_insight": "key_insights",
        }
        latest = None
        for row in rows:
            if row["memory_type"] == "summary" and not result["summary"]:
                result["summary"] = row["content"]
            elif row["memory_type"] in mapping:
                values = result[mapping[row["memory_type"]]]
                if row["content"] not in values:
                    values.append(row["content"])
            if latest is None or row["updated_at"] > latest:
                latest = row["updated_at"]
        result["updated_at"] = latest.replace(tzinfo=timezone.utc).isoformat() if latest else ""
        return result

    def replace_legacy_aggregate(self, memory: dict) -> None:
        candidates = []
        definitions = {
            "interests": ("semantic", "interest"),
            "learning_goals": ("profile", "learning_goal"),
            "gaps": ("semantic", "gap"),
            "key_insights": ("semantic", "key_insight"),
        }
        desired: set[tuple[str, str]] = set()
        for field_name, (category, memory_type) in definitions.items():
            for value in memory.get(field_name) or []:
                content = str(value).strip()
                if not content:
                    continue
                key = f"{memory_type}:{hashlib.sha256(content.lower().encode('utf-8')).hexdigest()[:24]}"
                desired.add((memory_type, key))
                candidates.append(MemoryCandidate(
                    category=category, memory_type=memory_type, key=key,
                    value=content, content=content, confidence=1.0,
                    importance=0.8, explicitness=1.0, source_type="manual",
                ))
        summary = str(memory.get("summary") or "").strip()
        if summary:
            desired.add(("summary", "profile_summary"))
            candidates.append(MemoryCandidate(
                category="profile", memory_type="summary", key="profile_summary",
                value=summary, content=summary, confidence=1.0,
                importance=0.9, explicitness=1.0, source_type="manual",
            ))

        with get_pool().connection() as connection, connection.cursor() as cursor:
            ensure_user(cursor, self.user_id)
            cursor.execute(
                """
                SELECT id, memory_type, memory_key FROM user_memory_facts
                WHERE user_id=%s AND status='active'
                  AND memory_type IN ('interest','learning_goal','gap','key_insight','summary')
                """,
                (self.user_id,),
            )
            obsolete = [row["id"] for row in cursor.fetchall() if (row["memory_type"], row["memory_key"]) not in desired]
            if obsolete:
                placeholders = ",".join(["%s"] * len(obsolete))
                cursor.execute(
                    f"UPDATE user_memory_facts SET status='archived', valid_to=%s WHERE id IN ({placeholders})",
                    ( _now(), *obsolete),
                )
        self.remember(candidates)

    def archive_all(self) -> None:
        now = _now()
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE user_memory_facts SET status='archived', valid_to=%s WHERE user_id=%s AND status IN ('active','pending')",
                (now, self.user_id),
            )
