"""Authenticate business APIs and keep identity bound through SSE streaming."""

from __future__ import annotations

from http.cookies import SimpleCookie

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from auth.context import bind_user, reset_user
from auth.security import TokenValidationError, decode_token
from config import AUTH_ACCESS_COOKIE_NAME


class ApiAuthenticationMiddleware:
    """Pure ASGI middleware so ContextVar survives the full streaming body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        if method == "OPTIONS" or not path.startswith("/api/") or path.startswith("/api/auth/"):
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}
        cookies = SimpleCookie()
        cookies.load(headers.get("cookie", ""))
        morsel = cookies.get(AUTH_ACCESS_COOKIE_NAME)
        token = morsel.value if morsel else ""
        try:
            payload = decode_token(token, "access")
        except TokenValidationError:
            response = JSONResponse(
                status_code=401,
                content={"detail": {"code": "authentication_required", "message": "请先登录"}},
            )
            await response(scope, receive, send)
            return

        user_id = str(payload["sub"])
        # An administrator suspension takes effect immediately instead of
        # waiting for the short-lived access token to expire.
        try:
            from auth.service import get_user

            user = get_user(user_id)
        except Exception:
            user = None
        if not user:
            response = JSONResponse(
                status_code=401,
                content={"detail": {"code": "invalid_account", "message": "账户不可用或登录已失效"}},
            )
            await response(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["user_id"] = user_id
        state["auth_user"] = user
        context_token = bind_user(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_user(context_token)
