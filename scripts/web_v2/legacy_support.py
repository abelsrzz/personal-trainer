#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import copy
import json
import calendar
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from scripts.system.capability_engine import ensure_fresh
from scripts.system.workout_knowledge import goal_label as shared_goal_label
from scripts.system.workout_knowledge import load_workout_knowledge, match_workout_knowledge
from scripts.system.fueling_engine import (
    load_or_build_fueling_payload,
    race_fueling_lookup,
    workout_fueling_lookup,
)
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
from scripts.garmin.recovery_analysis import build_recovery_analysis
from starlette.middleware.sessions import SessionMiddleware


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "web_v2" / "templates"
STATIC_DIR = ROOT / "web_v2" / "static"
PLANNED_WORKOUTS_DIR = ROOT / "training" / "planned" / "workouts"
COMPLETED_REVIEW_DIR = ROOT / "training" / "completed" / "reviews"
COMPLETED_FEEDBACK_DIR = ROOT / "training" / "completed" / "feedback"
GARMIN_ACTIVITY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
GARMIN_DAILY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "daily"
RACES_DIR = ROOT / "races"
MASTER_PLAN_PATH = ROOT / "planning" / "master_plan.md"
ACTIVE_CYCLE_PATH = ROOT / "planning" / "cycles" / "active.yaml"
WEB_CONFIG_PATH = ROOT / "web_v2" / "web_config.yaml"
WEB_LOG_PATH = ROOT / "web_v2" / "web_debug.log"
ACTIVE_WEEK_PATH = ROOT / "planning" / "weeks" / "semana_actual.md"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"
PLANNED_ACTIONS_PATH = ROOT / "system" / "state" / "planned_workout_actions.json"
PLANNED_REPLANS_PATH = ROOT / "system" / "state" / "planned_workout_replans.json"
DAILY_CHECKINS_PATH = ROOT / "system" / "state" / "daily_checkins.json"
GARMIN_RETRY_STATE_PATH = ROOT / "system" / "state" / "garmin_retry_state.json"
POST_WORKOUT_REFRESH_STATE_PATH = ROOT / "system" / "state" / "post_workout_refresh_state.json"
GARMIN_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
WEB_CHAT_UI_STATE_PATH = ROOT / "system" / "state" / "web_chat_ui.json"
WEEKLY_PLANNING_STATE_PATH = ROOT / "system" / "state" / "weekly_planning_state.json"
ATHLETE_STATE_PATH = ROOT / "system" / "state" / "athlete_state.json"
WEEKLY_PLANNING_SCRIPT = ROOT / "scripts" / "system" / "weekly_planning_pipeline.py"
AUTOMATION_SAFETY_PATH = ROOT / "system" / "automation_safety.yaml"
CHAT_WEB_ENABLED = False


WEB_CHAT_LOCKS: dict[str, asyncio.Lock] = {}
_WEB_CHAT_TASKS: dict[str, "asyncio.Task[None]"] = {}
FILE_CACHE: dict[tuple[str, str], tuple[int, int, Any]] = {}


def _file_cache_key(path: Path, kind: str) -> tuple[str, str]:
    return (str(path), kind)


def _read_cached_file(path: Path, kind: str) -> Any:
    stat = path.stat()
    cache_key = _file_cache_key(path, kind)
    cached = FILE_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        payload = cached[2]
        return copy.deepcopy(payload) if kind in {"json", "yaml"} else payload

    if kind == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    elif kind == "yaml":
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    else:
        payload = path.read_text(encoding="utf-8")

    FILE_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, payload)
    return copy.deepcopy(payload) if kind in {"json", "yaml"} else payload


logger = logging.getLogger("running_coach_web_support")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    # Rotating handler so the web debug log can't grow unbounded on the server.
    file_handler = RotatingFileHandler(
        WEB_LOG_PATH,
        encoding="utf-8",
        maxBytes=int(os.getenv("WEB_LOG_MAX_BYTES", str(5 * 1024 * 1024))),
        backupCount=int(os.getenv("WEB_LOG_BACKUP_COUNT", "3")),
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_cached_file(path, "yaml")


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


# NOTE: the live web app is scripts.web_v2.app:app. This module is imported by
# app.py only as a data/formatting library (portal_core), so it no longer
# defines its own FastAPI app or routes. `templates` is kept solely to register
# the Jinja filters reused by the live app.
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def load_json(path: Path) -> Any:
    return _read_cached_file(path, "json")


def load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return load_json(path)


def load_yaml(path: Path) -> dict[str, Any]:
    return _read_cached_file(path, "yaml")


def write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=False, sort_keys=False)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return _read_cached_file(path, "text")


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
            "last_seen_activity_date": None,
            "last_processed_activity_id": None,
            "last_processed_activity_date": None,
            "last_processed_at": None,
            "last_successful_run": None,
            "last_error": None,
            "last_activity_import_at": None,
            "last_daily_import_at": None,
            "last_profile_sync_at": None,
            "next_action": "import_recent_activities",
            "timer_interval_minutes": 5,
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
        "last_seen_activity_date": state.get("last_seen_activity_date"),
        "last_processed_activity_id": state.get("last_processed_activity_id"),
        "last_processed_activity_date": state.get("last_processed_activity_date"),
        "last_activity_import_at": format_datetime(state.get("last_activity_import_at")),
        "last_daily_import_at": format_datetime(state.get("last_daily_import_at")),
        "last_profile_sync_at": format_datetime(state.get("last_profile_sync_at")),
        "next_action": str(state.get("next_action") or "").strip() or None,
        "timer_interval_minutes": int(state.get("timer_interval_minutes") or 5),
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
        "cycling": "cycling",
        "swimming": "swimming",
        "strength": "strength_training",
        "fitness_equipment": "other",
        "mobility": "mobility",
        "stretching": "mobility",
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


def workout_target_value(target: dict[str, Any] | None) -> str | None:
    if not isinstance(target, dict):
        return None
    target_type = str(target.get("type") or "").strip().lower()
    if target_type == "pace_range":
        min_pace = str(target.get("min_pace") or "").strip()
        max_pace = str(target.get("max_pace") or "").strip()
        if min_pace and max_pace:
            return f"{min_pace} - {max_pace}"
        return min_pace or max_pace or None
    if target_type in {"heart_rate_range", "heart_rate_max"}:
        min_bpm = target.get("min_bpm")
        max_bpm = target.get("max_bpm")
        if min_bpm is not None and max_bpm is not None:
            return f"{int(min_bpm)}-{int(max_bpm)} ppm"
        if max_bpm is not None:
            return f"<= {int(max_bpm)} ppm"
        if min_bpm is not None:
            return f">= {int(min_bpm)} ppm"
        return None
    if target_type == "heart_rate_zone":
        zone = str(target.get("zone") or "").strip()
        min_bpm = target.get("min_bpm")
        max_bpm = target.get("max_bpm")
        bpm_text = None
        if min_bpm is not None and max_bpm is not None:
            bpm_text = f"{int(min_bpm)}-{int(max_bpm)} ppm"
        elif max_bpm is not None:
            bpm_text = f"<= {int(max_bpm)} ppm"
        elif min_bpm is not None:
            bpm_text = f">= {int(min_bpm)} ppm"
        if zone and bpm_text:
            return f"{zone} · {bpm_text}"
        return zone or bpm_text
    return None


def workout_targets_summary(payload: dict[str, Any]) -> dict[str, Any]:
    flat_steps = flatten_workout_steps(payload.get("steps") or [])
    pace_targets: list[str] = []
    hr_targets: list[str] = []
    step_targets: list[dict[str, str]] = []
    seen_step_targets: set[tuple[str, str, str]] = set()
    for step in flat_steps:
        if not isinstance(step, dict):
            continue
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        target_type = str(target.get("type") or "").strip().lower()
        target_value = workout_target_value(target)
        if not target_value:
            continue
        step_label = str(step.get("description") or step.get("step_type") or step.get("type") or "Bloque").strip()
        tone = "pace" if target_type == "pace_range" else "hr" if target_type in {"heart_rate_range", "heart_rate_zone", "heart_rate_max"} else "other"
        key = (step_label, target_type, target_value)
        if key not in seen_step_targets:
            seen_step_targets.add(key)
            step_targets.append({"label": step_label, "target_type": target_type, "target_value": target_value, "tone": tone})
        if target_type == "pace_range" and target_value not in pace_targets:
            pace_targets.append(target_value)
        if target_type in {"heart_rate_range", "heart_rate_zone", "heart_rate_max"} and target_value not in hr_targets:
            hr_targets.append(target_value)
    return {
        "primary_pace": pace_targets[0] if pace_targets else None,
        "primary_hr": hr_targets[0] if hr_targets else None,
        "pace_targets": pace_targets,
        "hr_targets": hr_targets,
        "step_targets": step_targets,
    }


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
        "elliptical": "Eliptica",
        "strength": "Fuerza",
        "mobility": "Movilidad",
        "race": "Competición",
        "rest": "Descanso",
        "other": "Otra sesión",
    }.get(value, "Otra sesión")


def session_color_class(value: str) -> str:
    return f"session-{value if value else 'other'}"


def classify_planned_workout(payload: dict[str, Any]) -> tuple[str, str, str]:
    sport = str(payload.get("sport") or "").strip().lower()
    if sport == "strength":
        kind = "strength"
        return kind, session_kind_label(kind), session_color_class(kind)
    if sport in {"mobility", "stretching"}:
        kind = "mobility"
        return kind, session_kind_label(kind), session_color_class(kind)
    if sport == "elliptical":
        kind = "elliptical"
        return kind, session_kind_label(kind), session_color_class(kind)

    steps = payload.get("steps") or []
    distance_m = payload.get("distance_m")
    if not distance_m:
        distance_m = sum(float(step.get("distance_m") or 0.0) for step in steps if isinstance(step, dict))
    name_text = str(payload.get("name") or "")
    description_text = str(payload.get("description") or "")
    step_text = json.dumps(steps, ensure_ascii=False)
    kind = classify_session_kind(name_text, description_text, step_text, float(distance_m) / 1000.0 if distance_m else None, steps)
    return kind, session_kind_label(kind), session_color_class(kind)


def workout_goal_label(goal: str) -> str:
    return shared_goal_label(goal)


def workout_knowledge_match(payload: dict[str, Any], session_kind: str) -> dict[str, Any] | None:
    return match_workout_knowledge(payload, session_kind)


def workout_knowledge_summary(payload: dict[str, Any], session_kind: str) -> dict[str, Any] | None:
    match = workout_knowledge_match(payload, session_kind)
    if not match:
        return None
    primary_goal = str(match.get("primary_goal") or "").strip()
    goal_labels = match.get("goal_labels") or []
    secondary = [item for item in goal_labels[1:3] if item]
    summary = f"Esta sesion se usa sobre todo para {primary_goal.lower()}." if primary_goal else "Esta sesion tiene un objetivo operativo reconocido."
    if secondary:
        summary += f" Tambien aporta {', '.join(item.lower() for item in secondary)}."
    return {
        **match,
        "summary": summary,
    }


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


def planned_session_reference_for_workout(workout: dict[str, Any] | None) -> str | None:
    if not isinstance(workout, dict):
        return None
    slug = str(workout.get("slug") or "").strip()
    if not slug:
        return None
    return f"training/planned/workouts/{slug}.yaml"


def review_planned_session_reference(review: dict[str, Any] | None) -> str | None:
    if not isinstance(review, dict):
        return None
    payload = review.get("payload", {}) if isinstance(review.get("payload"), dict) else {}
    planned = payload.get("planned", {}) if isinstance(payload.get("planned"), dict) else {}
    reference = str(planned.get("planned_session_reference") or "").strip()
    if reference:
        return reference
    slug = str(review.get("slug") or "").strip()
    if not slug:
        return None
    return f"training/planned/workouts/{slug}.yaml"


def review_matches_planned_workout(review: dict[str, Any] | None, workout: dict[str, Any] | None) -> bool:
    if not isinstance(review, dict) or not isinstance(workout, dict):
        return False
    workout_reference = planned_session_reference_for_workout(workout)
    review_reference = review_planned_session_reference(review)
    if workout_reference and review_reference:
        return workout_reference == review_reference
    workout_slug = str(workout.get("slug") or "").strip()
    review_slug = str(review.get("slug") or "").strip()
    return bool(workout_slug and review_slug and workout_slug == review_slug)


def find_review_for_planned_workout(workout: dict[str, Any] | None, reviews: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(workout, dict):
        return None
    for review in reviews:
        if review_matches_planned_workout(review, workout):
            return review
    return None


def pick_primary_review_for_day(
    day: str,
    reviews: list[dict[str, Any]],
    planned_today: dict[str, Any] | None,
    race_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    reviews_for_day = [item for item in reviews if item.get("date") == day]
    if not reviews_for_day:
        return None
    matched_review = find_review_for_planned_workout(planned_today, reviews_for_day)
    if matched_review:
        return matched_review
    if race_items:
        race_names = {str(item.get("name") or "").strip().lower() for item in race_items if str(item.get("name") or "").strip()}
        for review in reviews_for_day:
            if str(review.get("session_kind") or "").strip().lower() == "race":
                return review
            activity_name = str(review.get("activity_name") or review.get("name") or "").strip().lower()
            if activity_name and any(race_name and race_name in activity_name for race_name in race_names):
                return review
    return reviews_for_day[0]


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


def chat_page_guard() -> RedirectResponse | None:
    if CHAT_WEB_ENABLED:
        return None
    return RedirectResponse(url="/dashboard", status_code=303)


def chat_api_guard() -> JSONResponse | None:
    if CHAT_WEB_ENABLED:
        return None
    return JSONResponse({"ok": False, "error": "El chat web esta desactivado en esta instancia."}, status_code=403)


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

    gemini_data = opencode_data.get("gemini_fallback") or {}
    import os as _os
    gemini_api_key = str(_os.getenv("GEMINI_API_KEY") or gemini_data.get("api_key") or "").strip() or None

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
                gemini_fallback_enabled=bool(gemini_data.get("enabled", bool(gemini_api_key))),
                gemini_api_key=gemini_api_key,
                gemini_models=tuple(
                    str(m).strip() for m in (
                        gemini_data.get("models") or [gemini_data.get("model") or "gemini-2.5-pro"]
                    ) if str(m).strip()
                ) or ("gemini-2.5-pro",),
            ),
            None,
        )
    except (TypeError, ValueError) as exc:
        return None, f"Configuracion opencode_remote invalida: {exc}"


def available_web_chat_config(config: OpenCodeRemoteConfig | None, config_error: str | None) -> tuple[OpenCodeRemoteConfig | None, str | None]:
    if not config:
        return None, config_error or "Chat no disponible."
    if not config.enabled:
        return None, "El chat web esta deshabilitado en `opencode_remote.enabled`."
    return config, config_error


def web_chat_ui_store() -> dict[str, Any]:
    payload = load_optional_json(WEB_CHAT_UI_STATE_PATH, {"users": {}})
    users = payload.get("users") if isinstance(payload, dict) else None
    if not isinstance(users, dict):
        return {"users": {}}
    return payload


def _make_conv_id() -> str:
    import secrets
    return f"conv_{secrets.token_hex(8)}"


def _migrate_user_state(user_state: dict[str, Any]) -> dict[str, Any]:
    """Migrate old flat messages list to conversation-threaded structure."""
    if "conversations" in user_state:
        return user_state
    old_messages = user_state.get("messages") if isinstance(user_state.get("messages"), list) else []
    conv_id = _make_conv_id()
    title = "Chat anterior"
    if old_messages:
        first_user = next((m.get("text", "") for m in old_messages if m.get("role") == "user"), "")
        if first_user:
            title = first_user[:50].rstrip() + ("…" if len(first_user) > 50 else "")
    now = datetime.now().isoformat()
    user_state["conversations"] = {
        conv_id: {
            "id": conv_id,
            "title": title,
            "messages": old_messages[-80:],
            "created_at": now,
            "updated_at": now,
        }
    } if old_messages else {}
    user_state["active_conversation_id"] = conv_id if old_messages else None
    user_state.pop("messages", None)
    return user_state


def _get_user_state(user_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = web_chat_ui_store()
    raw = payload["users"].get(user_key, {})
    user_state = _migrate_user_state(dict(raw) if isinstance(raw, dict) else {})
    return payload, user_state


def _save_user_state(payload: dict[str, Any], user_key: str, user_state: dict[str, Any]) -> None:
    payload["users"][user_key] = user_state
    write_json(WEB_CHAT_UI_STATE_PATH, payload)


def get_active_conv_id(user_key: str, user_state: dict[str, Any]) -> str | None:
    return user_state.get("active_conversation_id")


def ensure_active_conversation(user_key: str) -> str:
    """Return active conversation ID, creating one if none exists."""
    payload, user_state = _get_user_state(user_key)
    active_id = user_state.get("active_conversation_id")
    convs = user_state.setdefault("conversations", {})
    if active_id and active_id in convs:
        return active_id
    conv_id = _make_conv_id()
    now = datetime.now().isoformat()
    convs[conv_id] = {"id": conv_id, "title": "Nueva conversación", "messages": [], "created_at": now, "updated_at": now}
    user_state["active_conversation_id"] = conv_id
    _save_user_state(payload, user_key, user_state)
    return conv_id


def list_chat_conversations(user_key: str) -> list[dict[str, Any]]:
    _, user_state = _get_user_state(user_key)
    convs = user_state.get("conversations", {})
    result = []
    for conv in convs.values():
        if not isinstance(conv, dict):
            continue
        messages = conv.get("messages") or []
        preview = ""
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("text"):
                preview = str(m["text"])[:80]
                break
        result.append({
            "id": conv.get("id", ""),
            "title": conv.get("title", "Conversación"),
            "updated_at": conv.get("updated_at", ""),
            "created_at": conv.get("created_at", ""),
            "preview": preview,
            "message_count": len(messages),
        })
    result.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return result


def create_chat_conversation(user_key: str) -> str:
    payload, user_state = _get_user_state(user_key)
    conv_id = _make_conv_id()
    now = datetime.now().isoformat()
    user_state.setdefault("conversations", {})[conv_id] = {
        "id": conv_id,
        "title": "Nueva conversación",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    user_state["active_conversation_id"] = conv_id
    _save_user_state(payload, user_key, user_state)
    return conv_id


def switch_chat_conversation(user_key: str, conv_id: str) -> bool:
    payload, user_state = _get_user_state(user_key)
    if conv_id not in user_state.get("conversations", {}):
        return False
    user_state["active_conversation_id"] = conv_id
    _save_user_state(payload, user_key, user_state)
    return True


def delete_chat_conversation(user_key: str, conv_id: str) -> str | None:
    payload, user_state = _get_user_state(user_key)
    convs = user_state.get("conversations", {})
    convs.pop(conv_id, None)
    active_id = user_state.get("active_conversation_id")
    if active_id == conv_id:
        remaining = list(convs.keys())
        user_state["active_conversation_id"] = remaining[0] if remaining else None
    _save_user_state(payload, user_key, user_state)
    return user_state.get("active_conversation_id")


def web_chat_history(user_key: str) -> list[dict[str, Any]]:
    _, user_state = _get_user_state(user_key)
    active_id = user_state.get("active_conversation_id")
    conv = user_state.get("conversations", {}).get(active_id or "", {})
    messages = conv.get("messages") if isinstance(conv, dict) else []
    return messages if isinstance(messages, list) else []


def save_web_chat_history(user_key: str, messages: list[dict[str, Any]]) -> None:
    payload, user_state = _get_user_state(user_key)
    active_id = ensure_active_conversation(user_key)
    payload, user_state = _get_user_state(user_key)
    conv = user_state["conversations"][active_id]
    conv["messages"] = messages[-80:]
    now = datetime.now().isoformat()
    conv["updated_at"] = now
    if conv.get("title") == "Nueva conversación":
        first_user = next((m.get("text", "") for m in messages if m.get("role") == "user"), "")
        if first_user:
            conv["title"] = first_user[:50].rstrip() + ("…" if len(first_user) > 50 else "")
    _save_user_state(payload, user_key, user_state)


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
    payload, user_state = _get_user_state(user_key)
    active_id = user_state.get("active_conversation_id")
    if active_id and active_id in user_state.get("conversations", {}):
        conv = user_state["conversations"][active_id]
        conv["messages"] = []
        conv["title"] = "Nueva conversación"
        conv["updated_at"] = datetime.now().isoformat()
    _save_user_state(payload, user_key, user_state)


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
    _, user_state = _get_user_state(user_key)
    active_conv_id = user_state.get("active_conversation_id")
    task = _WEB_CHAT_TASKS.get(user_key)
    processing = bool(task and not task.done())
    return {
        "available": bool(config and not config_error),
        "error": config_error,
        "history": web_chat_history(user_key),
        "active_model": active_model,
        "default_model": config.model if config else DEFAULT_OPENCODE_MODEL,
        "session_id": session_id,
        "pending_confirmation": web_chat_pending_confirmation(store, user_key) if store else None,
        "config_path": str(OPENCODE_REMOTE_CONFIG_PATH.relative_to(ROOT)),
        "conversations": list_chat_conversations(user_key),
        "active_conversation_id": active_conv_id,
        "processing": processing,
    }


def chat_state_response(request: Request) -> tuple[OpenCodeRemoteConfig | None, str | None, dict[str, Any]]:
    config, config_error = load_web_chat_remote_config()
    config, config_error = available_web_chat_config(config, config_error)
    return config, config_error, web_chat_state(request, config, config_error)


def chat_missing_message_response(request: Request) -> JSONResponse:
    return JSONResponse({"ok": False, "error": "Escribe un mensaje antes de enviar."}, status_code=400)


WEB_CHAT_TIMEOUT_S = 180

_logger_web_chat = logging.getLogger("web.chat")


async def _chat_background_task(user_key: str, config: OpenCodeRemoteConfig, message: str, display_message: str | None) -> None:
    stored_msg = display_message if display_message is not None else message
    try:
        bridge = OpenCodeBridge(config)
        result = await asyncio.wait_for(
            bridge.send(user_key, message, channel="web"),
            timeout=WEB_CHAT_TIMEOUT_S,
        )
        append_web_chat_message(user_key, "user", stored_msg)
        append_web_chat_message(user_key, "assistant", result.text, model=result.model, error=result.returncode != 0)
        _logger_web_chat.info("chat task done user_key=%s rc=%s", user_key, result.returncode)
    except asyncio.TimeoutError:
        timeout_text = (
            f"El entrenador no respondio en {WEB_CHAT_TIMEOUT_S}s. "
            "Puede que siga procesando; vuelve a abrir el chat en unos minutos."
        )
        append_web_chat_message(user_key, "user", stored_msg)
        append_web_chat_message(user_key, "assistant", timeout_text, error=True)
        _logger_web_chat.warning("chat task timeout user_key=%s timeout_s=%s", user_key, WEB_CHAT_TIMEOUT_S)
    except Exception as exc:
        err_text = f"Error del entrenador: {exc}"
        append_web_chat_message(user_key, "user", stored_msg)
        append_web_chat_message(user_key, "assistant", err_text, error=True)
        _logger_web_chat.error("chat task error user_key=%s exc=%s", user_key, exc, exc_info=True)
    finally:
        _WEB_CHAT_TASKS.pop(user_key, None)


async def chat_execute_message(request: Request, config: OpenCodeRemoteConfig, message: str, *, display_message: str | None = None) -> JSONResponse:
    user_key = web_chat_identity(request)
    existing = _WEB_CHAT_TASKS.get(user_key)
    if existing and not existing.done():
        return JSONResponse(
            {"ok": False, "error": "Ya hay una peticion en curso.", "state": web_chat_state(request, config)},
            status_code=409,
        )
    _WEB_CHAT_TASKS.pop(user_key, None)
    task = asyncio.create_task(_chat_background_task(user_key, config, message, display_message))
    _WEB_CHAT_TASKS[user_key] = task
    return JSONResponse(
        {"ok": True, "processing": True, "state": web_chat_state(request, config)},
        status_code=202,
    )


def chat_store_for_request(config: OpenCodeRemoteConfig, request: Request) -> tuple[SessionStore, str]:
    return SessionStore(config.session_store), web_chat_identity(request)


def json_auth_guard(request: Request) -> JSONResponse | None:
    if authenticated(request):
        return None
    return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)


ACTION_LABELS = {
    "done": "Marcada como hecha",
    "skipped": "Marcada como no realizada",
    "alternative_requested": "Alternativa solicitada",
    "replanned": "Replanificacion aplicada",
}


ACTION_BADGES = {
    "done": ("Ya resuelto", "ok"),
    "skipped": ("Ya resuelto", "warn"),
    "alternative_requested": ("Ya resuelto", "warn"),
    "replanned": ("Ya resuelto", "warn"),
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


def planned_workout_replans() -> dict[str, dict[str, Any]]:
    payload = load_optional_json(PLANNED_REPLANS_PATH, {"workouts": {}})
    workouts = payload.get("workouts") if isinstance(payload, dict) else {}
    return workouts if isinstance(workouts, dict) else {}


def planned_workout_replan(slug: str) -> dict[str, Any] | None:
    item = planned_workout_replans().get(slug)
    return item if isinstance(item, dict) else None


def clear_planned_workout_replan(slug: str) -> None:
    payload = load_optional_json(PLANNED_REPLANS_PATH, {"workouts": {}})
    if not isinstance(payload, dict):
        return
    workouts = payload.get("workouts")
    if not isinstance(workouts, dict):
        return
    workouts.pop(slug, None)
    write_json(PLANNED_REPLANS_PATH, payload)


def daily_checkins() -> dict[str, dict[str, Any]]:
    payload = load_optional_json(DAILY_CHECKINS_PATH, {"days": {}})
    days = payload.get("days") if isinstance(payload, dict) else {}
    return days if isinstance(days, dict) else {}


def daily_checkin(day: str) -> dict[str, Any] | None:
    item = daily_checkins().get(day)
    return item if isinstance(item, dict) else None


def set_daily_checkin(day: str, payload: dict[str, Any]) -> dict[str, Any]:
    state = load_optional_json(DAILY_CHECKINS_PATH, {"days": {}})
    if not isinstance(state, dict):
        state = {"days": {}}
    days = state.setdefault("days", {})
    days[day] = payload
    write_json(DAILY_CHECKINS_PATH, state)
    return payload


def daily_checkin_action_badge(action: str) -> dict[str, str]:
    mapping = {
        "keep": {"label": "Mantener", "tone": "ok"},
        "reduce": {"label": "Suavizar", "tone": "warn"},
        "move": {"label": "Mover", "tone": "warn"},
        "cancel": {"label": "Cancelar", "tone": "warn"},
        "unknown": {"label": "Sin decidir", "tone": ""},
    }
    return mapping.get(action, mapping["unknown"])


def daily_checkin_decision(checkin: dict[str, Any], planned_workout: dict[str, Any] | None) -> dict[str, Any]:
    energy = int(checkin.get("energy") or 0)
    sleep = int(checkin.get("sleep") or 0)
    pain = int(checkin.get("pain") or 0)
    motivation = int(checkin.get("motivation") or 0)
    available_minutes = int(checkin.get("available_minutes") or 0)
    planned_minutes = 0
    if planned_workout and isinstance(planned_workout.get("payload"), dict):
        planned_minutes = int(round(float(planned_workout["payload"].get("estimated_duration_s") or 0) / 60.0))

    reasons: list[str] = []
    score = 0
    score += energy * 10
    score += sleep * 8
    score += motivation * 7
    score += max(0, 20 - (pain * 3))
    if available_minutes > 0:
        if planned_minutes > 0:
            time_ratio = available_minutes / max(planned_minutes, 1)
            if time_ratio >= 1.0:
                score += 12
            elif time_ratio >= 0.75:
                score += 8
            elif time_ratio >= 0.5:
                score += 4
            else:
                score += 0
        else:
            score += 8
    score = max(0, min(100, score))

    action = "keep"
    headline = "Mantener el plan"
    summary = "Las sensaciones previas permiten ejecutar la sesion prevista."

    if pain >= 6:
        action = "cancel"
        headline = "Cancelar o descansar"
        summary = "El dolor reportado es demasiado alto para asumir la sesion de hoy con normalidad."
        reasons.append(f"Dolor {pain}/10")
    elif available_minutes > 0 and planned_minutes > 0 and available_minutes < max(20, int(planned_minutes * 0.45)):
        action = "move"
        headline = "Mover o recomponer"
        summary = "El tiempo disponible real no da para una version util de la sesion prevista."
        reasons.append(f"Solo hay {available_minutes} min reales frente a {planned_minutes} min previstos")
    elif pain >= 4 or energy <= 2 or sleep <= 2:
        action = "reduce"
        headline = "Suavizar la sesion"
        summary = "Conviene bajar coste hoy y ejecutar una version mas protectora o compacta."
        if pain >= 4:
            reasons.append(f"Dolor {pain}/10")
        if energy <= 2:
            reasons.append(f"Energia {energy}/5")
        if sleep <= 2:
            reasons.append(f"Sueno {sleep}/5")
    elif motivation <= 2 and score < 70:
        action = "reduce"
        headline = "Bajar exigencia"
        summary = "La disposicion mental no es buena; mejor mantener continuidad con menos coste."
        reasons.append(f"Ganas de entrenar {motivation}/5")
    else:
        if energy >= 4:
            reasons.append(f"Energia {energy}/5")
        if sleep >= 4:
            reasons.append(f"Sueno {sleep}/5")
        if available_minutes and planned_minutes:
            reasons.append(f"Tiempo disponible {available_minutes}/{planned_minutes} min")

    if not reasons:
        reasons.append(f"Score de disponibilidad {score}/100")

    return {
        "score": score,
        "action": action,
        "headline": headline,
        "summary": summary,
        "reasons": reasons[:3],
        "badge": daily_checkin_action_badge(action),
    }


def daily_checkin_form_state(checkin: dict[str, Any] | None, planned_workout: dict[str, Any] | None) -> dict[str, Any]:
    values = checkin or {}
    decision = daily_checkin_decision(values, planned_workout) if checkin else None
    return {
        "exists": bool(checkin),
        "form_values": {
            "energy": int(values.get("energy") or 3),
            "sleep": int(values.get("sleep") or 3),
            "pain": int(values.get("pain") or 0),
            "motivation": int(values.get("motivation") or 3),
            "available_minutes": int(values.get("available_minutes") or 45),
            "note": str(values.get("note") or "").strip(),
        },
        "updated_at": format_datetime(values.get("updated_at")) if checkin else None,
        "decision": decision,
    }


def daily_checkin_replan_suggestion(checkin_decision: dict[str, Any] | None, planned_workout: dict[str, Any] | None) -> dict[str, Any] | None:
    if not checkin_decision or not planned_workout:
        return None
    action = str(checkin_decision.get("action") or "").strip().lower()
    session_kind = str(planned_workout.get("session_kind") or "other").strip().lower()
    if action == "cancel":
        return {
            "strategy": "skip_recompose_week",
            "label": "Aplicar proteccion semanal",
            "summary": "El check-in recomienda cancelar hoy y recomponer la semana automaticamente.",
            "tone": "warn",
        }
    if action == "move":
        return {
            "strategy": "move_next_day",
            "label": "Mover sesion automaticamente",
            "summary": "El check-in detecta que hoy no encaja bien y propone recolocar la sesion al siguiente hueco util.",
            "tone": "warn",
        }
    if action == "reduce":
        return {
            "strategy": "reduce_keep_goal" if session_kind in {"quality", "long_run", "race"} else "auto_today",
            "label": "Aplicar version protectora",
            "summary": "El check-in recomienda una version mas corta o mas suave para mantener continuidad sin forzar el dia.",
            "tone": "warn",
        }
    return None


def preferred_replan_suggestion(planned_workout: dict[str, Any] | None, dashboard: dict[str, Any], checkin_decision: dict[str, Any] | None = None) -> dict[str, Any] | None:
    checkin_suggestion = daily_checkin_replan_suggestion(checkin_decision, planned_workout)
    if checkin_suggestion:
        checkin_suggestion["auto_allowed"] = auto_replan_allowed(str(checkin_suggestion.get("strategy") or ""), planned_workout or {})
        return checkin_suggestion
    return automatic_replan_suggestion(planned_workout, dashboard)


def clone_steps(steps: Any) -> list[dict[str, Any]]:
    if not isinstance(steps, list):
        return []
    cloned: list[dict[str, Any]] = []
    for step in steps:
        if isinstance(step, dict):
            cloned.append(copy.deepcopy(step))
    return cloned


def occupied_planned_dates(exclude_slug: str | None = None) -> set[str]:
    occupied: set[str] = set()
    for path in sorted(PLANNED_WORKOUTS_DIR.glob("*.yaml")):
        if path.name in {"library_run_templates.yaml", "workout_template.yaml"}:
            continue
        if exclude_slug and path.stem == exclude_slug:
            continue
        payload = load_yaml(path).get("workout", {})
        planned_date = str(payload.get("schedule_date") or "").strip()
        if planned_date:
            occupied.add(planned_date)
    for slug, replan_state in planned_workout_replans().items():
        if exclude_slug and slug == exclude_slug:
            continue
        if not isinstance(replan_state, dict):
            continue
        planned_date = str(replan_state.get("effective_date") or "").strip()
        if planned_date:
            occupied.add(planned_date)
    return occupied


def next_replan_date(current_date: str, exclude_slug: str) -> str:
    parsed_current = parse_iso_date(current_date)
    if not parsed_current:
        return current_date

    occupied = occupied_planned_dates(exclude_slug=exclude_slug)
    races = set(races_by_day().keys())
    week_content = read_text(ACTIVE_WEEK_PATH)
    start_date, end_date = parse_week_date_window(week_content)
    rows = parse_week_table(week_content)
    rest_candidates: list[str] = []
    if start_date and end_date:
        for row in rows:
            row_date = resolve_week_row_date(row.get("day", ""), start_date, end_date)
            if not row_date or row_date <= current_date:
                continue
            description = str(row.get("description") or "").lower()
            distance = str(row.get("distance") or "").lower()
            if "carrera" in description or "edicion" in description:
                continue
            if row_date in occupied or row_date in races:
                continue
            if distance == "0 km" or "descanso" in description or "movilidad" in description:
                rest_candidates.append(row_date)
    if rest_candidates:
        return sorted(rest_candidates)[0]

    for offset in range(1, 8):
        candidate = parsed_current.fromordinal(parsed_current.toordinal() + offset).isoformat()
        if candidate in occupied or candidate in races:
            continue
        return candidate
    return parsed_current.fromordinal(parsed_current.toordinal() + 1).isoformat()


def make_replan_steps(kind: str, strategy: str, original_name: str, duration_s: int) -> list[dict[str, Any]]:
    if strategy == "move_next_day":
        return [
            {"order": 1, "step_type": "note", "description": f"Mantener la sesion {original_name} en el nuevo dia sugerido."},
        ]
    if strategy == "skip_recompose_week":
        return [
            {"order": 1, "step_type": "note", "description": "Hoy se convierte en descanso o movilidad suave."},
            {"order": 2, "step_type": "note", "description": "La carga se recoloca en otro dia de la misma semana con margen."},
        ]
    if kind == "quality":
        if strategy == "reduce_keep_goal":
            return [
                {"order": 1, "step_type": "warmup", "description": "10-15 min faciles"},
                {"order": 2, "step_type": "interval", "description": "Bloque principal compacto: menos repeticiones y sin apretar"},
                {"order": 3, "step_type": "cooldown", "description": "10 min faciles"},
            ]
        return [
            {"order": 1, "step_type": "warmup", "description": "25-35 min muy faciles"},
            {"order": 2, "step_type": "cooldown", "description": "Movilidad corta al terminar"},
        ]
    if kind == "long_run":
        return [
            {"order": 1, "step_type": "warmup", "description": "Rodaje facil mas corto de lo previsto"},
            {"order": 2, "step_type": "cooldown", "description": "Parar con margen; sin buscar carga extra"},
        ]
    if kind in {"easy", "recovery"}:
        return [
            {"order": 1, "step_type": "warmup", "description": "Rodaje muy facil y conversacional"},
            {"order": 2, "step_type": "cooldown", "description": "Cortar antes si no acompana el dia"},
        ]
    if kind == "strength":
        return [
            {"order": 1, "step_type": "note", "description": "Version corta y sin carga residual alta."},
        ]
    return [
        {"order": 1, "step_type": "note", "description": f"Version adaptada de {original_name}."},
    ]


def protective_alternative_from_knowledge(workout: dict[str, Any], strategy: str) -> tuple[str | None, str | None]:
    knowledge = workout.get("knowledge") if isinstance(workout.get("knowledge"), dict) else None
    if not knowledge:
        return None, None
    goals = set(knowledge.get("goals") or [])
    if strategy == "auto_today":
        if goals & {"vo2max", "ritmo_5k", "ritmo_10k", "capacidad_anaerobica", "tolerancia_al_lactato", "cuestas_cortas", "cuestas_largas"}:
            return "recovery", "30' suave o 30' regenerativo muy suave"
        if goals & {"fondo_largo", "resistencia_especifica_maraton", "resistencia_especifica_21k"}:
            return "easy", "40' suave o 50' en Z2 estable"
    if strategy == "reduce_keep_goal":
        if goals & {"umbral_lactico", "umbral_fraccionado", "umbral_aerobico"}:
            return workout.get("session_kind") or "quality", "4x5' @ ritmo 21k rec 1'"
        if goals & {"ritmo_10k", "resistencia_especifica_10k"}:
            return workout.get("session_kind") or "quality", "5x1000 @ ritmo 10k rec 2'"
        if goals & {"ritmo_5k", "vo2max"}:
            return workout.get("session_kind") or "quality", "8x2' @ ritmo 5k / 2' suave"
        if goals & {"ritmo_maraton", "resistencia_especifica_maraton"}:
            return "easy", "45' progresivo de suave a ritmo M"
    return None, None


def generate_replan_proposal(workout: dict[str, Any], strategy: str, dashboard: dict[str, Any]) -> dict[str, Any]:
    payload = workout.get("payload", {}) if isinstance(workout.get("payload"), dict) else {}
    original_date = str(workout.get("date") or str(payload.get("schedule_date") or "")).strip()
    original_name = str(workout.get("name") or payload.get("name") or workout.get("slug") or "Sesion").strip()
    original_description = str(workout.get("description") or payload.get("description") or "").strip()
    kind = str(workout.get("session_kind") or "other").strip()
    original_steps = clone_steps(payload.get("steps"))
    decision = dashboard.get("decision", {}) if isinstance(dashboard, dict) else {}
    decision_status = str(decision.get("status") or "").strip().lower()
    recommendation = str(decision.get("recommendation") or "").strip()
    original_duration_s = int(payload.get("estimated_duration_s") or 0)
    effective_date = original_date
    effective_name = original_name
    effective_description = original_description
    effective_kind = kind
    effective_duration_s = original_duration_s
    label = "Replanificada"
    summary = "La sesion se ha adaptado en la web segun el contexto actual."
    cause = recommendation or "Cambio manual aplicado desde la web."
    variant = None
    knowledge = workout.get("knowledge") if isinstance(workout.get("knowledge"), dict) else None
    target_kind, target_label = protective_alternative_from_knowledge(workout, strategy)

    if strategy == "auto_today":
        label = "Alternativa para hoy"
        variant = target_label or ("rodaje muy facil" if kind in {"quality", "long_run"} or decision_status == "red" else "version corta")
        if kind in {"quality", "long_run"} or decision_status == "red":
            effective_kind = target_kind or "recovery"
            effective_name = f"Alternativa: {original_name}"
            effective_description = f"Cambio automatico para hoy: sustituir la sesion exigente por una version muy facil y de bajo coste. Referencia protectora: {target_label or 'rodaje suave'} ."
            effective_duration_s = max(1500, int(round(original_duration_s * 0.6))) if original_duration_s else 1800
        else:
            effective_kind = target_kind or "easy"
            effective_name = f"Version corta: {original_name}"
            effective_description = "Cambio automatico para hoy: mantener continuidad con una version mas corta y facil de encajar."
            effective_duration_s = max(1200, int(round(original_duration_s * 0.75))) if original_duration_s else 1500
        summary = "Se ha aplicado una alternativa automatica para hoy."
    elif strategy == "move_next_day":
        effective_date = next_replan_date(original_date, str(workout.get("slug") or ""))
        label = "Movida"
        summary = f"La sesion se mueve del {original_date} al {effective_date}."
        cause = "Se recoloca en el siguiente hueco util para no perder la sesion ni solapar la semana."
        variant = effective_date
    elif strategy == "reduce_keep_goal":
        label = "Carga reducida"
        effective_name = f"{original_name} · version compacta"
        if kind == "quality":
            effective_kind = "quality"
            effective_description = f"Version compacta: menos volumen de calidad y mas margen, manteniendo el objetivo semanal. Referencia: {target_label or 'bloque de calidad corto'}."
            effective_duration_s = max(1500, int(round(original_duration_s * 0.72))) if original_duration_s else 1800
            variant = target_label or "menos repeticiones"
        elif kind == "long_run":
            effective_kind = "easy"
            effective_description = "Version compacta: tirada mas corta y controlada para preservar continuidad sin vaciarte."
            effective_duration_s = max(2400, int(round(original_duration_s * 0.7))) if original_duration_s else 2700
            variant = "tirada recortada"
        else:
            effective_kind = kind if kind in {"easy", "recovery", "strength"} else "easy"
            effective_description = "Version compacta: mismo objetivo general, pero con menos coste y mas margen de ejecucion."
            effective_duration_s = max(900, int(round(original_duration_s * 0.8))) if original_duration_s else 1200
            variant = "volumen reducido"
        summary = "Se reduce la carga de la sesion manteniendo el objetivo semanal."
        cause = "La prioridad es sostener la semana sin perder del todo el estimulo previsto."
    elif strategy == "skip_recompose_week":
        effective_date = next_replan_date(original_date, str(workout.get("slug") or ""))
        label = "Semana recompuesta"
        effective_name = f"{original_name} · recolocada"
        effective_description = "Hoy no se entrena. La sesion se recoloca automaticamente en otro hueco de la semana con una version asumible."
        effective_duration_s = max(1200, int(round(original_duration_s * 0.9))) if original_duration_s else 1500
        summary = f"Hoy queda liberado y la sesion se recompone para el {effective_date}."
        cause = "Se prioriza no entrenar hoy sin romper por completo la logica semanal."
        variant = effective_date

    if knowledge and knowledge.get("primary_goal"):
        cause = f"{cause} Objetivo original protegido: {str(knowledge.get('primary_goal')).lower()}."

    return {
        "status": "applied",
        "strategy": strategy,
        "label": label,
        "summary": summary,
        "cause": cause,
        "variant": variant,
        "original_date": original_date,
        "effective_date": effective_date,
        "effective_name": effective_name,
        "effective_description": effective_description,
        "effective_duration_s": effective_duration_s,
        "effective_steps": original_steps if strategy == "move_next_day" else make_replan_steps(effective_kind, strategy, original_name, effective_duration_s),
        "effective_session_kind": effective_kind,
        "knowledge_label": knowledge.get("label") if knowledge else None,
        "knowledge_goal": knowledge.get("primary_goal") if knowledge else None,
    }


def apply_planned_workout_replan(slug: str, workout: dict[str, Any], strategy: str, dashboard: dict[str, Any], username: str | None) -> dict[str, Any]:
    proposal = generate_replan_proposal(workout, strategy, dashboard)
    payload = load_optional_json(PLANNED_REPLANS_PATH, {"workouts": {}})
    if not isinstance(payload, dict):
        payload = {"workouts": {}}
    workouts = payload.setdefault("workouts", {})
    workouts[slug] = {
        **proposal,
        "updated_at": datetime.now().isoformat(),
        "updated_by": username or "web",
        "slug": slug,
        "name": workout.get("name"),
    }
    write_json(PLANNED_REPLANS_PATH, payload)
    set_planned_workout_action(slug, workout, "replanned", username)
    garmin_ok, garmin_message = retry_garmin_workout_sync(slug, username)
    workouts[slug]["garmin_sync"] = {
        "ok": garmin_ok,
        "message": garmin_message,
        "updated_at": datetime.now().isoformat(),
    }
    write_json(PLANNED_REPLANS_PATH, payload)
    return workouts[slug]


def apply_replan_to_payload(payload: dict[str, Any], replan_state: dict[str, Any] | None) -> dict[str, Any]:
    effective_payload = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    if not replan_state:
        return effective_payload
    if replan_state.get("effective_sport"):
        effective_payload["sport"] = replan_state.get("effective_sport")
    if replan_state.get("effective_name"):
        effective_payload["name"] = replan_state.get("effective_name")
    if replan_state.get("effective_description"):
        effective_payload["description"] = replan_state.get("effective_description")
    if replan_state.get("effective_date"):
        effective_payload["schedule_date"] = replan_state.get("effective_date")
    if replan_state.get("effective_duration_s"):
        effective_payload["estimated_duration_s"] = replan_state.get("effective_duration_s")
    if isinstance(replan_state.get("effective_steps"), list):
        effective_payload["steps"] = clone_steps(replan_state.get("effective_steps"))
    return effective_payload


def automation_safety_policy() -> dict[str, Any]:
    payload = load_optional_yaml(AUTOMATION_SAFETY_PATH).get("automation_safety", {})
    return payload if isinstance(payload, dict) else {}


def auto_replan_allowed(strategy: str, workout: dict[str, Any]) -> bool:
    policy = automation_safety_policy()
    workout_kind = str(workout.get("session_kind") or "other").strip().lower()
    never_auto_session_kinds = set(policy.get("replan", {}).get("never_auto_session_kinds") or [])
    if workout_kind in never_auto_session_kinds:
        return False
    strategy_map = {
        "auto_today": "apply_today_protective_variant",
        "reduce_keep_goal": "reduce_non_race_workout",
        "move_next_day": "move_non_race_workout_to_rest_slot",
        "skip_recompose_week": "recompose_skipped_non_race_session",
    }
    capability = strategy_map.get(strategy)
    allowed = set(policy.get("allow_auto") or [])
    return bool(capability and capability in allowed)


def automatic_replan_suggestion(workout: dict[str, Any] | None, dashboard: dict[str, Any]) -> dict[str, Any] | None:
    if not workout:
        return None
    decision = dashboard.get("decision", {}) if isinstance(dashboard, dict) else {}
    triggers = dashboard.get("adaptation_triggers", {}).get("triggers", []) if isinstance(dashboard, dict) else []
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard, dict) else {}
    active_context = decision.get("active_context", {}) if isinstance(decision, dict) else {}
    workout_kind = str(workout.get("session_kind") or "other").strip().lower()
    if workout_kind == "race":
        return None
    active_trigger_keys = {str(item.get("key") or "") for item in triggers if isinstance(item, dict) and item.get("active")}
    days_to_goal_race = active_context.get("days_to_goal_race")
    race_horizon_days = int(automation_safety_policy().get("replan", {}).get("race_horizon_days") or 4)

    strategy = None
    summary = ""
    label = ""
    tone = "warn"
    if protection_mode.get("key") == "injury_protection" or "pain" in active_trigger_keys:
        strategy = "skip_recompose_week" if workout_kind in {"quality", "long_run"} else "auto_today"
        label = "Proteger por dolor"
        summary = "El contexto actual recomienda proteger tejido y rebajar impacto antes que sostener la sesion original."
    elif "fatigue" in active_trigger_keys:
        strategy = "reduce_keep_goal" if workout_kind in {"quality", "long_run"} else "auto_today"
        label = "Proteger por fatiga"
        summary = "La carga reciente y las señales Garmin sugieren mantener continuidad con una version mas barata."
    elif isinstance(days_to_goal_race, int) and 0 <= days_to_goal_race <= race_horizon_days:
        strategy = "reduce_keep_goal" if workout_kind in {"quality", "long_run"} else "move_next_day"
        label = "Proteger cercania de carrera"
        summary = "Hay carrera cercana y esta sesion no deberia competir contra la frescura necesaria para llegar bien."

    if not strategy:
        return None
    return {
        "strategy": strategy,
        "label": label,
        "summary": summary,
        "tone": tone,
        "auto_allowed": auto_replan_allowed(strategy, workout),
    }


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

    weekly_spike = decision.get("weekly_spike_pct")
    volume_spike = decision.get("volume_spike_pct")
    hrv_flag = str(daily_signals.get("hrv_flag") or "").strip()
    readiness_flag = str(daily_signals.get("readiness_flag") or "").strip()
    resting_hr_flag = str(daily_signals.get("resting_hr_flag") or "").strip()
    sleep_flag = str(daily_signals.get("sleep_flag") or "").strip()
    running_tolerance_flag = str(daily_signals.get("running_tolerance_flag") or "").strip()
    fatigue_active = False
    fatigue_reasons: list[str] = []
    if weekly_spike is not None and float(weekly_spike) >= 25.0:
        fatigue_active = True
        fatigue_reasons.append(f"Volumen semanal +{round(float(weekly_spike))}% frente a la semana completa previa")
    elif volume_spike is not None and float(volume_spike) >= 40.0:
        fatigue_reasons.append(f"Ventana movil 7d +{round(float(volume_spike))}% frente a los 7 dias anteriores")
    if hrv_flag in {"low", "suppressed"}:
        fatigue_active = True
        fatigue_reasons.append("HRV por debajo de la banda habitual")
    if readiness_flag in {"low", "poor"}:
        fatigue_active = True
        fatigue_reasons.append("Readiness diaria baja")
    if sleep_flag == "poor":
        fatigue_active = True
        fatigue_reasons.append("Sueño reciente pobre")
    if resting_hr_flag == "high":
        fatigue_active = True
        fatigue_reasons.append("Pulso en reposo por encima de lo normal")
    if running_tolerance_flag == "high":
        fatigue_active = True
        fatigue_reasons.append("Carga aguda alta frente a la tolerancia reciente")
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

    days_to_goal_race = decision.get("active_context", {}).get("days_to_goal_race") if isinstance(decision.get("active_context"), dict) else None
    race_active = isinstance(days_to_goal_race, int) and 0 <= days_to_goal_race <= 7
    race_summary = f"La carrera objetivo está a {days_to_goal_race} días; conviene priorizar frescura y especificidad." if race_active else "No hay una carrera objetivo inmediata que obligue a tocar el plan por sí sola."
    triggers.append(
        {
            "key": "race_near",
            "label": "Carrera cercana",
            "active": race_active,
            "badge": response_pattern_badge("watch" if race_active else "positive"),
            "summary": race_summary,
            "plan_change": "Recortar o mover sesiones que resten frescura si no son estrictamente útiles para llegar bien." if race_active else "Se puede planificar sin protección específica por carrera cercana.",
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
    replan_state = workout.get("replan_state") if isinstance(workout.get("replan_state"), dict) else None
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

    if replan_state and replan_state.get("status") == "applied":
        status = "adjusted"
        label = str(replan_state.get("label") or "Replanificada")
        tone = "warn"
        summary = str(replan_state.get("summary") or "La sesion tiene una replanificacion aplicada.")
        cause = str(replan_state.get("cause") or "Cambio aplicado desde la web.")
        changed_at = format_datetime(replan_state.get("updated_at"))
        variant = str(replan_state.get("variant") or "").strip() or None
    elif action_key == "alternative_requested":
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


def workout_is_completed(workout: dict[str, Any] | None) -> bool:
    if not isinstance(workout, dict):
        return False
    linked_review = workout.get("linked_review")
    return isinstance(linked_review, dict) and bool(linked_review.get("slug"))


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
    return {"label": "Guardado", "tone": "ok"}


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


def automated_review_summary(payload: dict[str, Any]) -> str | None:
    summary = str(payload.get("coaching_summary") or "").strip()
    if summary:
        return summary
    progression = str((payload.get("progression") or {}).get("summary") or "").strip()
    stimulus = str((payload.get("stimulus_alignment") or {}).get("summary") or "").strip()
    compliance_note = str(payload.get("analysis") or "").strip()
    parts = [item for item in [stimulus, progression, compliance_note] if item]
    if not parts:
        return None
    return " ".join(parts[:3])


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


def today_plan_data(
    day: str | None = None,
    *,
    dashboard: dict[str, Any] | None = None,
    workouts: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target_day = day or date.today().isoformat()
    dashboard = dashboard or dashboard_payload()
    decision = dashboard.get("decision", {})
    guidance = decision.get("session_guidance", {})
    goal_metrics = dashboard.get("goal_gates", {}).get("metrics", {})
    daily_signals = decision.get("daily_signals", {})
    workouts = workouts if workouts is not None else planned_workouts(dashboard)
    reviews = reviews if reviews is not None else completed_reviews()
    planned_today = next((item for item in workouts if item.get("date") == target_day), None)
    race_items = races_by_day().get(target_day, [])
    completed_today = pick_primary_review_for_day(target_day, reviews, planned_today, race_items)
    if planned_today and completed_today and not review_matches_planned_workout(completed_today, planned_today):
        if race_items or str(completed_today.get("session_kind") or "").strip().lower() == "race":
            planned_today = None
    checkin_state = daily_checkin_form_state(daily_checkin(target_day), planned_today)
    checkin_decision = checkin_state.get("decision") if isinstance(checkin_state, dict) else None
    checkin_replan = preferred_replan_suggestion(planned_today, dashboard, checkin_decision)

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

    if checkin_decision and not completed_today:
        if checkin_decision.get("action") == "cancel":
            status = "protective_today"
        elif checkin_decision.get("action") in {"reduce", "move"} and planned_today:
            status = "protective_today"

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
    if checkin_decision:
        why_today_parts.append(str(checkin_decision.get("summary") or "").strip())
    if planned_today:
        knowledge = planned_today.get("knowledge") if isinstance(planned_today.get("knowledge"), dict) else None
        if knowledge and knowledge.get("summary"):
            why_today_parts.append(str(knowledge.get("summary") or "").strip())
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
    if checkin_decision and checkin_decision.get("action") in {"reduce", "move", "cancel"}:
        watchouts.append(str(checkin_decision.get("headline") or "Ajuste recomendado."))
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
        "daily_checkin_visible": bool(planned_today and not completed_today and not checkin_state.get("exists")),
        "feedback_present": bool((completed_today or {}).get("athlete_feedback")),
        "daily_checkin": checkin_state,
        "recommended_replan": checkin_replan if not completed_today and checkin_state.get("exists") else None,
        "knowledge": (planned_today or {}).get("knowledge"),
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


def active_week_title(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Bloque activo"


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


def week_range_labels(start_date: date, end_date: date) -> str:
    return f"{start_date.isoformat()} -> {end_date.isoformat()}"


def workout_distance_km(workout: dict[str, Any]) -> float:
    payload = workout.get("payload", {}) if isinstance(workout.get("payload"), dict) else {}
    distance_m = payload.get("distance_m")
    if distance_m is None:
        distance_m = sum(float(step.get("distance_m") or 0.0) for step in payload.get("steps") or [] if isinstance(step, dict))
    return round(float(distance_m or 0.0) / 1000.0, 2)


def iso_week_bounds(value: date) -> tuple[date, date]:
    start = value.fromordinal(value.toordinal() - value.weekday())
    end = start.fromordinal(start.toordinal() + 6)
    return start, end


def next_monday_after(value: date) -> date:
    delta = 7 - value.weekday()
    if delta <= 0:
        delta += 7
    return value.fromordinal(value.toordinal() + delta)


def weekly_planning_state() -> dict[str, Any]:
    payload = load_optional_json(WEEKLY_PLANNING_STATE_PATH, {"prepared_weeks": {}})
    return payload if isinstance(payload, dict) else {"prepared_weeks": {}}


def weekly_sync_badge(status: str) -> dict[str, str]:
    mapping = {
        "ok": {"label": "Sincronizado", "tone": "ok"},
        "skipped": {"label": "Sin cambios", "tone": ""},
        "error": {"label": "Error", "tone": "warn"},
    }
    return mapping.get(str(status or "").strip().lower(), {"label": "Desconocido", "tone": ""})


def summarize_weekly_garmin_sync(sync_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(sync_payload, dict):
        return None
    items = sync_payload.get("items") if isinstance(sync_payload.get("items"), list) else []
    summarized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_message = str(item.get("message") or "").strip()
        parsed_message = None
        if raw_message.startswith("{"):
            try:
                parsed = json.loads(raw_message)
                if isinstance(parsed, dict):
                    parsed_message = parsed
            except json.JSONDecodeError:
                parsed_message = None
        summarized_items.append(
            {
                "file": str(item.get("file") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "badge": weekly_sync_badge(item.get("status") or ""),
                "workout_name": str((parsed_message or {}).get("workout_name") or Path(str(item.get("file") or "")).stem).strip(),
                "schedule_date": str((parsed_message or {}).get("schedule_date") or "").strip() or None,
                "sport": str((parsed_message or {}).get("sport") or "").strip() or None,
                "workout_id": (parsed_message or {}).get("workout_id"),
                "summary": raw_message.splitlines()[-1] if raw_message else "Sin detalle adicional.",
            }
        )
    return {
        "synced": int(sync_payload.get("synced") or 0),
        "failed": int(sync_payload.get("failed") or 0),
        "skipped": int(sync_payload.get("skipped") or 0),
        "items": summarized_items,
    }


def summarize_weekly_pdf_status(pdf_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(pdf_payload, dict):
        return None
    ok = bool(pdf_payload.get("ok"))
    return {
        "ok": ok,
        "badge": {"label": "Enviado" if ok else "Fallo", "tone": "ok" if ok else "warn"},
        "message": str(pdf_payload.get("message") or "").strip() or ("PDF enviado por Telegram." if ok else "No se pudo enviar el PDF por Telegram."),
    }


def weekly_planning_status() -> dict[str, Any]:
    state = weekly_planning_state()
    active_content = read_text(ACTIVE_WEEK_PATH)
    active_start, active_end = parse_week_date_window(active_content)
    target_start = next_monday_after(active_end) if active_end else None
    target_end = target_start.fromordinal(target_start.toordinal() + 6) if target_start else None
    prepared_entry = None
    prepared_path = None
    if target_start and target_end:
        prepared_entry = (state.get("prepared_weeks", {}) or {}).get(target_start.isoformat()) if isinstance(state.get("prepared_weeks"), dict) else None
        prepared_path = ROOT / str((prepared_entry or {}).get("path") or f"planning/weeks/prepared/{target_start.year}/{target_start.isoformat()}_{target_end.isoformat()}.md")
    prepared_exists = bool(prepared_path and prepared_path.exists())
    if not isinstance(prepared_entry, dict) and prepared_exists and target_start and target_end:
        prepared_entry = {
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "path": str(prepared_path.relative_to(ROOT)),
            "status": "prepared",
        }
    if isinstance(prepared_entry, dict):
        prepared_entry = {
            **prepared_entry,
            "garmin_sync_summary": summarize_weekly_garmin_sync(prepared_entry.get("garmin_sync") if isinstance(prepared_entry.get("garmin_sync"), dict) else None),
        }
    last_activation = state.get("last_activation") if isinstance(state.get("last_activation"), dict) else None
    if isinstance(last_activation, dict):
        last_activation = {
            **last_activation,
            "pdf_summary": summarize_weekly_pdf_status(last_activation.get("pdf") if isinstance(last_activation.get("pdf"), dict) else None),
            "garmin_sync_summary": summarize_weekly_garmin_sync(last_activation.get("garmin_sync") if isinstance(last_activation.get("garmin_sync"), dict) else None),
        }
    return {
        "active_week": {
            "title": active_week_title(active_content),
            "start_date": active_start.isoformat() if active_start else None,
            "end_date": active_end.isoformat() if active_end else None,
        },
        "next_target": {
            "start_date": target_start.isoformat() if target_start else None,
            "end_date": target_end.isoformat() if target_end else None,
        },
        "prepared_exists": prepared_exists,
        "prepared_week": prepared_entry,
        "last_plan": state.get("last_plan"),
        "last_activation": last_activation,
    }


def adherence_badge(value: float) -> dict[str, str]:
    if value >= 85.0:
        return {"label": "Alta", "tone": "ok"}
    if value >= 60.0:
        return {"label": "Media", "tone": "warn"}
    return {"label": "Baja", "tone": "warn"}


def plan_vs_reality_summary(start_date: date | None, end_date: date | None, title: str) -> dict[str, Any]:
    if not start_date or not end_date:
        return {"available": False, "weeks": [], "block": None}

    workouts = [
        item for item in planned_workouts()
        if parse_iso_date(item.get("date")) and start_date <= parse_iso_date(item.get("date")) <= end_date
    ]
    reviews = [
        item for item in completed_reviews()
        if parse_iso_date(item.get("date")) and start_date <= parse_iso_date(item.get("date")) <= end_date
    ]
    today = date.today()

    def summary_for_window(window_start: date, window_end: date, label: str) -> dict[str, Any]:
        window_workouts = [
            item for item in workouts
            if parse_iso_date(item.get("date")) and window_start <= parse_iso_date(item.get("date")) <= window_end
        ]
        window_reviews = [
            item for item in reviews
            if parse_iso_date(item.get("date")) and window_start <= parse_iso_date(item.get("date")) <= window_end
        ]
        window_planned_slugs = {item.get("slug") for item in window_workouts if item.get("slug")}
        matched_slugs = {item.get("slug") for item in window_reviews if item.get("slug") in window_planned_slugs}
        planned_km = round(sum(workout_distance_km(item) for item in window_workouts), 2)
        actual_km = round(sum(float(item.get("distance_km") or 0.0) for item in window_reviews), 2)
        planned_quality = sum(1 for item in window_workouts if item.get("session_kind") == "quality")
        completed_quality = sum(1 for item in window_reviews if item.get("session_kind") == "quality")
        skipped = 0
        for item in window_workouts:
            action_state = item.get("action_state") if isinstance(item.get("action_state"), dict) else {}
            planned_day = parse_iso_date(item.get("date"))
            if str(action_state.get("action") or "") == "skipped":
                skipped += 1
            elif planned_day and planned_day <= today and item.get("slug") not in matched_slugs:
                skipped += 1
        reprogrammed = sum(1 for item in window_workouts if isinstance(item.get("replan_state"), dict) and item["replan_state"].get("status") == "applied")
        adherence_pct = round((len(matched_slugs) / len(window_workouts)) * 100.0, 1) if window_workouts else 0.0
        return {
            "label": label,
            "range": week_range_labels(window_start, window_end),
            "planned_sessions": len(window_workouts),
            "completed_sessions": len(matched_slugs),
            "planned_km": planned_km,
            "actual_km": actual_km,
            "km_delta": round(actual_km - planned_km, 2),
            "planned_quality": planned_quality,
            "completed_quality": completed_quality,
            "skipped_sessions": skipped,
            "reprogrammed_sessions": reprogrammed,
            "adherence_pct": adherence_pct,
            "adherence_badge": adherence_badge(adherence_pct),
        }

    week_windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        week_start, week_end = iso_week_bounds(cursor)
        bounded_start = week_start if week_start >= start_date else start_date
        bounded_end = week_end if week_end <= end_date else end_date
        if not week_windows or week_windows[-1] != (bounded_start, bounded_end):
            week_windows.append((bounded_start, bounded_end))
        cursor = week_end.fromordinal(week_end.toordinal() + 1)

    week_summaries = [
        summary_for_window(window_start, window_end, f"Semana {index}")
        for index, (window_start, window_end) in enumerate(week_windows, start=1)
    ]

    block_summary = summary_for_window(start_date, end_date, title)
    return {"available": True, "weeks": week_summaries, "block": block_summary}


def weekly_goal_sentence(dashboard: dict[str, Any], rows: list[dict[str, str]]) -> str:
    decision = dashboard.get("decision", {}) if isinstance(dashboard.get("decision"), dict) else {}
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard.get("protection_mode"), dict) else {}
    descriptions = " ".join(str(row.get("description") or "") for row in rows).lower()
    if protection_mode.get("active"):
        return "Proteger tejido y sostener continuidad sin buscar carga extra."
    if "carrera" in descriptions or "edicion" in descriptions or any("carrera" in str(row.get("description") or "").lower() for row in rows):
        return "Llegar con frescura suficiente y ejecutar lo importante sin añadir fatiga inútil."
    status = str(decision.get("status") or "").lower()
    if status == "red":
        return "Bajar exigencia, quitar coste innecesario y conservar la continuidad de la semana."
    if status == "yellow":
        return "Mantener la estructura semanal sin progresar carga y con margen de adaptación."
    return "Completar la semana con continuidad y una progresión pequeña si las sensaciones acompañan."


def session_focus(row: dict[str, Any], linked_workout: dict[str, Any] | None, replan: dict[str, Any] | None) -> str:
    if replan and replan.get("is_changed"):
        status = str(replan.get("status") or "")
        if status in {"adjusted", "adjustable", "protected"}:
            return "Ejecutar con margen y aceptar la versión protectora si el día no sale limpio."
    if linked_workout:
        kind = str(linked_workout.get("session_kind") or "other")
        mapping = {
            "recovery": "Absorber carga y proteger tejido sin buscar estímulo extra.",
            "easy": "Sumar continuidad con coste controlado y ritmo conversacional.",
            "quality": "Estimular calidad sin salirte del margen que permite el estado actual.",
            "long_run": "Construir durabilidad sin convertir la sesión en un desgaste grande.",
            "strength": "Consolidar fuerza útil sin dejar fatiga residual alta.",
            "race": "Ejecutar con control y priorizar el objetivo competitivo del día.",
        }
        return mapping.get(kind, "Mantener continuidad con una carga adecuada al contexto actual.")
    description = str(row.get("description") or "").lower()
    distance = str(row.get("distance") or "").lower()
    if distance == "0 km" or "descanso" in description or "movilidad" in description:
        return "Recuperar, descargar y preparar mejor la siguiente sesión útil."
    if "rectas" in description or "ritmo" in str(row.get("target") or "").lower() or "bloques" in description:
        return "Activar sin desbordar el coste de la semana."
    if "carrera" in description or "edicion" in description:
        return "Competir o ejecutar con control según el papel de la carrera dentro del bloque."
    return "Sostener continuidad y no regalar fatiga innecesaria."


def weekly_status_payload(block: dict[str, Any] | None, dashboard: dict[str, Any]) -> dict[str, Any]:
    if not block:
        return {"status": "unknown", "label": "Sin lectura", "tone": "", "summary": "No hay datos suficientes para valorar la semana."}
    adherence = float(block.get("adherence_pct") or 0.0)
    skipped = int(block.get("skipped_sessions") or 0)
    reprogrammed = int(block.get("reprogrammed_sessions") or 0)
    decision = dashboard.get("decision", {}) if isinstance(dashboard.get("decision"), dict) else {}
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard.get("protection_mode"), dict) else {}
    status = "green"
    label = "Cumplimiento alto"
    summary = "La semana se está sosteniendo bien con el contexto actual."
    if protection_mode.get("active") or str(decision.get("status") or "") == "red":
        status = "yellow"
        label = "Semana protegida"
        summary = "La prioridad es respetar el contexto de protección más que perseguir cumplimiento bruto."
    if adherence < 60.0 or skipped >= 2:
        status = "red"
        label = "Cumplimiento frágil"
        summary = "Se están acumulando demasiadas pérdidas o desvíos para considerar la semana estable."
    elif adherence < 85.0 or reprogrammed >= 1 or str(decision.get("status") or "") == "yellow":
        status = "yellow"
        label = "Cumplimiento vigilado"
        summary = "La semana sigue viva, pero ya necesita ajustes o más margen de ejecución."
    return {"status": status, "label": label, "tone": "ok" if status == "green" else "warn" if status in {"yellow", "red"} else "", "summary": summary}


def executive_week_summary(rows: list[dict[str, Any]], dashboard: dict[str, Any], plan_vs_reality: dict[str, Any]) -> dict[str, Any]:
    workouts = [row.get("linked_workout") for row in rows if isinstance(row.get("linked_workout"), dict)]
    planned_total_km = round(sum(workout_distance_km(item) for item in workouts if isinstance(item, dict)), 2)
    planned_total_duration_s = sum(int((item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}).get("estimated_duration_s") or 0) for item in workouts if isinstance(item, dict))
    planned_quality_sessions = sum(1 for item in workouts if isinstance(item, dict) and item.get("session_kind") == "quality")
    planned_total_sessions = len(workouts)
    block = (plan_vs_reality or {}).get("block") if isinstance(plan_vs_reality, dict) else None
    completed_sessions = int((block or {}).get("completed_sessions") or 0)
    remaining_sessions = max(0, planned_total_sessions - completed_sessions)
    completed_km = float((block or {}).get("actual_km") or 0.0)
    completion_pct = round((completed_sessions / planned_total_sessions) * 100.0, 1) if planned_total_sessions else 0.0
    weekly_status = weekly_status_payload(block, dashboard)
    return {
        "goal_sentence": weekly_goal_sentence(dashboard, rows),
        "planned_total_km": planned_total_km,
        "planned_total_duration": format_duration(planned_total_duration_s),
        "planned_quality_sessions": planned_quality_sessions,
        "planned_total_sessions": planned_total_sessions,
        "completed_sessions": completed_sessions,
        "remaining_sessions": remaining_sessions,
        "completed_km": round(completed_km, 2),
        "completion_pct": completion_pct,
        "adherence_pct": float((block or {}).get("adherence_pct") or 0.0),
        "weekly_status": weekly_status,
    }


def week_document_data(
    path: Path,
    *,
    include_planning_status: bool = False,
    dashboard: dict[str, Any] | None = None,
    workouts: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content = read_text(path)
    rows = parse_week_table(content)
    start_date, end_date = parse_week_date_window(content)
    title = active_week_title(content)
    dashboard = dashboard or dashboard_payload()
    workouts = workouts if workouts is not None else planned_workouts(dashboard)
    reviews = reviews if reviews is not None else completed_reviews()
    plan_vs_reality = plan_vs_reality_summary(start_date, end_date, title)
    planned_by_date = {item.get("date"): item for item in workouts if item.get("date")}
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        row_date = resolve_week_row_date(row.get("day", ""), start_date, end_date)
        linked_workout = planned_by_date.get(row_date) if row_date else None
        linked_review = find_review_for_planned_workout(linked_workout, reviews) if linked_workout else None
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
                "focus": session_focus(row, linked_workout, replan),
            }
        )
    return {
        "exists": path.exists(),
        "path": str(path.relative_to(ROOT)) if path.exists() else str(path.relative_to(ROOT)),
        "title": title,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "content": content,
        "rows": enriched_rows,
        "executive_summary": executive_week_summary(enriched_rows, dashboard, plan_vs_reality),
        "plan_vs_reality": plan_vs_reality,
        "pdf_exists": path == ACTIVE_WEEK_PATH and (ROOT / "planning" / "weeks" / "generated" / "semana_actual.pdf").exists(),
        "planning_status": weekly_planning_status() if include_planning_status else None,
    }


def week_page_data(
    *,
    dashboard: dict[str, Any] | None = None,
    workouts: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return week_document_data(ACTIVE_WEEK_PATH, include_planning_status=True, dashboard=dashboard, workouts=workouts, reviews=reviews)


def prepared_week_path_for_start(start_date: str) -> Path | None:
    parsed = parse_iso_date(start_date)
    if not parsed:
        return None
    state = weekly_planning_state()
    entry = (state.get("prepared_weeks", {}) or {}).get(parsed.isoformat()) if isinstance(state.get("prepared_weeks"), dict) else None
    if isinstance(entry, dict) and entry.get("path"):
        candidate = ROOT / str(entry.get("path"))
        return candidate if candidate.exists() else None
    year_dir = ROOT / "planning" / "weeks" / "prepared" / str(parsed.year)
    if not year_dir.exists():
        return None
    matches = sorted(year_dir.glob(f"{parsed.isoformat()}_*.md"))
    return matches[0] if matches else None


def prepared_week_page_data(start_date: str) -> dict[str, Any] | None:
    path = prepared_week_path_for_start(start_date)
    if not path:
        return None
    payload = week_document_data(path, include_planning_status=False)
    payload["week_start"] = start_date
    state = weekly_planning_state()
    entry = (state.get("prepared_weeks", {}) or {}).get(start_date) if isinstance(state.get("prepared_weeks"), dict) else None
    payload["prepared_state"] = entry if isinstance(entry, dict) else None
    payload["garmin_sync_summary"] = summarize_weekly_garmin_sync((entry or {}).get("garmin_sync") if isinstance(entry, dict) and isinstance(entry.get("garmin_sync"), dict) else None)
    return payload


def planned_upload_data(workout_stem: str, schedule_date: str) -> dict[str, Any]:
    upload_path = PLANNED_WORKOUTS_DIR / schedule_date / f"{workout_stem}.garmin_upload.json"
    return load_json(upload_path) if upload_path.exists() else {}


def planned_workout_file(slug: str) -> Path:
    return PLANNED_WORKOUTS_DIR / f"{slug}.yaml"


def clear_planned_upload_data(slug: str, keep_path: Path | None = None) -> None:
    for upload_path in PLANNED_WORKOUTS_DIR.glob(f"*/{slug}.garmin_upload.json"):
        if keep_path and upload_path == keep_path:
            continue
        upload_path.unlink(missing_ok=True)


def garmin_sync_workout_file(slug: str) -> Path:
    workout_file = planned_workout_file(slug)
    replan_state = planned_workout_replan(slug)
    if not replan_state:
        return workout_file

    spec = load_yaml(workout_file)
    workout_payload = spec.get("workout", {}) if isinstance(spec, dict) else {}
    effective_payload = apply_replan_to_payload(workout_payload, replan_state)
    temp_dir = Path(tempfile.gettempdir()) / "personal-trainer" / "garmin-replans"
    temp_file = temp_dir / f"{slug}.yaml"
    write_yaml(temp_file, {"workout": effective_payload})
    return temp_file


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

    sync_workout_file = garmin_sync_workout_file(slug)
    command = [sys.executable, str(GARMIN_SYNC_SCRIPT), "schedule-workout-file", str(sync_workout_file)]
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
        sync_payload = load_yaml(sync_workout_file).get("workout", {}) if sync_workout_file.exists() else {}
        expected_schedule_date = str(sync_payload.get("schedule_date") or "").strip()
        expected_upload_path = PLANNED_WORKOUTS_DIR / expected_schedule_date / f"{slug}.garmin_upload.json" if expected_schedule_date else None
        clear_planned_upload_data(slug, expected_upload_path)
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


def run_weekly_planning_pipeline(*args: str) -> tuple[bool, dict[str, Any], str]:
    command = [sys.executable, str(WEEKLY_PLANNING_SCRIPT), *args]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=3600, check=False)
    except subprocess.TimeoutExpired:
        return False, {}, "La planificacion semanal excedio el tiempo maximo."
    payload: dict[str, Any] = {}
    if (result.stdout or "").strip():
        try:
            parsed = json.loads(result.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    ok = result.returncode == 0 and bool(payload.get("ok"))
    message = str(payload.get("message") or result.stderr or result.stdout or "Operacion semanal sin salida.").strip()
    return ok, payload, message


def dashboard_payload() -> dict[str, Any]:
    status = workspace_status()
    response_patterns = athlete_response_patterns()
    pipeline_status = automation_pipeline_status()
    athlete_state_capability = ensure_fresh("athlete_state")
    athlete_state = load_optional_json(ATHLETE_STATE_PATH, {})
    if not COACH_DECISION_PATH.exists():
        payload = empty_dashboard_payload(status)
        payload["response_patterns"] = response_patterns
        payload["adaptation_triggers"] = adaptation_triggers(payload)
        payload["protection_mode"] = protection_mode_payload(payload)
        payload["readiness_card"] = readiness_card_payload(payload)
        payload["automation_pipeline"] = pipeline_status
        payload["athlete_state"] = athlete_state
        payload["capability_messages"] = [message for message in [athlete_state_capability.warning] if message]
        return payload
    decision_capability = ensure_fresh("coach_decision")
    path = COACH_DECISION_PATH
    payload = load_json(path) if path.exists() else {}
    payload["capability_messages"] = [message for message in [decision_capability.warning, athlete_state_capability.warning] if message]
    payload["response_patterns"] = response_patterns
    payload["adaptation_triggers"] = adaptation_triggers(payload)
    payload["protection_mode"] = protection_mode_payload(payload)
    payload["readiness_card"] = readiness_card_payload(payload)
    payload["automation_pipeline"] = pipeline_status
    payload["athlete_state"] = athlete_state

    session_family_labels = {
        "easy_recovery": "Rodaje de recuperacion",
        "recovery_plus_mobility": "Recuperacion con movilidad",
        "walk_run_return": "Camina-corre retorno",
        "continuous_easy_return": "Rodaje continuo de retorno",
        "intro_fartlek_time_based": "Fartlek introductorio",
        "bike_easy_aerobic": "Bici aeróbica base",
        "bike_tempo_support": "Bici tempo de soporte",
        "bike_vo2_support": "Bici VO2 de soporte",
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


def parse_local_summary_date(value: Any) -> date | None:
    if not value:
        return None
    return parse_iso_date(str(value).split(" ")[0])


def running_activity_summaries() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(GARMIN_ACTIVITY_DIR.glob("*/summary.json")):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        activity_type = str(((payload.get("activityType") or {}) if isinstance(payload.get("activityType"), dict) else {}).get("typeKey") or "")
        if activity_type not in {"running", "trail_running"}:
            continue
        activity_date = parse_local_summary_date(payload.get("startTimeLocal") or payload.get("startTimeGMT"))
        if not activity_date:
            continue
        distance_m = float(payload.get("distance") or 0.0)
        duration_s = float(payload.get("duration") or payload.get("movingDuration") or 0.0)
        if distance_m <= 0 or duration_s <= 0:
            continue
        items.append(
            {
                "date": activity_date,
                "name": payload.get("activityName") or path.parent.name,
                "distance_km": distance_m / 1000.0,
                "duration_s": duration_s,
                "pace_s_per_km": (duration_s * 1000.0 / distance_m) if distance_m else None,
                "avg_hr": float(payload.get("averageHR") or 0.0) or None,
                "activity_id": payload.get("activityId"),
            }
        )
    items.sort(key=lambda item: item["date"])
    return items


def imported_activity_type_label(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return {
        "running": "Correr",
        "trail_running": "Trail",
        "walking": "Caminar",
        "cycling": "Bici",
        "road_biking": "Bici",
        "indoor_cycling": "Bici indoor",
        "strength_training": "Fuerza",
        "elliptical": "Elíptica",
        "fitness_equipment": "Cardio",
        "swimming": "Natación",
        "mobility": "Movilidad",
        "stretching": "Movilidad",
    }.get(normalized, normalized.replace("_", " ").title() or "Actividad")


def imported_garmin_activities(day: str, reviewed_activity_ids: set[int] | None = None) -> list[dict[str, Any]]:
    reviewed_ids = reviewed_activity_ids or set()
    items: list[dict[str, Any]] = []
    for path in sorted(GARMIN_ACTIVITY_DIR.glob(f"{day}_*/summary.json")):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        activity_id = int(payload.get("activityId") or 0)
        if not activity_id or activity_id in reviewed_ids:
            continue
        distance_m = float(payload.get("distance") or 0.0)
        duration_s = float(payload.get("duration") or payload.get("movingDuration") or 0.0)
        activity_type = str(((payload.get("activityType") or {}) if isinstance(payload.get("activityType"), dict) else {}).get("typeKey") or "").strip().lower()
        items.append(
            {
                "slug": f"garmin-import-{activity_id}",
                "date": day,
                "activity_name": payload.get("activityName") or path.parent.name,
                "name": payload.get("activityName") or path.parent.name,
                "distance_km": round(distance_m / 1000.0, 2) if distance_m > 0 else 0.0,
                "duration": format_duration(duration_s),
                "pace": format_pace((duration_s * 1000.0 / distance_m) if distance_m > 0 and duration_s > 0 else None),
                "avg_hr": payload.get("averageHR") or "-",
                "traffic_light": "Importada",
                "compliance_note": "Actividad Garmin importada todavía sin revisión asociada.",
                "feedback_summary": None,
                "sport": activity_type or "other",
                "sport_label": imported_activity_type_label(activity_type),
                "intensity_label": "Importada",
                "session_kind_label": imported_activity_type_label(activity_type),
                "calendar_color_class": "intensity-easy",
                "calendar_inline_style": "",
                "primary_icon": "",
                "detail_url": f"/completed-workouts/garmin-import-{activity_id}",
                "garmin_activity_id": activity_id,
                "payload": {"summary": payload},
                "is_imported_only": True,
            }
        )
    return items


def imported_garmin_activity_detail(activity_id: Any) -> dict[str, Any] | None:
    summary = garmin_activity_summary_payload(activity_id)
    if not isinstance(summary, dict) or not summary:
        return None
    parsed_date = parse_local_summary_date(summary.get("startTimeLocal") or summary.get("startTimeGMT"))
    date_text = parsed_date.isoformat() if parsed_date else ""
    distance_m = float(summary.get("distance") or 0.0)
    duration_s = float(summary.get("duration") or summary.get("movingDuration") or 0.0)
    activity_type = str(((summary.get("activityType") or {}) if isinstance(summary.get("activityType"), dict) else {}).get("typeKey") or "").strip().lower()
    review_payload = {
        "planned": {"date": date_text, "name": summary.get("activityName") or f"Actividad Garmin {activity_id}", "sport": activity_type or "other"},
        "summary": {
            "activity_id": summary.get("activityId"),
            "activity_name": summary.get("activityName"),
            "distance_m": distance_m,
            "duration_s": duration_s,
            "pace_s_per_km": (duration_s * 1000.0 / distance_m) if distance_m > 0 and duration_s > 0 else None,
            "avg_hr": summary.get("averageHR"),
        },
    }
    return {
        "slug": f"garmin-import-{activity_id}",
        "date": date_text,
        "name": summary.get("activityName") or f"Actividad Garmin {activity_id}",
        "score": "-",
        "traffic_light": "Importada",
        "risk_level": "-",
        "distance_km": round(distance_m / 1000.0, 2) if distance_m > 0 else 0.0,
        "duration": format_duration(duration_s),
        "pace": format_pace((duration_s * 1000.0 / distance_m) if distance_m > 0 and duration_s > 0 else None),
        "avg_hr": summary.get("averageHR") or "-",
        "garmin_activity_id": summary.get("activityId"),
        "garmin_activity_url": garmin_activity_url(summary.get("activityId")),
        "garmin_workout_id": None,
        "garmin_workout_url": None,
        "activity_name": summary.get("activityName") or f"Actividad Garmin {activity_id}",
        "planned_session_reference": None,
        "sport": activity_type or "other",
        "session_kind": activity_type or "other",
        "session_kind_label": imported_activity_type_label(activity_type),
        "session_color_class": "intensity-easy",
        "compliance_note": "Actividad Garmin importada en local sin revisión automática asociada.",
        "automated_review_summary": "Disponible para consulta y planificación aunque no tenga review enlazada.",
        "athlete_feedback": None,
        "feedback_badge": feedback_badge(None),
        "feedback_summary": None,
        "feedback_form": feedback_form_state(None),
        "feedback_locked": False,
        "recovery_analysis": build_recovery_analysis(review_payload),
        "payload": review_payload,
        "is_imported_only": True,
    }


def activity_window_stats(activities: list[dict[str, Any]], start: date, end: date, min_distance_km: float = 4.0, max_distance_km: float = 12.5) -> dict[str, Any]:
    window = [
        item for item in activities
        if start <= item["date"] <= end and min_distance_km <= float(item.get("distance_km") or 0.0) <= max_distance_km
    ]
    total_distance = sum(float(item.get("distance_km") or 0.0) for item in window)
    total_duration = sum(float(item.get("duration_s") or 0.0) for item in window)
    weighted_hr_num = sum(float(item.get("avg_hr") or 0.0) * float(item.get("duration_s") or 0.0) for item in window if item.get("avg_hr") is not None)
    avg_hr = weighted_hr_num / total_duration if total_duration else None
    pace = total_duration / total_distance if total_distance else None
    return {
        "count": len(window),
        "avg_pace_s_per_km": pace,
        "avg_hr": avg_hr,
        "avg_distance_km": (total_distance / len(window)) if window else None,
        "items": window,
    }


def feedback_window_stats(feedback_map: dict[str, dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    values: list[int] = []
    for payload in feedback_map.values():
        if not isinstance(payload, dict):
            continue
        feedback_date = parse_iso_date(str(payload.get("date") or ""))
        if not feedback_date or not (start <= feedback_date <= end):
            continue
        athlete_feedback = payload.get("athlete_feedback", {}) if isinstance(payload.get("athlete_feedback"), dict) else {}
        rpe = athlete_feedback.get("rpe")
        if rpe is None:
            continue
        values.append(int(rpe))
    return {"count": len(values), "avg_rpe": (sum(values) / len(values)) if values else None}


def progress_trend_insights(dashboard: dict[str, Any]) -> dict[str, Any]:
    activities = running_activity_summaries()
    feedback_map = completed_feedback_items()
    as_of = parse_iso_date(str(dashboard.get("as_of") or date.today().isoformat())) or date.today()
    recent_start = as_of - timedelta(days=27)
    previous_start = as_of - timedelta(days=55)
    previous_end = as_of - timedelta(days=28)
    recent = activity_window_stats(activities, recent_start, as_of)
    previous = activity_window_stats(activities, previous_start, previous_end)
    recent_feedback = feedback_window_stats(feedback_map, recent_start, as_of)
    previous_feedback = feedback_window_stats(feedback_map, previous_start, previous_end)

    pace_delta = None
    if recent.get("avg_pace_s_per_km") is not None and previous.get("avg_pace_s_per_km") is not None:
        pace_delta = float(previous["avg_pace_s_per_km"]) - float(recent["avg_pace_s_per_km"])
    hr_delta = None
    if recent.get("avg_hr") is not None and previous.get("avg_hr") is not None:
        hr_delta = float(previous["avg_hr"]) - float(recent["avg_hr"])
    rpe_delta = None
    if recent_feedback.get("avg_rpe") is not None and previous_feedback.get("avg_rpe") is not None:
        rpe_delta = float(previous_feedback["avg_rpe"]) - float(recent_feedback["avg_rpe"])

    comparison_state = "igual"
    comparison_summary = "No hay suficiente cambio consolidado para afirmar una mejora o una caída clara respecto a hace 4 semanas."
    if pace_delta is not None:
        if pace_delta >= 8.0 and (hr_delta is None or hr_delta >= -3.0):
            comparison_state = "mejor"
            comparison_summary = "Vas mejor que hace 4 semanas: en los rodajes comparables recientes sale más ritmo para un coste similar."
        elif pace_delta <= -8.0 or (hr_delta is not None and hr_delta <= -6.0):
            comparison_state = "peor"
            comparison_summary = "Vas peor que hace 4 semanas: el ritmo comparable ha caído o el coste cardiaco ha subido demasiado."

    trend_rows = [
        {
            "label": "Ritmo comparable",
            "current": format_pace(recent.get("avg_pace_s_per_km")),
            "previous": format_pace(previous.get("avg_pace_s_per_km")),
            "delta": f"{pace_delta:+.0f} s/km" if pace_delta is not None else "Sin base",
            "tone": "ok" if pace_delta is not None and pace_delta > 0 else "warn" if pace_delta is not None and pace_delta < 0 else "",
            "detail": f"Rodajes comparables 4-12.5 km · {recent.get('count', 0)} recientes vs {previous.get('count', 0)} previos.",
        },
        {
            "label": "FC comparable",
            "current": f"{round(float(recent['avg_hr']))} ppm" if recent.get("avg_hr") is not None else "Sin base",
            "previous": f"{round(float(previous['avg_hr']))} ppm" if previous.get("avg_hr") is not None else "Sin base",
            "delta": f"{hr_delta:+.0f} ppm" if hr_delta is not None else "Sin base",
            "tone": "ok" if hr_delta is not None and hr_delta > 0 else "warn" if hr_delta is not None and hr_delta < 0 else "",
            "detail": "Menor FC para esfuerzos comparables suele apuntar a mejor eficiencia.",
        },
        {
            "label": "RPE subjetivo",
            "current": f"{recent_feedback['avg_rpe']:.1f}/10" if recent_feedback.get("avg_rpe") is not None else "Sin feedback",
            "previous": f"{previous_feedback['avg_rpe']:.1f}/10" if previous_feedback.get("avg_rpe") is not None else "Sin feedback",
            "delta": f"{rpe_delta:+.1f}" if rpe_delta is not None else "Pendiente",
            "tone": "ok" if rpe_delta is not None and rpe_delta > 0 else "warn" if rpe_delta is not None and rpe_delta < 0 else "",
            "detail": "Esta métrica mejorará cuando haya más feedback subjetivo registrado.",
        },
    ]

    comparable_sessions: list[dict[str, Any]] = []
    buckets = [
        ("5k-ish", 4.0, 6.5),
        ("10k-ish", 8.0, 12.5),
        ("tirada larga", 12.5, 40.0),
    ]
    recent_90 = [item for item in activities if item["date"] >= as_of - timedelta(days=89)]
    for label, min_distance, max_distance in buckets:
        candidates = [item for item in recent_90 if min_distance <= float(item.get("distance_km") or 0.0) <= max_distance]
        if not candidates:
            continue
        best = min(candidates, key=lambda item: float(item.get("pace_s_per_km") or 10**9))
        comparable_sessions.append(
            {
                "label": label,
                "date": best["date"].isoformat(),
                "name": best.get("name") or label,
                "distance": f"{float(best.get('distance_km') or 0.0):.1f} km",
                "pace": format_pace(best.get("pace_s_per_km")),
                "avg_hr": f"{round(float(best['avg_hr']))} ppm" if best.get("avg_hr") is not None else "-",
                "url": garmin_activity_url(best.get("activity_id")),
            }
        )

    block_title = str(dashboard.get("active_context", {}).get("active_block") or "Bloque activo")
    weekly_volume = dashboard.get("weekly_volume", []) if isinstance(dashboard.get("weekly_volume"), list) else []
    recent_weekly = weekly_volume[-4:]
    previous_weekly = weekly_volume[-8:-4]
    recent_avg_km = (sum(float(item.get("km") or 0.0) for item in recent_weekly) / len(recent_weekly)) if recent_weekly else None
    previous_avg_km = (sum(float(item.get("km") or 0.0) for item in previous_weekly) / len(previous_weekly)) if previous_weekly else None
    form_blocks = [
        {
            "label": "Hace 8-4 semanas",
            "status": "Base de comparación",
            "metric": f"{previous_avg_km:.1f} km/sem" if previous_avg_km is not None else "Sin base",
            "detail": "Promedio semanal del bloque inmediatamente anterior de 4 semanas.",
        },
        {
            "label": "Últimas 4 semanas",
            "status": "Forma reciente",
            "metric": f"{recent_avg_km:.1f} km/sem" if recent_avg_km is not None else "Sin base",
            "detail": "Volumen reciente medio combinado con la lectura actual del dashboard.",
        },
        {
            "label": strip_markdown_ticks(block_title),
            "status": dashboard.get("decision", {}).get("status_label") or "Sin decisión",
            "metric": format_duration(dashboard.get("performance_estimate", {}).get("current_10k_estimate_s")) if dashboard.get("performance_estimate", {}).get("current_10k_estimate_s") else "Sin estimación",
            "detail": "Estimación de forma operativa del bloque actual usando la decisión del coach y la predicción vigente.",
        },
    ]

    return {
        "trends": trend_rows,
        "comparison_4w": {"state": comparison_state, "summary": comparison_summary},
        "comparable_sessions": comparable_sessions[:3],
        "form_blocks": form_blocks,
    }


def progress_page_data() -> dict[str, Any]:
    dashboard = dashboard_payload()
    master_plan = master_plan_page_data()
    metrics = progress_metrics()
    goal_gates = dashboard.get("goal_gates", {}) if isinstance(dashboard.get("goal_gates"), dict) else {}
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard.get("protection_mode"), dict) else {}
    response_patterns = dashboard.get("response_patterns", {}) if isinstance(dashboard.get("response_patterns"), dict) else {}
    goal_race = dashboard.get("active_context", {}).get("goal_race") if isinstance(dashboard.get("active_context"), dict) else None
    insights = progress_trend_insights(dashboard)

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
        "insights": insights,
    }


def fueling_page_data() -> dict[str, Any]:
    payload = load_or_build_fueling_payload()
    races = payload.get("races", []) if isinstance(payload.get("races"), list) else []
    workouts = payload.get("workouts", []) if isinstance(payload.get("workouts"), list) else []
    upcoming_races = sorted(
        [item for item in races if parse_iso_date(item.get("date")) and parse_iso_date(item.get("date")) >= date.today()],
        key=lambda item: item.get("date") or "",
    )
    hard_workouts = sorted(
        [item for item in workouts if parse_iso_date(item.get("date")) and parse_iso_date(item.get("date")) >= date.today()],
        key=lambda item: item.get("date") or "",
    )
    return {
        "generated_at": payload.get("generated_at"),
        "athlete": payload.get("athlete", {}),
        "supplements": payload.get("supplements", []),
        "upcoming_races": upcoming_races,
        "hard_workouts": hard_workouts,
        "all": payload,
    }


def decision_center_page_data() -> dict[str, Any]:
    dashboard = dashboard_payload()
    today_plan = today_plan_data()
    decision = dashboard.get("decision", {}) if isinstance(dashboard.get("decision"), dict) else {}
    guidance = decision.get("session_guidance", {}) if isinstance(decision.get("session_guidance"), dict) else {}
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard.get("protection_mode"), dict) else {}
    triggers = dashboard.get("adaptation_triggers", {}).get("triggers", []) if isinstance(dashboard.get("adaptation_triggers"), dict) else []
    active_trigger_items = [item for item in triggers if isinstance(item, dict) and item.get("active")]
    upcoming = [
        item for item in planned_workouts()
        if parse_iso_date(item.get("date")) and parse_iso_date(item.get("date")) >= date.today()
    ]
    upcoming.sort(key=lambda item: (item.get("date") or "", item.get("name") or ""))
    next_workout = next((item for item in upcoming if item.get("slug")), None)
    status = str(decision.get("status") or "unknown").lower()

    impact_reasons: list[dict[str, Any]] = []
    for index, reason in enumerate(decision.get("reasons", []) if isinstance(decision.get("reasons"), list) else [], start=1):
        impact_reasons.append({"rank": index, "label": str(reason), "tone": "warn" if index == 1 else ""})
    for item in active_trigger_items[:3]:
        impact_reasons.append({"rank": len(impact_reasons) + 1, "label": str(item.get("summary") or item.get("label") or ""), "tone": "warn"})

    changes_this_week: list[str] = []
    if status == "red":
        changes_this_week.append("Quitar o sustituir la siguiente sesion de calidad por trabajo facil o recuperacion.")
        changes_this_week.append("No aumentar volumen ni intensidad hasta que el contexto deje de estar en rojo.")
    elif status == "yellow":
        changes_this_week.append("Mantener la estructura, pero sin microprogresion ni carga extra.")
        changes_this_week.append("Compactar cualquier sesion exigente si el dia no llega limpio.")
    elif status == "green":
        changes_this_week.append("Mantener la semana actual y progresar solo de forma pequena y controlada.")
    if protection_mode.get("active") and protection_mode.get("guidance_note"):
        changes_this_week.append(str(protection_mode.get("guidance_note")))
    if today_plan.get("daily_checkin", {}).get("decision"):
        changes_this_week.append(f"Check-in de hoy: {today_plan['daily_checkin']['decision'].get('headline')}")
    changes_this_week = list(dict.fromkeys([item for item in changes_this_week if item]))[:5]

    prioritize_kinds = {"easy", "recovery", "elliptical", "strength", "mobility"}
    avoid_kinds = set()
    if status == "green":
        prioritize_kinds = {"quality", "long_run", "easy"}
    elif status == "yellow":
        prioritize_kinds = {"easy", "recovery", "elliptical", "strength", "mobility", "long_run"}
        avoid_kinds = {"quality"}
    else:
        avoid_kinds = {"quality", "long_run"}

    prioritized_sessions = [item for item in upcoming if item.get("session_kind") in prioritize_kinds][:4]
    avoided_sessions = [item for item in upcoming if item.get("session_kind") in avoid_kinds][:4]
    if not prioritized_sessions and next_workout:
        prioritized_sessions = [next_workout]

    direct_actions: list[dict[str, Any]] = [
        {"type": "link", "label": "Abrir plan de hoy", "url": today_plan.get("links", {}).get("day_url") or "/", "tone": ""},
        {"type": "link", "label": "Abrir semana operativa", "url": "/planned-workouts?view=week", "tone": ""},
        {"type": "link", "label": "Ver dashboard completo", "url": "/dashboard", "tone": ""},
    ]
    if next_workout:
        direct_actions.append(
            {"type": "link", "label": f"Abrir {next_workout.get('name')}", "url": f"/planned-workouts/{next_workout.get('slug')}", "tone": ""}
        )
        if status in {"red", "yellow"}:
            direct_actions.append(
                {
                    "type": "form",
                    "label": "Suavizar proxima sesion",
                    "url": f"/planned-workouts/{next_workout.get('slug')}/replan",
                    "strategy": "reduce_keep_goal",
                    "next_url": "/decision",
                    "tone": "warn",
                }
            )
        if status == "red":
            direct_actions.append(
                {
                    "type": "form",
                    "label": "Mover proxima sesion",
                    "url": f"/planned-workouts/{next_workout.get('slug')}/replan",
                    "strategy": "move_next_day",
                    "next_url": "/decision",
                    "tone": "warn",
                }
            )

    return {
        "dashboard": dashboard,
        "today_plan": today_plan,
        "current_decision": {
            "status": status,
            "status_label": decision.get("status_label") or "Sin decision",
            "action_label": decision.get("action_label") or "Sin accion definida",
            "recommendation": decision.get("recommendation") or "Sin recomendacion disponible.",
        },
        "impact_reasons": impact_reasons,
        "changes_this_week": changes_this_week,
        "prioritized_sessions": prioritized_sessions,
        "avoided_sessions": avoided_sessions,
        "direct_actions": direct_actions,
        "guidance": guidance,
    }


def planned_workouts(dashboard: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    workouts: list[dict[str, Any]] = []
    actions = planned_workout_actions()
    replans = planned_workout_replans()
    retry_states = garmin_retry_states()
    dashboard = dashboard or dashboard_payload()
    review_items = completed_reviews()
    for path in sorted(PLANNED_WORKOUTS_DIR.glob("*.yaml")):
        if path.name == "library_run_templates.yaml" or path.name == "workout_template.yaml":
            continue
        payload = load_yaml(path).get("workout", {})
        replan_state = replans.get(path.stem) if isinstance(replans.get(path.stem), dict) else None
        effective_payload = apply_replan_to_payload(payload, replan_state)
        source_schedule_date = str(payload.get("schedule_date") or "")
        schedule_date = str(effective_payload.get("schedule_date") or payload.get("schedule_date") or "")
        upload = planned_upload_data(path.stem, source_schedule_date) if source_schedule_date else {}
        uploaded_response = upload.get("uploaded_response", {})
        scheduled_response = upload.get("scheduled_response", {})
        workout_id = uploaded_response.get("workoutId") or scheduled_response.get("workout", {}).get("workoutId")
        scheduled_id = scheduled_response.get("workoutScheduleId")
        kind, kind_label, color_class = classify_planned_workout(effective_payload)
        action_state = actions.get(path.stem) if isinstance(actions.get(path.stem), dict) else None
        retry_state = retry_states.get(path.stem) if isinstance(retry_states.get(path.stem), dict) else None
        workout_url = garmin_scheduled_workout_url(scheduled_id) or garmin_workout_url(workout_id, effective_payload.get("sport"))
        linked_review = find_review_for_planned_workout({"slug": path.stem, "date": schedule_date}, review_items)
        knowledge = workout_knowledge_summary(effective_payload, kind)
        replan = planned_workout_replan_data(
            {
                "slug": path.stem,
                "date": schedule_date,
                "session_kind": kind,
                "action_state": action_state,
                "replan_state": replan_state,
                "knowledge": knowledge,
            },
            dashboard,
            linked_review,
        )
        workouts.append(
            {
                "slug": path.stem,
                "name": effective_payload.get("name") or path.stem,
                "date": schedule_date,
                "sport": effective_payload.get("sport") or "-",
                "description": effective_payload.get("description") or "",
                "estimated_duration": format_duration(effective_payload.get("estimated_duration_s")),
                "step_count": len(effective_payload.get("steps") or []),
                "garmin_workout_id": workout_id,
                "garmin_workout_url": workout_url,
                "garmin_scheduled_id": scheduled_id,
                "garmin_upload": upload,
                "garmin_retry_state": retry_state,
                "garmin_status_badge": garmin_status_badge(upload, retry_state, workout_url),
                "session_kind": kind,
                "session_kind_label": kind_label,
                "session_color_class": color_class,
                "knowledge": knowledge,
                "action_state": action_state,
                "action_badge": action_display_data((action_state or {}).get("action")),
                "replan": replan,
                "replan_state": replan_state,
                "linked_review": linked_review,
                "is_completed": bool(linked_review),
                "original_payload": payload,
                "payload": effective_payload,
            }
        )
    workouts.sort(key=lambda item: (item["date"], item["name"]))
    return workouts


def planned_workout_detail(slug: str) -> dict[str, Any] | None:
    for item in planned_workouts():
        if item["slug"] == slug:
            fueling = workout_fueling_lookup(load_or_build_fueling_payload(), slug)
            item["fueling"] = fueling
            item["targets"] = workout_targets_summary(item.get("payload") or {})
            knowledge = item.get("knowledge") if isinstance(item.get("knowledge"), dict) else None
            item["purpose_summary"] = (knowledge or {}).get("summary") if knowledge else None
            return item
    return None


def completed_reviews() -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    feedback_items = completed_feedback_items()
    for path in sorted(COMPLETED_REVIEW_DIR.glob("*.analysis.json")):
        payload = load_json(path)
        existing_recovery = payload.get("recovery_analysis") if isinstance(payload, dict) else None
        if not isinstance(existing_recovery, dict) or existing_recovery.get("status") in {None, "pending_data", "missing_data"}:
            computed_recovery = build_recovery_analysis(payload if isinstance(payload, dict) else {})
            if isinstance(payload, dict) and computed_recovery != existing_recovery:
                payload["recovery_analysis"] = computed_recovery
                write_json(path, payload)
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
                "planned_session_reference": planned.get("planned_session_reference"),
                "sport": planned.get("sport") or "-",
                "session_kind": kind,
                "session_kind_label": kind_label,
                "session_color_class": color_class,
                "compliance_note": payload.get("progression", {}).get("summary") or payload.get("analysis") or "Sin comentario disponible.",
                "automated_review_summary": automated_review_summary(payload),
                "athlete_feedback": feedback,
                "feedback_badge": feedback_badge(feedback),
                "feedback_summary": feedback_summary(feedback),
                "feedback_form": feedback_form_state(feedback),
                "feedback_locked": bool(feedback),
                "recovery_analysis": payload.get("recovery_analysis") if isinstance(payload.get("recovery_analysis"), dict) else None,
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


def garmin_activity_import_dir(activity_id: Any) -> Path | None:
    if activity_id in {None, ""}:
        return None
    activity_text = str(activity_id).strip()
    if not activity_text:
        return None
    matches = sorted(GARMIN_ACTIVITY_DIR.glob(f"*_{activity_text}"))
    return matches[0] if matches else None


def garmin_activity_summary_payload(activity_id: Any) -> dict[str, Any]:
    activity_dir = garmin_activity_import_dir(activity_id)
    if not activity_dir:
        return {}
    summary_path = activity_dir / "summary.json"
    return load_optional_json(summary_path, {}) if summary_path.exists() else {}


def garmin_feedback_metrics(activity_id: Any) -> list[dict[str, str]]:
    summary = garmin_activity_summary_payload(activity_id)
    if not isinstance(summary, dict) or not summary:
        return []

    def add_metric(items: list[dict[str, str]], label: str, value: Any) -> None:
        text = str(value).strip() if value not in {None, ""} else ""
        if text:
            items.append({"label": label, "value": text})

    metrics: list[dict[str, str]] = []
    event_type = ((summary.get("eventType") or {}).get("typeKey") if isinstance(summary.get("eventType"), dict) else None) or ""
    add_metric(metrics, "Tipo", str(event_type).replace("_", " ").title() if event_type else "")
    add_metric(metrics, "Lugar", summary.get("locationName"))
    if summary.get("calories") is not None:
        add_metric(metrics, "Calorías", f"{int(round(float(summary.get('calories') or 0.0)))} kcal")
    if summary.get("steps") is not None:
        add_metric(metrics, "Pasos", f"{int(summary.get('steps') or 0)}")
    if summary.get("activityTrainingLoad") is not None:
        add_metric(metrics, "Training load", f"{float(summary.get('activityTrainingLoad') or 0.0):.1f}")
    if summary.get("trainingEffectLabel"):
        add_metric(metrics, "Training effect", summary.get("trainingEffectLabel"))
    if summary.get("aerobicTrainingEffect") is not None:
        add_metric(metrics, "TE aeróbico", f"{float(summary.get('aerobicTrainingEffect') or 0.0):.1f}")
    if summary.get("anaerobicTrainingEffect") is not None:
        add_metric(metrics, "TE anaeróbico", f"{float(summary.get('anaerobicTrainingEffect') or 0.0):.1f}")
    if summary.get("avgPower") is not None:
        add_metric(metrics, "Potencia media", f"{int(round(float(summary.get('avgPower') or 0.0)))} W")
    if summary.get("normPower") is not None:
        add_metric(metrics, "Potencia normalizada", f"{int(round(float(summary.get('normPower') or 0.0)))} W")
    if summary.get("maxPower") is not None:
        add_metric(metrics, "Potencia máxima", f"{int(round(float(summary.get('maxPower') or 0.0)))} W")
    if summary.get("averageRunningCadenceInStepsPerMinute") is not None:
        add_metric(metrics, "Cadencia media", f"{float(summary.get('averageRunningCadenceInStepsPerMinute') or 0.0):.1f} spm")
    if summary.get("maxRunningCadenceInStepsPerMinute") is not None:
        add_metric(metrics, "Cadencia máxima", f"{int(round(float(summary.get('maxRunningCadenceInStepsPerMinute') or 0.0)))} spm")
    if summary.get("waterEstimated") is not None:
        add_metric(metrics, "Agua estimada", f"{int(round(float(summary.get('waterEstimated') or 0.0)))} ml")
    if summary.get("differenceBodyBattery") is not None:
        add_metric(metrics, "Body Battery", f"{int(round(float(summary.get('differenceBodyBattery') or 0.0)))}")
    min_temp = summary.get("minTemperature")
    max_temp = summary.get("maxTemperature")
    if min_temp is not None or max_temp is not None:
        if min_temp is not None and max_temp is not None:
            add_metric(metrics, "Temperatura", f"{float(min_temp):.0f}-{float(max_temp):.0f} C")
        elif min_temp is not None:
            add_metric(metrics, "Temperatura", f"{float(min_temp):.0f} C")
        else:
            add_metric(metrics, "Temperatura", f"{float(max_temp):.0f} C")
    if summary.get("lapCount") is not None:
        add_metric(metrics, "Vueltas", f"{int(summary.get('lapCount') or 0)}")
    if summary.get("vigorousIntensityMinutes") is not None:
        add_metric(metrics, "Min intensos", f"{int(round(float(summary.get('vigorousIntensityMinutes') or 0.0)))}")
    return metrics


def risk_tone_from_score(score: float | int | None) -> str:
    if score is None:
        return ""
    value = float(score)
    if value >= 4.0:
        return "warn"
    if value >= 2.0:
        return ""
    return "ok"


def pain_risk_page_data() -> dict[str, Any]:
    dashboard = dashboard_payload()
    shin_tracker = load_optional_yaml(ROOT / "athlete" / "shin_tracker.yaml").get("shin_tracker", {})
    shin_entries = shin_tracker.get("entries", []) if isinstance(shin_tracker.get("entries"), list) else []
    feedback_items = completed_feedback_items()
    timeline: list[dict[str, Any]] = []

    for entry in shin_entries:
        if not isinstance(entry, dict):
            continue
        pain_values = [entry.get("pain_during"), entry.get("pain_after"), entry.get("pain_next_morning")]
        numeric = [float(value) for value in pain_values if value is not None]
        max_pain = max(numeric) if numeric else None
        timeline.append(
            {
                "date": iso_date_string(entry.get("date")),
                "source": "shin_tracker",
                "label": "Tracker de periostio",
                "summary": str(entry.get("notes") or "Sin nota adicional."),
                "score": max_pain,
                "tone": risk_tone_from_score(max_pain),
                "meta": [
                    f"Durante {entry.get('pain_during', '-')}",
                    f"Despues {entry.get('pain_after', '-')}",
                    f"Mañana {entry.get('pain_next_morning', '-')}",
                    f"Superficie {entry.get('surface') or '-'}",
                    f"Zapatillas {entry.get('shoes') or '-'}",
                ],
            }
        )

    for slug, payload in feedback_items.items():
        if not isinstance(payload, dict):
            continue
        athlete_feedback = payload.get("athlete_feedback", {}) if isinstance(payload.get("athlete_feedback"), dict) else {}
        pain_level = athlete_feedback.get("pain_level")
        if pain_level is None:
            continue
        review = completed_review_detail(slug)
        timeline.append(
            {
                "date": iso_date_string(payload.get("date")),
                "source": "feedback",
                "label": "Feedback post-sesion",
                "summary": feedback_summary(payload) or "Feedback subjetivo registrado.",
                "score": float(pain_level),
                "tone": risk_tone_from_score(pain_level),
                "meta": [
                    f"Sesion {review.get('session_kind_label') if review else '-'}",
                    f"Localizacion {athlete_feedback.get('pain_location') or '-'}",
                    f"Cumplimiento {FEEDBACK_COMPLIANCE_LABELS.get(str(athlete_feedback.get('compliance') or ''), athlete_feedback.get('compliance') or '-')}",
                ],
            }
        )

    timeline.sort(key=lambda item: (item.get("date") or "", item.get("source") or ""), reverse=True)

    recent_scores = [float(item["score"]) for item in timeline[:3] if item.get("score") is not None]
    alerts: list[dict[str, Any]] = []
    if recent_scores:
        latest = recent_scores[0]
        if latest >= 4.0:
            alerts.append({"label": "Dolor actual alto", "summary": f"La ultima señal de dolor es {latest:.0f}/10 y activa protección clara.", "tone": "warn"})
        elif latest >= 3.0:
            alerts.append({"label": "Dolor a vigilar", "summary": f"La ultima señal de dolor es {latest:.0f}/10; no conviene progresar carga.", "tone": "warn"})
        if len(recent_scores) >= 2 and recent_scores[0] >= recent_scores[1] and recent_scores[0] >= 3.0:
            alerts.append({"label": "Tendencia no resuelta", "summary": "Las ultimas señales no muestran mejora clara del dolor.", "tone": "warn"})
        if len(recent_scores) >= 3 and sum(recent_scores) / len(recent_scores) >= 3.0:
            alerts.append({"label": "Promedio reciente elevado", "summary": "La media reciente de molestias sigue por encima de la zona segura.", "tone": "warn"})
    if not alerts:
        alerts.append({"label": "Sin alerta fuerte", "summary": "No hay una tendencia reciente que obligue a escalar la protección por sí sola.", "tone": "ok"})

    feedback_with_review: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for slug, payload in feedback_items.items():
        if isinstance(payload, dict):
            feedback_with_review.append((payload, completed_review_detail(slug)))

    session_corr: dict[str, list[float]] = {}
    for payload, review in feedback_with_review:
        athlete_feedback = payload.get("athlete_feedback", {}) if isinstance(payload.get("athlete_feedback"), dict) else {}
        pain_level = athlete_feedback.get("pain_level")
        if pain_level is None or not review:
            continue
        key = review.get("session_kind_label") or "Otra sesión"
        session_corr.setdefault(str(key), []).append(float(pain_level))

    surface_corr: dict[str, list[float]] = {}
    shoes_corr: dict[str, list[float]] = {}
    for entry in shin_entries:
        if not isinstance(entry, dict):
            continue
        pain_values = [entry.get("pain_during"), entry.get("pain_after"), entry.get("pain_next_morning")]
        numeric = [float(value) for value in pain_values if value is not None]
        if not numeric:
            continue
        avg_pain = sum(numeric) / len(numeric)
        if entry.get("surface"):
            surface_corr.setdefault(str(entry.get("surface")), []).append(avg_pain)
        if entry.get("shoes"):
            shoes_corr.setdefault(str(entry.get("shoes")), []).append(avg_pain)

    def correlation_rows(source: dict[str, list[float]], empty_label: str) -> list[dict[str, Any]]:
        rows = [
            {"label": label, "count": len(values), "avg_score": round(sum(values) / len(values), 1), "tone": risk_tone_from_score(sum(values) / len(values))}
            for label, values in source.items() if values
        ]
        rows.sort(key=lambda item: (item["avg_score"], item["count"]), reverse=True)
        if rows:
            return rows
        return [{"label": empty_label, "count": 0, "avg_score": None, "tone": ""}]

    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard.get("protection_mode"), dict) else {}
    rules = [
        {
            "label": protection_mode.get("label") or "Protección actual",
            "summary": protection_mode.get("allowed_progression") or "Sin regla automática activa.",
            "tone": protection_mode.get("tone") or "",
        },
        {
            "label": "Regla de dolor 3/10",
            "summary": "Con 3/10 o reacción suave al día siguiente no se debe aumentar carga.",
            "tone": "warn",
        },
        {
            "label": "Regla de dolor 4/10",
            "summary": "Con 4/10 o más se debe reducir impacto, quitar calidad o descansar.",
            "tone": "warn",
        },
    ]

    return {
        "dashboard": dashboard,
        "timeline": timeline,
        "alerts": alerts,
        "session_correlations": correlation_rows(session_corr, "Aun no hay feedback enlazado por tipo de sesión."),
        "surface_correlations": correlation_rows(surface_corr, "Aun no hay suficientes superficies registradas."),
        "shoes_correlations": correlation_rows(shoes_corr, "Aun no hay suficientes zapatillas registradas en el tracker."),
        "rules": rules,
    }


def athlete_page_data() -> dict[str, Any]:
    profile_capability = ensure_fresh("athlete_profile")
    athlete_state_capability = ensure_fresh("athlete_state")
    profile = load_optional_yaml(ROOT / "athlete" / "profile.yaml").get("athlete", {})
    health = load_optional_yaml(ROOT / "athlete" / "health.yaml").get("health", {})
    injury = load_optional_yaml(ROOT / "athlete" / "shin_tracker.yaml").get("shin_tracker", {})
    shoes = load_optional_yaml(ROOT / "athlete" / "shoes.yaml").get("shoes", [])
    athlete_state = load_optional_json(ATHLETE_STATE_PATH, {})
    entries = list(reversed(injury.get("entries") or []))
    capability_messages = [message for message in [profile_capability.warning, athlete_state_capability.warning] if message]
    return {
        "profile": profile,
        "health": health,
        "injury": injury,
        "entries": entries,
        "risk": pain_risk_page_data(),
        "shoes": shoes if isinstance(shoes, list) else [],
        "capability_messages": capability_messages,
        "impact_return": athlete_state.get("athlete", {}).get("impact_return", {}),
        "hybrid_training": athlete_state.get("athlete", {}).get("hybrid_training", {}),
        "training_paces": athlete_state.get("athlete", {}).get("training_paces", {}),
        "coach_permissions": athlete_state.get("coach", {}).get("permissions", {}),
        "replanning": athlete_state.get("coach", {}).get("replanning", {}),
    }


def races_page_data() -> list[dict[str, Any]]:
    review_items = completed_reviews()
    races: list[dict[str, Any]] = []
    for path in sorted(RACES_DIR.glob("**/*.yaml")):
        raw_payload = load_yaml(path)
        payload = raw_payload.get("race", raw_payload) if isinstance(raw_payload, dict) else {}
        if not isinstance(payload, dict):
            continue
        goal = payload.get("goal") or {}
        goal_value = goal.get("value") if isinstance(goal, dict) else goal
        race_date = iso_date_string(payload.get("date"))
        race_reference = str(path.relative_to(ROOT)).replace("\\", "/")
        linked_review = next((item for item in review_items if item.get("planned_session_reference") == race_reference), None)
        races.append(
            {
                "id": payload.get("id") or path.stem,
                "name": payload.get("name") or path.stem,
                "date": race_date,
                "priority_code": str(payload.get("priority") or "").upper(),
                "priority": priority_label(payload.get("priority")),
                "distance_km": payload.get("distance_km") or payload.get("distance") or "-",
                "elevation_gain_m": payload.get("elevation_gain_m") or "-",
                "location": payload.get("location") or "-",
                "goal": goal_value or "-",
                "goal_type": goal.get("type") if isinstance(goal, dict) else None,
                "goal_target_pace": goal.get("target_pace") if isinstance(goal, dict) else None,
                "notes": payload.get("notes") or "",
                "coaching_note": payload.get("coaching_note") or "",
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


def parse_race_distance_km(value: Any) -> float | None:
    text = str(value or "").strip().lower().replace(",", ".")
    if not text or text == "-":
        return None
    text = text.replace("km", "").replace("k", "")
    try:
        return float(text)
    except ValueError:
        return None


def riegel_prediction(source_time_s: float | None, source_distance_km: float, target_distance_km: float | None) -> float | None:
    if source_time_s is None or source_time_s <= 0 or not target_distance_km or target_distance_km <= 0:
        return None
    return float(source_time_s) * (float(target_distance_km) / float(source_distance_km)) ** 1.06


def countdown_label(days_to_race: int) -> str:
    if days_to_race < 0:
        return "Carrera pasada"
    if days_to_race == 0:
        return "Hoy"
    if days_to_race == 1:
        return "Mañana"
    return f"D-{days_to_race}"


def taper_monitor_payload(days_to_race: int | None, dashboard: dict[str, Any]) -> dict[str, Any]:
    decision = dashboard.get("decision", {}) if isinstance(dashboard.get("decision"), dict) else {}
    protection_mode = dashboard.get("protection_mode", {}) if isinstance(dashboard.get("protection_mode"), dict) else {}
    if days_to_race is None or days_to_race < 0:
        return {"label": "Cerrada", "tone": "", "summary": "La carrera ya ha pasado o no tiene fecha operativa."}
    if days_to_race > 21:
        return {"label": "Fuera de taper", "tone": "", "summary": "Todavía no toca afinar; la prioridad sigue siendo construir o consolidar."}
    if protection_mode.get("active"):
        return {"label": "Taper en riesgo", "tone": "warn", "summary": protection_mode.get("summary") or "El contexto actual no permite afinar de forma limpia."}
    if str(decision.get("status") or "") == "red":
        return {"label": "Taper tensionado", "tone": "warn", "summary": "La decisión actual obliga a proteger frescura y bajar coste antes de la carrera."}
    if str(decision.get("status") or "") == "yellow" or days_to_race <= 14:
        return {"label": "Taper vigilado", "tone": "warn", "summary": "Ya conviene evitar añadir carga que no aporte ejecución el día de carrera."}
    return {"label": "Taper alineado", "tone": "ok", "summary": "La preparación llega razonablemente ordenada para seguir afinando."}


def race_strategy_payload(race: dict[str, Any], predicted_time_s: float | None) -> dict[str, Any]:
    target_pace = str(race.get("goal_target_pace") or "").strip()
    goal_value = str(race.get("goal") or "").strip()
    distance_km = parse_race_distance_km(race.get("distance_km"))
    predicted_pace = (predicted_time_s / distance_km) if predicted_time_s and distance_km else None
    anchor = target_pace or (format_pace(predicted_pace) if predicted_pace else "por sensaciones controladas")
    return {
        "anchor": anchor,
        "opening": f"Salida controlada durante el primer 15-20% para no regalar pulso ni piernas antes de tiempo.",
        "middle": f"Bloque central estable alrededor de {anchor}.",
        "closing": "Último tramo progresivo solo si el coste sigue bajo control y no se rompe la técnica.",
        "note": goal_value if goal_value and goal_value != "-" else "Usar la forma actual como techo realista, no el objetivo aspiracional si aún no está desbloqueado.",
    }


def race_checklist_payload(race_date: date | None) -> list[dict[str, str]]:
    if not race_date:
        return []
    return [
        {"when": (race_date - timedelta(days=7)).isoformat(), "label": "Revisar semana de carrera", "detail": "Cerrar la carga útil y evitar meter fatiga nueva."},
        {"when": (race_date - timedelta(days=2)).isoformat(), "label": "Confirmar material", "detail": "Zapatillas, dorsal, previsión del recorrido y logística."},
        {"when": (race_date - timedelta(days=1)).isoformat(), "label": "Activación ligera", "detail": "Mover piernas sin fatigar y dejar claro el plan de ritmo."},
        {"when": race_date.isoformat(), "label": "Ejecución", "detail": "Calentar con margen y correr según estrategia, no por impulsos."},
    ]


def races_operational_page_data() -> dict[str, Any]:
    dashboard = dashboard_payload()
    fueling_payload = load_or_build_fueling_payload()
    today = date.today()
    races = races_page_data()
    estimate_10k_s = dashboard.get("performance_estimate", {}).get("current_10k_estimate_s") if isinstance(dashboard.get("performance_estimate"), dict) else None
    comparison = progress_trend_insights(dashboard).get("comparison_4w", {})
    enriched: list[dict[str, Any]] = []
    for race in races:
        race_date = parse_iso_date(race.get("date"))
        days_to_race = (race_date - today).days if race_date else None
        distance_km = parse_race_distance_km(race.get("distance_km"))
        predicted_time_s = riegel_prediction(float(estimate_10k_s) if estimate_10k_s is not None else None, 10.0, distance_km)
        enriched.append(
            {
                **race,
                "days_to_race": days_to_race,
                "countdown": countdown_label(days_to_race) if days_to_race is not None else "Sin fecha",
                "is_upcoming": bool(days_to_race is not None and days_to_race >= 0),
                "predicted_time": format_duration(predicted_time_s) if predicted_time_s else "Sin predicción",
                "predicted_pace": format_pace((predicted_time_s / distance_km) if predicted_time_s and distance_km else None),
                "strategy": race_strategy_payload(race, predicted_time_s),
                "taper": taper_monitor_payload(days_to_race, dashboard),
                "checklist": race_checklist_payload(race_date),
                "fueling": race_fueling_lookup(fueling_payload, str(race.get("id") or "")),
            }
        )
    upcoming = [item for item in enriched if item.get("is_upcoming")]
    completed = [item for item in enriched if not item.get("is_upcoming")]
    upcoming.sort(key=lambda item: item.get("date") or "")
    completed.sort(key=lambda item: item.get("date") or "", reverse=True)
    next_race = upcoming[0] if upcoming else None
    return {
        "dashboard": dashboard,
        "comparison_4w": comparison,
        "next_race": next_race,
        "upcoming": upcoming,
        "completed": completed,
        "all": enriched,
    }


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
    matched_review_slugs: set[str] = set()

    for review in completed_items:
        payload = review.get("payload", {}) if isinstance(review.get("payload"), dict) else {}
        embedded_planned = payload.get("planned", {}) if isinstance(payload.get("planned"), dict) else {}
        compliance = payload.get("compliance", {}) if isinstance(payload.get("compliance"), dict) else {}
        slug = review.get("slug")
        planned_item = next((item for item in planned_items if review_matches_planned_workout(review, item)), None)
        if planned_item and slug:
            matched_review_slugs.add(str(slug))
        planned_slug = planned_item.get("slug") if isinstance(planned_item, dict) else None
        if planned_slug:
            matched_slugs.add(str(planned_slug))

        if not planned_item:
            continue

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
        if slug and str(slug) in matched_review_slugs:
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
    review_items = [item for item in completed_reviews() if item.get("date") == day]
    reviewed_activity_ids = {
        int(item.get("garmin_activity_id"))
        for item in review_items
        if item.get("garmin_activity_id") not in {None, ""}
    }
    completed_items = review_items + imported_garmin_activities(day, reviewed_activity_ids)
    race_items = races_by_day().get(day, [])
    reviews = review_items
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


def current_week_stats() -> dict[str, Any]:
    today_val = date.today()
    week_start = today_val - timedelta(days=today_val.weekday())
    week_end = week_start + timedelta(days=6)
    workouts = planned_workouts()
    reviews = completed_reviews()
    this_week_workouts = [w for w in workouts if parse_iso_date(w.get("date")) and week_start <= parse_iso_date(w.get("date")) <= week_end]
    this_week_km = round(sum(workout_distance_km(w) for w in this_week_workouts), 1)
    this_week_sessions = len(this_week_workouts)
    week_planned_slugs = {w.get("slug") for w in this_week_workouts if w.get("slug")}
    this_week_reviews = [r for r in reviews if parse_iso_date(r.get("date")) and week_start <= parse_iso_date(r.get("date")) <= week_end]
    this_week_completed = sum(1 for r in this_week_reviews if r.get("slug") in week_planned_slugs)
    this_week_actual_km = round(sum(float(r.get("distance_km") or 0.0) for r in this_week_reviews), 1)
    next_race = next(
        (r for r in races_page_data() if parse_iso_date(r.get("date")) and parse_iso_date(r.get("date")) >= today_val),
        None,
    )
    next_race_days: int | None = (parse_iso_date(next_race["date"]) - today_val).days if next_race else None
    next_race_name: str | None = next_race.get("name") if next_race else None
    return {
        "current_week_km": this_week_km,
        "current_week_sessions": this_week_sessions,
        "current_week_completed": this_week_completed,
        "current_week_actual_km": this_week_actual_km,
        "next_race_days": next_race_days,
        "next_race_name": next_race_name,
    }


def home_page_data() -> dict[str, Any]:
    status = workspace_status()
    dashboard = dashboard_payload()
    active_cycle = active_cycle_data()
    workouts = planned_workouts(dashboard)
    reviews = completed_reviews()
    week = week_page_data(dashboard=dashboard, workouts=workouts, reviews=reviews)
    upcoming = [item for item in workouts if parse_iso_date(item["date"]) and parse_iso_date(item["date"]) >= date.today()]
    recent_reviews = reviews[:5]
    week_stats = current_week_stats()
    return {
        "workspace": status,
        "dashboard": dashboard,
        "today_plan": today_plan_data(dashboard=dashboard, workouts=workouts, reviews=reviews),
        "active_cycle": active_cycle,
        "week": week,
        "upcoming": upcoming[:5] if upcoming else workouts[:5],
        "recent_reviews": recent_reviews,
        "planned_count": len(workouts),
        "review_count": len(reviews),
        "progress_metrics": progress_metrics(),
        **week_stats,
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
