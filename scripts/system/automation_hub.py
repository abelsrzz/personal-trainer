#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.system.action_runtime import run_action
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.action_runtime import run_action


ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "system" / "state" / "automation_jobs.json"


@dataclass(frozen=True)
class JobSpec:
    name: str
    description: str
    action: str
    payload: dict[str, Any]
    interval_minutes: int


JOBS: dict[str, JobSpec] = {
    "refresh_automation_health": JobSpec(
        name="refresh_automation_health",
        description="Keep automation health artifacts fresh.",
        action="refresh_automation_health",
        payload={},
        interval_minutes=15,
    ),
    "refresh_athlete_state": JobSpec(
        name="refresh_athlete_state",
        description="Rebuild consolidated athlete state.",
        action="refresh_athlete_state",
        payload={},
        interval_minutes=30,
    ),
    "refresh_today_context": JobSpec(
        name="refresh_today_context",
        description="Refresh the web-first today context.",
        action="refresh_contexts",
        payload={"context": "today_context", "refresh_capabilities": False},
        interval_minutes=15,
    ),
    "refresh_today_feed": JobSpec(
        name="refresh_today_feed",
        description="Refresh the persisted today feed for the home experience.",
        action="refresh_today_feed",
        payload={},
        interval_minutes=15,
    ),
    "refresh_workout_family_response": JobSpec(
        name="refresh_workout_family_response",
        description="Refresh workout-family response memory from completed reviews.",
        action="refresh_workout_family_response",
        payload={},
        interval_minutes=60,
    ),
    "rebuild_coach_state": JobSpec(
        name="rebuild_coach_state",
        description="Refresh dashboard and coach decision from local data.",
        action="rebuild_coach_state",
        payload={"days": 28},
        interval_minutes=60,
    ),
    "sync_planned_workouts": JobSpec(
        name="sync_planned_workouts",
        description="Reconcile planned future workouts with Garmin.",
        action="sync_planned_workouts",
        payload={},
        interval_minutes=30,
    ),
    "prepare_next_week": JobSpec(
        name="prepare_next_week",
        description="Prepare the next weekly plan through the structured runtime.",
        action="prepare_next_week",
        payload={"source": "timer", "force": False},
        interval_minutes=720,
    ),
    "process_completed_activity": JobSpec(
        name="process_completed_activity",
        description="Run the automatic post-workout pipeline.",
        action="process_completed_activity",
        payload={"activity_days": 3, "daily_days": 14, "limit": 20},
        interval_minutes=10,
    ),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"generated_at": None, "jobs": {}}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"generated_at": None, "jobs": {}}
    return payload if isinstance(payload, dict) else {"generated_at": None, "jobs": {}}


def save_state(payload: dict[str, Any]) -> None:
    payload["generated_at"] = utcnow_iso()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


def job_state(state: dict[str, Any], name: str) -> dict[str, Any]:
    jobs = state.setdefault("jobs", {})
    job_payload = jobs.setdefault(name, {})
    return job_payload if isinstance(job_payload, dict) else {}


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def job_due(spec: JobSpec, state: dict[str, Any]) -> bool:
    current = job_state(state, spec.name)
    last_success = parse_dt(current.get("last_success_at"))
    if last_success is None:
        return True
    return utcnow() - last_success >= timedelta(minutes=spec.interval_minutes)


def build_status(state: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for spec in JOBS.values():
        current = job_state(state, spec.name)
        items.append(
            {
                "name": spec.name,
                "description": spec.description,
                "action": spec.action,
                "interval_minutes": spec.interval_minutes,
                "due": job_due(spec, state),
                "last_started_at": current.get("last_started_at"),
                "last_finished_at": current.get("last_finished_at"),
                "last_success_at": current.get("last_success_at"),
                "last_ok": current.get("last_ok"),
                "last_message": current.get("last_message"),
            }
        )
    return {"generated_at": utcnow_iso(), "jobs": items}


def run_job(name: str, *, force: bool = False) -> dict[str, Any]:
    spec = JOBS.get(name)
    if spec is None:
        return {"ok": False, "message": f"Unknown automation job: {name}"}
    state = load_state()
    current = job_state(state, name)
    if not force and not job_due(spec, state):
        payload = {"ok": True, "message": "Job not due yet.", "job": name, "skipped": True, "last_success_at": current.get("last_success_at")}
        save_state(state)
        return payload

    current["last_started_at"] = utcnow_iso()
    current["running"] = True
    save_state(state)

    result = run_action(spec.action, payload=dict(spec.payload))

    current["running"] = False
    current["last_finished_at"] = utcnow_iso()
    current["last_ok"] = bool(result.get("ok"))
    current["last_message"] = str(result.get("message") or "")
    current["last_result"] = result
    if result.get("ok"):
        current["last_success_at"] = current["last_finished_at"]
    save_state(state)
    return {"job": name, **result}


def run_due_jobs() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for spec in JOBS.values():
        if job_due(spec, load_state()):
            results.append(run_job(spec.name))
    return {"ok": True, "results": results, "status": build_status(load_state())}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automation hub for scheduled product jobs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show automation job status")
    run_parser = subparsers.add_parser("run", help="Run one automation job")
    run_parser.add_argument("job", choices=sorted(JOBS.keys()), help="Job name")
    run_parser.add_argument("--force", action="store_true", help="Run even if the job is not due yet")
    subparsers.add_parser("run-due", help="Run all jobs currently due")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "status":
        payload = {"ok": True, **build_status(load_state())}
    elif args.command == "run":
        payload = run_job(args.job, force=bool(args.force))
    else:
        payload = run_due_jobs()
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
