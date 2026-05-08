#!/usr/bin/env python3

from __future__ import annotations

import json
import calendar
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


def month_label(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError:
        return value
    return parsed.strftime("%B %Y").capitalize()


def garmin_activity_url(activity_id: int | str | None) -> str | None:
    if not activity_id:
        return None
    return f"https://connect.garmin.com/modern/activity/{activity_id}"


def garmin_workout_url(workout_id: int | str | None) -> str | None:
    if not workout_id:
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
        "maintain_or_progress_carefully": "Mantener la linea actual con una progresion pequena y controlada",
        "maintain_with_caution": "Mantener la estructura sin subir carga",
        "reduce_or_replace_quality": "Reducir exigencia y priorizar recuperacion",
    }.get(str(value or "").lower(), "Sin accion definida")


def goal_status_label(value: str | None) -> str:
    return {
        "unsupported_now": "Aun es pronto para orientar el entrenamiento a ese objetivo",
        "development_needed": "La base mejora, pero todavia falta desarrollo",
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
        if path.name == "library_10k_templates.yaml" or path.name == "workout_template.yaml":
            continue
        payload = load_yaml(path).get("workout", {})
        schedule_date = str(payload.get("schedule_date") or "")
        upload = planned_upload_data(path.stem, schedule_date) if schedule_date else {}
        uploaded_response = upload.get("uploaded_response", {})
        scheduled_response = upload.get("scheduled_response", {})
        workout_id = uploaded_response.get("workoutId") or scheduled_response.get("workout", {}).get("workoutId")
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
        payload = load_yaml(path).get("race", {})
        races.append(
            {
                "name": payload.get("name") or path.stem,
                "date": payload.get("date") or "",
                "priority": priority_label(payload.get("priority")),
                "distance_km": payload.get("distance_km") or "-",
                "elevation_gain_m": payload.get("elevation_gain_m") or "-",
                "location": payload.get("location") or "-",
                "goal": payload.get("goal") or "-",
            }
        )
    races.sort(key=lambda item: item["date"])
    return races


def system_page_data() -> dict[str, Any]:
    coach_path = ROOT / "planning" / "coach_decision.json"
    activity_count = len(list(GARMIN_ACTIVITY_DIR.glob("*/summary.json")))
    daily_count = len(
        [path for path in GARMIN_DAILY_DIR.glob("*.json") if not path.name.startswith("last_import") and not path.name.startswith("running_tolerance")]
    )
    review_count = len(list(COMPLETED_REVIEW_DIR.glob("*.analysis.json")))
    planned_count = len([path for path in PLANNED_WORKOUTS_DIR.glob("*.yaml") if path.name not in {"library_10k_templates.yaml", "workout_template.yaml"}])
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
                error="La web no esta configurada todavia. Define las credenciales de acceso y vuelve a intentarlo.",
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
    calendar_data = planned_calendar_data(month)
    return templates.TemplateResponse(
        request,
        "planned_workouts.html",
        template_context(request, workouts=items, current_view=view if view in {"list", "calendar"} else "list", calendar=calendar_data),
    )


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
