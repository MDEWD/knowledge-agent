"""Password hashing and signed access/refresh token primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from config import (
    AUTH_ACCESS_TOKEN_MINUTES,
    AUTH_JWT_ALGORITHM,
    AUTH_REFRESH_TOKEN_DAYS,
    AUTH_SECRET_KEY,
)


class TokenValidationError(ValueError):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), encoded.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _encode_token(
    user_id: str,
    token_type: str,
    lifetime: timedelta,
    *,
    session_id: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": secrets.token_urlsafe(18),
    }
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, AUTH_SECRET_KEY, algorithm=AUTH_JWT_ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _encode_token(
        user_id,
        "access",
        timedelta(minutes=AUTH_ACCESS_TOKEN_MINUTES),
    )


def create_refresh_token(user_id: str, session_id: str) -> str:
    return _encode_token(
        user_id,
        "refresh",
        timedelta(days=AUTH_REFRESH_TOKEN_DAYS),
        session_id=session_id,
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenValidationError("invalid or expired token") from exc
    if payload.get("type") != expected_type or not payload.get("sub"):
        raise TokenValidationError("unexpected token type")
    if expected_type == "refresh" and not payload.get("sid"):
        raise TokenValidationError("refresh token has no session")
    return payload


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def generate_action_code() -> str:
    """Return a cryptographically secure six-digit email code."""
    return f"{secrets.randbelow(1_000_000):06d}"


def action_code_digest(user_id: str, purpose: str, code: str) -> bytes:
    """Key a low-entropy email code so a leaked database is not enough to brute-force it."""
    value = f"{user_id}:{purpose}:{code}".encode("utf-8")
    return hmac.new(AUTH_SECRET_KEY.encode("utf-8"), value, hashlib.sha256).digest()
