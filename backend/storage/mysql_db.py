"""Small lazy MySQL connection pool for business persistence."""

from __future__ import annotations

import os
import queue
import threading
from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from config import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_POOL_SIZE,
    MYSQL_PORT,
    MYSQL_USER,
)


class MySQLPool:
    def __init__(self, max_size: int = MYSQL_POOL_SIZE) -> None:
        self._max_size = max(1, max_size)
        self._available: queue.LifoQueue[Connection] = queue.LifoQueue(self._max_size)
        self._created = 0
        self._lock = threading.Lock()

    def _connect(self) -> Connection:
        return pymysql.connect(
            host=os.environ.get("MYSQL_HOST", MYSQL_HOST),
            port=int(os.environ.get("MYSQL_PORT", str(MYSQL_PORT))),
            user=os.environ.get("MYSQL_USER", MYSQL_USER),
            password=os.environ.get("MYSQL_PASSWORD", MYSQL_PASSWORD),
            database=os.environ.get("MYSQL_DATABASE", MYSQL_DATABASE),
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=5,
            read_timeout=30,
            write_timeout=30,
        )

    def _acquire(self) -> Connection:
        try:
            connection = self._available.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self._max_size:
                    self._created += 1
                    try:
                        return self._connect()
                    except Exception:
                        self._created -= 1
                        raise
            connection = self._available.get(timeout=10)
        connection.ping(reconnect=True)
        return connection

    def _release(self, connection: Connection) -> None:
        try:
            self._available.put_nowait(connection)
        except queue.Full:
            connection.close()
            with self._lock:
                self._created = max(0, self._created - 1)

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        connection = self._acquire()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)


_pool: MySQLPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> MySQLPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = MySQLPool()
    return _pool


def mysql_enabled() -> bool:
    """Return whether business persistence should use MySQL."""
    configured = os.environ.get("MEMORY_STORAGE_BACKEND")
    if configured is not None:
        return configured.strip().lower() == "mysql"
    return bool(os.environ.get("MYSQL_PASSWORD", MYSQL_PASSWORD))


def ensure_user(cursor, user_id: str | None = None) -> None:
    from auth.context import get_current_user_id

    user_id = user_id or get_current_user_id()
    cursor.execute(
        """
        INSERT INTO users (id, username, display_name, status)
        VALUES (%s, %s, %s, 'active')
        ON DUPLICATE KEY UPDATE id = VALUES(id)
        """,
        (user_id, user_id, "本地用户" if user_id == "local-user" else user_id),
    )
