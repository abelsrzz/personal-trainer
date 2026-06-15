#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.notifications.coach_messages import send_post_workout_message
    from scripts.notifications.sync_alerts import looks_like_auth_error, notify_sync_gap, notify_token_problem
    from scripts.system.athlete_state import write_athlete_state
    from scripts.system.workout_family_response import write_workout_family_response
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.notifications.coach_messages import send_post_workout_message
    from scripts.notifications.sync_alerts import looks_like_auth_error, notify_sync_gap, notify_token_problem
    from scripts.system.athlete_state import write_athlete_state
    from scripts.system.workout_family_response import write_workout_family_response


ROOT = Path(__file__).resolve().parents[2]
IMPORT_ROOT = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
FEEDBACK_ROOT = ROOT / "training" / "completed" / "feedback"
SHIN_TRACKER_PATH = ROOT / "athlete" / "shin_tracker.yaml"
STATE_PATH = ROOT / "system" / "state" / "post_workout_refresh_state.json"
SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
REVIEW_SCRIPT = ROOT / "scripts" / "garmin" / "review_planned_session.py"
ENGINE_SCRIPT = ROOT / "scripts" / "garmin" / "coach_engine.py"
ATHLETE_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "athlete_sync.py"
REVIEWABLE_ACTIVITY_TYPES = {
    "running",
    "trail_running",
    "cycling",
    "road_biking",
    "indoor_cycling",
    "swimming",
    "strength_training",
    "elliptical",
    "fitness_equipment",
    "mobility",
    "stretching",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect new Garmin activities and trigger post-workout refresh automatically")
    parser.add_argument("--activity-days", type=int, default=3, help="Days back to import Garmin activities while polling")
    parser.add_argument("--daily-days", type=int, default=14, help="Days back for Garmin daily metrics when new activity appears")
    parser.add_argument("--limit", type=int, default=20, help="Maximum Garmin activities to inspect per poll")
    parser.add_argument("--dashboard-days", type=int, default=28, help="Lookback window for coach dashboard rebuild")
    parser.add_argument("--skip-activity-import", action="store_true", help="Reuse existing imported Garmin activities instead of importing them again")
    parser.add_argument("--skip-daily", action="store_true", help="Skip Garmin daily metrics refresh when new activity is found")
    parser.add_argument("--skip-athlete-profile", action="store_true", help="Skip Garmin athlete profile refresh when new activity is found")
    parser.add_argument("--skip-trigger", action="store_true", help="Only detect new activities and update state without launching the pipeline")
    return parser.parse_args()


SYNC_GAP_ALERT_HOURS = float(os.getenv("GARMIN_SYNC_GAP_ALERT_HOURS", "18"))


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def load_state() -> dict[str, Any]:
    payload = load_json(
        STATE_PATH,
        {
            "last_seen_activity_id": None,
            "last_seen_activity_date": None,
            "last_processed_activity_id": None,
            "last_processed_activity_date": None,
            "last_processed_at": None,
            "last_successful_run": None,
            "last_error": None,
            "last_activity_import_at": None,
            "last_daily_import_at": None,
            "last_profile_sync_at": None,
            "next_action": "import_recent_activities",
            "timer_interval_minutes": 5,
            "processed_activities": [],
            "processed_feedback_updates": [],
            "runs": [],
        },
    )
    return payload if isinstance(payload, dict) else {}


def activity_summaries() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(IMPORT_ROOT.glob("*/summary.json")):
        try:
            payload = load_json(path, {})
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        activity_id = payload.get("activityId")
        start_local = str(payload.get("startTimeLocal") or "")
        date_text = start_local.split(" ")[0] if start_local else ""
        activity_type = str(payload.get("activityType", {}).get("typeKey") or "").strip().lower()
        if not activity_id or not date_text or activity_type not in REVIEWABLE_ACTIVITY_TYPES:
            continue
        items.append(
            {
                "activity_id": int(activity_id),
                "activity_date": date_text,
                "activity_name": payload.get("activityName") or path.parent.name,
                "activity_type": activity_type,
                "source_path": str(path.relative_to(ROOT)),
            }
        )
    items.sort(key=lambda item: item["activity_id"])
    return items


def run_step(command: list[str]) -> tuple[bool, str | None]:
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode == 0:
        return True, None
    stderr = (result.stderr or result.stdout or "").strip()
    return False, stderr or f"Command failed with exit code {result.returncode}"


def run_json_step(command: list[str]) -> tuple[bool, dict[str, Any] | None, str | None]:
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        return False, None, stderr or stdout or f"Command failed with exit code {result.returncode}"
    if not stdout:
        return True, {}, None
    try:
        return True, json.loads(stdout), None
    except json.JSONDecodeError:
        return True, {"raw_output": stdout}, None


def review_error_is_non_blocking(error: str | None) -> bool:
    text = str(error or "")
    return any(
        marker in text
        for marker in (
            "No planned workout found",
            "Multiple planned workouts found",
            "No local Garmin matching activities found",
            "available for review",
        )
    )


def remember_processed(state: dict[str, Any], activity: dict[str, Any], result: str, review_slug: str | None = None) -> None:
    processed = state.setdefault("processed_activities", [])
    if not isinstance(processed, list):
        processed = []
        state["processed_activities"] = processed
    processed.append(
        {
            "activity_id": activity["activity_id"],
            "activity_date": activity["activity_date"],
            "activity_name": activity.get("activity_name"),
            "review_slug": review_slug,
            "result": result,
            "processed_at": utcnow_iso(),
        }
    )
    if len(processed) > 100:
        del processed[:-100]


def feedback_updates() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(FEEDBACK_ROOT.glob("*.feedback.json")):
        try:
            payload = load_json(path, {})
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        updated_at = str(payload.get("updated_at") or "")
        feedback_date = str(payload.get("date") or "")
        slug = path.stem.replace(".feedback", "")
        athlete_feedback = payload.get("athlete_feedback") if isinstance(payload.get("athlete_feedback"), dict) else {}
        if not updated_at or not feedback_date:
            continue
        items.append({"slug": slug, "date": feedback_date, "updated_at": updated_at, "athlete_feedback": athlete_feedback})
    return items


def remember_feedback_processed(state: dict[str, Any], item: dict[str, Any], result: str) -> None:
    processed = state.setdefault("processed_feedback_updates", [])
    if not isinstance(processed, list):
        processed = []
        state["processed_feedback_updates"] = processed
    processed.append(
        {
            "slug": item["slug"],
            "date": item["date"],
            "updated_at": item["updated_at"],
            "result": result,
            "processed_at": utcnow_iso(),
        }
    )
    if len(processed) > 100:
        del processed[:-100]


def is_shin_related_text(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    keywords = ["shin", "tibia", "tibial", "periost", "espinilla"]
    return any(keyword in text for keyword in keywords)


def normalized_shin_location(text: str) -> str:
    value = str(text or "").strip().lower()
    if "right" in value or "derech" in value:
        return "right_shin"
    if "left" in value or "izquier" in value:
        return "left_shin"
    return "left_shin" if is_shin_related_text(value) else "left_shin"


def maybe_promote_feedback_to_shin_tracker(item: dict[str, Any]) -> bool:
    athlete_feedback = item.get("athlete_feedback") if isinstance(item.get("athlete_feedback"), dict) else {}
    pain_level = int(athlete_feedback.get("pain_level") or 0) if athlete_feedback else 0
    pain_location = str(athlete_feedback.get("pain_location") or "").strip()
    note = str(athlete_feedback.get("note") or "").strip()
    combined_text = f"{pain_location} {note}".strip()
    if pain_level <= 0:
        return False
    if not is_shin_related_text(combined_text) and pain_level < 4:
        return False
    if pain_level < 2 and not SHIN_TRACKER_PATH.exists():
        return False

    payload = load_yaml(SHIN_TRACKER_PATH)
    shin_tracker = payload.setdefault(
        "shin_tracker",
        {
            "scale": "0=no pain, 10=stop-level pain",
            "rules": {
                "green": "0-2/10 and not worse next morning",
                "yellow": "3/10 or mild next-morning reaction; do not increase load",
                "red": "4/10 or more, pain changing gait, or worsening trend; reduce running load",
            },
            "entries": [],
        },
    )
    entries = shin_tracker.setdefault("entries", [])
    if not isinstance(entries, list):
        entries = []
        shin_tracker["entries"] = entries

    note_line = f"Auto-promoted from feedback {item['slug']} ({item['updated_at']}): dolor {pain_level}/10."
    if pain_location:
        note_line += f" Localizacion: {pain_location}."
    if note:
        note_line += f" Nota: {note}"

    existing = next((entry for entry in entries if str(entry.get("date") or "") == item["date"]), None)
    if existing:
        existing["pain_during"] = max(int(existing.get("pain_during") or 0), pain_level)
        existing["pain_after"] = max(int(existing.get("pain_after") or 0), pain_level)
        existing["pain_next_morning"] = max(int(existing.get("pain_next_morning") or 0), pain_level)
        existing["location"] = existing.get("location") or normalized_shin_location(combined_text)
        if note_line not in str(existing.get("notes") or ""):
            existing["notes"] = (str(existing.get("notes") or "").strip() + " " + note_line).strip()
        existing["updated_by"] = "auto_feedback"
    else:
        entries.append(
            {
                "date": item["date"],
                "pain_during": pain_level,
                "pain_after": pain_level,
                "pain_next_morning": pain_level,
                "location": normalized_shin_location(combined_text),
                "surface": None,
                "shoes": None,
                "notes": note_line,
                "source": "auto_feedback",
            }
        )
    entries.sort(key=lambda entry: str(entry.get("date") or ""))
    save_yaml(SHIN_TRACKER_PATH, payload)
    return True


def remember_run(state: dict[str, Any], detected: list[dict[str, Any]], launched: bool, error: str | None = None) -> None:
    runs = state.setdefault("runs", [])
    if not isinstance(runs, list):
        runs = []
        state["runs"] = runs
    runs.append(
        {
            "run_at": utcnow_iso(),
            "detected_count": len(detected),
            "detected_activity_ids": [item["activity_id"] for item in detected],
            "triggered_pipeline": launched,
            "error": error,
        }
    )
    if len(runs) > 50:
        del runs[:-50]


def main() -> None:
    args = parse_args()
    state = load_state()
    processed_success_ids = {
        int(item.get("activity_id"))
        for item in state.get("processed_activities", [])
        if isinstance(item, dict) and item.get("result") == "success" and item.get("activity_id") is not None
    }
    processed_feedback_versions = {
        (str(item.get("slug")), str(item.get("updated_at")))
        for item in state.get("processed_feedback_updates", [])
        if isinstance(item, dict) and item.get("result") == "success"
    }

    # Detect a sync gap (daemon down / Garmin unreachable for a while): alert and
    # widen the import window so missed activities are recovered rather than lost.
    now = datetime.now(timezone.utc)
    last_success = _parse_iso(state.get("last_successful_sync_at")) or _parse_iso(state.get("last_activity_import_at"))
    activity_days = args.activity_days
    if last_success is not None:
        gap_hours = (now - last_success).total_seconds() / 3600
        if gap_hours > SYNC_GAP_ALERT_HOURS:
            notify_sync_gap(gap_hours)
            activity_days = max(args.activity_days, min(int(gap_hours / 24) + 2, 30))

    if not args.skip_activity_import:
        ok, error = run_step(
            [
                sys.executable,
                str(SYNC_SCRIPT),
                "import-activities",
                "--days",
                str(activity_days),
                "--limit",
                str(args.limit),
            ]
        )
        if not ok:
            state["last_error"] = error
            if looks_like_auth_error(error):
                notify_token_problem(error)
            remember_run(state, [], launched=False, error=error)
            save_json(STATE_PATH, state)
            raise SystemExit(error)
        state["last_successful_sync_at"] = utcnow_iso()

    summaries = activity_summaries()
    new_activities = [item for item in summaries if item["activity_id"] not in processed_success_ids]
    pending_feedback_updates = [item for item in feedback_updates() if (item["slug"], item["updated_at"]) not in processed_feedback_versions]
    if summaries:
        state["last_seen_activity_id"] = summaries[-1]["activity_id"]
        state["last_seen_activity_date"] = summaries[-1]["activity_date"]
    state["last_activity_import_at"] = utcnow_iso()

    if not new_activities and not pending_feedback_updates:
        state["last_error"] = None
        state["last_successful_run"] = utcnow_iso()
        state["next_action"] = "wait_for_new_activity_or_feedback"
        remember_run(state, [], launched=False)
        save_json(STATE_PATH, state)
        write_athlete_state()
        print(json.dumps({"detected": 0, "triggered": False}, indent=2, ensure_ascii=True))
        return

    pipeline_error = None
    if not args.skip_trigger:
        ok = True
        if not args.skip_daily:
            ok, pipeline_error = run_step([sys.executable, str(SYNC_SCRIPT), "import-daily", "--days", str(args.daily_days)])
            if ok:
                state["last_daily_import_at"] = utcnow_iso()
        if ok and not args.skip_athlete_profile:
            ok, pipeline_error = run_step([sys.executable, str(SYNC_SCRIPT), "import-athlete-profile"])
            if ok:
                state["last_profile_sync_at"] = utcnow_iso()
                ok, pipeline_error = run_step([sys.executable, str(ATHLETE_SYNC_SCRIPT)])
        for activity in sorted(new_activities, key=lambda item: (item["activity_date"], item["activity_id"])):
            if not ok:
                break
            review_slug = None
            review_ok, review_payload, review_error = run_json_step(
                [
                    sys.executable,
                    str(REVIEW_SCRIPT),
                    "--date",
                    activity["activity_date"],
                    "--activity-id",
                    str(activity["activity_id"]),
                    "--use-local-imports-only",
                    "--force",
                ]
            )
            if review_ok and isinstance(review_payload, dict):
                analysis_file = str(review_payload.get("analysis_file") or "")
                review_slug = Path(analysis_file).stem.replace(".analysis", "") if analysis_file else None
            elif review_error and review_error_is_non_blocking(review_error):
                review_ok = True
            ok, pipeline_error = run_step(
                [
                    sys.executable,
                    str(ENGINE_SCRIPT),
                    "--as-of",
                    activity["activity_date"],
                    "--days",
                    str(args.dashboard_days),
                ]
            )
            if not review_ok and not pipeline_error:
                pipeline_error = review_error
                ok = False
            remember_processed(state, activity, "success" if ok else "error", review_slug=review_slug)
            if ok:
                state["last_processed_activity_id"] = activity["activity_id"]
                state["last_processed_activity_date"] = activity["activity_date"]
                state["last_processed_at"] = utcnow_iso()
                try:
                    send_post_workout_message(
                        activity_date=activity["activity_date"],
                        activity_id=str(activity["activity_id"]),
                        review_slug=review_slug or "",
                    )
                except Exception:
                    pass
        if ok:
            for item in pending_feedback_updates:
                maybe_promote_feedback_to_shin_tracker(item)
                ok, pipeline_error = run_step(
                    [
                        sys.executable,
                        str(ENGINE_SCRIPT),
                        "--as-of",
                        item["date"],
                        "--days",
                        str(args.dashboard_days),
                    ]
                )
                remember_feedback_processed(state, item, "success" if ok else "error")
                if not ok:
                    break
    else:
        for activity in new_activities:
            remember_processed(state, activity, "detected_only")
        for item in pending_feedback_updates:
            remember_feedback_processed(state, item, "detected_only")

    state["last_error"] = pipeline_error
    state["last_successful_run"] = utcnow_iso() if pipeline_error is None else state.get("last_successful_run")
    if pipeline_error:
        state["next_action"] = "inspect_last_error"
    elif pending_feedback_updates:
        state["next_action"] = "wait_for_new_activity_or_feedback"
    elif new_activities:
        state["next_action"] = "wait_for_new_activity"
    else:
        state["next_action"] = "wait_for_new_activity_or_feedback"
    remember_run(state, new_activities, launched=not args.skip_trigger, error=pipeline_error)
    save_json(STATE_PATH, state)
    write_athlete_state()
    write_workout_family_response()

    if pipeline_error:
        raise SystemExit(pipeline_error)

    print(
        json.dumps(
            {
                "detected": len(new_activities),
                "detected_activity_ids": [item["activity_id"] for item in new_activities],
                "feedback_updates": len(pending_feedback_updates),
                "triggered": not args.skip_trigger,
            },
            indent=2,
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
