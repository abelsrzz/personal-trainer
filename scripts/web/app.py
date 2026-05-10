#!/usr/bin/env python3

from __future__ import annotations

import json
import calendar
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from scripts.system.capability_engine import ensure_fresh
from starlette.middleware.sessions import SessionMiddleware


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "web" / "templates"
STATIC_DIR = ROOT / "web" / "static"
PLANNED_WORKOUTS_DIR = ROOT / "training" / "planned" / "workouts"
COMPLETED_REVIEW_DIR = ROOT / "training" / "completed" / "reviews"
GARMIN_ACTIVITY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
GARMIN_DAILY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "daily"
RACES_DIR = ROOT / "races"
MASTER_PLAN_PATH = ROOT / "planning" / "master_plan.md"
ACTIVE_CYCLE_PATH = ROOT / "planning" / "cycles" / "active.yaml"
WEB_CONFIG_PATH = ROOT / "web" / "web_config.yaml"
WEB_LOG_PATH = ROOT / "web" / "web_debug.log"
ACTIVE_WEEK_PATH = ROOT / "planning" / "weeks" / "semana_actual.md"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"


logger = logging.getLogger("running_coach_web")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(WEB_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def env_config() -> dict[str, Any]:
    file_config = load_optional_yaml(WEB_CONFIG_PATH).get("web", {})
    username = str(os.getenv("RUNNING_WEB_USERNAME") or file_config.get("username") or "").strip()
    password = str(os.getenv("RUNNING_WEB_PASSWORD") or file_config.get("password") or "").strip()
    secret = str(os.getenv("RUNNING_WEB_SECRET") or file_config.get("secret") or "change-this-session-secret").strip()
    return {
        "username": username,
        "password": password,
        "configured": bool(username and password),
        "secret": secret,
        "config_path": str(WEB_CONFIG_PATH.relative_to(ROOT)),
    }


app = FastAPI(title="RunPilot")
app.add_middleware(SessionMiddleware, secret_key=env_config()["secret"], same_site="lax")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def strip_markdown_ticks(value: Any) -> str:
    return str(value or "").strip().strip("`")


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def format_duration(seconds: float | int | None) -> str:
    if not seconds:
        return "-"
    total = int(round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(seconds: float | int | None) -> str:
    if not seconds:
        return "-"
    total = int(round(float(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}/km"


def format_datetime(value: str | None) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M")


def iso_date_string(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def month_label(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError:
        return value
    return parsed.strftime("%B %Y").capitalize()


def day_label(value: str) -> str:
    parsed = parse_iso_date(value)
    if not parsed:
        return value
    names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    return f"{names[parsed.weekday()]} {parsed.day:02d}/{parsed.month:02d}/{parsed.year}"


def active_cycle_data() -> dict[str, Any]:
    payload = load_optional_yaml(ACTIVE_CYCLE_PATH).get("cycle", {})
    return payload if isinstance(payload, dict) else {}


def workspace_status() -> dict[str, Any]:
    checks = [
        {
            "key": "athlete_profile",
            "label": "Perfil estructurado",
            "path": "athlete/profile.yaml",
            "required": True,
            "exists": (ROOT / "athlete" / "profile.yaml").exists(),
            "purpose": "Guardar los datos base del atleta.",
        },
        {
            "key": "races",
            "label": "Carreras cargadas",
            "path": "races/**/*.yaml",
            "required": False,
            "exists": any(RACES_DIR.glob("**/*.yaml")),
            "purpose": "Definir objetivos de carrera cuando existan.",
        },
        {
            "key": "master_plan",
            "label": "Plan general",
            "path": "planning/master_plan.md",
            "required": True,
            "exists": MASTER_PLAN_PATH.exists(),
            "purpose": "Describir la estrategia global del ciclo.",
        },
        {
            "key": "active_week",
            "label": "Semana activa",
            "path": "planning/weeks/semana_actual.md",
            "required": True,
            "exists": ACTIVE_WEEK_PATH.exists(),
            "purpose": "Mostrar la semana operativa actual.",
        },
        {
            "key": "coach_decision",
            "label": "Decision del coach",
            "path": "planning/coach_decision.json",
            "required": False,
            "exists": COACH_DECISION_PATH.exists(),
            "purpose": "Activar dashboard analitico y decision automatica.",
        },
    ]
    missing_required = [item for item in checks if item["required"] and not item["exists"]]
    missing_optional = [item for item in checks if not item["required"] and not item["exists"]]
    return {
        "ready": not missing_required,
        "checks": checks,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "messages": [
            "El proyecto aun no esta completamente preparado para consulta operativa." if missing_required else "La base minima del proyecto ya esta lista.",
            "Cuando exista `planning/coach_decision.json`, el dashboard mostrara tambien analisis automatizado." if not missing_required else "Faltan algunos archivos base para activar toda la capa operativa.",
        ],
    }


def empty_dashboard_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "as_of": None,
        "lookback_days": None,
        "capability_messages": status["messages"],
        "decision": {
            "status": "unknown",
            "status_label": "Proyecto incompleto",
            "action_label": "Completa los archivos operativos base",
            "recommendation": "La web esta funcionando, pero todavia faltan archivos minimos para mostrar la capa operativa completa.",
            "reasons": [f"Falta `{item['path']}`" for item in status["missing_required"]],
            "windows": {
                "last_7_days": {"km": 0.0, "runs": 0, "quality_runs": 0},
                "last_28_days": {"long_run_km": 0.0, "runs": 0},
            },
            "session_guidance": {"primary_labels": [], "avoid_labels": [], "optional_labels": [], "quality_volume_cap": None},
            "latest_injury_entry": None,
        },
        "goal_gates": {
            "status": "unsupported_now",
            "status_label": "Sin evaluacion disponible",
            "summary": "Los checkpoints del objetivo apareceran cuando exista plan y decision automatica.",
            "passed_count": 0,
            "total_gates": 0,
            "metrics": {"latest_injury_pain": None},
            "gates": [],
        },
        "active_context": {"active_block": None, "days_to_goal_race": None, "goal_race": None},
        "performance_estimate": {"current_10k_estimate_s": None, "method": "Sin datos suficientes"},
        "daily_metrics": {"latest_hrv": None, "latest_training_readiness": None, "latest_resting_heart_rate": None},
        "weekly_volume": [],
    }


def garmin_activity_url(activity_id: int | str | None) -> str | None:
    if not activity_id:
        return None
    activity_id = str(activity_id).strip()
    if not activity_id.isdigit():
        return None
    return f"https://connect.garmin.com/modern/activity/{activity_id}"


def garmin_workout_type(sport: str | None) -> str:
    normalized = str(sport or "running").strip().lower()
    return {
        "running": "running",
        "strength": "other",
        "fitness_equipment": "other",
        "mobility": "other",
        "stretching": "other",
        "other": "other",
    }.get(normalized, "other")


def garmin_workout_url(workout_id: int | str | None, sport: str | None = None) -> str | None:
    if not workout_id:
        return None
    workout_id = str(workout_id).strip()
    if not workout_id.isdigit():
        return None
    workout_type = garmin_workout_type(sport)
    return f"https://connect.garmin.com/app/workout/{workout_id}?workoutType={workout_type}"


def garmin_scheduled_workout_url(workout_schedule_id: int | str | None) -> str | None:
    if not workout_schedule_id:
        return None
    workout_schedule_id = str(workout_schedule_id).strip()
    if not workout_schedule_id.isdigit():
        return None
    return f"https://connect.garmin.com/modern/calendar/{workout_schedule_id}"


def decision_status_label(value: str | None) -> str:
    return {
        "green": "Buen momento para seguir construyendo",
        "yellow": "Conviene ir con prudencia",
        "red": "Hace falta bajar la carga",
    }.get(str(value or "").lower(), "Estado no disponible")


def decision_action_label(value: str | None) -> str:
    return {
        "maintain_or_progress_carefully": "Mantener la línea actual con una progresión pequeña y controlada",
        "maintain_with_caution": "Mantener la estructura sin subir carga",
        "reduce_or_replace_quality": "Reducir exigencia y priorizar recuperación",
    }.get(str(value or "").lower(), "Sin acción definida")


def goal_status_label(value: str | None) -> str:
    return {
        "unsupported_now": "Aún es pronto para orientar el entrenamiento a ese objetivo",
        "development_needed": "La base mejora, pero todavía falta desarrollo",
        "aggressive_alive": "El objetivo sigue vivo si la progresión se consolida",
        "35_ready": "El objetivo ya puede influir en la estrategia",
    }.get(str(value or "").lower(), "Sin evaluación disponible")


def traffic_light_label(value: str | None) -> str:
    return {
        "verde": "Verde",
        "amarillo": "Amarillo",
        "rojo": "Rojo",
    }.get(str(value or "").lower(), str(value or "-"))


def risk_level_label(value: str | None) -> str:
    return {
        "bajo": "Bajo",
        "medio": "Medio",
        "alto": "Alto",
    }.get(str(value or "").lower(), str(value or "-"))


def priority_label(value: str | None) -> str:
    return {
        "S": "Objetivo principal",
        "A": "Muy importante",
        "B": "Importante",
        "C": "Secundaria",
        "D": "Complementaria",
    }.get(str(value or "").upper(), str(value or "-"))


def normalize_text(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).strip().lower()


def flatten_workout_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        flat_steps.append(step)
        nested_steps = step.get("steps") or []
        if isinstance(nested_steps, list):
            flat_steps.extend(flatten_workout_steps(nested_steps))
    return flat_steps


def classify_session_kind(name_text: str, description_text: str, step_text: str, distance_km: float | None = None, steps: list[dict[str, Any]] | None = None) -> str:
    race_markers = {"competición", "competicion", "race day", "tune-up", "pre-carrera", "shakeout pre-carrera"}
    easy_markers = {"rodaje", "fácil", "facil", "suave", "easy", "continuidad", "z2", "cómodo", "comodo"}
    recovery_markers = {"recuperación", "recuperacion", "recovery", "reintroducción", "reintroduccion"}
    quality_name_markers = {"activación", "activacion", "ritmo carrera", "series", "umbral", "tempo", "específica", "especifica", "cuestas"}
    quality_step_markers = {"ritmo objetivo", "pace_range", "tempo", "series", "cuestas", "controlados"}

    full_text = normalize_text(name_text, description_text, step_text)
    name_text = normalize_text(name_text)
    description_text = normalize_text(description_text)
    flat_steps = flatten_workout_steps(steps or [])

    if any(keyword in full_text for keyword in {"descanso", "rest"}):
        return "rest"
    if any(keyword in full_text for keyword in race_markers):
        return "race"
    if any(keyword in full_text for keyword in {"fuerza", "strength", "gimnasio", "gymnasio"}):
        return "strength"
    if any(keyword in name_text or keyword in description_text for keyword in recovery_markers):
        return "recovery"
    if any(keyword in full_text for keyword in {"tirada larga", "long run", "tirada"}):
        return "long_run"
    if distance_km and distance_km >= 14:
        return "long_run"

    has_quality_name = any(keyword in name_text for keyword in quality_name_markers)
    has_quality_steps = any(keyword in step_text for keyword in quality_step_markers)
    repeat_groups = sum(1 for step in flat_steps if step.get("type") == "repeat_group" or step.get("type") == "RepeatGroupDTO")
    interval_blocks = sum(1 for step in flat_steps if str(step.get("step_type") or step.get("stepType", {}).get("stepTypeKey") or "").lower() == "interval")
    recovery_blocks = sum(1 for step in flat_steps if str(step.get("step_type") or step.get("stepType", {}).get("stepTypeKey") or "").lower() == "recovery")
    easy_base = any(keyword in name_text for keyword in easy_markers) or any(keyword in description_text for keyword in easy_markers)
    has_only_light_strides = "recta" in full_text and easy_base and not has_quality_name and not has_quality_steps

    if has_only_light_strides:
        return "recovery" if any(keyword in full_text for keyword in recovery_markers) else "easy"

    if has_quality_name:
        return "quality"
    if has_quality_steps and (repeat_groups > 0 or interval_blocks >= 2):
        return "quality"
    if interval_blocks > 1 and recovery_blocks > 0 and not easy_base:
        return "quality"
    if easy_base:
        return "easy"
    return "other"


def session_kind_label(value: str) -> str:
    return {
        "easy": "Rodaje suave",
        "recovery": "Recuperación",
        "quality": "Calidad",
        "long_run": "Tirada larga",
        "strength": "Fuerza",
        "race": "Competición",
        "rest": "Descanso",
        "other": "Otra sesión",
    }.get(value, "Otra sesión")


def session_color_class(value: str) -> str:
    return f"session-{value if value else 'other'}"


def classify_planned_workout(payload: dict[str, Any]) -> tuple[str, str, str]:
    steps = payload.get("steps") or []
    distance_m = payload.get("distance_m")
    if not distance_m:
        distance_m = sum(float(step.get("distance_m") or 0.0) for step in steps if isinstance(step, dict))
    name_text = str(payload.get("name") or "")
    description_text = str(payload.get("description") or "")
    step_text = json.dumps(steps, ensure_ascii=False)
    kind = classify_session_kind(name_text, description_text, step_text, float(distance_m) / 1000.0 if distance_m else None, steps)
    return kind, session_kind_label(kind), session_color_class(kind)


def classify_completed_review(payload: dict[str, Any]) -> tuple[str, str, str]:
    planned = payload.get("planned", {})
    summary = payload.get("summary", {})
    goal_category = normalize_text(planned.get("goal_category"))
    distance_km = round(float(summary.get("distance_m") or 0.0) / 1000.0, 2) if summary.get("distance_m") else None
    if any(keyword in goal_category for keyword in {"recovery", "reintroduction"}):
        kind = "recovery"
    elif any(keyword in goal_category for keyword in {"easy", "steady_easy", "easy_aerobic"}):
        kind = "easy"
    elif any(keyword in goal_category for keyword in {"tempo", "threshold", "specific", "quality"}):
        kind = "quality"
    else:
        kind = classify_session_kind(
            str(planned.get("name") or summary.get("activity_name") or ""),
            str(planned.get("description") or ""),
            json.dumps(payload.get("splits") or [], ensure_ascii=False),
            distance_km,
            [],
        )
    return kind, session_kind_label(kind), session_color_class(kind)


def day_status_label(planned_items: list[dict[str, Any]], completed_items: list[dict[str, Any]], reviews: list[dict[str, Any]], races: list[dict[str, Any]]) -> str:
    if races:
        return "Carrera"
    if reviews:
        return "Revisado"
    if planned_items and completed_items:
        return "Planificado y completado"
    if completed_items:
        return "Completado"
    if planned_items:
        return "Solo planificado"
    return "Descanso"


def event_status(event: dict[str, Any]) -> str:
    if event.get("race"):
        return "race_day"
    if event.get("review"):
        return "reviewed"
    if event.get("planned_workout") and event.get("completed_review"):
        return "matched_completed"
    if event.get("completed_review"):
        return "completed_unplanned"
    if event.get("planned_workout"):
        return "planned_only"
    return "rest_day"


def event_status_label(value: str) -> str:
    return {
        "planned_only": "Planificado",
        "completed_unplanned": "Hecho sin plan enlazado",
        "matched_completed": "Plan y ejecución",
        "reviewed": "Revisado",
        "race_day": "Carrera",
        "rest_day": "Descanso",
    }.get(value, "Sin estado")


def event_matches_filters(event: dict[str, Any], kind: str, status: str) -> bool:
    if kind != "all" and event.get("kind") != kind:
        return False
    if status != "all" and event.get("status") != status:
        return False
    return True


def traffic_light_class(value: str | None) -> str:
    normalized = str(value or "").lower()
    return {
        "verde": "status-green",
        "amarillo": "status-yellow",
        "rojo": "status-red",
    }.get(normalized, "")


templates.env.filters["format_duration"] = format_duration
templates.env.filters["format_pace"] = format_pace


def authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def auth_guard(request: Request) -> RedirectResponse | None:
    if authenticated(request):
        return None
    return RedirectResponse(url="/login", status_code=303)


def template_context(request: Request, **values: Any) -> dict[str, Any]:
    config = env_config()
    context = {
        "request": request,
        "portal_configured": config["configured"],
        "authenticated": authenticated(request),
        "today": date.today().isoformat(),
        "current_path": request.url.path,
    }
    context.update(values)
    return context


def parse_week_table(content: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in content.splitlines():
        if not line.startswith("|"):
            continue
        if line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] == "Dia":
            continue
        rows.append(
            {
                "day": cells[0],
                "description": cells[1],
                "distance": cells[2],
                "target": cells[3],
                "shoes": cells[4],
            }
        )
    return rows


def week_page_data() -> dict[str, Any]:
    path = ACTIVE_WEEK_PATH
    content = read_text(path)
    return {
        "exists": path.exists(),
        "content": content,
        "rows": parse_week_table(content),
        "pdf_exists": (ROOT / "planning" / "weeks" / "generated" / "semana_actual.pdf").exists(),
    }


def planned_upload_data(workout_stem: str, schedule_date: str) -> dict[str, Any]:
    upload_path = PLANNED_WORKOUTS_DIR / schedule_date / f"{workout_stem}.garmin_upload.json"
    return load_json(upload_path) if upload_path.exists() else {}


def dashboard_payload() -> dict[str, Any]:
    status = workspace_status()
    if not COACH_DECISION_PATH.exists():
        return empty_dashboard_payload(status)
    decision_capability = ensure_fresh("coach_decision")
    path = COACH_DECISION_PATH
    payload = load_json(path) if path.exists() else {}
    payload["capability_messages"] = [message for message in [decision_capability.warning] if message]

    session_family_labels = {
        "easy_recovery": "Rodaje de recuperacion",
        "recovery_plus_mobility": "Recuperacion con movilidad",
        "easy_z2": "Rodaje aerobico Z2",
        "easy_plus_strides": "Rodaje facil con rectas",
        "technique_drills_strides": "Tecnica y rectas",
        "aerobic_steady": "Aerobico sostenido",
        "cruise_intervals": "Cruise intervals",
        "tempo_continuous": "Tempo continuo",
        "tempo_broken": "Tempo fraccionado",
        "short_intervals_economy": "Series cortas de economia",
        "short_intervals_vo2": "Series cortas VO2max",
        "medium_intervals_vo2": "Series medias VO2max",
        "ten_k_specific_reps": "Repeticiones especificas 10k",
        "ten_k_specific_continuous": "Continuo especifico 10k",
        "five_k_specific_reps": "Repeticiones especificas 5k",
        "half_marathon_specific_blocks": "Bloques especificos de media maraton",
        "long_run": "Tirada larga",
        "long_run_quality": "Tirada larga con calidad",
        "hills_strength": "Cuestas de fuerza",
        "short_hills_power": "Cuestas cortas de potencia",
        "mixed_tempo_plus_fast": "Mixto tempo mas rapido",
        "fartlek_structured": "Fartlek estructurado",
        "progression_finish_fast": "Progresivo con final vivo",
        "race_activation": "Activacion de carrera",
        "marathon_specific_blocks": "Bloques especificos de maraton",
        "polarized_aerobic_with_spikes": "Aerobico polarizado con toques rapidos",
    }

    def humanize_session_family(value: str) -> str:
        return session_family_labels.get(value, value.replace("_", " ").capitalize())

    if payload.get("decision"):
        payload["decision"]["status_label"] = decision_status_label(payload["decision"].get("status"))
        payload["decision"]["action_label"] = decision_action_label(payload["decision"].get("action"))
        guidance = payload["decision"].get("session_guidance", {})
        guidance["primary_labels"] = [humanize_session_family(item) for item in guidance.get("primary", [])]
        guidance["avoid_labels"] = [humanize_session_family(item) for item in guidance.get("avoid", [])]
        guidance["optional_labels"] = [humanize_session_family(item) for item in guidance.get("optional", [])]
    if payload.get("goal_gates"):
        payload["goal_gates"]["status_label"] = goal_status_label(payload["goal_gates"].get("status"))
        metrics = payload["goal_gates"].get("metrics", {})

        def km(value: Any) -> str:
            return f"{float(value):.1f} km" if value is not None else "-"

        def pace_target(seconds: Any) -> str:
            if seconds is None:
                return "-"
            return format_duration(seconds)

        def missing_text(checks: list[dict[str, Any]]) -> str:
            pending = [check["missing"] for check in checks if not check.get("passed") and check.get("missing")]
            return "; ".join(pending) if pending else "Checkpoint cumplido."

        gates_with_checks = []
        for gate in payload["goal_gates"].get("gates", []):
            name = gate.get("name")
            checks: list[dict[str, Any]] = []
            description = ""
            if name == "Base estable":
                checks = [
                    {
                        "label": "Volumen medio 4 semanas",
                        "required": "Al menos 40.0 km/sem",
                        "current": f"{float(metrics.get('avg_weekly_km_28d') or 0.0):.1f} km/sem",
                        "passed": float(metrics.get("avg_weekly_km_28d") or 0.0) >= 40.0,
                        "missing": f"Subir {max(0.0, 40.0 - float(metrics.get('avg_weekly_km_28d') or 0.0)):.1f} km/sem de media",
                    },
                    {
                        "label": "Tirada larga",
                        "required": "Al menos 14.0 km",
                        "current": km(metrics.get("long_run_km_28d")),
                        "passed": float(metrics.get("long_run_km_28d") or 0.0) >= 14.0,
                        "missing": f"Alargar {max(0.0, 14.0 - float(metrics.get('long_run_km_28d') or 0.0)):.1f} km la tirada larga",
                    },
                    {
                        "label": "Revisiones de alto riesgo",
                        "required": "0 en los ultimos 28 dias",
                        "current": str(int(metrics.get("high_risk_reviews_28d") or 0)),
                        "passed": int(metrics.get("high_risk_reviews_28d") or 0) == 0,
                        "missing": "Encadenar 28 dias sin revisiones de alto riesgo",
                    },
                    {
                        "label": "Periostio",
                        "required": "2/10 o menos",
                        "current": f"{metrics.get('latest_shin_pain') if metrics.get('latest_shin_pain') is not None else '-'} /10",
                        "passed": metrics.get("latest_shin_pain") is None or float(metrics.get("latest_shin_pain") or 0.0) <= 2.0,
                        "missing": "Bajar las molestias de periostio a 2/10 o menos",
                    },
                ]
                description = "Antes de pensar en ritmos agresivos hace falta una base repetible y estable."
            elif name == "Umbral competitivo":
                best_5k = metrics.get("best_5k_s_90d")
                checks = [
                    {
                        "label": "Mejor 5k reciente",
                        "required": "19:00 o mejor",
                        "current": pace_target(best_5k),
                        "passed": best_5k is not None and float(best_5k) <= 1140.0,
                        "missing": "Acercar el 5k hacia 19:00 o mejor",
                    }
                ]
                description = "Este checkpoint mide si ya hay una base de rendimiento compatible con un objetivo competitivo."
            elif name == "Precondicion 35:00":
                best_5k = metrics.get("best_5k_s_90d")
                checks = [
                    {
                        "label": "Volumen medio 4 semanas",
                        "required": "Al menos 50.0 km/sem",
                        "current": f"{float(metrics.get('avg_weekly_km_28d') or 0.0):.1f} km/sem",
                        "passed": float(metrics.get("avg_weekly_km_28d") or 0.0) >= 50.0,
                        "missing": f"Subir {max(0.0, 50.0 - float(metrics.get('avg_weekly_km_28d') or 0.0)):.1f} km/sem de media",
                    },
                    {
                        "label": "Tirada larga",
                        "required": "Al menos 16.0 km",
                        "current": km(metrics.get("long_run_km_28d")),
                        "passed": float(metrics.get("long_run_km_28d") or 0.0) >= 16.0,
                        "missing": f"Alargar {max(0.0, 16.0 - float(metrics.get('long_run_km_28d') or 0.0)):.1f} km la tirada larga",
                    },
                    {
                        "label": "Mejor 5k reciente",
                        "required": "18:00 o mejor",
                        "current": pace_target(best_5k),
                        "passed": best_5k is not None and float(best_5k) <= 1080.0,
                        "missing": "Acercar el 5k hacia 18:00 o mejor",
                    },
                    {
                        "label": "Riesgo y periostio",
                        "required": "Sin riesgo alto y periostio <= 2/10",
                        "current": f"Riesgo {int(metrics.get('high_risk_reviews_28d') or 0)}, periostio {metrics.get('latest_shin_pain') if metrics.get('latest_shin_pain') is not None else '-'} /10",
                        "passed": int(metrics.get("high_risk_reviews_28d") or 0) == 0 and (metrics.get("latest_shin_pain") is None or float(metrics.get("latest_shin_pain") or 0.0) <= 2.0),
                        "missing": "Consolidar 28 dias sin riesgo alto y con periostio controlado",
                    },
                ]
                description = "Aqui se comprueba si el objetivo 35:00 empieza a ser plausible sin forzar la preparacion."
            elif name == "Seleccion 35:00":
                best_5k = metrics.get("best_5k_s_90d")
                best_10k = metrics.get("best_10k_s_180d")
                checks = [
                    {
                        "label": "Mejor 5k reciente",
                        "required": "17:15 o mejor",
                        "current": pace_target(best_5k),
                        "passed": best_5k is not None and float(best_5k) <= 1035.0,
                        "missing": "Acercar el 5k hacia 17:15 o mejor",
                    },
                    {
                        "label": "Mejor 10k o tune-up",
                        "required": "36:30 o mejor",
                        "current": pace_target(best_10k),
                        "passed": best_10k is not None and float(best_10k) <= 2190.0,
                        "missing": "Acercar el 10k hacia 36:30 o mejor",
                    },
                    {
                        "label": "Precondicion 35:00",
                        "required": "Checkpoint anterior cumplido",
                        "current": "Si" if any(item.get("name") == "Precondicion 35:00" and item.get("passed") for item in payload["goal_gates"].get("gates", [])) else "No",
                        "passed": any(item.get("name") == "Precondicion 35:00" and item.get("passed") for item in payload["goal_gates"].get("gates", [])),
                        "missing": "Primero hay que cumplir la precondicion 35:00",
                    },
                ]
                description = "Este es el filtro final antes de permitir que 35:00 guie la estrategia de carrera."

            gate["description"] = description
            gate["checks"] = checks
            gate["next_step"] = missing_text(checks)
            gates_with_checks.append(gate)

        payload["goal_gates"]["gates"] = gates_with_checks
    return payload


def progress_metrics() -> list[dict[str, Any]]:
    master_plan = master_plan_page_data()
    dashboard = dashboard_payload()
    today = date.today()
    metrics: list[dict[str, Any]] = []

    start_date = parse_iso_date(strip_markdown_ticks(master_plan.get("cycle_window", {}).get("start_date")))
    goal_date = parse_iso_date(strip_markdown_ticks(master_plan.get("cycle_window", {}).get("goal_race_date")))
    if start_date and goal_date and goal_date >= start_date:
        total_days = max((goal_date - start_date).days, 1)
        elapsed_days = min(max((today - start_date).days, 0), total_days)
        remaining_days = max((goal_date - today).days, 0)
        cycle_progress = round((elapsed_days / total_days) * 100)
        remaining_progress = round((remaining_days / total_days) * 100)
        metrics.append(
            {
                "label": "Tiempo hasta la carrera principal",
                "value": remaining_progress,
                "value_label": f"{remaining_days} dias",
                "detail": f"{remaining_days} dias para el objetivo; ciclo completado al {cycle_progress}%.",
                "tone": "accent",
            }
        )
        metrics.append(
            {
                "label": "Progreso del ciclo",
                "value": cycle_progress,
                "value_label": f"{cycle_progress}%",
                "detail": f"Desde {start_date.isoformat()} hasta {goal_date.isoformat()}.",
                "tone": "info",
            }
        )

    goal_gate_status = str(dashboard.get("goal_gates", {}).get("status") or "").lower()
    goal_probability_map = {
        "unsupported_now": 18,
        "development_needed": 42,
        "aggressive_alive": 68,
        "35_ready": 88,
    }
    if goal_gate_status:
        probability = goal_probability_map.get(goal_gate_status, 0)
        metrics.append(
            {
                "label": "Posibilidades de cumplir el objetivo",
                "value": probability,
                "value_label": f"{probability}%",
                "detail": dashboard.get("goal_gates", {}).get("summary") or "Estimacion automatica basada en el estado actual del objetivo.",
                "tone": "warn" if probability < 50 else "accent",
            }
        )

    workouts = [item for item in planned_workouts() if parse_iso_date(item.get("date")) and parse_iso_date(item.get("date")) <= today]
    reviews_by_date = {item.get("date") for item in completed_reviews() if item.get("date") and parse_iso_date(item.get("date")) and parse_iso_date(item.get("date")) <= today}
    if workouts:
        matched = sum(1 for item in workouts if item.get("date") in reviews_by_date)
        adherence = round((matched / len(workouts)) * 100)
        metrics.append(
            {
                "label": "Adherencia al plan",
                "value": adherence,
                "value_label": f"{matched}/{len(workouts)}",
                "detail": "Relacion entre sesiones planificadas ya vencidas y sesiones con revision registrada.",
                "tone": "accent" if adherence >= 75 else "warn",
            }
        )

    return metrics


def planned_workouts() -> list[dict[str, Any]]:
    workouts: list[dict[str, Any]] = []
    for path in sorted(PLANNED_WORKOUTS_DIR.glob("*.yaml")):
        if path.name == "library_run_templates.yaml" or path.name == "workout_template.yaml":
            continue
        payload = load_yaml(path).get("workout", {})
        schedule_date = str(payload.get("schedule_date") or "")
        upload = planned_upload_data(path.stem, schedule_date) if schedule_date else {}
        uploaded_response = upload.get("uploaded_response", {})
        scheduled_response = upload.get("scheduled_response", {})
        workout_id = uploaded_response.get("workoutId") or scheduled_response.get("workout", {}).get("workoutId")
        scheduled_id = scheduled_response.get("workoutScheduleId")
        kind, kind_label, color_class = classify_planned_workout(payload)
        workouts.append(
            {
                "slug": path.stem,
                "name": payload.get("name") or path.stem,
                "date": schedule_date,
                "sport": payload.get("sport") or "-",
                "description": payload.get("description") or "",
                "estimated_duration": format_duration(payload.get("estimated_duration_s")),
                "step_count": len(payload.get("steps") or []),
                "garmin_workout_id": workout_id,
                "garmin_workout_url": garmin_scheduled_workout_url(scheduled_id) or garmin_workout_url(workout_id, payload.get("sport")),
                "garmin_scheduled_id": scheduled_id,
                "session_kind": kind,
                "session_kind_label": kind_label,
                "session_color_class": color_class,
                "payload": payload,
            }
        )
    workouts.sort(key=lambda item: (item["date"], item["name"]))
    return workouts


def planned_workout_detail(slug: str) -> dict[str, Any] | None:
    for item in planned_workouts():
        if item["slug"] == slug:
            return item
    return None


def completed_reviews() -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for path in sorted(COMPLETED_REVIEW_DIR.glob("*.analysis.json")):
        payload = load_json(path)
        planned = payload.get("planned", {})
        summary = payload.get("summary", {})
        kind, kind_label, color_class = classify_completed_review(payload)
        reviews.append(
            {
                "slug": path.stem.replace(".analysis", ""),
                "date": planned.get("date") or "",
                "name": planned.get("name") or path.stem,
                "score": payload.get("score"),
                "traffic_light": traffic_light_label(payload.get("traffic_light")),
                "risk_level": risk_level_label(payload.get("risk_level")),
                "distance_km": round(float(summary.get("distance_m") or 0.0) / 1000.0, 2),
                "duration": format_duration(summary.get("duration_s")),
                "pace": format_pace(summary.get("pace_s_per_km")),
                "avg_hr": summary.get("avg_hr") or "-",
                "garmin_activity_id": summary.get("activity_id") or summary.get("activityId"),
                "garmin_activity_url": garmin_activity_url(summary.get("activity_id") or summary.get("activityId")),
                "garmin_workout_id": summary.get("workout_id") or summary.get("workoutId"),
                "garmin_workout_url": garmin_workout_url(summary.get("workout_id") or summary.get("workoutId"), planned.get("sport")),
                "activity_name": summary.get("activity_name") or planned.get("name") or path.stem,
                "session_kind": kind,
                "session_kind_label": kind_label,
                "session_color_class": color_class,
                "compliance_note": payload.get("progression", {}).get("summary") or payload.get("analysis") or "Sin comentario disponible.",
                "payload": payload,
            }
        )
    reviews.sort(key=lambda item: (item["date"], item["name"]), reverse=True)
    return reviews


def completed_review_detail(slug: str) -> dict[str, Any] | None:
    for item in completed_reviews():
        if item["slug"] == slug:
            return item
    return None


def athlete_page_data() -> dict[str, Any]:
    shoes_capability = ensure_fresh("shoes_mileage")
    profile_capability = ensure_fresh("athlete_profile")
    profile = load_optional_yaml(ROOT / "athlete" / "profile.yaml").get("athlete", {})
    health = load_optional_yaml(ROOT / "athlete" / "health.yaml").get("health", {})
    injury = load_optional_yaml(ROOT / "athlete" / "injury_tracker.yaml").get("injury_tracker", {})
    shoes = load_optional_yaml(ROOT / "athlete" / "shoes.yaml").get("shoes", [])
    entries = list(reversed(injury.get("entries") or []))
    capability_messages = [message for message in [shoes_capability.warning, profile_capability.warning] if message]
    return {
        "profile": profile,
        "health": health,
        "injury": injury,
        "entries": entries,
        "shoes": shoes if isinstance(shoes, list) else [],
        "capability_messages": capability_messages,
    }


def races_page_data() -> list[dict[str, Any]]:
    reviews_by_date = {item["date"]: item for item in completed_reviews() if item.get("date")}
    races: list[dict[str, Any]] = []
    for path in sorted(RACES_DIR.glob("**/*.yaml")):
        raw_payload = load_yaml(path)
        payload = raw_payload.get("race", raw_payload) if isinstance(raw_payload, dict) else {}
        if not isinstance(payload, dict):
            continue
        goal = payload.get("goal") or {}
        goal_value = goal.get("value") if isinstance(goal, dict) else goal
        race_date = iso_date_string(payload.get("date"))
        linked_review = reviews_by_date.get(race_date)
        races.append(
            {
                "name": payload.get("name") or path.stem,
                "date": race_date,
                "priority": priority_label(payload.get("priority")),
                "distance_km": payload.get("distance_km") or payload.get("distance") or "-",
                "elevation_gain_m": payload.get("elevation_gain_m") or "-",
                "location": payload.get("location") or "-",
                "goal": goal_value or "-",
                "completed_review_slug": linked_review.get("slug") if linked_review else None,
                "completed_review_score": linked_review.get("score") if linked_review else None,
                "completed_review_pace": linked_review.get("pace") if linked_review else None,
                "completed_review_traffic_light": linked_review.get("traffic_light") if linked_review else None,
            }
        )
    races.sort(key=lambda item: item["date"])
    return races


def races_by_day() -> dict[str, list[dict[str, Any]]]:
    items: dict[str, list[dict[str, Any]]] = {}
    for race in races_page_data():
        if race.get("date"):
            items.setdefault(race["date"], []).append(race)
    return items


def calendar_day_data(day: str) -> dict[str, Any]:
    planned_items = [item for item in planned_workouts() if item.get("date") == day]
    completed_items = [item for item in completed_reviews() if item.get("date") == day]
    race_items = races_by_day().get(day, [])
    reviews = completed_items
    summary_items = len(planned_items) + len(completed_items) + len(race_items)
    return {
        "date": day,
        "date_label": day_label(day),
        "planned_items": planned_items,
        "completed_items": completed_items,
        "reviews": reviews,
        "races": race_items,
        "daily_summary": {
            "status_label": day_status_label(planned_items, completed_items, reviews, race_items),
            "item_count": summary_items,
            "has_content": bool(summary_items),
        },
        "links": {
            "planned_count": len(planned_items),
            "completed_count": len(completed_items),
            "race_count": len(race_items),
        },
    }


def calendar_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    review_items = completed_reviews()
    planned_items = planned_workouts()
    reviews_by_date = {item["date"]: item for item in review_items if isinstance(item, dict) and item.get("date")}
    completed_by_date = {item["date"]: item for item in review_items if isinstance(item, dict) and item.get("date")}
    planned_by_date = {item["date"]: item for item in planned_items if isinstance(item, dict) and item.get("date")}

    all_dates = sorted(day for day in (set(planned_by_date) | set(completed_by_date)) if parse_iso_date(day))
    for day in all_dates:
        planned = planned_by_date.get(day)
        review = reviews_by_date.get(day)
        completed = completed_by_date.get(day)
        primary_source = review or planned or completed or {}
        primary_kind = primary_source.get("session_kind") or "other"
        status = event_status(
            {
                "planned_workout": planned,
                "completed_review": completed,
                "review": review,
                "race": None,
            }
        )
        title = primary_source.get("name")
        events.append(
            {
                "date": day,
                "title": title or day,
                "kind": primary_kind,
                "source": "review" if review else ("planned" if planned else "completed"),
                "planned_workout": planned,
                "completed_review": completed,
                "review": review,
                "race": None,
                "garmin_activity_url": (completed or {}).get("garmin_activity_url"),
                "garmin_workout_url": (planned or completed or {}).get("garmin_workout_url"),
                "status": status,
                "status_label": event_status_label(status),
                "score": (review or {}).get("score"),
                "traffic_light": (review or {}).get("traffic_light"),
                "traffic_light_class": traffic_light_class((review or {}).get("traffic_light")),
                "detail_url": f"/calendar/day/{day}",
                "session_kind_label": session_kind_label(primary_kind),
                "session_color_class": session_color_class(primary_kind),
                "badges": [badge for badge in ["Plan" if planned else None, "Hecho" if completed else None, "Revisión" if review else None] if badge],
            }
        )
    return events


def calendar_month_data_combined(month: str | None, kind: str = "all", status: str = "all") -> dict[str, Any]:
    try:
        workout_events = calendar_events()
        races = races_by_day()
        event_by_day = {event["date"]: event for event in workout_events}
        for race_date, race_items in races.items():
            logger.info("calendar race candidate date=%s items=%s", race_date, len(race_items))
            if not parse_iso_date(race_date):
                logger.warning("calendar skipping invalid race date=%s", race_date)
                continue
            if not race_items or not isinstance(race_items[0], dict):
                logger.warning("calendar skipping malformed race items date=%s", race_date)
                continue
            if race_date in event_by_day:
                event_by_day[race_date]["race"] = race_items[0]
                event_by_day[race_date].setdefault("badges", []).append("Carrera")
                if not event_by_day[race_date].get("review"):
                    event_by_day[race_date]["status"] = "race_day"
                    event_by_day[race_date]["status_label"] = "Carrera"
                continue
            event_by_day[race_date] = {
                "date": race_date,
                "title": race_items[0].get("name") or race_date,
                "kind": "race",
                "source": "race",
                "planned_workout": None,
                "completed_review": None,
                "review": None,
                "race": race_items[0],
                "garmin_activity_url": None,
                "garmin_workout_url": None,
                "status": "race_day",
                "status_label": "Carrera",
                "score": None,
                "traffic_light": None,
                "traffic_light_class": "",
                "detail_url": f"/calendar/day/{race_date}",
                "session_kind_label": session_kind_label("race"),
                "session_color_class": session_color_class("race"),
                "badges": ["Carrera"],
            }
        filtered_event_by_day = {day: event for day, event in event_by_day.items() if event_matches_filters(event, kind, status)}
        available_months = sorted({day[:7] for day in event_by_day if parse_iso_date(day)})
        selected = month if month in available_months else None
        if not selected:
            today_month = date.today().strftime("%Y-%m")
            selected = today_month if today_month in available_months else (available_months[0] if available_months else today_month)

        year, month_number = map(int, selected.split("-"))
        cal = calendar.Calendar(firstweekday=0)
        weeks: list[list[dict[str, Any]]] = []
        for week in cal.monthdatescalendar(year, month_number):
            row: list[dict[str, Any]] = []
            for day in week:
                iso_day = day.isoformat()
                row.append(
                    {
                        "date": iso_day,
                        "day": day.day,
                        "in_month": day.month == month_number,
                        "is_today": day == date.today(),
                        "event": filtered_event_by_day.get(iso_day),
                        "detail_url": f"/calendar/day/{iso_day}",
                    }
                )
            weeks.append(row)

        return {
            "selected": selected,
            "selected_label": month_label(selected),
            "available_months": available_months,
            "weeks": weeks,
            "prev_month": add_month(selected, -1),
            "next_month": add_month(selected, 1),
            "selected_kind": kind,
            "selected_status": status,
        }
    except Exception:
        logger.exception("calendar_month_data_combined failed month=%s", month)
        raise


def master_plan_page_data() -> dict[str, Any]:
    active_cycle = active_cycle_data()
    master_plan_path = ROOT / str(active_cycle.get("master_plan_path") or MASTER_PLAN_PATH.relative_to(ROOT))
    if not master_plan_path.exists():
        return {
            "exists": False,
            "active_cycle": active_cycle,
            "cycle_window": {},
            "goal_race": [],
            "pre_cycle_race": [],
            "interpretation": [],
            "current_level": [],
            "planning_logic": [],
            "blocks": [],
            "weekly_structure": [],
            "volume_progression": [],
            "intensity_rules": [],
            "checkpoints": [],
            "calibration_rule": [],
        }
    text = read_text(master_plan_path)
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            sections[current_section] = []
            continue
        if current_section is not None:
            sections[current_section].append(stripped)

    def clean_items(name: str) -> list[str]:
        return [line[2:].strip() for line in sections.get(name, []) if line.startswith("- ")]

    def translate_text(value: str) -> str:
        replacements = [
            ("Start date", "Fecha de inicio"),
            ("Goal race date", "Fecha de la carrera objetivo"),
            ("Total duration", "Duracion total"),
            ("Last full review", "Ultima revision completa"),
            ("Date", "Fecha"),
            ("Priority", "Prioridad"),
            ("Distance", "Distancia"),
            ("Elevation gain", "Desnivel positivo"),
            ("Declared goal", "Objetivo declarado"),
            ("Role", "Rol"),
            ("Goal", "Objetivo"),
            ("Practical impact", "Impacto practico"),
            ("Dates", "Fechas"),
            ("Duration", "Duracion"),
            ("Focus", "Enfoque"),
            ("Tuesday", "Martes"),
            ("Thursday", "Jueves"),
            ("Sunday", "Domingo"),
            ("Strength", "Fuerza"),
            ("Recovery", "Recuperacion"),
            ("Quality Density", "Densidad de calidad"),
            ("End of Block", "Fin del bloque"),
            ("Mid Block", "Mitad del bloque"),
            ("Block ", "Bloque "),
            ("Reset, consistency and tissue tolerance", "Reinicio, consistencia y tolerancia tisular"),
            ("Aerobic base and volume consolidation", "Base aerobica y consolidacion del volumen"),
            ("Threshold development and strength endurance", "Desarrollo del umbral y resistencia de fuerza"),
            ("Specific 10k development", "Desarrollo especifico de 10k"),
            ("Specific consolidation and competitive sharpening", "Consolidacion especifica y afinado competitivo"),
            ("Taper and race execution", "Puesta a punto y ejecucion de carrera"),
            ("weeks", "semanas"),
            ("week", "semana"),
            ("The `S` race is the fixed target event.", "La carrera `S` es el objetivo fijo del ciclo."),
            ("`35:00` is a stretch target, not the training pace to force from the current level.", "`35:00` es un objetivo ambicioso, no un ritmo de entrenamiento que haya que forzar desde el nivel actual."),
            ("The current evidence does not justify prescribing `3:30/km` work yet.", "La evidencia actual todavia no justifica prescribir trabajo a `3:30/km`."),
            ("The plan must earn that pace through checkpoints; if the data does not support it, the race target is recalibrated while still prioritizing the best possible 10k performance in February.", "El plan debe ganarse ese ritmo a traves de checkpoints; si los datos no lo sostienen, se recalibra el objetivo de carrera manteniendo como prioridad el mejor 10k posible en febrero."),
            ("Base the whole cycle on the only `S` race.", "Construir todo el ciclo alrededor de la unica carrera `S`."),
            ("Fit `A`, `B`, `C` and `D` races around the active block.", "Encajar las carreras `A`, `B`, `C` y `D` alrededor del bloque activo."),
            ("Update weekly planning every Sunday using completed training, fatigue, shin response and race proximity.", "Actualizar la planificacion semanal cada domingo usando entrenamientos completados, fatiga, respuesta de la tibia y proximidad de carrera."),
            ("Use heart rate to control easy and long runs, and pace to control intervals or tempo work.", "Usar la frecuencia cardiaca para controlar rodajes y tiradas largas, y el ritmo para intervalos o trabajos de tempo."),
            ("Keep load progression conservative until the left shin is stable.", "Mantener una progresion de carga conservadora hasta que la tibia izquierda este estable."),
            ("Do not use final-goal pace until checkpoints prove that it is a realistic training stimulus.", "No usar el ritmo objetivo final hasta que los checkpoints demuestren que es un estimulo realista."),
        ]
        translated = value
        for source, target in replacements:
            translated = translated.replace(source, target)
        return translated

    def numbered_items(name: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for raw_line in sections.get(name, []):
            stripped = raw_line.strip()
            if not stripped:
                continue
            number, separator, remainder = stripped.partition(". ")
            if number.isdigit() and separator:
                if current:
                    items.append(current)
                current = {"title": remainder.strip(), "details": []}
                continue
            if stripped.startswith("- ") and current is not None:
                current["details"].append(stripped[2:].strip())
        if current:
            items.append(current)
        return items

    cycle_window_key_map = {
        "Start date": "start_date",
        "Goal race date": "goal_race_date",
        "Total duration": "total_duration",
        "Last full review": "last_full_review",
    }
    cycle_window: dict[str, str] = {}
    for item in clean_items("Cycle Window"):
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        normalized_key = cycle_window_key_map.get(key.strip(), key.strip().lower().replace(" ", "_"))
        cycle_window[normalized_key] = translate_text(value.strip())

    blocks: list[dict[str, Any]] = []
    for index, entry in enumerate(numbered_items("Revised Block Structure"), start=1):
        block = {"index": index, "title": translate_text(entry["title"]), "dates": "-", "duration": "-", "focus": "-"}
        for detail in entry["details"]:
            if detail.startswith("Dates:"):
                block["dates"] = translate_text(detail.split(":", 1)[1].strip())
            elif detail.startswith("Duration:"):
                block["duration"] = translate_text(detail.split(":", 1)[1].strip())
            elif detail.startswith("Focus:"):
                block["focus"] = translate_text(detail.split(":", 1)[1].strip())
        blocks.append(block)

    def translated_items(name: str) -> list[str]:
        return [translate_text(item) for item in clean_items(name)]

    def translated_numbered_items(name: str) -> list[dict[str, Any]]:
        return [
            {
                "title": translate_text(item["title"]),
                "details": [translate_text(detail) for detail in item["details"]],
            }
            for item in numbered_items(name)
        ]

    return {
        "exists": True,
        "active_cycle": active_cycle,
        "cycle_window": cycle_window,
        "goal_race": translated_items("Main Goal Race"),
        "pre_cycle_race": translated_items("Pre-Cycle Race"),
        "interpretation": translated_items("Coaching Interpretation Of The Goal"),
        "current_level": translated_items("Current Level Audit"),
        "planning_logic": translated_items("Planning Logic"),
        "blocks": blocks,
        "weekly_structure": translated_numbered_items("Weekly Structure Principles"),
        "volume_progression": translated_items("Volume Progression"),
        "intensity_rules": translated_items("Intensity Rules"),
        "checkpoints": translated_numbered_items("Checkpoints"),
        "calibration_rule": translated_items("Calibration Rule"),
    }


def cycle_page_data() -> dict[str, Any]:
    dashboard = dashboard_payload()
    master_plan = master_plan_page_data()
    active_cycle = active_cycle_data()
    blocks = master_plan.get("blocks", [])
    active_block_name = dashboard.get("active_context", {}).get("active_block")
    current_block = next((block for block in blocks if block.get("title") == active_block_name), blocks[0] if blocks else None)
    return {
        "active_cycle": active_cycle,
        "dashboard": dashboard,
        "master_plan": master_plan,
        "current_block": current_block,
        "goal_race": dashboard.get("active_context", {}).get("goal_race"),
        "days_to_goal_race": dashboard.get("active_context", {}).get("days_to_goal_race"),
        "session_guidance": dashboard.get("decision", {}).get("session_guidance", {}),
    }


def home_page_data() -> dict[str, Any]:
    status = workspace_status()
    dashboard = dashboard_payload()
    active_cycle = active_cycle_data()
    week = week_page_data()
    workouts = planned_workouts()
    reviews = completed_reviews()
    upcoming = [item for item in workouts if parse_iso_date(item["date"]) and parse_iso_date(item["date"]) >= date.today()]
    recent_reviews = reviews[:5]
    return {
        "workspace": status,
        "dashboard": dashboard,
        "active_cycle": active_cycle,
        "week": week,
        "upcoming": upcoming[:5] if upcoming else workouts[:5],
        "recent_reviews": recent_reviews,
        "planned_count": len(workouts),
        "review_count": len(reviews),
        "progress_metrics": progress_metrics(),
    }


def add_month(year_month: str, delta: int) -> str:
    base = datetime.strptime(year_month, "%Y-%m")
    month_index = base.year * 12 + (base.month - 1) + delta
    year = month_index // 12
    month = month_index % 12 + 1
    return f"{year:04d}-{month:02d}"


def planned_calendar_data(month: str | None) -> dict[str, Any]:
    workouts = planned_workouts()
    workout_by_day: dict[str, list[dict[str, Any]]] = {}
    for workout in workouts:
        workout_by_day.setdefault(workout["date"], []).append(workout)

    available_months = sorted({item["date"][:7] for item in workouts if item.get("date")})
    selected = month if month in available_months else None
    if not selected:
        today_month = date.today().strftime("%Y-%m")
        selected = today_month if today_month in available_months else (available_months[0] if available_months else today_month)

    year, month_number = map(int, selected.split("-"))
    cal = calendar.Calendar(firstweekday=0)
    weeks: list[list[dict[str, Any]]] = []
    for week in cal.monthdatescalendar(year, month_number):
        row: list[dict[str, Any]] = []
        for day in week:
            iso_day = day.isoformat()
            row.append(
                {
                    "date": iso_day,
                    "day": day.day,
                    "in_month": day.month == month_number,
                    "is_today": day == date.today(),
                    "workouts": workout_by_day.get(iso_day, []),
                }
            )
        weeks.append(row)

    return {
        "selected": selected,
        "selected_label": month_label(selected),
        "available_months": available_months,
        "weeks": weeks,
        "prev_month": add_month(selected, -1),
        "next_month": add_month(selected, 1),
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if authenticated(request):
        return templates.TemplateResponse(request, "index.html", template_context(request, **home_page_data()))
    return templates.TemplateResponse(request, "login.html", template_context(request, error=None))


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)) -> HTMLResponse:
    config = env_config()
    if not config["configured"]:
        return templates.TemplateResponse(
            request,
            "login.html",
            template_context(
                request,
                error="La web no está configurada todavía. Define las credenciales de acceso y vuelve a intentarlo.",
            ),
            status_code=503,
        )
    if username == config["username"] and password == config["password"]:
        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", template_context(request, error="Credenciales incorrectas."), status_code=401)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "index.html", template_context(request, **home_page_data()))


@app.get("/week", response_class=HTMLResponse)
async def week(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return RedirectResponse(url="/planned-workouts?view=week", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "dashboard.html", template_context(request, dashboard=dashboard_payload(), workspace=workspace_status()))


@app.get("/decision", response_class=HTMLResponse)
async def decision(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/planned-workouts", response_class=HTMLResponse)
async def planned_workouts_page(request: Request, view: str = "list", month: str | None = None, kind: str = "all", status: str = "all") -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    items = planned_workouts()
    if kind != "all":
        items = [item for item in items if item.get("session_kind") == kind]
    current_view = view if view in {"week", "list", "calendar"} else "week"
    calendar_data = (
        calendar_month_data_combined(month, kind=kind, status=status)
        if current_view == "calendar"
        else {"selected": month or "", "selected_label": "", "weeks": [], "prev_month": "", "next_month": "", "selected_kind": kind, "selected_status": status}
    )
    return templates.TemplateResponse(
        request,
        "planned_workouts.html",
        template_context(request, workouts=items, current_view=current_view, calendar=calendar_data, selected_kind=kind, selected_status=status, week=week_page_data(), workspace=workspace_status()),
    )


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, month: str | None = None, kind: str = "all", status: str = "all") -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    workouts = planned_workouts()
    if kind != "all":
        workouts = [item for item in workouts if item.get("session_kind") == kind]
    return templates.TemplateResponse(
        request,
        "planned_workouts.html",
        template_context(request, workouts=workouts, current_view="calendar", calendar=calendar_month_data_combined(month, kind=kind, status=status), selected_kind=kind, selected_status=status, week=week_page_data(), workspace=workspace_status()),
    )


@app.get("/calendar/day/{day}", response_class=HTMLResponse)
async def calendar_day_page(request: Request, day: str) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "calendar_day.html", template_context(request, calendar_day=calendar_day_data(day)))


@app.get("/planned-workouts/{slug}", response_class=HTMLResponse)
async def planned_workout_page(request: Request, slug: str) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    item = planned_workout_detail(slug)
    if not item:
        return RedirectResponse(url="/planned-workouts", status_code=303)
    return templates.TemplateResponse(request, "planned_workout_detail.html", template_context(request, workout=item))


@app.get("/completed-workouts", response_class=HTMLResponse)
async def completed_workouts_page(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    items = completed_reviews()
    return templates.TemplateResponse(request, "completed_workouts.html", template_context(request, reviews=items))


@app.get("/completed-workouts/{slug}", response_class=HTMLResponse)
async def completed_workout_page(request: Request, slug: str) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    item = completed_review_detail(slug)
    if not item:
        return RedirectResponse(url="/completed-workouts", status_code=303)
    return templates.TemplateResponse(request, "completed_workout_detail.html", template_context(request, review=item))


@app.get("/athlete", response_class=HTMLResponse)
async def athlete(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "athlete.html", template_context(request, athlete=athlete_page_data(), workspace=workspace_status()))


@app.get("/races", response_class=HTMLResponse)
async def races(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "races.html", template_context(request, races=races_page_data(), workspace=workspace_status()))


@app.get("/cycle", response_class=HTMLResponse)
async def cycle(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "cycle.html", template_context(request, cycle=cycle_page_data(), workspace=workspace_status()))


@app.get("/master-plan", response_class=HTMLResponse)
async def master_plan(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "master_plan.html", template_context(request, master_plan=master_plan_page_data(), workspace=workspace_status()))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/data-sources")
async def debug_data_sources() -> dict[str, Any]:
    planned_files = sorted(
        path.name for path in PLANNED_WORKOUTS_DIR.glob("*.yaml") if path.name not in {"library_run_templates.yaml", "workout_template.yaml"}
    )
    race_files = sorted(path.name for path in RACES_DIR.glob("**/*.yaml"))
    return {
        "planned_count": len(planned_files),
        "planned_files": planned_files,
        "race_count": len(race_files),
        "race_files": race_files,
        "races_loaded": races_page_data(),
    }
