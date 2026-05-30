#!/usr/bin/env python3

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def pace_text_to_seconds(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("/km"):
        text = text[:-3]
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return None


def format_pace(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}/km"


def best_split(activities: list[dict[str, Any]], key: str, *, as_of: date, days: int) -> float | None:
    start = as_of - timedelta(days=days - 1)
    values = []
    for item in activities:
        activity_date = item.get("date")
        if not isinstance(activity_date, date):
            continue
        if not (start <= activity_date <= as_of):
            continue
        if item.get(key):
            values.append(float(item[key]))
    return min(values) if values else None


def running_pace_bands(activities: list[dict[str, Any]], zones: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    best_5k = best_split(activities, "fastest_5k_s", as_of=as_of, days=120)
    best_10k = best_split(activities, "fastest_10k_s", as_of=as_of, days=180)
    base_10k_pace = (best_10k / 10.0) if best_10k else pace_text_to_seconds((zones.get("pace") or {}).get("ten_k"))
    base_5k_pace = (best_5k / 5.0) if best_5k else pace_text_to_seconds((zones.get("pace") or {}).get("five_k"))
    if base_10k_pace is None and base_5k_pace is not None:
        base_10k_pace = base_5k_pace + 11.0
    if base_5k_pace is None and base_10k_pace is not None:
        base_5k_pace = max(1.0, base_10k_pace - 7.0)
    threshold_pace = base_10k_pace + 12.0 if base_10k_pace is not None else None
    fartlek_pace = base_10k_pace + 6.0 if base_10k_pace is not None else None
    easy_floor = pace_text_to_seconds((zones.get("pace") or {}).get("easy", "").split("-")[-1])
    return {
        "evidence": {
            "best_5k_s_120d": best_5k,
            "best_10k_s_180d": best_10k,
        },
        "bands": {
            "easy": {"min_s_per_km": base_10k_pace + 95.0 if base_10k_pace is not None else None, "max_s_per_km": easy_floor},
            "fartlek": {"min_s_per_km": fartlek_pace - 8.0 if fartlek_pace is not None else None, "max_s_per_km": fartlek_pace + 8.0 if fartlek_pace is not None else None},
            "tempo": {"min_s_per_km": threshold_pace - 5.0 if threshold_pace is not None else None, "max_s_per_km": threshold_pace + 5.0 if threshold_pace is not None else None},
            "ten_k_specific": {"min_s_per_km": base_10k_pace - 3.0 if base_10k_pace is not None else None, "max_s_per_km": base_10k_pace + 3.0 if base_10k_pace is not None else None},
            "vo2": {"min_s_per_km": base_5k_pace - 4.0 if base_5k_pace is not None else None, "max_s_per_km": base_5k_pace + 4.0 if base_5k_pace is not None else None},
        },
    }


def bike_hr_bands(zones: dict[str, Any]) -> dict[str, Any]:
    heart_rate = zones.get("heart_rate", {}) if isinstance(zones.get("heart_rate"), dict) else {}
    threshold_hr = int(heart_rate.get("threshold_hr") or 191)
    z2_text = str(heart_rate.get("z2") or "145-160")
    try:
        z2_low, z2_high = [int(part) for part in z2_text.split("-")]
    except ValueError:
        z2_low, z2_high = 145, 160
    bike_tempo_low = max(z2_high, threshold_hr - 31)
    bike_tempo_high = threshold_hr - 21
    bike_vo2_low = threshold_hr - 15
    bike_vo2_high = threshold_hr - 5
    return {
        "easy": {"min_bpm": max(110, z2_low - 15), "max_bpm": z2_low - 1},
        "aerobic": {"min_bpm": z2_low, "max_bpm": z2_high},
        "tempo": {"min_bpm": bike_tempo_low, "max_bpm": bike_tempo_high},
        "vo2": {"min_bpm": bike_vo2_low, "max_bpm": bike_vo2_high},
    }


def build_training_paces(activities: list[dict[str, Any]], zones: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    running = running_pace_bands(activities, zones, as_of=as_of)
    bike = bike_hr_bands(zones)
    labels = {
        key: {
            "min": format_pace(value.get("min_s_per_km")),
            "max": format_pace(value.get("max_s_per_km")),
        }
        for key, value in running["bands"].items()
    }
    return {
        "strategy": "progress_from_recent_evidence",
        "running": running,
        "bike": bike,
        "labels": labels,
        "updated_from": running["evidence"],
    }
