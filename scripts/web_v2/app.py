from __future__ import annotations

from datetime import timedelta
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from scripts.system.automation_hub import build_status as automation_jobs_status, load_state as load_automation_jobs_state, run_due_jobs, run_job
from scripts.system.action_runtime import list_actions, run_action
from scripts.system.automation_health import load_automation_health
from scripts.system.context_engine import load_context_artifact
from scripts.system.today_feed import load_today_feed
from scripts.web_v2 import legacy_support as portal_core


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "web_v2" / "templates"
STATIC_DIR = ROOT / "web_v2" / "static"
GARMIN_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
POST_WORKOUT_REFRESH_SCRIPT = ROOT / "scripts" / "garmin" / "post_workout_refresh.py"
ATHLETE_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "athlete_sync.py"
COACH_ENGINE_SCRIPT = ROOT / "scripts" / "garmin" / "coach_engine.py"
GARMIN_AUTO_SYNC_ENABLED = str(os.getenv("RUNNING_WEB_V2_GARMIN_AUTO_SYNC") or "1").strip().lower() not in {"0", "false", "no", "off"}
GARMIN_AUTO_SYNC_INTERVAL_SECONDS = max(300, int(os.getenv("RUNNING_WEB_V2_GARMIN_SYNC_INTERVAL_SECONDS") or "900"))
GARMIN_SYNC_ACTIVITY_DAYS = max(1, int(os.getenv("RUNNING_WEB_V2_GARMIN_ACTIVITY_DAYS") or "14"))
GARMIN_SYNC_DAILY_DAYS = max(1, int(os.getenv("RUNNING_WEB_V2_GARMIN_DAILY_DAYS") or "14"))
GARMIN_SYNC_ACTIVITY_LIMIT = max(1, int(os.getenv("RUNNING_WEB_V2_GARMIN_ACTIVITY_LIMIT") or "40"))
GARMIN_SYNC_ACTIVITY_TYPE = str(os.getenv("RUNNING_WEB_V2_GARMIN_ACTIVITY_TYPE") or "all").strip() or "all"
GARMIN_SYNC_DASHBOARD_DAYS = max(1, int(os.getenv("RUNNING_WEB_V2_GARMIN_DASHBOARD_DAYS") or "28"))

logger = logging.getLogger("web_v2.garmin_sync")

app = FastAPI(title="RunPilot Next")
app.add_middleware(
    SessionMiddleware,
    secret_key=portal_core.env_config()["secret"],
    same_site="lax",
    session_cookie="runpilot_v2_session",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


TECHNICAL_LABELS = {
    "hold_or_reduce": "Mantener o reducir",
    "hold_running_progression": "Pausar progresión running",
    "convert_second_quality_to_easy_or_bike": "Convertir calidad extra en fácil o bici",
    "every_7_to_14_days_when_tolerated": "Cada 7-14 días si hay tolerancia",
    "ready": "Listo",
    "green": "Verde",
    "yellow": "Precaución",
    "red": "Alto riesgo",
    "no_quality": "Sin calidad",
    "sin calidad": "Sin calidad",
    "easy": "Fácil",
    "recovery": "Recuperación",
    "moderate": "Moderado",
    "hard": "Intenso",
    "race": "Carrera",
    "bike": "Bici",
    "run": "Run",
    "running progression": "Progresión running",
    "cruise intervals": "Intervalos cruise",
    "final recovery and controlled impact return": "Recuperación final y vuelta controlada al impacto",
    "warmup": "Calentamiento",
    "interval": "Bloque principal",
    "cooldown": "Vuelta a la calma",
    "recuperacion": "Recuperación",
}


def clean_ui_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    text = portal_core.strip_markdown_ticks(text)
    text = text.replace("`", "").strip()
    replacements = {
        "Final recovery and controlled impact return": "Recuperación final y vuelta controlada al impacto",
        "absorb Ordes, complete the final low-impact phase, then restart running from 2026-06-16 with conservative but real progression.": "Asimilar Ordes, cerrar la fase de bajo impacto y volver a correr desde 2026-06-16 con progresión conservadora pero real.",
        "General sensations recently poor, but the 2026-06-10 2 km test run did not leave next-day pain; only mild provoked tension remains in the left shin area.": "Sensaciones generales recientes bajas, pero el test de 2 km del 2026-06-10 no dejó dolor al día siguiente; solo queda tensión leve provocada en la tibia izquierda.",
        "Left shin periosteum improving; no pain after 2 km test run, but mild tension remains with exaggerated inward foot rotation": "Periostio tibial izquierdo mejorando; sin dolor tras el test de 2 km, con tensión leve solo al forzar rotación interna del pie.",
        " to ": " a ",
        "aerobico": "aeróbico",
        "Aerobico": "Aeróbico",
        "recuperacion": "recuperación",
        "Recuperacion": "Recuperación",
        "sesion": "sesión",
        "Sesion": "Sesión",
        "tension": "tensión",
        "Tension": "Tensión",
        "reintroduccion": "reintroducción",
        "Reintroduccion": "Reintroducción",
        "progresion": "progresión",
        "Progresion": "Progresión",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text or "-"


def humanize_ui_label(value: Any) -> str:
    text = clean_ui_text(value)
    normalized = text.strip().lower()
    if normalized in TECHNICAL_LABELS:
        return TECHNICAL_LABELS[normalized]
    if "_" in text and " " not in text:
        text = text.replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "-"


templates.env.filters["format_duration"] = portal_core.format_duration
templates.env.filters["format_pace"] = portal_core.format_pace
templates.env.filters["format_datetime"] = portal_core.format_datetime
templates.env.filters["clean_text"] = clean_ui_text
templates.env.filters["humanize"] = humanize_ui_label

_garmin_sync_lock = threading.Lock()
_garmin_sync_state: dict[str, Any] = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_trigger": None,
    "last_ok": None,
    "last_message": None,
}
_garmin_auto_sync_started = False


def run_project_command(command: list[str], timeout: int) -> tuple[bool, str]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        return True, output
    return False, output or f"Command failed with exit code {result.returncode}"


def garmin_sync_status_text(sync_state: dict[str, Any] | None = None) -> str:
    state = sync_state if isinstance(sync_state, dict) else _garmin_sync_state
    if state.get("running"):
        return str(state.get("last_message") or "Sincronizacion Garmin en curso.")
    if state.get("last_finished_at"):
        status_label = "OK" if state.get("last_ok") else "Error"
        return f"{state.get('last_message') or 'Sincronizacion Garmin finalizada.'} ({status_label})"
    return "Pendiente de primera sincronizacion automatica."


def run_garmin_bidirectional_sync(trigger: str) -> tuple[bool, str]:
    if not _garmin_sync_lock.acquire(blocking=False):
        return False, "Ya hay una sincronizacion Garmin en curso."

    started_at = portal_core.datetime.now().isoformat()
    _garmin_sync_state.update(
        {
            "running": True,
            "last_started_at": started_at,
            "last_finished_at": None,
            "last_trigger": trigger,
            "last_message": "Sincronizacion Garmin en curso.",
        }
    )

    commands = [
        (
            "import-activities",
            [
                sys.executable,
                str(GARMIN_SYNC_SCRIPT),
                "import-activities",
                "--days",
                str(GARMIN_SYNC_ACTIVITY_DAYS),
                "--limit",
                str(GARMIN_SYNC_ACTIVITY_LIMIT),
                "--activity-type",
                GARMIN_SYNC_ACTIVITY_TYPE,
            ],
            2400,
        ),
        (
            "sync-planned-workouts",
            [sys.executable, str(GARMIN_SYNC_SCRIPT), "sync-planned-workouts"],
            1800,
        ),
        (
            "import-daily",
            [sys.executable, str(GARMIN_SYNC_SCRIPT), "import-daily", "--days", str(GARMIN_SYNC_DAILY_DAYS)],
            1800,
        ),
        (
            "import-athlete-profile",
            [sys.executable, str(GARMIN_SYNC_SCRIPT), "import-athlete-profile"],
            900,
        ),
        (
            "athlete-sync",
            [sys.executable, str(ATHLETE_SYNC_SCRIPT)],
            900,
        ),
        (
            "post-workout-refresh",
            [
                sys.executable,
                str(POST_WORKOUT_REFRESH_SCRIPT),
                "--activity-days",
                str(GARMIN_SYNC_ACTIVITY_DAYS),
                "--daily-days",
                str(GARMIN_SYNC_DAILY_DAYS),
                "--limit",
                str(GARMIN_SYNC_ACTIVITY_LIMIT),
                "--skip-activity-import",
                "--skip-daily",
                "--skip-athlete-profile",
            ],
            2400,
        ),
        (
            "coach-engine",
            [
                sys.executable,
                str(COACH_ENGINE_SCRIPT),
                "--as-of",
                portal_core.date.today().isoformat(),
                "--days",
                str(GARMIN_SYNC_DASHBOARD_DAYS),
            ],
            1800,
        ),
    ]

    try:
        for label, command, timeout in commands:
            ok, message = run_project_command(command, timeout=timeout)
            if not ok:
                final_message = f"Fallo en {label}: {message.splitlines()[-1] if message else label}"
                _garmin_sync_state.update(
                    {
                        "running": False,
                        "last_finished_at": portal_core.datetime.now().isoformat(),
                        "last_ok": False,
                        "last_message": final_message,
                    }
                )
                logger.error("Garmin sync failed trigger=%s step=%s message=%s", trigger, label, message)
                return False, final_message
        final_message = "Sincronizacion Garmin bidireccional completada."
        _garmin_sync_state.update(
            {
                "running": False,
                "last_finished_at": portal_core.datetime.now().isoformat(),
                "last_ok": True,
                "last_message": final_message,
            }
        )
        logger.info("Garmin sync completed trigger=%s", trigger)
        return True, final_message
    except subprocess.TimeoutExpired as exc:
        final_message = f"Timeout en la sincronizacion Garmin: {exc.cmd[1] if isinstance(exc.cmd, list) and len(exc.cmd) > 1 else 'comando'}"
        _garmin_sync_state.update(
            {
                "running": False,
                "last_finished_at": portal_core.datetime.now().isoformat(),
                "last_ok": False,
                "last_message": final_message,
            }
        )
        logger.exception("Garmin sync timeout trigger=%s", trigger)
        return False, final_message
    finally:
        _garmin_sync_lock.release()


def launch_garmin_bidirectional_sync(trigger: str) -> tuple[bool, str]:
    with _garmin_sync_lock:
        if _garmin_sync_state.get("running"):
            return False, "Ya hay una sincronizacion Garmin en curso."

        def runner() -> None:
            run_garmin_bidirectional_sync(trigger)

        thread = threading.Thread(target=runner, name=f"garmin-sync-{trigger}", daemon=True)
        thread.start()
    return True, "Sincronizacion Garmin lanzada en segundo plano."


def garmin_auto_sync_loop() -> None:
    ok, message = run_garmin_bidirectional_sync("startup")
    if not ok:
        logger.warning("Initial Garmin auto sync failed: %s", message)
    while True:
        time.sleep(GARMIN_AUTO_SYNC_INTERVAL_SECONDS)
        ok, message = run_garmin_bidirectional_sync("interval")
        if not ok:
            logger.warning("Periodic Garmin auto sync failed: %s", message)


def start_garmin_auto_sync() -> None:
    global _garmin_auto_sync_started
    if _garmin_auto_sync_started or not GARMIN_AUTO_SYNC_ENABLED:
        return
    thread = threading.Thread(target=garmin_auto_sync_loop, name="garmin-auto-sync", daemon=True)
    thread.start()
    _garmin_auto_sync_started = True


def svg_smooth_path(points: list[dict[str, Any]]) -> str:
    if not points:
        return ""
    if len(points) == 1:
        return f"M {points[0]['x']} {points[0]['y']}"
    commands = [f"M {points[0]['x']} {points[0]['y']}"]
    for index in range(len(points) - 1):
        current = points[index]
        nxt = points[index + 1]
        prev = points[index - 1] if index > 0 else current
        after = points[index + 2] if index + 2 < len(points) else nxt
        cp1x = current["x"] + (nxt["x"] - prev["x"]) / 6.0
        cp1y = current["y"] + (nxt["y"] - prev["y"]) / 6.0
        cp2x = nxt["x"] - (after["x"] - current["x"]) / 6.0
        cp2y = nxt["y"] - (after["y"] - current["y"]) / 6.0
        commands.append(
            f"C {cp1x:.2f} {cp1y:.2f}, {cp2x:.2f} {cp2y:.2f}, {nxt['x']:.2f} {nxt['y']:.2f}"
        )
    return " ".join(commands)


def format_pace_label(seconds: float | None) -> str:
    return portal_core.format_pace(seconds)


def aerobic_target_hr_values() -> list[int]:
    fallback = [145, 153, 160]
    try:
        zones_payload = portal_core.load_yaml(ROOT / "athlete" / "zones.yaml")
    except OSError:
        return fallback
    heart_rate = zones_payload.get("zones", {}).get("heart_rate", {}) if isinstance(zones_payload, dict) else {}
    z2_text = str(heart_rate.get("z2") or "").strip()
    try:
        z2_low, z2_high = [int(part.strip()) for part in z2_text.split("-")]
    except ValueError:
        return fallback
    midpoint = int(math.ceil((z2_low + z2_high) / 2.0))
    return [z2_low, midpoint, z2_high]


def build_aerobic_trend_chart() -> dict[str, Any] | None:
    activities = portal_core.running_activity_summaries()
    if not isinstance(activities, list) or len(activities) < 3:
        return None

    target_hrs = aerobic_target_hr_values()
    z2_low, _, z2_high = target_hrs
    eligible = []
    for item in activities:
        if not isinstance(item, dict):
            continue
        activity_date = item.get("date")
        pace_s = item.get("pace_s_per_km")
        avg_hr = item.get("avg_hr")
        distance_km = float(item.get("distance_km") or 0.0)
        if activity_date is None or pace_s is None or avg_hr is None:
            continue
        if distance_km < 4.0 or distance_km > 30.0:
            continue
        avg_hr_num = float(avg_hr)
        if avg_hr_num < (z2_low - 8) or avg_hr_num > (z2_high + 3):
            continue
        eligible.append(
            {
                **item,
                "avg_hr": avg_hr_num,
                "pace_s_per_km": float(pace_s),
                "distance_km": distance_km,
            }
        )
    if len(eligible) < 3:
        return None

    week_starts = sorted({item["date"] - timedelta(days=item["date"].weekday()) for item in eligible})
    if not week_starts:
        return None

    palette = ["#72f0c2", "#7cb8ff", "#ffcc81"]
    series = [{"target_hr": target_hr, "color": palette[index % len(palette)], "points": []} for index, target_hr in enumerate(target_hrs)]
    week_labels = []

    for week_start in week_starts[-10:]:
        week_end = week_start + timedelta(days=6)
        window_start = week_end - timedelta(days=41)
        window = [item for item in eligible if window_start <= item["date"] <= week_end]
        if len(window) < 2:
            continue

        added_point = False
        week_label = f"W{week_start.isocalendar().week:02d}"
        for series_item in series:
            target_hr = float(series_item["target_hr"])
            weighted_pace = 0.0
            total_weight = 0.0
            comparable_count = 0
            for candidate in window:
                hr_gap = abs(float(candidate["avg_hr"]) - target_hr)
                if hr_gap > 8.0:
                    continue
                age_days = max(0, (week_end - candidate["date"]).days)
                hr_weight = max(0.1, 1.0 - (hr_gap / 8.0))
                recency_weight = max(0.3, 1.0 - (age_days / 42.0))
                distance_weight = min(max(float(candidate["distance_km"]), 4.0), 18.0) / 18.0
                weight = hr_weight * recency_weight * distance_weight
                weighted_pace += float(candidate["pace_s_per_km"]) * weight
                total_weight += weight
                comparable_count += 1
            if comparable_count < 2 or total_weight <= 0.0:
                continue
            estimated_pace = weighted_pace / total_weight
            series_item["points"].append(
                {
                    "week_start": week_start.isoformat(),
                    "week_label": week_label,
                    "week_end": week_end.isoformat(),
                    "pace_s_per_km": estimated_pace,
                    "pace_label": format_pace_label(estimated_pace),
                    "comparable_count": comparable_count,
                }
            )
            added_point = True
        if added_point:
            week_labels.append({"week_start": week_start.isoformat(), "label": week_label})

    if not week_labels or not any(item["points"] for item in series):
        return None

    width = 720.0
    height = 300.0
    pad_left = 52.0
    pad_right = 20.0
    pad_top = 30.0
    pad_bottom = 56.0
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    week_index = {item["week_start"]: index for index, item in enumerate(week_labels)}
    max_index = max(1, len(week_labels) - 1)
    all_paces = [float(point["pace_s_per_km"]) for item in series for point in item["points"]]
    pace_padding = max(6.0, (max(all_paces) - min(all_paces)) * 0.14) if len(all_paces) > 1 else 10.0
    chart_min_pace = max(1.0, min(all_paces) - pace_padding)
    chart_max_pace = max(all_paces) + pace_padding
    pace_span = max(1.0, chart_max_pace - chart_min_pace)

    def point_xy(week_start: str, pace_s: float) -> tuple[float, float]:
        x_index = week_index[week_start]
        x = pad_left + (x_index / max_index) * plot_width
        y = pad_top + ((pace_s - chart_min_pace) / pace_span) * plot_height
        return round(x, 2), round(y, 2)

    for item in series:
        svg_points = []
        for point in item["points"]:
            x, y = point_xy(str(point["week_start"]), float(point["pace_s_per_km"]))
            svg_points.append({**point, "x": x, "y": y})
        item["svg_points"] = svg_points
        item["polyline"] = " ".join(
            f"{'M' if index == 0 else 'L'} {point['x']:.2f} {point['y']:.2f}"
            for index, point in enumerate(svg_points)
        )
        item["latest"] = svg_points[-1] if svg_points else None
        item["recent_points"] = svg_points[-3:]

    latest_values = [
        {
            "target_hr": item["target_hr"],
            "pace_label": item["latest"]["pace_label"],
            "week_label": item["latest"]["week_label"],
            "color": item["color"],
        }
        for item in series
        if item.get("latest")
    ]
    y_ticks = []
    for value in [chart_min_pace, chart_min_pace + pace_span / 2.0, chart_max_pace]:
        y = pad_top + ((value - chart_min_pace) / pace_span) * plot_height
        y_ticks.append({"value": format_pace_label(value), "y": round(y, 2)})
    x_ticks = []
    for item in week_labels:
        x, _ = point_xy(str(item["week_start"]), chart_max_pace)
        x_ticks.append({"x": x, "label": item["label"]})

    return {
        "title": "Evolución ritmos aeróbicos",
        "target_hrs": target_hrs,
        "subtitle": f"Estimación semanal con ventana móvil de 6 semanas para tu Z2 ({z2_low}-{z2_high} ppm).",
        "series": series,
        "latest_values": latest_values,
        "svg": {
            "width": width,
            "height": height,
            "x_axis_y": height - pad_bottom,
            "y_axis_x": pad_left,
            "x_ticks": x_ticks,
            "y_ticks": y_ticks,
        },
    }


def authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def auth_guard(request: Request) -> RedirectResponse | None:
    if authenticated(request):
        return None
    return RedirectResponse(url="/login", status_code=303)


def template_context(request: Request, **values: Any) -> dict[str, Any]:
    config = portal_core.env_config()
    automation_health = load_automation_health()
    today_context = load_context_artifact("today_context")
    context = {
        "request": request,
        "portal_configured": config["configured"],
        "authenticated": authenticated(request),
        "today": portal_core.date.today().isoformat(),
        "current_path": request.url.path,
        "flash": request.session.pop("flash", None),
        "garmin_sync": dict(_garmin_sync_state),
        "garmin_sync_status_text": garmin_sync_status_text(),
        "automation_health": automation_health,
        "today_context": today_context,
    }
    context.update(values)
    return context


def active_nav(path: str) -> str:
    if path == "/":
        return "hoy"
    if path.startswith("/calendar"):
        return "calendar"
    if path.startswith("/plan"):
        return "plan"
    if path.startswith("/eventos"):
        return "eventos"
    if path.startswith("/atleta"):
        return "atleta"
    return ""


def today_fueling_entries(today_plan: dict[str, Any]) -> list[dict[str, Any]]:
    planned = today_plan.get("planned_workout") if isinstance(today_plan.get("planned_workout"), dict) else None
    if not planned or not planned.get("slug"):
        return []
    payload = portal_core.load_or_build_fueling_payload()
    workout_fueling = portal_core.workout_fueling_lookup(payload, str(planned.get("slug")))
    if isinstance(workout_fueling, dict):
        entries = workout_fueling.get("entries")
        if isinstance(entries, list):
            return entries
    return []


def compact_today_review(review: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(review, dict):
        return None
    return {
        **review,
        "detail_url": f"/completed-workouts/{review.get('slug') or ''}",
    }


def compact_race(race: dict[str, Any] | None, day: str) -> dict[str, Any] | None:
    if not isinstance(race, dict):
        return None
    distance = race.get("distance_km") or race.get("distance") or "-"
    goal = race.get("goal") or race.get("priority") or "Carrera"
    return {
        **race,
        "slug": f"race-{day}",
        "name": race.get("name") or "Carrera",
        "session_kind_label": "Carrera",
        "estimated_duration": str(distance),
        "description": str(goal),
        "detail_url": f"/calendar/day/{day or ''}",
        "day_url": f"/calendar/day/{day or ''}",
    }


def compact_workout(workout: dict[str, Any] | None, day: str) -> dict[str, Any] | None:
    if not workout:
        return None
    return {
        **workout,
        "detail_url": f"/planned-workouts/{workout.get('slug') or ''}",
        "day_url": f"/calendar/day/{day or ''}",
    }


def normalized_sport(value: str | None) -> str:
    sport = str(value or "").strip().lower()
    if sport in {"running", "trail_running", "race"}:
        return "running"
    if sport in {"cycling", "road_biking", "indoor_cycling", "bike", "biking"}:
        return "cycling"
    if sport in {"swimming", "pool_swimming", "open_water_swimming"}:
        return "swimming"
    if sport in {"strength", "strength_training"}:
        return "strength"
    if sport in {"mobility", "stretching"}:
        return "mobility"
    if sport in {"elliptical", "fitness_equipment"}:
        return "elliptical"
    return sport or "other"


def sport_label(value: str | None) -> str:
    return {
        "running": "Correr",
        "cycling": "Bici",
        "swimming": "Natación",
        "strength": "Fuerza",
        "mobility": "Movilidad",
        "elliptical": "Cardio",
        "other": "Otra",
    }.get(normalized_sport(value), "Otra")


def sport_icon_html(value: str | None) -> str:
    return {
        "running": "&#128095;",
        "cycling": "&#128690;",
        "swimming": "&#127946;",
        "strength": "&#127947;",
        "mobility": "&#129496;",
        "elliptical": "&#127939;",
        "other": "&#9679;",
    }.get(normalized_sport(value), "&#9679;")


def event_icon_html() -> str:
    return "&#127937;"


def intensity_key(item: dict[str, Any], source: str | None = None) -> str:
    source_key = str(source or item.get("source") or "").strip().lower()
    sport = normalized_sport(item.get("sport"))
    kind = str(item.get("session_kind") or item.get("kind") or "").strip().lower()
    text = " ".join(
        [
            str(item.get("name") or ""),
            str(item.get("title") or ""),
            str(item.get("activity_name") or ""),
            str(item.get("description") or ""),
            str(item.get("session_kind_label") or ""),
        ]
    ).lower()

    if source_key == "race" or kind == "race":
        return "race"
    if sport in {"strength", "mobility"}:
        return "neutral"
    if kind in {"easy", "recovery", "elliptical"}:
        return "easy"
    if kind == "long_run":
        return "moderate"

    hard_markers = {
        "series",
        "interval",
        "repeticiones",
        "vo2",
        "sprint",
        "anaer",
        "cuestas",
        "bloque medio",
    }
    moderate_markers = {
        "tempo",
        "umbral",
        "controlad",
        "progresiv",
        "ritmo",
        "steady",
        "continua",
        "continuidad",
        "larga",
    }
    if kind == "quality":
        return "hard" if any(marker in text for marker in hard_markers) else "moderate"
    if any(marker in text for marker in hard_markers):
        return "hard"
    if any(marker in text for marker in moderate_markers):
        return "moderate"
    return "easy"


def intensity_label(value: str) -> str:
    return {
        "easy": "Suave",
        "moderate": "Media",
        "hard": "Alta",
        "race": "Carrera",
        "neutral": "Neutra",
        "empty": "Libre",
    }.get(value, "Suave")


def intensity_style(value: str, surface: str = "day") -> str:
    palette = {
        "easy": {
            "day_border": "rgba(89, 211, 147, 0.3)",
            "day_bg": "linear-gradient(180deg, rgba(89, 211, 147, 0.2), rgba(89, 211, 147, 0.09) 36%, rgba(10, 20, 36, 0.96) 86%), rgba(12, 24, 36, 0.95)",
            "pill_border": "rgba(89, 211, 147, 0.2)",
            "pill_bg": "rgba(89, 211, 147, 0.1)",
        },
        "moderate": {
            "day_border": "rgba(255, 204, 129, 0.3)",
            "day_bg": "linear-gradient(180deg, rgba(255, 204, 129, 0.2), rgba(255, 204, 129, 0.09) 36%, rgba(10, 20, 36, 0.96) 86%), rgba(12, 24, 36, 0.95)",
            "pill_border": "rgba(255, 204, 129, 0.2)",
            "pill_bg": "rgba(255, 204, 129, 0.1)",
        },
        "hard": {
            "day_border": "rgba(255, 153, 82, 0.34)",
            "day_bg": "linear-gradient(180deg, rgba(255, 153, 82, 0.22), rgba(255, 153, 82, 0.1) 36%, rgba(10, 20, 36, 0.96) 86%), rgba(12, 24, 36, 0.95)",
            "pill_border": "rgba(255, 153, 82, 0.22)",
            "pill_bg": "rgba(255, 153, 82, 0.11)",
        },
        "race": {
            "day_border": "rgba(255, 128, 120, 0.36)",
            "day_bg": "linear-gradient(180deg, rgba(255, 128, 120, 0.24), rgba(255, 128, 120, 0.11) 36%, rgba(10, 20, 36, 0.96) 86%), rgba(12, 24, 36, 0.95)",
            "pill_border": "rgba(255, 128, 120, 0.24)",
            "pill_bg": "rgba(255, 128, 120, 0.11)",
        },
        "neutral": {
            "day_border": "rgba(148, 168, 201, 0.28)",
            "day_bg": "linear-gradient(180deg, rgba(148, 168, 201, 0.17), rgba(148, 168, 201, 0.08) 36%, rgba(10, 20, 36, 0.96) 86%), rgba(12, 24, 36, 0.95)",
            "pill_border": "rgba(148, 168, 201, 0.18)",
            "pill_bg": "rgba(148, 168, 201, 0.09)",
        },
        "empty": {
            "day_border": "rgba(255, 255, 255, 0.08)",
            "day_bg": "linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.02)), rgba(10, 20, 36, 0.9)",
            "pill_border": "rgba(255, 255, 255, 0.08)",
            "pill_bg": "rgba(255, 255, 255, 0.04)",
        },
    }
    selected = palette.get(value, palette["easy"])
    if surface == "pill":
        return f"background: {selected['pill_bg']}; border-color: {selected['pill_border']};"
    return f"border-color: {selected['day_border']}; background: {selected['day_bg']};"


def calendar_icons(sport: str | None, include_event: bool = False) -> list[str]:
    return [event_icon_html() if include_event else sport_icon_html(sport)]


def decorate_calendar_entry(item: dict[str, Any] | None, source: str | None = None, completed: bool | None = None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    source_key = str(source or item.get("source") or "").strip().lower()
    sport = normalized_sport(str(item.get("sport") or ""))
    intensity = intensity_key(item, source=source_key)
    return {
        **item,
        "calendar_source": source_key,
        "sport": sport,
        "sport_label": sport_label(sport),
        "icons": calendar_icons(sport, include_event=source_key == "race"),
        "primary_icon": event_icon_html() if source_key == "race" else sport_icon_html(sport),
        "intensity_key": intensity,
        "intensity_label": intensity_label(intensity),
        "calendar_color_class": f"intensity-{intensity}",
        "calendar_inline_style": intensity_style(intensity, surface="pill"),
        "is_completed": bool(item.get("is_completed")) if completed is None else completed,
    }


def home_page_data() -> dict[str, Any]:
    feed = load_today_feed()
    if feed:
        return {
            **feed,
            "active_nav": "hoy",
        }

    payload = portal_core.home_page_data()
    today_plan = payload.get("today_plan", {}) if isinstance(payload.get("today_plan"), dict) else {}
    today_date = str(today_plan.get("date") or "").strip()
    day_payload = portal_core.calendar_day_data(today_date) if today_date else {"planned_items": [], "completed_items": []}
    planned_items = day_payload.get("planned_items", []) if isinstance(day_payload.get("planned_items"), list) else []
    completed_items = day_payload.get("completed_items", []) if isinstance(day_payload.get("completed_items"), list) else []
    race_items = portal_core.races_by_day().get(today_date, []) if today_date else []
    workouts = [item for item in [compact_workout(workout, today_date) for workout in planned_items] if item]
    workouts.extend(item for item in [compact_race(race, today_date) for race in race_items] if item)
    reviews = [item for item in [compact_today_review(review) for review in completed_items] if item]
    review = reviews[0] if reviews else compact_today_review(today_plan.get("completed_review"))
    workout = workouts[0] if workouts else None
    completed_review = today_plan.get("completed_review") if isinstance(today_plan.get("completed_review"), dict) else None
    planned_workout = today_plan.get("planned_workout") if isinstance(today_plan.get("planned_workout"), dict) else None
    if race_items and today_date:
        race_review = next(
            (
                item
                for item in portal_core.completed_reviews()
                if item.get("date") == today_date and str(item.get("session_kind") or "").strip().lower() == "race"
            ),
            None,
        )
        if race_review:
            review = compact_today_review(race_review)
            reviews = [review_item for review_item in reviews if review_item.get("slug") != review.get("slug")]
            reviews.insert(0, review)
        elif completed_review and planned_workout and not portal_core.review_matches_planned_workout(completed_review, planned_workout):
            workout = None
    fueling_entries = today_fueling_entries(today_plan)
    decision = payload.get("dashboard", {}).get("decision", {}) if isinstance(payload.get("dashboard"), dict) else {}
    progression = decision.get("progression", {}) if isinstance(decision.get("progression"), dict) else {}
    training_paces = payload.get("dashboard", {}).get("training_paces", {}) if isinstance(payload.get("dashboard"), dict) else {}
    return {
        "workspace": payload.get("workspace"),
        "dashboard": payload.get("dashboard"),
        "active_cycle": payload.get("active_cycle"),
        "today_plan": today_plan,
        "today_workout": workout,
        "today_review": review,
        "today_workouts": workouts,
        "today_reviews": reviews,
        "today_fueling": fueling_entries,
        "progression": progression,
        "training_paces": training_paces,
        "upcoming": [
            {
                **item,
                "detail_url": f"/planned-workouts/{item.get('slug') or ''}",
            }
            for item in payload.get("upcoming", [])[:4]
        ],
        "recent_reviews": [compact_today_review(item) for item in payload.get("recent_reviews", [])[:3]],
        "active_nav": "hoy",
    }


def calendar_page_data(month: str | None, focus: str = "all") -> dict[str, Any]:
    payload = portal_core.calendar_month_data_combined(month)

    def session_priority(item: dict[str, Any]) -> tuple[int, int, str]:
        intensity_order = {"race": 0, "hard": 1, "moderate": 2, "easy": 3, "neutral": 4, "empty": 5}
        source_order = {"race": 0, "planned": 1, "review": 2}
        return (
            intensity_order.get(str(item.get("intensity_key") or "easy"), 9),
            source_order.get(str(item.get("calendar_source") or "planned"), 9),
            0 if item.get("is_completed") else 1,
            str(item.get("title") or ""),
        )

    def build_day_sessions(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        sessions: list[dict[str, Any]] = []
        race_completed = any(
            str(item.get("source") or "").strip().lower() == "review" and str(item.get("session_kind") or item.get("kind") or "").strip().lower() == "race"
            for item in events
            if isinstance(item, dict)
        )
        for item in events:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip().lower()
            status = str(item.get("status") or "").strip().lower()
            if source == "planned":
                planned = item.get("planned_workout") if isinstance(item.get("planned_workout"), dict) else item
                sessions.append(
                    decorate_calendar_entry(
                        {
                            "title": planned.get("name") or item.get("title") or "Sesión planificada",
                            "name": planned.get("name"),
                            "description": planned.get("description"),
                            "sport": planned.get("sport"),
                            "session_kind": planned.get("session_kind") or item.get("kind"),
                            "session_kind_label": planned.get("session_kind_label") or item.get("session_kind_label"),
                            "detail_url": item.get("detail_url"),
                            "is_completed": bool(planned.get("is_completed")),
                        },
                        source="planned",
                        completed=bool(planned.get("is_completed")),
                    )
                )
            elif source == "review" and status == "completed_unplanned":
                review = item.get("review") if isinstance(item.get("review"), dict) else item
                sessions.append(
                    decorate_calendar_entry(
                        {
                            "title": review.get("activity_name") or item.get("title") or "Actividad completada",
                            "activity_name": review.get("activity_name"),
                            "description": review.get("compliance_note") or review.get("feedback_summary"),
                            "sport": review.get("sport"),
                            "session_kind": review.get("session_kind") or item.get("kind"),
                            "session_kind_label": review.get("session_kind_label") or item.get("session_kind_label"),
                            "detail_url": item.get("detail_url"),
                            "is_completed": True,
                        },
                        source="review",
                        completed=True,
                    )
                )
            elif source == "race":
                race = item.get("race") if isinstance(item.get("race"), dict) else item
                sessions.append(
                    decorate_calendar_entry(
                        {
                            "title": race.get("name") or item.get("title") or "Evento",
                            "name": race.get("name"),
                            "description": race.get("goal") or race.get("priority") or "Carrera",
                            "sport": race.get("sport") or "running",
                            "session_kind": "race",
                            "session_kind_label": "Carrera",
                            "detail_url": item.get("detail_url"),
                            "is_completed": race_completed,
                        },
                        source="race",
                        completed=race_completed,
                    )
                )
        sessions.sort(key=session_priority)
        has_unplanned = any(str(item.get("status") or "").strip().lower() == "completed_unplanned" for item in events if isinstance(item, dict))
        return sessions, has_unplanned

    def day_matches_focus(summary: dict[str, Any], selected_focus: str) -> bool:
        if selected_focus == "all":
            return True
        if selected_focus == "key":
            return summary["primary_intensity"] in {"moderate", "hard", "race"}
        if selected_focus == "completed":
            return summary["completed_count"] > 0
        if selected_focus == "conflicts":
            return summary["has_unplanned"] or summary["has_replan"]
        if selected_focus == "races":
            return summary["has_race"]
        return True

    def summarize_day(day: dict[str, Any]) -> dict[str, Any]:
        events = day.get("events", []) if isinstance(day.get("events"), list) else []
        sessions, has_unplanned = build_day_sessions(events)
        primary = sessions[0] if sessions else None
        counts = {"planned": 0, "reviewed": 0, "races": 0}
        for item in events:
            source = str(item.get("source") or "").strip().lower()
            if source == "planned":
                counts["planned"] += 1
            elif source == "review":
                counts["reviewed"] += 1
            elif source == "race":
                counts["races"] += 1
        has_replan = any(bool((item.get("replan") or {}).get("is_changed")) for item in events if isinstance(item, dict))
        completed_count = sum(1 for item in sessions if item.get("is_completed"))
        metric_items = []
        if sessions:
            metric_items.append(f"{len(sessions)} ses.")
            metric_items.append(f"{completed_count} hechas")
        elif has_replan:
            metric_items.append("Replan")
        return {
            "primary": primary,
            "sessions": sessions,
            "counts": counts,
            "dominant_class": str((primary or {}).get("calendar_color_class") or "intensity-empty"),
            "primary_intensity": str((primary or {}).get("intensity_key") or "empty"),
            "day_inline_style": intensity_style(str((primary or {}).get("intensity_key") or "empty"), surface="day"),
            "completed_count": completed_count,
            "has_race": counts["races"] > 0,
            "has_unplanned": has_unplanned,
            "headline": (
                primary.get("title")
                if isinstance(primary, dict) and primary.get("title")
                else "Sin carga"
            ),
            "subline": (
                f"{primary.get('sport_label')} · {primary.get('intensity_label')}"
                if isinstance(primary, dict) and primary.get("sport_label")
                else "Día libre"
            ),
            "metric_items": metric_items[:2],
            "has_replan": has_replan,
            "items": events,
        }

    summary_days: list[dict[str, Any]] = []
    for week in payload.get("weeks", []):
        for day in week:
            day["v2_detail_url"] = f"/calendar/day/{day.get('date')}"
            day["summary"] = summarize_day(day)
            day["is_dimmed"] = not day_matches_focus(day["summary"], focus)
            summary_days.append(day)

    month_days = [day for day in summary_days if day.get("in_month")]
    month_start = month_days[0].get("date") if month_days else portal_core.date.today().replace(day=1).isoformat()
    month_end = month_days[-1].get("date") if month_days else portal_core.date.today().isoformat()
    summary = {
        "planned": sum(day["summary"]["counts"]["planned"] for day in month_days),
        "completed": sum(day["summary"]["counts"]["reviewed"] for day in month_days),
        "races": sum(day["summary"]["counts"]["races"] for day in month_days),
        "key_days": sum(1 for day in month_days if day["summary"]["primary_intensity"] in {"moderate", "hard", "race"}),
        "conflicts": sum(1 for day in month_days if day["summary"]["has_unplanned"] or day["summary"]["has_replan"]),
    }
    next_race = next(
        (
            day["summary"]["primary"]
            for day in month_days
            if day["summary"]["has_race"] and day["summary"]["primary"] and day.get("date", "") >= portal_core.date.today().isoformat()
        ),
        None,
    )
    payload["month_summary"] = summary
    payload["next_race"] = next_race
    payload["focus"] = focus if focus in {"all", "key", "completed", "conflicts", "races"} else "all"
    payload["focus_options"] = [
        {"key": "all", "label": "Todo"},
        {"key": "key", "label": "Días clave"},
        {"key": "completed", "label": "Hechos"},
        {"key": "conflicts", "label": "Conflictos"},
        {"key": "races", "label": "Carreras"},
    ]
    payload["plan_range_form"] = {
        "start_date": month_start,
        "end_date": month_end,
        "premise": "",
        "return_to": f"/calendar?month={payload.get('selected')}&focus={payload.get('focus')}",
    }
    payload["replan_range_form"] = {
        "start_date": month_start,
        "end_date": month_end,
        "premise": "",
        "return_to": f"/calendar?month={payload.get('selected')}&focus={payload.get('focus')}",
    }
    payload["active_nav"] = "calendar"
    return payload


def plan_page_data() -> dict[str, Any]:
    workouts = portal_core.planned_workouts()
    reviews = portal_core.completed_reviews()
    cycle = portal_core.cycle_page_data()
    master_plan = cycle.get("master_plan", {}) if isinstance(cycle.get("master_plan"), dict) else {}
    blocks = master_plan.get("blocks", []) if isinstance(master_plan.get("blocks"), list) else []
    current_block = cycle.get("current_block") if isinstance(cycle.get("current_block"), dict) else None
    current_index = int(current_block.get("index") or 0) if current_block else 0
    completed_blocks = [block for block in blocks if int(block.get("index") or 0) < current_index]
    future_blocks = [block for block in blocks if int(block.get("index") or 0) > current_index]
    week = portal_core.week_page_data(dashboard=cycle.get("dashboard"), workouts=workouts, reviews=reviews)
    dashboard = cycle.get("dashboard", {}) if isinstance(cycle.get("dashboard"), dict) else {}
    decision = dashboard.get("decision", {}) if isinstance(dashboard.get("decision"), dict) else {}
    return {
        "cycle": cycle,
        "master_plan": master_plan,
        "current_block": current_block,
        "completed_blocks": completed_blocks,
        "future_blocks": future_blocks,
        "week": week,
        "progression": decision.get("progression", {}),
        "training_paces": dashboard.get("training_paces", {}),
        "goal_gates": dashboard.get("goal_gates", {}),
        "hybrid_training": (dashboard.get("athlete_state", {}) or {}).get("athlete", {}).get("hybrid_training", {}),
        "replanning": decision.get("replanning", {}),
        "aerobic_trend_chart": build_aerobic_trend_chart(),
        "active_nav": "plan",
    }


def events_page_data() -> dict[str, Any]:
    payload = portal_core.races_operational_page_data()
    payload["active_nav"] = "eventos"
    return payload


def athlete_page_data() -> dict[str, Any]:
    athlete = portal_core.athlete_page_data()
    fueling = portal_core.fueling_page_data()
    zones = portal_core.load_optional_yaml(ROOT / "athlete" / "zones.yaml").get("zones", {})
    return {
        "athlete": athlete,
        "zones": zones,
        "impact_return": athlete.get("impact_return", {}),
        "hybrid_training": athlete.get("hybrid_training", {}),
        "training_paces": athlete.get("training_paces", {}),
        "coach_permissions": athlete.get("coach_permissions", {}),
        "replanning": athlete.get("replanning", {}),
        "fueling": {
            "supplements": fueling.get("supplements", [])[:6],
            "generated_at": fueling.get("generated_at"),
        },
        "active_nav": "atleta",
    }


def calendar_day_page_data(day: str) -> dict[str, Any]:
    payload = portal_core.calendar_day_data(day)
    for item in payload.get("planned_items", []):
        item["detail_url"] = f"/planned-workouts/{item.get('slug')}"
        item.update(decorate_calendar_entry(item, source="planned", completed=bool(item.get("is_completed"))))
    for item in payload.get("completed_items", []):
        item["detail_url"] = f"/completed-workouts/{item.get('slug')}"
        item.update(decorate_calendar_entry(item, source="review", completed=True))
    decorated_races = []
    for item in payload.get("races", []):
        decorated_races.append(
            decorate_calendar_entry(
                {
                    **item,
                    "title": item.get("name") or "Evento",
                    "sport": item.get("sport") or "running",
                    "session_kind": "race",
                    "session_kind_label": "Carrera",
                },
                source="race",
                completed=any(str(review.get("session_kind") or "").strip().lower() == "race" for review in payload.get("completed_items", [])),
            )
        )
    payload["races"] = decorated_races
    if isinstance(payload.get("today_plan"), dict):
        today_plan = payload["today_plan"]
        links = today_plan.get("links", {}) if isinstance(today_plan.get("links"), dict) else {}
        if links.get("detail_url"):
            links["detail_url"] = f"/planned-workouts/{today_plan.get('planned_workout', {}).get('slug')}"
        if links.get("feedback_url") and isinstance(today_plan.get("completed_review"), dict):
            links["feedback_url"] = f"/completed-workouts/{today_plan.get('completed_review', {}).get('slug')}"
        if isinstance(today_plan.get("planned_workout"), dict):
            workout = today_plan["planned_workout"]
            workout["detail_url"] = f"/planned-workouts/{workout.get('slug')}"
    payload["active_nav"] = "calendar"
    return payload


def planned_workout_page_data(slug: str) -> dict[str, Any] | None:
    workout = portal_core.planned_workout_detail(slug)
    if not workout:
        return None
    linked_review = workout.get("linked_review") if isinstance(workout.get("linked_review"), dict) else None
    return {
        "workout": workout,
        "linked_review_url": f"/completed-workouts/{linked_review.get('slug')}" if linked_review and linked_review.get("slug") else None,
        "replan_form": {
            "slug": slug,
            "premise": "",
            "return_to": f"/planned-workouts/{slug}",
        },
        "active_nav": "calendar",
    }


def completed_workout_page_data(slug: str) -> dict[str, Any] | None:
    review = portal_core.completed_review_detail(slug)
    if not review and slug.startswith("garmin-import-"):
        review = portal_core.imported_garmin_activity_detail(slug.removeprefix("garmin-import-"))
    if not review:
        return None
    review["garmin_feedback"] = portal_core.garmin_feedback_metrics(review.get("garmin_activity_id"))
    recovery = review.get("recovery_analysis") if isinstance(review.get("recovery_analysis"), dict) else None
    if recovery and recovery.get("status") == "complete":
        chart = recovery.get("chart") if isinstance(recovery.get("chart"), dict) else {}
        points = chart.get("points") if isinstance(chart.get("points"), list) else []
        if points:
            width = 640.0
            height = 260.0
            pad_left = 44.0
            pad_right = 18.0
            pad_top = 14.0
            pad_bottom = 34.0
            plot_width = width - pad_left - pad_right
            plot_height = height - pad_top - pad_bottom
            min_minute = min(float(point.get("minute") or 0.0) for point in points)
            max_minute = max(float(point.get("minute") or 0.0) for point in points)
            min_hr = min(float(point.get("hr") or 0.0) for point in points)
            max_hr = max(float(point.get("hr") or 0.0) for point in points)
            minute_span = max(1.0, max_minute - min_minute)
            hr_padding = max(4.0, (max_hr - min_hr) * 0.12)
            chart_min_hr = max(40.0, min_hr - hr_padding)
            chart_max_hr = max_hr + hr_padding
            hr_span = max(1.0, chart_max_hr - chart_min_hr)

            svg_points: list[dict[str, Any]] = []
            for point in points:
                minute = float(point.get("minute") or 0.0)
                hr = float(point.get("hr") or 0.0)
                x = pad_left + ((minute - min_minute) / minute_span) * plot_width
                y = pad_top + (1.0 - ((hr - chart_min_hr) / hr_span)) * plot_height
                svg_points.append({
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "minute": minute,
                    "hr": int(round(hr)),
                    "label": point.get("label") or f"{int(round(minute))}m",
                })

            smooth_path = svg_smooth_path(svg_points)
            area_path = (
                f"{smooth_path} L {svg_points[-1]['x']:.2f} {height - pad_bottom:.2f} "
                f"L {pad_left:.2f} {height - pad_bottom:.2f} Z"
            )
            x_ticks = []
            for point in svg_points:
                rounded_minute = int(round(float(point["minute"])))
                if rounded_minute in {0, 1, 3, 5, 10, 15, 20, 25, 30}:
                    x_ticks.append({"x": point["x"], "label": point["label"]})
            highlighted = []
            for point in svg_points:
                rounded_minute = int(round(float(point["minute"])))
                if rounded_minute in {0, 1, 3, 5, 10, 15, 20, 25, 30}:
                    highlighted.append(point)
            normal_point = None
            if recovery.get("time_to_normal_s") is not None:
                target_minute = float(recovery.get("time_to_normal_s") or 0.0) / 60.0
                normal_point = min(svg_points, key=lambda item: abs(float(item["minute"]) - target_minute))
            callout_points = []
            for target in (0, 3):
                candidate = min(svg_points, key=lambda item: abs(float(item["minute"]) - target))
                callout_points.append({
                    "x": candidate["x"],
                    "y": candidate["y"],
                    "hr": candidate["hr"],
                    "minute_label": candidate["label"],
                })

            recovery["chart_svg"] = {
                "width": width,
                "height": height,
                "points": svg_points,
                "polyline": " ".join(f"{point['x']},{point['y']}" for point in svg_points),
                "smooth_path": smooth_path,
                "area_path": area_path,
                "x_ticks": x_ticks,
                "highlighted": highlighted,
                "callout_points": callout_points,
                "normal_point": normal_point,
                "x_axis_y": height - pad_bottom,
                "y_axis_x": pad_left,
                "normal_y": round(pad_top + (1.0 - ((float(recovery.get('normal_hr_bpm') or 0.0) - chart_min_hr) / hr_span)) * plot_height, 2),
                "normal_hr_bpm": recovery.get("normal_hr_bpm"),
                "finish_hr_bpm": recovery.get("finish_hr_bpm"),
                "y_ticks": [
                    {
                        "value": int(round(value)),
                        "y": round(pad_top + (1.0 - ((value - chart_min_hr) / hr_span)) * plot_height, 2),
                    }
                    for value in [chart_min_hr, chart_min_hr + hr_span / 2.0, chart_max_hr]
                ],
            }
    return {
        "review": review,
        "active_nav": "calendar",
    }


def safe_return_to(value: str | None, fallback: str) -> str:
    target = str(value or "").strip()
    if target.startswith("/"):
        return target
    return fallback


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if authenticated(request):
        return templates.TemplateResponse(request, "index.html", template_context(request, page=home_page_data(), active_nav="hoy"))
    return templates.TemplateResponse(request, "login.html", template_context(request, error=None, active_nav=""))


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)) -> HTMLResponse:
    config = portal_core.env_config()
    if not config["configured"]:
        return templates.TemplateResponse(
            request,
            "login.html",
            template_context(request, error="La web no está configurada todavía.", active_nav=""),
            status_code=503,
        )
    if username == config["username"] and password == config["password"]:
        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        template_context(request, error="Credenciales incorrectas.", active_nav=""),
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "index.html", template_context(request, page=home_page_data(), active_nav=active_nav(request.url.path)))


@app.get("/calendar", response_class=HTMLResponse)
async def calendar(request: Request, month: str | None = None, focus: str = "all") -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "calendar.html",
        template_context(request, page=calendar_page_data(month, focus=focus), active_nav=active_nav(request.url.path)),
    )


@app.post("/calendar/plan-range")
async def calendar_plan_range_submit(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    premise: str = Form(""),
    return_to: str = Form("/calendar"),
) -> RedirectResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    result = run_action(
        "plan_range",
        payload={
            "start_date": start_date,
            "end_date": end_date,
            "premise": premise,
            "source": "web",
        },
    )
    request.session["flash"] = {"level": "ok" if result.get("ok") else "error", "message": str(result.get("message") or "Operacion finalizada.")}
    return RedirectResponse(url=safe_return_to(return_to, "/calendar"), status_code=303)


@app.post("/calendar/replan-range")
async def calendar_replan_range_submit(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    premise: str = Form(""),
    return_to: str = Form("/calendar"),
) -> RedirectResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    result = run_action(
        "replan_range",
        payload={
            "start_date": start_date,
            "end_date": end_date,
            "premise": premise,
            "source": "web",
        },
    )
    request.session["flash"] = {"level": "ok" if result.get("ok") else "error", "message": str(result.get("message") or "Operacion finalizada.")}
    return RedirectResponse(url=safe_return_to(return_to, "/calendar"), status_code=303)


@app.get("/plan", response_class=HTMLResponse)
async def plan(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "plan.html", template_context(request, page=plan_page_data(), active_nav=active_nav(request.url.path)))


@app.get("/eventos", response_class=HTMLResponse)
async def eventos(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "eventos.html", template_context(request, page=events_page_data(), active_nav=active_nav(request.url.path)))


@app.get("/atleta", response_class=HTMLResponse)
async def atleta(request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "atleta.html", template_context(request, page=athlete_page_data(), active_nav=active_nav(request.url.path)))


@app.get("/calendar/day/{day}", response_class=HTMLResponse)
async def calendar_day(day: str, request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "calendar_day.html",
        template_context(request, page=calendar_day_page_data(day), active_nav="calendar"),
    )


@app.get("/planned-workouts/{slug}", response_class=HTMLResponse)
async def planned_workout_detail(slug: str, request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    page = planned_workout_page_data(slug)
    if not page:
        return HTMLResponse("Sesión planificada no encontrada.", status_code=404)
    return templates.TemplateResponse(request, "planned_workout_detail.html", template_context(request, page=page, active_nav="calendar"))


@app.post("/planned-workouts/{slug}/replan")
async def planned_workout_replan_submit(
    slug: str,
    request: Request,
    premise: str = Form(""),
    return_to: str = Form(""),
) -> RedirectResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    result = run_action(
        "replan_workout",
        payload={
            "slug": slug,
            "premise": premise,
            "source": "web",
        },
    )
    request.session["flash"] = {"level": "ok" if result.get("ok") else "error", "message": str(result.get("message") or "Operacion finalizada.")}
    return RedirectResponse(url=safe_return_to(return_to, f"/planned-workouts/{slug}"), status_code=303)


@app.get("/completed-workouts/{slug}", response_class=HTMLResponse)
async def completed_workout_detail(slug: str, request: Request) -> HTMLResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    page = completed_workout_page_data(slug)
    if not page:
        return HTMLResponse("Sesión completada no encontrada.", status_code=404)
    return templates.TemplateResponse(request, "completed_workout_detail.html", template_context(request, page=page, active_nav="calendar"))


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    automation_health = load_automation_health()
    return {"status": "ok", "automation_status": automation_health.get("overall_status"), "summary": automation_health.get("summary")}


@app.post("/garmin/sync")
async def garmin_sync_submit(request: Request, return_to: str = Form("/")) -> RedirectResponse:
    redirect = auth_guard(request)
    if redirect:
        return redirect
    ok, message = launch_garmin_bidirectional_sync("manual")
    request.session["flash"] = {"level": "ok" if ok else "error", "message": message}
    target = return_to if str(return_to or "").startswith("/") else "/"
    return RedirectResponse(url=target, status_code=303)


@app.get("/api/garmin/sync")
async def garmin_sync_status(request: Request) -> JSONResponse:
    guard = auth_guard(request)
    if guard:
        return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)
    return JSONResponse({"ok": True, "sync": dict(_garmin_sync_state), "status_text": garmin_sync_status_text()}, status_code=200)


@app.get("/api/automation/health")
async def automation_health_api(request: Request) -> JSONResponse:
    guard = auth_guard(request)
    if guard:
        return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)
    return JSONResponse({"ok": True, "health": load_automation_health()}, status_code=200)


@app.get("/api/context/today")
async def today_context_api(request: Request) -> JSONResponse:
    guard = auth_guard(request)
    if guard:
        return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)
    return JSONResponse({"ok": True, "context": load_context_artifact("today_context")}, status_code=200)


@app.get("/api/actions/catalog")
async def action_catalog_api(request: Request) -> JSONResponse:
    guard = auth_guard(request)
    if guard:
        return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)
    return JSONResponse({"ok": True, "actions": list_actions()}, status_code=200)


@app.post("/api/actions/run")
async def action_run_api(request: Request) -> JSONResponse:
    guard = auth_guard(request)
    if guard:
        return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Payload no valido."}, status_code=400)
    action_name = str(payload.get("action") or "").strip()
    if not action_name:
        return JSONResponse({"ok": False, "error": "Falta la accion."}, status_code=400)
    action_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    result = run_action(action_name, payload=action_payload)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


@app.get("/api/automation/jobs")
async def automation_jobs_api(request: Request) -> JSONResponse:
    guard = auth_guard(request)
    if guard:
        return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)
    return JSONResponse({"ok": True, **automation_jobs_status(load_automation_jobs_state())}, status_code=200)


@app.post("/api/automation/jobs/run")
async def automation_jobs_run_api(request: Request) -> JSONResponse:
    guard = auth_guard(request)
    if guard:
        return JSONResponse({"ok": False, "error": "Sesion no valida."}, status_code=401)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Payload no valido."}, status_code=400)
    job_name = str(payload.get("job") or "").strip()
    force = bool(payload.get("force"))
    run_due = bool(payload.get("run_due"))
    if run_due:
        result = run_due_jobs()
    elif job_name:
        result = run_job(job_name, force=force)
    else:
        return JSONResponse({"ok": False, "error": "Indica un job o activa run_due."}, status_code=400)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


if hasattr(app, "on_event"):
    @app.on_event("startup")
    async def garmin_sync_startup_event() -> None:
        start_garmin_auto_sync()
