"""Administrator user/session operations with audit logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from auth.service import AuthError, public_user
from storage.mysql_db import get_pool

VALID_ROLES = {"user", "admin"}
VALID_STATUSES = {"active", "pending", "suspended"}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(cursor, actor_id: str, target_id: str, action: str, details: dict, ip_address: str = "") -> None:
    cursor.execute(
        """
        INSERT INTO auth_audit_logs
            (actor_user_id, target_user_id, action, details_json, ip_address)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (actor_id, target_id, action, json.dumps(details, ensure_ascii=False), ip_address[:45] or None),
    )


def list_users(*, query: str = "", role: str = "", status: str = "", limit: int = 50, offset: int = 0) -> dict:
    clauses: list[str] = []
    params: list[object] = []
    if query.strip():
        pattern = f"%{query.strip()}%"
        clauses.append("(u.email LIKE %s OR u.display_name LIKE %s)")
        params.extend([pattern, pattern])
    if role in VALID_ROLES:
        clauses.append("u.role=%s")
        params.append(role)
    if status in VALID_STATUSES:
        clauses.append("u.status=%s")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))

    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS total FROM users u {where}", tuple(params))
        total = int(cursor.fetchone()["total"])
        cursor.execute(
            f"""
            SELECT u.id, u.email, u.display_name, u.role, u.status,
                   u.email_verified_at, u.created_at,
                   COUNT(s.id) AS session_count,
                   MAX(s.last_seen_at) AS last_seen_at
            FROM users u
            LEFT JOIN auth_sessions s ON s.user_id=u.id AND s.revoked_at IS NULL
            {where}
            GROUP BY u.id, u.email, u.display_name, u.role, u.status,
                     u.email_verified_at, u.created_at
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple([*params, limit, offset]),
        )
        rows = cursor.fetchall()
    users = []
    for row in rows:
        item = public_user(row)
        item["session_count"] = int(row.get("session_count") or 0)
        item["last_seen_at"] = row["last_seen_at"].isoformat() if row.get("last_seen_at") else None
        users.append(item)
    return {"users": users, "total": total, "limit": limit, "offset": offset}


def update_user(
    actor_id: str,
    target_id: str,
    *,
    role: str | None = None,
    status: str | None = None,
    ip_address: str = "",
) -> dict:
    if role is not None and role not in VALID_ROLES:
        raise AuthError("不支持的用户角色", code="invalid_role")
    if status is not None and status not in VALID_STATUSES:
        raise AuthError("不支持的账户状态", code="invalid_status")
    if actor_id == target_id and (role is not None or status is not None):
        raise AuthError("不能修改自己的角色或状态", code="cannot_modify_self")

    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, email, display_name, role, status, email_verified_at, created_at
            FROM users WHERE id=%s FOR UPDATE
            """,
            (target_id,),
        )
        target = cursor.fetchone()
        if not target:
            raise AuthError("用户不存在", code="account_not_found")
        if status == "active" and not target.get("email_verified_at"):
            raise AuthError("邮箱尚未验证，不能直接启用", code="email_unverified")

        removes_admin = target.get("role") == "admin" and (
            role == "user" or status == "suspended"
        )
        if removes_admin:
            cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role='admin' AND status='active'")
            if int(cursor.fetchone()["total"]) <= 1:
                raise AuthError("系统至少需要保留一名有效管理员", code="last_admin")

        new_role = role or target["role"]
        new_status = status or target["status"]
        cursor.execute("UPDATE users SET role=%s, status=%s WHERE id=%s", (new_role, new_status, target_id))
        if new_status != "active":
            cursor.execute(
                "UPDATE auth_sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL",
                (_now(), target_id),
            )
        details = {
            "before": {"role": target["role"], "status": target["status"]},
            "after": {"role": new_role, "status": new_status},
        }
        _audit(cursor, actor_id, target_id, "user.updated", details, ip_address)
        target["role"] = new_role
        target["status"] = new_status
    return public_user(target)


def revoke_user_sessions(actor_id: str, target_id: str, *, ip_address: str = "") -> int:
    if actor_id == target_id:
        raise AuthError("请使用退出登录结束自己的会话", code="cannot_modify_self")
    now = _now()
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE id=%s", (target_id,))
        if not cursor.fetchone():
            raise AuthError("用户不存在", code="account_not_found")
        cursor.execute(
            "UPDATE auth_sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL",
            (now, target_id),
        )
        count = cursor.rowcount
        _audit(cursor, actor_id, target_id, "sessions.revoked", {"count": count}, ip_address)
    return int(count)


def list_audit_logs(limit: int = 100) -> list[dict]:
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT l.id, l.action, l.details_json, l.ip_address, l.created_at,
                   a.email AS actor_email, t.email AS target_email
            FROM auth_audit_logs l
            LEFT JOIN users a ON a.id=l.actor_user_id
            LEFT JOIN users t ON t.id=l.target_user_id
            ORDER BY l.created_at DESC LIMIT %s
            """,
            (max(1, min(200, int(limit))),),
        )
        rows = cursor.fetchall()
    for row in rows:
        if isinstance(row.get("details_json"), str):
            row["details"] = json.loads(row.pop("details_json") or "{}")
        else:
            row["details"] = row.pop("details_json", {}) or {}
        if row.get("created_at"):
            row["created_at"] = row["created_at"].isoformat()
    return rows

