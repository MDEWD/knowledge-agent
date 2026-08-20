from __future__ import annotations

import pytest

from auth.context import get_current_user_id, user_scope
from auth.security import (
    TokenValidationError,
    action_code_digest,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    generate_action_code,
    token_digest,
    verify_password,
)


def test_password_hash_round_trip_and_digest_is_not_plaintext():
    encoded = hash_password("Research123")
    assert encoded != "Research123"
    assert verify_password("Research123", encoded) is True
    assert verify_password("wrong-password", encoded) is False


def test_access_and_refresh_tokens_have_distinct_contracts():
    access = create_access_token("user-1")
    refresh = create_refresh_token("user-1", "session-1")

    assert decode_token(access, "access")["sub"] == "user-1"
    assert decode_token(refresh, "refresh")["sid"] == "session-1"
    assert token_digest(refresh) != refresh.encode("utf-8")

    with pytest.raises(TokenValidationError):
        decode_token(access, "refresh")


def test_user_scope_restores_previous_identity():
    previous = get_current_user_id()
    with user_scope("tenant-a"):
        assert get_current_user_id() == "tenant-a"
        with user_scope("tenant-b"):
            assert get_current_user_id() == "tenant-b"
        assert get_current_user_id() == "tenant-a"
    assert get_current_user_id() == previous


def test_email_action_codes_are_six_digits_and_context_bound():
    code = generate_action_code()
    assert len(code) == 6
    assert code.isdigit()

    digest = action_code_digest("user-1", "verify_email", code)
    assert digest == action_code_digest("user-1", "verify_email", code)
    assert digest != action_code_digest("user-1", "reset_password", code)
    assert digest != action_code_digest("user-2", "verify_email", code)
