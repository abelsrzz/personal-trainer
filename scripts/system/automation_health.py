#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.system.capability_engine import CapabilityEngine
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.capability_engine import CapabilityEngine


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_JSON_PATH = ROOT / "system" / "state" / "automation_health.json"
OUTPUT_MD_PATH = ROOT / "system" / "state" / "automation_health.md"
POST_WORKOUT_REFRESH_STATE_PATH = ROOT / "system" / "state" / "post_workout_refresh_state.json"
WEEKLY_PLANNING_STATE_PATH = ROOT / "system" / "state" / "weekly_planning_state.json"
ATHLETE_STATE_PATH = ROOT / "system" / "state" / "athlete_state.json"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"
GARMIN_RECONCILE_STATE_PATH = ROOT / "system" / "state" / "garmin_reconcile_state.json"
TELEGRAM_NOTIFICATION_STATE_PATH = ROOT / "telegram" / "coach_notifications_state.json"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def capabilities_status() -> tuple[list[dict[str, Any]], list[str], list[str]]:
    engine = CapabilityEngine()
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    for name in sorted(engine.registry.keys()):
        state = engine._state(name)
        stale = engine._is_stale(name)
        item = {
            "name": name,
            "stale": stale,
            "last_successful_sync": state.get("last_successful_sync"),
            "last_attempted_sync": state.get("last_attempted_sync"),
            "last_error": state.get("last_error"),
        }
        results.append(item)
        if stale:
            warnings.append(f"Capability stale: {name}")
        if state.get("last_error"):
            errors.append(f"Capability error {name}: {state.get('last_error')}")
    return results, warnings, errors


def build_automation_health() -> dict[str, Any]:
    post_workout = load_optional_json(POST_WORKOUT_REFRESH_STATE_PATH, {})
    weekly = load_optional_json(WEEKLY_PLANNING_STATE_PATH, {})
    athlete_state = load_optional_json(ATHLETE_STATE_PATH, {})
    coach_decision = load_optional_json(COACH_DECISION_PATH, {})
    garmin_reconcile = load_optional_json(GARMIN_RECONCILE_STATE_PATH, {})
    telegram_notifications = load_optional_json(TELEGRAM_NOTIFICATION_STATE_PATH, {})
    capabilities, warnings, errors = capabilities_status()

    if post_workout.get("last_error"):
        errors.append(f"Post-workout refresh: {post_workout.get('last_error')}")
    last_plan = weekly.get("last_plan") if isinstance(weekly, dict) else None
    if isinstance(last_plan, dict) and last_plan.get("status") == "error":
        errors.append("Weekly planning pipeline reports last_plan=status:error")

    last_activation = weekly.get("last_activation") if isinstance(weekly, dict) else None
    if isinstance(last_activation, dict):
        pdf = last_activation.get("pdf") if isinstance(last_activation.get("pdf"), dict) else {}
        if pdf and not pdf.get("ok"):
            warnings.append("Last weekly activation could not send PDF")
    if isinstance(garmin_reconcile, dict) and garmin_reconcile and not garmin_reconcile.get("ok", True):
        errors.append(f"Garmin reconcile: {garmin_reconcile.get('message') or 'unknown error'}")

    overall_status = "ok"
    if errors:
        overall_status = "error"
    elif warnings:
        overall_status = "warning"

    summary = "Sistema operativo estable."
    if overall_status == "error":
        summary = "Hay errores operativos que requieren atencion."
    elif overall_status == "warning":
        summary = "Sistema usable con advertencias o datos potencialmente stale."

    return {
        "generated_at": utcnow_iso(),
        "overall_status": overall_status,
        "summary": summary,
        "warnings": warnings,
        "errors": errors,
        "services": {
            "post_workout_refresh": {
                "last_successful_run": post_workout.get("last_successful_run") if isinstance(post_workout, dict) else None,
                "last_processed_activity_date": post_workout.get("last_processed_activity_date") if isinstance(post_workout, dict) else None,
                "last_error": post_workout.get("last_error") if isinstance(post_workout, dict) else None,
            },
            "weekly_planning": {
                "active_week": weekly.get("active_week") if isinstance(weekly, dict) else None,
                "last_plan": last_plan,
                "last_activation": last_activation,
            },
            "coach_state": {
                "coach_as_of": coach_decision.get("as_of") if isinstance(coach_decision, dict) else None,
                "coach_status": (coach_decision.get("decision") or {}).get("status") if isinstance(coach_decision, dict) else None,
                "athlete_state_generated_at": athlete_state.get("generated_at") if isinstance(athlete_state, dict) else None,
            },
            "garmin_reconcile": {
                "generated_at": garmin_reconcile.get("generated_at") if isinstance(garmin_reconcile, dict) else None,
                "ok": garmin_reconcile.get("ok") if isinstance(garmin_reconcile, dict) else None,
                "message": garmin_reconcile.get("message") if isinstance(garmin_reconcile, dict) else None,
            },
            "telegram_notifications": {
                "last_morning_brief_date": telegram_notifications.get("last_morning_brief_date") if isinstance(telegram_notifications, dict) else None,
                "last_morning_brief_at": telegram_notifications.get("last_morning_brief_at") if isinstance(telegram_notifications, dict) else None,
                "post_workout_sent": len((telegram_notifications.get("post_workout_notifications") or {})) if isinstance(telegram_notifications, dict) else 0,
            },
        },
        "capabilities": capabilities,
    }


def health_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Automation Health",
        "",
        f"- Generated: `{payload.get('generated_at')}`",
        f"- Status: `{payload.get('overall_status')}`",
        f"- Summary: {payload.get('summary')}",
        "",
        "## Warnings",
    ]
    warnings = payload.get("warnings") or []
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- None")
    lines.extend(["", "## Errors"])
    errors = payload.get("errors") or []
    if errors:
        lines.extend(f"- {item}" for item in errors)
    else:
        lines.append("- None")
    lines.extend(["", "## Capabilities"])
    for item in payload.get("capabilities") or []:
        status = "stale" if item.get("stale") else "fresh"
        lines.append(f"- `{item.get('name')}`: `{status}`")
    return "\n".join(lines) + "\n"


def write_automation_health() -> dict[str, Any]:
    payload = build_automation_health()
    write_json(OUTPUT_JSON_PATH, payload)
    write_text(OUTPUT_MD_PATH, health_markdown(payload))
    return payload


def load_automation_health(*, build_if_missing: bool = True) -> dict[str, Any]:
    payload = load_optional_json(OUTPUT_JSON_PATH, {})
    if payload or not build_if_missing:
        return payload if isinstance(payload, dict) else {}
    return write_automation_health()


def main() -> None:
    import sys

    sys.stdout.write(json.dumps(write_automation_health(), indent=2, ensure_ascii=True) + "\n")


if __name__ == "__main__":
    main()
