"""FastAPI email-authentication endpoints using HttpOnly cookies."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from auth.security import TokenValidationError, decode_token
from auth.mailer import send_action_code
from auth.service import (
    AuthError,
    authenticate,
    create_session,
    get_user,
    register,
    request_password_reset_code,
    request_verification_code,
    reset_password_with_code,
    revoke_session,
    rotate_session,
    verify_email_code,
)
from config import (
    AUTH_ACCESS_COOKIE_NAME,
    AUTH_ACCESS_TOKEN_MINUTES,
    AUTH_CODE_MINUTES,
    AUTH_COOKIE_SAMESITE,
    AUTH_COOKIE_SECURE,
    AUTH_EXPOSE_CODES,
    AUTH_REFRESH_COOKIE_NAME,
    AUTH_REFRESH_TOKEN_DAYS,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class VerifyCodeRequest(EmailRequest):
    code: str = Field(min_length=6, max_length=6)


class ResetPasswordRequest(VerifyCodeRequest):
    new_password: str = Field(min_length=8, max_length=128)


def _client_metadata(request: Request) -> tuple[str, str]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded or (request.client.host if request.client else "")
    return ip_address, request.headers.get("user-agent", "")


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    common = {
        "httponly": True,
        "secure": AUTH_COOKIE_SECURE,
        "samesite": AUTH_COOKIE_SAMESITE,
    }
    response.set_cookie(
        AUTH_ACCESS_COOKIE_NAME,
        access,
        max_age=AUTH_ACCESS_TOKEN_MINUTES * 60,
        path="/api",
        **common,
    )
    response.set_cookie(
        AUTH_REFRESH_COOKIE_NAME,
        refresh,
        max_age=AUTH_REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        path="/api/auth",
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(AUTH_ACCESS_COOKIE_NAME, path="/api")
    response.delete_cookie(AUTH_REFRESH_COOKIE_NAME, path="/api/auth")


def _auth_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthError):
        if exc.code == "email_exists":
            status = 409
        elif exc.code in {"invalid_credentials", "account_locked"}:
            status = 401
        elif exc.code in {"email_unverified", "account_disabled"}:
            status = 403
        elif exc.code == "code_rate_limited":
            status = 429
        else:
            status = 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=401, detail={"code": "invalid_session", "message": "登录状态已失效"})


async def _deliver(email: str, code: str, purpose: str) -> dict:
    try:
        channel = await asyncio.to_thread(
            send_action_code, email, code, purpose, AUTH_CODE_MINUTES
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "email_delivery_failed", "message": "邮件发送失败，请检查 SMTP 配置"},
        ) from exc
    result = {
        "ok": True,
        "delivery": channel,
        "message": "验证码已发送到邮箱" if channel == "smtp" else "SMTP 未配置，验证码已输出到后端终端",
    }
    if AUTH_EXPOSE_CODES:
        result["dev_code"] = code
    return result


@router.post("/register", status_code=201)
async def register_account(payload: RegisterRequest, request: Request, response: Response):
    try:
        user = register(payload.email, payload.password, payload.display_name)
        _, code = request_verification_code(user["email"])
    except (AuthError, TokenValidationError) as exc:
        raise _auth_error(exc) from exc
    delivery = await _deliver(user["email"], code, "verify_email")
    return {"user": user, "requires_verification": True, **delivery}


@router.post("/verify-email")
async def verify_email(payload: VerifyCodeRequest, request: Request, response: Response):
    try:
        user = verify_email_code(payload.email, payload.code)
        ip_address, user_agent = _client_metadata(request)
        access, refresh = create_session(user["id"], ip_address=ip_address, user_agent=user_agent)
    except (AuthError, TokenValidationError) as exc:
        raise _auth_error(exc) from exc
    _set_auth_cookies(response, access, refresh)
    return {"user": user}


@router.post("/resend-verification")
async def resend_verification(payload: EmailRequest):
    try:
        user, code = request_verification_code(payload.email)
    except AuthError as exc:
        raise _auth_error(exc) from exc
    return await _deliver(user["email"], code, "verify_email")


@router.post("/forgot-password")
async def forgot_password(payload: EmailRequest):
    try:
        issued = request_password_reset_code(payload.email)
    except AuthError as exc:
        if exc.code in {"code_rate_limited", "account_not_found"}:
            issued = None
        else:
            raise _auth_error(exc) from exc
    if issued:
        user, code = issued
        try:
            await _deliver(user["email"], code, "reset_password")
        except HTTPException as exc:
            # Do not reveal whether an email exists through delivery behavior.
            print(f"[Auth/reset_password] delivery failed for {user['email']}: {exc.detail}")
    return {"ok": True, "message": "如果该邮箱已注册，验证码将发送到邮箱"}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, response: Response):
    try:
        reset_password_with_code(payload.email, payload.code, payload.new_password)
    except AuthError as exc:
        raise _auth_error(exc) from exc
    _clear_auth_cookies(response)
    return {"ok": True, "message": "密码已重置，请重新登录"}


@router.post("/login")
async def login_account(payload: LoginRequest, request: Request, response: Response):
    try:
        user = authenticate(payload.email, payload.password)
        ip_address, user_agent = _client_metadata(request)
        access, refresh = create_session(user["id"], ip_address=ip_address, user_agent=user_agent)
    except (AuthError, TokenValidationError) as exc:
        raise _auth_error(exc) from exc
    _set_auth_cookies(response, access, refresh)
    return {"user": user}


@router.post("/refresh")
async def refresh_account(request: Request, response: Response):
    token = request.cookies.get(AUTH_REFRESH_COOKIE_NAME, "")
    if not token:
        raise _auth_error(TokenValidationError("missing refresh token"))
    try:
        user, access, refresh = rotate_session(token)
    except (AuthError, TokenValidationError) as exc:
        _clear_auth_cookies(response)
        raise _auth_error(exc) from exc
    _set_auth_cookies(response, access, refresh)
    return {"user": user}


@router.post("/logout")
async def logout_account(request: Request, response: Response):
    token = request.cookies.get(AUTH_REFRESH_COOKIE_NAME, "")
    if token:
        revoke_session(token)
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me")
async def current_account(request: Request):
    token = request.cookies.get(AUTH_ACCESS_COOKIE_NAME, "")
    try:
        payload = decode_token(token, "access")
    except TokenValidationError as exc:
        raise _auth_error(exc) from exc
    user = get_user(str(payload["sub"]))
    if not user:
        raise _auth_error(TokenValidationError("user is inactive"))
    return {"user": user}
