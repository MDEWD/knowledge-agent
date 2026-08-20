"""Persistent completed DeepResearch conversations.

MySQL is the runtime store. The legacy JSON implementation remains available
for tests, migration and deployments that explicitly select the JSON backend.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone

from auth.context import get_current_user_id, user_data_path
from storage.mysql_db import ensure_user, get_pool, mysql_enabled

_LOCK = threading.RLock()
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def append_pending_turn(turns: list[dict], question: str) -> tuple[list[dict], int]:
    """Append one run as a distinct conversation turn.

    Question text is not a stable identity: a user may intentionally ask the
    same follow-up twice. The run owns the returned zero-based index instead.
    """
    next_turns = [dict(turn) for turn in turns]
    next_turns.append({"question": question, "answer": ""})
    return next_turns, len(next_turns) - 1


def complete_turn(
    turns: list[dict],
    turn_index: int,
    *,
    question: str,
    answer: str,
) -> list[dict]:
    """Complete the turn allocated to a run without replacing another turn."""
    next_turns = [dict(turn) for turn in turns]
    while len(next_turns) <= turn_index:
        next_turns.append({"question": "", "answer": ""})
    next_turns[turn_index] = {"question": question, "answer": answer}
    return next_turns
# Test/migration compatibility hook. Runtime storage remains tenant-scoped when
# this value is ``None``.
_HISTORY_FILE = None


def _history_file():
    return _HISTORY_FILE or user_data_path("deep_research_history.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_unlocked() -> list[dict]:
    history_file = _history_file()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    if not history_file.exists():
        return []
    try:
        payload = json.loads(history_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _save_unlocked(sessions: list[dict]) -> None:
    history_file = _history_file()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = history_file.with_suffix(".tmp")
    temp_path.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(history_file)


def list_sessions() -> list[dict]:
    if mysql_enabled():
        return _list_mysql()
    return list_legacy_sessions()


def get_session(session_id: str) -> dict | None:
    if mysql_enabled():
        return _get_mysql(session_id)
    return get_legacy_session(session_id)


def upsert_session(session: dict) -> dict:
    if mysql_enabled():
        return _upsert_mysql(session)
    return upsert_legacy_session(session)


def delete_session(session_id: str) -> bool:
    if mysql_enabled():
        return _delete_mysql(session_id)
    return delete_legacy_session(session_id)


def list_legacy_sessions() -> list[dict]:
    with _LOCK:
        sessions = _load_unlocked()
    sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return [
        {
            "id": item.get("id", ""),
            "title": item.get("title", "Deep Research"),
            "run_id": item.get("run_id", ""),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
            "turn_count": len(item.get("turns", [])),
        }
        for item in sessions
        if item.get("id")
    ]


def get_legacy_session(session_id: str) -> dict | None:
    with _LOCK:
        return next((item for item in _load_unlocked() if item.get("id") == session_id), None)


def upsert_legacy_session(session: dict) -> dict:
    with _LOCK:
        sessions = _load_unlocked()
        existing = next((item for item in sessions if item.get("id") == session["id"]), None)
        now = _now()
        record = {
            "id": session["id"],
            "title": session.get("title") or "Deep Research",
            "run_id": session.get("run_id") or "",
            "turns": list(session.get("turns") or []),
            "evidence": list(session.get("evidence") or []),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        sessions = [item for item in sessions if item.get("id") != record["id"]]
        sessions.insert(0, record)
        _save_unlocked(sessions)
        return record


def delete_legacy_session(session_id: str) -> bool:
    with _LOCK:
        sessions = _load_unlocked()
        remaining = [item for item in sessions if item.get("id") != session_id]
        if len(remaining) == len(sessions):
            return False
        _save_unlocked(remaining)
        return True


def _as_iso(value) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value or "")


def _parse_json(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _score(value):
    if value is None:
        return None
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None


def _list_mysql() -> list[dict]:
    user_id = get_current_user_id()
    with get_pool().connection() as connection, connection.cursor() as cursor:
        ensure_user(cursor, user_id)
        cursor.execute(
            """
            SELECT s.id, s.title, s.metadata_json, s.created_at, s.updated_at,
                   COUNT(t.id) AS turn_count
            FROM research_sessions s
            LEFT JOIN research_turns t ON t.session_id = s.id
            WHERE s.user_id = %s
            GROUP BY s.id, s.title, s.metadata_json, s.created_at, s.updated_at
            ORDER BY s.updated_at DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "run_id": _parse_json(row.get("metadata_json")).get("run_id", ""),
            "created_at": _as_iso(row["created_at"]),
            "updated_at": _as_iso(row["updated_at"]),
            "turn_count": int(row["turn_count"] or 0),
        }
        for row in rows
    ]


def _get_mysql(session_id: str) -> dict | None:
    user_id = get_current_user_id()
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, title, metadata_json, created_at, updated_at
            FROM research_sessions
            WHERE id = %s AND user_id = %s
            """,
            (session_id, user_id),
        )
        session = cursor.fetchone()
        if session is None:
            return None
        cursor.execute(
            """
            SELECT id, turn_index, question, answer_markdown
            FROM research_turns
            WHERE session_id = %s
            ORDER BY turn_index
            """,
            (session_id,),
        )
        turns = cursor.fetchall()
        evidence_rows = []
        if turns:
            cursor.execute(
                """
                SELECT id, source_type, title, url, snippet, published_at,
                       authority_score, freshness_score, metadata_json
                FROM research_evidence
                WHERE turn_id = %s
                ORDER BY id
                """,
                (turns[-1]["id"],),
            )
            evidence_rows = cursor.fetchall()
    evidence = []
    for row in evidence_rows:
        source_metadata = _parse_json(row.get("metadata_json"))
        evidence.append({
            "source_id": source_metadata.get("source_id") or row["id"],
            "query": source_metadata.get("query") or "",
            "title": row.get("title") or row.get("url") or "Untitled source",
            "url": row.get("url") or "",
            "snippet": row.get("snippet") or "",
            "status": source_metadata.get("status") or "summarized",
            "published_at": _as_iso(row.get("published_at")) or None,
            "source_type": row.get("source_type") or "web",
            "authority_score": _score(row.get("authority_score")),
            "freshness_score": _score(row.get("freshness_score")),
        })
    return {
        "id": session["id"],
        "title": session["title"],
        "run_id": _parse_json(session.get("metadata_json")).get("run_id", ""),
        "turns": [{"question": row["question"], "answer": row["answer_markdown"]} for row in turns],
        "evidence": evidence,
        "created_at": _as_iso(session["created_at"]),
        "updated_at": _as_iso(session["updated_at"]),
    }


def _upsert_mysql(session: dict) -> dict:
    user_id = get_current_user_id()
    session_id = str(session["id"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    metadata = json.dumps({"run_id": session.get("run_id") or ""}, ensure_ascii=False)
    turns = list(session.get("turns") or [])
    with get_pool().connection() as connection, connection.cursor() as cursor:
        ensure_user(cursor, user_id)
        cursor.execute(
            "SELECT user_id FROM research_sessions WHERE id=%s FOR UPDATE",
            (session_id,),
        )
        owner = cursor.fetchone()
        if owner and owner["user_id"] != user_id:
            raise PermissionError("research session belongs to another user")
        cursor.execute(
            """
            INSERT INTO research_sessions
                (id, user_id, title, status, metadata_json, created_at, updated_at)
            VALUES (%s, %s, %s, 'completed', %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title), status = 'completed',
                metadata_json = VALUES(metadata_json), updated_at = VALUES(updated_at)
            """,
            (session_id, user_id, session.get("title") or "Deep Research", metadata, now, now),
        )
        if turns:
            cursor.executemany(
                """
                INSERT INTO research_turns
                    (id, session_id, turn_index, question, answer_markdown, status, completed_at)
                VALUES (%s, %s, %s, %s, %s, 'completed', %s)
                ON DUPLICATE KEY UPDATE
                    question = VALUES(question), answer_markdown = VALUES(answer_markdown),
                    status = 'completed', completed_at = VALUES(completed_at)
                """,
                [
                    (
                        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{session_id}:{index}")),
                        session_id,
                        index,
                        str(turn.get("question") or ""),
                        str(turn.get("answer") or ""),
                        now,
                    )
                    for index, turn in enumerate(turns, start=1)
                ],
            )
        cursor.execute(
            "DELETE FROM research_turns WHERE session_id = %s AND turn_index > %s",
            (session_id, len(turns)),
        )

        # Evidence belongs to the newest turn. Existing earlier turns keep their
        # own evidence when a follow-up extends the session.
        evidence = session.get("evidence")
        if turns and evidence is not None:
            turn_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{session_id}:{len(turns)}"))
            cursor.execute("DELETE FROM research_evidence WHERE turn_id = %s", (turn_id,))
            evidence_by_url: dict[str, str] = {}
            for source in evidence:
                url = str(source.get("url") or "").strip()
                title = str(source.get("title") or url or "Untitled source").strip()[:500]
                identity = url or f"{title}:{source.get('snippet') or ''}"
                evidence_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{turn_id}:{identity}"))
                metadata_json = json.dumps(
                    {
                        "source_id": source.get("source_id"),
                        "query": source.get("query"),
                        "status": source.get("status"),
                    },
                    ensure_ascii=False,
                )
                cursor.execute(
                    """
                    INSERT INTO research_evidence
                        (id, turn_id, source_type, title, url, url_hash, snippet,
                         published_at, authority_score, freshness_score, metadata_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        evidence_id,
                        turn_id,
                        str(source.get("source_type") or "web")[:40],
                        title,
                        url or None,
                        hashlib.sha256(url.encode("utf-8")).digest() if url else None,
                        str(source.get("snippet") or "") or None,
                        _parse_datetime(source.get("published_at")),
                        _score(source.get("authority_score")),
                        _score(source.get("freshness_score")),
                        metadata_json,
                    ),
                )
                if url:
                    evidence_by_url[url] = evidence_id

            answer = str(turns[-1].get("answer") or "")
            citation_rows = []
            for claim_index, line in enumerate(answer.splitlines(), start=1):
                citation_index = 0
                for match in _MARKDOWN_LINK_RE.finditer(line):
                    evidence_id = evidence_by_url.get(match.group(2))
                    if not evidence_id:
                        continue
                    citation_index += 1
                    citation_rows.append(
                        (
                            turn_id,
                            evidence_id,
                            claim_index,
                            citation_index,
                            line.strip() or match.group(1),
                            "validated",
                            "Matched to persisted research evidence",
                        )
                    )
            if citation_rows:
                cursor.executemany(
                    """
                    INSERT INTO research_citations
                        (turn_id, evidence_id, claim_index, citation_index,
                         claim_text, validation_status, validation_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    citation_rows,
                )
    return _get_mysql(session_id) or session


def _delete_mysql(session_id: str) -> bool:
    user_id = get_current_user_id()
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM research_sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id),
        )
        return cursor.rowcount > 0
