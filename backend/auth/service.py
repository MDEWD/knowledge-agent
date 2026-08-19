"""Database-backed email account and refresh-session service."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from pymysql.err import IntegrityError

from auth.security import (
    TokenValidationError,
    action_code_digest,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_action_code,
    hash_password,
    token_digest,
    verify_password,
)
from config import (
    AUTH_ADMIN_EMAILS,
    AUTH_CODE_MAX_ATTEMPTS,
    AUTH_CODE_MINUTES,
    AUTH_CODE_RESEND_SECONDS,
    AUTH_REFRESH_TOKEN_DAYS,
)
from storage.mysql_db import get_pool

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MAX_FAILURES = 5
_LOCK_MINUTES = 15


class AuthError(ValueError):
    def __init__(self, message: str, *, code: str = "auth_error") -> None:
        super().__init__(message)
        self.code = code


def normalise_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 255 or not _EMAIL_RE.fullmatch(value):
        raise AuthError("请输入有效的邮箱地址", code="invalid_email")
    return value


def validate_password(password: str) -> None:
    if len(password) < 8 or len(password) > 128:
        raise AuthError("密码长度需要在 8 到 128 位之间", code="invalid_password")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise AuthError("密码必须同时包含字母和数字", code="invalid_password")


def public_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row.get("email") or "",
        "display_name": row.get("display_name") or "",
        "role": row.get("role") or "user",
        "status": row.get("status") or "active",
        "email_verified": bool(row.get("email_verified_at")),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
    }


def get_user(user_id: str) -> dict | None:
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, email, display_name, role, status, email_verified_at, created_at
            FROM users WHERE id=%s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
    if not row or row.get("status") != "active" or not row.get("email_verified_at"):
        return None
    return public_user(row)


def register(email: str, password: str, display_name: str = "") -> dict:
    email = normalise_email(email)
    validate_password(password)
    name = display_name.strip()[:120] or email.split("@", 1)[0]
    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)
    role = "admin" if email in AUTH_ADMIN_EMAILS else "user"
    try:
        with get_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (id, email, display_name, status, role, auth_provider, auth_subject)
                VALUES (%s, %s, %s, 'pending', %s, 'password', %s)
                """,
                (user_id, email, name, role, email),
            )
            cursor.execute(
                "INSERT INTO user_credentials (user_id, password_hash) VALUES (%s, %s)",
                (user_id, password_hash),
            )
    except IntegrityError as exc:
        raise AuthError("该邮箱已经注册", code="email_exists") from exc
    return {
        "id": user_id,
        "email": email,
        "display_name": name,
        "role": role,
        "status": "pending",
        "email_verified": False,
        "created_at": None,
    }


def authenticate(email: str, password: str) -> dict:
    email = normalise_email(email)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    failure: AuthError | None = None
    authenticated_row: dict | None = None
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT u.id, u.email, u.display_name, u.role, u.status,
                   u.email_verified_at, u.created_at,
                   c.password_hash, c.failed_login_count, c.locked_until
            FROM users u
            JOIN user_credentials c ON c.user_id = u.id
            WHERE u.email = %s
            FOR UPDATE
            """,
            (email,),
        )
        row = cursor.fetchone()
        if not row:
            failure = AuthError("邮箱或密码错误", code="invalid_credentials")
        elif row.get("status") == "pending" or not row.get("email_verified_at"):
            failure = AuthError("请先完成邮箱验证", code="email_unverified")
        elif row.get("status") != "active":
            failure = AuthError("账户已被停用，请联系管理员", code="account_disabled")
        elif row.get("locked_until") and row["locked_until"] > now:
            failure = AuthError("登录失败次数过多，请稍后再试", code="account_locked")
        elif not verify_password(password, row["password_hash"]):
            failures = int(row.get("failed_login_count") or 0) + 1
            locked_until = now + timedelta(minutes=_LOCK_MINUTES) if failures >= _MAX_FAILURES else None
            cursor.execute(
                "UPDATE user_credentials SET failed_login_count=%s, locked_until=%s WHERE user_id=%s",
                (failures, locked_until, row["id"]),
            )
            failure = AuthError("邮箱或密码错误", code="invalid_credentials")
        else:
            cursor.execute(
                "UPDATE user_credentials SET failed_login_count=0, locked_until=NULL WHERE user_id=%s",
                (row["id"],),
            )
            authenticated_row = row
    if failure:
        raise failure
    if authenticated_row is None:
        raise AuthError("邮箱或密码错误", code="invalid_credentials")
    return public_user(authenticated_row)


def create_session(user_id: str, *, ip_address: str = "", user_agent: str = "") -> tuple[str, str]:
    session_id = str(uuid.uuid4())
    refresh = create_refresh_token(user_id, session_id)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=AUTH_REFRESH_TOKEN_DAYS)
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO auth_sessions
                (id, user_id, refresh_token_hash, ip_address, user_agent, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                session_id, user_id, token_digest(refresh), ip_address[:45] or None,
                user_agent[:500] or None, expires_at,
            ),
        )
    return create_access_token(user_id), refresh


def rotate_session(refresh_token: str) -> tuple[dict, str, str]:
    payload = decode_token(refresh_token, "refresh")
    user_id = str(payload["sub"])
    session_id = str(payload["sid"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    new_refresh = create_refresh_token(user_id, session_id)
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.refresh_token_hash, s.expires_at, s.revoked_at,
                   u.id, u.email, u.display_name, u.role, u.status,
                   u.email_verified_at, u.created_at
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.id=%s AND s.user_id=%s
            FOR UPDATE
            """,
            (session_id, user_id),
        )
        row = cursor.fetchone()
        if (
            not row
            or row.get("revoked_at") is not None
            or row.get("expires_at") <= now
            or row.get("status") != "active"
            or not row.get("email_verified_at")
            or row.get("refresh_token_hash") != token_digest(refresh_token)
        ):
            raise TokenValidationError("refresh session is invalid")
        cursor.execute(
            """
            UPDATE auth_sessions
            SET refresh_token_hash=%s, last_seen_at=%s
            WHERE id=%s
            """,
            (token_digest(new_refresh), now, session_id),
        )
    return public_user(row), create_access_token(user_id), new_refresh


def revoke_session(refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, "refresh")
    except TokenValidationError:
        return
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE auth_sessions SET revoked_at=%s WHERE id=%s AND user_id=%s AND revoked_at IS NULL",
            (
                datetime.now(timezone.utc).replace(tzinfo=None),
                str(payload["sid"]),
                str(payload["sub"]),
            ),
        )


def _issue_action_code(email: str, purpose: str, *, hide_missing: bool = False) -> tuple[dict, str] | None:
    email = normalise_email(email)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, email, display_name, role, status, email_verified_at, created_at
            FROM users WHERE email=%s FOR UPDATE
            """,
            (email,),
        )
        user = cursor.fetchone()
        if not user:
            if hide_missing:
                return None
            raise AuthError("没有找到该邮箱账户", code="account_not_found")
        if purpose == "verify_email" and user.get("status") != "pending":
            raise AuthError("该邮箱已经验证或账户不可用", code="already_verified")
        if purpose == "reset_password" and user.get("status") != "active":
            return None

        cursor.execute(
            """
            SELECT created_at FROM auth_action_codes
            WHERE user_id=%s AND purpose=%s
            ORDER BY created_at DESC LIMIT 1
            """,
            (user["id"], purpose),
        )
        previous = cursor.fetchone()
        if previous and previous["created_at"] > now - timedelta(seconds=AUTH_CODE_RESEND_SECONDS):
            raise AuthError("验证码发送过于频繁，请稍后再试", code="code_rate_limited")

        code = generate_action_code()
        cursor.execute(
            """
            UPDATE auth_action_codes SET consumed_at=%s
            WHERE user_id=%s AND purpose=%s AND consumed_at IS NULL
            """,
            (now, user["id"], purpose),
        )
        cursor.execute(
            """
            INSERT INTO auth_action_codes
                (id, user_id, purpose, code_hash, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()), user["id"], purpose,
                action_code_digest(user["id"], purpose, code),
                now + timedelta(minutes=AUTH_CODE_MINUTES),
            ),
        )
    return user, code


def request_verification_code(email: str) -> tuple[dict, str]:
    issued = _issue_action_code(email, "verify_email")
    if issued is None:
        raise AuthError("无法发送验证码", code="code_unavailable")
    return issued


def request_password_reset_code(email: str) -> tuple[dict, str] | None:
    return _issue_action_code(email, "reset_password", hide_missing=True)


def _consume_action_code(email: str, purpose: str, code: str, on_success=None) -> dict:
    email = normalise_email(email)
    code = code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise AuthError("请输入 6 位验证码", code="invalid_code")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    failure: AuthError | None = None
    user: dict | None = None
    with get_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT u.id, u.email, u.display_name, u.role, u.status,
                   u.email_verified_at, u.created_at,
                   c.id AS code_id, c.code_hash, c.attempt_count, c.expires_at
            FROM users u
            JOIN auth_action_codes c ON c.user_id=u.id
            WHERE u.email=%s AND c.purpose=%s AND c.consumed_at IS NULL
            ORDER BY c.created_at DESC LIMIT 1 FOR UPDATE
            """,
            (email, purpose),
        )
        row = cursor.fetchone()
        if not row:
            failure = AuthError("验证码无效或已使用", code="invalid_code")
        elif row["expires_at"] <= now:
            failure = AuthError("验证码已过期，请重新获取", code="expired_code")
        elif int(row.get("attempt_count") or 0) >= AUTH_CODE_MAX_ATTEMPTS:
            failure = AuthError("验证码错误次数过多，请重新获取", code="code_attempts_exceeded")
        elif not secrets.compare_digest(
            row["code_hash"], action_code_digest(row["id"], purpose, code)
        ):
            cursor.execute(
                "UPDATE auth_action_codes SET attempt_count=attempt_count+1 WHERE id=%s",
                (row["code_id"],),
            )
            failure = AuthError("验证码错误", code="invalid_code")
        else:
            cursor.execute(
                "UPDATE auth_action_codes SET consumed_at=%s WHERE id=%s",
                (now, row["code_id"]),
            )
            if on_success is not None:
                on_success(cursor, row, now)
            user = row
    if failure:
        raise failure
    if user is None:
        raise AuthError("验证码无效", code="invalid_code")
    return user


def verify_email_code(email: str, code: str) -> dict:
    def activate(cursor, user, now):
        cursor.execute(
            """
            UPDATE users SET status='active', email_verified_at=%s
            WHERE id=%s AND status='pending'
            """,
            (now, user["id"]),
        )
        user["status"] = "active"
        user["email_verified_at"] = now

    user = _consume_action_code(email, "verify_email", code, activate)
    return public_user(user)


def reset_password_with_code(email: str, code: str, new_password: str) -> None:
    validate_password(new_password)
    password_hash = hash_password(new_password)

    def change_password(cursor, user, now):
        cursor.execute(
            """
            UPDATE user_credentials
            SET password_hash=%s, failed_login_count=0, locked_until=NULL,
                password_updated_at=%s
            WHERE user_id=%s
            """,
            (password_hash, now, user["id"]),
        )
        cursor.execute(
            "UPDATE auth_sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL",
            (now, user["id"]),
        )

    _consume_action_code(email, "reset_password", code, change_password)
