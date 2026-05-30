#!/usr/bin/env python3

from __future__ import annotations

from typing import Any


def recommend_replan(*, coach_status: str, shin_band: str, risky_review: bool, latest_pain: int | None, next_workouts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    summary = "Mantener estructura."
    reason = "Sin disparadores fuertes."
    if coach_status == "red" or shin_band == "red" or risky_review or (latest_pain is not None and latest_pain >= 4):
        summary = "Reducir o sustituir calidad inmediata."
        reason = "Riesgo alto, dolor o proteccion del coach."
        actions = [
            {"type": "replace_quality", "with": "bike_support_or_recovery"},
            {"type": "hold_running_progression"},
            {"type": "keep_bike_support"},
        ]
    elif coach_status == "yellow" or shin_band == "yellow" or (latest_pain is not None and latest_pain == 3):
        summary = "Mantener sin progresar y proteger el siguiente dia de calidad."
        reason = "Cautela por dolor o absorcion parcial."
        actions = [
            {"type": "hold_running_progression"},
            {"type": "convert_second_quality_to_easy_or_bike"},
        ]
    if next_workouts:
        for workout in next_workouts[:2]:
            sport = str(workout.get("sport") or "running")
            if sport == "running" and any(action["type"] == "replace_quality" for action in actions):
                workout["replan_hint"] = "first_running_quality_is_replaceable"
    return {"summary": summary, "reason": reason, "actions": actions, "next_workouts": next_workouts or []}
