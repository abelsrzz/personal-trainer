#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.system.athlete_state import write_athlete_state
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.athlete_state import write_athlete_state


ROOT = Path(__file__).resolve().parents[2]
GARMIN_ACTIVITY_ROOT = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
GARMIN_DAILY_ROOT = ROOT / "training" / "completed" / "imports" / "garmin" / "daily"
REVIEW_ROOT = ROOT / "training" / "completed" / "reviews"
FEEDBACK_ROOT = ROOT / "training" / "completed" / "feedback"
SHIN_TRACKER_PATH = ROOT / "athlete" / "shin_tracker.yaml"
GOAL_GATES_PATH = ROOT / "planning" / "goal_gates.yaml"
ACTIVE_CYCLE_PATH = ROOT / "planning" / "cycles" / "active.yaml"
PREFERENCES_PATH = ROOT / "athlete" / "preferences.yaml"
RESPONSE_PROFILE_PATH = ROOT / "athlete" / "response_profile.yaml"
SESSION_SELECTION_MATRIX_PATH = ROOT / "planning" / "session_selection_matrix.yaml"
RACES_ROOT = ROOT / "races"
STATUS_DASHBOARD_PATH = ROOT / "athlete" / "status_dashboard.md"
COACH_DECISION_MD_PATH = ROOT / "planning" / "coach_decision.md"
COACH_DECISION_JSON_PATH = ROOT / "planning" / "coach_decision.json"
GARMIN_COVERAGE_REPORT_PATH = ROOT / "planning" / "data_quality_report.md"
RUNNING_TOLERANCE_PATH = GARMIN_DAILY_ROOT / "running_tolerance_weekly.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build athlete dashboard and coaching decision from local Garmin data")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Analysis date, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=28, help="Dashboard lookback window")
    parser.add_argument("--write", action=argparse.BooleanOptionalAction, default=True, help="Write markdown and JSON outputs")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True, default=str)
        handle.write("\n")


def save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_local_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).split(" ")[0]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def seconds_to_pace(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}/km"


def seconds_to_time(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}%"


def fmt_float(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def activity_type(summary: dict[str, Any]) -> str | None:
    return summary.get("activityType", {}).get("typeKey")


def load_activity_summaries() -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    for path in sorted(GARMIN_ACTIVITY_ROOT.glob("*/summary.json")):
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        if activity_type(payload) not in {"running", "trail_running"}:
            continue
        activity_date = parse_local_date(payload.get("startTimeLocal") or payload.get("startTimeGMT"))
        if activity_date is None:
            continue
        distance_m = float(payload.get("distance") or 0.0)
        duration_s = float(payload.get("duration") or payload.get("movingDuration") or 0.0)
        pace_s = duration_s * 1000.0 / distance_m if distance_m else None
        activities.append(
            {
                "date": activity_date,
                "activity_id": payload.get("activityId"),
                "name": payload.get("activityName"),
                "distance_km": distance_m / 1000.0,
                "duration_s": duration_s,
                "pace_s_per_km": pace_s,
                "avg_hr": payload.get("averageHR"),
                "max_hr": payload.get("maxHR"),
                "avg_power_w": payload.get("avgPower"),
                "elevation_gain_m": payload.get("elevationGain"),
                "aerobic_training_effect": payload.get("aerobicTrainingEffect"),
                "anaerobic_training_effect": payload.get("anaerobicTrainingEffect"),
                "training_effect_label": payload.get("trainingEffectLabel"),
                "vo2max": payload.get("vO2MaxValue"),
                "fastest_1k_s": payload.get("fastestSplit_1000"),
                "fastest_5k_s": payload.get("fastestSplit_5000"),
                "fastest_10k_s": payload.get("fastestSplit_10000"),
                "source_path": str(path.relative_to(ROOT)),
            }
        )
    activities.sort(key=lambda item: item["date"])
    return activities


def load_reviews() -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for path in sorted(REVIEW_ROOT.glob("*.analysis.json")):
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        review_date = parse_local_date(payload.get("planned", {}).get("date"))
        if review_date is None:
            continue
        payload["review_date"] = review_date
        payload["source_path"] = str(path.relative_to(ROOT))
        reviews.append(payload)
    reviews.sort(key=lambda item: item["review_date"])
    return reviews


def load_feedback() -> list[dict[str, Any]]:
    feedback_items: list[dict[str, Any]] = []
    for path in sorted(FEEDBACK_ROOT.glob("*.feedback.json")):
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        feedback_date = parse_local_date(payload.get("date"))
        athlete_feedback = payload.get("athlete_feedback") if isinstance(payload.get("athlete_feedback"), dict) else {}
        if feedback_date is None or not isinstance(athlete_feedback, dict):
            continue
        feedback_items.append(
            {
                **payload,
                "feedback_date": feedback_date,
                "athlete_feedback": athlete_feedback,
                "slug": path.stem.replace(".feedback", ""),
                "source_path": str(path.relative_to(ROOT)),
            }
        )
    feedback_items.sort(key=lambda item: (item["feedback_date"], str(item.get("updated_at") or "")))
    return feedback_items


def load_daily_metrics() -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for path in sorted(GARMIN_DAILY_ROOT.glob("*.json")):
        if path.name.startswith("last_import") or path.name.startswith("running_tolerance"):
            continue
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        metric_date = parse_local_date(payload.get("date") or path.stem)
        if metric_date is None:
            continue
        metrics.append({"date": metric_date, "payload": payload, "source_path": str(path.relative_to(ROOT))})
    metrics.sort(key=lambda item: item["date"])
    return metrics


def load_running_tolerance() -> dict[str, Any]:
    if not RUNNING_TOLERANCE_PATH.exists():
        return {}
    try:
        payload = load_json(RUNNING_TOLERANCE_PATH)
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_active_cycle() -> dict[str, Any]:
    payload = load_yaml(ACTIVE_CYCLE_PATH).get("cycle", {})
    return payload if isinstance(payload, dict) else {}


def load_preferences() -> dict[str, Any]:
    payload = load_yaml(PREFERENCES_PATH).get("preferences", {})
    return payload if isinstance(payload, dict) else {}


def load_response_profile() -> dict[str, Any]:
    payload = load_yaml(RESPONSE_PROFILE_PATH).get("response_profile", {})
    return payload if isinstance(payload, dict) else {}


def load_session_selection_matrix() -> dict[str, Any]:
    payload = load_yaml(SESSION_SELECTION_MATRIX_PATH).get("session_selection_matrix", {})
    return payload if isinstance(payload, dict) else {}


def load_races() -> list[dict[str, Any]]:
    races: list[dict[str, Any]] = []
    for path in sorted(RACES_ROOT.glob("**/*.yaml")):
        payload = load_yaml(path)
        if not isinstance(payload, dict):
            continue
        race_date = parse_local_date(payload.get("date"))
        if race_date is None:
            continue
        races.append(
            {
                "id": payload.get("id") or path.stem,
                "name": payload.get("name") or path.stem,
                "date": race_date,
                "priority": str(payload.get("priority") or "").upper(),
                "distance": str(payload.get("distance") or payload.get("distance_km") or ""),
                "goal": payload.get("goal") or {},
                "coaching_note": payload.get("coaching_note") or "",
            }
        )
    races.sort(key=lambda item: item["date"])
    return races


def active_block_from_master_plan(as_of: date, active_cycle: dict[str, Any]) -> dict[str, Any]:
    master_plan_path = ROOT / str(active_cycle.get("master_plan_path") or "planning/master_plan.md")
    text = master_plan_path.read_text(encoding="utf-8") if master_plan_path.exists() else ""
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        number, separator, remainder = line.partition(". ")
        if number.isdigit() and separator and remainder.startswith("`"):
            if current:
                blocks.append(current)
            current = {"name": remainder.strip("`").strip(), "start": None, "end": None}
            continue
        if current and line.startswith("- Dates:"):
            date_text = line.split(":", 1)[1].strip().replace("`", "")
            if " to " in date_text:
                start_text, end_text = date_text.split(" to ", 1)
                current["start"] = parse_local_date(start_text.strip())
                current["end"] = parse_local_date(end_text.strip())
    if current:
        blocks.append(current)
    for block in blocks:
        if block.get("start") and block.get("end") and block["start"] <= as_of <= block["end"]:
            return block
    return blocks[0] if blocks else {}


def active_context(as_of: date) -> dict[str, Any]:
    cycle = load_active_cycle()
    races = load_races()
    goal_race_slug = str(cycle.get("goal_race_slug") or "").lower()
    goal_race = next((race for race in races if goal_race_slug and goal_race_slug in str(race.get("id") or "").lower()), None)
    if goal_race is None:
        goal_race = next((race for race in races if race.get("priority") == "S"), None)
    block = active_block_from_master_plan(as_of, cycle)
    days_to_goal_race = (goal_race["date"] - as_of).days if goal_race and goal_race.get("date") else None
    response_profile = load_response_profile()
    preferences = load_preferences()
    selection_matrix = load_session_selection_matrix()
    return {
        "cycle": cycle,
        "goal_race": goal_race,
        "days_to_goal_race": days_to_goal_race,
        "active_block": block,
        "response_profile": response_profile,
        "preferences": preferences,
        "selection_matrix": selection_matrix,
        "races": races,
    }


def block_key(block_name: str | None) -> str | None:
    normalized = str(block_name or "").lower()
    if "block 1" in normalized or "bloque 1" in normalized:
        return "block_1"
    if "block 2" in normalized or "bloque 2" in normalized:
        return "block_2"
    if "block 3" in normalized or "bloque 3" in normalized:
        return "block_3"
    if "block 4" in normalized or "bloque 4" in normalized:
        return "block_4"
    if "block 5" in normalized or "bloque 5" in normalized:
        return "block_5"
    if "block 6" in normalized or "bloque 6" in normalized:
        return "block_6"
    return None


def target_distance_key(goal_race: dict[str, Any] | None) -> str:
    raw = str((goal_race or {}).get("distance") or "general").lower()
    if "10" in raw:
        return "10k"
    if "5" in raw:
        return "5k"
    if "21" in raw or "half" in raw:
        return "21k"
    if "42" in raw or "marathon" in raw:
        return "marathon"
    return "general"


def shin_band(shin_pain: int | None) -> str:
    if shin_pain is None or shin_pain <= 2:
        return "green"
    if shin_pain == 3:
        return "yellow"
    return "red"


def derive_session_guidance(context: dict[str, Any], coach_state: str, shin_pain: int | None) -> dict[str, Any]:
    matrix = context.get("selection_matrix", {})
    rules = matrix.get("rules", [])
    block = block_key(context.get("active_block", {}).get("name"))
    target_distance = target_distance_key(context.get("goal_race"))
    current_shin_band = shin_band(shin_pain)
    primary: list[str] = []
    optional: list[str] = []
    avoid: list[str] = []
    quality_volume_cap = None

    for rule in rules:
        when = rule.get("when", {})
        if when.get("coach_state") and when.get("coach_state") != coach_state:
            continue
        if when.get("block") and when.get("block") != block:
            continue
        if when.get("target_distance") and when.get("target_distance") != target_distance:
            continue
        recommend = rule.get("recommend", {})
        if recommend:
            primary.extend(recommend.get("primary", []))
            optional.extend(recommend.get("optional", []))
            avoid.extend(rule.get("avoid", []))
            quality_volume_cap = rule.get("quality_volume_cap") or quality_volume_cap

    for rule in rules:
        when = rule.get("when", {})
        if when.get("shin_band") != current_shin_band:
            continue
        override = rule.get("override", {})
        remove = set(override.get("remove", []))
        prefer = override.get("prefer", [])
        primary = [item for item in primary if item not in remove]
        optional = [item for item in optional if item not in remove]
        avoid.extend(list(remove))
        primary = prefer + [item for item in primary if item not in prefer]

    positive_bias = [item.get("family") for item in context.get("response_profile", {}).get("workout_response", {}).get("likely_positive", []) if item.get("family")]
    careful_bias = [item.get("family") for item in context.get("response_profile", {}).get("workout_response", {}).get("use_carefully", []) if item.get("family")]
    lower_priority = [item.get("family") for item in context.get("response_profile", {}).get("workout_response", {}).get("likely_lower_priority", []) if item.get("family")]

    ordered_primary = [item for item in positive_bias if item in primary] + [item for item in primary if item not in positive_bias and item not in lower_priority]
    avoid = list(dict.fromkeys(avoid + careful_bias + lower_priority))

    return {
        "coach_state": coach_state,
        "shin_band": current_shin_band,
        "block": block,
        "target_distance": target_distance,
        "primary": list(dict.fromkeys(ordered_primary)),
        "optional": list(dict.fromkeys(optional)),
        "avoid": list(dict.fromkeys(avoid)),
        "quality_volume_cap": quality_volume_cap,
        "selection_order": matrix.get("interpretation", {}).get("selection_order", []),
    }


def nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        for item in value:
            numeric = first_numeric(item)
            if numeric is not None:
                return numeric
    if isinstance(value, dict):
        for nested in value.values():
            numeric = first_numeric(nested)
            if numeric is not None:
                return numeric
    return None


def daily_metric_snapshot(metrics: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    candidates = [item for item in metrics if item["date"] <= as_of]
    if not candidates:
        return {}
    latest = candidates[-1]["payload"]
    sleep_payload = latest.get("sleep") if isinstance(latest.get("sleep"), dict) else {}
    return {
        "hrv": first_numeric(latest.get("hrv")),
        "training_readiness": first_numeric(latest.get("training_readiness")),
        "resting_heart_rate": first_numeric(nested_get(latest, "heart_rates", "restingHeartRate")) or first_numeric(latest.get("heart_rates")),
        "training_status": nested_get(latest, "training_status", "mostRecentTrainingStatus", "trainingStatus")
        or nested_get(latest, "training_status", "trainingStatus")
        or latest.get("training_status"),
        "sleep_score": first_numeric(sleep_payload.get("sleepScores")),
        "sleep_duration_s": first_numeric(sleep_payload.get("sleepTimeSeconds")),
    }


def classify_daily_signals(metrics: list[dict[str, Any]], activities: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    snapshot = daily_metric_snapshot(metrics, as_of)
    last_28 = aggregate_window(activities, as_of - timedelta(days=27), as_of)
    running_tolerance = load_running_tolerance()
    daily_window = [item for item in metrics if as_of - timedelta(days=6) <= item["date"] <= as_of]
    hrv_values = [first_numeric(item["payload"].get("hrv")) for item in daily_window]
    hrv_values = [value for value in hrv_values if value is not None]
    readiness = snapshot.get("training_readiness")
    resting_hr = snapshot.get("resting_heart_rate")
    sleep_score = snapshot.get("sleep_score")
    avg_run_hr = last_28.get("avg_hr")
    baseline_hrv = sum(hrv_values) / len(hrv_values) if hrv_values else None

    hrv_flag = None
    if snapshot.get("hrv") is not None and baseline_hrv is not None and baseline_hrv > 0:
        hrv_ratio = float(snapshot["hrv"]) / baseline_hrv
        if hrv_ratio < 0.85:
            hrv_flag = "low"
        elif hrv_ratio > 1.1:
            hrv_flag = "high"
        else:
            hrv_flag = "stable"

    readiness_flag = None
    if readiness is not None:
        if readiness < 35:
            readiness_flag = "low"
        elif readiness < 60:
            readiness_flag = "moderate"
        else:
            readiness_flag = "good"

    resting_hr_flag = None
    if resting_hr is not None and avg_run_hr is not None:
        if resting_hr >= 60:
            resting_hr_flag = "high"
        elif resting_hr <= 50:
            resting_hr_flag = "low"
        else:
            resting_hr_flag = "normal"

    training_status_text = str(snapshot.get("training_status") or "").lower()
    training_status_flag = None
    if training_status_text:
        if any(keyword in training_status_text for keyword in ["recovery", "detraining", "strained", "overreaching"]):
            training_status_flag = "caution"
        elif any(keyword in training_status_text for keyword in ["productive", "maintaining", "peaking"]):
            training_status_flag = "positive"
        else:
            training_status_flag = "neutral"

    sleep_flag = None
    if sleep_score is not None:
        if sleep_score < 60:
            sleep_flag = "poor"
        elif sleep_score < 75:
            sleep_flag = "fair"
        else:
            sleep_flag = "good"

    acute_load = None
    chronic_load = None
    load_ratio = None
    running_tolerance_flag = None
    entries = running_tolerance.get("weekSummaries") or running_tolerance.get("weeks") or running_tolerance.get("summaries") or []
    if isinstance(entries, list) and entries:
        latest_entry = entries[-1] if isinstance(entries[-1], dict) else {}
        acute_load = first_numeric(latest_entry.get("acuteLoad") or latest_entry.get("recentTrainingLoad") or latest_entry.get("currentLoad"))
        chronic_load = first_numeric(latest_entry.get("chronicLoad") or latest_entry.get("chronicTrainingLoad") or latest_entry.get("baselineLoad"))
        if acute_load is not None and chronic_load is not None and chronic_load > 0:
            load_ratio = acute_load / chronic_load
            if load_ratio >= 1.3:
                running_tolerance_flag = "high"
            elif load_ratio <= 0.75:
                running_tolerance_flag = "low"
            else:
                running_tolerance_flag = "balanced"

    return {
        "snapshot": snapshot,
        "baseline_hrv": baseline_hrv,
        "hrv_flag": hrv_flag,
        "readiness_flag": readiness_flag,
        "resting_hr_flag": resting_hr_flag,
        "training_status_flag": training_status_flag,
        "sleep_flag": sleep_flag,
        "acute_load": acute_load,
        "chronic_load": chronic_load,
        "load_ratio": load_ratio,
        "running_tolerance_flag": running_tolerance_flag,
    }


def garmin_data_quality_report(daily: list[dict[str, Any]], activities: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    daily_snapshot = daily_metric_snapshot(daily, as_of)
    daily_available = bool(daily)
    running_tolerance = load_running_tolerance()
    latest_daily = daily[-1]["date"].isoformat() if daily else None
    activity_latest = activities[-1]["date"].isoformat() if activities else None
    available = {
        "activities": bool(activities),
        "daily_metrics": daily_available,
        "hrv": daily_snapshot.get("hrv") is not None,
        "training_readiness": daily_snapshot.get("training_readiness") is not None,
        "resting_heart_rate": daily_snapshot.get("resting_heart_rate") is not None,
        "training_status": daily_snapshot.get("training_status") is not None,
        "sleep": daily_snapshot.get("sleep_score") is not None,
        "running_tolerance": bool(running_tolerance),
    }
    missing = [name for name, present in available.items() if not present and name not in {"activities", "daily_metrics"}]
    improvements = []
    if available["hrv"]:
        improvements.append("Integrar HRV reciente en la decision de carga y en el dashboard.")
    if available["training_readiness"]:
        improvements.append("Usar training readiness para bloquear progresiones cuando Garmin marque baja preparacion.")
    if available["resting_heart_rate"]:
        improvements.append("Comparar resting HR reciente con baseline para detectar fatiga o deriva.")
    if available["training_status"]:
        improvements.append("Traducir training status a una señal visible de forma y tolerancia de carga.")
    if available["sleep"]:
        improvements.append("Usar sueño reciente para frenar sesiones exigentes cuando Garmin marque mala noche.")
    if available["running_tolerance"]:
        improvements.append("Usar running tolerance para limitar aumentos de carga cuando Garmin marque baja tolerancia.")
    if not daily_available:
        improvements.append("Importar daily metrics de Garmin con regularidad para desbloquear HRV, readiness y resting HR.")
    if not activities:
        improvements.append("Importar actividades recientes de Garmin antes de cualquier analisis de rendimiento.")
    return {
        "available": available,
        "missing": missing,
        "latest_daily_date": latest_daily,
        "latest_activity_date": activity_latest,
        "daily_snapshot": daily_snapshot,
        "improvements": improvements,
    }


def load_shin_entries() -> list[dict[str, Any]]:
    data = load_yaml(SHIN_TRACKER_PATH)
    entries = data.get("shin_tracker", {}).get("entries", [])
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        entry_date = parse_local_date(entry.get("date"))
        if entry_date is None:
            continue
        normalized.append({**entry, "date": entry_date})
    normalized.sort(key=lambda item: item["date"])
    return normalized


def is_quality_activity(activity: dict[str, Any]) -> bool:
    label = str(activity.get("training_effect_label") or "").upper()
    aerobic_te = float(activity.get("aerobic_training_effect") or 0.0)
    anaerobic_te = float(activity.get("anaerobic_training_effect") or 0.0)
    avg_hr = float(activity.get("avg_hr") or 0.0)
    return aerobic_te >= 3.5 or anaerobic_te >= 1.0 or avg_hr >= 165 or any(key in label for key in ["TEMPO", "VO2", "ANAEROBIC", "LACTATE"])


def activities_between(activities: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [item for item in activities if start <= item["date"] <= end]


def aggregate_window(activities: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    window = activities_between(activities, start, end)
    total_km = sum(float(item.get("distance_km") or 0.0) for item in window)
    total_duration = sum(float(item.get("duration_s") or 0.0) for item in window)
    quality = [item for item in window if is_quality_activity(item)]
    long_run = max((float(item.get("distance_km") or 0.0) for item in window), default=0.0)
    weighted_hr_num = sum(float(item.get("avg_hr") or 0.0) * float(item.get("duration_s") or 0.0) for item in window if item.get("avg_hr"))
    avg_hr = weighted_hr_num / total_duration if total_duration else None
    pace = total_duration / total_km if total_km else None
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "runs": len(window),
        "km": total_km,
        "duration_s": total_duration,
        "avg_pace_s_per_km": pace,
        "avg_hr": avg_hr,
        "quality_runs": len(quality),
        "long_run_km": long_run,
    }


def weekly_volume(activities: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, int], dict[str, Any]] = defaultdict(lambda: {"km": 0.0, "runs": 0, "quality_runs": 0, "long_run_km": 0.0})
    for activity in activities_between(activities, start, end):
        year, week, _ = activity["date"].isocalendar()
        bucket = buckets[(year, week)]
        distance = float(activity.get("distance_km") or 0.0)
        bucket["km"] += distance
        bucket["runs"] += 1
        bucket["long_run_km"] = max(bucket["long_run_km"], distance)
        if is_quality_activity(activity):
            bucket["quality_runs"] += 1
    return [
        {"week": f"{year}-W{week:02d}", **values}
        for (year, week), values in sorted(buckets.items())
    ]


def iso_week_window(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())
    end = start + timedelta(days=6)
    return start, end


def completed_week_windows(as_of: date) -> tuple[tuple[date, date], tuple[date, date]]:
    last_completed_end = as_of - timedelta(days=as_of.weekday() + 1)
    last_completed_start = last_completed_end - timedelta(days=6)
    previous_end = last_completed_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)
    return (last_completed_start, last_completed_end), (previous_start, previous_end)


def latest_high_risk_review(reviews: list[dict[str, Any]], as_of: date, days: int = 7) -> dict[str, Any] | None:
    start = as_of - timedelta(days=days - 1)
    candidates = [item for item in reviews if start <= item["review_date"] <= as_of]
    risky = [item for item in candidates if item.get("risk_level") == "alto" or int(item.get("score") or 10) <= 4]
    return risky[-1] if risky else None


def recent_feedback_items(feedback_items: list[dict[str, Any]], as_of: date, days: int = 7) -> list[dict[str, Any]]:
    start = as_of - timedelta(days=days - 1)
    return [item for item in feedback_items if start <= item["feedback_date"] <= as_of]


def latest_feedback(feedback_items: list[dict[str, Any]], as_of: date) -> dict[str, Any] | None:
    candidates = [item for item in feedback_items if item["feedback_date"] <= as_of]
    return candidates[-1] if candidates else None


def latest_shin_entry(entries: list[dict[str, Any]], as_of: date) -> dict[str, Any] | None:
    candidates = [entry for entry in entries if entry["date"] <= as_of]
    return candidates[-1] if candidates else None


def max_shin_pain(entry: dict[str, Any] | None) -> int | None:
    if not entry:
        return None
    values = [entry.get("pain_during"), entry.get("pain_after"), entry.get("pain_next_morning")]
    numeric = [int(value) for value in values if value is not None]
    return max(numeric) if numeric else None


def best_split(activities: list[dict[str, Any]], key: str, start: date, end: date) -> float | None:
    values = [float(item[key]) for item in activities_between(activities, start, end) if item.get(key)]
    return min(values) if values else None


def evaluate_goal_gates(activities: list[dict[str, Any]], reviews: list[dict[str, Any]], feedback_items: list[dict[str, Any]], shin_entries: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    config = load_yaml(GOAL_GATES_PATH).get("goal_gates", {})
    thresholds = config.get("thresholds", {})
    start_28 = as_of - timedelta(days=27)
    start_90 = as_of - timedelta(days=89)
    start_180 = as_of - timedelta(days=179)
    last_28 = aggregate_window(activities, start_28, as_of)
    avg_weekly_km = last_28["km"] / 4.0
    best_5k = best_split(activities, "fastest_5k_s", start_90, as_of)
    best_10k = best_split(activities, "fastest_10k_s", start_180, as_of)
    high_risk_count = len(
        [item for item in reviews if start_28 <= item["review_date"] <= as_of and (item.get("risk_level") == "alto" or int(item.get("score") or 10) <= 4)]
    )
    subjective_alerts_28d = len([
        item for item in feedback_items if start_28 <= item["feedback_date"] <= as_of and (
            int(item.get("athlete_feedback", {}).get("pain_level") or 0) >= 4
            or str(item.get("athlete_feedback", {}).get("compliance") or "") in {"aborted", "modified"}
        )
    ])
    total_risk_events = high_risk_count + subjective_alerts_28d
    shin_pain = max_shin_pain(latest_shin_entry(shin_entries, as_of))

    foundation = {
        "name": "Base estable",
        "passed": avg_weekly_km >= float(thresholds.get("foundation_avg_weekly_km", 40))
        and last_28["long_run_km"] >= float(thresholds.get("foundation_long_run_km", 14))
        and total_risk_events == 0
        and (shin_pain is None or shin_pain <= 2),
        "evidence": f"Media 4 semanas {avg_weekly_km:.1f} km/sem, tirada larga {last_28['long_run_km']:.1f} km, alertas {total_risk_events}, periostio {shin_pain if shin_pain is not None else '-'}.",
    }
    threshold_gate = {
        "name": "Umbral competitivo",
        "passed": best_5k is not None and best_5k <= float(thresholds.get("threshold_gate_5k_s", 19 * 60)),
        "evidence": f"Mejor 5k reciente: {seconds_to_time(best_5k)}.",
    }
    specific_gate = {
        "name": "Precondicion 35:00",
        "passed": avg_weekly_km >= float(thresholds.get("specific_avg_weekly_km", 50))
        and last_28["long_run_km"] >= float(thresholds.get("specific_long_run_km", 16))
        and best_5k is not None
        and best_5k <= float(thresholds.get("specific_5k_s", 18 * 60))
        and total_risk_events == 0
        and (shin_pain is None or shin_pain <= 2),
        "evidence": f"Media {avg_weekly_km:.1f} km/sem, tirada {last_28['long_run_km']:.1f} km, 5k {seconds_to_time(best_5k)}, alertas {total_risk_events}.",
    }
    final_gate = {
        "name": "Seleccion 35:00",
        "passed": best_5k is not None
        and best_5k <= float(thresholds.get("final_5k_s", 17 * 60 + 15))
        and (best_10k is None or best_10k <= float(thresholds.get("final_10k_s", 36 * 60 + 30)))
        and specific_gate["passed"],
        "evidence": f"5k {seconds_to_time(best_5k)}, 10k {seconds_to_time(best_10k)}.",
    }

    gates = [foundation, threshold_gate, specific_gate, final_gate]
    passed_count = sum(1 for gate in gates if gate["passed"])
    if final_gate["passed"]:
        status = "35_ready"
        summary = "El 35:00 puede entrar en la estrategia si las semanas finales confirman recuperacion."
    elif specific_gate["passed"]:
        status = "aggressive_alive"
        summary = "El objetivo agresivo sigue vivo, pero aun falta evidencia final."
    elif threshold_gate["passed"] or foundation["passed"]:
        status = "development_needed"
        summary = "Hay base para progresar, pero 35:00 aun no debe dirigir los ritmos."
    else:
        status = "unsupported_now"
        summary = "Con la evidencia actual, 35:00 sigue siendo aspiracional y no prescribe ritmos."

    return {
        "status": status,
        "summary": summary,
        "passed_count": passed_count,
        "total_gates": len(gates),
        "metrics": {
            "avg_weekly_km_28d": avg_weekly_km,
            "long_run_km_28d": last_28["long_run_km"],
            "best_5k_s_90d": best_5k,
            "best_10k_s_180d": best_10k,
            "high_risk_reviews_28d": total_risk_events,
            "subjective_alerts_28d": subjective_alerts_28d,
            "latest_shin_pain": shin_pain,
        },
        "gates": gates,
    }


def riegel_time(source_time_s: float, source_distance_km: float, target_distance_km: float) -> float:
    return source_time_s * (target_distance_km / source_distance_km) ** 1.06


def performance_estimate(activities: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    start_90 = as_of - timedelta(days=89)
    start_180 = as_of - timedelta(days=179)
    best_5k = best_split(activities, "fastest_5k_s", start_90, as_of)
    best_10k = best_split(activities, "fastest_10k_s", start_180, as_of)
    estimate_10k_from_5k = riegel_time(best_5k, 5.0, 10.0) if best_5k else None
    estimate_5k_from_10k = riegel_time(best_10k, 10.0, 5.0) if best_10k else None
    candidates_10k = [value for value in [best_10k, estimate_10k_from_5k] if value is not None]
    current_10k_estimate = min(candidates_10k) if candidates_10k else None
    return {
        "best_5k_s_90d": best_5k,
        "best_10k_s_180d": best_10k,
        "estimate_10k_from_5k_s": estimate_10k_from_5k,
        "estimate_5k_from_10k_s": estimate_5k_from_10k,
        "current_10k_estimate_s": current_10k_estimate,
        "method": "Mejores splits recientes de Garmin y conversion Riegel; usar como tendencia, no como garantia de carrera.",
    }


def build_decision(activities: list[dict[str, Any]], reviews: list[dict[str, Any]], feedback_items: list[dict[str, Any]], shin_entries: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    last_7 = aggregate_window(activities, as_of - timedelta(days=6), as_of)
    prev_7 = aggregate_window(activities, as_of - timedelta(days=13), as_of - timedelta(days=7))
    last_28 = aggregate_window(activities, as_of - timedelta(days=27), as_of)
    (last_week_start, last_week_end), (prev_week_start, prev_week_end) = completed_week_windows(as_of)
    last_complete_week = aggregate_window(activities, last_week_start, last_week_end)
    previous_complete_week = aggregate_window(activities, prev_week_start, prev_week_end)
    volume_spike = None
    if prev_7["km"] > 0:
        volume_spike = ((last_7["km"] - prev_7["km"]) / prev_7["km"]) * 100.0
    weekly_spike = None
    if previous_complete_week["km"] > 0:
        weekly_spike = ((last_complete_week["km"] - previous_complete_week["km"]) / previous_complete_week["km"]) * 100.0

    risky_review = latest_high_risk_review(reviews, as_of)
    latest_feedback_item = latest_feedback(feedback_items, as_of)
    recent_feedback = recent_feedback_items(feedback_items, as_of)
    shin_entry = latest_shin_entry(shin_entries, as_of)
    shin_pain = max_shin_pain(shin_entry)
    daily_signals = classify_daily_signals(load_daily_metrics(), activities, as_of)
    context = active_context(as_of)
    reasons: list[str] = []
    status = "green"
    action = "maintain_or_progress_carefully"

    if risky_review:
        reasons.append(f"Revision reciente de alto riesgo: {risky_review['planned']['date']} {risky_review['planned']['name']}.")
        status = "red"
    if shin_pain is not None and shin_pain >= 4:
        reasons.append(f"Periostio con dolor maximo {shin_pain}/10 en el ultimo registro.")
        status = "red"
    elif shin_pain is not None and shin_pain == 3 and status != "red":
        reasons.append("Periostio en 3/10: no conviene aumentar carga.")
        status = "yellow"
    if weekly_spike is not None and weekly_spike > 30 and last_complete_week["km"] >= 25:
        reasons.append(
            f"Subida de volumen semanal de {weekly_spike:.0f}% ({previous_complete_week['km']:.1f} -> {last_complete_week['km']:.1f} km entre semanas completas)."
        )
        status = "red" if weekly_spike > 50 else "yellow"
    if last_7["quality_runs"] >= 3:
        reasons.append(f"Demasiada densidad de calidad: {last_7['quality_runs']} sesiones exigentes en 7 dias.")
        status = "red"
    if last_7["avg_hr"] and last_7["avg_hr"] > 152 and last_7["avg_pace_s_per_km"] and last_7["avg_pace_s_per_km"] > 420:
        reasons.append("Rodajes recientes muestran pulso alto para ritmo facil; senal de fatiga, calor o baja eficiencia actual.")
        status = "yellow" if status == "green" else status
    if daily_signals["readiness_flag"] == "low":
        reasons.append("Garmin readiness reciente es baja; no conviene progresar carga.")
        status = "red" if status == "red" else "yellow"
    elif daily_signals["readiness_flag"] == "moderate" and status == "green":
        reasons.append("Garmin readiness reciente es intermedia; mejor consolidar antes de subir carga.")
        status = "yellow"
    if daily_signals["hrv_flag"] == "low":
        reasons.append("HRV reciente por debajo de su rango inmediato; posible señal de fatiga o recuperacion incompleta.")
        status = "yellow" if status == "green" else status
    if daily_signals["resting_hr_flag"] == "high":
        reasons.append("Resting HR reciente relativamente alta; vigilar estres o recuperacion.")
        status = "yellow" if status == "green" else status
    if daily_signals["sleep_flag"] == "poor":
        reasons.append("Garmin marca sueño reciente pobre; no conviene apretar ni buscar deuda extra de recuperación.")
        status = "yellow" if status == "green" else status
    if daily_signals["training_status_flag"] == "caution":
        reasons.append("Training status de Garmin sugiere prudencia en la carga actual.")
        status = "yellow" if status == "green" else status
    if daily_signals["running_tolerance_flag"] == "high":
        reasons.append("La relación carga aguda/crónica sale alta; conviene evitar un nuevo salto de carga.")
        status = "red" if status == "red" else "yellow"

    latest_athlete_feedback = latest_feedback_item.get("athlete_feedback", {}) if latest_feedback_item else {}
    latest_pain_level = int(latest_athlete_feedback.get("pain_level") or 0) if latest_athlete_feedback else 0
    latest_compliance = str(latest_athlete_feedback.get("compliance") or "") if latest_athlete_feedback else ""
    latest_rpe = int(latest_athlete_feedback.get("rpe") or 0) if latest_athlete_feedback else 0
    if latest_pain_level >= 4:
        reasons.append(f"Feedback subjetivo reciente con dolor {latest_pain_level}/10; conviene proteger carga.")
        status = "red"
    elif latest_pain_level == 3 and status != "red":
        reasons.append("Feedback subjetivo reciente con dolor 3/10; no conviene progresar carga.")
        status = "yellow"
    if latest_compliance == "aborted":
        reasons.append("La ultima sesion fue cortada por el atleta; hay que asumir coste alto o mala tolerancia actual.")
        status = "red"
    elif latest_compliance in {"modified", "partial"} and status == "green":
        reasons.append("La ultima sesion no se completo exactamente como estaba prescrita; mejor consolidar antes de progresar.")
        status = "yellow"
    if latest_rpe >= 9 and status == "green":
        reasons.append("La ultima sesion se percibio muy exigente (RPE alto); conviene prudencia en la siguiente decision.")
        status = "yellow"
    recent_subjective_alerts = [
        item
        for item in recent_feedback
        if int(item.get("athlete_feedback", {}).get("pain_level") or 0) >= 4
        or str(item.get("athlete_feedback", {}).get("compliance") or "") in {"aborted", "modified"}
    ]
    if len(recent_subjective_alerts) >= 2:
        reasons.append("El feedback subjetivo reciente repite señales de mala tolerancia o dolor; no toca progresar.")
        status = "red" if status == "red" else "yellow"

    active_block_name = str(context.get("active_block", {}).get("name") or "").lower()
    if "reset" in active_block_name or "consistency" in active_block_name:
        reasons.append("El bloque activo prioriza reconstruccion, consistencia y tolerancia tisular antes de ritmos agresivos.")
        if status == "green":
            action = "maintain_or_progress_carefully"

    days_to_goal_race = context.get("days_to_goal_race")
    if isinstance(days_to_goal_race, int) and 0 <= days_to_goal_race <= 14:
        reasons.append(f"La carrera objetivo esta a {days_to_goal_race} dias; la carga debe proteger frescura y ejecucion.")
        status = "yellow" if status == "green" else status

    profile_summary = context.get("response_profile", {}).get("summary", {})
    if profile_summary.get("primary_limiter") == "aerobic_durability":
        reasons.append("El limitador principal declarado sigue siendo la durabilidad aerobica; la construccion debe respetarlo.")

    default_quality_backbone = context.get("response_profile", {}).get("automation_rules", {}).get("default_quality_backbone", [])
    if default_quality_backbone:
        reasons.append("La automatizacion prioriza como backbone de calidad: " + ", ".join(default_quality_backbone[:3]) + ".")

    if status == "red":
        action = "reduce_or_replace_quality"
        recommendation = "Reducir carga inmediata: cambiar la proxima calidad por rodaje muy facil o descanso, y mantener FC capada."
    elif status == "yellow":
        action = "maintain_with_caution"
        recommendation = "Mantener estructura, pero sin subir volumen ni intensidad hasta ver 2-3 sesiones faciles estables."
    else:
        recommendation = "Mantener plan y permitir progresion pequena si el periostio sigue en 0-2/10."

    if not reasons:
        reasons.append("Sin banderas rojas objetivas en los datos locales disponibles.")

    session_guidance = derive_session_guidance(context, status, shin_pain)

    return {
        "as_of": as_of.isoformat(),
        "status": status,
        "action": action,
        "recommendation": recommendation,
        "reasons": reasons,
        "windows": {
            "last_7_days": last_7,
            "previous_7_days": prev_7,
            "last_28_days": last_28,
            "last_complete_week": last_complete_week,
            "previous_complete_week": previous_complete_week,
        },
        "volume_spike_pct": volume_spike,
        "weekly_spike_pct": weekly_spike,
        "latest_shin_entry": shin_entry,
        "latest_high_risk_review": risky_review,
        "latest_feedback": latest_feedback_item,
        "daily_signals": daily_signals,
        "session_guidance": session_guidance,
        "active_context": {
            "cycle_id": context.get("cycle", {}).get("id"),
            "active_block": context.get("active_block", {}).get("name"),
            "goal_race_name": context.get("goal_race", {}).get("name") if context.get("goal_race") else None,
            "goal_race_priority": context.get("goal_race", {}).get("priority") if context.get("goal_race") else None,
            "days_to_goal_race": context.get("days_to_goal_race"),
            "preferred_plan_columns": context.get("preferences", {}).get("weekly_plan_format", {}).get("columns", []),
            "primary_limiter": profile_summary.get("primary_limiter"),
            "default_quality_backbone": default_quality_backbone,
            "available_race_count": len(context.get("races", [])),
        },
    }


def summarize_daily(metrics: list[dict[str, Any]], as_of: date, days: int) -> dict[str, Any]:
    start = as_of - timedelta(days=days - 1)
    window = [item for item in metrics if start <= item["date"] <= as_of]
    snapshot = daily_metric_snapshot(metrics, as_of)
    return {
        "available_days": len(window),
        "latest_date": window[-1]["date"].isoformat() if window else None,
        "source": "garmin_daily" if window else "none",
        "latest_hrv": snapshot.get("hrv"),
        "latest_training_readiness": snapshot.get("training_readiness"),
        "latest_resting_heart_rate": snapshot.get("resting_heart_rate"),
        "latest_training_status": snapshot.get("training_status"),
        "latest_sleep_score": snapshot.get("sleep_score"),
        "latest_sleep_duration_s": snapshot.get("sleep_duration_s"),
    }


def render_data_quality_report(payload: dict[str, Any]) -> str:
    quality = payload["data_quality"]
    daily = payload["daily_metrics"]
    lines = [
        "# Garmin Data Quality Report",
        "",
        f"- Fecha de analisis: `{payload['as_of']}`",
        f"- Ultima actividad importada: `{quality['latest_activity_date'] or '-'}`",
        f"- Ultimo daily importado: `{quality['latest_daily_date'] or '-'}`",
        "",
        "## Cobertura",
        "",
    ]
    for key, present in quality["available"].items():
        lines.append(f"- `{key}`: `{'yes' if present else 'no'}`")
    lines.extend([
        "",
        "## Snapshot Diario Disponible",
        "",
        f"- HRV: `{fmt_float(daily.get('latest_hrv'))}`",
        f"- Training readiness: `{fmt_float(daily.get('latest_training_readiness'))}`",
        f"- Resting HR: `{fmt_float(daily.get('latest_resting_heart_rate'))}`",
        f"- Training status: `{daily.get('latest_training_status') or '-'}`",
        f"- Sleep score: `{fmt_float(daily.get('latest_sleep_score'))}`",
        "",
        "## Mejoras Sugeridas",
        "",
    ])
    for item in quality["improvements"]:
        lines.append(f"- {item}")
    if quality["missing"]:
        lines.extend(["", "## Gaps", ""])
        for item in quality["missing"]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def render_dashboard(payload: dict[str, Any]) -> str:
    decision = payload["decision"]
    gates = payload["goal_gates"]
    estimate = payload["performance_estimate"]
    last_7 = decision["windows"]["last_7_days"]
    last_28 = decision["windows"]["last_28_days"]
    last_week = decision["windows"]["last_complete_week"]
    prev_week = decision["windows"]["previous_complete_week"]
    weekly = payload["weekly_volume"][-8:]
    lines = [
        "# Athlete Status Dashboard",
        "",
        f"- Fecha de analisis: `{payload['as_of']}`",
        f"- Estado: `{decision['status']}`",
        f"- Accion recomendada: `{decision['action']}`",
        f"- Recomendacion: {decision['recommendation']}",
        "",
        "## Carga Reciente",
        "",
        f"- Ultimos 7 dias: `{last_7['km']:.1f} km`, `{last_7['runs']}` carreras, `{last_7['quality_runs']}` exigentes, tirada larga `{last_7['long_run_km']:.1f} km`.",
        f"- Ultima semana completa: `{last_week['km']:.1f} km` vs semana previa `{prev_week['km']:.1f} km` (`{pct(decision.get('weekly_spike_pct'))}`).",
        f"- Ultimos 28 dias: `{last_28['km']:.1f} km`, `{last_28['runs']}` carreras, media `{last_28['km'] / 4.0:.1f} km/sem`.",
        f"- Ritmo medio 7d: `{seconds_to_pace(last_7['avg_pace_s_per_km'])}`, FC media `{fmt_float(last_7['avg_hr'])}`.",
            f"- Ventana movil 7d vs 7d previos: `{pct(decision['volume_spike_pct'])}`.",
            "",
            "## Predictor De Marca",
            "",
            f"- Mejor 5k reciente: `{seconds_to_time(estimate['best_5k_s_90d'])}`.",
            f"- Mejor 10k reciente: `{seconds_to_time(estimate['best_10k_s_180d'])}`.",
            f"- Estimacion 10k actual: `{seconds_to_time(estimate['current_10k_estimate_s'])}`.",
            f"- Metodo: {estimate['method']}",
            "",
            "## Riesgos Detectados",
            "",
    ]
    lines.extend([f"- {reason}" for reason in decision["reasons"]])
    lines.extend(
        [
            "",
            "## Objetivo 35:00",
            "",
            f"- Estado: `{gates['status']}`",
            f"- Resumen: {gates['summary']}",
            f"- Gates cumplidos: `{gates['passed_count']}/{gates['total_gates']}`",
            "",
        ]
    )
    for gate in gates["gates"]:
        marker = "OK" if gate["passed"] else "NO"
        lines.append(f"- `{marker}` {gate['name']}: {gate['evidence']}")
    lines.extend(["", "## Volumen Semanal", ""])
    if weekly:
        for item in weekly:
            lines.append(f"- `{item['week']}`: `{item['km']:.1f} km`, `{item['runs']}` carreras, `{item['quality_runs']}` exigentes, tirada `{item['long_run_km']:.1f} km`.")
    else:
        lines.append("- Sin actividades importadas en la ventana.")
    lines.extend(
        [
            "",
            "## Datos Garmin Daily",
            "",
            f"- Dias disponibles en ventana: `{payload['daily_metrics']['available_days']}`.",
            f"- Ultimo dia diario importado: `{payload['daily_metrics']['latest_date'] or '-'}`.",
        ]
    )
    return "\n".join(lines)


def render_decision(payload: dict[str, Any]) -> str:
    decision = payload["decision"]
    lines = [
        "# Coach Decision",
        "",
        f"- Fecha de analisis: `{payload['as_of']}`",
        f"- Estado: `{decision['status']}`",
        f"- Accion: `{decision['action']}`",
        f"- Decision: {decision['recommendation']}",
        "",
        "## Motivos",
        "",
    ]
    lines.extend([f"- {reason}" for reason in decision["reasons"]])
    lines.extend(
        [
            "",
            "## Regla Operativa",
            "",
            "- `green`: se puede mantener el plan y progresar poco.",
            "- `yellow`: mantener sin subir carga; vigilar 2-3 sesiones.",
            "- `red`: reducir o sustituir calidad por rodaje muy facil/descanso.",
        ]
    )
    return "\n".join(lines)


def build_payload(as_of: date, days: int) -> dict[str, Any]:
    activities = load_activity_summaries()
    reviews = load_reviews()
    feedback_items = load_feedback()
    daily = load_daily_metrics()
    shin_entries = load_shin_entries()
    start = as_of - timedelta(days=days - 1)
    decision = build_decision(activities, reviews, feedback_items, shin_entries, as_of)
    context = active_context(as_of)
    latest_feedback_item = latest_feedback(feedback_items, as_of)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": as_of.isoformat(),
        "lookback_days": days,
        "activity_count_total": len(activities),
        "review_count_total": len(reviews),
        "decision": decision,
        "goal_gates": evaluate_goal_gates(activities, reviews, feedback_items, shin_entries, as_of),
        "performance_estimate": performance_estimate(activities, as_of),
        "weekly_volume": weekly_volume(activities, start, as_of),
        "daily_metrics": summarize_daily(daily, as_of, days),
        "data_quality": garmin_data_quality_report(daily, activities, as_of),
        "running_tolerance": load_running_tolerance(),
        "feedback_summary": {
            "available_count": len(feedback_items),
            "latest_date": latest_feedback_item["feedback_date"].isoformat() if latest_feedback_item else None,
        },
        "active_context": {
            "cycle_id": context.get("cycle", {}).get("id"),
            "active_block": context.get("active_block", {}).get("name"),
            "goal_race": context.get("goal_race"),
            "days_to_goal_race": context.get("days_to_goal_race"),
            "available_race_count": len(context.get("races", [])),
        },
    }


def main() -> None:
    args = parse_args()
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    payload = build_payload(as_of, args.days)
    if args.write:
        save_json(COACH_DECISION_JSON_PATH, payload)
        save_text(STATUS_DASHBOARD_PATH, render_dashboard(payload))
        save_text(COACH_DECISION_MD_PATH, render_decision(payload))
        save_text(GARMIN_COVERAGE_REPORT_PATH, render_data_quality_report(payload))
        write_athlete_state()
    print(json.dumps({"status": payload["decision"]["status"], "action": payload["decision"]["action"], "as_of": payload["as_of"]}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
