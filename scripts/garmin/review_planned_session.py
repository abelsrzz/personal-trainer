#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.garmin.sync_garmin import DEFAULT_WORKOUTS_ROOT, ROOT, load_credentials, login, save_json
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.garmin.sync_garmin import DEFAULT_WORKOUTS_ROOT, ROOT, load_credentials, login, save_json

try:
    from scripts.system.workout_knowledge import match_workout_knowledge
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.workout_knowledge import match_workout_knowledge


DEFAULT_IMPORT_ROOT = ROOT / "training" / "completed" / "imports" / "garmin"
DEFAULT_ACTIVITY_ROOT = ROOT / "training" / "completed" / "activities"
DEFAULT_REVIEW_ROOT = ROOT / "training" / "completed" / "reviews"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Garmin workout and generate planned-vs-completed review")
    parser.add_argument("--date", default=date.today().isoformat(), help="Workout date to review, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=3, help="How many days back to inspect in Garmin")
    parser.add_argument("--limit", type=int, default=10, help="Maximum Garmin activities to inspect")
    parser.add_argument(
        "--credentials",
        type=Path,
        default=ROOT / "garmin" / "local_credentials.yaml",
        help="Path to local Garmin credentials YAML",
    )
    parser.add_argument("--activity-id", type=int, default=None, help="Specific Garmin activity ID to review")
    parser.add_argument("--use-local-imports-only", action="store_true", help="Do not contact Garmin; use already imported local activity files only")
    parser.add_argument("--force", action="store_true", help="Regenerate outputs even if review already exists")
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def find_planned_workout(day: str) -> Path:
    matches = sorted(DEFAULT_WORKOUTS_ROOT.glob(f"{day}_*.yaml"))
    if not matches:
        raise FileNotFoundError(f"No planned workout found for {day} in {DEFAULT_WORKOUTS_ROOT}")
    if len(matches) > 1:
        running_matches = [path for path in matches if load_yaml(path).get("workout", {}).get("sport") == "running"]
        if len(running_matches) == 1:
            return running_matches[0]
        raise ValueError(f"Multiple planned workouts found for {day}; disambiguation not implemented")
    return matches[0]


def import_recent_running_activities(day: str, credentials_path: Path, days: int, limit: int) -> list[dict[str, Any]]:
    credentials = load_credentials(credentials_path)
    client = login(credentials)
    activities = client.get_activities(0, limit)
    imported: list[dict[str, Any]] = []
    for activity in activities:
        activity_type = activity.get("activityType", {}).get("typeKey")
        start_local = str(activity.get("startTimeLocal", "")).split(" ")[0]
        if activity_type != "running" or start_local < day:
            continue
        activity_id = activity.get("activityId")
        activity_dir = DEFAULT_IMPORT_ROOT / "activities" / f"{start_local}_{activity_id}"
        activity_dir.mkdir(parents=True, exist_ok=True)
        save_json(activity_dir / "summary.json", activity)
        save_json(activity_dir / "details.json", client.get_activity_details(activity_id))
        imported.append(activity)
    if not imported:
        raise FileNotFoundError(f"No Garmin running activities found for {day}")
    return imported


def select_activity(activities: list[dict[str, Any]], planned: dict[str, Any], day: str) -> dict[str, Any]:
    same_day = [a for a in activities if str(a.get("startTimeLocal", "")).split(" ")[0] == day]
    if not same_day:
        raise FileNotFoundError(f"No Garmin activity on {day}")
    planned_distance = planned_distance_m(planned)
    if planned_distance is None:
        return sorted(same_day, key=lambda item: item.get("startTimeLocal", ""))[0]
    return min(same_day, key=lambda item: abs(float(item.get("distance") or 0.0) - planned_distance))


def load_local_running_activities(day: str) -> list[dict[str, Any]]:
    imported: list[dict[str, Any]] = []
    for path in sorted(DEFAULT_IMPORT_ROOT.glob(f"activities/{day}_*/summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("activityType", {}).get("typeKey") != "running":
            continue
        imported.append(payload)
    if not imported:
        raise FileNotFoundError(f"No local Garmin running activities found for {day}")
    return imported


def select_activity_by_id(activities: list[dict[str, Any]], activity_id: int) -> dict[str, Any]:
    match = next((item for item in activities if int(item.get("activityId") or 0) == activity_id), None)
    if match is None:
        raise FileNotFoundError(f"No Garmin activity with id {activity_id} available for review")
    return match


def flatten_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for step in steps:
        if step.get("type") == "repeat_group":
            nested = flatten_steps(step.get("steps", []))
            for _ in range(int(step.get("iterations", 0) or 0)):
                flat.extend(nested)
            continue
        flat.append(step)
    return flat


def planned_distance_m(workout: dict[str, Any]) -> float | None:
    total = 0.0
    found = False
    for step in flatten_steps(workout.get("workout", {}).get("steps", [])):
        if step.get("distance_m") is not None:
            total += float(step["distance_m"])
            found = True
    return total if found else None


def planned_primary_hr_range(workout: dict[str, Any]) -> tuple[float | None, float | None]:
    mins: list[float] = []
    maxs: list[float] = []
    for step in flatten_steps(workout.get("workout", {}).get("steps", [])):
        target = step.get("target") or {}
        if target.get("type") == "heart_rate_range":
            if target.get("min_bpm") is not None:
                mins.append(float(target["min_bpm"]))
            if target.get("max_bpm") is not None:
                maxs.append(float(target["max_bpm"]))
    return (min(mins) if mins else None, max(maxs) if maxs else None)


def planned_goal_category(workout: dict[str, Any]) -> str:
    workout_data = workout.get("workout", {})
    name = str(workout_data.get("name") or "").lower()
    description = str(workout_data.get("description") or "").lower()
    steps = flatten_steps(workout.get("workout", {}).get("steps", []))
    text = f"{name} {description}"
    has_pace = any((step.get("target") or {}).get("type") == "pace_range" for step in steps)
    has_rectas = "recta" in text or "strides" in text
    has_warmup_cooldown = any(step.get("step_type") in {"warmup", "cooldown"} for step in steps)
    distance_m = planned_distance_m(workout) or 0.0

    if "reintroduccion" in text:
        return "reintroduction_easy"
    if "recuperacion" in text:
        return "recovery_easy"
    if "activacion" in text:
        return "activation"
    if "tirada larga" in text or distance_m >= 10000:
        return "long_run"
    if "continuidad" in text:
        return "steady_easy"
    if has_rectas:
        return "easy_plus_strides"
    if has_pace and has_warmup_cooldown:
        return "controlled_quality"
    if has_pace:
        return "quality"
    if "facil" in text or "suave" in text or "z2" in text:
        return "easy_aerobic"
    return "general_run"


def planned_session_kind(workout: dict[str, Any]) -> str:
    goal_category = planned_goal_category(workout)
    if goal_category in {"reintroduction_easy", "recovery_easy"}:
        return "recovery"
    if goal_category in {"long_run"}:
        return "long_run"
    if goal_category in {"activation", "easy_plus_strides", "controlled_quality", "quality"}:
        return "quality"
    if "strength" in json.dumps(workout, ensure_ascii=False).lower():
        return "strength"
    return "easy"


def planned_knowledge_summary(workout: dict[str, Any]) -> dict[str, Any] | None:
    workout_data = workout.get("workout", {}) if isinstance(workout.get("workout"), dict) else {}
    session_kind = planned_session_kind(workout)
    return match_workout_knowledge(workout_data, session_kind, template_id=str(workout_data.get("template_id") or "").strip() or None)


def actual_stimulus_summary(summary: dict[str, Any]) -> list[str]:
    goals: list[str] = []
    te_label = str(summary.get("trainingEffectLabel") or "").lower()
    aerobic_te = float(summary.get("aerobicTrainingEffect") or 0.0)
    anaerobic_te = float(summary.get("anaerobicTrainingEffect") or 0.0)
    pace_s = float(summary.get("duration") or 0.0) / (float(summary.get("distance") or 1.0) / 1000.0) if float(summary.get("distance") or 0.0) > 0 else None
    distance_km = float(summary.get("distance") or 0.0) / 1000.0
    if distance_km >= 14:
        goals.append("fondo_largo")
    if aerobic_te >= 3.8:
        goals.append("vo2max")
    elif aerobic_te >= 2.8:
        goals.append("umbral_lactico")
    elif aerobic_te >= 1.5:
        goals.append("base_aerobica")
    if anaerobic_te >= 1.0:
        goals.append("capacidad_anaerobica")
    if any(keyword in te_label for keyword in ["tempo", "threshold"]):
        goals.append("umbral_lactico")
    if any(keyword in te_label for keyword in ["anaerobic", "sprint"]):
        goals.append("tolerancia_al_lactato")
    if pace_s is not None and pace_s <= 255:
        goals.append("ritmo_5k")
    elif pace_s is not None and pace_s <= 285:
        goals.append("ritmo_10k")
    return list(dict.fromkeys(goals))


def planned_vs_actual_stimulus(workout: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    planned_knowledge = planned_knowledge_summary(workout)
    planned_goals = planned_knowledge.get("goals") if isinstance(planned_knowledge, dict) else []
    actual_goals = actual_stimulus_summary(summary)
    overlap = [goal for goal in actual_goals if goal in planned_goals]
    alignment = "aligned" if overlap else ("unknown" if not planned_goals or not actual_goals else "drifted")
    summary_text = "No hay suficientes datos para comparar el estimulo real con el objetivo previsto."
    if alignment == "aligned":
        summary_text = f"El estimulo real parece alineado con el objetivo previsto: {', '.join(overlap[:3])}."
    elif alignment == "drifted":
        summary_text = f"El estimulo real se desvia del objetivo previsto. Previsto: {', '.join(planned_goals[:3])}. Real observado: {', '.join(actual_goals[:3])}."
    return {
        "planned_knowledge": planned_knowledge,
        "actual_goals": actual_goals,
        "overlap": overlap,
        "alignment": alignment,
        "summary": summary_text,
    }


def parse_duration_text(value: str | None) -> float | None:
    if not value:
        return None
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return None


def metric_rows(details: dict[str, Any]) -> list[dict[str, float | None]]:
    descriptors = {item["metricsIndex"]: item["key"] for item in details["metricDescriptors"]}
    rows: list[dict[str, float | None]] = []
    for item in details["activityDetailMetrics"]:
        metrics = item["metrics"]
        row = {descriptors[index]: metrics[index] if index < len(metrics) else None for index in descriptors}
        if row.get("sumDistance") is None or row.get("sumDuration") is None:
            continue
        rows.append(row)
    return rows


def segment_rows(rows: list[dict[str, float | None]]) -> list[dict[str, float | None]]:
    segments: list[dict[str, float | None]] = []
    for current, nxt in zip(rows, rows[1:]):
        dt = float(nxt["sumDuration"]) - float(current["sumDuration"])
        dd = float(nxt["sumDistance"]) - float(current["sumDistance"])
        if dt <= 0:
            continue
        segment: dict[str, float | None] = {"dt": dt, "dd": dd}
        for key in [
            "directHeartRate",
            "directSpeed",
            "directRunCadence",
            "directPower",
            "directGroundContactTime",
            "directVerticalOscillation",
            "directVerticalRatio",
            "directStrideLength",
            "directAirTemperature",
            "directElevation",
            "directGradeAdjustedSpeed",
        ]:
            values = [value for value in (current.get(key), nxt.get(key)) if value is not None]
            segment[key] = sum(values) / len(values) if values else None
        segments.append(segment)
    return segments


def weighted_average(segments: list[dict[str, float | None]], key: str, weight_key: str = "dt") -> float | None:
    weighted_sum = 0.0
    total = 0.0
    for segment in segments:
        value = segment.get(key)
        weight = segment.get(weight_key)
        if value is None or weight is None or weight <= 0:
            continue
        weighted_sum += float(value) * float(weight)
        total += float(weight)
    return weighted_sum / total if total else None


def weighted_std(segments: list[dict[str, float | None]], key: str, weight_key: str = "dt") -> float | None:
    average = weighted_average(segments, key, weight_key)
    if average is None:
        return None
    total = 0.0
    variance = 0.0
    for segment in segments:
        value = segment.get(key)
        weight = segment.get(weight_key)
        if value is None or weight is None or weight <= 0:
            continue
        variance += float(weight) * (float(value) - average) ** 2
        total += float(weight)
    return math.sqrt(variance / total) if total else None


def pace_from_speed(speed_mps: float | None) -> float | None:
    if speed_mps is None or speed_mps <= 0:
        return None
    return 1000.0 / speed_mps


def format_pace(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    minutes = int(seconds // 60)
    secs = int(round(seconds - minutes * 60))
    if secs == 60:
        minutes += 1
        secs = 0
    return f"{minutes}:{secs:02d}/km"


def format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def load_historical_reviews(current_activity_id: int) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for path in sorted(DEFAULT_REVIEW_ROOT.glob("*.analysis.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("summary", {}).get("activity_id") or 0) == current_activity_id:
            continue
        reviews.append(payload)
    return reviews


def comparable_session(candidate: dict[str, Any], planned: dict[str, Any], summary: dict[str, Any]) -> bool:
    if candidate.get("planned", {}).get("sport") != planned.get("sport"):
        return False
    candidate_knowledge_id = str(candidate.get("planned", {}).get("knowledge_id") or "").strip()
    planned_knowledge_id = str(planned.get("knowledge_id") or "").strip()
    if candidate_knowledge_id and planned_knowledge_id:
        if candidate_knowledge_id != planned_knowledge_id:
            return False
    else:
        candidate_goal = candidate.get("planned", {}).get("goal_category")
        planned_goal = planned.get("goal_category")
        goal_groups = {
            "easy_family": {"reintroduction_easy", "recovery_easy", "easy_aerobic", "steady_easy", "general_run"},
            "strides_family": {"easy_plus_strides", "activation"},
            "quality_family": {"controlled_quality", "quality"},
        }
        same_goal = candidate_goal == planned_goal
        same_family = any(candidate_goal in family and planned_goal in family for family in goal_groups.values())
        if not same_goal and not same_family:
            return False
    candidate_distance = candidate.get("planned", {}).get("distance_m")
    planned_distance = planned.get("distance_m")
    if candidate_distance is None or planned_distance is None:
        return False
    if abs(float(candidate_distance) - float(planned_distance)) > max(1000.0, float(planned_distance) * 0.2):
        return False
    candidate_gain = candidate.get("summary", {}).get("elevation_gain_m")
    current_gain = summary.get("elevation_gain_m")
    if candidate_gain is None or current_gain is None:
        return True
    return abs(float(candidate_gain) - float(current_gain)) <= max(20.0, float(current_gain) * 0.75)


def progression_label(delta_pace_s: float | None, delta_hr: float | None) -> tuple[str, str]:
    if delta_pace_s is None or delta_hr is None:
        return ("neutral", "No hay suficientes datos para valorar progresion de forma fiable.")
    if delta_pace_s <= -8 and delta_hr <= 2:
        return ("progress", "Ritmo mas rapido con pulso similar o mejor controlado frente a sesiones comparables.")
    if delta_hr <= -3 and delta_pace_s <= 5:
        return ("progress", "Pulso mas bajo a un ritmo parecido, senal positiva de eficiencia aerobica.")
    if delta_pace_s >= 8 and delta_hr >= 3:
        return ("regression", "Ritmo peor con pulso mas alto frente a sesiones comparables, senal de regresion o fatiga contextual.")
    if delta_pace_s >= 12 and delta_hr >= 0:
        return ("regression", "Ritmo claramente peor sin mejora cardiaca apreciable frente a referencias similares.")
    return ("neutral", "Cambios pequenos o ambiguos frente a sesiones comparables; no hay una senal clara de progresion o regresion.")


def progression_analysis(review: dict[str, Any]) -> dict[str, Any]:
    history = load_historical_reviews(int(review["summary"]["activity_id"]))
    comparables = [item for item in history if comparable_session(item, review["planned"], review["summary"])]
    comparables.sort(key=lambda item: item.get("planned", {}).get("date", ""), reverse=True)
    recent = comparables[:3]
    if not recent:
        return {
            "comparable_count": 0,
            "matches": [],
            "trend": "insufficient_data",
            "summary": "Aun no hay sesiones comparables previas para medir progresion o regresion.",
        }

    pace_values = [float(item["summary"]["pace_s_per_km"]) for item in recent if item.get("summary", {}).get("pace_s_per_km") is not None]
    hr_values = [float(item["summary"]["avg_hr"]) for item in recent if item.get("summary", {}).get("avg_hr") is not None]
    current_pace = float(review["summary"]["pace_s_per_km"])
    current_hr = float(review["summary"]["avg_hr"])
    baseline_pace = sum(pace_values) / len(pace_values) if pace_values else None
    baseline_hr = sum(hr_values) / len(hr_values) if hr_values else None
    delta_pace = current_pace - baseline_pace if baseline_pace is not None else None
    delta_hr = current_hr - baseline_hr if baseline_hr is not None else None
    trend, text = progression_label(delta_pace, delta_hr)
    matches = []
    for item in recent:
        matches.append(
            {
                "date": item["planned"]["date"],
                "name": item["planned"]["name"],
                "goal_category": item["planned"].get("goal_category"),
                "distance_m": item["summary"].get("distance_m"),
                "elevation_gain_m": item["summary"].get("elevation_gain_m"),
                "pace_s_per_km": item["summary"].get("pace_s_per_km"),
                "avg_hr": item["summary"].get("avg_hr"),
                "avg_power_w": item["summary"].get("avg_power_w"),
                "decoupling_pct": item.get("halves", {}).get("decoupling_pct"),
            }
        )
    return {
        "comparable_count": len(comparables),
        "matches": matches,
        "baseline": {
            "pace_s_per_km": baseline_pace,
            "avg_hr": baseline_hr,
        },
        "delta_vs_baseline": {
            "pace_s_per_km": delta_pace,
            "avg_hr": delta_hr,
        },
        "trend": trend,
        "summary": text,
    }


def split_metrics(segments: list[dict[str, float | None]], split_distance_m: float, total_distance_m: float, total_duration_s: float) -> list[dict[str, Any]]:
    splits: list[dict[str, Any]] = []
    markers: list[float] = []
    marker = split_distance_m
    while marker <= total_distance_m:
        markers.append(marker)
        marker += split_distance_m
    previous_distance = 0.0
    previous_time = 0.0
    cumulative_distance = 0.0
    cumulative_time = 0.0
    segment_index = 0
    for marker in markers:
        while segment_index < len(segments) and cumulative_distance + float(segments[segment_index]["dd"] or 0.0) < marker:
            cumulative_distance += float(segments[segment_index]["dd"] or 0.0)
            cumulative_time += float(segments[segment_index]["dt"] or 0.0)
            segment_index += 1
        if segment_index >= len(segments):
            break
        segment = segments[segment_index]
        fraction = 0.0
        if segment["dd"]:
            fraction = (marker - cumulative_distance) / float(segment["dd"])
        time_at_marker = cumulative_time + float(segment["dt"] or 0.0) * fraction
        splits.append(build_split(segments, previous_distance, marker, time_at_marker - previous_time, label=str(int(marker / 1000))))
        previous_distance = marker
        previous_time = time_at_marker
    if total_distance_m > previous_distance:
        splits.append(build_split(segments, previous_distance, total_distance_m, total_duration_s - previous_time, label=f"{(total_distance_m - previous_distance) / 1000:.2f}"))
    return splits


def build_split(segments: list[dict[str, float | None]], start_distance: float, end_distance: float, split_time_s: float, label: str) -> dict[str, Any]:
    bucket: dict[str, list[tuple[float, float]]] = {
        "directHeartRate": [],
        "directRunCadence": [],
        "directPower": [],
        "directGroundContactTime": [],
        "directVerticalOscillation": [],
        "directVerticalRatio": [],
        "directStrideLength": [],
        "directAirTemperature": [],
        "directElevation": [],
        "directGradeAdjustedSpeed": [],
    }
    cumulative_distance = 0.0
    for segment in segments:
        next_distance = cumulative_distance + float(segment["dd"] or 0.0)
        left = max(start_distance, cumulative_distance)
        right = min(end_distance, next_distance)
        if right > left and float(segment["dd"] or 0.0) > 0:
            fraction = (right - left) / float(segment["dd"])
            sample_time = float(segment["dt"] or 0.0) * fraction
            for key in bucket:
                value = segment.get(key)
                if value is not None:
                    bucket[key].append((float(value), sample_time))
        cumulative_distance = next_distance
        if cumulative_distance >= end_distance:
            break
    split_distance = end_distance - start_distance
    return {
        "label": label,
        "distance_m": split_distance,
        "duration_s": split_time_s,
        "pace_s_per_km": split_time_s * 1000.0 / split_distance if split_distance else None,
        "avg_hr": weighted_bucket(bucket["directHeartRate"]),
        "avg_cadence_spm": weighted_bucket(bucket["directRunCadence"]),
        "avg_power_w": weighted_bucket(bucket["directPower"]),
        "avg_gct_ms": weighted_bucket(bucket["directGroundContactTime"]),
        "avg_vo_cm": weighted_bucket(bucket["directVerticalOscillation"]),
        "avg_vr": weighted_bucket(bucket["directVerticalRatio"]),
        "avg_stride_cm": weighted_bucket(bucket["directStrideLength"]),
        "avg_temp_c": weighted_bucket(bucket["directAirTemperature"]),
        "avg_elevation_m": weighted_bucket(bucket["directElevation"]),
        "avg_gap_pace_s_per_km": pace_from_speed(weighted_bucket(bucket["directGradeAdjustedSpeed"])),
    }


def weighted_bucket(bucket: list[tuple[float, float]]) -> float | None:
    total = sum(weight for _, weight in bucket)
    if not total:
        return None
    return sum(value * weight for value, weight in bucket) / total


def split_halves(segments: list[dict[str, float | None]], total_distance_m: float) -> tuple[list[dict[str, float | None]], list[dict[str, float | None]]]:
    half_distance = total_distance_m / 2.0
    first_half: list[dict[str, float | None]] = []
    second_half: list[dict[str, float | None]] = []
    cumulative_distance = 0.0
    for segment in segments:
        segment_distance = float(segment["dd"] or 0.0)
        next_distance = cumulative_distance + segment_distance
        if next_distance <= half_distance:
            first_half.append(segment)
        elif cumulative_distance >= half_distance:
            second_half.append(segment)
        elif segment_distance > 0:
            first_fraction = (half_distance - cumulative_distance) / segment_distance
            second_fraction = 1.0 - first_fraction
            first_segment = segment.copy()
            first_segment["dd"] = segment_distance * first_fraction
            first_segment["dt"] = float(segment["dt"] or 0.0) * first_fraction
            second_segment = segment.copy()
            second_segment["dd"] = segment_distance * second_fraction
            second_segment["dt"] = float(segment["dt"] or 0.0) * second_fraction
            first_half.append(first_segment)
            second_half.append(second_segment)
        cumulative_distance = next_distance
    return first_half, second_half


def traffic_light(score: int) -> str:
    if score >= 8:
        return "verde"
    if score >= 5:
        return "amarillo"
    return "rojo"


def risk_level(score: int, above_zone_pct: float, decoupling_pct: float | None) -> str:
    if score >= 8 and above_zone_pct < 20 and (decoupling_pct is None or decoupling_pct < 5):
        return "bajo"
    if score >= 5 and above_zone_pct < 60 and (decoupling_pct is None or decoupling_pct < 10):
        return "medio"
    return "alto"


def score_session(distance_diff_m: float, above_zone_pct: float, decoupling_pct: float | None) -> int:
    score = 8
    if abs(distance_diff_m) > 800:
        score -= 2
    elif abs(distance_diff_m) > 400:
        score -= 1
    if above_zone_pct > 70:
        score -= 3
    elif above_zone_pct > 50:
        score -= 2
    elif above_zone_pct > 35:
        score -= 1
    if decoupling_pct is not None and decoupling_pct > 12:
        score -= 2
    elif decoupling_pct is not None and decoupling_pct > 8:
        score -= 1
    return max(1, min(10, score))


def analyze_workout(planned: dict[str, Any], summary: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    rows = metric_rows(details)
    segments = segment_rows(rows)
    planned_distance = planned_distance_m(planned)
    planned_hr_min, planned_hr_max = planned_primary_hr_range(planned)
    actual_distance = float(summary["distance"])
    actual_duration = float(summary["duration"])

    time_in_zone = 0.0
    time_below_zone = 0.0
    time_above_zone = 0.0
    time_to_enter_zone: float | None = None
    distance_to_enter_zone: float | None = None
    elapsed_time = 0.0
    elapsed_distance = 0.0
    for segment in segments:
        elapsed_time += float(segment["dt"] or 0.0)
        elapsed_distance += float(segment["dd"] or 0.0)
        heart_rate = segment.get("directHeartRate")
        if heart_rate is None or planned_hr_min is None or planned_hr_max is None:
            continue
        if planned_hr_min <= float(heart_rate) <= planned_hr_max:
            time_in_zone += float(segment["dt"] or 0.0)
            if time_to_enter_zone is None:
                time_to_enter_zone = elapsed_time
                distance_to_enter_zone = elapsed_distance
        elif float(heart_rate) < planned_hr_min:
            time_below_zone += float(segment["dt"] or 0.0)
        else:
            time_above_zone += float(segment["dt"] or 0.0)

    first_half, second_half = split_halves(segments, actual_distance)
    first_half_speed = weighted_average(first_half, "directSpeed")
    second_half_speed = weighted_average(second_half, "directSpeed")
    first_half_hr = weighted_average(first_half, "directHeartRate")
    second_half_hr = weighted_average(second_half, "directHeartRate")
    first_half_power = weighted_average(first_half, "directPower")
    second_half_power = weighted_average(second_half, "directPower")
    first_half_pace = pace_from_speed(first_half_speed)
    second_half_pace = pace_from_speed(second_half_speed)
    efficiency_first = first_half_speed / first_half_hr if first_half_speed and first_half_hr else None
    efficiency_second = second_half_speed / second_half_hr if second_half_speed and second_half_hr else None
    decoupling = None
    if all(value is not None for value in [first_half_hr, second_half_hr, first_half_pace, second_half_pace]):
        decoupling = ((second_half_hr / first_half_hr) / (second_half_pace / first_half_pace) - 1.0) * 100.0

    pace_std = None
    speed_std = weighted_std(segments, "directSpeed")
    avg_speed = weighted_average(segments, "directSpeed")
    if speed_std is not None and avg_speed:
        pace_std = (1000.0 / (avg_speed ** 2)) * speed_std

    compliance = {
        "distance_diff_m": actual_distance - planned_distance if planned_distance is not None else None,
        "duration_diff_s_vs_est": actual_duration - float(planned["workout"].get("estimated_duration_s") or 0.0),
        "time_in_hr_zone_s": time_in_zone,
        "time_below_hr_zone_s": time_below_zone,
        "time_above_hr_zone_s": time_above_zone,
        "pct_in_hr_zone": (time_in_zone / actual_duration) * 100.0 if actual_duration else None,
        "pct_below_hr_zone": (time_below_zone / actual_duration) * 100.0 if actual_duration else None,
        "pct_above_hr_zone": (time_above_zone / actual_duration) * 100.0 if actual_duration else None,
        "time_to_enter_zone_s": time_to_enter_zone,
        "distance_to_enter_zone_m": distance_to_enter_zone,
    }
    score = score_session(
        float(compliance["distance_diff_m"] or 0.0),
        float(compliance["pct_above_hr_zone"] or 0.0),
        decoupling,
    )

    review = {
        "planned": {
            "name": planned["workout"]["name"],
            "date": planned["workout"]["schedule_date"],
            "sport": planned["workout"].get("sport"),
            "goal_category": planned_goal_category(planned),
            "template_id": planned["workout"].get("template_id"),
            "knowledge_id": (planned_knowledge_summary(planned) or {}).get("id") or planned["workout"].get("knowledge_id"),
            "knowledge_label": planned["workout"].get("knowledge_label"),
            "primary_goal": planned["workout"].get("primary_goal"),
            "description": planned["workout"].get("description"),
            "estimated_duration_s": planned["workout"].get("estimated_duration_s"),
            "distance_m": planned_distance,
            "primary_hr_min": planned_hr_min,
            "primary_hr_max": planned_hr_max,
        },
        "summary": {
            "activity_id": summary["activityId"],
            "activity_name": summary["activityName"],
            "start_time_local": summary["startTimeLocal"],
            "distance_m": actual_distance,
            "duration_s": actual_duration,
            "elapsed_s": summary.get("elapsedDuration"),
            "moving_s": summary.get("movingDuration"),
            "pace_s_per_km": actual_duration / (actual_distance / 1000.0) if actual_distance else None,
            "moving_pace_s_per_km": float(summary.get("movingDuration") or 0.0) / (actual_distance / 1000.0) if actual_distance else None,
            "avg_hr": summary.get("averageHR"),
            "max_hr": summary.get("maxHR"),
            "avg_cadence_spm": summary.get("averageRunningCadenceInStepsPerMinute"),
            "max_cadence_spm": summary.get("maxRunningCadenceInStepsPerMinute"),
            "avg_power_w": summary.get("avgPower"),
            "max_power_w": summary.get("maxPower"),
            "elevation_gain_m": summary.get("elevationGain"),
            "elevation_loss_m": summary.get("elevationLoss"),
            "avg_stride_cm": summary.get("avgStrideLength"),
            "avg_gct_ms": summary.get("avgGroundContactTime"),
            "avg_vo_cm": summary.get("avgVerticalOscillation"),
            "avg_vr": summary.get("avgVerticalRatio"),
            "calories": summary.get("calories"),
            "water_estimated_ml": summary.get("waterEstimated"),
            "aerobic_training_effect": summary.get("aerobicTrainingEffect"),
            "anaerobic_training_effect": summary.get("anaerobicTrainingEffect"),
            "training_effect_label": summary.get("trainingEffectLabel"),
            "min_temp_c": summary.get("minTemperature"),
            "max_temp_c": summary.get("maxTemperature"),
            "gap_pace_s_per_km": pace_from_speed(summary.get("avgGradeAdjustedSpeed")),
        },
        "compliance": compliance,
        "stability": {
            "pace_std_s_per_km": pace_std,
            "hr_std_bpm": weighted_std(segments, "directHeartRate"),
            "cadence_std_spm": weighted_std(segments, "directRunCadence"),
            "power_std_w": weighted_std(segments, "directPower"),
        },
        "halves": {
            "first_half_pace_s_per_km": first_half_pace,
            "second_half_pace_s_per_km": second_half_pace,
            "first_half_hr": first_half_hr,
            "second_half_hr": second_half_hr,
            "first_half_power_w": first_half_power,
            "second_half_power_w": second_half_power,
            "efficiency_first": efficiency_first,
            "efficiency_second": efficiency_second,
            "efficiency_change_pct": ((efficiency_second / efficiency_first) - 1.0) * 100.0 if efficiency_first and efficiency_second else None,
            "decoupling_pct": decoupling,
        },
        "splits": split_metrics(segments, 1000.0, actual_distance, actual_duration),
        "score": score,
        "traffic_light": traffic_light(score),
        "risk_level": risk_level(score, float(compliance["pct_above_hr_zone"] or 0.0), decoupling),
    }
    review["stimulus_alignment"] = planned_vs_actual_stimulus(planned, summary)
    review["progression"] = progression_analysis(review)
    return review


def activity_record(review: dict[str, Any], planned_reference: str) -> dict[str, Any]:
    summary = review["summary"]
    return {
        "activity": {
            "id": f"garmin-{summary['activity_id']}",
            "source": "garmin",
            "garmin_activity_id": summary["activity_id"],
            "date": review["planned"]["date"],
            "title": summary["activity_name"],
            "type": "run",
            "planned_session_reference": planned_reference,
            "distance_km": round(float(summary["distance_m"]) / 1000.0, 3),
            "duration": format_duration(summary["duration_s"]),
            "elevation_gain_m": summary["elevation_gain_m"],
            "avg_pace": format_pace(summary["pace_s_per_km"]),
            "avg_hr": summary["avg_hr"],
            "max_hr": summary["max_hr"],
            "shoes": None,
            "notes": f"Autoimported from Garmin on {datetime.now().isoformat(timespec='seconds')}",
        }
    }


def coaching_text(review: dict[str, Any]) -> tuple[str, str, str, str]:
    planned = review["planned"]
    summary = review["summary"]
    compliance = review["compliance"]
    halves = review["halves"]
    goal = planned.get("description") or planned["name"]
    if halves["decoupling_pct"] is None:
        good = "Se completo la distancia prevista con estabilidad mecanica y sin senales de fatiga clara."
    elif halves["decoupling_pct"] < 5:
        good = f"Se completo la sesion con estabilidad mecanica y una deriva cardiaca baja ({halves['decoupling_pct']:.1f}%)."
    elif halves["decoupling_pct"] < 9:
        good = f"La sesion mantuvo una tecnica estable y una deriva cardiaca moderada ({halves['decoupling_pct']:.1f}%), asumible si las sensaciones fueron buenas."
    else:
        good = f"Se sostuvo bien la tecnica, pero la deriva cardiaca ya fue apreciable ({halves['decoupling_pct']:.1f}%)."
    missed = ""
    if compliance["pct_above_hr_zone"] and compliance["pct_above_hr_zone"] > 50:
        missed = f"La intensidad quedo claramente por encima de lo prescrito: {compliance['pct_above_hr_zone']:.1f}% del tiempo estuvo sobre el techo de FC objetivo."
    elif compliance["pct_above_hr_zone"] and compliance["pct_above_hr_zone"] > 30:
        missed = f"La intensidad se fue algo por encima de lo ideal en varios tramos ({compliance['pct_above_hr_zone']:.1f}% del tiempo sobre el techo de FC), pero no implica por si sola que haya que replantear la semana."
    elif compliance["pct_above_hr_zone"] and compliance["pct_above_hr_zone"] > 15:
        missed = f"Hubo algunos tramos por encima del techo de FC ({compliance['pct_above_hr_zone']:.1f}% del tiempo), aunque dentro de un desvio relativamente normal para un rodaje al aire libre."
    else:
        missed = "La intensidad se mantuvo razonablemente alineada con el objetivo previsto."
    relevant = (
        f"Ritmo medio {format_pace(summary['pace_s_per_km'])}, FC {summary['avg_hr']}/{summary['max_hr']} bpm, "
        f"cadencia {summary['avg_cadence_spm']:.1f} spm, potencia {summary['avg_power_w']} W, "
        f"temperatura {summary['min_temp_c']}-{summary['max_temp_c']} C, desnivel +{summary['elevation_gain_m']} m."
    )
    if compliance["pct_above_hr_zone"] and compliance["pct_above_hr_zone"] > 50:
        written = (
            "Sesion util, pero mas exigente de lo previsto para el objetivo del dia. "
            "La lectura correcta es ajustar el juicio del entreno, no dramatizarlo: solo conviene vigilar fatiga y sensaciones antes de la siguiente sesion importante."
        )
    elif compliance["pct_above_hr_zone"] and compliance["pct_above_hr_zone"] > 30:
        written = (
            "Sesion globalmente valida, aunque algo mas viva de lo ideal. "
            "Es una desviacion moderada y normalmente se corrige mas con control fino en los proximos rodajes que con cambios grandes en la semana."
        )
    else:
        written = (
            "Sesion bien alineada con el objetivo del dia y sin senales relevantes de exceso. "
            "Si las sensaciones posteriores son normales, no deberia condicionar la planificacion inmediata."
        )
    return goal, good, missed, relevant + " " + written


def review_markdown(review: dict[str, Any], planned_reference: str, completed_reference: str) -> str:
    summary = review["summary"]
    compliance = review["compliance"]
    halves = review["halves"]
    goal, good, missed, written = coaching_text(review)
    keep_week = "yes" if review["score"] >= 6 else "no"
    changes = "none" if keep_week == "yes" else "Reduce upcoming load and review shin response."
    split_lines = []
    progression = review.get("progression", {})
    for split in review["splits"]:
        split_lines.append(
            f"- {split['label']} km: {format_pace(split['pace_s_per_km'])}, {split['avg_hr']:.1f} bpm, {split['avg_power_w']:.0f} W, {split['avg_cadence_spm']:.1f} spm"
        )
    progression_lines = [f"- Trend: {progression.get('trend', 'unknown')}", f"- Summary: {progression.get('summary', 'No progression summary available.')}" ]
    stimulus_alignment = review.get("stimulus_alignment", {})
    baseline = progression.get("baseline") or {}
    delta = progression.get("delta_vs_baseline") or {}
    if baseline.get("pace_s_per_km") is not None and baseline.get("avg_hr") is not None:
        progression_lines.append(
            f"- Baseline comparable sessions: {format_pace(baseline['pace_s_per_km'])}, {baseline['avg_hr']:.1f} bpm"
        )
    if delta.get("pace_s_per_km") is not None and delta.get("avg_hr") is not None:
        progression_lines.append(
            f"- Delta vs baseline: {delta['pace_s_per_km']:+.1f} s/km, {delta['avg_hr']:+.1f} bpm"
        )
    for match in progression.get("matches", []):
        progression_lines.append(
            f"- Comparable {match['date']}: {match['name']}, {format_pace(match['pace_s_per_km'])}, {match['avg_hr']:.1f} bpm, +{match['elevation_gain_m']:.0f} m"
        )
    return "\n".join(
        [
            f"# Review {review['planned']['date']} - {review['planned']['name']}",
            "",
            "## Session",
            "",
            f"- Date: {review['planned']['date']}",
            "- Activity source: garmin",
            f"- Planned reference: {planned_reference}",
            f"- Completed reference: {completed_reference}",
            "",
            "## Rating",
            "",
            f"- Numeric score: {review['score']}/10",
            f"- Traffic light: {review['traffic_light']}",
            f"- Written review: {written}",
            "",
            "## Execution Analysis",
            "",
            f"- Goal of the session: {goal}",
            f"- Template id: {review['planned'].get('template_id') or '-'}",
            f"- Knowledge id: {review['planned'].get('knowledge_id') or '-'}",
            f"- Planned physiological goal: {review['planned'].get('primary_goal') or '-'}",
            f"- Stimulus alignment: {stimulus_alignment.get('summary') or '-'}",
            f"- What went well: {good}",
            f"- What missed the target: {missed}",
            f"- Relevant signals: ritmo {format_pace(summary['pace_s_per_km'])}, FC media/max {summary['avg_hr']}/{summary['max_hr']}, cadencia {summary['avg_cadence_spm']:.1f}, potencia {summary['avg_power_w']}, terreno +{summary['elevation_gain_m']} m, temperatura {summary['min_temp_c']}-{summary['max_temp_c']} C.",
            "",
            "## Planned Vs Completed",
            "",
            f"- Planned distance: {review['planned']['distance_m']} m",
            f"- Completed distance: {summary['distance_m']:.1f} m",
            f"- Distance difference: {compliance['distance_diff_m']:.1f} m",
            f"- Planned duration: {format_duration(review['planned']['estimated_duration_s'])}",
            f"- Completed duration: {format_duration(summary['duration_s'])}",
            f"- Duration difference: {format_duration(compliance['duration_diff_s_vs_est'])}",
            f"- HR target: {review['planned']['primary_hr_min']}-{review['planned']['primary_hr_max']} bpm",
            f"- Time in HR target: {format_duration(compliance['time_in_hr_zone_s'])} ({compliance['pct_in_hr_zone']:.1f}%)",
            f"- Time above HR target: {format_duration(compliance['time_above_hr_zone_s'])} ({compliance['pct_above_hr_zone']:.1f}%)",
            f"- Time to enter target zone: {format_duration(compliance['time_to_enter_zone_s'])}",
            "",
            "## Split Detail",
            "",
            *split_lines,
            "",
            "## Advanced Signals",
            "",
            f"- Pace variability: {review['stability']['pace_std_s_per_km']:.1f} s/km",
            f"- HR variability: {review['stability']['hr_std_bpm']:.1f} bpm",
            f"- Cadence variability: {review['stability']['cadence_std_spm']:.1f} spm",
            f"- Power variability: {review['stability']['power_std_w']:.1f} W",
            f"- First half: {format_pace(halves['first_half_pace_s_per_km'])}, {halves['first_half_hr']:.1f} bpm, {halves['first_half_power_w']:.0f} W",
            f"- Second half: {format_pace(halves['second_half_pace_s_per_km'])}, {halves['second_half_hr']:.1f} bpm, {halves['second_half_power_w']:.0f} W",
            f"- Decoupling: {halves['decoupling_pct']:.1f}%",
            f"- Avg stride length: {summary['avg_stride_cm']:.1f} cm",
            f"- Avg ground contact time: {summary['avg_gct_ms']:.1f} ms",
            f"- Avg vertical oscillation: {summary['avg_vo_cm']:.2f} cm",
            f"- Avg vertical ratio: {summary['avg_vr']:.2f}",
            f"- Aerobic training effect: {summary['aerobic_training_effect']}",
            f"- Anaerobic training effect: {summary['anaerobic_training_effect']}",
            "",
            "## Progression Markers",
            "",
            *progression_lines,
            "",
            "## Coaching Decision",
            "",
            f"- Keep the week as planned: {keep_week}",
            f"- If not, what changes: {changes}",
            f"- Risk level: {review['risk_level']}",
        ]
    )


def output_paths(day: str, planned_workout_path: Path) -> tuple[Path, Path, Path]:
    slug = planned_workout_path.stem
    activity_path = DEFAULT_ACTIVITY_ROOT / f"{slug}.yaml"
    review_path = DEFAULT_REVIEW_ROOT / f"{slug}.md"
    analysis_path = DEFAULT_REVIEW_ROOT / f"{slug}.analysis.json"
    return activity_path, review_path, analysis_path


def main() -> None:
    args = parse_args()
    planned_workout_path = find_planned_workout(args.date)
    activity_path, review_path, analysis_path = output_paths(args.date, planned_workout_path)
    if not args.force and review_path.exists():
        raise FileExistsError(f"Review already exists at {review_path}; use --force to regenerate")

    planned = load_yaml(planned_workout_path)
    if args.use_local_imports_only:
        activities = load_local_running_activities(args.date)
    else:
        activities = import_recent_running_activities(args.date, args.credentials, args.days, args.limit)
    activity = select_activity_by_id(activities, args.activity_id) if args.activity_id is not None else select_activity(activities, planned, args.date)
    activity_dir = DEFAULT_IMPORT_ROOT / "activities" / f"{args.date}_{activity['activityId']}"
    summary = json.loads((activity_dir / "summary.json").read_text(encoding="utf-8"))
    details = json.loads((activity_dir / "details.json").read_text(encoding="utf-8"))
    review = analyze_workout(planned, summary, details)

    planned_reference = str(planned_workout_path.relative_to(ROOT))
    completed_reference = str(activity_path.relative_to(ROOT))
    save_yaml(activity_path, activity_record(review, planned_reference))
    save_text(review_path, review_markdown(review, planned_reference, completed_reference))
    save_json(analysis_path, review)
    print(
        json.dumps(
            {
                "planned_workout": planned_reference,
                "garmin_activity_id": summary["activityId"],
                "activity_file": str(activity_path.relative_to(ROOT)),
                "review_file": str(review_path.relative_to(ROOT)),
                "analysis_file": str(analysis_path.relative_to(ROOT)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
