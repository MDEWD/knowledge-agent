-- Email verification, password recovery and administrator management.
-- Apply through 004_email_verification_admin.py for idempotent column checks.

USE `multi_agent_platform`;

ALTER TABLE `users`
  ADD COLUMN `role` VARCHAR(20) NOT NULL DEFAULT 'user' AFTER `status`,
  ADD COLUMN `email_verified_at` DATETIME(6) NULL AFTER `role`,
  ADD KEY `idx_users_role_status` (`role`, `status`);

CREATE TABLE IF NOT EXISTS `auth_action_codes` (
  `id` CHAR(36) NOT NULL,
  `user_id` VARCHAR(64) NOT NULL,
  `purpose` VARCHAR(32) NOT NULL,
  `code_hash` BINARY(32) NOT NULL,
  `attempt_count` INT UNSIGNED NOT NULL DEFAULT 0,
  `expires_at` DATETIME(6) NOT NULL,
  `consumed_at` DATETIME(6) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_auth_codes_user_purpose` (`user_id`, `purpose`, `created_at` DESC),
  KEY `idx_auth_codes_expiry` (`expires_at`),
  CONSTRAINT `fk_auth_codes_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `auth_audit_logs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `actor_user_id` VARCHAR(64) NULL,
  `target_user_id` VARCHAR(64) NULL,
  `action` VARCHAR(80) NOT NULL,
  `details_json` JSON NULL,
  `ip_address` VARCHAR(45) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_auth_audit_actor_created` (`actor_user_id`, `created_at` DESC),
  KEY `idx_auth_audit_target_created` (`target_user_id`, `created_at` DESC),
  CONSTRAINT `fk_auth_audit_actor`
    FOREIGN KEY (`actor_user_id`) REFERENCES `users` (`id`)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_auth_audit_target`
    FOREIGN KEY (`target_user_id`) REFERENCES `users` (`id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

