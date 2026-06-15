#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


try:
    from scripts.web_v2 import legacy_support as portal_core
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.web_v2 import legacy_support as portal_core


ROOT = Path(__file__).resolve().parents[2]
TODAY_FEED_PATH = ROOT / "system" / "state" / "today_feed.json"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


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
    if not isinstance(workout, dict):
        return None
    return {
        **workout,
        "detail_url": f"/planned-workouts/{workout.get('slug') or ''}",
        "day_url": f"/calendar/day/{day or ''}",
    }


def build_today_feed() -> dict[str, Any]:
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
    decision = payload.get("dashboard", {}).get("decision", {}) if isinstance(payload.get("dashboard"), dict) else {}
    progression = decision.get("progression", {}) if isinstance(decision.get("progression"), dict) else {}
    training_paces = payload.get("dashboard", {}).get("training_paces", {}) if isinstance(payload.get("dashboard"), dict) else {}
    feed = {
        "generated_at": utcnow_iso(),
        "workspace": payload.get("workspace"),
        "dashboard": payload.get("dashboard"),
        "active_cycle": payload.get("active_cycle"),
        "today_plan": today_plan,
        "today_workout": workout,
        "today_review": review,
        "today_workouts": workouts,
        "today_reviews": reviews,
        "today_fueling": [],
        "progression": progression,
        "training_paces": training_paces,
        "upcoming": [
            {
                **item,
                "detail_url": f"/planned-workouts/{item.get('slug') or ''}",
            }
            for item in payload.get("upcoming", [])[:4]
            if isinstance(item, dict)
        ],
        "recent_reviews": [item for item in [compact_today_review(review_item) for review_item in payload.get("recent_reviews", [])[:3]] if item],
        "active_nav": "hoy",
    }
    return feed


def write_today_feed() -> dict[str, Any]:
    payload = build_today_feed()
    write_json(TODAY_FEED_PATH, payload)
    return payload


def load_today_feed(*, build_if_missing: bool = True) -> dict[str, Any]:
    if TODAY_FEED_PATH.exists():
        try:
            payload = json.loads(TODAY_FEED_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                cached_date = str(
                    (payload.get("today_plan") or {}).get("date") or ""
                ).strip()
                if cached_date == date.today().isoformat():
                    return payload
        except (json.JSONDecodeError, OSError):
            pass
    if not build_if_missing:
        return {}
    return write_today_feed()


def main() -> None:
    print(json.dumps(write_today_feed(), indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
