"""Generate several days of local previews in one go.

    python scripts/preview_week.py --days 7
    python scripts/preview_week.py --days 7 --online

Each day is a normal preview run, so nothing is queued. Offline is the default
because it needs no API key and gives repeatable output; pass ``--online`` to
use RSS research and Gemini.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_brand  # noqa: E402
from src.main import main as run_main  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate N daily previews locally")
    parser.add_argument("--days", type=int, default=7, help="number of days (default: 7)")
    parser.add_argument("--start", help="first day, YYYY-MM-DD (default: today in Dhaka)")
    parser.add_argument("--out", default="out", help="output directory (default: out)")
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    parser.add_argument(
        "--online",
        action="store_true",
        help="use RSS research and Gemini instead of the offline topic/templates",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 31:
        parser.error("--days must be between 1 and 31")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    brand = load_brand(ROOT / args.config / "brand.json")

    if args.start:
        try:
            start = date.fromisoformat(args.start)
        except ValueError:
            print("--start must be YYYY-MM-DD", file=sys.stderr)
            return 2
    else:
        start = datetime.now(timezone.utc).astimezone(brand.tz).date()

    rows: list[tuple[str, int, Path]] = []
    for offset in range(args.days):
        day = start + timedelta(days=offset)
        command = [
            "--mode",
            "preview",
            "--date",
            day.isoformat(),
            "--out",
            args.out,
            "--config",
            args.config,
        ]
        if not args.online:
            command.append("--offline")

        code = run_main(command, env_file=ROOT / ".env")
        rows.append((day.isoformat(), code, ROOT / args.out / day.isoformat()))

    print()
    print(f"Preview summary ({args.days} day(s), {'online' if args.online else 'offline'}):")
    for day, code, directory in rows:
        label = "ok" if code == 0 else f"exit {code}"
        print(f"  {day}  {label:8} {directory / 'image.png'}")

    failed = sum(1 for _, code, _ in rows if code != 0)
    if failed:
        print(f"\n{failed} day(s) did not produce a preview. Read the report.md files.")
        return 1
    print("\nNothing was queued. Review the images and captions before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
