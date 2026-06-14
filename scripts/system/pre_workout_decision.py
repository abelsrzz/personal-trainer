#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ATHLETE_STATE_PATH = ROOT / "system" / "state" / "athlete_state.json"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"


def load_today_feed_runtime() -> dict[str, Any]:
    try:
        from scripts.system.today_feed import load_today_feed
    except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
        import sys

        sys.path.append(str(Path(__file__).resolve().parents[2]))
        from scripts.system.today_feed import load_today_feed
    return load_today_feed(build_if_missing=True)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def max_shin_pain(athlete_state: dict[str, Any], coach_decision: dict[str, Any]) -> int | None:
    athlete_entry = ((athlete_state.get("athlete") or {}).get("latest_shin_entry") or {}) if isinstance(athlete_state, dict) else {}
    coach_entry = ((coach_decision.get("decision") or {}).get("latest_shin_entry") or {}) if isinstance(coach_decision, dict) else {}
    values: list[int] = []
    for entry in (athlete_entry, coach_entry):
        if not isinstance(entry, dict):
            continue
        for key in ("pain_during", "pain_after", "pain_next_morning"):
            if entry.get(key) is not None:
                values.append(int(entry.get(key) or 0))
    return max(values) if values else None


def quality_like(workout: dict[str, Any]) -> bool:
    text = " ".join(
        str(workout.get(key) or "")
        for key in ("session_kind", "session_kind_label", "name", "description", "primary_goal", "knowledge_label")
    ).lower()
    markers = ("tempo", "interval", "series", "fartlek", "quality", "umbral", "ritmo", "specific", "especific")
    return any(marker in text for marker in markers)


def build_pre_workout_decision(day: str | None = None) -> dict[str, Any]:
    today = str(day or date.today().isoformat())
    today_feed = load_today_feed_runtime()
    athlete_state = load_json(ATHLETE_STATE_PATH)
    coach_decision = load_json(COACH_DECISION_PATH)
    decision = coach_decision.get("decision", {}) if isinstance(coach_decision.get("decision"), dict) else {}
    workout = today_feed.get("today_workout") if isinstance(today_feed.get("today_workout"), dict) else None
    review = today_feed.get("today_review") if isinstance(today_feed.get("today_review"), dict) else None
    progression = ((athlete_state.get("athlete") or {}).get("impact_return") or {}) if isinstance(athlete_state, dict) else {}
    latest_daily = ((athlete_state.get("garmin") or {}).get("daily_metrics") or {}) if isinstance(athlete_state, dict) else {}
    coach_status = str(decision.get("status") or "green").strip().lower()
    readiness = latest_daily.get("latest_training_readiness")
    readiness_flag = str((((decision.get("daily_signals") or {}).get("readiness_flag")) or "")).strip().lower()
    shin_pain = max_shin_pain(athlete_state, coach_decision)

    if review and str(review.get("date") or "") == today:
        return {
            "date": today,
            "action": "already_done",
            "summary": "La sesion de hoy ya figura como completada.",
            "before_training": ["No hace falta decision pre-entreno adicional hoy."],
            "stop_if": [],
            "fallback": "Revisa la recuperacion y deja feedback si falta.",
            "workout": workout,
            "review": review,
            "coach_status": coach_status,
            "shin_pain": shin_pain,
            "readiness": readiness,
        }

    if not workout:
        return {
            "date": today,
            "action": "rest_or_optional",
            "summary": "Hoy no aparece una sesion planificada obligatoria.",
            "before_training": ["Si haces algo, que sea facil y sin coste oculto."],
            "stop_if": ["Corta si aparece dolor tibial o fatiga rara desde el inicio."],
            "fallback": "Movilidad, paseo o descanso.",
            "workout": None,
            "review": review,
            "coach_status": coach_status,
            "shin_pain": shin_pain,
            "readiness": readiness,
        }

    action = "go"
    summary = "Puedes hacer la sesion prevista segun el plan actual."
    fallback = "Mantener la sesion, con control tecnico y sin regalar intensidad extra."
    before_training = [
        "Haz un check rapido de tibia, piernas y sensacion general antes de salir.",
        "Empieza conservador y deja que el cuerpo confirme el plan, no al reves.",
    ]
    stop_if = [
        "Para o cambia a facil si la tibia pasa de 2/10 o cambia la mecanica.",
        "Recorta si el calentamiento ya sale mas duro de lo normal.",
    ]
    is_quality = quality_like(workout)
    blocked = progression.get("blocked_dimensions") or []

    if coach_status == "red" or (shin_pain is not None and shin_pain >= 4):
        action = "bike_or_rest"
        summary = "Hoy no conviene asumir coste de carrera o calidad. Prioriza descarga y proteccion." 
        fallback = "Sustituye por bici suave, movilidad o descanso completo."
    elif readiness_flag == "low" or (readiness is not None and float(readiness) < 35):
        action = "swap_to_lower_cost" if is_quality else "go_but_reduce"
        summary = "La readiness reciente es baja; mejor bajar el coste de la sesion de hoy."
        fallback = "Reduce volumen, quita calidad o cambia a rodaje muy facil/bici."
    elif coach_status == "yellow" or (shin_pain is not None and shin_pain == 3) or "running_progression" in blocked:
        action = "swap_to_lower_cost" if is_quality else "go_but_reduce"
        summary = "Toca prudencia: mantén la estructura sin progresar carga ni intensidad."
        fallback = "Mantener estimulo, pero con variante mas facil o menos volumen."
    elif progression.get("baseline_running_km") == 0 and str(workout.get("session_kind") or "").lower() == "running":
        action = "go_but_reduce"
        summary = "Sigues en reintroduccion al impacto; la prioridad es tolerar bien el paso de hoy."
        fallback = "Trata la sesion como un escalon de vuelta a correr, no como un dia para apretar."

    return {
        "date": today,
        "action": action,
        "summary": summary,
        "before_training": before_training,
        "stop_if": stop_if,
        "fallback": fallback,
        "workout": workout,
        "review": review,
        "coach_status": coach_status,
        "shin_pain": shin_pain,
        "readiness": readiness,
        "readiness_flag": readiness_flag,
        "blocked_dimensions": blocked,
    }


def format_pre_workout_decision(payload: dict[str, Any]) -> str:
    workout = payload.get("workout") if isinstance(payload.get("workout"), dict) else {}
    lines = [
        f"Pre-entreno {payload.get('date')}",
        f"Decision: {payload.get('action')}",
        f"Resumen: {payload.get('summary')}",
    ]
    if workout:
        lines.append(f"Sesion: {workout.get('name') or workout.get('session_kind_label') or workout.get('slug')}")
    if payload.get("coach_status"):
        lines.append(f"Coach: {payload.get('coach_status')}")
    if payload.get("readiness") is not None:
        lines.append(f"Readiness: {payload.get('readiness')}")
    if payload.get("shin_pain") is not None:
        lines.append(f"Tibia max: {payload.get('shin_pain')}/10")
    before_training = payload.get("before_training") or []
    if before_training:
        lines.append("Antes:")
        lines.extend(f"- {item}" for item in before_training)
    stop_if = payload.get("stop_if") or []
    if stop_if:
        lines.append("Parar o cambiar si:")
        lines.extend(f"- {item}" for item in stop_if)
    if payload.get("fallback"):
        lines.append(f"Plan B: {payload.get('fallback')}")
    return "\n".join(lines)


def main() -> None:
    payload = build_pre_workout_decision()
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
