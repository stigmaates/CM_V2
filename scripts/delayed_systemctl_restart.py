from __future__ import annotations

import subprocess
import sys
import time


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) < 2:
        return 2

    try:
        delay_seconds = max(0.0, float(argv[0]))
    except ValueError:
        return 2

    command = argv[1:]
    time.sleep(delay_seconds)
    completed = subprocess.run(command, check=False)
    return int(completed.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
