#!/usr/bin/env python3

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        year, month, day = [int(part) for part in text.split("-", 2)]
    except (TypeError, ValueError):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def monday_for(day_value: date) -> date:
    return day_value - timedelta(days=day_value.weekday())


def week_key(day_value: date) -> str:
    iso = day_value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def bike_equivalent_km(sport: str, duration_s: float) -> float:
    duration_min = max(0.0, float(duration_s or 0.0)) / 60.0
    if sport == "cycling":
        return duration_min / 3.5
    if sport == "elliptical":
        return duration_min / 5.0
    if sport in {"mobility", "strength"}:
        return duration_min / 12.0
    return 0.0


def normalize_review(review: dict[str, Any]) -> dict[str, Any] | None:
    planned = review.get("planned", {}) if isinstance(review.get("planned"), dict) else {}
    summary = review.get("summary", {}) if isinstance(review.get("summary"), dict) else {}
    review_date = parse_iso_date(planned.get("date") or review.get("date") or review.get("review_date"))
    if review_date is None:
        return None
    sport = str(planned.get("sport") or "running").strip().lower()
    distance_m = float(summary.get("distance_m") or 0.0)
    duration_s = float(summary.get("duration_s") or 0.0)
    risk = str(review.get("risk_level") or "").strip().lower()
    score = int(review.get("score") or 0)
    return {
        "date": review_date,
        "sport": sport,
        "distance_km": distance_m / 1000.0,
        "duration_s": duration_s,
        "equivalent_km": distance_m / 1000.0 if sport in {"running", "trail_running", "race"} else bike_equivalent_km(sport, duration_s),
        "risk_level": risk,
        "score": score,
        "review": review,
    }


def weekly_training_mix(reviews: list[dict[str, Any]], *, until: date | None = None) -> list[dict[str, Any]]:
    grouped: dict[date, dict[str, Any]] = {}
    for raw in reviews:
        item = normalize_review(raw)
        if not item:
            continue
        if until and item["date"] > until:
            continue
        week_start = monday_for(item["date"])
        bucket = grouped.setdefault(
            week_start,
            {
                "week_start": week_start,
                "week_end": week_start + timedelta(days=6),
                "week": week_key(week_start),
                "running_km": 0.0,
                "cycling_minutes": 0.0,
                "elliptical_minutes": 0.0,
                "strength_minutes": 0.0,
                "hybrid_equivalent_km": 0.0,
                "review_count": 0,
                "high_risk_reviews": 0,
                "low_score_reviews": 0,
                "sports": defaultdict(int),
            },
        )
        bucket["review_count"] += 1
        bucket["hybrid_equivalent_km"] += float(item["equivalent_km"])
        bucket["sports"][item["sport"]] += 1
        if item["sport"] in {"running", "trail_running"}:
            bucket["running_km"] += float(item["distance_km"])
        elif item["sport"] == "cycling":
            bucket["cycling_minutes"] += float(item["duration_s"]) / 60.0
        elif item["sport"] == "elliptical":
            bucket["elliptical_minutes"] += float(item["duration_s"]) / 60.0
        else:
            bucket["strength_minutes"] += float(item["duration_s"]) / 60.0
        if item["risk_level"] == "alto":
            bucket["high_risk_reviews"] += 1
        if item["score"] and item["score"] <= 4:
            bucket["low_score_reviews"] += 1
    items = []
    for value in sorted(grouped.values(), key=lambda item: item["week_start"]):
        value["sports"] = dict(value["sports"])
        items.append(value)
    return items


def latest_shin_status(shin_entries: list[dict[str, Any]], *, as_of: date) -> dict[str, Any]:
    latest = None
    latest_date = None
    for item in shin_entries:
        item_date = item.get("date")
        if isinstance(item_date, date):
            current_date = item_date
        else:
            current_date = parse_iso_date(item_date)
        if current_date is None or current_date > as_of:
            continue
        if latest_date is None or current_date >= latest_date:
            latest_date = current_date
            latest = item
    pain_values = []
    if isinstance(latest, dict):
        for key in ("pain_during", "pain_after", "pain_next_morning"):
            if latest.get(key) is not None:
                pain_values.append(int(latest.get(key) or 0))
    pain = max(pain_values) if pain_values else None
    if pain is None or pain <= 2:
        band = "green"
    elif pain == 3:
        band = "yellow"
    else:
        band = "red"
    return {"entry": latest, "max_pain": pain, "band": band}


def absorption_status(week_summary: dict[str, Any], *, shin_band: str, coach_status: str | None = None) -> dict[str, Any]:
    blockers: list[str] = []
    if week_summary.get("high_risk_reviews"):
        blockers.append("high_risk_review")
    if week_summary.get("low_score_reviews"):
        blockers.append("low_score_review")
    if shin_band in {"yellow", "red"}:
        blockers.append(f"shin_{shin_band}")
    if str(coach_status or "") in {"yellow", "red"}:
        blockers.append(f"coach_{coach_status}")
    absorbed = not blockers
    return {
        "absorbed": absorbed,
        "status": "absorbed" if absorbed else "fragile",
        "blockers": blockers,
    }


def last_absorbed_week(reviews: list[dict[str, Any]], shin_entries: list[dict[str, Any]], *, as_of: date, coach_status: str | None = None) -> dict[str, Any] | None:
    weeks = weekly_training_mix(reviews, until=as_of)
    for week in reversed(weeks):
        if week["week_end"] > as_of:
            continue
        shin = latest_shin_status(shin_entries, as_of=week["week_end"])
        status = absorption_status(week, shin_band=shin["band"], coach_status=coach_status)
        if status["absorbed"]:
            return {**week, "absorption": status, "shin": shin}
    return weeks[-1] if weeks else None


def progression_window(reviews: list[dict[str, Any]], shin_entries: list[dict[str, Any]], *, as_of: date, coach_status: str | None = None) -> dict[str, Any]:
    weeks = weekly_training_mix(reviews, until=as_of)
    current = weeks[-1] if weeks else None
    absorbed = last_absorbed_week(reviews, shin_entries, as_of=as_of, coach_status=coach_status)
    shin = latest_shin_status(shin_entries, as_of=as_of)
    baseline_running_km = float((absorbed or {}).get("running_km") or 0.0)
    growth_pct = 8.0
    next_running_km = baseline_running_km * (1.0 + (growth_pct / 100.0)) if baseline_running_km > 0 else 0.0
    blocked_dimensions: list[str] = []
    if shin["band"] != "green":
        blocked_dimensions.extend(["running_volume", "running_intensity"])
    if str(coach_status or "") in {"yellow", "red"}:
        blocked_dimensions.append("running_progression")
    return {
        "current_week": current,
        "last_absorbed_week": absorbed,
        "shin_status": shin,
        "baseline_running_km": round(baseline_running_km, 1),
        "default_running_growth_pct": growth_pct,
        "next_running_target_km": round(next_running_km, 1),
        "next_running_target_range_km": {
            "min": round(next_running_km * 0.95, 1) if next_running_km else 0.0,
            "max": round(next_running_km * 1.05, 1) if next_running_km else 0.0,
        },
        "blocked_dimensions": sorted(set(blocked_dimensions)),
        "keep_bike_support_session": True,
        "fartlek_frequency": "every_7_to_14_days_when_tolerated",
        "status": "hold_or_reduce" if blocked_dimensions else "allow_small_progression",
    }
