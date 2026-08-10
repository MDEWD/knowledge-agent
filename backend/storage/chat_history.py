"""Server-side persistence for the regular AI chat conversation."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from config import DEFAULT_USER_ID
from storage.mysql_db import ensure_user, get_pool


def _parse_json(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat()


def _public_id(session_id: str, index: int, value) -> str:
    candidate = str(value or "")
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{session_id}:{index}:{candidate}"))


def get_latest_session() -> dict | None:
    with get_pool().connection() as connection, connection.cursor() as cursor:
        ensure_user(cursor)
        cursor.execute(
            """
            SELECT id, title, model_name, created_at, updated_at
            FROM chat_sessions
            WHERE user_id = %s AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (DEFAULT_USER_ID,),
        )
        session = cursor.fetchone()
        if session is None:
            return None
        cursor.execute(
            """
            SELECT public_id, role, content, citations_json, tool_calls_json
            FROM chat_messages
            WHERE session_id = %s
            ORDER BY id
            """,
            (session["id"],),
        )
        rows = cursor.fetchall()
    messages = []
    for row in rows:
        message = {"id": row["public_id"], "role": row["role"], "content": row["content"]}
        metadata = _parse_json(row.get("tool_calls_json"), {})
        if isinstance(metadata, dict):
            message.update(metadata)
        citations = _parse_json(row.get("citations_json"), None)
        if citations:
            message["citations"] = citations
        messages.append(message)
    return {
        "id": session["id"],
        "title": session["title"],
        "model": session["model_name"] or "deepseek",
        "messages": messages,
        "created_at": _iso(session["created_at"]),
        "updated_at": _iso(session["updated_at"]),
    }


def save_session(session_id: str | None, messages: list[dict], model: str) -> dict:
    session_id = session_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    first_user = next(
        (str(message.get("content") or "").strip() for message in messages if message.get("role") == "user"),
        "",
    )
    title = first_user[:100] or "New Chat"
    with get_pool().connection() as connection, connection.cursor() as cursor:
        ensure_user(cursor)
        cursor.execute(
            """
            INSERT INTO chat_sessions
                (id, user_id, title, model_name, status, last_message_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'active', %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title), model_name = VALUES(model_name), status = 'active',
                last_message_at = VALUES(last_message_at), updated_at = VALUES(updated_at)
            """,
            (session_id, DEFAULT_USER_ID, title, model, now, now, now),
        )
        cursor.execute("DELETE FROM chat_messages WHERE session_id = %s", (session_id,))
        rows = []
        for index, message in enumerate(messages):
            public_id = _public_id(session_id, index, message.get("id"))
            role = str(message.get("role") or "assistant")
            if role not in {"system", "user", "assistant", "tool"}:
                role = "assistant"
            metadata = {
                key: value
                for key, value in message.items()
                if key not in {"id", "role", "content", "citations"} and value is not None
            }
            rows.append(
                (
                    public_id, session_id, role, str(message.get("content") or ""),
                    model if role == "assistant" else None,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    json.dumps(message.get("citations"), ensure_ascii=False) if message.get("citations") else None,
                    now,
                )
            )
        if rows:
            cursor.executemany(
                """
                INSERT INTO chat_messages
                    (public_id, session_id, role, content, model_name,
                     tool_calls_json, citations_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
    return {"id": session_id, "title": title, "model": model, "messages": messages}


def delete_session(session_id: str) -> bool:
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM chat_sessions WHERE id = %s AND user_id = %s",
            (session_id, DEFAULT_USER_ID),
        )
        return cursor.rowcount > 0
