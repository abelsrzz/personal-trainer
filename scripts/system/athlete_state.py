#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.system.load_progression import progression_window, weekly_training_mix
    from scripts.system.training_paces import build_training_paces
    from scripts.system.week_replanner import recommend_replan
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.load_progression import progression_window, weekly_training_mix
    from scripts.system.training_paces import build_training_paces
    from scripts.system.week_replanner import recommend_replan


ROOT = Path(__file__).resolve().parents[2]
ATHLETE_STATE_PATH = ROOT / "system" / "state" / "athlete_state.json"
PROFILE_PATH = ROOT / "athlete" / "profile.yaml"
HEALTH_PATH = ROOT / "athlete" / "health.yaml"
ZONES_PATH = ROOT / "athlete" / "zones.yaml"
SHOES_PATH = ROOT / "athlete" / "shoes.yaml"
SHIN_TRACKER_PATH = ROOT / "athlete" / "shin_tracker.yaml"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"
ACTIVE_CYCLE_PATH = ROOT / "planning" / "cycles" / "active.yaml"
WORKOUT_FAMILY_RESPONSE_PATH = ROOT / "system" / "state" / "workout_family_response.json"
GARMIN_PROFILE_PATH = ROOT / "training" / "completed" / "imports" / "garmin" / "profile" / "athlete_profile_snapshot.json"
GARMIN_ACTIVITIES_MANIFEST_PATH = ROOT / "training" / "completed" / "imports" / "garmin" / "activities" / "last_import_manifest.json"
GARMIN_DAILY_MANIFEST_PATH = ROOT / "training" / "completed" / "imports" / "garmin" / "daily" / "last_import_manifest.json"
COMPLETED_REVIEW_ROOT = ROOT / "training" / "completed" / "reviews"
POST_WORKOUT_REFRESH_STATE_PATH = ROOT / "system" / "state" / "post_workout_refresh_state.json"
WEEKLY_PLANNING_STATE_PATH = ROOT / "system" / "state" / "weekly_planning_state.json"
AUTOMATION_SAFETY_PATH = ROOT / "system" / "automation_safety.yaml"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        payload = load_json(path)
    except (json.JSONDecodeError, OSError):
        return default
    return payload


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def last_shin_entry() -> dict[str, Any] | None:
    entries = load_optional_yaml(SHIN_TRACKER_PATH).get("shin_tracker", {}).get("entries", [])
    if not isinstance(entries, list) or not entries:
        return None
    normalized = [item for item in entries if isinstance(item, dict) and item.get("date")]
    if not normalized:
        return None
    normalized.sort(key=lambda item: str(item.get("date") or ""))
    return normalized[-1]


def load_review_payloads() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(COMPLETED_REVIEW_ROOT.glob("*.analysis.json")):
        payload = load_optional_json(path, {})
        if isinstance(payload, dict):
            items.append(payload)
    return items


def load_running_activities() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted((ROOT / "training" / "completed" / "imports" / "garmin" / "activities").glob("*/summary.json")):
        payload = load_optional_json(path, {})
        if not isinstance(payload, dict):
            continue
        activity_date = str(payload.get("startTimeLocal") or "").split(" ")[0]
        items.append(
            {
                "date": datetime.strptime(activity_date, "%Y-%m-%d").date() if activity_date else None,
                "fastest_5k_s": payload.get("fastestSplit_5000"),
                "fastest_10k_s": payload.get("fastestSplit_10000"),
                "distance_km": float(payload.get("distance") or 0.0) / 1000.0,
                "duration_s": float(payload.get("duration") or payload.get("movingDuration") or 0.0),
                "pace_s_per_km": (float(payload.get("duration") or payload.get("movingDuration") or 0.0) * 1000.0 / float(payload.get("distance") or 0.0)) if float(payload.get("distance") or 0.0) else None,
                "avg_hr": payload.get("averageHR"),
            }
        )
    return items


def build_athlete_state() -> dict[str, Any]:
    profile = load_optional_yaml(PROFILE_PATH).get("athlete", {})
    health = load_optional_yaml(HEALTH_PATH).get("health", {})
    zones = load_optional_yaml(ZONES_PATH).get("zones", {})
    shoes = load_optional_yaml(SHOES_PATH).get("shoes", [])
    coach_decision = load_optional_json(COACH_DECISION_PATH, {})
    active_cycle = load_optional_yaml(ACTIVE_CYCLE_PATH).get("cycle", {})
    garmin_profile = load_optional_json(GARMIN_PROFILE_PATH, {})
    activities_manifest = load_optional_json(GARMIN_ACTIVITIES_MANIFEST_PATH, {})
    daily_manifest = load_optional_json(GARMIN_DAILY_MANIFEST_PATH, {})
    post_workout_state = load_optional_json(POST_WORKOUT_REFRESH_STATE_PATH, {})
    weekly_planning_state = load_optional_json(WEEKLY_PLANNING_STATE_PATH, {})
    workout_family_response = load_optional_json(WORKOUT_FAMILY_RESPONSE_PATH, {})
    automation_safety = load_optional_yaml(AUTOMATION_SAFETY_PATH).get("automation_safety", {})
    latest_shin = last_shin_entry()
    reviews = load_review_payloads()
    running_activities = load_running_activities()

    decision = coach_decision.get("decision", {}) if isinstance(coach_decision, dict) else {}
    goal_gates = coach_decision.get("goal_gates", {}) if isinstance(coach_decision, dict) else {}
    daily_metrics = coach_decision.get("daily_metrics", {}) if isinstance(coach_decision, dict) else {}
    data_quality = coach_decision.get("data_quality", {}) if isinstance(coach_decision, dict) else {}
    progression = progression_window(reviews, load_optional_yaml(SHIN_TRACKER_PATH).get("shin_tracker", {}).get("entries", []), as_of=datetime.now().date(), coach_status=decision.get("status"))
    hybrid_load = weekly_training_mix(reviews, until=datetime.now().date())
    pace_bands = build_training_paces(running_activities, zones, as_of=datetime.now().date())
    replanning = recommend_replan(
        coach_status=str(decision.get("status") or "green"),
        shin_band=str(progression.get("shin_status", {}).get("band") or "green"),
        risky_review=bool(progression.get("current_week", {}).get("high_risk_reviews")),
        latest_pain=progression.get("shin_status", {}).get("max_pain"),
    )

    return {
        "generated_at": utcnow_iso(),
        "source_of_truth": "system/state/athlete_state.json",
        "identity": {
            "id": profile.get("id"),
            "name": profile.get("name"),
            "birth_date": profile.get("birth_date"),
            "sex": profile.get("sex"),
            "height_cm": profile.get("height_cm"),
            "weight_kg": profile.get("weight_kg"),
        },
        "athlete": {
            "profile": profile,
            "health": health,
            "zones": zones,
            "shoes_count": len(shoes) if isinstance(shoes, list) else 0,
            "latest_shin_entry": latest_shin,
            "hybrid_training": {
                "weeks": hybrid_load[-6:],
                "latest_week": hybrid_load[-1] if hybrid_load else None,
            },
            "impact_return": progression,
            "training_paces": pace_bands,
        },
        "coach": {
            "as_of": coach_decision.get("as_of"),
            "status": decision.get("status"),
            "action": decision.get("action"),
            "recommendation": decision.get("recommendation"),
            "session_guidance": decision.get("session_guidance"),
            "goal_gates": {
                "status": goal_gates.get("status"),
                "summary": goal_gates.get("summary"),
                "passed_count": goal_gates.get("passed_count"),
                "total_gates": goal_gates.get("total_gates"),
            },
            "permissions": {
                "blocked_dimensions": progression.get("blocked_dimensions", []),
                "keep_bike_support_session": progression.get("keep_bike_support_session"),
                "fartlek_frequency": progression.get("fartlek_frequency"),
            },
            "replanning": replanning,
            "workout_family_response": workout_family_response.get("families", [])[:8] if isinstance(workout_family_response, dict) else [],
        },
        "garmin": {
            "profile_synced_at": garmin_profile.get("synced_at"),
            "latest_activity_import_at": activities_manifest.get("generated_at"),
            "latest_daily_import_at": daily_manifest.get("generated_at"),
            "latest_activity_ids": activities_manifest.get("imported_activity_ids") or [],
            "latest_daily_days": daily_manifest.get("imported_days") or [],
            "daily_metrics": {
                "latest_date": daily_metrics.get("latest_date"),
                "latest_hrv": daily_metrics.get("latest_hrv"),
                "latest_training_readiness": daily_metrics.get("latest_training_readiness"),
                "latest_resting_heart_rate": daily_metrics.get("latest_resting_heart_rate"),
                "latest_training_status": daily_metrics.get("latest_training_status"),
            },
            "data_quality": data_quality.get("available") or {},
        },
        "automation": {
            "post_workout_refresh": {
                "last_seen_activity_id": post_workout_state.get("last_seen_activity_id"),
                "last_seen_activity_date": post_workout_state.get("last_seen_activity_date"),
                "last_processed_activity_id": post_workout_state.get("last_processed_activity_id"),
                "last_processed_activity_date": post_workout_state.get("last_processed_activity_date"),
                "last_processed_at": post_workout_state.get("last_processed_at"),
                "last_successful_run": post_workout_state.get("last_successful_run"),
                "last_error": post_workout_state.get("last_error"),
                "next_action": post_workout_state.get("next_action"),
                "timer_interval_minutes": post_workout_state.get("timer_interval_minutes"),
            },
            "weekly_planning": {
                "last_plan": weekly_planning_state.get("last_plan"),
                "last_activation": weekly_planning_state.get("last_activation"),
            },
            "safety_policy": {
                "allow_auto": automation_safety.get("allow_auto") or [],
                "require_confirmation": automation_safety.get("require_confirmation") or [],
                "never_auto": automation_safety.get("never_auto") or [],
            },
        },
        "active_cycle": active_cycle,
    }


def write_athlete_state() -> dict[str, Any]:
    payload = build_athlete_state()
    write_json(ATHLETE_STATE_PATH, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(write_athlete_state(), indent=2, ensure_ascii=True, default=str))
