#!/usr/bin/env python3

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]


def parse_week_window(markdown: str) -> tuple[str | None, str | None]:
    match = re.search(r"Del `(?P<start>\d{4}-\d{2}-\d{2})` al `(?P<end>\d{4}-\d{2}-\d{2})`", markdown)
    if not match:
        return None, None
    return match.group("start"), match.group("end")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def workout_distance_km(workout: dict[str, Any]) -> float:
    distance = float(workout.get("distance_m") or 0.0)
    if distance <= 0:
        for step in workout.get("steps") or []:
            if isinstance(step, dict):
                distance += float(step.get("distance_m") or 0.0)
    return distance / 1000.0


def workout_has_executable_steps(workout: dict[str, Any]) -> bool:
    steps = workout.get("steps") or []
    if not steps:
        return False
    for step in steps:
        if not isinstance(step, dict):
            return False
        if step.get("type") == "repeat_group":
            nested = step.get("steps") or []
            if not nested or not all(isinstance(item, dict) for item in nested):
                return False
            continue
        if not any(step.get(key) is not None for key in ("duration_s", "distance_m", "repetitions")):
            return False
    return True


def workout_files_for_range(start_date: str, end_date: str) -> list[Path]:
    items: list[Path] = []
    for path in sorted((ROOT / "training" / "planned" / "workouts").glob("*.yaml")):
        if path.name in {"library_run_templates.yaml", "workout_template.yaml"}:
            continue
        workout = load_yaml(path).get("workout", {})
        schedule_date = str(workout.get("schedule_date") or "")
        if start_date <= schedule_date <= end_date:
            items.append(path)
    return items


def validate_prepared_week(week_path: Path) -> dict[str, Any]:
    markdown = week_path.read_text(encoding="utf-8") if week_path.exists() else ""
    start_date, end_date = parse_week_window(markdown)
    warnings: list[str] = []
    errors: list[str] = []
    if not start_date or not end_date:
        errors.append("No se pudo leer el rango lunes-domingo de la semana preparada.")
        return {"ok": False, "warnings": warnings, "errors": errors}
    workouts = workout_files_for_range(start_date, end_date)
    athlete_state = load_json(ROOT / "system" / "state" / "athlete_state.json")
    coach_decision = load_json(ROOT / "planning" / "coach_decision.json")
    coach_status = str(((coach_decision.get("decision") or {}).get("status") or (athlete_state.get("coach") or {}).get("status") or "")).lower()
    blocked_dimensions = set(((athlete_state.get("coach") or {}).get("permissions") or {}).get("blocked_dimensions") or [])
    next_range = ((athlete_state.get("athlete") or {}).get("impact_return") or {}).get("next_running_target_range_km") or {}
    running_km = 0.0
    if not workouts:
        warnings.append("No hay workouts fechados dentro del rango preparado.")
    bike_count = 0
    quality_count = 0
    for path in workouts:
        workout = load_yaml(path).get("workout", {})
        sport = str(workout.get("sport") or "running")
        schedule_date = str(workout.get("schedule_date") or "")
        if schedule_date and not (start_date <= schedule_date <= end_date):
            errors.append(f"{path.name}: schedule_date fuera del rango semanal.")
        if not workout_has_executable_steps(workout):
            warnings.append(f"{path.name}: pasos no ejecutables o ausentes para Garmin.")
        if sport == "cycling":
            bike_count += 1
        if sport in {"running", "trail_running"}:
            running_km += workout_distance_km(workout)
        template_id = str(workout.get("template_id") or "")
        description = str(workout.get("description") or "").lower()
        if template_id in {"tempo_continuous", "tempo_broken", "cruise_intervals", "ten_k_specific_reps", "short_intervals_vo2", "medium_intervals_vo2", "fartlek_structured"} or any(token in description for token in ["tempo", "umbral", "fartlek", "vo2", "series"]):
            quality_count += 1
    if quality_count > 2:
        errors.append(f"Hay {quality_count} sesiones de calidad potencial; maximo operativo 2.")
    if bike_count == 0:
        warnings.append("No aparece ninguna sesion de bici de soporte en la semana preparada.")
    if coach_status == "yellow" and running_km > float(next_range.get("max") or 0.0) and "running_progression" in blocked_dimensions:
        errors.append(f"Coach yellow bloquea progresion running, pero la semana planifica {running_km:.1f} km (> {float(next_range.get('max') or 0.0):.1f}).")
    if coach_status == "red" and quality_count > 0:
        errors.append("Coach red no permite sesiones de calidad running.")
    return {"ok": not errors, "warnings": warnings, "errors": errors, "bike_count": bike_count, "quality_count": quality_count, "running_km": round(running_km, 1), "workout_count": len(workouts)}
