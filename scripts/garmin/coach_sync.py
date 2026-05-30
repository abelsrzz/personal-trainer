#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKOUTS_ROOT = ROOT / "training" / "planned" / "workouts"
SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
REVIEW_SCRIPT = ROOT / "scripts" / "garmin" / "review_planned_session.py"
ENGINE_SCRIPT = ROOT / "scripts" / "garmin" / "coach_engine.py"
ATHLETE_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "athlete_sync.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-command Garmin sync, workout review and coach dashboard generation")
    parser.add_argument("--date", default=date.today().isoformat(), help="Operational date, YYYY-MM-DD")
    parser.add_argument("--activity-days", type=int, default=14, help="Days back for Garmin activity import")
    parser.add_argument("--daily-days", type=int, default=14, help="Days back for Garmin daily metrics")
    parser.add_argument("--limit", type=int, default=40, help="Maximum Garmin activities to inspect")
    parser.add_argument("--dashboard-days", type=int, default=28, help="Lookback window for coach dashboard")
    parser.add_argument("--skip-garmin", action="store_true", help="Do not contact Garmin; use local imported files only")
    parser.add_argument("--skip-daily", action="store_true", help="Skip Garmin daily recovery metrics import")
    parser.add_argument("--skip-athlete-profile", action="store_true", help="Skip Garmin athlete profile and gear sync")
    parser.add_argument("--skip-review", action="store_true", help="Skip planned-session review")
    parser.add_argument("--force-review", action="store_true", help="Regenerate planned-session review if it exists")
    return parser.parse_args()


def run_step(label: str, command: list[str], required: bool = True) -> bool:
    print(f"== {label}", flush=True)
    print(" ".join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode == 0:
        return True
    message = f"Step failed: {label} (exit {result.returncode})"
    if required:
        raise SystemExit(message)
    print(message, flush=True)
    return False


def planned_workout_exists(day: str) -> bool:
    return bool(sorted(WORKOUTS_ROOT.glob(f"{day}_*.yaml")))


def main() -> None:
    args = parse_args()

    if not args.skip_garmin:
        run_step(
            "Import Garmin activities",
            [
                sys.executable,
                str(SYNC_SCRIPT),
                "import-activities",
                "--days",
                str(args.activity_days),
                "--limit",
                str(args.limit),
            ],
        )
        if not args.skip_daily:
            run_step(
                "Import Garmin daily metrics",
                [sys.executable, str(SYNC_SCRIPT), "import-daily", "--days", str(args.daily_days)],
                required=False,
            )
        if not args.skip_athlete_profile:
            if run_step(
                "Import Garmin athlete profile",
                [sys.executable, str(SYNC_SCRIPT), "import-athlete-profile"],
                required=False,
            ):
                run_step(
                    "Apply Garmin athlete profile to local athlete files",
                    [sys.executable, str(ATHLETE_SYNC_SCRIPT)],
                    required=False,
                )

    if not args.skip_review:
        if planned_workout_exists(args.date):
            command = [sys.executable, str(REVIEW_SCRIPT), "--date", args.date, "--days", str(args.activity_days), "--limit", str(args.limit)]
            if args.force_review:
                command.append("--force")
            run_step("Review planned session", command, required=False)
        else:
            print(f"== Review planned session\nNo planned workout found for {args.date}; skipping review.", flush=True)

    run_step(
        "Build coach dashboard",
        [sys.executable, str(ENGINE_SCRIPT), "--as-of", args.date, "--days", str(args.dashboard_days)],
    )

    print("== Outputs", flush=True)
    print("athlete/status_dashboard.md", flush=True)
    print("planning/coach_decision.md", flush=True)
    print("planning/coach_decision.json", flush=True)


if __name__ == "__main__":
    main()
