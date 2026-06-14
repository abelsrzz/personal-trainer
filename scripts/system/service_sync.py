#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
COACH_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "coach_sync.py"
SYNC_GARMIN_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
ATHLETE_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "athlete_sync.py"


def write_athlete_state_runtime() -> dict[str, Any]:
    try:
        from scripts.system.athlete_state import write_athlete_state
    except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
        sys.path.append(str(Path(__file__).resolve().parents[2]))
        from scripts.system.athlete_state import write_athlete_state
    return write_athlete_state()


def write_today_feed_runtime() -> dict[str, Any]:
    try:
        from scripts.system.today_feed import write_today_feed
    except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
        sys.path.append(str(Path(__file__).resolve().parents[2]))
        from scripts.system.today_feed import write_today_feed
    return write_today_feed()


def write_automation_health_runtime() -> dict[str, Any]:
    try:
        from scripts.system.automation_health import write_automation_health
    except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
        sys.path.append(str(Path(__file__).resolve().parents[2]))
        from scripts.system.automation_health import write_automation_health
    return write_automation_health()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Operational Garmin + coach sync for service and Telegram")
    parser.add_argument("--date", default=date.today().isoformat(), help="Operational date YYYY-MM-DD")
    parser.add_argument("--skip-garmin", action="store_true", help="Use local data only")
    return parser.parse_args()


def run_step(label: str, command: list[str], *, required: bool = True) -> dict[str, Any]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    ok = result.returncode == 0
    return {
        "label": label,
        "command": " ".join(command),
        "ok": ok,
        "required": required,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
        "returncode": result.returncode,
    }


def build_summary(day: str, steps: list[dict[str, Any]]) -> str:
    ok_count = sum(1 for item in steps if item.get("ok"))
    failed = [item for item in steps if not item.get("ok") and item.get("required")]
    optional_failed = [item for item in steps if not item.get("ok") and not item.get("required")]
    lines = [f"Sync operativo {day}", f"Pasos correctos: {ok_count}/{len(steps)}"]
    if failed:
        lines.append("Fallo bloqueante: " + ", ".join(str(item.get("label")) for item in failed))
    elif optional_failed:
        lines.append("Con avisos: " + ", ".join(str(item.get("label")) for item in optional_failed))
    else:
        lines.append("Sin incidencias relevantes.")
    return "\n".join(lines)


def service_sync(day: str, *, skip_garmin: bool = False) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    if not skip_garmin:
        steps.append(run_step("Import Garmin activities", [sys.executable, str(SYNC_GARMIN_SCRIPT), "import-activities", "--days", "14", "--limit", "40"]))
        steps.append(run_step("Import Garmin daily metrics", [sys.executable, str(SYNC_GARMIN_SCRIPT), "import-daily", "--days", "14"], required=False))
        profile_step = run_step("Import Garmin athlete profile", [sys.executable, str(SYNC_GARMIN_SCRIPT), "import-athlete-profile"], required=False)
        steps.append(profile_step)
        if profile_step.get("ok"):
            steps.append(run_step("Apply Garmin athlete profile", [sys.executable, str(ATHLETE_SYNC_SCRIPT)], required=False))
    coach_command = [sys.executable, str(COACH_SYNC_SCRIPT), "--date", day]
    if skip_garmin:
        coach_command.append("--skip-garmin")
    steps.append(run_step("Coach sync", coach_command))
    if not skip_garmin:
        steps.append(run_step("Sync planned workouts", [sys.executable, str(SYNC_GARMIN_SCRIPT), "sync-planned-workouts"], required=False))
    athlete_state = write_athlete_state_runtime()
    today_feed = write_today_feed_runtime()
    health = write_automation_health_runtime()
    ok = all(item.get("ok") or not item.get("required") for item in steps)
    return {
        "ok": ok,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": day,
        "skip_garmin": skip_garmin,
        "summary": build_summary(day, steps),
        "steps": steps,
        "artifacts": {
            "athlete_state_generated_at": athlete_state.get("generated_at"),
            "today_feed_generated_at": today_feed.get("generated_at"),
            "automation_health_generated_at": health.get("generated_at"),
        },
    }


def main() -> None:
    args = parse_args()
    payload = service_sync(args.date, skip_garmin=bool(args.skip_garmin))
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
