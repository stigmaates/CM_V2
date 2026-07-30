def table_has_column(cursor, table_name: str, column_name: str) -> bool:
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


def service_enabled_select_expr(cursor, table_alias: str | None = None) -> str:
    prefix = f"{table_alias}." if table_alias else ""
    if table_has_column(cursor, "clubs", "service_enabled"):
        return f"{prefix}service_enabled AS service_enabled"
    return "1 AS service_enabled"


def is_service_enabled(row: dict) -> bool:
    value = row.get("service_enabled", 1)
    if value is None:
        return True
    return bool(int(value))
