"""Apply email-verification and administrator schema changes idempotently."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from config import AUTH_ADMIN_EMAILS, MYSQL_DATABASE
from storage.mysql_db import get_pool


AUTH_CODES_SQL = """
CREATE TABLE IF NOT EXISTS auth_action_codes (
  id CHAR(36) NOT NULL,
  user_id VARCHAR(64) NOT NULL,
  purpose VARCHAR(32) NOT NULL,
  code_hash BINARY(32) NOT NULL,
  attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
  expires_at DATETIME(6) NOT NULL,
  consumed_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_auth_codes_user_purpose (user_id, purpose, created_at DESC),
  KEY idx_auth_codes_expiry (expires_at),
  CONSTRAINT fk_auth_codes_user FOREIGN KEY (user_id) REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""

AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS auth_audit_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  actor_user_id VARCHAR(64) NULL,
  target_user_id VARCHAR(64) NULL,
  action VARCHAR(80) NOT NULL,
  details_json JSON NULL,
  ip_address VARCHAR(45) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_auth_audit_actor_created (actor_user_id, created_at DESC),
  KEY idx_auth_audit_target_created (target_user_id, created_at DESC),
  CONSTRAINT fk_auth_audit_actor FOREIGN KEY (actor_user_id) REFERENCES users (id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_auth_audit_target FOREIGN KEY (target_user_id) REFERENCES users (id)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""


def _columns(cursor) -> set[str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users'
        """,
        (MYSQL_DATABASE,),
    )
    return {row["COLUMN_NAME"] for row in cursor.fetchall()}


def _indexes(cursor) -> set[str]:
    cursor.execute(
        """
        SELECT DISTINCT INDEX_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users'
        """,
        (MYSQL_DATABASE,),
    )
    return {row["INDEX_NAME"] for row in cursor.fetchall()}


def main() -> None:
    with get_pool().connection() as connection, connection.cursor() as cursor:
        columns = _columns(cursor)
        if "role" not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user' AFTER status")
        if "email_verified_at" not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN email_verified_at DATETIME(6) NULL AFTER role")
        if "idx_users_role_status" not in _indexes(cursor):
            cursor.execute("ALTER TABLE users ADD KEY idx_users_role_status (role, status)")

        cursor.execute(AUTH_CODES_SQL)
        cursor.execute(AUDIT_SQL)

        # Accounts created before verification existed remain usable.
        cursor.execute(
            """
            UPDATE users
            SET email_verified_at=COALESCE(email_verified_at, created_at)
            WHERE email IS NOT NULL AND status='active'
            """
        )
        if AUTH_ADMIN_EMAILS:
            placeholders = ",".join(["%s"] * len(AUTH_ADMIN_EMAILS))
            cursor.execute(
                f"UPDATE users SET role='admin' WHERE LOWER(email) IN ({placeholders})",
                tuple(sorted(AUTH_ADMIN_EMAILS)),
            )

    print("Migration 004 applied: email verification, password reset and admin management are ready.")


if __name__ == "__main__":
    main()

