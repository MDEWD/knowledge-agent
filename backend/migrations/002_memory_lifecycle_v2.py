"""Idempotent MySQL migration for the production Memory lifecycle."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=True)

from config import MYSQL_DATABASE  # noqa: E402
from storage.mysql_db import get_pool  # noqa: E402


COLUMNS = {
    "memory_category": "VARCHAR(30) NOT NULL DEFAULT 'semantic' AFTER user_id",
    "memory_key": "VARCHAR(191) NULL AFTER memory_type",
    "value_json": "JSON NULL AFTER content",
    "scope_json": "JSON NULL AFTER value_json",
    "semantic_hash": "BINARY(32) NULL AFTER scope_json",
    "explicitness": "DECIMAL(5,4) NOT NULL DEFAULT 0.5000 AFTER salience",
    "utility_score": "DECIMAL(5,4) NOT NULL DEFAULT 0.5000 AFTER explicitness",
    "usage_count": "BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER utility_score",
    "version": "INT UNSIGNED NOT NULL DEFAULT 1 AFTER status",
    "valid_from": "DATETIME(6) NULL AFTER version",
    "valid_to": "DATETIME(6) NULL AFTER valid_from",
    "last_confirmed_at": "DATETIME(6) NULL AFTER last_used_at",
    "supersedes_id": "BIGINT UNSIGNED NULL AFTER last_confirmed_at",
}


CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS memory_observations (
      id CHAR(36) NOT NULL,
      user_id VARCHAR(64) NOT NULL,
      source_type VARCHAR(40) NOT NULL,
      source_id VARCHAR(100) NULL,
      content LONGTEXT NOT NULL,
      payload_json JSON NULL,
      selection_status VARCHAR(20) NOT NULL DEFAULT 'pending',
      selection_reason VARCHAR(500) NULL,
      importance DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
      observed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      processed_at DATETIME(6) NULL,
      reflected_at DATETIME(6) NULL,
      expires_at DATETIME(6) NULL,
      PRIMARY KEY (id),
      KEY idx_memory_observations_pending (user_id, selection_status, reflected_at),
      KEY idx_memory_observations_expiry (expires_at),
      CONSTRAINT fk_memory_observations_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_conflicts (
      id CHAR(36) NOT NULL,
      user_id VARCHAR(64) NOT NULL,
      existing_memory_id BIGINT UNSIGNED NOT NULL,
      candidate_memory_id BIGINT UNSIGNED NOT NULL,
      conflict_type VARCHAR(40) NOT NULL,
      resolution_status VARCHAR(20) NOT NULL DEFAULT 'pending',
      winner_memory_id BIGINT UNSIGNED NULL,
      resolution_reason VARCHAR(1000) NULL,
      resolved_by VARCHAR(40) NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      resolved_at DATETIME(6) NULL,
      PRIMARY KEY (id),
      KEY idx_memory_conflicts_user_status (user_id, resolution_status, created_at),
      CONSTRAINT fk_memory_conflicts_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
      CONSTRAINT fk_memory_conflicts_existing
        FOREIGN KEY (existing_memory_id) REFERENCES user_memory_facts (id),
      CONSTRAINT fk_memory_conflicts_candidate
        FOREIGN KEY (candidate_memory_id) REFERENCES user_memory_facts (id),
      CONSTRAINT fk_memory_conflicts_winner
        FOREIGN KEY (winner_memory_id) REFERENCES user_memory_facts (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_relations (
      id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      user_id VARCHAR(64) NOT NULL,
      source_memory_id BIGINT UNSIGNED NOT NULL,
      relation_type VARCHAR(50) NOT NULL,
      target_memory_id BIGINT UNSIGNED NOT NULL,
      confidence DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
      evidence_json JSON NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
      PRIMARY KEY (id),
      UNIQUE KEY uk_memory_relation
        (user_id, source_memory_id, relation_type, target_memory_id),
      KEY idx_memory_relations_target (target_memory_id, relation_type),
      CONSTRAINT fk_memory_relations_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
      CONSTRAINT fk_memory_relations_source
        FOREIGN KEY (source_memory_id) REFERENCES user_memory_facts (id)
        ON DELETE CASCADE,
      CONSTRAINT fk_memory_relations_target
        FOREIGN KEY (target_memory_id) REFERENCES user_memory_facts (id)
        ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_usage_events (
      id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      user_id VARCHAR(64) NOT NULL,
      memory_id BIGINT UNSIGNED NOT NULL,
      task_type VARCHAR(50) NULL,
      agent_name VARCHAR(80) NULL,
      query_text TEXT NULL,
      retrieval_score DECIMAL(7,6) NOT NULL DEFAULT 0,
      used_in_prompt BOOLEAN NOT NULL DEFAULT TRUE,
      outcome_score DECIMAL(5,4) NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      PRIMARY KEY (id),
      KEY idx_memory_usage_fact_time (memory_id, created_at),
      KEY idx_memory_usage_user_task (user_id, task_type, created_at),
      CONSTRAINT fk_memory_usage_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
      CONSTRAINT fk_memory_usage_fact
        FOREIGN KEY (memory_id) REFERENCES user_memory_facts (id)
        ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_fact_observations (
      memory_id BIGINT UNSIGNED NOT NULL,
      observation_id CHAR(36) NOT NULL,
      contribution_type VARCHAR(30) NOT NULL DEFAULT 'support',
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      PRIMARY KEY (memory_id, observation_id),
      KEY idx_memory_fact_observations_observation (observation_id, memory_id),
      CONSTRAINT fk_memory_fact_observations_fact
        FOREIGN KEY (memory_id) REFERENCES user_memory_facts (id)
        ON DELETE CASCADE,
      CONSTRAINT fk_memory_fact_observations_observation
        FOREIGN KEY (observation_id) REFERENCES memory_observations (id)
        ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


def _exists(cursor, kind: str, name: str) -> bool:
    column = "COLUMN_NAME" if kind == "column" else "INDEX_NAME"
    table = "COLUMNS" if kind == "column" else "STATISTICS"
    cursor.execute(
        f"SELECT 1 FROM information_schema.{table} "
        f"WHERE TABLE_SCHEMA=%s AND TABLE_NAME='user_memory_facts' AND {column}=%s LIMIT 1",
        (MYSQL_DATABASE, name),
    )
    return cursor.fetchone() is not None


def _constraint_exists(cursor, name: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME='user_memory_facts'
          AND CONSTRAINT_NAME=%s
        LIMIT 1
        """,
        (MYSQL_DATABASE, name),
    )
    return cursor.fetchone() is not None


def main() -> None:
    with get_pool().connection() as connection, connection.cursor() as cursor:
        for name, definition in COLUMNS.items():
            if not _exists(cursor, "column", name):
                cursor.execute(f"ALTER TABLE user_memory_facts ADD COLUMN {name} {definition}")

        if not _exists(cursor, "index", "idx_memory_user_key_status"):
            cursor.execute(
                "CREATE INDEX idx_memory_user_key_status "
                "ON user_memory_facts (user_id, memory_type, memory_key, status)"
            )
        if not _exists(cursor, "index", "idx_memory_validity"):
            cursor.execute(
                "CREATE INDEX idx_memory_validity "
                "ON user_memory_facts (user_id, status, valid_from, valid_to, expires_at)"
            )
        if not _constraint_exists(cursor, "fk_memory_supersedes"):
            cursor.execute(
                """
                ALTER TABLE user_memory_facts
                ADD CONSTRAINT fk_memory_supersedes
                FOREIGN KEY (supersedes_id) REFERENCES user_memory_facts (id)
                ON DELETE SET NULL
                """
            )

        cursor.execute(
            """
            UPDATE user_memory_facts
            SET memory_category = CASE
                    WHEN memory_type IN ('summary', 'preference', 'identity') THEN 'profile'
                    WHEN memory_type IN ('procedure', 'lesson') THEN 'procedural'
                    ELSE 'semantic'
                END,
                memory_key = COALESCE(
                    memory_key,
                    CASE WHEN memory_type = 'summary' THEN 'profile_summary'
                         ELSE CONCAT(memory_type, ':', LEFT(SHA2(content, 256), 24)) END
                ),
                value_json = COALESCE(value_json, JSON_OBJECT('value', content)),
                scope_json = COALESCE(scope_json, JSON_OBJECT()),
                semantic_hash = COALESCE(semantic_hash, UNHEX(SHA2(LOWER(TRIM(content)), 256))),
                valid_from = COALESCE(valid_from, created_at),
                last_confirmed_at = COALESCE(last_confirmed_at, updated_at)
            """
        )

        for statement in CREATE_TABLES:
            cursor.execute(statement)

    print("memory_schema_v2=ready")


if __name__ == "__main__":
    main()
