#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import calendar
import logging
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from scripts.system.capability_engine import ensure_fresh
from scripts.telegram.opencode_bridge import (
    DEFAULT_CONFIG_PATH as OPENCODE_REMOTE_CONFIG_PATH,
    DEFAULT_OPENCODE_MODEL,
    OpenCodeBridge,
    OpenCodeRemoteConfig,
    SessionStore,
    command_mentions_commit_or_push,
    confirmation_reason,
    normalize_model_name,
)
from starlette.middleware.sessions import SessionMiddleware


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "web" / "templates"
STATIC_DIR = ROOT / "web" / "static"
PLANNED_WORKOUTS_DIR = ROOT / "training" / "planned" / "workouts"
COMPLETED_REVIEW_DIR = ROOT / "training" / "completed" / "reviews"
COMPLETED_FEEDBACK_DIR = ROOT / "training" / "completed" / "feedback"
GARMIN_ACTIVITY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
GARMIN_DAILY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "daily"
RACES_DIR = ROOT / "races"
MASTER_PLAN_PATH = ROOT / "planning" / "master_plan.md"
ACTIVE_CYCLE_PATH = ROOT / "planning" / "cycles" / "active.yaml"
WEB_CONFIG_PATH = ROOT / "web" / "web_config.yaml"
WEB_LOG_PATH = ROOT / "web" / "web_debug.log"
ACTIVE_WEEK_PATH = ROOT / "planning" / "weeks" / "semana_actual.md"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"
PLANNED_ACTIONS_PATH = ROOT / "system" / "state" / "planned_workout_actions.json"
GARMIN_RETRY_STATE_PATH = ROOT / "system" / "state" / "garmin_retry_state.json"
POST_WORKOUT_REFRESH_STATE_PATH = ROOT / "system" / "state" / "post_workout_refresh_state.json"
GARMIN_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
WEB_CHAT_UI_STATE_PATH = ROOT / "system" / "state" / "web_chat_ui.json"


WEB_CHAT_LOCKS: dict[str, asyncio.Lock] = {}


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


def load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return load_json(path)


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


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


def automation_pipeline_status() -> dict[str, Any]:
    state = load_optional_json(
        POST_WORKOUT_REFRESH_STATE_PATH,
        {
            "last_seen_activity_id": None,
            "last_processed_activity_id": None,
            "last_processed_at": None,
            "last_successful_run": None,
            "last_error": None,
            "processed_activities": [],
            "processed_feedback_updates": [],
            "runs": [],
        },
    )
    state = state if isinstance(state, dict) else {}
    last_error = str(state.get("last_error") or "").strip() or None
    last_successful_run = format_datetime(state.get("last_successful_run"))
    last_processed_at = format_datetime(state.get("last_processed_at"))
    processed_activities = state.get("processed_activities") if isinstance(state.get("processed_activities"), list) else []
    processed_feedback_updates = state.get("processed_feedback_updates") if isinstance(state.get("processed_feedback_updates"), list) else []
    recent_activity_items = list(reversed(processed_activities[-5:]))
    recent_feedback_items = list(reversed(processed_feedback_updates[-5:]))
    recent_runs = state.get("runs") if isinstance(state.get("runs"), list) else []
    last_run = recent_runs[-1] if recent_runs else None
    healthy = bool(last_successful_run and not last_error)
    status_label = "Operativo" if healthy else ("Con errores" if last_error else "Pendiente")
    summary = "El pipeline automatico esta procesando actividades y feedback sin errores recientes." if healthy else (
        f"Ultimo error: {last_error}" if last_error else "El pipeline automatico aun no ha procesado eventos suficientes."
    )
    return {
        "healthy": healthy,
        "status_label": status_label,
        "summary": summary,
        "last_successful_run": last_successful_run,
        "last_processed_at": last_processed_at,
        "last_seen_activity_id": state.get("last_seen_activity_id"),
        "last_processed_activity_id": state.get("last_processed_activity_id"),
        "last_error": last_error,
        "last_run": {
            "run_at": format_datetime((last_run or {}).get("run_at")),
            "detected_count": (last_run or {}).get("detected_count") or 0,
            "triggered_pipeline": bool((last_run or {}).get("triggered_pipeline")),
            "error": (last_run or {}).get("error") or None,
        },
        "recent_activities": recent_activity_items,
        "recent_feedback_updates": recent_feedback_items,
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
            "latest_shin_entry": None,
        },
        "goal_gates": {
            "status": "unsupported_now",
            "status_label": "Sin evaluacion disponible",
            "summary": "Los checkpoints del objetivo apareceran cuando exista plan y decision automatica.",
            "passed_count": 0,
            "total_gates": 0,
            "metrics": {"latest_shin_pain": None},
            "gates": [],
        },
        "active_context": {"active_block": None, "days_to_goal_race": None, "goal_race": None},
        "performance_estimate": {"current_10k_estimate_s": None, "method": "Sin datos suficientes"},
        "daily_metrics": {"latest_hrv": None, "latest_training_readiness": None, "latest_resting_heart_rate": None},
        "readiness_card": {
            "state": "missing",
            "label": "Sin readiness disponible",
            "tone": "warn",
            "summary": "Faltan señales diarias para traducir el estado de hoy a una acción clara.",
            "action": "Apóyate en la decisión global y mantén margen conservador.",
            "detail": "No hay métricas diarias suficientes o están desactualizadas.",
            "source_label": "Sin dato diario",
            "signals": [],
        },
        "protection_mode": {
            "active": False,
            "key": "normal_build",
            "label": "Construccion normal",
            "tone": "ok",
            "summary": "Sin modo lesion activo.",
            "allowed_progression": "Se puede progresar con cautela normal.",
            "guidance_note": "",
            "quality_cap_label": None,
            "triggers": [],
        },
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


def calendar_event_sort_key(event: dict[str, Any]) -> tuple[int, str, str]:
    source_order = {"race": 0, "review": 1, "completed": 2, "planned": 3}
    return (
        source_order.get(str(event.get("source") or ""), 9),
        str(event.get("title") or ""),
        str(event.get("status") or ""),
    )


def traffic_light_class(value: str | None) -> str:
    normalized = str(value or "").lower()
    return {
        "verde": "status-green",
        "amarillo": "status-yellow",
        "rojo": "status-red",
    }.get(normalized, "")


templates.env.filters["format_duration"] = format_duration
templates.env.filters["format_pace"] = format_pace
templates.env.filters["format_datetime"] = format_datetime


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
        "flash": request.session.pop("flash", None),
    }
    context.update(values)
    return context


def web_chat_identity(request: Request) -> str:
    return f"web:{request.session.get('username') or 'unknown'}"


def normalize_runtime_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def load_web_chat_remote_config() -> tuple[OpenCodeRemoteConfig | None, str | None]:
    if not OPENCODE_REMOTE_CONFIG_PATH.exists():
        return None, f"Falta `telegram/{OPENCODE_REMOTE_CONFIG_PATH.name}` con la configuracion de `opencode_remote`."

    opencode_data = load_optional_yaml(OPENCODE_REMOTE_CONFIG_PATH).get("opencode_remote") or {}
    if not isinstance(opencode_data, dict) or not opencode_data:
        return None, "No existe el bloque `opencode_remote` en la configuracion del bridge."

    try:
        return (
            OpenCodeRemoteConfig(
                enabled=bool(opencode_data.get("enabled", True)),
                server_url=str(opencode_data.get("server_url") or "http://127.0.0.1:4096").strip(),
                project_dir=normalize_runtime_path(opencode_data.get("project_dir") or ROOT),
                session_store=normalize_runtime_path(opencode_data.get("session_store") or "telegram/opencode_sessions.json"),
                timeout_s=int(opencode_data.get("timeout_s") or 3600),
                allow_commit=bool(opencode_data.get("allow_commit", True)),
                allow_push=bool(opencode_data.get("allow_push", True)),
                dangerously_skip_permissions=bool(opencode_data.get("dangerously_skip_permissions", False)),
                model=normalize_model_name(opencode_data.get("model") or DEFAULT_OPENCODE_MODEL),
                max_response_chars=int(opencode_data.get("max_response_chars") or 12000),
                require_confirmation_patterns=tuple(
                    str(item).lower() for item in opencode_data.get("require_confirmation_patterns", []) if str(item).strip()
                ),
            ),
            None,
        )
    except (TypeError, ValueError) as exc:
        return None, f"Configuracion opencode_remote invalida: {exc}"


def web_chat_ui_store() -> dict[str, Any]:
    payload = load_optional_json(WEB_CHAT_UI_STATE_PATH, {"users": {}})
    users = payload.get("users") if isinstance(payload, dict) else None
    if not isinstance(users, dict):
        return {"users": {}}
    return payload


def web_chat_history(user_key: str) -> list[dict[str, Any]]:
    payload = web_chat_ui_store()
    user_state = payload["users"].get(user_key, {})
    messages = user_state.get("messages") if isinstance(user_state, dict) else []
    return messages if isinstance(messages, list) else []


def save_web_chat_history(user_key: str, messages: list[dict[str, Any]]) -> None:
    payload = web_chat_ui_store()
    user_state = payload["users"].setdefault(user_key, {})
    user_state["messages"] = messages[-80:]
    user_state["updated_at"] = datetime.now().isoformat()
    write_json(WEB_CHAT_UI_STATE_PATH, payload)


def append_web_chat_message(user_key: str, role: str, text: str, *, model: str | None = None, error: bool = False) -> None:
    messages = web_chat_history(user_key)
    messages.append(
        {
            "role": role,
            "text": str(text or "").strip(),
            "created_at": datetime.now().isoformat(),
            "model": model,
            "error": error,
        }
    )
    save_web_chat_history(user_key, messages)


def clear_web_chat_history(user_key: str) -> None:
    payload = web_chat_ui_store()
    user_state = payload["users"].setdefault(user_key, {})
    user_state["messages"] = []
    user_state["updated_at"] = datetime.now().isoformat()
    write_json(WEB_CHAT_UI_STATE_PATH, payload)


def clear_web_chat_confirmation(store: SessionStore, user_key: str) -> None:
    data = store.load()
    data.get("confirmations", {}).pop(user_key, None)
    store.save(data)


def web_chat_pending_confirmation(store: SessionStore, user_key: str) -> dict[str, Any] | None:
    pending = store.load().get("confirmations", {}).get(user_key)
    if not isinstance(pending, dict):
        return None
    return {
        "id": str(pending.get("id") or "").strip(),
        "reason": str(pending.get("reason") or "Confirmacion requerida.").strip(),
        "created_at": pending.get("created_at"),
        "preview": preview_user_message(str(pending.get("message") or "")),
    }


def preview_user_message(text: str, limit: int = 220) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def web_chat_policy_block(text: str, config: OpenCodeRemoteConfig) -> str | None:
    wants_commit, wants_push = command_mentions_commit_or_push(text)
    if wants_commit and not config.allow_commit:
        return "Los commits estan deshabilitados en `opencode_remote.allow_commit`."
    if wants_push and not config.allow_push:
        return "Los push estan deshabilitados en `opencode_remote.allow_push`."
    return None


def web_chat_state(request: Request, config: OpenCodeRemoteConfig | None, config_error: str | None = None) -> dict[str, Any]:
    user_key = web_chat_identity(request)
    store = SessionStore(config.session_store) if config else None
    active_model = (store.get_model(user_key) if store else None) or (config.model if config else DEFAULT_OPENCODE_MODEL)
    session_id = store.get_session(user_key) if store else None
    return {
        "available": bool(config and not config_error),
        "error": config_error,
        "history": web_chat_history(user_key),
        "active_model": active_model,
        "default_model": config.model if config else DEFAULT_OPENCODE_MODEL,
        "session_id": session_id,
        "pending_confirmation": web_chat_pending_confirmation(store, user_key) if store else None,
        "config_path": str(OPENCODE_REMOTE_CONFIG_PATH.relative_to(ROOT)),
    }


def json_auth_guard(request: Request) -> JSONResponse | None:
    if authenticated(request):
        return None
    return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)


ACTION_LABELS = {
    "done": "Marcada como hecha",
    "skipped": "Marcada como no realizada",
    "alternative_requested": "Alternativa solicitada",
}


ACTION_BADGES = {
    "done": ("Hecha", "ok"),
    "skipped": ("No realizada", "warn"),
    "alternative_requested": ("Alternativa pedida", "warn"),
}

FEEDBACK_COMPLIANCE_LABELS = {
    "full": "La hice como tocaba",
    "partial": "La hice parcialmente",
    "modified": "La adapte",
    "aborted": "La corte",
}

FEEDBACK_TIME_FEELING_LABELS = {
    "spare": "Iba sobrado de tiempo",
    "ok": "Tiempo suficiente",
    "tight": "Iba justo de tiempo",
    "cut_short": "Tuve que recortar por tiempo",
}


def planned_workout_actions() -> dict[str, dict[str, Any]]:
    payload = load_optional_json(PLANNED_ACTIONS_PATH, {"workouts": {}})
    workouts = payload.get("workouts") if isinstance(payload, dict) else {}
    return workouts if isinstance(workouts, dict) else {}


def planned_workout_action(slug: str) -> dict[str, Any] | None:
    action = planned_workout_actions().get(slug)
    return action if isinstance(action, dict) else None


def action_display_data(action_key: str | None) -> dict[str, str] | None:
    if not action_key:
        return None
    label, tone = ACTION_BADGES.get(action_key, (action_key, ""))
    return {"label": label, "tone": tone}


def set_planned_workout_action(slug: str, workout: dict[str, Any], action_key: str, username: str | None) -> None:
    payload = load_optional_json(PLANNED_ACTIONS_PATH, {"workouts": {}})
    if not isinstance(payload, dict):
        payload = {"workouts": {}}
    workouts = payload.setdefault("workouts", {})
    workouts[slug] = {
        "action": action_key,
        "label": ACTION_LABELS.get(action_key, action_key),
        "updated_at": datetime.now().isoformat(),
        "date": workout.get("date"),
        "name": workout.get("name"),
        "updated_by": username or "web",
    }
    write_json(PLANNED_ACTIONS_PATH, payload)


def clear_planned_workout_action(slug: str) -> None:
    payload = load_optional_json(PLANNED_ACTIONS_PATH, {"workouts": {}})
    if not isinstance(payload, dict):
        return
    workouts = payload.get("workouts")
    if not isinstance(workouts, dict):
        return
    workouts.pop(slug, None)
    write_json(PLANNED_ACTIONS_PATH, payload)


def garmin_retry_states() -> dict[str, dict[str, Any]]:
    payload = load_optional_json(GARMIN_RETRY_STATE_PATH, {"workouts": {}})
    workouts = payload.get("workouts") if isinstance(payload, dict) else {}
    return workouts if isinstance(workouts, dict) else {}


def set_garmin_retry_state(slug: str, state: dict[str, Any]) -> None:
    payload = load_optional_json(GARMIN_RETRY_STATE_PATH, {"workouts": {}})
    if not isinstance(payload, dict):
        payload = {"workouts": {}}
    workouts = payload.setdefault("workouts", {})
    workouts[slug] = state
    write_json(GARMIN_RETRY_STATE_PATH, payload)


def garmin_status_badge(upload: dict[str, Any], retry_state: dict[str, Any] | None, workout_url: str | None) -> dict[str, str]:
    if retry_state and retry_state.get("status") == "error":
        return {"label": "Error Garmin", "tone": "warn"}
    if retry_state and retry_state.get("status") == "success":
        return {"label": "Reenvio OK", "tone": "ok"}
    if workout_url or upload:
        return {"label": "Sincronizado", "tone": "ok"}
    return {"label": "Pendiente Garmin", "tone": ""}


def completed_feedback_items() -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for path in sorted(COMPLETED_FEEDBACK_DIR.glob("*.feedback.json")):
        payload = load_json(path)
        if isinstance(payload, dict):
            items[path.stem.replace(".feedback", "")] = payload
    return items


def completed_feedback_detail(slug: str) -> dict[str, Any] | None:
    item = completed_feedback_items().get(slug)
    return item if isinstance(item, dict) else None


def response_pattern_badge(status: str) -> dict[str, str]:
    mapping = {
        "positive": {"label": "Favorable", "tone": "ok"},
        "mixed": {"label": "Mixto", "tone": ""},
        "watch": {"label": "Vigilar", "tone": "warn"},
        "unknown": {"label": "Sin datos", "tone": ""},
    }
    return mapping.get(status, mapping["unknown"])


def to_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def athlete_response_patterns() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for payload in completed_feedback_items().values():
        athlete_feedback = payload.get("athlete_feedback", {}) if isinstance(payload, dict) else {}
        if not isinstance(athlete_feedback, dict):
            continue
        records.append(
            {
                "date": iso_date_string(payload.get("date")),
                "updated_at": str(payload.get("updated_at") or ""),
                "rpe": to_int_or_none(athlete_feedback.get("rpe")),
                "pain_level": to_int_or_none(athlete_feedback.get("pain_level")),
                "pain_location": str(athlete_feedback.get("pain_location") or "").strip(),
                "compliance": str(athlete_feedback.get("compliance") or "").strip(),
                "time_feeling": str(athlete_feedback.get("time_feeling") or "").strip(),
                "note": str(athlete_feedback.get("note") or "").strip(),
            }
        )

    records.sort(key=lambda item: (item["date"], item["updated_at"]), reverse=True)
    recent = records[:6]
    if not recent:
        return {
            "headline": "Todavia no hay feedback suficiente para aprender patrones del atleta.",
            "window_label": "Sin sesiones con feedback",
            "patterns": [
                {
                    "label": "Tolerancia reciente",
                    "status": "unknown",
                    "badge": response_pattern_badge("unknown"),
                    "summary": "Aun no hay sesiones valoradas.",
                },
                {
                    "label": "Dolor reportado",
                    "status": "unknown",
                    "badge": response_pattern_badge("unknown"),
                    "summary": "No hay senales subjetivas de dolor todavia.",
                },
                {
                    "label": "Adherencia",
                    "status": "unknown",
                    "badge": response_pattern_badge("unknown"),
                    "summary": "No se puede estimar cumplimiento aun.",
                },
            ],
            "notes": [],
        }

    rpe_values = [item["rpe"] for item in recent if item.get("rpe") is not None]
    pain_values = [item["pain_level"] for item in recent if item.get("pain_level") is not None]
    avg_rpe = sum(rpe_values) / len(rpe_values) if rpe_values else None
    avg_pain = sum(pain_values) / len(pain_values) if pain_values else None
    high_pain_count = sum(1 for value in pain_values if value >= 4)
    high_rpe_count = sum(1 for value in rpe_values if value >= 8)
    modified_or_aborted = sum(1 for item in recent if item.get("compliance") in {"modified", "aborted"})
    location_counts: dict[str, int] = {}
    for item in recent:
        pain_level = item.get("pain_level")
        if pain_level is not None and pain_level >= 3 and item.get("pain_location"):
            key = str(item["pain_location"]).lower()
            location_counts[key] = location_counts.get(key, 0) + 1
    repeated_location = max(location_counts, key=location_counts.get) if location_counts else ""
    repeated_location_count = location_counts.get(repeated_location, 0)

    compliance_score_map = {"full": 1.0, "partial": 0.6, "modified": 0.35, "aborted": 0.0}
    compliance_scores = [compliance_score_map.get(item.get("compliance"), 0.5) for item in recent]
    adherence_score = sum(compliance_scores) / len(compliance_scores) if compliance_scores else 0.0

    tolerance_status = "mixed"
    tolerance_summary = "La carga parece tolerable, pero aun sin patron totalmente limpio."
    if avg_pain is not None and avg_rpe is not None:
        if avg_pain <= 2.0 and avg_rpe <= 6.5 and modified_or_aborted == 0:
            tolerance_status = "positive"
            tolerance_summary = "Las ultimas sesiones sugieren que la carga reciente se esta absorbiendo bien."
        elif avg_pain >= 4.0 or high_rpe_count >= 2 or modified_or_aborted >= 2:
            tolerance_status = "watch"
            tolerance_summary = "La respuesta reciente apunta a un coste alto; conviene frenar progresion o recortar densidad."

    pain_status = "mixed"
    pain_summary = "El dolor existe, pero sin una alarma repetida clara en el feedback reciente."
    if avg_pain is not None:
        if avg_pain <= 2.0 and high_pain_count == 0:
            pain_status = "positive"
            pain_summary = "El dolor reportado esta en zona tranquila durante las ultimas sesiones con feedback."
        elif high_pain_count >= 2 or (repeated_location and repeated_location_count >= 2):
            pain_status = "watch"
            location_text = f" en {repeated_location}" if repeated_location else ""
            pain_summary = f"Se repite dolor relevante{location_text}; esto deberia pesar en la siguiente decision de carga."

    adherence_status = "mixed"
    adherence_summary = "La adherencia es utilizable, pero todavia con desviaciones en la ejecucion."
    if adherence_score >= 0.85:
        adherence_status = "positive"
        adherence_summary = "El atleta esta completando casi todo lo previsto sin necesidad de grandes ajustes."
    elif adherence_score < 0.55:
        adherence_status = "watch"
        adherence_summary = "La adherencia reciente es fragil; el plan puede estar pidiendo mas de lo que cabe absorber o encajar."

    notes = [
        {"date": item["date"], "note": item["note"], "summary": feedback_summary({"athlete_feedback": item})}
        for item in recent
        if item.get("note")
    ][:3]
    return {
        "headline": "Patrones simples derivados del feedback subjetivo reciente.",
        "window_label": f"Ultimas {len(recent)} sesiones con feedback",
        "patterns": [
            {
                "label": "Tolerancia reciente",
                "status": tolerance_status,
                "badge": response_pattern_badge(tolerance_status),
                "summary": tolerance_summary,
            },
            {
                "label": "Dolor reportado",
                "status": pain_status,
                "badge": response_pattern_badge(pain_status),
                "summary": pain_summary,
            },
            {
                "label": "Adherencia",
                "status": adherence_status,
                "badge": response_pattern_badge(adherence_status),
                "summary": adherence_summary,
            },
        ],
        "notes": notes,
    }


def adaptation_triggers(dashboard: dict[str, Any]) -> dict[str, Any]:
    decision = dashboard.get("decision", {}) if isinstance(dashboard, dict) else {}
    reasons = decision.get("reasons", []) if isinstance(decision.get("reasons"), list) else []
    daily_signals = decision.get("daily_signals", {}) if isinstance(decision.get("daily_signals"), dict) else {}
    goal_metrics = dashboard.get("goal_gates", {}).get("metrics", {}) if isinstance(dashboard.get("goal_gates"), dict) else {}
    response_patterns = dashboard.get("response_patterns", {}) if isinstance(dashboard.get("response_patterns"), dict) else {}
    reviews = completed_reviews()
    latest_review = reviews[0] if reviews else None
    recent_feedback = completed_feedback_items()
    recent_feedback_item = None
    if latest_review:
        recent_feedback_item = recent_feedback.get(latest_review.get("slug"))
    athlete_feedback = recent_feedback_item.get("athlete_feedback", {}) if isinstance(recent_feedback_item, dict) else {}
    athlete_feedback = athlete_feedback if isinstance(athlete_feedback, dict) else {}

    triggers: list[dict[str, Any]] = []

    volume_spike = decision.get("volume_spike_pct")
    hrv_flag = str(daily_signals.get("hrv_flag") or "").strip()
    readiness_flag = str(daily_signals.get("readiness_flag") or "").strip()
    resting_hr_flag = str(daily_signals.get("resting_hr_flag") or "").strip()
    fatigue_active = False
    fatigue_reasons: list[str] = []
    if volume_spike is not None and float(volume_spike) >= 25.0:
        fatigue_active = True
        fatigue_reasons.append(f"Volumen 7d +{round(float(volume_spike))}% frente a la semana previa")
    if hrv_flag in {"low", "suppressed"}:
        fatigue_active = True
        fatigue_reasons.append("HRV por debajo de la banda habitual")
    if readiness_flag in {"low", "poor"}:
        fatigue_active = True
        fatigue_reasons.append("Readiness diaria baja")
    if resting_hr_flag == "high":
        fatigue_active = True
        fatigue_reasons.append("Pulso en reposo por encima de lo normal")
    if decision.get("status") == "red" and reasons:
        fatigue_reasons.append(str(reasons[0]))
    triggers.append(
        {
            "key": "fatigue",
            "label": "Fatiga / carga",
            "active": fatigue_active,
            "badge": response_pattern_badge("watch" if fatigue_active else "positive"),
            "summary": "; ".join(fatigue_reasons[:2]) if fatigue_reasons else "No hay senal clara de fatiga aguda en los datos visibles.",
            "plan_change": "Bajar coste de la siguiente sesion: quitar calidad, recortar volumen o mover a rodaje muy facil." if fatigue_active else "Se puede mantener la estructura actual sin progresar por este trigger.",
        }
    )

    latest_shin_pain = goal_metrics.get("latest_shin_pain")
    pain_pattern = next((item for item in response_patterns.get("patterns", []) if item.get("label") == "Dolor reportado"), None)
    pain_active = bool((latest_shin_pain is not None and float(latest_shin_pain) > 2.0) or (pain_pattern and pain_pattern.get("status") == "watch"))
    pain_reasons: list[str] = []
    if latest_shin_pain is not None:
        pain_reasons.append(f"Periostio actual {latest_shin_pain}/10")
    if pain_pattern and pain_pattern.get("status") == "watch":
        pain_reasons.append(str(pain_pattern.get("summary") or ""))
    triggers.append(
        {
            "key": "pain",
            "label": "Dolor / lesion",
            "active": pain_active,
            "badge": response_pattern_badge("watch" if pain_active else "positive"),
            "summary": "; ".join([item for item in pain_reasons if item][:2]) if pain_reasons else "No hay senal clara de dolor que obligue a adaptar por si sola.",
            "plan_change": "Proteger tejido: evitar impacto de calidad, bajar agresividad mecanica o incluso descansar." if pain_active else "No hace falta ajustar el plan por dolor ahora mismo.",
        }
    )

    time_feeling = str(athlete_feedback.get("time_feeling") or "").strip()
    compliance = str(athlete_feedback.get("compliance") or "").strip()
    action_keys = [
        str((item or {}).get("action") or "")
        for item in planned_workout_actions().values()
        if isinstance(item, dict)
    ]
    time_active = time_feeling in {"tight", "cut_short"} or "alternative_requested" in action_keys
    time_signals: list[str] = []
    if time_feeling in FEEDBACK_TIME_FEELING_LABELS:
        time_signals.append(FEEDBACK_TIME_FEELING_LABELS[time_feeling])
    if "alternative_requested" in action_keys:
        time_signals.append("Hay una sesion marcada con alternativa solicitada")
    if compliance in {"partial", "modified"} and time_feeling in {"tight", "cut_short"}:
        time_signals.append("La ejecucion reciente ya se vio recortada por agenda")
    triggers.append(
        {
            "key": "time",
            "label": "Tiempo disponible",
            "active": time_active,
            "badge": response_pattern_badge("watch" if time_active else "positive"),
            "summary": "; ".join(time_signals[:2]) if time_signals else "No hay senal reciente de que la agenda este rompiendo el plan.",
            "plan_change": "Sustituir por version corta, compacta o mas facil de encajar sin perder continuidad." if time_active else "No hace falta compactar la sesion por agenda.",
        }
    )

    adherence_pattern = next((item for item in response_patterns.get("patterns", []) if item.get("label") == "Adherencia"), None)
    execution_active = False
    execution_signals: list[str] = []
    if latest_review and str(latest_review.get("traffic_light") or "").lower() in {"amarillo", "rojo"}:
        execution_active = True
        execution_signals.append(f"Ultima review en {latest_review.get('traffic_light')}")
    if compliance in {"modified", "aborted", "partial"}:
        execution_active = True
        execution_signals.append(FEEDBACK_COMPLIANCE_LABELS.get(compliance, compliance))
    if adherence_pattern and adherence_pattern.get("status") == "watch":
        execution_active = True
        execution_signals.append(str(adherence_pattern.get("summary") or ""))
    triggers.append(
        {
            "key": "execution",
            "label": "Ejecucion real",
            "active": execution_active,
            "badge": response_pattern_badge("watch" if execution_active else "positive"),
            "summary": "; ".join([item for item in execution_signals if item][:2]) if execution_signals else "La ejecucion reciente no obliga por si sola a cambiar el siguiente paso.",
            "plan_change": "Repetir familia mas controlable o bajar densidad antes de volver a progresar." if execution_active else "La siguiente progresion no necesita frenarse por ejecucion.",
        }
    )

    active_count = sum(1 for item in triggers if item["active"])
    return {
        "headline": "Mapa simple trigger -> cambio de plan para explicar por que RunPilot adapta la siguiente decision.",
        "summary": f"{active_count} trigger(s) activos ahora mismo.",
        "triggers": triggers,
    }


def active_trigger_labels(dashboard: dict[str, Any]) -> list[str]:
    items = dashboard.get("adaptation_triggers", {}).get("triggers", []) if isinstance(dashboard, dict) else []
    return [str(item.get("label") or "") for item in items if isinstance(item, dict) and item.get("active") and item.get("label")]


def planned_workout_replan_data(
    workout: dict[str, Any],
    dashboard: dict[str, Any] | None = None,
    linked_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dashboard = dashboard or dashboard_payload()
    action_state = workout.get("action_state") if isinstance(workout.get("action_state"), dict) else None
    action_key = str((action_state or {}).get("action") or "")
    action_updated_at = format_datetime((action_state or {}).get("updated_at")) if action_state else None
    decision = dashboard.get("decision", {}) if isinstance(dashboard, dict) else {}
    trigger_labels = active_trigger_labels(dashboard)
    primary_labels = list((decision.get("session_guidance", {}) or {}).get("primary_labels") or [])
    recommendation = str(decision.get("recommendation") or "").strip()
    workout_date = parse_iso_date(workout.get("date"))
    is_upcoming = bool(workout_date and workout_date >= date.today())
    status = "original"
    label = "Original"
    tone = ""
    summary = "La sesion sigue tal como estaba planificada."
    cause = "Sin trigger visible que obligue a cambiarla."
    changed_at = None
    variant = None

    if action_key == "alternative_requested":
        status = "adjusted"
        label = "Ajustada"
        tone = "warn"
        summary = "El atleta pidio una alternativa para esta sesion."
        cause = "Cambio manual desde la web para adaptar la sesion al contexto del dia."
        changed_at = action_updated_at
        variant = primary_labels[0] if primary_labels else None
    elif action_key == "skipped":
        status = "adjusted"
        label = "Ajustada"
        tone = "warn"
        summary = "La sesion quedo marcada como no realizada."
        cause = "La siguiente decision deberia recolocar o absorber esta carga perdida."
        changed_at = action_updated_at
    elif linked_review:
        athlete_feedback = linked_review.get("athlete_feedback", {}).get("athlete_feedback", {}) if isinstance(linked_review.get("athlete_feedback"), dict) else {}
        compliance = str(athlete_feedback.get("compliance") or "").strip()
        if compliance in {"partial", "modified", "aborted"}:
            status = "adjusted"
            label = "Ajustada"
            tone = "warn"
            summary = "La ejecucion real no coincidió del todo con lo prescrito."
            cause = FEEDBACK_COMPLIANCE_LABELS.get(compliance, "Feedback subjetivo con desviacion de la sesion.")
            changed_at = format_datetime(linked_review.get("athlete_feedback", {}).get("updated_at")) if linked_review.get("athlete_feedback") else None
        elif str(linked_review.get("traffic_light") or "").lower() in {"amarillo", "rojo"}:
            status = "adjusted"
            label = "Ajustada"
            tone = "warn"
            summary = "La review de la sesion pide prudencia antes de progresar."
            cause = str(linked_review.get("compliance_note") or "").strip()
    elif is_upcoming and decision.get("status") == "red" and workout.get("session_kind") in {"quality", "long_run"}:
        status = "protected"
        label = "Protegida"
        tone = "warn"
        summary = "La sesion deberia ejecutarse en version protectora o sustituirse."
        cause = ", ".join(trigger_labels[:2]) if trigger_labels else recommendation or "La decision actual del coach esta en rojo."
        changed_at = dashboard.get("as_of")
        variant = primary_labels[0] if primary_labels else None
    elif is_upcoming and decision.get("status") == "yellow" and workout.get("session_kind") == "quality":
        status = "adjusted"
        label = "Ajustable"
        tone = "warn"
        summary = "Conviene hacerla con margen o recorte si el dia no acompana."
        cause = ", ".join(trigger_labels[:2]) if trigger_labels else recommendation or "La decision actual pide cautela."
        changed_at = dashboard.get("as_of")
        variant = primary_labels[0] if primary_labels else None

    return {
        "status": status,
        "label": label,
        "tone": tone,
        "summary": summary,
        "cause": cause,
        "changed_at": changed_at,
        "variant": variant,
        "is_changed": status in {"adjusted", "protected", "adjustable"},
    }


def protection_mode_payload(dashboard: dict[str, Any]) -> dict[str, Any]:
    decision = dashboard.get("decision", {}) if isinstance(dashboard, dict) else {}
    goal_metrics = dashboard.get("goal_gates", {}).get("metrics", {}) if isinstance(dashboard.get("goal_gates"), dict) else {}
    response_patterns = dashboard.get("response_patterns", {}) if isinstance(dashboard.get("response_patterns"), dict) else {}
    latest_shin_entry = decision.get("latest_shin_entry") if isinstance(decision.get("latest_shin_entry"), dict) else {}
    latest_shin_pain = goal_metrics.get("latest_shin_pain")
    pain_pattern = next((item for item in response_patterns.get("patterns", []) if item.get("label") == "Dolor reportado"), None)
    adherence_pattern = next((item for item in response_patterns.get("patterns", []) if item.get("label") == "Adherencia"), None)
    fatigue_trigger = next((item for item in dashboard.get("adaptation_triggers", {}).get("triggers", []) if item.get("key") == "fatigue"), None)
    shin_band = str((decision.get("session_guidance", {}) or {}).get("shin_band") or "").strip().lower()
    next_morning = latest_shin_entry.get("pain_next_morning") if isinstance(latest_shin_entry, dict) else None
    triggers: list[str] = []

    pain_value = float(latest_shin_pain) if latest_shin_pain is not None else None
    if pain_value is not None and pain_value >= 4.0:
        triggers.append(f"Periostio {pain_value:.0f}/10")
    if next_morning is not None and float(next_morning) >= 4.0:
        triggers.append("Reaccion alta al dia siguiente")
    if shin_band == "red":
        triggers.append("Banda tibial roja")
    if pain_pattern and pain_pattern.get("status") == "watch":
        triggers.append("Dolor subjetivo repetido")

    if triggers:
        return {
            "active": True,
            "key": "injury_protection",
            "label": "Modo lesion",
            "tone": "warn",
            "summary": "La prioridad pasa a proteger tejido y reducir el coste mecanico antes de volver a construir.",
            "allowed_progression": "No se permite progresar carga. Solo mantener o reducir hasta volver a banda verde.",
            "guidance_note": "Evita calidad, cuestas y tiradas largas agresivas. Usa solo rodajes muy faciles, movilidad o descanso.",
            "quality_cap_label": "sin calidad",
            "triggers": triggers,
        }

    return_triggers: list[str] = []
    if (pain_value is not None and pain_value >= 2.0) or shin_band == "yellow":
        return_triggers.append("Periostio aun sensible")
    if next_morning is not None and float(next_morning) >= 2.0:
        return_triggers.append("Hay reaccion al dia siguiente")
    if adherence_pattern and adherence_pattern.get("status") == "watch":
        return_triggers.append("La tolerancia todavia no es repetible")
    if fatigue_trigger and fatigue_trigger.get("active"):
        return_triggers.append("La fatiga actual desaconseja progresar")
    if decision.get("status") in {"red", "yellow"} and str(decision.get("recommendation") or ""):
        return_triggers.append("La decision diaria aun pide prudencia")
    if return_triggers:
        return {
            "active": True,
            "key": "return_to_running",
            "label": "Modo retorno",
            "tone": "warn",
            "summary": "El sistema debe priorizar continuidad, control de FC y respuesta del periostio antes de volver a empujar.",
            "allowed_progression": "Solo progresion minima y ganada: repetir familias seguras antes de aumentar densidad o ritmo.",
            "guidance_note": "Prioriza rodajes suaves, recuperacion y sesiones de bajo coste. La calidad solo entra si la semana sale limpia.",
            "quality_cap_label": "mini-progresion",
            "triggers": return_triggers[:3],
        }

    return {
        "active": False,
        "key": "normal_build",
        "label": "Construccion normal",
        "tone": "ok",
        "summary": "No hay senales suficientes para activar un modo lesion o retorno.",
        "allowed_progression": "Se puede progresar con prudencia normal del bloque.",
        "guidance_note": "",
        "quality_cap_label": None,
        "triggers": [],
    }


def readiness_card_payload(dashboard: dict[str, Any]) -> dict[str, Any]:
    daily_metrics = dashboard.get("daily_metrics", {}) if isinstance(dashboard, dict) else {}
    data_quality = dashboard.get("data_quality", {}) if isinstance(dashboard, dict) else {}
    decision = dashboard.get("decision", {}) if isinstance(dashboard, dict) else {}
    daily_signals = decision.get("daily_signals", {}) if isinstance(decision.get("daily_signals"), dict) else {}
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard, dict) else {}

    latest_date = parse_iso_date(daily_metrics.get("latest_date") or data_quality.get("latest_daily_date"))
    stale = latest_date is None or latest_date < date.today()
    readiness = daily_metrics.get("latest_training_readiness")
    hrv = daily_metrics.get("latest_hrv")
    resting_hr = daily_metrics.get("latest_resting_heart_rate")
    hrv_flag = str(daily_signals.get("hrv_flag") or "").strip()
    readiness_flag = str(daily_signals.get("readiness_flag") or "").strip()
    resting_hr_flag = str(daily_signals.get("resting_hr_flag") or "").strip()
    signals: list[str] = []

    if readiness is not None:
        signals.append(f"Readiness {int(readiness)}")
    elif data_quality.get("available", {}).get("training_readiness") is False:
        signals.append("Readiness no disponible")
    if hrv is not None:
        signals.append(f"HRV {int(hrv)}")
    if resting_hr is not None:
        signals.append(f"Resting HR {int(resting_hr)}")

    if stale:
        return {
            "state": "stale",
            "label": "Readiness desactualizada",
            "tone": "warn",
            "summary": "La última señal diaria no es de hoy, así que conviene leerla con cautela.",
            "action": "No tomes decisiones finas por readiness. Usa el modo de protección y la decisión global como referencia principal.",
            "detail": f"Último dato diario: {latest_date.isoformat() if latest_date else '-'}.",
            "source_label": latest_date.isoformat() if latest_date else "Sin fecha diaria",
            "signals": signals,
        }

    if protection_mode.get("active"):
        return {
            "state": "protected",
            "label": "Readiness protegida",
            "tone": "warn",
            "summary": "Aunque las señales diarias no sean malas, hoy manda el contexto de protección o retorno.",
            "action": protection_mode.get("allowed_progression") or "Mantén la progresión limitada.",
            "detail": protection_mode.get("summary") or "El modo actual impone prudencia adicional.",
            "source_label": latest_date.isoformat() if latest_date else "Hoy",
            "signals": signals,
        }

    if readiness_flag in {"low", "poor"} or hrv_flag in {"low", "suppressed"} or resting_hr_flag == "high":
        return {
            "state": "protected",
            "label": "Readiness protegida",
            "tone": "warn",
            "summary": "Las señales diarias sugieren no empujar hoy aunque el plan original lo permita.",
            "action": "Recorta intensidad o cambia a versión fácil si el día no se siente limpio.",
            "detail": "Una o más señales diarias salen de la banda cómoda esperada.",
            "source_label": latest_date.isoformat() if latest_date else "Hoy",
            "signals": signals,
        }

    if readiness is not None and int(readiness) >= 75 and hrv_flag in {"stable", "good", "high"} and resting_hr_flag in {"normal", "low", ""}:
        return {
            "state": "fresh",
            "label": "Readiness fresca",
            "tone": "ok",
            "summary": "Las señales diarias son suficientemente limpias para ejecutar lo previsto sin añadir protección extra.",
            "action": "Puedes seguir la sesión del día tal como está, manteniendo la prudencia normal del bloque.",
            "detail": "Readiness alta o señales estables de HRV y pulso en reposo.",
            "source_label": latest_date.isoformat() if latest_date else "Hoy",
            "signals": signals,
        }

    if any(item for item in [readiness, hrv, resting_hr] if item is not None):
        return {
            "state": "neutral",
            "label": "Readiness neutra",
            "tone": "",
            "summary": "No hay una señal diaria fuerte ni para apretar ni para proteger más de la cuenta.",
            "action": "Sigue el plan con margen y deja que la sensación de calentamiento confirme la sesión.",
            "detail": "Las métricas disponibles no disparan ni verde claro ni alerta directa.",
            "source_label": latest_date.isoformat() if latest_date else "Hoy",
            "signals": signals,
        }

    return {
        "state": "missing",
        "label": "Sin readiness disponible",
        "tone": "warn",
        "summary": "Faltan señales diarias para traducir el estado de hoy a una acción clara.",
        "action": "Apóyate en la decisión global y mantén margen conservador.",
        "detail": "No hay métricas diarias suficientes o están desactualizadas.",
        "source_label": latest_date.isoformat() if latest_date else "Sin dato diario",
        "signals": signals,
    }


def feedback_badge(feedback: dict[str, Any] | None) -> dict[str, str] | None:
    if not feedback:
        return None
    return {"label": "Con feedback", "tone": "ok"}


def feedback_summary(feedback: dict[str, Any] | None) -> str | None:
    if not feedback:
        return None
    athlete_feedback = feedback.get("athlete_feedback", {})
    if not isinstance(athlete_feedback, dict):
        return None
    compliance = FEEDBACK_COMPLIANCE_LABELS.get(str(athlete_feedback.get("compliance") or ""))
    rpe = athlete_feedback.get("rpe")
    pain_level = athlete_feedback.get("pain_level")
    parts = []
    if rpe is not None:
        parts.append(f"RPE {rpe}/10")
    if pain_level is not None:
        parts.append(f"Dolor {pain_level}/10")
    if compliance:
        parts.append(compliance)
    return " · ".join(parts) if parts else None


def feedback_form_state(feedback: dict[str, Any] | None = None) -> dict[str, Any]:
    athlete_feedback = feedback.get("athlete_feedback", {}) if isinstance(feedback, dict) else {}
    athlete_feedback = athlete_feedback if isinstance(athlete_feedback, dict) else {}
    return {
        "rpe": athlete_feedback.get("rpe") or "",
        "pain_level": athlete_feedback.get("pain_level") if athlete_feedback.get("pain_level") is not None else "",
        "compliance": athlete_feedback.get("compliance") or "",
        "time_feeling": athlete_feedback.get("time_feeling") or "",
        "pain_location": athlete_feedback.get("pain_location") or "",
        "note": athlete_feedback.get("note") or "",
        "compliance_options": FEEDBACK_COMPLIANCE_LABELS,
        "time_feeling_options": FEEDBACK_TIME_FEELING_LABELS,
    }


def set_completed_feedback(
    slug: str,
    review: dict[str, Any],
    rpe: int,
    pain_level: int,
    compliance: str,
    time_feeling: str,
    pain_location: str,
    note: str,
    username: str | None,
) -> bool:
    path = COMPLETED_FEEDBACK_DIR / f"{slug}.feedback.json"
    existing = load_optional_json(path, {})
    created_at = existing.get("created_at") if isinstance(existing, dict) else None
    now = datetime.now().isoformat()
    payload = {
        "source": "web_manual_feedback",
        "created_at": created_at or now,
        "updated_at": now,
        "updated_by": username or "web",
        "date": review.get("date"),
        "planned_workout_slug": slug,
        "completed_review_slug": slug,
        "garmin_activity_id": review.get("garmin_activity_id"),
        "athlete_feedback": {
            "rpe": rpe,
            "pain_level": pain_level,
            "pain_location": pain_location or None,
            "compliance": compliance,
            "time_feeling": time_feeling or None,
            "note": note or None,
        },
    }
    write_json(path, payload)
    return bool(created_at)


def today_plan_data(day: str | None = None) -> dict[str, Any]:
    target_day = day or date.today().isoformat()
    dashboard = dashboard_payload()
    decision = dashboard.get("decision", {})
    guidance = decision.get("session_guidance", {})
    goal_metrics = dashboard.get("goal_gates", {}).get("metrics", {})
    daily_signals = decision.get("daily_signals", {})
    planned_today = next((item for item in planned_workouts() if item.get("date") == target_day), None)
    completed_today = next((item for item in completed_reviews() if item.get("date") == target_day), None)

    shin_pain = goal_metrics.get("latest_shin_pain")
    resting_hr_flag = daily_signals.get("resting_hr_flag")
    has_context = bool(decision) and decision.get("status") != "unknown"
    protective_mode = decision.get("status") == "red" or (shin_pain is not None and float(shin_pain) > 2.0)

    if not has_context:
        status = "insufficient_data"
    elif completed_today:
        status = "completed_today"
    elif planned_today and protective_mode:
        status = "protective_today"
    elif planned_today:
        status = "planned_today"
    else:
        status = "no_plan_today"

    status_labels = {
        "planned_today": "Listo para ejecutar",
        "completed_today": "Ya ejecutado",
        "no_plan_today": "Sin sesion planificada",
        "protective_today": "Protegido",
        "insufficient_data": "Pendiente de datos",
    }

    session_objective_map = {
        "recovery": "El objetivo hoy es absorber carga y proteger tejido.",
        "easy": "El objetivo hoy es sumar sin aumentar demasiado el coste.",
        "quality": "El objetivo hoy es estimular calidad dentro del margen permitido por el estado actual.",
        "long_run": "El objetivo hoy es construir durabilidad aerobica sin salirte del margen previsto.",
        "strength": "El objetivo hoy es consolidar fuerza util sin generar fatiga residual alta.",
        "race": "El objetivo hoy es ejecutar con control y aprovechar el contexto competitivo.",
    }

    why_today_parts = []
    if decision.get("recommendation"):
        why_today_parts.append(str(decision["recommendation"]).strip())
    if planned_today:
        objective_text = session_objective_map.get(planned_today.get("session_kind"), "El objetivo hoy es mantener continuidad con una carga adecuada.")
        why_today_parts.append(objective_text)
    elif has_context:
        why_today_parts.append("Hoy no hay sesion planificada; si entrenas, que sea opcional y conservador.")

    watchouts: list[str] = []
    if shin_pain is not None:
        watchouts.append(f"Periostio {shin_pain}/10")
    if decision.get("status") == "red":
        watchouts.append("No subir carga ni intensidad hoy.")
    elif resting_hr_flag == "high":
        watchouts.append("Pulso en reposo algo alto; deja margen.")
    watchouts = watchouts[:2]

    return {
        "date": target_day,
        "date_label": day_label(target_day),
        "status": status,
        "status_label": status_labels[status],
        "planned_workout": planned_today,
        "completed_review": completed_today,
        "decision": decision,
        "why_today": " ".join(why_today_parts).strip(),
        "watchouts": watchouts,
        "priorities": list(guidance.get("primary_labels") or [])[:2],
        "action_state": (planned_today or {}).get("action_state"),
        "action_badge": (planned_today or {}).get("action_badge"),
        "cta_enabled": bool(planned_today and not completed_today),
        "feedback_present": bool((completed_today or {}).get("athlete_feedback")),
        "links": {
            "detail_url": f"/planned-workouts/{planned_today['slug']}" if planned_today else None,
            "day_url": f"/calendar/day/{target_day}",
            "feedback_url": f"/completed-workouts/{completed_today['slug']}" if completed_today else None,
        },
    }


def safe_next_url(value: str | None, fallback: str) -> str:
    candidate = str(value or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return fallback


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


def parse_week_date_window(content: str) -> tuple[date | None, date | None]:
    match = re.search(r"Del `(?P<start>\d{4}-\d{2}-\d{2})` al `(?P<end>\d{4}-\d{2}-\d{2})`", content)
    if not match:
        return None, None
    return parse_iso_date(match.group("start")), parse_iso_date(match.group("end"))


def resolve_week_row_date(label: str, start_date: date | None, end_date: date | None) -> str | None:
    if not start_date or not end_date:
        return None
    match = re.search(r"(\d{1,2})$", str(label).strip())
    if not match:
        return None
    day_number = int(match.group(1))
    current = start_date
    while current <= end_date:
        if current.day == day_number:
            return current.isoformat()
        current = current.fromordinal(current.toordinal() + 1)
    return None


def week_page_data() -> dict[str, Any]:
    path = ACTIVE_WEEK_PATH
    content = read_text(path)
    rows = parse_week_table(content)
    start_date, end_date = parse_week_date_window(content)
    dashboard = dashboard_payload()
    planned_by_date = {item.get("date"): item for item in planned_workouts(dashboard) if item.get("date")}
    reviews_by_date = {item.get("date"): item for item in completed_reviews() if item.get("date")}
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        row_date = resolve_week_row_date(row.get("day", ""), start_date, end_date)
        linked_workout = planned_by_date.get(row_date) if row_date else None
        linked_review = reviews_by_date.get(row_date) if row_date else None
        replan = planned_workout_replan_data(linked_workout, dashboard, linked_review) if linked_workout else {
            "status": "original",
            "label": "Original",
            "tone": "",
            "summary": "Sin ajuste visible para este bloque.",
            "cause": "-",
            "changed_at": None,
            "variant": None,
            "is_changed": False,
        }
        enriched_rows.append(
            {
                **row,
                "date": row_date,
                "linked_workout": linked_workout,
                "linked_review": linked_review,
                "replan": replan,
            }
        )
    return {
        "exists": path.exists(),
        "content": content,
        "rows": enriched_rows,
        "pdf_exists": (ROOT / "planning" / "weeks" / "generated" / "semana_actual.pdf").exists(),
    }


def planned_upload_data(workout_stem: str, schedule_date: str) -> dict[str, Any]:
    upload_path = PLANNED_WORKOUTS_DIR / schedule_date / f"{workout_stem}.garmin_upload.json"
    return load_json(upload_path) if upload_path.exists() else {}


def planned_workout_file(slug: str) -> Path:
    return PLANNED_WORKOUTS_DIR / f"{slug}.yaml"


def retry_garmin_workout_sync(slug: str, username: str | None) -> tuple[bool, str]:
    workout_file = planned_workout_file(slug)
    attempted_at = datetime.now().isoformat()
    if not workout_file.exists():
        set_garmin_retry_state(
            slug,
            {
                "status": "error",
                "label": "Archivo no encontrado",
                "message": f"No existe {workout_file.relative_to(ROOT)}.",
                "updated_at": attempted_at,
                "updated_by": username or "web",
            },
        )
        return False, "No se encontro el archivo de la sesion planificada."

    command = [sys.executable, str(GARMIN_SYNC_SCRIPT), "schedule-workout-file", str(workout_file)]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300, check=False)
    except subprocess.TimeoutExpired:
        set_garmin_retry_state(
            slug,
            {
                "status": "error",
                "label": "Timeout Garmin",
                "message": "La subida a Garmin excedio el tiempo maximo.",
                "updated_at": attempted_at,
                "updated_by": username or "web",
            },
        )
        return False, "El reenvio a Garmin tardo demasiado y se corto."

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode == 0:
        set_garmin_retry_state(
            slug,
            {
                "status": "success",
                "label": "Reenvio OK",
                "message": stdout.splitlines()[-1] if stdout else "Sesion reenviada a Garmin.",
                "updated_at": attempted_at,
                "updated_by": username or "web",
            },
        )
        return True, "Sesion reenviada a Garmin."

    error_message = stderr.splitlines()[-1] if stderr else (stdout.splitlines()[-1] if stdout else f"Fallo de Garmin (exit {result.returncode}).")
    set_garmin_retry_state(
        slug,
        {
            "status": "error",
            "label": "Error Garmin",
            "message": error_message,
            "updated_at": attempted_at,
            "updated_by": username or "web",
        },
    )
    return False, f"No se pudo reenviar a Garmin: {error_message}"


def dashboard_payload() -> dict[str, Any]:
    status = workspace_status()
    response_patterns = athlete_response_patterns()
    pipeline_status = automation_pipeline_status()
    if not COACH_DECISION_PATH.exists():
        payload = empty_dashboard_payload(status)
        payload["response_patterns"] = response_patterns
        payload["adaptation_triggers"] = adaptation_triggers(payload)
        payload["protection_mode"] = protection_mode_payload(payload)
        payload["readiness_card"] = readiness_card_payload(payload)
        payload["automation_pipeline"] = pipeline_status
        return payload
    decision_capability = ensure_fresh("coach_decision")
    path = COACH_DECISION_PATH
    payload = load_json(path) if path.exists() else {}
    payload["capability_messages"] = [message for message in [decision_capability.warning] if message]
    payload["response_patterns"] = response_patterns
    payload["adaptation_triggers"] = adaptation_triggers(payload)
    payload["protection_mode"] = protection_mode_payload(payload)
    payload["readiness_card"] = readiness_card_payload(payload)
    payload["automation_pipeline"] = pipeline_status

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
        protection_mode = payload.get("protection_mode", {})
        if protection_mode.get("active"):
            guidance["protection_note"] = protection_mode.get("guidance_note")
            if protection_mode.get("quality_cap_label"):
                guidance["quality_volume_cap"] = protection_mode.get("quality_cap_label")
            if protection_mode.get("key") == "injury_protection":
                guidance["primary_labels"] = ["Rodaje de recuperacion", "Recuperacion con movilidad"]
                guidance["avoid_labels"] = list(dict.fromkeys(["Tempo continuo", "Cruise intervals", "Tirada larga con calidad"] + list(guidance.get("avoid_labels") or [])))
            elif protection_mode.get("key") == "return_to_running":
                guidance["primary_labels"] = ["Rodaje aerobico Z2", "Rodaje de recuperacion"]
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

    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard, dict) else {}
    if protection_mode.get("active"):
        metrics.append(
            {
                "label": "Progreso permitido ahora",
                "value": 15 if protection_mode.get("key") == "injury_protection" else 35,
                "value_label": protection_mode.get("label") or "Protegido",
                "detail": protection_mode.get("allowed_progression") or "La progresion queda limitada por el modo actual.",
                "tone": "warn",
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
        if protection_mode.get("key") == "injury_protection":
            probability = min(probability, 25)
        elif protection_mode.get("key") == "return_to_running":
            probability = min(probability, 45)
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


def progress_page_data() -> dict[str, Any]:
    dashboard = dashboard_payload()
    master_plan = master_plan_page_data()
    metrics = progress_metrics()
    goal_gates = dashboard.get("goal_gates", {}) if isinstance(dashboard.get("goal_gates"), dict) else {}
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard.get("protection_mode"), dict) else {}
    response_patterns = dashboard.get("response_patterns", {}) if isinstance(dashboard.get("response_patterns"), dict) else {}
    goal_race = dashboard.get("active_context", {}).get("goal_race") if isinstance(dashboard.get("active_context"), dict) else None

    headline = goal_gates.get("status_label") or "Progreso no disponible"
    summary = goal_gates.get("summary") or "Todavia no hay una lectura suficiente del progreso contra el objetivo."
    if protection_mode.get("active"):
        summary = f"{summary} Ahora mismo el sistema esta en {protection_mode.get('label', 'modo protegido').lower()}, asi que el progreso se mide primero por control y continuidad."

    focus_items: list[str] = []
    for gate in goal_gates.get("gates", []):
        if not gate.get("passed") and gate.get("next_step"):
            focus_items.append(str(gate.get("next_step")))
    focus_items = focus_items[:4]

    strengths: list[str] = []
    for gate in goal_gates.get("gates", []):
        if gate.get("passed"):
            strengths.append(f"Checkpoint superado: {gate.get('name')}")
    for pattern in response_patterns.get("patterns", []):
        if pattern.get("status") == "positive":
            strengths.append(str(pattern.get("summary") or ""))
    strengths = [item for item in strengths if item][:4]

    watchouts: list[str] = []
    if protection_mode.get("active") and protection_mode.get("triggers"):
        watchouts.extend([str(item) for item in protection_mode.get("triggers", []) if item])
    else:
        for item in dashboard.get("adaptation_triggers", {}).get("triggers", []):
            if item.get("active"):
                watchouts.append(str(item.get("summary") or ""))
    watchouts = [item for item in watchouts if item][:4]

    compact_metrics = metrics[:4]
    return {
        "headline": headline,
        "summary": summary,
        "goal_race": goal_race,
        "goal_gates": goal_gates,
        "metrics": compact_metrics,
        "all_metrics": metrics,
        "weekly_volume": dashboard.get("weekly_volume", []),
        "strengths": strengths,
        "watchouts": watchouts,
        "focus_items": focus_items,
        "protection_mode": protection_mode,
        "master_plan": master_plan,
    }


def planned_workouts(dashboard: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    workouts: list[dict[str, Any]] = []
    actions = planned_workout_actions()
    retry_states = garmin_retry_states()
    dashboard = dashboard or dashboard_payload()
    reviews_by_date = {item.get("date"): item for item in completed_reviews() if item.get("date")}
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
        action_state = actions.get(path.stem) if isinstance(actions.get(path.stem), dict) else None
        retry_state = retry_states.get(path.stem) if isinstance(retry_states.get(path.stem), dict) else None
        workout_url = garmin_scheduled_workout_url(scheduled_id) or garmin_workout_url(workout_id, payload.get("sport"))
        linked_review = reviews_by_date.get(schedule_date)
        replan = planned_workout_replan_data(
            {
                "slug": path.stem,
                "date": schedule_date,
                "session_kind": kind,
                "action_state": action_state,
            },
            dashboard,
            linked_review,
        )
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
                "garmin_workout_url": workout_url,
                "garmin_scheduled_id": scheduled_id,
                "garmin_upload": upload,
                "garmin_retry_state": retry_state,
                "garmin_status_badge": garmin_status_badge(upload, retry_state, workout_url),
                "session_kind": kind,
                "session_kind_label": kind_label,
                "session_color_class": color_class,
                "action_state": action_state,
                "action_badge": action_display_data((action_state or {}).get("action")),
                "replan": replan,
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
    feedback_items = completed_feedback_items()
    for path in sorted(COMPLETED_REVIEW_DIR.glob("*.analysis.json")):
        payload = load_json(path)
        planned = payload.get("planned", {})
        summary = payload.get("summary", {})
        kind, kind_label, color_class = classify_completed_review(payload)
        slug = path.stem.replace(".analysis", "")
        feedback = feedback_items.get(slug) if isinstance(feedback_items.get(slug), dict) else None
        reviews.append(
            {
                "slug": slug,
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
                "athlete_feedback": feedback,
                "feedback_badge": feedback_badge(feedback),
                "feedback_summary": feedback_summary(feedback),
                "feedback_form": feedback_form_state(feedback),
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
    profile_capability = ensure_fresh("athlete_profile")
    profile = load_optional_yaml(ROOT / "athlete" / "profile.yaml").get("athlete", {})
    health = load_optional_yaml(ROOT / "athlete" / "health.yaml").get("health", {})
    injury = load_optional_yaml(ROOT / "athlete" / "injury_tracker.yaml").get("injury_tracker", {})
    shoes = load_optional_yaml(ROOT / "athlete" / "shoes.yaml").get("shoes", [])
    entries = list(reversed(injury.get("entries") or []))
    capability_messages = [message for message in [profile_capability.warning] if message]
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


def comparison_badge(status: str) -> dict[str, str]:
    mapping = {
        "matched": {"label": "Comparado", "tone": "ok"},
        "planned_only": {"label": "Sin ejecutar", "tone": "warn"},
        "completed_only": {"label": "Sin plan enlazado", "tone": "warn"},
    }
    return mapping.get(status, {"label": status, "tone": ""})


def compare_day_plan_vs_execution(planned_items: list[dict[str, Any]], completed_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    planned_by_slug = {item.get("slug"): item for item in planned_items if item.get("slug")}
    matched_slugs: set[str] = set()

    for review in completed_items:
        payload = review.get("payload", {}) if isinstance(review.get("payload"), dict) else {}
        embedded_planned = payload.get("planned", {}) if isinstance(payload.get("planned"), dict) else {}
        compliance = payload.get("compliance", {}) if isinstance(payload.get("compliance"), dict) else {}
        slug = review.get("slug")
        planned_item = planned_by_slug.get(slug) if slug else None
        if planned_item and slug:
            matched_slugs.add(slug)

        planned_name = (planned_item or {}).get("name") or embedded_planned.get("name") or "-"
        planned_duration = (planned_item or {}).get("estimated_duration") or format_duration(embedded_planned.get("estimated_duration_s"))
        planned_hr_min = embedded_planned.get("primary_hr_min")
        planned_hr_max = embedded_planned.get("primary_hr_max")
        planned_hr = (
            f"{int(planned_hr_min)}-{int(planned_hr_max)} ppm"
            if planned_hr_min is not None and planned_hr_max is not None
            else "-"
        )
        planned_distance_km = float(embedded_planned.get("distance_m") or 0.0) / 1000.0 if embedded_planned.get("distance_m") is not None else None
        actual_distance_km = review.get("distance_km")
        actual_duration = review.get("duration")
        actual_hr = f"{review.get('avg_hr')} ppm" if review.get("avg_hr") not in {None, '-'} else "-"
        deltas = []
        if compliance.get("distance_diff_m") is not None:
            deltas.append(f"Distancia {int(round(float(compliance.get('distance_diff_m') or 0.0)))} m")
        if compliance.get("duration_diff_s_vs_est") is not None:
            deltas.append(f"Duracion {int(round(float(compliance.get('duration_diff_s_vs_est') or 0.0)))} s")
        if compliance.get("pct_above_hr_zone") is not None:
            deltas.append(f"{float(compliance.get('pct_above_hr_zone') or 0.0):.1f}% por encima de zona")
        comparisons.append(
            {
                "status": "matched",
                "badge": comparison_badge("matched"),
                "planned_name": planned_name,
                "actual_name": review.get("activity_name") or review.get("name") or "-",
                "planned_kind_label": (planned_item or {}).get("session_kind_label") or review.get("session_kind_label") or "-",
                "actual_kind_label": review.get("session_kind_label") or "-",
                "planned_distance": f"{planned_distance_km:.2f} km" if planned_distance_km is not None else "-",
                "actual_distance": f"{float(actual_distance_km):.2f} km" if actual_distance_km is not None else "-",
                "planned_duration": planned_duration or "-",
                "actual_duration": actual_duration or "-",
                "planned_hr": planned_hr,
                "actual_hr": actual_hr,
                "result": review.get("traffic_light") or "-",
                "result_note": review.get("compliance_note") or "Sin lectura disponible.",
                "deltas": deltas,
            }
        )

    for planned in planned_items:
        slug = planned.get("slug")
        if slug and slug in matched_slugs:
            continue
        planned_distance_m = planned.get("payload", {}).get("distance_m") if isinstance(planned.get("payload"), dict) else None
        comparisons.append(
            {
                "status": "planned_only",
                "badge": comparison_badge("planned_only"),
                "planned_name": planned.get("name") or "-",
                "actual_name": "Sin actividad enlazada",
                "planned_kind_label": planned.get("session_kind_label") or "-",
                "actual_kind_label": "-",
                "planned_distance": f"{float(planned_distance_m) / 1000.0:.2f} km" if planned_distance_m is not None else "-",
                "actual_distance": "-",
                "planned_duration": planned.get("estimated_duration") or "-",
                "actual_duration": "-",
                "planned_hr": "-",
                "actual_hr": "-",
                "result": "Pendiente",
                "result_note": "La sesion estaba prescrita pero no hay ejecucion enlazada para este dia.",
                "deltas": [],
            }
        )

    planned_slugs = {item.get("slug") for item in planned_items if item.get("slug")}
    for review in completed_items:
        slug = review.get("slug")
        if slug and slug in planned_slugs:
            continue
        if slug and any(item.get("actual_name") == (review.get("activity_name") or review.get("name") or "-") for item in comparisons if item.get("status") == "matched"):
            continue
        comparisons.append(
            {
                "status": "completed_only",
                "badge": comparison_badge("completed_only"),
                "planned_name": "Sin plan enlazado",
                "actual_name": review.get("activity_name") or review.get("name") or "-",
                "planned_kind_label": "-",
                "actual_kind_label": review.get("session_kind_label") or "-",
                "planned_distance": "-",
                "actual_distance": f"{float(review.get('distance_km') or 0.0):.2f} km",
                "planned_duration": "-",
                "actual_duration": review.get("duration") or "-",
                "planned_hr": "-",
                "actual_hr": f"{review.get('avg_hr')} ppm" if review.get("avg_hr") not in {None, '-'} else "-",
                "result": review.get("traffic_light") or "-",
                "result_note": "Hay ejecucion para este dia pero no se ha podido enlazar a una sesion prescrita.",
                "deltas": [],
            }
        )

    return comparisons


def calendar_day_data(day: str) -> dict[str, Any]:
    planned_items = [item for item in planned_workouts() if item.get("date") == day]
    completed_items = [item for item in completed_reviews() if item.get("date") == day]
    race_items = races_by_day().get(day, [])
    reviews = completed_items
    summary_items = len(planned_items) + len(completed_items) + len(race_items)
    comparison = compare_day_plan_vs_execution(planned_items, completed_items)
    return {
        "date": day,
        "date_label": day_label(day),
        "today_plan": today_plan_data(day) if day == date.today().isoformat() else None,
        "planned_items": planned_items,
        "completed_items": completed_items,
        "comparison": comparison,
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
    reviews_by_date: dict[str, list[dict[str, Any]]] = {}
    planned_by_date: dict[str, list[dict[str, Any]]] = {}
    for item in review_items:
        if isinstance(item, dict) and item.get("date"):
            reviews_by_date.setdefault(item["date"], []).append(item)
    for item in planned_items:
        if isinstance(item, dict) and item.get("date"):
            planned_by_date.setdefault(item["date"], []).append(item)

    all_dates = sorted(day for day in (set(planned_by_date) | set(reviews_by_date)) if parse_iso_date(day))
    for day in all_dates:
        planned_for_day = planned_by_date.get(day, [])
        reviews_for_day = reviews_by_date.get(day, [])
        for planned in planned_for_day:
            status = "matched_completed" if reviews_for_day else "planned_only"
            events.append(
                {
                    "date": day,
                    "title": planned.get("name") or day,
                    "kind": planned.get("session_kind") or "other",
                    "source": "planned",
                    "planned_workout": planned,
                    "completed_review": reviews_for_day[0] if reviews_for_day else None,
                    "review": reviews_for_day[0] if reviews_for_day else None,
                    "race": None,
                    "garmin_activity_url": None,
                    "garmin_workout_url": planned.get("garmin_workout_url"),
                    "status": status,
                    "status_label": event_status_label(status),
                    "score": None,
                    "traffic_light": None,
                    "traffic_light_class": "",
                    "detail_url": f"/calendar/day/{day}",
                    "session_kind_label": planned.get("session_kind_label") or session_kind_label(planned.get("session_kind") or "other"),
                    "session_color_class": planned.get("session_color_class") or session_color_class(planned.get("session_kind") or "other"),
                    "replan": planned.get("replan"),
                    "badges": [
                        badge
                        for badge in [
                            "Plan",
                            (planned.get("replan") or {}).get("label") if (planned.get("replan") or {}).get("is_changed") else None,
                        ]
                        if badge
                    ],
                }
            )
        for review in reviews_for_day:
            has_planned = bool(planned_for_day)
            status = "reviewed" if has_planned else "completed_unplanned"
            events.append(
                {
                    "date": day,
                    "title": review.get("activity_name") or review.get("name") or day,
                    "kind": review.get("session_kind") or "other",
                    "source": "review",
                    "planned_workout": planned_for_day[0] if planned_for_day else None,
                    "completed_review": review,
                    "review": review,
                    "race": None,
                    "garmin_activity_url": review.get("garmin_activity_url"),
                    "garmin_workout_url": review.get("garmin_workout_url"),
                    "status": status,
                    "status_label": event_status_label(status),
                    "score": review.get("score"),
                    "traffic_light": review.get("traffic_light"),
                    "traffic_light_class": traffic_light_class(review.get("traffic_light")),
                    "detail_url": f"/calendar/day/{day}",
                    "session_kind_label": review.get("session_kind_label") or session_kind_label(review.get("session_kind") or "other"),
                    "session_color_class": review.get("session_color_class") or session_color_class(review.get("session_kind") or "other"),
                    "replan": None,
                    "badges": [badge for badge in ["Revision", "Hecho"] if badge],
                }
            )
    events.sort(key=calendar_event_sort_key)
    return events


def calendar_month_data_combined(month: str | None, kind: str = "all", status: str = "all") -> dict[str, Any]:
    try:
        workout_events = calendar_events()
        races = races_by_day()
        events_by_day: dict[str, list[dict[str, Any]]] = {}
        for event in workout_events:
            events_by_day.setdefault(event["date"], []).append(event)
        for race_date, race_items in races.items():
            logger.info("calendar race candidate date=%s items=%s", race_date, len(race_items))
            if not parse_iso_date(race_date):
                logger.warning("calendar skipping invalid race date=%s", race_date)
                continue
            if not race_items or not isinstance(race_items[0], dict):
                logger.warning("calendar skipping malformed race items date=%s", race_date)
                continue
            events_by_day.setdefault(race_date, []).append(
                {
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
                "replan": None,
                "badges": ["Carrera"],
                }
            )
        for day, items in events_by_day.items():
            items.sort(key=calendar_event_sort_key)
        filtered_event_by_day = {
            day: [item for item in items if event_matches_filters(item, kind, status)]
            for day, items in events_by_day.items()
        }
        filtered_event_by_day = {day: items for day, items in filtered_event_by_day.items() if items}
        available_months = sorted({day[:7] for day in events_by_day if parse_iso_date(day)})
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
                        "events": filtered_event_by_day.get(iso_day, []),
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
        "today_plan": today_plan_data(),
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


@app.post("/planned-workouts/{slug}/action")
async def planned_workout_action_submit(
    request: Request,
    slug: str,
    action: str = Form(...),
    next_url: str = Form(""),
) -> RedirectResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    workout = planned_workout_detail(slug)
    target = safe_next_url(next_url, f"/planned-workouts/{slug}")
    if not workout:
        request.session["flash"] = {"level": "error", "message": "No se encontro la sesion planificada."}
        return RedirectResponse(url="/planned-workouts", status_code=303)

    allowed_actions = {"done", "skipped", "alternative_requested", "clear"}
    if action not in allowed_actions:
        request.session["flash"] = {"level": "error", "message": "Accion no valida."}
        return RedirectResponse(url=target, status_code=303)

    if action == "clear":
        clear_planned_workout_action(slug)
        request.session["flash"] = {"level": "ok", "message": "Estado operativo limpiado."}
        return RedirectResponse(url=target, status_code=303)

    set_planned_workout_action(slug, workout, action, request.session.get("username"))
    request.session["flash"] = {"level": "ok", "message": ACTION_LABELS.get(action, "Accion guardada.")}
    return RedirectResponse(url=target, status_code=303)


@app.post("/planned-workouts/{slug}/garmin-retry")
async def planned_workout_garmin_retry_submit(
    request: Request,
    slug: str,
    next_url: str = Form(""),
) -> RedirectResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    workout = planned_workout_detail(slug)
    target = safe_next_url(next_url, f"/planned-workouts/{slug}")
    if not workout:
        request.session["flash"] = {"level": "error", "message": "No se encontro la sesion planificada."}
        return RedirectResponse(url="/planned-workouts", status_code=303)

    ok, message = retry_garmin_workout_sync(slug, request.session.get("username"))
    request.session["flash"] = {"level": "ok" if ok else "error", "message": message}
    return RedirectResponse(url=target, status_code=303)


@app.post("/completed-workouts/{slug}/feedback")
async def completed_workout_feedback_submit(
    request: Request,
    slug: str,
    rpe: int = Form(...),
    pain_level: int = Form(...),
    compliance: str = Form(...),
    time_feeling: str = Form(""),
    pain_location: str = Form(""),
    note: str = Form(""),
    next_url: str = Form(""),
) -> RedirectResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    review = completed_review_detail(slug)
    target = safe_next_url(next_url, f"/completed-workouts/{slug}")
    if not review:
        request.session["flash"] = {"level": "error", "message": "No se encontro la revision completada."}
        return RedirectResponse(url="/completed-workouts", status_code=303)

    note = str(note or "").strip()[:200]
    pain_location = str(pain_location or "").strip()[:80]
    if not (1 <= int(rpe) <= 10 and 0 <= int(pain_level) <= 10 and compliance in FEEDBACK_COMPLIANCE_LABELS and (not time_feeling or time_feeling in FEEDBACK_TIME_FEELING_LABELS)):
        request.session["flash"] = {"level": "error", "message": "Revisa los campos de esfuerzo y dolor."}
        return RedirectResponse(url=target, status_code=303)

    updated = set_completed_feedback(
        slug,
        review,
        int(rpe),
        int(pain_level),
        compliance,
        time_feeling,
        pain_location,
        note,
        request.session.get("username"),
    )
    request.session["flash"] = {"level": "ok", "message": "Feedback actualizado." if updated else "Feedback guardado."}
    return RedirectResponse(url=target, status_code=303)


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


@app.get("/progress", response_class=HTMLResponse)
async def progress(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "progress.html", template_context(request, progress=progress_page_data(), workspace=workspace_status()))


@app.get("/master-plan", response_class=HTMLResponse)
async def master_plan(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "master_plan.html", template_context(request, master_plan=master_plan_page_data(), workspace=workspace_status()))


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    config, config_error = load_web_chat_remote_config()
    return templates.TemplateResponse(request, "chat.html", template_context(request, chat_state=web_chat_state(request, config, config_error)))


@app.post("/chat/messages")
async def chat_messages(request: Request) -> JSONResponse:
    unauthorized = json_auth_guard(request)
    if unauthorized:
        return unauthorized

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Payload no valido."}, status_code=400)

    config, config_error = load_web_chat_remote_config()
    if not config:
        return JSONResponse(
            {"ok": False, "error": config_error or "Chat no disponible.", "state": web_chat_state(request, None, config_error)},
            status_code=503,
        )

    store = SessionStore(config.session_store)
    user_key = web_chat_identity(request)

    if payload.get("cancel_confirmation"):
        clear_web_chat_confirmation(store, user_key)
        return JSONResponse(
            {"ok": True, "message": "Confirmacion cancelada.", "state": web_chat_state(request, config)},
            status_code=200,
        )

    confirmed = bool(payload.get("confirm"))
    if confirmed:
        confirmation_id = str(payload.get("confirmation_id") or "").strip()
        pending = store.pop_confirmation(user_key, confirmation_id)
        if not pending:
            return JSONResponse(
                {"ok": False, "error": "La confirmacion ya no existe o no coincide.", "state": web_chat_state(request, config)},
                status_code=409,
            )
        message = str(pending.get("message") or "").strip()
    else:
        message = str(payload.get("message") or "").strip()

    if not message:
        return JSONResponse({"ok": False, "error": "Escribe un mensaje antes de enviar."}, status_code=400)

    policy_error = web_chat_policy_block(message, config)
    if policy_error:
        return JSONResponse(
            {"ok": False, "error": policy_error, "state": web_chat_state(request, config)},
            status_code=403,
        )

    if not confirmed:
        reason = confirmation_reason(message, config.require_confirmation_patterns)
        if reason:
            confirmation_id = store.set_confirmation(user_key, message, reason)
            state = web_chat_state(request, config)
            return JSONResponse(
                {
                    "ok": True,
                    "needs_confirmation": True,
                    "confirmation_id": confirmation_id,
                    "message": "Accion sensible detectada. Confirmala antes de ejecutarla.",
                    "state": state,
                },
                status_code=202,
            )

    lock = WEB_CHAT_LOCKS.setdefault(user_key, asyncio.Lock())
    if lock.locked():
        return JSONResponse(
            {"ok": False, "error": "Ya hay una peticion en curso para este usuario.", "state": web_chat_state(request, config)},
            status_code=409,
        )

    async with lock:
        bridge = OpenCodeBridge(config)
        result = await bridge.send(user_key, message, channel="web")

    append_web_chat_message(user_key, "user", message)
    append_web_chat_message(user_key, "assistant", result.text, model=result.model, error=result.returncode != 0)
    return JSONResponse(
        {
            "ok": result.returncode == 0,
            "message": None if result.returncode == 0 else "OpenCode devolvio una respuesta con incidencia operativa.",
            "state": web_chat_state(request, config),
        },
        status_code=200,
    )


@app.post("/chat/session/reset")
async def chat_session_reset(request: Request) -> JSONResponse:
    unauthorized = json_auth_guard(request)
    if unauthorized:
        return unauthorized

    config, config_error = load_web_chat_remote_config()
    user_key = web_chat_identity(request)
    clear_web_chat_history(user_key)
    if not config:
        return JSONResponse(
            {"ok": False, "error": config_error or "Chat no disponible.", "state": web_chat_state(request, None, config_error)},
            status_code=503,
        )

    store = SessionStore(config.session_store)
    store.clear_session(user_key)
    clear_web_chat_confirmation(store, user_key)
    return JSONResponse({"ok": True, "message": "Sesion reiniciada.", "state": web_chat_state(request, config)}, status_code=200)


@app.post("/chat/model")
async def chat_model(request: Request) -> JSONResponse:
    unauthorized = json_auth_guard(request)
    if unauthorized:
        return unauthorized

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Payload no valido."}, status_code=400)

    config, config_error = load_web_chat_remote_config()
    if not config:
        return JSONResponse(
            {"ok": False, "error": config_error or "Chat no disponible.", "state": web_chat_state(request, None, config_error)},
            status_code=503,
        )

    store = SessionStore(config.session_store)
    user_key = web_chat_identity(request)
    raw_model = str(payload.get("model") or "").strip()
    if str(payload.get("action") or "").strip().lower() in {"reset", "default"}:
        store.clear_model(user_key)
        return JSONResponse({"ok": True, "message": "Modelo reseteado al valor por defecto.", "state": web_chat_state(request, config)}, status_code=200)

    if not raw_model:
        return JSONResponse({"ok": False, "error": "Indica un modelo valido."}, status_code=400)

    store.set_model(user_key, normalize_model_name(raw_model))
    return JSONResponse({"ok": True, "message": "Modelo activo actualizado.", "state": web_chat_state(request, config)}, status_code=200)


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
