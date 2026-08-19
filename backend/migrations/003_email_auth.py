"""Apply the idempotent email-authentication schema migration."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

from storage.mysql_db import get_pool  # noqa: E402


def main() -> None:
    sql_path = Path(__file__).with_suffix(".sql")
    lines = [
        line
        for line in sql_path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--") and not line.lstrip().upper().startswith("USE ")
    ]
    statements = [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]
    with get_pool().connection() as connection, connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    print("email_auth_schema=ready")


if __name__ == "__main__":
    main()
