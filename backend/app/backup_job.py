from __future__ import annotations

import sys

from .backup_scheduler import _rolling_db_backup


def main() -> int:
    try:
        target = _rolling_db_backup()
        print(f"OK: {target}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
