"""Discard one guest's latest unfinished pool without spending a refresh prize."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.game_contracts import (  # noqa: E402
    get_guest_contract_pool,
    reroll_guest_contracts,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discard the latest unfinished pool; the next guest request creates six different contracts"
    )
    parser.add_argument("--club-id", type=int, required=True)
    parser.add_argument("--guest-id", type=int, required=True)
    parser.add_argument("--game", choices=("cs2", "dota2"), required=True)
    args = parser.parse_args()
    result = reroll_guest_contracts(
        args.club_id,
        args.guest_id,
        args.game,
        consume_refresh=False,
    )
    pool = get_guest_contract_pool(args.club_id, args.guest_id, args.game) or {}
    contracts = pool.get("contracts") or []
    print("OK:", result)
    print("Сформированы шесть новых вариантов:")
    for contract in contracts:
        print(f"- {contract['difficulty']}: {contract['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
