#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.notifications.coach_messages import send_morning_brief
    from scripts.system.automation_health import write_automation_health
    from scripts.system.capability_engine import record_capabilities
    from scripts.system.context_engine import write_all_contexts, write_context
    from scripts.system.policy_gate import PolicyGateError
    from scripts.system.service_sync import service_sync
    from scripts.system.today_feed import write_today_feed
    from scripts.system.weekly_planning_pipeline import activate_prepared_week, plan_next_week, plan_range, replan_range, replan_workout
    from scripts.system.athlete_state import write_athlete_state
    from scripts.system.workout_family_response import write_workout_family_response
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.notifications.coach_messages import send_morning_brief
    from scripts.system.automation_health import write_automation_health
    from scripts.system.capability_engine import record_capabilities
    from scripts.system.context_engine import write_all_contexts, write_context
    from scripts.system.policy_gate import PolicyGateError
    from scripts.system.service_sync import service_sync
    from scripts.system.today_feed import write_today_feed
    from scripts.system.weekly_planning_pipeline import activate_prepared_week, plan_next_week, plan_range, replan_range, replan_workout
    from scripts.system.athlete_state import write_athlete_state
    from scripts.system.workout_family_response import write_workout_family_response


ROOT = Path(__file__).resolve().parents[2]
GARMIN_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
POST_WORKOUT_REFRESH_SCRIPT = ROOT / "scripts" / "garmin" / "post_workout_refresh.py"
COACH_ENGINE_SCRIPT = ROOT / "scripts" / "garmin" / "coach_engine.py"
GARMIN_RECONCILE_STATE_PATH = ROOT / "system" / "state" / "garmin_reconcile_state.json"


@dataclass
class ActionSpec:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]
    payload_schema: dict[str, str]


class ActionRuntimeError(RuntimeError):
    pass


POST_SUCCESS_CAPABILITIES: dict[str, list[str]] = {
    "refresh_athlete_state": ["athlete_state", "progression_state", "training_paces"],
    "process_completed_activity": ["post_workout_refresh", "athlete_state", "progression_state", "training_paces", "coach_decision"],
    "rebuild_coach_state": ["coach_decision"],
    "sync_planned_workouts": [],
    "refresh_today_feed": [],
    "service_sync": ["coach_decision", "athlete_state", "post_workout_refresh"],
    "plan_range": ["coach_decision", "athlete_state", "post_workout_refresh"],
    "replan_range": ["coach_decision", "athlete_state", "post_workout_refresh"],
    "replan_workout": ["coach_decision", "athlete_state", "post_workout_refresh"],
}


REFRESH_ARTIFACT_ACTIONS = {
    "refresh_athlete_state",
    "process_completed_activity",
    "rebuild_coach_state",
    "prepare_next_week",
    "plan_range",
    "replan_range",
    "replan_workout",
    "activate_prepared_week",
    "sync_workout_to_garmin",
    "sync_planned_workouts",
    "refresh_contexts",
    "refresh_automation_health",
    "refresh_today_feed",
    "refresh_workout_family_response",
    "send_morning_brief",
    "service_sync",
}


def run_command(command: list[str], *, timeout: int = 3600) -> tuple[bool, str, dict[str, Any] | None]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    parsed = None
    if stdout:
        try:
            payload = json.loads(stdout)
            if isinstance(payload, dict):
                parsed = payload
        except json.JSONDecodeError:
            parsed = None
    ok = result.returncode == 0
    message = stdout or stderr or f"Command failed with exit code {result.returncode}"
    return ok, message, parsed


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


def action_refresh_athlete_state(**_: Any) -> dict[str, Any]:
    payload = write_athlete_state()
    return {"ok": True, "message": "Athlete state refreshed.", "payload": payload}


def action_refresh_contexts(*, refresh_capabilities: bool = False, context: str = "all", **_: Any) -> dict[str, Any]:
    if context == "all":
        payload = write_all_contexts(refresh_capabilities=bool(refresh_capabilities))
    else:
        payload = write_context(context, refresh_capabilities=bool(refresh_capabilities))
    return {"ok": True, "message": "Operational contexts refreshed.", "payload": payload}


def action_refresh_automation_health(**_: Any) -> dict[str, Any]:
    payload = write_automation_health()
    return {"ok": True, "message": "Automation health refreshed.", "payload": payload}


def action_refresh_today_feed(**_: Any) -> dict[str, Any]:
    payload = write_today_feed()
    return {"ok": True, "message": "Today feed refreshed.", "payload": payload}


def action_refresh_workout_family_response(**_: Any) -> dict[str, Any]:
    payload = write_workout_family_response()
    return {"ok": True, "message": "Workout family response refreshed.", "payload": payload}


def action_prepare_next_week(*, source: str = "manual", force: bool = False, **_: Any) -> dict[str, Any]:
    payload = plan_next_week(force=bool(force), source=source)
    return {"ok": bool(payload.get("ok")), "message": str(payload.get("message") or "Prepare next week finished."), "payload": payload}


def action_activate_prepared_week(*, source: str = "manual", week_start: str = "", confirmed: bool = False, **_: Any) -> dict[str, Any]:
    # `confirmed` is reserved for future explicit confirmation flows.
    _ = confirmed
    payload = activate_prepared_week(source=source, week_start=week_start)
    return {"ok": bool(payload.get("ok")), "message": str(payload.get("message") or "Activate prepared week finished."), "payload": payload}


def action_plan_range(*, start_date: str, end_date: str, premise: str = "", source: str = "manual", **_: Any) -> dict[str, Any]:
    if not start_date or not end_date:
        raise ActionRuntimeError("Missing required payload fields: start_date, end_date")
    payload = plan_range(start_date, end_date, premise, source)
    return {"ok": bool(payload.get("ok")), "message": str(payload.get("message") or "Plan range finished."), "payload": payload}


def action_replan_range(*, start_date: str, end_date: str, premise: str = "", source: str = "manual", **_: Any) -> dict[str, Any]:
    if not start_date or not end_date:
        raise ActionRuntimeError("Missing required payload fields: start_date, end_date")
    payload = replan_range(start_date, end_date, premise, source)
    return {"ok": bool(payload.get("ok")), "message": str(payload.get("message") or "Replan range finished."), "payload": payload}


def action_replan_workout(*, slug: str, premise: str = "", source: str = "manual", **_: Any) -> dict[str, Any]:
    if not slug:
        raise ActionRuntimeError("Missing required payload field: slug")
    payload = replan_workout(slug, premise, source)
    return {"ok": bool(payload.get("ok")), "message": str(payload.get("message") or "Replan workout finished."), "payload": payload}


def action_sync_workout_to_garmin(*, workout_file: str, **_: Any) -> dict[str, Any]:
    if not workout_file:
        raise ActionRuntimeError("Missing required payload field: workout_file")
    target = Path(workout_file)
    if not target.is_absolute():
        target = ROOT / workout_file
    if not target.exists():
        raise ActionRuntimeError(f"Workout file not found: {workout_file}")
    ok, message, parsed = run_command([sys.executable, str(GARMIN_SYNC_SCRIPT), "schedule-workout-file", str(target)], timeout=600)
    return {"ok": ok, "message": message, "payload": parsed or {"raw_output": message}}


def action_sync_planned_workouts(**_: Any) -> dict[str, Any]:
    ok, message, parsed = run_command([sys.executable, str(GARMIN_SYNC_SCRIPT), "sync-planned-workouts"], timeout=1800)
    payload = parsed or {"raw_output": message}
    if isinstance(payload, dict) and int(payload.get("failed") or 0) > 0:
        ok = False
        message = f"Garmin sync finished with {int(payload.get('failed') or 0)} failed planned workout(s)."
    write_json(
        GARMIN_RECONCILE_STATE_PATH,
        {
            "generated_at": str(__import__("datetime").datetime.utcnow().isoformat()) + "Z",
            "ok": ok,
            "message": message,
            "result": payload,
        },
    )
    return {"ok": ok, "message": message, "payload": payload}


def action_process_completed_activity(
    *,
    activity_days: int = 3,
    daily_days: int = 14,
    limit: int = 20,
    skip_activity_import: bool = False,
    skip_daily: bool = False,
    skip_athlete_profile: bool = False,
    skip_trigger: bool = False,
    **_: Any,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(POST_WORKOUT_REFRESH_SCRIPT),
        "--activity-days",
        str(activity_days),
        "--daily-days",
        str(daily_days),
        "--limit",
        str(limit),
    ]
    if skip_activity_import:
        command.append("--skip-activity-import")
    if skip_daily:
        command.append("--skip-daily")
    if skip_athlete_profile:
        command.append("--skip-athlete-profile")
    if skip_trigger:
        command.append("--skip-trigger")
    ok, message, parsed = run_command(command, timeout=1200)
    return {"ok": ok, "message": message, "payload": parsed or {"raw_output": message}}


def action_rebuild_coach_state(*, as_of: str = "", days: int = 28, **_: Any) -> dict[str, Any]:
    command = [sys.executable, str(COACH_ENGINE_SCRIPT), "--as-of", as_of or str(__import__("datetime").date.today().isoformat()), "--days", str(days)]
    ok, message, parsed = run_command(command, timeout=1200)
    return {"ok": ok, "message": message, "payload": parsed or {"raw_output": message}}


def action_send_morning_brief(*, force: bool = False, **_: Any) -> dict[str, Any]:
    payload = send_morning_brief(force=bool(force))
    return {"ok": True, "message": str(payload.get("message") or "Morning brief processed."), "payload": payload}


def action_service_sync(*, as_of: str = "", skip_garmin: bool = False, **_: Any) -> dict[str, Any]:
    payload = service_sync(as_of or str(__import__("datetime").date.today().isoformat()), skip_garmin=bool(skip_garmin))
    return {"ok": bool(payload.get("ok")), "message": str(payload.get("summary") or "Service sync finished."), "payload": payload}


ACTIONS: dict[str, ActionSpec] = {
    "refresh_athlete_state": ActionSpec(
        name="refresh_athlete_state",
        description="Rebuild system/state/athlete_state.json",
        handler=action_refresh_athlete_state,
        payload_schema={},
    ),
    "refresh_contexts": ActionSpec(
        name="refresh_contexts",
        description="Build one or all operational contexts",
        handler=action_refresh_contexts,
        payload_schema={"context": "Context name or 'all'", "refresh_capabilities": "Boolean flag"},
    ),
    "refresh_automation_health": ActionSpec(
        name="refresh_automation_health",
        description="Rebuild automation health artifacts",
        handler=action_refresh_automation_health,
        payload_schema={},
    ),
    "refresh_today_feed": ActionSpec(
        name="refresh_today_feed",
        description="Rebuild the web-first today feed artifact",
        handler=action_refresh_today_feed,
        payload_schema={},
    ),
    "refresh_workout_family_response": ActionSpec(
        name="refresh_workout_family_response",
        description="Rebuild workout-family response memory from completed reviews",
        handler=action_refresh_workout_family_response,
        payload_schema={},
    ),
    "prepare_next_week": ActionSpec(
        name="prepare_next_week",
        description="Prepare next week through weekly_planning_pipeline",
        handler=action_prepare_next_week,
        payload_schema={"source": "Trigger source", "force": "Boolean flag"},
    ),
    "plan_range": ActionSpec(
        name="plan_range",
        description="Generate or regenerate planned workouts inside a date range",
        handler=action_plan_range,
        payload_schema={"start_date": "Range start YYYY-MM-DD", "end_date": "Range end YYYY-MM-DD", "premise": "Free-text planning premise", "source": "Trigger source"},
    ),
    "replan_range": ActionSpec(
        name="replan_range",
        description="Replan workouts inside a date range with Garmin verification",
        handler=action_replan_range,
        payload_schema={"start_date": "Range start YYYY-MM-DD", "end_date": "Range end YYYY-MM-DD", "premise": "Free-text replanning premise", "source": "Trigger source"},
    ),
    "replan_workout": ActionSpec(
        name="replan_workout",
        description="Replan one workout with Garmin verification",
        handler=action_replan_workout,
        payload_schema={"slug": "Workout YAML stem", "premise": "Free-text replanning premise", "source": "Trigger source"},
    ),
    "activate_prepared_week": ActionSpec(
        name="activate_prepared_week",
        description="Activate prepared week through weekly_planning_pipeline",
        handler=action_activate_prepared_week,
        payload_schema={"source": "Trigger source", "week_start": "Optional YYYY-MM-DD"},
    ),
    "sync_workout_to_garmin": ActionSpec(
        name="sync_workout_to_garmin",
        description="Upload and schedule one workout file in Garmin",
        handler=action_sync_workout_to_garmin,
        payload_schema={"workout_file": "Relative or absolute workout YAML path"},
    ),
    "sync_planned_workouts": ActionSpec(
        name="sync_planned_workouts",
        description="Reconcile all planned workouts against Garmin",
        handler=action_sync_planned_workouts,
        payload_schema={},
    ),
    "process_completed_activity": ActionSpec(
        name="process_completed_activity",
        description="Run the automatic post-workout refresh pipeline",
        handler=action_process_completed_activity,
        payload_schema={
            "activity_days": "Lookback for Garmin activities",
            "daily_days": "Lookback for daily metrics",
            "limit": "Maximum Garmin activities to inspect",
            "skip_activity_import": "Boolean flag",
            "skip_daily": "Boolean flag",
            "skip_athlete_profile": "Boolean flag",
            "skip_trigger": "Boolean flag",
        },
    ),
    "rebuild_coach_state": ActionSpec(
        name="rebuild_coach_state",
        description="Rebuild dashboard and coach decision from local data",
        handler=action_rebuild_coach_state,
        payload_schema={"as_of": "Reference date YYYY-MM-DD", "days": "Lookback window"},
    ),
    "send_morning_brief": ActionSpec(
        name="send_morning_brief",
        description="Send the Telegram morning coach briefing",
        handler=action_send_morning_brief,
        payload_schema={"force": "Boolean flag"},
    ),
    "service_sync": ActionSpec(
        name="service_sync",
        description="Full Garmin plus coach sync for service and Telegram",
        handler=action_service_sync,
        payload_schema={"as_of": "Reference date YYYY-MM-DD", "skip_garmin": "Boolean flag"},
    ),
}


def list_actions() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "payload_schema": spec.payload_schema,
        }
        for spec in ACTIONS.values()
    ]


def post_success_refresh(action_name: str) -> None:
    capability_names = POST_SUCCESS_CAPABILITIES.get(action_name) or []
    if capability_names:
        record_capabilities(capability_names, success=True)
    if action_name in REFRESH_ARTIFACT_ACTIONS:
        write_all_contexts(refresh_capabilities=False)
        write_automation_health()


def run_action(name: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = ACTIONS.get(name)
    if spec is None:
        raise ActionRuntimeError(f"Unknown action: {name}")
    try:
        result = spec.handler(**(payload or {}))
    except PolicyGateError as exc:
        return {"ok": False, "action": name, "message": str(exc), "error_type": "policy_gate"}
    except ActionRuntimeError as exc:
        return {"ok": False, "action": name, "message": str(exc), "error_type": "runtime"}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "action": name, "message": f"Action timed out: {exc}", "error_type": "timeout"}
    except Exception as exc:  # pragma: no cover - broad safety for runtime wrapper
        return {"ok": False, "action": name, "message": f"Unexpected action error: {exc}", "error_type": "unexpected"}
    if result.get("ok"):
        post_success_refresh(name)
    return {"action": name, **result}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Structured action runtime for automation and web-first flows")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List available actions")
    run_parser = subparsers.add_parser("run", help="Run one structured action")
    run_parser.add_argument("action", choices=sorted(ACTIONS.keys()), help="Action name")
    run_parser.add_argument("--payload-json", default="{}", help="JSON payload for the action")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "list":
        sys.stdout.write(json.dumps({"ok": True, "actions": list_actions()}, indent=2, ensure_ascii=True) + "\n")
        return
    try:
        payload = json.loads(str(args.payload_json or "{}"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON payload: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit("Payload JSON must be an object.")
    sys.stdout.write(json.dumps(run_action(args.action, payload=payload), indent=2, ensure_ascii=True, default=str) + "\n")


if __name__ == "__main__":
    main()
