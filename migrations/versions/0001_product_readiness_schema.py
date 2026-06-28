"""Create product-readiness tables and columns.

This migration captures schema changes that were previously created lazily by
runtime code. Existing lazy guards remain temporarily as a compatibility net,
but production databases should run migrations before application deploys.
"""

revision = "0001_product_readiness_schema"


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


def _add_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if _table_exists(cursor, table_name) and not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def _index_columns(cursor, table_name: str, index_name: str) -> str:
    cursor.execute(
        """
        SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table_name, index_name),
    )
    row = cursor.fetchone() or {}
    return row.get("cols") or ""


def upgrade(cursor) -> None:
    _add_column(cursor, "clubs", "cm_bonus_admin_chat_id", "VARCHAR(80) NULL AFTER secret")
    _add_column(cursor, "clubs", "instagram_url", "VARCHAR(255) NULL")
    _add_column(cursor, "clubs", "youtube_url", "VARCHAR(255) NULL")
    _add_column(cursor, "clubs", "vk_url", "VARCHAR(255) NULL")
    _add_column(cursor, "clubs", "telegram_channel_url", "VARCHAR(255) NULL")
    _add_column(cursor, "clubs", "yandex_maps_url", "VARCHAR(255) NULL")
    _add_column(cursor, "clubs", "two_gis_url", "VARCHAR(255) NULL")

    _add_column(cursor, "guest_login_tokens", "club_id", "INT NULL AFTER guest_id")

    _add_column(cursor, "club_missions", "custom_name", "VARCHAR(255) NULL AFTER mission_template_id")
    _add_column(cursor, "club_missions", "custom_description", "TEXT NULL AFTER custom_name")
    _add_column(cursor, "club_missions", "reward_text", "VARCHAR(255) NULL AFTER target_amount")
    _add_column(cursor, "club_missions", "token_reward", "INT NOT NULL DEFAULT 0 AFTER reward_text")
    _add_column(cursor, "club_missions", "cm_bonus_reward", "INT NOT NULL DEFAULT 0 AFTER token_reward")

    _add_column(
        cursor,
        "club_wheel_prizes",
        "icon_emoji",
        "VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL AFTER image_url",
    )
    _add_column(cursor, "club_wheel_prizes", "bonus_amount", "INT NOT NULL DEFAULT 0 AFTER image_url")
    _add_column(cursor, "club_wheel_prizes", "token_amount", "INT NOT NULL DEFAULT 0 AFTER bonus_amount")
    if _table_exists(cursor, "club_wheel_prizes") and _column_exists(cursor, "club_wheel_prizes", "icon_emoji"):
        cursor.execute(
            """
            ALTER TABLE club_wheel_prizes
            MODIFY icon_emoji VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL
            """
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cm_bonus_balances (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            balance INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_cm_bonus_balance (club_id, guest_id),
            KEY idx_cm_bonus_balance_guest (guest_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cm_bonus_transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            amount INT NOT NULL,
            balance_after INT NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            source_id VARCHAR(120) NULL,
            description VARCHAR(255) NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'done',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_cm_bonus_source (club_id, guest_id, source_type, source_id),
            KEY idx_cm_bonus_guest_created (club_id, guest_id, created_at),
            KEY idx_cm_bonus_source_type (source_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cm_bonus_redeem_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            amount INT NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'pending',
            admin_chat_id VARCHAR(80) NULL,
            telegram_message_id BIGINT NULL,
            error_text TEXT NULL,
            requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at DATETIME NULL,
            processed_by_telegram_id BIGINT NULL,
            processed_by_username VARCHAR(255) NULL,
            KEY idx_cm_bonus_redeem_guest (club_id, guest_id, requested_at),
            KEY idx_cm_bonus_redeem_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    _add_column(cursor, "cm_bonus_redeem_requests", "processed_by_telegram_id", "BIGINT NULL")
    _add_column(cursor, "cm_bonus_redeem_requests", "processed_by_username", "VARCHAR(255) NULL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_wheel_token_balances (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            balance INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_wheel_token_balance (club_id, guest_id),
            KEY idx_guest_wheel_token_balance_guest (guest_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_wheel_token_transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            amount INT NOT NULL,
            balance_after INT NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            source_id VARCHAR(120) NULL,
            description VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_guest_wheel_token_source (club_id, guest_id, source_type, source_id),
            KEY idx_guest_wheel_token_guest_created (club_id, guest_id, created_at),
            KEY idx_guest_wheel_token_source_type (source_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_prize_claims (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            spin_id INT NOT NULL,
            prize_id INT NOT NULL,
            prize_name VARCHAR(255) NOT NULL,
            prize_description TEXT NULL,
            prize_image_url TEXT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'pending',
            admin_chat_id VARCHAR(80) NULL,
            telegram_message_id BIGINT NULL,
            notify_error TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notified_at DATETIME NULL,
            issued_at DATETIME NULL,
            issued_by_telegram_id BIGINT NULL,
            issued_by_username VARCHAR(255) NULL,
            cancelled_at DATETIME NULL,
            cancelled_by_telegram_id BIGINT NULL,
            cancel_reason VARCHAR(255) NULL,
            KEY idx_prize_claims_club_status (club_id, status),
            KEY idx_prize_claims_guest (club_id, guest_id, created_at),
            KEY idx_prize_claims_spin (spin_id),
            UNIQUE KEY uq_prize_claim_spin (spin_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS club_pc_names (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            uuid VARCHAR(100) NOT NULL,
            display_name VARCHAR(120) NULL,
            sort_order INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_club_pc_uuid (club_id, uuid),
            KEY idx_club_pc_order (club_id, sort_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS auto_mailing_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            code VARCHAR(80) NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NULL,
            message_text TEXT NOT NULL,
            days_inactive INT NOT NULL DEFAULT 14,
            bonus_amount INT NOT NULL DEFAULT 200,
            repeat_after_days INT NOT NULL DEFAULT 30,
            is_enabled TINYINT(1) NOT NULL DEFAULT 0,
            last_run_at DATETIME NULL,
            last_mailing_id INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_auto_mailing_club_code (club_id, code),
            KEY idx_auto_mailing_enabled (is_enabled),
            KEY idx_auto_mailing_club (club_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    _add_column(cursor, "auto_mailing_settings", "days_inactive", "INT NOT NULL DEFAULT 14")
    _add_column(cursor, "auto_mailing_settings", "bonus_amount", "INT NOT NULL DEFAULT 200")
    _add_column(cursor, "auto_mailing_settings", "repeat_after_days", "INT NOT NULL DEFAULT 30")
    _add_column(cursor, "auto_mailing_settings", "last_run_at", "DATETIME NULL")
    _add_column(cursor, "auto_mailing_settings", "last_mailing_id", "INT NULL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS auto_mailing_logs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            auto_mailing_code VARCHAR(80) NOT NULL,
            guest_id INT NOT NULL,
            mailing_id INT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'created',
            message TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_auto_mailing_logs_club_code (club_id, auto_mailing_code, created_at),
            KEY idx_auto_mailing_logs_guest (club_id, guest_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS first_visit_surveys (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            telegram_id BIGINT NOT NULL,
            auto_mailing_setting_id INT NULL,
            session_id BIGINT NULL,
            session_ended_at DATETIME NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'invited',
            rating INT NULL,
            feedback_text TEXT NULL,
            bonus_amount INT NOT NULL DEFAULT 100,
            bonus_awarded TINYINT(1) NOT NULL DEFAULT 0,
            invite_message_id BIGINT NULL,
            invite_sent_at DATETIME NULL,
            started_at DATETIME NULL,
            completed_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_first_visit_survey_guest (club_id, guest_id),
            KEY idx_first_visit_survey_status (status),
            KEY idx_first_visit_survey_telegram (telegram_id),
            KEY idx_first_visit_survey_session (session_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    _add_column(cursor, "first_visit_surveys", "auto_mailing_setting_id", "INT NULL")
    _add_column(cursor, "first_visit_surveys", "invite_message_id", "BIGINT NULL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bonus_giveaways (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            filters_json JSON NULL,
            bonus_amount INT NOT NULL,
            message_text TEXT NOT NULL,
            mailing_id INT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'created',
            recipients_count INT NOT NULL DEFAULT 0,
            awarded_count INT NOT NULL DEFAULT 0,
            skipped_count INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME NULL,
            KEY idx_bonus_giveaways_club_created (club_id, created_at),
            KEY idx_bonus_giveaways_mailing (mailing_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bonus_giveaway_recipients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            giveaway_id INT NOT NULL,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            telegram_id BIGINT NULL,
            bonus_amount INT NOT NULL,
            transaction_status VARCHAR(40) NOT NULL DEFAULT 'pending',
            transaction_id INT NULL,
            mailing_recipient_id INT NULL,
            error_text TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            awarded_at DATETIME NULL,
            UNIQUE KEY uq_bonus_giveaway_guest (giveaway_id, club_id, guest_id),
            KEY idx_bonus_giveaway_recipients_guest (club_id, guest_id),
            KEY idx_bonus_giveaway_recipients_status (transaction_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    if _index_columns(cursor, "bonus_giveaway_recipients", "uq_bonus_giveaway_guest") == "giveaway_id,guest_id":
        cursor.execute(
            """
            ALTER TABLE bonus_giveaway_recipients
            DROP INDEX uq_bonus_giveaway_guest,
            ADD UNIQUE KEY uq_bonus_giveaway_guest (giveaway_id, club_id, guest_id)
            """
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_sync_logs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            script_name VARCHAR(80) NOT NULL,
            sync_mode VARCHAR(30) NOT NULL,
            status VARCHAR(30) NOT NULL,
            message TEXT NULL,
            started_at DATETIME NOT NULL,
            finished_at DATETIME NULL,
            created_by INT NULL,
            INDEX idx_admin_sync_logs_club (club_id),
            INDEX idx_admin_sync_logs_started (started_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_impersonation_logs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            admin_user_id INT NOT NULL,
            admin_login VARCHAR(120) NULL,
            club_id INT NOT NULL,
            club_name VARCHAR(255) NULL,
            started_at DATETIME NOT NULL,
            ended_at DATETIME NULL,
            ip VARCHAR(80) NULL,
            user_agent TEXT NULL,
            INDEX idx_admin_impersonation_admin (admin_user_id),
            INDEX idx_admin_impersonation_club (club_id),
            INDEX idx_admin_impersonation_started (started_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NULL,
            actor_user_id INT NULL,
            actor_role VARCHAR(40) NULL,
            action VARCHAR(120) NOT NULL,
            entity_type VARCHAR(80) NULL,
            entity_id VARCHAR(120) NULL,
            details_json JSON NULL,
            ip VARCHAR(80) NULL,
            user_agent TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_audit_logs_club_created (club_id, created_at),
            KEY idx_audit_logs_actor_created (actor_user_id, created_at),
            KEY idx_audit_logs_action_created (action, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
