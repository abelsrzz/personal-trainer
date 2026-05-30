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
    if not workouts:
        warnings.append("No hay workouts fechados dentro del rango preparado.")
    bike_count = 0
    quality_count = 0
    for path in workouts:
        workout = load_yaml(path).get("workout", {})
        sport = str(workout.get("sport") or "running")
        if sport == "cycling":
            bike_count += 1
        template_id = str(workout.get("template_id") or "")
        description = str(workout.get("description") or "").lower()
        if template_id in {"tempo_continuous", "tempo_broken", "cruise_intervals", "ten_k_specific_reps", "short_intervals_vo2", "medium_intervals_vo2", "fartlek_structured"} or any(token in description for token in ["tempo", "umbral", "fartlek", "vo2", "series"]):
            quality_count += 1
    if quality_count > 2:
        warnings.append(f"Hay {quality_count} sesiones de calidad potencial; revisar densidad.")
    if bike_count == 0:
        warnings.append("No aparece ninguna sesion de bici de soporte en la semana preparada.")
    return {"ok": not errors, "warnings": warnings, "errors": errors, "bike_count": bike_count, "quality_count": quality_count, "workout_count": len(workouts)}
