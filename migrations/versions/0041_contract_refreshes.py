"""Contract refresh balances and case rewards."""

revision = "0041_contract_refreshes"


def upgrade(cursor) -> None:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'club_case_items'
          AND COLUMN_NAME = 'contract_refresh_amount'
        """
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            ALTER TABLE club_case_items
            ADD COLUMN contract_refresh_amount INT NOT NULL DEFAULT 0
            AFTER token_amount
            """
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_contract_refresh_balances (
            club_id INT NOT NULL,
            guest_id INT NOT NULL,
            balance INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (club_id, guest_id),
            KEY idx_contract_refresh_guest (guest_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
