-- Multi-Agent Platform: core identity, conversation, memory and research data.
-- Safe to run repeatedly on MySQL 8.x.

CREATE DATABASE IF NOT EXISTS `multi_agent_platform`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE `multi_agent_platform`;

CREATE TABLE IF NOT EXISTS `users` (
  `id` VARCHAR(64) NOT NULL,
  `username` VARCHAR(100) NULL,
  `display_name` VARCHAR(120) NULL,
  `email` VARCHAR(255) NULL,
  `auth_provider` VARCHAR(50) NULL,
  `auth_subject` VARCHAR(255) NULL,
  `status` VARCHAR(20) NOT NULL DEFAULT 'active',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`),
  UNIQUE KEY `uk_users_email` (`email`),
  UNIQUE KEY `uk_users_auth_identity` (`auth_provider`, `auth_subject`),
  KEY `idx_users_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `chat_sessions` (
  `id` CHAR(36) NOT NULL,
  `user_id` VARCHAR(64) NOT NULL,
  `title` VARCHAR(300) NOT NULL DEFAULT '新对话',
  `model_name` VARCHAR(120) NULL,
  `status` VARCHAR(20) NOT NULL DEFAULT 'active',
  `metadata_json` JSON NULL,
  `last_message_at` DATETIME(6) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_chat_sessions_user_updated` (`user_id`, `updated_at` DESC),
  KEY `idx_chat_sessions_user_status` (`user_id`, `status`),
  CONSTRAINT `fk_chat_sessions_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `chat_messages` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `public_id` CHAR(36) NOT NULL,
  `session_id` CHAR(36) NOT NULL,
  `role` VARCHAR(20) NOT NULL,
  `content` LONGTEXT NOT NULL,
  `model_name` VARCHAR(120) NULL,
  `tool_calls_json` JSON NULL,
  `citations_json` JSON NULL,
  `input_tokens` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `output_tokens` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_chat_messages_public_id` (`public_id`),
  KEY `idx_chat_messages_session_order` (`session_id`, `id`),
  CONSTRAINT `fk_chat_messages_session`
    FOREIGN KEY (`session_id`) REFERENCES `chat_sessions` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `ck_chat_messages_role`
    CHECK (`role` IN ('system', 'user', 'assistant', 'tool'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `user_memory_facts` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` VARCHAR(64) NOT NULL,
  `memory_type` VARCHAR(40) NOT NULL,
  `content` TEXT NOT NULL,
  `source_type` VARCHAR(40) NULL,
  `source_id` VARCHAR(100) NULL,
  `confidence` DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
  `salience` DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
  `status` VARCHAR(20) NOT NULL DEFAULT 'active',
  `metadata_json` JSON NULL,
  `last_used_at` DATETIME(6) NULL,
  `expires_at` DATETIME(6) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_memory_user_type_status` (`user_id`, `memory_type`, `status`),
  KEY `idx_memory_user_salience` (`user_id`, `salience` DESC),
  KEY `idx_memory_expiry` (`expires_at`),
  CONSTRAINT `fk_memory_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `ck_memory_confidence`
    CHECK (`confidence` >= 0 AND `confidence` <= 1),
  CONSTRAINT `ck_memory_salience`
    CHECK (`salience` >= 0 AND `salience` <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `research_sessions` (
  `id` CHAR(36) NOT NULL,
  `user_id` VARCHAR(64) NOT NULL,
  `title` VARCHAR(300) NOT NULL,
  `status` VARCHAR(20) NOT NULL DEFAULT 'active',
  `metadata_json` JSON NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_research_sessions_user_updated` (`user_id`, `updated_at` DESC),
  KEY `idx_research_sessions_user_status` (`user_id`, `status`),
  CONSTRAINT `fk_research_sessions_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `research_turns` (
  `id` CHAR(36) NOT NULL,
  `session_id` CHAR(36) NOT NULL,
  `run_id` CHAR(36) NULL,
  `turn_index` INT UNSIGNED NOT NULL,
  `question` LONGTEXT NOT NULL,
  `answer_markdown` LONGTEXT NOT NULL,
  `status` VARCHAR(20) NOT NULL DEFAULT 'completed',
  `model_config_json` JSON NULL,
  `evaluation_json` JSON NULL,
  `usage_json` JSON NULL,
  `cost_usd` DECIMAL(18,8) NOT NULL DEFAULT 0,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `completed_at` DATETIME(6) NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_research_turn_order` (`session_id`, `turn_index`),
  UNIQUE KEY `uk_research_turn_run` (`run_id`),
  KEY `idx_research_turns_session_created` (`session_id`, `created_at`),
  CONSTRAINT `fk_research_turns_session`
    FOREIGN KEY (`session_id`) REFERENCES `research_sessions` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `research_evidence` (
  `id` VARCHAR(100) NOT NULL,
  `turn_id` CHAR(36) NOT NULL,
  `source_type` VARCHAR(40) NOT NULL,
  `title` VARCHAR(500) NOT NULL,
  `url` TEXT NULL,
  `url_hash` BINARY(32) NULL,
  `snippet` MEDIUMTEXT NULL,
  `content` MEDIUMTEXT NULL,
  `published_at` DATETIME(6) NULL,
  `fetched_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `authority_score` DECIMAL(5,4) NULL,
  `freshness_score` DECIMAL(5,4) NULL,
  `metadata_json` JSON NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_research_evidence_url` (`turn_id`, `url_hash`),
  KEY `idx_research_evidence_turn` (`turn_id`),
  KEY `idx_research_evidence_type` (`source_type`),
  CONSTRAINT `fk_research_evidence_turn`
    FOREIGN KEY (`turn_id`) REFERENCES `research_turns` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `ck_evidence_authority_score`
    CHECK (`authority_score` IS NULL OR (`authority_score` >= 0 AND `authority_score` <= 1)),
  CONSTRAINT `ck_evidence_freshness_score`
    CHECK (`freshness_score` IS NULL OR (`freshness_score` >= 0 AND `freshness_score` <= 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `research_citations` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `turn_id` CHAR(36) NOT NULL,
  `evidence_id` VARCHAR(100) NOT NULL,
  `claim_index` INT UNSIGNED NOT NULL,
  `citation_index` INT UNSIGNED NOT NULL,
  `claim_text` TEXT NOT NULL,
  `validation_status` VARCHAR(20) NOT NULL DEFAULT 'pending',
  `validation_message` VARCHAR(1000) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_research_citation_position`
    (`turn_id`, `claim_index`, `citation_index`),
  KEY `idx_research_citations_evidence` (`evidence_id`),
  CONSTRAINT `fk_research_citations_turn`
    FOREIGN KEY (`turn_id`) REFERENCES `research_turns` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_research_citations_evidence`
    FOREIGN KEY (`evidence_id`) REFERENCES `research_evidence` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Keep the current single-user desktop experience usable before auth exists.
INSERT INTO `users` (`id`, `username`, `display_name`, `status`)
VALUES ('local-user', 'local-user', '本地用户', 'active')
ON DUPLICATE KEY UPDATE
  `display_name` = VALUES(`display_name`),
  `status` = VALUES(`status`);
