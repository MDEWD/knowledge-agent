"""FastAPI routes for administrator user management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth.admin_service import list_audit_logs, list_users, revoke_user_sessions, update_user
from auth.service import AuthError

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserUpdateRequest(BaseModel):
    role: str | None = None
    status: str | None = None


def _admin(request: Request) -> dict:
    user = getattr(request.state, "auth_user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "需要管理员权限"})
    return user


def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "")


def _error(exc: AuthError) -> HTTPException:
    status = 404 if exc.code == "account_not_found" else 409 if exc.code in {"last_admin", "cannot_modify_self"} else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/users")
async def users(request: Request, q: str = "", role: str = "", status: str = "", limit: int = 50, offset: int = 0):
    _admin(request)
    return list_users(query=q, role=role, status=status, limit=limit, offset=offset)


@router.patch("/users/{user_id}")
async def change_user(user_id: str, payload: UserUpdateRequest, request: Request):
    actor = _admin(request)
    try:
        user = update_user(
            actor["id"], user_id, role=payload.role, status=payload.status, ip_address=_ip(request)
        )
    except AuthError as exc:
        raise _error(exc) from exc
    return {"user": user}


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_sessions(user_id: str, request: Request):
    actor = _admin(request)
    try:
        count = revoke_user_sessions(actor["id"], user_id, ip_address=_ip(request))
    except AuthError as exc:
        raise _error(exc) from exc
    return {"ok": True, "revoked": count}


@router.get("/audit-logs")
async def audit_logs(request: Request, limit: int = 100):
    _admin(request)
    return {"logs": list_audit_logs(limit)}

