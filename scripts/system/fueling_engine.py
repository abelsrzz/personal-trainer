#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "athlete" / "profile.yaml"
SUPPLEMENTS_PATH = ROOT / "athlete" / "supplements.yaml"
RACES_ROOT = ROOT / "races"
WORKOUTS_ROOT = ROOT / "training" / "planned" / "workouts"
FUELING_JSON_PATH = ROOT / "planning" / "fueling_operational.json"
FUELING_MD_PATH = ROOT / "planning" / "fueling_operational.md"


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).split(" ")[0].strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_duration(seconds: float | int | None) -> str:
    if seconds is None or float(seconds) <= 0:
        return "-"
    total = int(round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(seconds: float | int | None) -> str:
    if seconds is None or float(seconds) <= 0:
        return "-"
    total = int(round(float(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}/km"


def parse_distance_km(value: Any) -> float | None:
    text = str(value or "").strip().lower().replace(",", ".")
    if not text or text == "-":
        return None
    text = text.replace("km", "").replace("k", "")
    try:
        return float(text)
    except ValueError:
        return None


def workout_distance_km(payload: dict[str, Any]) -> float | None:
    distance_m = payload.get("distance_m")
    if distance_m is None:
        distance_m = sum(float(step.get("distance_m") or 0.0) for step in payload.get("steps") or [] if isinstance(step, dict))
    if not distance_m:
        return None
    return float(distance_m) / 1000.0


def athlete_profile() -> dict[str, Any]:
    return load_yaml(PROFILE_PATH).get("athlete", {})


def athlete_weight_kg() -> float:
    profile = athlete_profile()
    try:
        return float(profile.get("weight_kg") or 64.0)
    except (TypeError, ValueError):
        return 64.0


def supplements_catalog() -> list[dict[str, Any]]:
    items = load_yaml(SUPPLEMENTS_PATH).get("supplements", [])
    return [item for item in items if isinstance(item, dict) and item.get("enabled")]


def find_supplements(category: str) -> list[dict[str, Any]]:
    return [item for item in supplements_catalog() if str(item.get("category") or "") == category]


def first_supplement(category: str) -> dict[str, Any] | None:
    items = find_supplements(category)
    return items[0] if items else None


def carb_supplements() -> list[dict[str, Any]]:
    return [item for item in supplements_catalog() if str(item.get("category") or "") == "carbs"]


def products_label(items: list[dict[str, Any]]) -> str:
    return " + ".join(str(item.get("name") or "") for item in items if item.get("name")) or "Sin producto definido"


def create_entry(context_type: str, context_id: str, target_date: date, time_label: str, phase: str, recommendation: str, products: list[dict[str, Any]], quantity: str, reason: str) -> dict[str, Any]:
    return {
        "context_type": context_type,
        "context_id": context_id,
        "date": target_date.isoformat(),
        "time_label": time_label,
        "phase": phase,
        "recommendation": recommendation,
        "products": [{"id": item.get("id"), "name": item.get("name")} for item in products],
        "products_label": products_label(products),
        "quantity": quantity,
        "reason": reason,
    }


def carb_load_targets(distance_km: float | None, weight_kg: float) -> list[tuple[int, float]]:
    if not distance_km:
        return [(-1, 5.0 * weight_kg)]
    if distance_km <= 6.0:
        return [(-1, 5.0 * weight_kg)]
    if distance_km <= 12.0:
        return [(-2, 5.0 * weight_kg), (-1, 6.0 * weight_kg)]
    return [(-2, 6.0 * weight_kg), (-1, 7.0 * weight_kg)]


def race_prediction_seconds(race_distance_km: float | None, current_10k_estimate_s: float | None) -> float | None:
    if not race_distance_km or not current_10k_estimate_s:
        return None
    return float(current_10k_estimate_s) * (float(race_distance_km) / 10.0) ** 1.06


def race_plan(race: dict[str, Any], current_10k_estimate_s: float | None) -> dict[str, Any]:
    race_date = parse_iso_date(race.get("date"))
    if not race_date:
        return {"entries": []}
    distance_km = parse_distance_km(race.get("distance") or race.get("distance_km"))
    weight_kg = athlete_weight_kg()
    carbs = carb_supplements()
    electrolytes = [item for item in supplements_catalog() if "electrolytes" in str(item.get("category") or "")]
    protein = first_supplement("protein")
    creatine = first_supplement("creatine")
    caffeinated = [item for item in supplements_catalog() if float(item.get("caffeine_mg") or 0.0) > 0]
    predicted_time_s = race_prediction_seconds(distance_km, current_10k_estimate_s)
    during_needed = bool(predicted_time_s and predicted_time_s >= 3600) or bool(distance_km and distance_km >= 10.0)

    entries: list[dict[str, Any]] = []
    for offset_days, target_carbs_g in carb_load_targets(distance_km, weight_kg):
        entries.append(
            create_entry(
                "race",
                str(race.get("id") or race.get("name") or race_date.isoformat()),
                race_date + timedelta(days=offset_days),
                "Durante el dia",
                "carb_load",
                f"Apuntar a {round(target_carbs_g)} g de hidratos en el dia, priorizando comidas faciles de digerir.",
                carbs,
                f"{round(target_carbs_g)} g CHO/dia",
                "Asegura glucogeno suficiente para competir sin llegar vacio al dia de carrera.",
            )
        )

    entries.append(
        create_entry(
            "race",
            str(race.get("id") or race.get("name") or race_date.isoformat()),
            race_date - timedelta(days=1),
            "Distribuido en el dia",
            "hydration",
            f"Beber entre {round((weight_kg * 35) / 1000, 1)} y {round((weight_kg * 40) / 1000, 1)} L repartidos y añadir sodio si hace calor.",
            electrolytes[:1],
            f"{round((weight_kg * 35) / 1000, 1)}-{round((weight_kg * 40) / 1000, 1)} L",
            "Llegar bien hidratado mejora tolerancia al ritmo y reduce el coste final.",
        )
    )

    entries.append(
        create_entry(
            "race",
            str(race.get("id") or race.get("name") or race_date.isoformat()),
            race_date,
            "T-3h",
            "pre",
            f"Comida previa con {round(weight_kg * (1.2 if (distance_km or 0) <= 10 else 1.5))} g de hidratos y muy baja en fibra/grasa.",
            carbs,
            f"{round(weight_kg * (1.2 if (distance_km or 0) <= 10 else 1.5))} g CHO",
            "Llegar con energia disponible sin pesadez gastrointestinal.",
        )
    )

    entries.append(
        create_entry(
            "race",
            str(race.get("id") or race.get("name") or race_date.isoformat()),
            race_date,
            "T-45m",
            "pre",
            "Top-up pequeño si llegas con hambre o la salida se retrasa.",
            carbs,
            "20-25 g CHO",
            "Ayuda a no arrancar con sensacion de vacio sin cargar de mas el estomago.",
        )
    )

    if caffeinated:
        entries.append(
            create_entry(
                "race",
                str(race.get("id") or race.get("name") or race_date.isoformat()),
                race_date,
                "T-30m",
                "pre",
                "Cafeina opcional solo si ya esta probada en entrenos o carreras.",
                caffeinated[:1],
                f"{int(float(caffeinated[0].get('caffeine_mg') or 0))} mg cafeina",
                "Puede mejorar activacion y foco, pero no conviene estrenarla el dia de carrera.",
            )
        )

    if during_needed:
        entries.append(
            create_entry(
                "race",
                str(race.get("id") or race.get("name") or race_date.isoformat()),
                race_date,
                "Durante",
                "during",
                "Tomar hidratos y sodio de forma fraccionada si la carrera supera ~60 min o si hace calor.",
                carbs + electrolytes[:1],
                "30-45 g CHO/h + sodio",
                "Mantener disponibilidad de energia y limitar la deriva de rendimiento al final.",
            )
        )
    else:
        entries.append(
            create_entry(
                "race",
                str(race.get("id") or race.get("name") or race_date.isoformat()),
                race_date,
                "Durante",
                "during",
                "Para esta distancia basta con pequeños sorbos de agua/electrolitos si hace calor o hay espera larga.",
                electrolytes[:1],
                "A demanda",
                "La prioridad es llegar bien preparado al inicio; durante no hace falta meter mucho si la prueba es corta.",
            )
        )

    post_products = [item for item in [protein, creatine, *(carbs[:1])] if item]
    entries.append(
        create_entry(
            "race",
            str(race.get("id") or race.get("name") or race_date.isoformat()),
            race_date,
            "T+30m",
            "post",
            "Recuperacion inmediata con proteina, creatina y algo de hidratos si no comes pronto.",
            post_products,
            "20-30 g proteina + 3-5 g creatina + 40-60 g CHO",
            "Acelera recuperacion y reduce el impacto del esfuerzo sobre la siguiente semana.",
        )
    )

    return {
        "entries": entries,
        "predicted_time": format_duration(predicted_time_s),
        "predicted_pace": format_pace((predicted_time_s / distance_km) if predicted_time_s and distance_km else None),
    }


def classify_workout_intensity(payload: dict[str, Any]) -> str:
    name = str(payload.get("name") or "").lower()
    description = str(payload.get("description") or "").lower()
    duration_s = float(payload.get("estimated_duration_s") or 0.0)
    distance_km = workout_distance_km(payload) or 0.0
    if any(keyword in name or keyword in description for keyword in ["10x1000", "series", "interval", "especifica", "tempo", "bloques"]):
        return "hard"
    if duration_s >= 5400 or distance_km >= 14.0:
        return "very_hard"
    if duration_s >= 3600 or distance_km >= 10.0:
        return "hard"
    return "normal"


def workout_plan(slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    workout_date = parse_iso_date(payload.get("schedule_date"))
    if not workout_date:
        return {"entries": [], "is_recommended": False}
    intensity = classify_workout_intensity(payload)
    if intensity == "normal":
        return {"entries": [], "is_recommended": False}
    duration_s = float(payload.get("estimated_duration_s") or 0.0)
    distance_km = workout_distance_km(payload) or 0.0
    carbs = carb_supplements()
    electrolytes = [item for item in supplements_catalog() if "electrolytes" in str(item.get("category") or "")]
    protein = first_supplement("protein")
    creatine = first_supplement("creatine")
    entries: list[dict[str, Any]] = []
    during_target = None
    if duration_s >= 5400 or intensity == "very_hard":
        during_target = "60-75 g CHO/h + sodio"
    elif duration_s >= 3600 or distance_km >= 10.0:
        during_target = "30-45 g CHO/h + sodio"

    entries.append(
        create_entry(
            "workout",
            slug,
            workout_date,
            "T-90m",
            "pre",
            "Llegar con hidratos disponibles y sin pesadez antes de la sesion exigente.",
            carbs,
            "30-60 g CHO",
            "Mejora la calidad del entrenamiento y evita recortarlo por falta de energia.",
        )
    )
    if during_target:
        entries.append(
            create_entry(
                "workout",
                slug,
                workout_date,
                "Durante",
                "during",
                "Mantener energia y sodio durante la sesion si el coste es alto o se alarga mucho.",
                carbs + electrolytes[:1],
                during_target,
                "Reduce la deriva final y mejora la tolerancia al bloque completo.",
            )
        )
    entries.append(
        create_entry(
            "workout",
            slug,
            workout_date,
            "T+30m",
            "post",
            "Recuperacion corta con proteina, creatina y algo de hidratos tras la sesion dura.",
            [item for item in [protein, creatine, *(carbs[:1])] if item],
            "20-30 g proteina + 3-5 g creatina + 30-60 g CHO",
            "Acelera recuperacion y ayuda a llegar mejor al siguiente dia util.",
        )
    )
    return {"entries": entries, "is_recommended": True, "intensity": intensity}


def load_races() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(RACES_ROOT.glob("**/*.yaml")):
        raw = load_yaml(path)
        payload = raw.get("race", raw) if isinstance(raw, dict) else {}
        if not isinstance(payload, dict):
            continue
        items.append({**payload, "source_path": str(path.relative_to(ROOT))})
    return items


def load_workouts() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(WORKOUTS_ROOT.glob("*.yaml")):
        if path.name in {"library_run_templates.yaml", "workout_template.yaml"}:
            continue
        payload = load_yaml(path).get("workout", {})
        if not isinstance(payload, dict):
            continue
        items.append({"slug": path.stem, "payload": payload, "source_path": str(path.relative_to(ROOT))})
    return items


def build_fueling_payload() -> dict[str, Any]:
    races = load_races()
    workouts = load_workouts()
    weight_kg = athlete_weight_kg()
    supplements = supplements_catalog()
    coach_path = ROOT / "planning" / "coach_decision.json"
    coach_payload = json.loads(coach_path.read_text(encoding="utf-8")) if coach_path.exists() else {}
    current_10k_estimate_s = (coach_payload.get("performance_estimate", {}) if isinstance(coach_payload, dict) else {}).get("current_10k_estimate_s")
    race_plans = []
    workout_plans = []
    for race in races:
        plan = race_plan(race, float(current_10k_estimate_s) if current_10k_estimate_s is not None else None)
        race_plans.append({
            "id": str(race.get("id") or race.get("name") or race.get("date") or "race"),
            "name": str(race.get("name") or "Carrera"),
            "date": str(race.get("date") or ""),
            "distance": race.get("distance") or race.get("distance_km"),
            "priority": str(race.get("priority") or ""),
            "goal": (race.get("goal") or {}).get("value") if isinstance(race.get("goal"), dict) else race.get("goal"),
            "plan": plan,
        })
    for workout in workouts:
        plan = workout_plan(workout["slug"], workout["payload"])
        if plan.get("is_recommended"):
            workout_plans.append(
                {
                    "slug": workout["slug"],
                    "name": workout["payload"].get("name") or workout["slug"],
                    "date": str(workout["payload"].get("schedule_date") or ""),
                    "plan": plan,
                }
            )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "athlete": {"weight_kg": weight_kg},
        "supplements": supplements,
        "races": race_plans,
        "workouts": workout_plans,
    }


def render_fueling_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Fueling Operational Plan",
        "",
        f"- Generated: `{payload.get('generated_at')}`",
        f"- Athlete weight: `{payload.get('athlete', {}).get('weight_kg')}` kg",
        "",
        "## Supplements",
        "",
    ]
    for item in payload.get("supplements", []):
        lines.append(f"- `{item.get('name')}` ({item.get('category')}): {item.get('serving_size')} {item.get('serving_unit')}")
    lines.extend(["", "## Races", ""])
    for race in payload.get("races", []):
        lines.append(f"### {race.get('date')} · {race.get('name')}")
        lines.append("")
        lines.append(f"- Distance: `{race.get('distance')}`")
        lines.append(f"- Prediction: `{race.get('plan', {}).get('predicted_time')}` · pace `{race.get('plan', {}).get('predicted_pace')}`")
        for entry in race.get("plan", {}).get("entries", []):
            lines.append(f"- `{entry.get('date')} {entry.get('time_label')}` {entry.get('phase')}: {entry.get('recommendation')} ({entry.get('quantity')}; {entry.get('products_label')})")
        lines.append("")
    lines.extend(["## Hard Workouts", ""])
    for workout in payload.get("workouts", []):
        lines.append(f"### {workout.get('date')} · {workout.get('name')}")
        lines.append("")
        for entry in workout.get("plan", {}).get("entries", []):
            lines.append(f"- `{entry.get('date')} {entry.get('time_label')}` {entry.get('phase')}: {entry.get('recommendation')} ({entry.get('quantity')}; {entry.get('products_label')})")
        lines.append("")
    return "\n".join(lines)


def source_paths() -> list[Path]:
    paths = [PROFILE_PATH, SUPPLEMENTS_PATH, Path(__file__).resolve()]
    paths.extend(sorted(RACES_ROOT.glob("**/*.yaml")))
    paths.extend(sorted(WORKOUTS_ROOT.glob("*.yaml")))
    coach_path = ROOT / "planning" / "coach_decision.json"
    if coach_path.exists():
        paths.append(coach_path)
    return [path for path in paths if path.exists()]


def fueling_artifact_stale() -> bool:
    if not FUELING_JSON_PATH.exists() or not FUELING_MD_PATH.exists():
        return True
    artifact_mtime = min(FUELING_JSON_PATH.stat().st_mtime, FUELING_MD_PATH.stat().st_mtime)
    return any(path.stat().st_mtime > artifact_mtime for path in source_paths())


def write_fueling_artifacts(payload: dict[str, Any]) -> None:
    save_json(FUELING_JSON_PATH, payload)
    save_text(FUELING_MD_PATH, render_fueling_markdown(payload))


def load_or_build_fueling_payload(force: bool = False) -> dict[str, Any]:
    if not force and not fueling_artifact_stale():
        try:
            return json.loads(FUELING_JSON_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    payload = build_fueling_payload()
    write_fueling_artifacts(payload)
    return payload


def workout_fueling_lookup(payload: dict[str, Any], slug: str) -> dict[str, Any] | None:
    for item in payload.get("workouts", []):
        if str(item.get("slug") or "") == slug:
            return item.get("plan") if isinstance(item.get("plan"), dict) else item
    return None


def race_fueling_lookup(payload: dict[str, Any], race_id: str) -> dict[str, Any] | None:
    for item in payload.get("races", []):
        if str(item.get("id") or "") == race_id:
            return item.get("plan") if isinstance(item.get("plan"), dict) else item
    return None


if __name__ == "__main__":
    write_fueling_artifacts(build_fueling_payload())
