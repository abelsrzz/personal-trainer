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
from starlette.middleware.sessions import SessionMiddleware


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "web" / "templates"
STATIC_DIR = ROOT / "web" / "static"
PLANNED_WORKOUTS_DIR = ROOT / "training" / "planned" / "workouts"
COMPLETED_REVIEW_DIR = ROOT / "training" / "completed" / "reviews"
GARMIN_ACTIVITY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
GARMIN_DAILY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "daily"
RACES_DIR = ROOT / "races"
WEB_CONFIG_PATH = ROOT / "web" / "web_config.yaml"
WEB_LOG_PATH = ROOT / "web" / "web_debug.log"


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


app = FastAPI(title="Running Coach Portal")
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


def garmin_activity_url(activity_id: int | str | None) -> str | None:
    if not activity_id:
        return None
    activity_id = str(activity_id).strip()
    if not activity_id.isdigit():
        return None
    return f"https://connect.garmin.com/modern/activity/{activity_id}"


def garmin_workout_url(workout_id: int | str | None) -> str | None:
    if not workout_id:
        return None
    workout_id = str(workout_id).strip()
    if not workout_id.isdigit():
        return None
    return f"https://connect.garmin.com/modern/workout/{workout_id}"


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
        "reduce_or_replace_quality": "Reducir exigencia y priorizar recuperacion",
    }.get(str(value or "").lower(), "Sin acción definida")


def goal_status_label(value: str | None) -> str:
    return {
        "unsupported_now": "Aún es pronto para orientar el entrenamiento a ese objetivo",
        "development_needed": "La base mejora, pero todavía falta desarrollo",
        "aggressive_alive": "El objetivo sigue vivo si la progresion se consolida",
        "35_ready": "El objetivo ya puede influir en la estrategia",
    }.get(str(value or "").lower(), "Sin evaluacion disponible")


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


def classify_session_kind(text: str, distance_km: float | None = None) -> str:
    race_markers = {"competicion", "race day", "tune-up", "pre-carrera", "shakeout pre-carrera"}
    if any(keyword in text for keyword in {"descanso", "rest"}):
        return "rest"
    if any(keyword in text for keyword in {"recuperacion", "recovery", "reintroduccion"}):
        return "recovery"
    if any(keyword in text for keyword in {"fuerza", "strength", "gymnasio", "gimnasio"}):
        return "strength"
    if any(keyword in text for keyword in {"activacion", "rectas", "ritmo", "series", "interval", "tempo", "umbral", "especifica", "cuestas"}):
        return "quality"
    if any(keyword in text for keyword in {"tirada", "long run", "larga"}):
        return "long_run"
    if distance_km and distance_km >= 14:
        return "long_run"
    if any(keyword in text for keyword in race_markers):
        return "race"
    if any(keyword in text for keyword in {"rodaje", "facil", "suave", "easy"}):
        return "easy"
    return "other"


def session_kind_label(value: str) -> str:
    return {
        "easy": "Rodaje suave",
        "recovery": "Recuperacion",
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
    text = normalize_text(payload.get("name"), payload.get("description"), json.dumps(steps, ensure_ascii=True))
    kind = classify_session_kind(text, float(distance_m) / 1000.0 if distance_m else None)
    return kind, session_kind_label(kind), session_color_class(kind)


def classify_completed_review(payload: dict[str, Any]) -> tuple[str, str, str]:
    planned = payload.get("planned", {})
    summary = payload.get("summary", {})
    text = normalize_text(
        planned.get("goal_category"),
        planned.get("name"),
        planned.get("description"),
        summary.get("activity_name"),
    )
    distance_km = round(float(summary.get("distance_m") or 0.0) / 1000.0, 2) if summary.get("distance_m") else None
    kind = classify_session_kind(text, distance_km)
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
        "matched_completed": "Plan y ejecucion",
        "reviewed": "Revisado",
        "race_day": "Carrera",
        "rest_day": "Descanso",
    }.get(value, "Sin estado")


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
    path = ROOT / "planning" / "weeks" / "semana_actual.md"
    content = read_text(path)
    return {
        "content": content,
        "rows": parse_week_table(content),
        "pdf_exists": (ROOT / "planning" / "weeks" / "generated" / "semana_actual.pdf").exists(),
    }


def planned_upload_data(workout_stem: str, schedule_date: str) -> dict[str, Any]:
    upload_path = PLANNED_WORKOUTS_DIR / schedule_date / f"{workout_stem}.garmin_upload.json"
    return load_json(upload_path) if upload_path.exists() else {}


def dashboard_payload() -> dict[str, Any]:
    path = ROOT / "planning" / "coach_decision.json"
    payload = load_json(path) if path.exists() else {}
    if payload.get("decision"):
        payload["decision"]["status_label"] = decision_status_label(payload["decision"].get("status"))
        payload["decision"]["action_label"] = decision_action_label(payload["decision"].get("action"))
    if payload.get("goal_gates"):
        payload["goal_gates"]["status_label"] = goal_status_label(payload["goal_gates"].get("status"))
    return payload


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
                "garmin_workout_url": garmin_workout_url(workout_id),
                "garmin_scheduled_id": scheduled_response.get("workoutScheduleId"),
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
                "garmin_workout_url": garmin_workout_url(summary.get("workout_id") or summary.get("workoutId")),
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
    profile = load_yaml(ROOT / "athlete" / "profile.yaml").get("athlete", {})
    health = load_yaml(ROOT / "athlete" / "health.yaml").get("health", {})
    shin = load_yaml(ROOT / "athlete" / "shin_tracker.yaml").get("shin_tracker", {})
    entries = list(reversed(shin.get("entries") or []))
    return {
        "profile": profile,
        "health": health,
        "shin": shin,
        "entries": entries,
    }


def races_page_data() -> list[dict[str, Any]]:
    races: list[dict[str, Any]] = []
    for path in sorted(RACES_DIR.glob("**/*.yaml")):
        raw_payload = load_yaml(path)
        payload = raw_payload.get("race", raw_payload) if isinstance(raw_payload, dict) else {}
        if not isinstance(payload, dict):
            continue
        goal = payload.get("goal") or {}
        goal_value = goal.get("value") if isinstance(goal, dict) else goal
        races.append(
            {
                "name": payload.get("name") or path.stem,
                "date": iso_date_string(payload.get("date")),
                "priority": priority_label(payload.get("priority")),
                "distance_km": payload.get("distance_km") or payload.get("distance") or "-",
                "elevation_gain_m": payload.get("elevation_gain_m") or "-",
                "location": payload.get("location") or "-",
                "goal": goal_value or "-",
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
            }
        )
    return events


def calendar_month_data_combined(month: str | None) -> dict[str, Any]:
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
            }
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
                        "event": event_by_day.get(iso_day),
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
        }
    except Exception:
        logger.exception("calendar_month_data_combined failed month=%s", month)
        raise


def system_page_data() -> dict[str, Any]:
    coach_path = ROOT / "planning" / "coach_decision.json"
    activity_count = len(list(GARMIN_ACTIVITY_DIR.glob("*/summary.json")))
    daily_count = len(
        [path for path in GARMIN_DAILY_DIR.glob("*.json") if not path.name.startswith("last_import") and not path.name.startswith("running_tolerance")]
    )
    review_count = len(list(COMPLETED_REVIEW_DIR.glob("*.analysis.json")))
    planned_count = len([path for path in PLANNED_WORKOUTS_DIR.glob("*.yaml") if path.name not in {"library_run_templates.yaml", "workout_template.yaml"}])
    return {
        "coach_generated_at": format_datetime(load_json(coach_path).get("generated_at")) if coach_path.exists() else "-",
        "activity_count": activity_count,
        "daily_count": daily_count,
        "review_count": review_count,
        "planned_count": planned_count,
        "week_pdf_exists": (ROOT / "planning" / "weeks" / "generated" / "semana_actual.pdf").exists(),
    }


def home_page_data() -> dict[str, Any]:
    dashboard = dashboard_payload()
    week = week_page_data()
    workouts = planned_workouts()
    reviews = completed_reviews()
    upcoming = [item for item in workouts if parse_iso_date(item["date"]) and parse_iso_date(item["date"]) >= date.today()]
    recent_reviews = reviews[:5]
    return {
        "dashboard": dashboard,
        "week": week,
        "upcoming": upcoming[:5] if upcoming else workouts[:5],
        "recent_reviews": recent_reviews,
        "planned_count": len(workouts),
        "review_count": len(reviews),
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
    return templates.TemplateResponse(request, "week.html", template_context(request, week=week_page_data()))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "dashboard.html", template_context(request, dashboard=dashboard_payload()))


@app.get("/decision", response_class=HTMLResponse)
async def decision(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    dashboard = dashboard_payload()
    return templates.TemplateResponse(request, "decision.html", template_context(request, dashboard=dashboard, decision=dashboard.get("decision", {})))


@app.get("/planned-workouts", response_class=HTMLResponse)
async def planned_workouts_page(request: Request, view: str = "list", month: str | None = None) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    items = planned_workouts()
    current_view = view if view in {"list", "calendar"} else "list"
    calendar_data = calendar_month_data_combined(month) if current_view == "calendar" else {"selected": month or "", "selected_label": "", "weeks": [], "prev_month": "", "next_month": ""}
    return templates.TemplateResponse(
        request,
        "planned_workouts.html",
        template_context(request, workouts=items, current_view=current_view, calendar=calendar_data),
    )


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, month: str | None = None) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "planned_workouts.html", template_context(request, workouts=planned_workouts(), current_view="calendar", calendar=calendar_month_data_combined(month)))


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
    return templates.TemplateResponse(request, "athlete.html", template_context(request, athlete=athlete_page_data()))


@app.get("/races", response_class=HTMLResponse)
async def races(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "races.html", template_context(request, races=races_page_data()))


@app.get("/system", response_class=HTMLResponse)
async def system(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "system.html", template_context(request, system=system_page_data()))


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
