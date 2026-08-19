"""Email authentication and request-scoped identity."""

from auth.context import get_current_user_id, user_scope

__all__ = ["get_current_user_id", "user_scope"]
