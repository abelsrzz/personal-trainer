#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from scripts.notifications.telegram_utils import load_telegram_config, send_text_message
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.notifications.telegram_utils import load_telegram_config, send_text_message


ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "telegram" / "coach_notifications_state.json"
COACH_DECISION_PATH = ROOT / "planning" / "coach_decision.json"
ATHLETE_STATE_PATH = ROOT / "system" / "state" / "athlete_state.json"
REVIEW_ROOT = ROOT / "training" / "completed" / "reviews"


def runtime_today_feed() -> dict[str, Any]:
    try:
        from scripts.system.today_feed import write_today_feed
    except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
        import sys

        sys.path.append(str(Path(__file__).resolve().parents[2]))
        from scripts.system.today_feed import write_today_feed
    return write_today_feed()


def runtime_pre_workout(day: str | None = None) -> dict[str, Any]:
    try:
        from scripts.system.pre_workout_decision import build_pre_workout_decision
    except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
        import sys

        sys.path.append(str(Path(__file__).resolve().parents[2]))
        from scripts.system.pre_workout_decision import build_pre_workout_decision
    return build_pre_workout_decision(day)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram coach briefing and post-workout notifications")
    subparsers = parser.add_subparsers(dest="command", required=True)
    brief = subparsers.add_parser("send-morning-brief", help="Send daily coach briefing")
    brief.add_argument("--force", action="store_true", help="Send even if already sent today")
    post = subparsers.add_parser("send-post-workout", help="Send one post-workout summary")
    post.add_argument("--activity-date", required=True, help="Workout date YYYY-MM-DD")
    post.add_argument("--activity-id", default="", help="Garmin activity id if available")
    post.add_argument("--review-slug", default="", help="Review slug if available")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH)


def save_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


def today_local_date() -> str:
    config = load_telegram_config()
    return datetime.now(ZoneInfo(config.timezone)).date().isoformat()


def build_morning_brief_text() -> str:
    feed = runtime_today_feed()
    pre = runtime_pre_workout(feed.get("today_plan", {}).get("date") if isinstance(feed.get("today_plan"), dict) else None)
    workout = pre.get("workout") if isinstance(pre.get("workout"), dict) else {}
    upcoming = feed.get("upcoming") or []
    lines = [f"Buenos dias. Briefing del entrenador para {pre.get('date')}."]
    if workout:
        lines.append(f"Hoy toca: {workout.get('name') or workout.get('session_kind_label') or workout.get('slug')}")
    else:
        lines.append("Hoy no aparece una sesion obligatoria en el plan.")
    lines.append(pre.get("summary") or "")
    before_training = pre.get("before_training") or []
    if before_training:
        lines.append("Antes de entrenar:")
        lines.extend(f"- {item}" for item in before_training[:2])
    if pre.get("fallback"):
        lines.append(f"Plan B: {pre.get('fallback')}")
    stop_if = pre.get("stop_if") or []
    if stop_if:
        lines.append(f"Cambia o corta si: {stop_if[0]}")
    if upcoming:
        lines.append(f"Despues viene: {(upcoming[0] or {}).get('name') or (upcoming[0] or {}).get('session_kind_label') or 'siguiente sesion'}")
    return "\n".join(line for line in lines if line)


def send_morning_brief(*, force: bool = False) -> dict[str, Any]:
    config = load_telegram_config()
    state = load_state()
    local_day = today_local_date()
    if not force and state.get("last_morning_brief_date") == local_day:
        return {"ok": True, "skipped": True, "message": "Morning brief already sent today."}
    text = build_morning_brief_text()
    response = send_text_message(text, config=config)
    state["last_morning_brief_date"] = local_day
    state["last_morning_brief_at"] = datetime.now(ZoneInfo(config.timezone)).isoformat()
    state["last_morning_brief_text"] = text
    save_state(state)
    return {"ok": True, "message": "Morning brief sent.", "telegram": response, "text": text}


def review_payload(review_slug: str) -> dict[str, Any]:
    if not review_slug:
        return {}
    path = REVIEW_ROOT / f"{review_slug}.analysis.json"
    return load_json(path)


def build_post_workout_text(*, activity_date: str, activity_id: str = "", review_slug: str = "") -> str:
    payload = review_payload(review_slug)
    coach_decision = load_json(COACH_DECISION_PATH)
    decision = coach_decision.get("decision", {}) if isinstance(coach_decision.get("decision"), dict) else {}
    if payload:
        compliance = payload.get("compliance", {}) if isinstance(payload.get("compliance"), dict) else {}
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        lines = [
            f"Sesion detectada del {activity_date}.",
            f"Valoracion: {payload.get('traffic_light') or payload.get('risk_level') or 'revisada'}.",
            f"Cumplimiento: {compliance.get('summary') or compliance.get('status') or 'sin detalle'}.",
        ]
        if summary.get("distance_m"):
            lines.append(f"Carga: {round(float(summary.get('distance_m') or 0.0) / 1000.0, 1)} km en {summary.get('duration') or summary.get('duration_s') or '-'}.")
        if decision.get("recommendation"):
            lines.append(f"Impacto en el plan: {decision.get('recommendation')}")
        return "\n".join(lines)
    lines = [f"Sesion detectada del {activity_date}."]
    if activity_id:
        lines.append(f"Actividad Garmin importada: {activity_id}.")
    lines.append("He actualizado el estado del entrenador, pero esta actividad no genero una review utilizable automatica.")
    if decision.get("recommendation"):
        lines.append(f"Decision actual: {decision.get('recommendation')}")
    return "\n".join(lines)


def send_post_workout_message(*, activity_date: str, activity_id: str = "", review_slug: str = "") -> dict[str, Any]:
    state = load_state()
    message_key = f"{activity_date}:{activity_id or review_slug or 'unknown'}"
    sent_items = state.setdefault("post_workout_notifications", {})
    if sent_items.get(message_key):
        return {"ok": True, "skipped": True, "message": "Post-workout message already sent."}
    text = build_post_workout_text(activity_date=activity_date, activity_id=activity_id, review_slug=review_slug)
    response = send_text_message(text)
    sent_items[message_key] = {"sent_at": datetime.utcnow().isoformat() + "Z", "review_slug": review_slug, "activity_id": activity_id}
    save_state(state)
    return {"ok": True, "message": "Post-workout message sent.", "telegram": response, "text": text}


def main() -> None:
    args = parse_args()
    if args.command == "send-morning-brief":
        payload = send_morning_brief(force=bool(args.force))
    else:
        payload = send_post_workout_message(activity_date=args.activity_date, activity_id=str(args.activity_id or ""), review_slug=str(args.review_slug or ""))
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
