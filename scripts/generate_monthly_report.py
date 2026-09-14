"""Generate one queued monthly report outside the web request."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.monthly_report_generation import generate_saved_monthly_report  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(0 if generate_saved_monthly_report(args.report_id) else 1)
