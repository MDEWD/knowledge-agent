"""Production migration helper: wait for MySQL and apply all idempotent migrations.

Run before `python app.py` in containerized deployments. Every step is safe to
repeat, so this also works as a manual migration command on any environment:

    python scripts/apply_migrations.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pymysql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from config import MYSQL_DATABASE, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER  # noqa: E402

MIGRATIONS_DIR = ROOT / "migrations"


def _server_connection() -> pymysql.connections.Connection:
    """Connect without selecting a database, so we can create it first."""
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=5,
    )


def wait_for_mysql(retries: int = 60, delay: float = 3.0) -> None:
    for attempt in range(1, retries + 1):
        try:
            connection = _server_connection()
            connection.close()
            print(f"mysql_ready (attempt {attempt})")
            return
        except pymysql.MySQLError as error:
            print(f"waiting_for_mysql ({attempt}/{retries}): {error}")
            time.sleep(delay)
    raise SystemExit("MySQL did not become ready in time.")


def ensure_database() -> None:
    with _server_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
            (MYSQL_DATABASE,),
        )
        if cursor.fetchone():
            print(f"database_ready={MYSQL_DATABASE}")
            return
        # The MySQL image creates MYSQL_DATABASE up front; this branch only runs
        # for self-managed MySQL where the migration account has server rights.
        cursor.execute(
            f"CREATE DATABASE `{MYSQL_DATABASE}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        print(f"database_ready={MYSQL_DATABASE} (created)")


def apply_sql_file(path: Path) -> None:
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
        and not line.lstrip().upper().startswith("USE ")
    ]
    statements = [
        s.strip()
        for s in "\n".join(lines).split(";")
        if s.strip() and not s.strip().upper().startswith("CREATE DATABASE")
    ]
    from storage.mysql_db import get_pool  # noqa: E402

    with get_pool().connection() as connection, connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    print(f"applied_sql={path.name}")


def run_python_migration(filename: str) -> None:
    script = MIGRATIONS_DIR / filename
    subprocess.run([sys.executable, str(script)], check=True)
    print(f"applied_python={filename}")


def main() -> None:
    wait_for_mysql()
    ensure_database()
    apply_sql_file(MIGRATIONS_DIR / "001_multi_agent_memory_schema.sql")
    run_python_migration("002_memory_lifecycle_v2.py")
    run_python_migration("003_email_auth.py")
    run_python_migration("004_email_verification_admin.py")
    print("migrations_complete")


if __name__ == "__main__":
    main()
