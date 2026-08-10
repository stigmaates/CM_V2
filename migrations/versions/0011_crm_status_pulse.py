"""Add CRM status change history for base pulse."""

revision = "0011_crm_status_pulse"


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


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table_name, index_name),
    )
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0) > 0


def _add_index(cursor, table_name: str, index_name: str, columns_sql: str) -> None:
    if not _table_exists(cursor, table_name) or _index_exists(cursor, table_name, index_name):
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD INDEX {index_name} ({columns_sql})")


def upgrade(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_status_changes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            old_crm_type VARCHAR(40) NULL,
            new_crm_type VARCHAR(40) NOT NULL,
            changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_crm_status_changes_club_changed (club_id, changed_at),
            KEY idx_crm_status_changes_guest (club_id, guest_id, changed_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    _add_index(cursor, "auto_mailing_logs", "idx_auto_mailing_logs_guest_created", "club_id, guest_id, created_at")
