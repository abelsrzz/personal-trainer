#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.system.capability_engine import CapabilityEngine, ensure_fresh
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.capability_engine import CapabilityEngine, ensure_fresh


ROOT = Path(__file__).resolve().parents[2]
CONTEXTS_DIR = ROOT / "system" / "state" / "contexts"
ATHLETE_STATE_PATH = ROOT / "system" / "state" / "athlete_state.json"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"
STATUS_DASHBOARD_PATH = ROOT / "athlete" / "status_dashboard.md"
WEEKLY_PLANNING_STATE_PATH = ROOT / "system" / "state" / "weekly_planning_state.json"
POST_WORKOUT_REFRESH_STATE_PATH = ROOT / "system" / "state" / "post_workout_refresh_state.json"
GARMIN_RECONCILE_STATE_PATH = ROOT / "system" / "state" / "garmin_reconcile_state.json"
ACTIVE_WEEK_PATH = ROOT / "planning" / "weeks" / "semana_actual.md"
PLANNED_WORKOUTS_DIR = ROOT / "training" / "planned" / "workouts"
RACES_DIR = ROOT / "races"

CONTEXT_CAPABILITIES: dict[str, list[str]] = {
    "global_context": ["athlete_state", "coach_decision"],
    "today_context": ["athlete_state", "coach_decision"],
    "planning_context": ["athlete_profile", "athlete_state", "progression_state", "training_paces", "coach_decision"],
    "replanning_context": ["athlete_state", "progression_state", "training_paces", "coach_decision"],
    "race_context": ["athlete_profile", "athlete_state", "training_paces", "coach_decision", "shoes_mileage"],
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_week_window(markdown: str) -> tuple[str | None, str | None]:
    import re

    match = re.search(r"Del `(?P<start>\d{4}-\d{2}-\d{2})` al `(?P<end>\d{4}-\d{2}-\d{2})`", markdown)
    if not match:
        return None, None
    return match.group("start"), match.group("end")


def active_week_payload() -> dict[str, Any]:
    markdown = read_text(ACTIVE_WEEK_PATH)
    start_date, end_date = parse_week_window(markdown)
    title = ""
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return {
        "title": title,
        "start_date": start_date,
        "end_date": end_date,
        "path": str(ACTIVE_WEEK_PATH.relative_to(ROOT)) if ACTIVE_WEEK_PATH.exists() else None,
    }


def prepared_weeks_payload() -> list[dict[str, Any]]:
    state = load_optional_json(WEEKLY_PLANNING_STATE_PATH, {})
    prepared = state.get("prepared_weeks") if isinstance(state, dict) else {}
    items: list[dict[str, Any]] = []
    if not isinstance(prepared, dict):
        return items
    for key in sorted(prepared.keys()):
        item = prepared.get(key)
        if isinstance(item, dict):
            items.append(item)
    return items


def upcoming_races(limit: int = 5) -> list[dict[str, Any]]:
    today = date.today()
    items: list[dict[str, Any]] = []
    for path in sorted(RACES_DIR.glob("**/*.yaml")):
        payload = load_optional_yaml(path)
        race_date = parse_iso_date(payload.get("date"))
        if not race_date or race_date < today:
            continue
        items.append(
            {
                "id": payload.get("id") or path.stem,
                "name": payload.get("name") or path.stem,
                "date": race_date.isoformat(),
                "priority": payload.get("priority"),
                "distance": payload.get("distance"),
                "path": str(path.relative_to(ROOT)),
            }
        )
    items.sort(key=lambda item: str(item.get("date") or ""))
    return items[:limit]


def planned_workouts_for_day(target_day: date) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(PLANNED_WORKOUTS_DIR.glob("*.yaml")):
        if path.name in {"library_run_templates.yaml", "workout_template.yaml"}:
            continue
        payload = load_optional_yaml(path).get("workout", {})
        workout_date = parse_iso_date(payload.get("schedule_date"))
        if workout_date != target_day:
            continue
        items.append(
            {
                "slug": path.stem,
                "name": payload.get("name") or path.stem,
                "sport": payload.get("sport") or "running",
                "description": payload.get("description") or "",
                "primary_goal": payload.get("primary_goal"),
                "path": str(path.relative_to(ROOT)),
            }
        )
    return items


def capability_results(names: list[str], *, refresh: bool) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    stale: list[str] = []
    engine = CapabilityEngine()
    for name in names:
        if refresh:
            result = ensure_fresh(name)
            attempted_refresh = result.attempted_refresh
            refreshed = result.refreshed
        else:
            config = engine.capability(name)
            state = engine._state(name)
            is_stale = engine._is_stale(name)
            warning = None
            if is_stale and str(config.get("stale_behavior") or "") == "show_cached_with_warning":
                warning = f"{name}: datos potencialmente desactualizados."
            result = type("CapabilitySnapshot", (), {"name": name, "stale": is_stale, "warning": warning, "error": state.get("last_error")})()
            attempted_refresh = False
            refreshed = False
        results.append(
            {
                "name": result.name,
                "attempted_refresh": attempted_refresh,
                "refreshed": refreshed,
                "stale": result.stale,
                "warning": result.warning,
                "error": result.error,
            }
        )
        if result.warning:
            warnings.append(result.warning)
        if result.error:
            warnings.append(f"{name}: {result.error}")
        if result.stale:
            stale.append(name)
    return {"items": results, "warnings": warnings, "stale": stale}


def build_context(name: str, *, refresh_capabilities: bool = True) -> dict[str, Any]:
    if name not in CONTEXT_CAPABILITIES:
        raise KeyError(f"Unknown context: {name}")

    capability_state = capability_results(CONTEXT_CAPABILITIES[name], refresh=refresh_capabilities)
    athlete_state = load_optional_json(ATHLETE_STATE_PATH, {})
    coach_decision = load_optional_json(COACH_DECISION_PATH, {})
    weekly_state = load_optional_json(WEEKLY_PLANNING_STATE_PATH, {})
    post_workout = load_optional_json(POST_WORKOUT_REFRESH_STATE_PATH, {})
    garmin_reconcile = load_optional_json(GARMIN_RECONCILE_STATE_PATH, {})
    today = date.today()
    races = upcoming_races(limit=8)
    race_today = next((item for item in races if item.get("date") == today.isoformat()), None)

    payload: dict[str, Any] = {
        "generated_at": utcnow_iso(),
        "context": name,
        "today": today.isoformat(),
        "warnings": capability_state["warnings"],
        "stale_capabilities": capability_state["stale"],
        "capabilities": capability_state["items"],
        "active_week": active_week_payload(),
        "prepared_weeks": prepared_weeks_payload()[:4],
        "next_races": races,
        "race_today": race_today,
        "coach": {
            "as_of": coach_decision.get("as_of") if isinstance(coach_decision, dict) else None,
            "status": (coach_decision.get("decision") or {}).get("status") if isinstance(coach_decision, dict) else None,
            "action": (coach_decision.get("decision") or {}).get("action") if isinstance(coach_decision, dict) else None,
            "recommendation": (coach_decision.get("decision") or {}).get("recommendation") if isinstance(coach_decision, dict) else None,
        },
        "athlete_state": athlete_state,
        "automation": {
            "weekly_planning": {
                "last_plan": weekly_state.get("last_plan") if isinstance(weekly_state, dict) else None,
                "last_activation": weekly_state.get("last_activation") if isinstance(weekly_state, dict) else None,
            },
            "post_workout_refresh": {
                "last_successful_run": post_workout.get("last_successful_run") if isinstance(post_workout, dict) else None,
                "last_error": post_workout.get("last_error") if isinstance(post_workout, dict) else None,
                "last_processed_activity_date": post_workout.get("last_processed_activity_date") if isinstance(post_workout, dict) else None,
            },
            "garmin_reconcile": {
                "generated_at": garmin_reconcile.get("generated_at") if isinstance(garmin_reconcile, dict) else None,
                "ok": garmin_reconcile.get("ok") if isinstance(garmin_reconcile, dict) else None,
                "message": garmin_reconcile.get("message") if isinstance(garmin_reconcile, dict) else None,
            },
        },
    }

    if name == "today_context":
        payload["today_plan"] = {
            "workouts": planned_workouts_for_day(today),
            "race": race_today,
            "dashboard_excerpt": read_text(STATUS_DASHBOARD_PATH).splitlines()[:8],
        }
    elif name == "planning_context":
        payload["planning"] = {
            "default_running_growth_pct": ((athlete_state.get("athlete") or {}).get("impact_return") or {}).get("default_running_growth_pct"),
            "next_running_target_range_km": ((athlete_state.get("athlete") or {}).get("impact_return") or {}).get("next_running_target_range_km"),
            "blocked_dimensions": ((athlete_state.get("coach") or {}).get("permissions") or {}).get("blocked_dimensions"),
        }
    elif name == "replanning_context":
        payload["replanning"] = ((athlete_state.get("coach") or {}).get("replanning") or {})
    elif name == "race_context":
        payload["race"] = race_today or (races[0] if races else None)

    return payload


def context_path(name: str) -> Path:
    return CONTEXTS_DIR / f"{name}.json"


def write_context(name: str, *, refresh_capabilities: bool = True) -> dict[str, Any]:
    payload = build_context(name, refresh_capabilities=refresh_capabilities)
    write_json(context_path(name), payload)
    return payload


def write_all_contexts(*, refresh_capabilities: bool = True) -> dict[str, dict[str, Any]]:
    return {name: write_context(name, refresh_capabilities=refresh_capabilities) for name in CONTEXT_CAPABILITIES}


def load_context_artifact(name: str, *, build_if_missing: bool = True) -> dict[str, Any]:
    path = context_path(name)
    payload = load_optional_json(path, {})
    if payload or not build_if_missing:
        return payload if isinstance(payload, dict) else {}
    return write_context(name, refresh_capabilities=False)


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Build AI/web operational contexts")
    parser.add_argument("context", choices=[*CONTEXT_CAPABILITIES.keys(), "all"], help="Context artifact to generate")
    parser.add_argument("--skip-refresh", action="store_true", help="Do not refresh capabilities before building the context")
    args = parser.parse_args()
    if args.context == "all":
        payload: Any = write_all_contexts(refresh_capabilities=not args.skip_refresh)
    else:
        payload = write_context(args.context, refresh_capabilities=not args.skip_refresh)
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


if __name__ == "__main__":
    main()
