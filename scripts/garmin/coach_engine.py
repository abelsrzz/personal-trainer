#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
GARMIN_ACTIVITY_ROOT = ROOT / "training" / "completed" / "imports" / "garmin" / "activities"
GARMIN_DAILY_ROOT = ROOT / "training" / "completed" / "imports" / "garmin" / "daily"
REVIEW_ROOT = ROOT / "training" / "completed" / "reviews"
SHIN_TRACKER_PATH = ROOT / "athlete" / "shin_tracker.yaml"
GOAL_GATES_PATH = ROOT / "planning" / "goal_gates.yaml"
STATUS_DASHBOARD_PATH = ROOT / "athlete" / "status_dashboard.md"
COACH_DECISION_MD_PATH = ROOT / "planning" / "coach_decision.md"
COACH_DECISION_JSON_PATH = ROOT / "planning" / "coach_decision.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build athlete dashboard and coaching decision from local Garmin data")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Analysis date, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=28, help="Dashboard lookback window")
    parser.add_argument("--write", action=argparse.BooleanOptionalAction, default=True, help="Write markdown and JSON outputs")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True, default=str)
        handle.write("\n")


def save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_local_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).split(" ")[0]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def seconds_to_pace(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}/km"


def seconds_to_time(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}%"


def fmt_float(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def activity_type(summary: dict[str, Any]) -> str | None:
    return summary.get("activityType", {}).get("typeKey")


def load_activity_summaries() -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    for path in sorted(GARMIN_ACTIVITY_ROOT.glob("*/summary.json")):
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        if activity_type(payload) not in {"running", "trail_running"}:
            continue
        activity_date = parse_local_date(payload.get("startTimeLocal") or payload.get("startTimeGMT"))
        if activity_date is None:
            continue
        distance_m = float(payload.get("distance") or 0.0)
        duration_s = float(payload.get("duration") or payload.get("movingDuration") or 0.0)
        pace_s = duration_s * 1000.0 / distance_m if distance_m else None
        activities.append(
            {
                "date": activity_date,
                "activity_id": payload.get("activityId"),
                "name": payload.get("activityName"),
                "distance_km": distance_m / 1000.0,
                "duration_s": duration_s,
                "pace_s_per_km": pace_s,
                "avg_hr": payload.get("averageHR"),
                "max_hr": payload.get("maxHR"),
                "avg_power_w": payload.get("avgPower"),
                "elevation_gain_m": payload.get("elevationGain"),
                "aerobic_training_effect": payload.get("aerobicTrainingEffect"),
                "anaerobic_training_effect": payload.get("anaerobicTrainingEffect"),
                "training_effect_label": payload.get("trainingEffectLabel"),
                "vo2max": payload.get("vO2MaxValue"),
                "fastest_1k_s": payload.get("fastestSplit_1000"),
                "fastest_5k_s": payload.get("fastestSplit_5000"),
                "fastest_10k_s": payload.get("fastestSplit_10000"),
                "source_path": str(path.relative_to(ROOT)),
            }
        )
    activities.sort(key=lambda item: item["date"])
    return activities


def load_reviews() -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for path in sorted(REVIEW_ROOT.glob("*.analysis.json")):
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        review_date = parse_local_date(payload.get("planned", {}).get("date"))
        if review_date is None:
            continue
        payload["review_date"] = review_date
        payload["source_path"] = str(path.relative_to(ROOT))
        reviews.append(payload)
    reviews.sort(key=lambda item: item["review_date"])
    return reviews


def load_daily_metrics() -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for path in sorted(GARMIN_DAILY_ROOT.glob("*.json")):
        if path.name.startswith("last_import") or path.name.startswith("running_tolerance"):
            continue
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        metric_date = parse_local_date(payload.get("date") or path.stem)
        if metric_date is None:
            continue
        metrics.append({"date": metric_date, "payload": payload, "source_path": str(path.relative_to(ROOT))})
    metrics.sort(key=lambda item: item["date"])
    return metrics


def load_shin_entries() -> list[dict[str, Any]]:
    data = load_yaml(SHIN_TRACKER_PATH)
    entries = data.get("shin_tracker", {}).get("entries", [])
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        entry_date = parse_local_date(entry.get("date"))
        if entry_date is None:
            continue
        normalized.append({**entry, "date": entry_date})
    normalized.sort(key=lambda item: item["date"])
    return normalized


def is_quality_activity(activity: dict[str, Any]) -> bool:
    label = str(activity.get("training_effect_label") or "").upper()
    aerobic_te = float(activity.get("aerobic_training_effect") or 0.0)
    anaerobic_te = float(activity.get("anaerobic_training_effect") or 0.0)
    avg_hr = float(activity.get("avg_hr") or 0.0)
    return aerobic_te >= 3.5 or anaerobic_te >= 1.0 or avg_hr >= 165 or any(key in label for key in ["TEMPO", "VO2", "ANAEROBIC", "LACTATE"])


def activities_between(activities: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [item for item in activities if start <= item["date"] <= end]


def aggregate_window(activities: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    window = activities_between(activities, start, end)
    total_km = sum(float(item.get("distance_km") or 0.0) for item in window)
    total_duration = sum(float(item.get("duration_s") or 0.0) for item in window)
    quality = [item for item in window if is_quality_activity(item)]
    long_run = max((float(item.get("distance_km") or 0.0) for item in window), default=0.0)
    weighted_hr_num = sum(float(item.get("avg_hr") or 0.0) * float(item.get("duration_s") or 0.0) for item in window if item.get("avg_hr"))
    avg_hr = weighted_hr_num / total_duration if total_duration else None
    pace = total_duration / total_km if total_km else None
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "runs": len(window),
        "km": total_km,
        "duration_s": total_duration,
        "avg_pace_s_per_km": pace,
        "avg_hr": avg_hr,
        "quality_runs": len(quality),
        "long_run_km": long_run,
    }


def weekly_volume(activities: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, int], dict[str, Any]] = defaultdict(lambda: {"km": 0.0, "runs": 0, "quality_runs": 0, "long_run_km": 0.0})
    for activity in activities_between(activities, start, end):
        year, week, _ = activity["date"].isocalendar()
        bucket = buckets[(year, week)]
        distance = float(activity.get("distance_km") or 0.0)
        bucket["km"] += distance
        bucket["runs"] += 1
        bucket["long_run_km"] = max(bucket["long_run_km"], distance)
        if is_quality_activity(activity):
            bucket["quality_runs"] += 1
    return [
        {"week": f"{year}-W{week:02d}", **values}
        for (year, week), values in sorted(buckets.items())
    ]


def latest_high_risk_review(reviews: list[dict[str, Any]], as_of: date, days: int = 7) -> dict[str, Any] | None:
    start = as_of - timedelta(days=days - 1)
    candidates = [item for item in reviews if start <= item["review_date"] <= as_of]
    risky = [item for item in candidates if item.get("risk_level") == "alto" or int(item.get("score") or 10) <= 4]
    return risky[-1] if risky else None


def latest_shin_entry(entries: list[dict[str, Any]], as_of: date) -> dict[str, Any] | None:
    candidates = [entry for entry in entries if entry["date"] <= as_of]
    return candidates[-1] if candidates else None


def max_shin_pain(entry: dict[str, Any] | None) -> int | None:
    if not entry:
        return None
    values = [entry.get("pain_during"), entry.get("pain_after"), entry.get("pain_next_morning")]
    numeric = [int(value) for value in values if value is not None]
    return max(numeric) if numeric else None


def best_split(activities: list[dict[str, Any]], key: str, start: date, end: date) -> float | None:
    values = [float(item[key]) for item in activities_between(activities, start, end) if item.get(key)]
    return min(values) if values else None


def evaluate_goal_gates(activities: list[dict[str, Any]], reviews: list[dict[str, Any]], shin_entries: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    config = load_yaml(GOAL_GATES_PATH).get("goal_gates", {})
    thresholds = config.get("thresholds", {})
    start_28 = as_of - timedelta(days=27)
    start_90 = as_of - timedelta(days=89)
    start_180 = as_of - timedelta(days=179)
    last_28 = aggregate_window(activities, start_28, as_of)
    avg_weekly_km = last_28["km"] / 4.0
    best_5k = best_split(activities, "fastest_5k_s", start_90, as_of)
    best_10k = best_split(activities, "fastest_10k_s", start_180, as_of)
    high_risk_count = len(
        [item for item in reviews if start_28 <= item["review_date"] <= as_of and (item.get("risk_level") == "alto" or int(item.get("score") or 10) <= 4)]
    )
    shin_pain = max_shin_pain(latest_shin_entry(shin_entries, as_of))

    foundation = {
        "name": "Base estable",
        "passed": avg_weekly_km >= float(thresholds.get("foundation_avg_weekly_km", 40))
        and last_28["long_run_km"] >= float(thresholds.get("foundation_long_run_km", 14))
        and high_risk_count == 0
        and (shin_pain is None or shin_pain <= 2),
        "evidence": f"Media 4 semanas {avg_weekly_km:.1f} km/sem, tirada larga {last_28['long_run_km']:.1f} km, revisiones rojas {high_risk_count}, periostio {shin_pain if shin_pain is not None else '-'}.",
    }
    threshold_gate = {
        "name": "Umbral competitivo",
        "passed": best_5k is not None and best_5k <= float(thresholds.get("threshold_gate_5k_s", 19 * 60)),
        "evidence": f"Mejor 5k reciente: {seconds_to_time(best_5k)}.",
    }
    specific_gate = {
        "name": "Precondicion 35:00",
        "passed": avg_weekly_km >= float(thresholds.get("specific_avg_weekly_km", 50))
        and last_28["long_run_km"] >= float(thresholds.get("specific_long_run_km", 16))
        and best_5k is not None
        and best_5k <= float(thresholds.get("specific_5k_s", 18 * 60))
        and high_risk_count == 0
        and (shin_pain is None or shin_pain <= 2),
        "evidence": f"Media {avg_weekly_km:.1f} km/sem, tirada {last_28['long_run_km']:.1f} km, 5k {seconds_to_time(best_5k)}, riesgo {high_risk_count}.",
    }
    final_gate = {
        "name": "Seleccion 35:00",
        "passed": best_5k is not None
        and best_5k <= float(thresholds.get("final_5k_s", 17 * 60 + 15))
        and (best_10k is None or best_10k <= float(thresholds.get("final_10k_s", 36 * 60 + 30)))
        and specific_gate["passed"],
        "evidence": f"5k {seconds_to_time(best_5k)}, 10k {seconds_to_time(best_10k)}.",
    }

    gates = [foundation, threshold_gate, specific_gate, final_gate]
    passed_count = sum(1 for gate in gates if gate["passed"])
    if final_gate["passed"]:
        status = "35_ready"
        summary = "El 35:00 puede entrar en la estrategia si las semanas finales confirman recuperacion."
    elif specific_gate["passed"]:
        status = "aggressive_alive"
        summary = "El objetivo agresivo sigue vivo, pero aun falta evidencia final."
    elif threshold_gate["passed"] or foundation["passed"]:
        status = "development_needed"
        summary = "Hay base para progresar, pero 35:00 aun no debe dirigir los ritmos."
    else:
        status = "unsupported_now"
        summary = "Con la evidencia actual, 35:00 sigue siendo aspiracional y no prescribe ritmos."

    return {
        "status": status,
        "summary": summary,
        "passed_count": passed_count,
        "total_gates": len(gates),
        "metrics": {
            "avg_weekly_km_28d": avg_weekly_km,
            "long_run_km_28d": last_28["long_run_km"],
            "best_5k_s_90d": best_5k,
            "best_10k_s_180d": best_10k,
            "high_risk_reviews_28d": high_risk_count,
            "latest_shin_pain": shin_pain,
        },
        "gates": gates,
    }


def riegel_time(source_time_s: float, source_distance_km: float, target_distance_km: float) -> float:
    return source_time_s * (target_distance_km / source_distance_km) ** 1.06


def performance_estimate(activities: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    start_90 = as_of - timedelta(days=89)
    start_180 = as_of - timedelta(days=179)
    best_5k = best_split(activities, "fastest_5k_s", start_90, as_of)
    best_10k = best_split(activities, "fastest_10k_s", start_180, as_of)
    estimate_10k_from_5k = riegel_time(best_5k, 5.0, 10.0) if best_5k else None
    estimate_5k_from_10k = riegel_time(best_10k, 10.0, 5.0) if best_10k else None
    candidates_10k = [value for value in [best_10k, estimate_10k_from_5k] if value is not None]
    current_10k_estimate = min(candidates_10k) if candidates_10k else None
    return {
        "best_5k_s_90d": best_5k,
        "best_10k_s_180d": best_10k,
        "estimate_10k_from_5k_s": estimate_10k_from_5k,
        "estimate_5k_from_10k_s": estimate_5k_from_10k,
        "current_10k_estimate_s": current_10k_estimate,
        "method": "Mejores splits recientes de Garmin y conversion Riegel; usar como tendencia, no como garantia de carrera.",
    }


def build_decision(activities: list[dict[str, Any]], reviews: list[dict[str, Any]], shin_entries: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    last_7 = aggregate_window(activities, as_of - timedelta(days=6), as_of)
    prev_7 = aggregate_window(activities, as_of - timedelta(days=13), as_of - timedelta(days=7))
    last_28 = aggregate_window(activities, as_of - timedelta(days=27), as_of)
    volume_spike = None
    if prev_7["km"] > 0:
        volume_spike = ((last_7["km"] - prev_7["km"]) / prev_7["km"]) * 100.0

    risky_review = latest_high_risk_review(reviews, as_of)
    shin_entry = latest_shin_entry(shin_entries, as_of)
    shin_pain = max_shin_pain(shin_entry)
    reasons: list[str] = []
    status = "green"
    action = "maintain_or_progress_carefully"

    if risky_review:
        reasons.append(f"Revision reciente de alto riesgo: {risky_review['planned']['date']} {risky_review['planned']['name']}.")
        status = "red"
    if shin_pain is not None and shin_pain >= 4:
        reasons.append(f"Periostio con dolor maximo {shin_pain}/10 en el ultimo registro.")
        status = "red"
    elif shin_pain is not None and shin_pain == 3 and status != "red":
        reasons.append("Periostio en 3/10: no conviene aumentar carga.")
        status = "yellow"
    if volume_spike is not None and volume_spike > 30 and last_7["km"] >= 25:
        reasons.append(f"Subida de volumen 7d de {volume_spike:.0f}%.")
        status = "red" if volume_spike > 50 else "yellow"
    if last_7["quality_runs"] >= 3:
        reasons.append(f"Demasiada densidad de calidad: {last_7['quality_runs']} sesiones exigentes en 7 dias.")
        status = "red"
    if last_7["avg_hr"] and last_7["avg_hr"] > 152 and last_7["avg_pace_s_per_km"] and last_7["avg_pace_s_per_km"] > 420:
        reasons.append("Rodajes recientes muestran pulso alto para ritmo facil; senal de fatiga, calor o baja eficiencia actual.")
        status = "yellow" if status == "green" else status

    if status == "red":
        action = "reduce_or_replace_quality"
        recommendation = "Reducir carga inmediata: cambiar la proxima calidad por rodaje muy facil o descanso, y mantener FC capada."
    elif status == "yellow":
        action = "maintain_with_caution"
        recommendation = "Mantener estructura, pero sin subir volumen ni intensidad hasta ver 2-3 sesiones faciles estables."
    else:
        recommendation = "Mantener plan y permitir progresion pequena si el periostio sigue en 0-2/10."

    if not reasons:
        reasons.append("Sin banderas rojas objetivas en los datos locales disponibles.")

    return {
        "as_of": as_of.isoformat(),
        "status": status,
        "action": action,
        "recommendation": recommendation,
        "reasons": reasons,
        "windows": {"last_7_days": last_7, "previous_7_days": prev_7, "last_28_days": last_28},
        "volume_spike_pct": volume_spike,
        "latest_shin_entry": shin_entry,
        "latest_high_risk_review": risky_review,
    }


def summarize_daily(metrics: list[dict[str, Any]], as_of: date, days: int) -> dict[str, Any]:
    start = as_of - timedelta(days=days - 1)
    window = [item for item in metrics if start <= item["date"] <= as_of]
    return {
        "available_days": len(window),
        "latest_date": window[-1]["date"].isoformat() if window else None,
        "source": "garmin_daily" if window else "none",
    }


def render_dashboard(payload: dict[str, Any]) -> str:
    decision = payload["decision"]
    gates = payload["goal_gates"]
    estimate = payload["performance_estimate"]
    last_7 = decision["windows"]["last_7_days"]
    last_28 = decision["windows"]["last_28_days"]
    weekly = payload["weekly_volume"][-8:]
    lines = [
        "# Athlete Status Dashboard",
        "",
        f"- Fecha de analisis: `{payload['as_of']}`",
        f"- Estado: `{decision['status']}`",
        f"- Accion recomendada: `{decision['action']}`",
        f"- Recomendacion: {decision['recommendation']}",
        "",
        "## Carga Reciente",
        "",
        f"- Ultimos 7 dias: `{last_7['km']:.1f} km`, `{last_7['runs']}` carreras, `{last_7['quality_runs']}` exigentes, tirada larga `{last_7['long_run_km']:.1f} km`.",
        f"- Ultimos 28 dias: `{last_28['km']:.1f} km`, `{last_28['runs']}` carreras, media `{last_28['km'] / 4.0:.1f} km/sem`.",
        f"- Ritmo medio 7d: `{seconds_to_pace(last_7['avg_pace_s_per_km'])}`, FC media `{fmt_float(last_7['avg_hr'])}`.",
            f"- Cambio vs 7 dias previos: `{pct(decision['volume_spike_pct'])}`.",
            "",
            "## Predictor De Marca",
            "",
            f"- Mejor 5k reciente: `{seconds_to_time(estimate['best_5k_s_90d'])}`.",
            f"- Mejor 10k reciente: `{seconds_to_time(estimate['best_10k_s_180d'])}`.",
            f"- Estimacion 10k actual: `{seconds_to_time(estimate['current_10k_estimate_s'])}`.",
            f"- Metodo: {estimate['method']}",
            "",
            "## Riesgos Detectados",
            "",
    ]
    lines.extend([f"- {reason}" for reason in decision["reasons"]])
    lines.extend(
        [
            "",
            "## Objetivo 35:00",
            "",
            f"- Estado: `{gates['status']}`",
            f"- Resumen: {gates['summary']}",
            f"- Gates cumplidos: `{gates['passed_count']}/{gates['total_gates']}`",
            "",
        ]
    )
    for gate in gates["gates"]:
        marker = "OK" if gate["passed"] else "NO"
        lines.append(f"- `{marker}` {gate['name']}: {gate['evidence']}")
    lines.extend(["", "## Volumen Semanal", ""])
    if weekly:
        for item in weekly:
            lines.append(f"- `{item['week']}`: `{item['km']:.1f} km`, `{item['runs']}` carreras, `{item['quality_runs']}` exigentes, tirada `{item['long_run_km']:.1f} km`.")
    else:
        lines.append("- Sin actividades importadas en la ventana.")
    lines.extend(
        [
            "",
            "## Datos Garmin Daily",
            "",
            f"- Dias disponibles en ventana: `{payload['daily_metrics']['available_days']}`.",
            f"- Ultimo dia diario importado: `{payload['daily_metrics']['latest_date'] or '-'}`.",
        ]
    )
    return "\n".join(lines)


def render_decision(payload: dict[str, Any]) -> str:
    decision = payload["decision"]
    lines = [
        "# Coach Decision",
        "",
        f"- Fecha de analisis: `{payload['as_of']}`",
        f"- Estado: `{decision['status']}`",
        f"- Accion: `{decision['action']}`",
        f"- Decision: {decision['recommendation']}",
        "",
        "## Motivos",
        "",
    ]
    lines.extend([f"- {reason}" for reason in decision["reasons"]])
    lines.extend(
        [
            "",
            "## Regla Operativa",
            "",
            "- `green`: se puede mantener el plan y progresar poco.",
            "- `yellow`: mantener sin subir carga; vigilar 2-3 sesiones.",
            "- `red`: reducir o sustituir calidad por rodaje muy facil/descanso.",
        ]
    )
    return "\n".join(lines)


def build_payload(as_of: date, days: int) -> dict[str, Any]:
    activities = load_activity_summaries()
    reviews = load_reviews()
    daily = load_daily_metrics()
    shin_entries = load_shin_entries()
    start = as_of - timedelta(days=days - 1)
    decision = build_decision(activities, reviews, shin_entries, as_of)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": as_of.isoformat(),
        "lookback_days": days,
        "activity_count_total": len(activities),
        "review_count_total": len(reviews),
        "decision": decision,
        "goal_gates": evaluate_goal_gates(activities, reviews, shin_entries, as_of),
        "performance_estimate": performance_estimate(activities, as_of),
        "weekly_volume": weekly_volume(activities, start, as_of),
        "daily_metrics": summarize_daily(daily, as_of, days),
    }


def main() -> None:
    args = parse_args()
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    payload = build_payload(as_of, args.days)
    if args.write:
        save_json(COACH_DECISION_JSON_PATH, payload)
        save_text(STATUS_DASHBOARD_PATH, render_dashboard(payload))
        save_text(COACH_DECISION_MD_PATH, render_decision(payload))
    print(json.dumps({"status": payload["decision"]["status"], "action": payload["decision"]["action"], "as_of": payload["as_of"]}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
