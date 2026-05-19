#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from garminconnect import Garmin
from garminconnect.workout import CyclingWorkout, ExecutableStep, FitnessEquipmentWorkout, RepeatGroup, RunningWorkout, SwimmingWorkout, WorkoutSegment

try:
    from scripts.system.athlete_state import write_athlete_state
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.athlete_state import write_athlete_state

try:
    from garminconnect import ActivityDownloadFormat
except ImportError:  # pragma: no cover - depends on installed library version
    ActivityDownloadFormat = None


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CREDENTIALS_PATH = ROOT / "garmin" / "local_credentials.yaml"
DEFAULT_IMPORT_ROOT = ROOT / "training" / "completed" / "imports" / "garmin"
DEFAULT_WORKOUTS_ROOT = ROOT / "training" / "planned" / "workouts"

logger = logging.getLogger("garmin.sync")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Garmin local sync for the running workspace")
    parser.add_argument(
        "--credentials",
        type=Path,
        default=DEFAULT_CREDENTIALS_PATH,
        help="Path to local Garmin credentials YAML",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    import_activities = subparsers.add_parser("import-activities", help="Import recent Garmin activities")
    import_activities.add_argument("--days", type=int, default=14, help="How many days back to import")
    import_activities.add_argument("--limit", type=int, default=50, help="Maximum activities to inspect")
    import_activities.add_argument(
        "--activity-type",
        default="running",
        help="Garmin activity type filter, for example running or trail_running",
    )
    import_activities.add_argument(
        "--download-format",
        choices=["original", "gpx", "tcx", "csv", "kml"],
        default=None,
        help="Optional extra file download format for each activity",
    )

    import_daily = subparsers.add_parser("import-daily", help="Import daily recovery and readiness metrics")
    import_daily.add_argument("--days", type=int, default=14, help="How many days back to import")

    subparsers.add_parser("import-athlete-profile", help="Import Garmin athlete profile, heart-rate baselines and gear")

    schedule_workout = subparsers.add_parser("schedule-workout-file", help="Upload and schedule a planned workout from YAML")
    schedule_workout.add_argument("workout_file", type=Path, help="Path to workout YAML file")

    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def setup_logging() -> None:
    level_name = str(os.getenv("GARMIN_SYNC_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def preview_json(value: Any, limit: int = 500) -> str:
    text = json.dumps(value, ensure_ascii=True, default=json_default) if not isinstance(value, str) else value
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def credentials_from_env() -> dict[str, str | None]:
    return {
        "email": os.getenv("GARMIN_EMAIL"),
        "password": os.getenv("GARMIN_PASSWORD"),
        "token_store": os.getenv("GARMIN_TOKEN_STORE"),
    }


def load_credentials(path: Path) -> dict[str, str]:
    env_creds = credentials_from_env()
    if env_creds["email"] and env_creds["password"]:
        return {
            "email": env_creds["email"],
            "password": env_creds["password"],
            "token_store": env_creds["token_store"] or os.path.expanduser("~/.garminconnect"),
        }

    if not path.exists():
        raise FileNotFoundError(
            f"Credentials not found at {path}. Create it from garmin/local_credentials.yaml.example or set GARMIN_EMAIL and GARMIN_PASSWORD."
        )

    data = load_yaml(path).get("garmin", {})
    email = data.get("email")
    password = data.get("password")
    token_store = data.get("token_store") or os.path.expanduser("~/.garminconnect")

    if not email or not password:
        raise ValueError("Garmin credentials file must define email and password")

    return {
        "email": str(email),
        "password": str(password),
        "token_store": os.path.expanduser(str(token_store)),
    }


def login(credentials: dict[str, str]) -> Garmin:
    logger.info(
        "Logging into Garmin email=%s token_store=%s",
        credentials["email"],
        credentials["token_store"],
    )
    client = Garmin(credentials["email"], credentials["password"])
    client.login(credentials["token_store"])
    logger.info("Garmin login successful")
    return client


def json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def save_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True, default=json_default)
        handle.write("\n")


def save_bytes(path: Path, payload: bytes) -> None:
    ensure_dir(path.parent)
    with path.open("wb") as handle:
        handle.write(payload)


def save_text(path: Path, payload: str) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")


def normalize_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def iso_date_days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def normalize_weight_kg(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    numeric = float(value)
    if numeric > 250:
        return round(numeric / 1000.0, 3)
    return round(numeric, 3)


def imported_activity_max_hr() -> int | None:
    values: list[int] = []
    for path in sorted((DEFAULT_IMPORT_ROOT / "activities").glob("*/summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        max_hr = payload.get("maxHR")
        if max_hr is None:
            continue
        numeric = int(float(max_hr))
        if numeric >= 120:
            values.append(numeric)
    return max(values) if values else None


def activity_dir(activity: dict[str, Any]) -> Path:
    start_time = activity.get("startTimeLocal") or activity.get("startTimeGMT") or "unknown-date"
    day = str(start_time).split(" ")[0]
    activity_id = activity.get("activityId", "unknown")
    return DEFAULT_IMPORT_ROOT / "activities" / f"{day}_{activity_id}"


def activity_matches_date(activity: dict[str, Any], start_date: str) -> bool:
    start_time = activity.get("startTimeLocal") or activity.get("startTimeGMT")
    if not start_time:
        return False
    day = str(start_time).split(" ")[0]
    return day >= start_date


def maybe_download_activity(client: Garmin, activity_id: int, fmt: str | None, target_dir: Path) -> None:
    if not fmt:
        return
    download_format: Any = fmt.upper()
    if ActivityDownloadFormat is not None:
        download_format = getattr(ActivityDownloadFormat, fmt.upper())

    download = client.download_activity(activity_id, dl_fmt=download_format)
    suffix = fmt.lower()
    filename = target_dir / f"activity.{suffix}"

    if isinstance(download, bytes):
        save_bytes(filename, download)
        return

    if isinstance(download, str):
        save_text(filename, download)
        return

    raise TypeError(f"Unexpected download payload type for activity {activity_id}: {type(download)!r}")


def heart_rate_target(zone: str | None, min_bpm: int | None, max_bpm: int | None) -> dict[str, Any]:
    _ = zone, min_bpm, max_bpm
    return {
        "workoutTargetTypeId": 4,
        "workoutTargetTypeKey": "heart.rate.zone",
        "displayOrder": 4,
    }


def no_target() -> dict[str, Any]:
    return {
        "workoutTargetTypeId": 1,
        "workoutTargetTypeKey": "no.target",
        "displayOrder": 1,
    }


STEP_TYPE_MAP = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "rest": {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
}


def meter_unit() -> dict[str, Any]:
    return {"unitId": 1, "unitKey": "meter", "factor": 100}


def distance_condition() -> dict[str, Any]:
    return {
        "conditionTypeId": 3,
        "conditionTypeKey": "distance",
        "displayOrder": 3,
        "displayable": True,
    }


def time_condition() -> dict[str, Any]:
    return {
        "conditionTypeId": 2,
        "conditionTypeKey": "time",
        "displayOrder": 2,
        "displayable": True,
    }


def iterations_condition() -> dict[str, Any]:
    return {
        "conditionTypeId": 7,
        "conditionTypeKey": "iterations",
        "displayOrder": 7,
        "displayable": False,
    }


def pace_to_speed_mps(pace: str) -> float:
    minutes, seconds = pace.replace("/km", "").split(":")
    total_seconds = int(minutes) * 60 + int(seconds)
    return round(1000 / total_seconds, 3)


def pace_target(min_pace: str | None, max_pace: str | None) -> dict[str, Any]:
    values = [pace_to_speed_mps(value) for value in (min_pace, max_pace) if value]
    if not values:
        return no_target()
    values.sort()
    return {
        "workoutTargetTypeId": 6,
        "workoutTargetTypeKey": "pace.zone",
        "displayOrder": 6,
        "targetValueOne": values[0],
        "targetValueTwo": values[1] if len(values) > 1 else None,
    }


def target_payload(target_data: dict[str, Any] | None, include_targets: bool) -> dict[str, Any]:
    if not include_targets or not target_data:
        return no_target()

    target_type = target_data.get("type")
    if not target_type and target_data.get("zone"):
        target_type = "heart_rate_zone"
    if not target_type and (target_data.get("min_bpm") is not None or target_data.get("max_bpm") is not None):
        target_type = "heart_rate_range"
    if not target_type and (target_data.get("min_pace") or target_data.get("max_pace")):
        target_type = "pace_range"

    if target_type in {"heart_rate_zone", "heart_rate_range", "heart_rate_max"}:
        return heart_rate_target(target_data.get("zone"), target_data.get("min_bpm"), target_data.get("max_bpm"))
    if target_type == "pace_range":
        return pace_target(target_data.get("min_pace"), target_data.get("max_pace"))
    return no_target()


def step_target_fields(target_data: dict[str, Any] | None, include_targets: bool) -> dict[str, Any]:
    if not include_targets or not target_data:
        return {}

    target_type = target_data.get("type")
    if not target_type and target_data.get("zone"):
        target_type = "heart_rate_zone"
    if not target_type and (target_data.get("min_bpm") is not None or target_data.get("max_bpm") is not None):
        target_type = "heart_rate_range"
    if not target_type and (target_data.get("min_pace") or target_data.get("max_pace")):
        target_type = "pace_range"

    if target_type == "heart_rate_zone":
        fields: dict[str, Any] = {}
        if target_data.get("zone"):
            fields["zoneNumber"] = int(str(target_data["zone"]).upper().replace("Z", ""))
        if target_data.get("min_bpm") is not None:
            fields["targetValueOne"] = int(target_data["min_bpm"])
        if target_data.get("max_bpm") is not None:
            fields["targetValueTwo"] = int(target_data["max_bpm"])
        return fields

    if target_type in {"heart_rate_range", "heart_rate_max"}:
        fields: dict[str, Any] = {}
        if target_data.get("min_bpm") is not None:
            fields["targetValueOne"] = int(target_data["min_bpm"])
        if target_data.get("max_bpm") is not None:
            fields["targetValueTwo"] = int(target_data["max_bpm"])
        return fields

    if target_type == "pace_range":
        values = [pace_to_speed_mps(value) for value in (target_data.get("min_pace"), target_data.get("max_pace")) if value]
        values.sort()
        fields = {}
        if values:
            fields["targetValueOne"] = values[0]
        if len(values) > 1:
            fields["targetValueTwo"] = values[1]
        return fields

    return {}


def build_executable_step(step_data: dict[str, Any], include_targets: bool) -> ExecutableStep:
    step_type_key = step_data.get("step_type", "interval")
    if step_type_key not in STEP_TYPE_MAP:
        raise ValueError(f"Unsupported step_type: {step_type_key}")

    kwargs: dict[str, Any] = {
        "stepOrder": int(step_data.get("order", 1)),
        "stepType": STEP_TYPE_MAP[step_type_key],
        "targetType": target_payload(step_data.get("target"), include_targets),
        "strokeType": {"strokeTypeId": 0, "displayOrder": 0},
        "equipmentType": {"equipmentTypeId": 0, "displayOrder": 0},
    }

    if step_data.get("description"):
        kwargs["description"] = step_data["description"]

    kwargs.update(step_target_fields(step_data.get("target"), include_targets))

    if step_data.get("distance_m") is not None:
        kwargs["endCondition"] = distance_condition()
        kwargs["endConditionValue"] = float(step_data["distance_m"])
        kwargs["preferredEndConditionUnit"] = meter_unit()
    elif step_data.get("duration_s") is not None:
        kwargs["endCondition"] = time_condition()
        kwargs["endConditionValue"] = float(step_data["duration_s"])
    else:
        raise ValueError("Executable workout step must define distance_m or duration_s")

    return ExecutableStep(**kwargs)


def build_repeat_group(step_data: dict[str, Any], include_targets: bool) -> RepeatGroup:
    iterations = int(step_data["iterations"])
    children = [build_workout_step(child, include_targets) for child in step_data["steps"]]
    kwargs: dict[str, Any] = {
        "stepOrder": int(step_data.get("order", 1)),
        "stepType": STEP_TYPE_MAP["repeat"],
        "numberOfIterations": iterations,
        "workoutSteps": children,
        "endCondition": iterations_condition(),
        "endConditionValue": float(iterations),
        "smartRepeat": False,
    }
    if step_data.get("description"):
        kwargs["description"] = step_data["description"]
    return RepeatGroup(**kwargs)


def build_workout_step(step_data: dict[str, Any], include_targets: bool) -> ExecutableStep | RepeatGroup:
    if step_data.get("type") == "repeat_group":
        return build_repeat_group(step_data, include_targets)
    return build_executable_step(step_data, include_targets)


def infer_workout_sport(workout: dict[str, Any]) -> str:
    raw_sport = str(workout.get("sport", "running")).strip().lower()
    if raw_sport in {"cycling", "bike", "biking"}:
        return "cycling"
    if raw_sport in {"swimming", "swim", "pool_swimming", "lap_swimming"}:
        return "swimming"

    text = " ".join(
        str(value or "")
        for value in (
            workout.get("name"),
            workout.get("description"),
        )
    ).lower()
    if raw_sport == "fitness_equipment" and any(marker in text for marker in {"bicicleta", "bike", "cycling", "rodillo", "ciclismo"}):
        return "cycling"
    if any(marker in text for marker in {"natacion", "natación", "swim", "swimming", "piscina", "nadar"}):
        return "swimming"
    return raw_sport


def sport_type_payload(sport: str) -> dict[str, Any]:
    if sport == "running":
        return {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
    if sport == "cycling":
        return {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2}
    if sport == "swimming":
        return {"sportTypeId": 5, "sportTypeKey": "swimming", "displayOrder": 5}
    return {"sportTypeId": 6, "sportTypeKey": "fitness_equipment", "displayOrder": 6}


def build_workout_payload(spec: dict[str, Any], include_targets: bool) -> RunningWorkout | CyclingWorkout | SwimmingWorkout | FitnessEquipmentWorkout:
    workout = spec["workout"]
    sport = infer_workout_sport(workout)
    steps = [build_workout_step(step, include_targets) for step in workout["steps"]]
    segment = WorkoutSegment(
        segmentOrder=1,
        sportType=sport_type_payload(sport),
        workoutSteps=steps,
    )

    common_kwargs: dict[str, Any] = {
        "workoutName": workout["name"],
        "estimatedDurationInSecs": int(workout["estimated_duration_s"]),
        "workoutSegments": [segment],
        "description": workout.get("description"),
    }
    if sport == "running":
        return RunningWorkout(**common_kwargs)
    if sport == "cycling":
        return CyclingWorkout(**common_kwargs)
    if sport == "swimming":
        return SwimmingWorkout(**common_kwargs)
    if sport in {"fitness_equipment", "strength", "mobility", "stretching", "other"}:
        return FitnessEquipmentWorkout(**common_kwargs)
    raise ValueError(f"Unsupported workout sport: {sport}")


def build_other_workout_dict(spec: dict[str, Any], include_targets: bool) -> dict[str, Any]:
    workout = spec["workout"]
    payload = build_workout_payload({"workout": {**workout, "sport": "other"}}, include_targets).to_dict()
    payload["sportType"] = {
        "sportTypeId": 11,
        "sportTypeKey": "other",
        "displayOrder": 11,
    }
    for segment in payload.get("workoutSegments", []):
        if isinstance(segment, dict):
            segment["sportType"] = {
                "sportTypeId": 11,
                "sportTypeKey": "other",
                "displayOrder": 11,
            }
    return payload


def schedule_workout_file(client: Garmin, workout_file: Path) -> None:
    workout_path = normalize_path(workout_file)
    spec = load_yaml(workout_path)
    workout = spec.get("workout", {})
    schedule_date = workout.get("schedule_date")
    if not schedule_date:
        raise ValueError("Workout spec must define workout.schedule_date")
    if isinstance(schedule_date, (date, datetime)):
        schedule_date = schedule_date.isoformat()
    else:
        schedule_date = str(schedule_date)

    response: dict[str, Any] | None = None
    sport = infer_workout_sport(workout)
    upload_mode = "structured_targets"
    normalized_sport = str(sport).strip().lower()
    prefers_other_fallback = normalized_sport in {"mobility", "stretching", "other"}
    logger.info(
        "Scheduling workout file=%s name=%s date=%s sport=%s prefers_other_fallback=%s",
        display_path(workout_path),
        workout.get("name"),
        schedule_date,
        sport,
        prefers_other_fallback,
    )

    try:
        payload = build_workout_payload(spec, include_targets=True)
        logger.info("Uploading Garmin workout mode=%s payload_preview=%s", upload_mode, preview_json(payload.to_dict()))
        if normalized_sport == "cycling":
            response = client.upload_cycling_workout(payload)
        elif normalized_sport == "swimming":
            response = client.upload_swimming_workout(payload)
        else:
            response = client.upload_workout(payload.to_dict())
    except Exception as exc:
        logger.warning("Structured Garmin upload failed file=%s error=%s", display_path(workout_path), exc)
        if prefers_other_fallback:
            upload_mode = "other_workout_fallback"
            print(f"Structured upload failed, retrying as Garmin other workout: {exc}")
            try:
                other_payload = build_other_workout_dict(spec, include_targets=False)
                logger.info("Uploading Garmin workout mode=%s payload_preview=%s", upload_mode, preview_json(other_payload))
                response = client.upload_workout(other_payload)
            except Exception as other_exc:
                upload_mode = "fitness_equipment_fallback"
                print(f"Garmin other workout failed, retrying as fitness equipment: {other_exc}")
                payload = build_workout_payload({"workout": {**workout, "sport": "fitness_equipment"}}, include_targets=False)
                logger.warning("Garmin other upload failed file=%s error=%s", display_path(workout_path), other_exc)
                logger.info("Uploading Garmin workout mode=%s payload_preview=%s", upload_mode, preview_json(payload.to_dict()))
                response = client.upload_workout(payload.to_dict())
        else:
            upload_mode = "no_target_fallback"
            print(f"Structured target upload failed, retrying without targets: {exc}")
            payload = build_workout_payload(spec, include_targets=False)
            logger.info("Uploading Garmin workout mode=%s payload_preview=%s", upload_mode, preview_json(payload.to_dict()))
            if normalized_sport == "cycling":
                response = client.upload_cycling_workout(payload)
            elif normalized_sport == "swimming":
                response = client.upload_swimming_workout(payload)
            else:
                response = client.upload_workout(payload.to_dict())

    workout_id = response.get("workoutId") or response.get("id")
    if not workout_id:
        raise ValueError(f"Could not determine workout_id from Garmin response: {response}")

    logger.info(
        "Garmin workout uploaded file=%s workout_id=%s upload_mode=%s response_preview=%s",
        display_path(workout_path),
        workout_id,
        upload_mode,
        preview_json(response),
    )
    scheduled = client.schedule_workout(workout_id, schedule_date)
    logger.info(
        "Garmin workout scheduled file=%s workout_id=%s date=%s response_preview=%s",
        display_path(workout_path),
        workout_id,
        schedule_date,
        preview_json(scheduled),
    )
    target_dir = DEFAULT_WORKOUTS_ROOT / schedule_date
    ensure_dir(target_dir)
    save_json(target_dir / f"{workout_path.stem}.garmin_upload.json", {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "status": "scheduled",
        "upload_mode": upload_mode,
        "workout_file": display_path(workout_path),
        "uploaded_response": response,
        "scheduled_response": scheduled,
    })
    print(json.dumps({
        "upload_mode": upload_mode,
        "workout_id": workout_id,
        "schedule_date": schedule_date,
        "workout_name": workout.get("name"),
        "sport": sport,
    }, indent=2, ensure_ascii=True))


def import_activities(client: Garmin, days: int, limit: int, activity_type: str, download_format: str | None) -> None:
    start_date = iso_date_days_ago(days)
    activities = client.get_activities(0, limit, activity_type)
    kept = [activity for activity in activities if activity_matches_date(activity, start_date)]

    imported_ids: list[int] = []
    for activity in kept:
        activity_id = activity["activityId"]
        detail = client.get_activity_details(activity_id)
        target_dir = activity_dir(activity)
        save_json(target_dir / "summary.json", activity)
        save_json(target_dir / "details.json", detail)
        maybe_download_activity(client, activity_id, download_format, target_dir)
        imported_ids.append(activity_id)

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days": days,
        "limit": limit,
        "activity_type": activity_type,
        "imported_count": len(imported_ids),
        "imported_activity_ids": imported_ids,
    }
    save_json(DEFAULT_IMPORT_ROOT / "activities" / "last_import_manifest.json", manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=True))


def import_daily_metrics(client: Garmin, days: int) -> None:
    imported_days: list[str] = []
    start = date.today() - timedelta(days=days)
    for offset in range(days + 1):
        current = (start + timedelta(days=offset)).isoformat()
        sleep_payload = None
        sleep_method = getattr(client, "get_sleep_data", None)
        if sleep_method is not None:
            try:
                sleep_payload = sleep_method(current)
            except Exception as exc:
                sleep_payload = {"error": str(exc)}
        payload = {
            "date": current,
            "heart_rates": client.get_heart_rates(current),
            "hrv": client.get_hrv_data(current),
            "training_readiness": client.get_training_readiness(current),
            "training_status": client.get_training_status(current),
            "max_metrics": client.get_max_metrics(current),
            "sleep": sleep_payload,
        }
        save_json(DEFAULT_IMPORT_ROOT / "daily" / f"{current}.json", payload)
        imported_days.append(current)

    running_tolerance = client.get_running_tolerance(start.isoformat(), date.today().isoformat(), aggregation="weekly")
    save_json(DEFAULT_IMPORT_ROOT / "daily" / "running_tolerance_weekly.json", running_tolerance)

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days": days,
        "imported_days": imported_days,
    }
    save_json(DEFAULT_IMPORT_ROOT / "daily" / "last_import_manifest.json", manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=True))


def import_athlete_profile(client: Garmin) -> None:
    profile: dict[str, Any] = {}

    def call_client(method_name: str, *args: Any) -> Any:
        method = getattr(client, method_name, None)
        if method is None:
            return None
        try:
            return method(*args)
        except Exception as exc:
            return {"error": str(exc)}

    profile["get_full_name"] = call_client("get_full_name")
    profile["get_user_profile"] = call_client("get_user_profile")
    profile["get_settings"] = call_client("get_settings")
    profile["get_personal_record"] = call_client("get_personal_record")

    user_profile = profile.get("get_user_profile") if isinstance(profile.get("get_user_profile"), dict) else {}
    user_data = user_profile.get("userData") if isinstance(user_profile.get("userData"), dict) else {}
    user_id = user_profile.get("id") or user_profile.get("userProfileId") or user_data.get("userProfilePk")
    profile["get_user_summary"] = call_client("get_user_summary", date.today().isoformat())
    if user_id is not None:
        profile["get_gear"] = call_client("get_gear", user_id)
    else:
        profile["get_gear"] = {"error": "Could not determine Garmin user profile id for gear sync"}

    flattened = {
        "synced_at": datetime.utcnow().isoformat() + "Z",
        "raw": profile,
    }

    user_summary = profile.get("get_user_summary") if isinstance(profile.get("get_user_summary"), dict) else {}
    user_settings = profile.get("get_settings") if isinstance(profile.get("get_settings"), dict) else {}
    gear = profile.get("get_gear") if isinstance(profile.get("get_gear"), list) else []
    full_name = profile.get("get_full_name")
    if isinstance(full_name, str):
        flattened["full_name"] = full_name

    flattened["display_name"] = user_profile.get("displayName") or user_profile.get("fullName")
    flattened["gender"] = user_data.get("gender") or user_profile.get("gender") or user_settings.get("gender")
    flattened["birth_date"] = user_data.get("birthDate") or user_profile.get("birthDate") or user_settings.get("birthDate")
    flattened["weight_kg"] = normalize_weight_kg(user_data.get("weight") or user_profile.get("weight") or user_settings.get("weight"))
    flattened["height_cm"] = user_data.get("height") or user_profile.get("height") or user_settings.get("height")
    flattened["resting_heart_rate"] = user_summary.get("restingHeartRate") or user_profile.get("restingHeartRate") or user_settings.get("restingHR")
    explicit_max_hr = user_data.get("maxHeartRate") or user_profile.get("maxHeartRate") or user_settings.get("maxHR")
    explicit_max_hr = int(float(explicit_max_hr)) if explicit_max_hr not in {None, ""} else None
    flattened["max_heart_rate"] = explicit_max_hr if explicit_max_hr and explicit_max_hr >= 120 else imported_activity_max_hr()
    flattened["vo2max"] = user_data.get("vo2MaxRunning") or user_profile.get("vo2MaxRunning") or user_profile.get("vo2Max")
    flattened["lactate_threshold_heart_rate"] = user_data.get("lactateThresholdHeartRate") or user_profile.get("lactateThresholdHeartRate")
    flattened["training_days"] = user_data.get("availableTrainingDays") or []
    flattened["preferred_long_training_days"] = user_data.get("preferredLongTrainingDays") or []
    flattened["gear"] = []

    for item in gear:
        if not isinstance(item, dict):
            continue
        flattened["gear"].append(
            {
                "name": item.get("name"),
                "display_name": item.get("displayName") or item.get("customMakeModel") or item.get("name"),
                "distance_km": item.get("totalDistance") or item.get("distance"),
            }
        )

    target_dir = DEFAULT_IMPORT_ROOT / "profile"
    save_json(target_dir / "athlete_profile_snapshot.json", flattened)
    write_athlete_state()
    print(json.dumps({"written": display_path(target_dir / 'athlete_profile_snapshot.json')}, indent=2, ensure_ascii=True))


def main() -> None:
    setup_logging()
    args = parse_args()
    credentials = load_credentials(args.credentials)
    client = login(credentials)

    if args.command == "import-activities":
        import_activities(client, args.days, args.limit, args.activity_type, args.download_format)
        return

    if args.command == "import-daily":
        import_daily_metrics(client, args.days)
        return

    if args.command == "import-athlete-profile":
        import_athlete_profile(client)
        return

    if args.command == "schedule-workout-file":
        schedule_workout_file(client, args.workout_file)
        return

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
