"""Shared logins have real PC time/money, but no identifiable CRM person."""

import re

revision = "0054_unattributed_source_events"


def upgrade(cursor):
    for table in ("guest_sessions", "guest_balance_topups"):
        cursor.execute(
            """SELECT COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable
            FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
            AND TABLE_NAME=%s AND COLUMN_NAME='guest_id'""",
            (table,),
        )
        column = cursor.fetchone()
        if not column or not re.fullmatch(
            r"(?:tinyint|smallint|mediumint|int|bigint)(?:\(\d+\))?(?: unsigned)?", column["column_type"]
        ):
            raise RuntimeError(f"Unexpected {table}.guest_id schema; migration requires inspection")
        if column["is_nullable"] != "YES":
            cursor.execute(f"ALTER TABLE {table} MODIFY COLUMN guest_id {column['column_type']} NULL")
        cursor.execute(
            """SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='source_guest_id'""",
            (table,),
        )
        if not (cursor.fetchone() or {}).get("cnt"):
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN source_guest_id BIGINT NULL")
