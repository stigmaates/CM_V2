"""Allow a club to create any number of missions from one template."""

revision = "0033_reusable_mission_templates"


def _index_definitions(cursor) -> dict[str, dict]:
    cursor.execute(
        """
        SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'club_missions'
        ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """
    )
    indexes: dict[str, dict] = {}
    for row in cursor.fetchall():
        name = str(row["INDEX_NAME"])
        item = indexes.setdefault(
            name,
            {"non_unique": int(row["NON_UNIQUE"]), "columns": []},
        )
        item["columns"].append(str(row["COLUMN_NAME"]))
    return indexes


def _quote_identifier(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def upgrade(cursor) -> None:
    indexes = _index_definitions(cursor)
    reusable_template_indexes = [
        name
        for name, definition in indexes.items()
        if name != "PRIMARY"
        and definition["non_unique"] == 0
        and {"club_id", "mission_template_id"}.issubset(definition["columns"])
    ]

    # The old unique index may also be the index MySQL chose for the club_id
    # foreign key. Create an ordinary replacement before removing it.
    has_club_lookup_index = any(
        definition["non_unique"] == 1 and definition["columns"][:1] == ["club_id"]
        for definition in indexes.values()
    )
    if reusable_template_indexes and not has_club_lookup_index:
        lookup_index_name = "idx_club_missions_club"
        if lookup_index_name in indexes:
            lookup_index_name = "idx_club_missions_club_lookup"
        cursor.execute(
            "ALTER TABLE club_missions ADD INDEX "
            f"{_quote_identifier(lookup_index_name)} (club_id)"
        )

    for index_name in reusable_template_indexes:
        cursor.execute(
            f"ALTER TABLE club_missions DROP INDEX {_quote_identifier(index_name)}"
        )
