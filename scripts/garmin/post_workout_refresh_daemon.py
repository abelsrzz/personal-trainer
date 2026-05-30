#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFRESH_SCRIPT = ROOT / "scripts" / "garmin" / "post_workout_refresh.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Garmin post-workout refresh in a polling loop")
    parser.add_argument("--interval-seconds", type=int, default=300, help="Polling interval between refresh runs")
    return parser.parse_args()


def utcnow_label() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    args = parse_args()
    interval = max(30, int(args.interval_seconds or 300))
    while True:
        started_at = utcnow_label()
        result = subprocess.run([sys.executable, str(REFRESH_SCRIPT)], cwd=ROOT, check=False, capture_output=True, text=True)
        print(f"[{started_at}] post_workout_refresh exit={result.returncode}")
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(interval)


if __name__ == "__main__":
    main()
