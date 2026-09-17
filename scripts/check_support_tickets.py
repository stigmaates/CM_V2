from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import TECH_SUPPORT_CHAT_ID  # noqa: E402
from app.core import get_db_connection  # noqa: E402


def main() -> int:
    if not (TECH_SUPPORT_CHAT_ID or "").strip():
        print("ERROR: TECH_SUPPORT_CHAT_ID and TECH_ALERT_CHAT_ID are empty")
        return 1

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM support_tickets")
            tickets = int((cursor.fetchone() or {}).get("cnt") or 0)
            cursor.execute("SELECT COUNT(*) AS cnt FROM support_ticket_events")
            events = int((cursor.fetchone() or {}).get("cnt") or 0)
            cursor.execute(
                """
                SELECT club_id, name, cm_bonus_admin_chat_id
                FROM clubs
                WHERE NULLIF(TRIM(cm_bonus_admin_chat_id), '') IS NOT NULL
                ORDER BY club_id
                """
            )
            club_chats = cursor.fetchall()
    finally:
        conn.close()

    chat_counts = Counter(row["cm_bonus_admin_chat_id"] for row in club_chats)
    duplicate_chat_ids = {chat_id for chat_id, count in chat_counts.items() if count > 1}
    if duplicate_chat_ids:
        print("ERROR: duplicate club chat IDs: " + ", ".join(sorted(duplicate_chat_ids)))
        return 1

    print(f"Technical support chat: {TECH_SUPPORT_CHAT_ID}")
    print(f"Configured club chats: {len(club_chats)}")
    for row in club_chats:
        print(f"- club {row['club_id']} ({row.get('name') or '—'}): {row['cm_bonus_admin_chat_id']}")
    print(f"Stored tickets: {tickets}; status events: {events}")
    print("Support ticket configuration OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
