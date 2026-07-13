from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.operational_alerts import get_operational_alerts, summarize_alerts


def _format_alert(alert: dict) -> str:
    parts = [alert["severity"].upper(), alert["code"]]
    if alert.get("club_id") is not None:
        parts.append(f"club={alert['club_id']}")
    if alert.get("age_minutes") is not None:
        parts.append(f"age={alert['age_minutes']}m")
    return f"{' '.join(parts)}: {alert['message']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Cyber Bonus operational alerts.")
    parser.add_argument("--problem-job-limit", type=int, default=20)
    parser.add_argument("--stuck-mailing-minutes", type=int, default=60)
    args = parser.parse_args(argv)

    alerts = get_operational_alerts(
        problem_job_limit=args.problem_job_limit,
        stuck_mailing_minutes=args.stuck_mailing_minutes,
    )
    summary = summarize_alerts(alerts)

    if not alerts:
        print("OK: no operational alerts")
        return 0

    for alert in alerts:
        print(_format_alert(alert))

    print(
        "SUMMARY: "
        f"errors={summary['error']} "
        f"warnings={summary['warning']} "
        f"total={summary['total']}"
    )
    return 2 if summary["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
