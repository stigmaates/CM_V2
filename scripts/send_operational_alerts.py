from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.tech_alerts import send_operational_alerts, send_test_alert


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send critical ClubModule operational alerts to Telegram.")
    parser.add_argument("--cooldown-minutes", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent without notifying Telegram")
    parser.add_argument("--test-message", action="store_true", help="Send one explicit Telegram test message")
    args = parser.parse_args(argv)

    if args.test_message:
        sent, error = send_test_alert()
        if sent:
            print("OK: test alert sent")
            return 0
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    result = send_operational_alerts(
        cooldown_minutes=args.cooldown_minutes,
        dry_run=args.dry_run,
    )
    for message in result["messages"]:
        print(message)
        print("")
    print(
        "SUMMARY: "
        f"critical={result['critical']} "
        f"sent={result['sent']} "
        f"skipped={result['skipped']} "
        f"errors={len(result['errors'])}"
    )
    for error in result["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
