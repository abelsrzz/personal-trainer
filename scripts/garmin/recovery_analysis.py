from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTIVITY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
DEFAULT_DAILY_DIR = ROOT / "training" / "completed" / "imports" / "garmin" / "daily"


def load_optional_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def activity_import_dir(activity_id: Any, activity_dir: Path = DEFAULT_ACTIVITY_DIR) -> Path | None:
    if activity_id in {None, ""}:
        return None
    matches = sorted(activity_dir.glob(f"*_{str(activity_id).strip()}"))
    return matches[0] if matches else None


def activity_summary_payload(activity_id: Any, activity_dir: Path = DEFAULT_ACTIVITY_DIR) -> dict[str, Any]:
    folder = activity_import_dir(activity_id, activity_dir)
    if not folder:
        return {}
    return load_optional_json(folder / "summary.json") or {}


def activity_details_payload(activity_id: Any, activity_dir: Path = DEFAULT_ACTIVITY_DIR) -> dict[str, Any]:
    folder = activity_import_dir(activity_id, activity_dir)
    if not folder:
        return {}
    return load_optional_json(folder / "details.json") or {}


def parse_summary_end_timestamp_ms(summary: dict[str, Any]) -> int | None:
    value = str(summary.get("endTimeGMT") or "").strip()
    if not value:
        return None
    try:
        return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


def finish_sample(summary: dict[str, Any], details: dict[str, Any]) -> tuple[int | None, int | None]:
    descriptors = details.get("metricDescriptors", []) if isinstance(details.get("metricDescriptors"), list) else []
    key_to_index = {
        str(item.get("key") or ""): int(item.get("metricsIndex"))
        for item in descriptors
        if isinstance(item, dict) and item.get("key") is not None and item.get("metricsIndex") is not None
    }
    ts_idx = key_to_index.get("directTimestamp")
    hr_idx = key_to_index.get("directHeartRate")
    if ts_idx is not None and hr_idx is not None:
        rows = details.get("activityDetailMetrics", []) if isinstance(details.get("activityDetailMetrics"), list) else []
        for row in reversed(rows):
            metrics = row.get("metrics", []) if isinstance(row, dict) else []
            if not isinstance(metrics, list):
                continue
            if ts_idx >= len(metrics) or hr_idx >= len(metrics):
                continue
            timestamp = metrics[ts_idx]
            heart_rate = metrics[hr_idx]
            if timestamp is None or heart_rate is None:
                continue
            return int(float(timestamp)), int(round(float(heart_rate)))
    return parse_summary_end_timestamp_ms(summary), int(round(float(summary.get("maxHR") or summary.get("averageHR") or 0.0))) or None


def daily_heart_rate_payload(day: str, daily_dir: Path = DEFAULT_DAILY_DIR) -> dict[str, Any]:
    return load_optional_json(daily_dir / f"{day}.json") or {}


def nearest_sample(samples: list[tuple[int, int]], target_ts: int, max_delta_ms: int) -> tuple[int, int] | None:
    if not samples:
        return None
    sample = min(samples, key=lambda item: abs(item[0] - target_ts))
    return sample if abs(sample[0] - target_ts) <= max_delta_ms else None


def recovery_conclusion(hrr3: int | None, time_to_normal_s: float | None, normal_hr_bpm: int, finish_hr_bpm: int, has_oscillation: bool) -> str:
    if hrr3 is None:
        return "No hay suficientes muestras posteriores para valorar la recuperación de pulso."
    if hrr3 >= 50:
        lead = "Recuperación inicial muy buena"
    elif hrr3 >= 35:
        lead = "Recuperación inicial buena"
    elif hrr3 >= 25:
        lead = "Recuperación inicial aceptable"
    else:
        lead = "Recuperación inicial lenta"
    if time_to_normal_s is None:
        tail = f"La FC bajó con claridad desde {finish_hr_bpm} ppm, pero aún no hay ventana suficiente para confirmar cuándo volvió a una FC normal (<= {normal_hr_bpm} ppm)."
    else:
        minutes = time_to_normal_s / 60.0
        if minutes <= 5:
            tail = f"Volviste a una FC normal personalizada (<= {normal_hr_bpm} ppm) en {minutes:.1f} min."
        elif minutes <= 15:
            tail = f"Volviste a una FC normal personalizada (<= {normal_hr_bpm} ppm) en {minutes:.1f} min, que sigue siendo una respuesta sólida tras el esfuerzo."
        else:
            tail = f"Volviste a una FC normal personalizada (<= {normal_hr_bpm} ppm) en {minutes:.1f} min; la bajada inicial fue buena pero el retorno completo fue más gradual."
    if has_oscillation:
        tail += " La curva posterior oscila, señal de que seguiste caminando o moviéndote tras meta más que quedarte en reposo pasivo."
    return f"{lead}. {tail}"


def build_recovery_analysis(
    review_payload: dict[str, Any],
    *,
    activity_dir: Path = DEFAULT_ACTIVITY_DIR,
    daily_dir: Path = DEFAULT_DAILY_DIR,
    minimum_window_minutes: int = 10,
    chart_window_minutes: int = 30,
) -> dict[str, Any]:
    planned = review_payload.get("planned", {}) if isinstance(review_payload.get("planned"), dict) else {}
    summary_payload = review_payload.get("summary", {}) if isinstance(review_payload.get("summary"), dict) else {}
    activity_id = summary_payload.get("activity_id") or summary_payload.get("activityId")
    day = str(planned.get("date") or "").strip()
    if not activity_id or not day:
        return {"status": "missing_data", "summary": "Faltan identificador de actividad o fecha para calcular la recuperación."}

    activity_summary = activity_summary_payload(activity_id, activity_dir)
    activity_details = activity_details_payload(activity_id, activity_dir)
    finish_ts_ms, finish_hr_bpm = finish_sample(activity_summary, activity_details)
    if finish_ts_ms is None or finish_hr_bpm is None:
        return {"status": "missing_data", "summary": "No se pudo localizar el final real de la actividad en los datos importados."}

    daily_payload = daily_heart_rate_payload(day, daily_dir)
    heart_rates = daily_payload.get("heart_rates", {}) if isinstance(daily_payload.get("heart_rates"), dict) else {}
    values = heart_rates.get("heartRateValues", []) if isinstance(heart_rates.get("heartRateValues"), list) else []
    samples = [
        (int(item[0]), int(item[1]))
        for item in values
        if isinstance(item, list) and len(item) >= 2 and item[0] is not None and item[1] is not None
    ]
    post_samples = [(ts, hr) for ts, hr in samples if ts >= finish_ts_ms]
    minimum_window_ms = minimum_window_minutes * 60 * 1000
    if not post_samples or post_samples[-1][0] < finish_ts_ms + minimum_window_ms:
        return {
            "status": "pending_data",
            "summary": "Aún no hay suficiente ventana de pulso posterior a la actividad para medir la recuperación.",
        }

    resting_hr_bpm = int(round(float(heart_rates.get("restingHeartRate") or 60.0)))
    normal_hr_bpm = min(max(resting_hr_bpm + 75, 120), 140)
    chart_end_ts = min(post_samples[-1][0], finish_ts_ms + chart_window_minutes * 60 * 1000)
    chart_samples = [(ts, hr) for ts, hr in post_samples if ts <= chart_end_ts]
    points = [{"minute": 0.0, "hr": finish_hr_bpm, "label": "0m"}]
    for ts, hr in chart_samples:
        minute = round((ts - finish_ts_ms) / 60000.0, 2)
        if minute <= 0:
            continue
        points.append({"minute": minute, "hr": hr, "label": f"{int(round(minute))}m"})

    hr_values = [point["hr"] for point in points]
    min_hr = min(hr_values)
    max_hr = max(hr_values)
    hr_span = max(1, max_hr - min_hr)
    bars = [
        {
            "minute": point["minute"],
            "label": point["label"],
            "hr": point["hr"],
            "height_pct": round(18 + 82 * ((point["hr"] - min_hr) / hr_span), 1),
        }
        for point in points
    ]

    mark_minutes = [1, 2, 3, 5, 10, 15, 20, 30]
    mark_data: list[dict[str, Any]] = []
    for minute in mark_minutes:
        sample = nearest_sample(post_samples, finish_ts_ms + minute * 60 * 1000, 90 * 1000)
        if not sample:
            continue
        timestamp_ms, hr = sample
        mark_data.append(
            {
                "minute": minute,
                "timestamp_gmt": datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat(),
                "hr": hr,
                "drop": int(finish_hr_bpm - hr),
            }
        )

    marks_by_minute = {item["minute"]: item for item in mark_data}
    time_to_normal = next(((ts - finish_ts_ms) / 1000.0 for ts, hr in post_samples if hr <= normal_hr_bpm), None)
    time_to_140 = next(((ts - finish_ts_ms) / 1000.0 for ts, hr in post_samples if hr <= 140), None)
    has_oscillation = any(
        points[index]["hr"] - points[index - 1]["hr"] >= 8
        for index in range(1, len(points))
        if points[index]["minute"] >= 5
    )
    hrr1 = marks_by_minute.get(1, {}).get("drop")
    hrr3 = marks_by_minute.get(3, {}).get("drop")
    hrr5 = marks_by_minute.get(5, {}).get("drop")
    conclusion = recovery_conclusion(hrr3, time_to_normal, normal_hr_bpm, finish_hr_bpm, has_oscillation)

    return {
        "status": "complete",
        "resting_hr_bpm": resting_hr_bpm,
        "normal_hr_bpm": normal_hr_bpm,
        "finish_hr_bpm": finish_hr_bpm,
        "finish_timestamp_gmt": datetime.fromtimestamp(finish_ts_ms / 1000, tz=timezone.utc).isoformat(),
        "time_to_normal_s": time_to_normal,
        "time_to_140_s": time_to_140,
        "hrr_1min_bpm": hrr1,
        "hrr_3min_bpm": hrr3,
        "hrr_5min_bpm": hrr5,
        "marks": mark_data,
        "chart": {
            "points": points,
            "bars": bars,
            "min_hr": min_hr,
            "max_hr": max_hr,
        },
        "summary": conclusion,
    }
