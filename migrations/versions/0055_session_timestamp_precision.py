"""Do not collapse valid sub-second Gizmo sessions to zero duration in MySQL."""

import re

revision = "0055_session_timestamp_precision"


def upgrade(cursor):
    changes = []
    parameters = []
    # Validate both definitions before issuing DDL (MySQL ALTER auto-commits).
    for name in ("date_start", "date_stop"):
        cursor.execute(
            """SELECT COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable,
                      COLUMN_DEFAULT AS column_default, EXTRA AS extra, COLUMN_COMMENT AS comment
               FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
               AND TABLE_NAME='guest_sessions' AND COLUMN_NAME=%s""",
            (name,),
        )
        column = cursor.fetchone()
        if not column or not re.fullmatch(r"datetime(?:\([0-6]\))?", column["column_type"].lower()):
            raise RuntimeError(f"Unexpected guest_sessions.{name} type; inspect schema before precision migration")
        if column["column_type"].lower() == "datetime(6)":
            continue
        definition = f"MODIFY COLUMN {name} DATETIME(6)"
        definition += " NULL" if column["is_nullable"] == "YES" else " NOT NULL"
        default = column["column_default"]
        if isinstance(default, str) and re.fullmatch(r"current_timestamp(?:\([0-6]?\))?", default.lower()):
            definition += " DEFAULT CURRENT_TIMESTAMP(6)"
        elif default is not None:
            definition += " DEFAULT %s"
            parameters.append(default)
        elif column["is_nullable"] == "YES":
            definition += " DEFAULT NULL"
        extra = (column["extra"] or "").lower().replace("default_generated", "").strip()
        if extra:
            if not re.fullmatch(r"on update current_timestamp(?:\([0-6]?\))?", extra):
                raise RuntimeError(f"Unexpected guest_sessions.{name} attributes; inspect before migration")
            definition += " ON UPDATE CURRENT_TIMESTAMP(6)"
        definition += " COMMENT %s"
        parameters.append(column["comment"] or "")
        changes.append(definition)
    if changes:
        cursor.execute("ALTER TABLE guest_sessions " + ", ".join(changes), tuple(parameters))
