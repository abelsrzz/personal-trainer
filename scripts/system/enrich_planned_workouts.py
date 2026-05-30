#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.system.workout_knowledge import match_workout_knowledge
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.workout_knowledge import match_workout_knowledge

from scripts.system.library_templates import template_knowledge_map


ROOT = Path(__file__).resolve().parents[2]
WORKOUTS_DIR = ROOT / "training" / "planned" / "workouts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist workout knowledge metadata into planned workout YAML files")
    parser.add_argument("--start-date", default="", help="Optional YYYY-MM-DD inclusive lower bound")
    parser.add_argument("--end-date", default="", help="Optional YYYY-MM-DD inclusive upper bound")
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def classify_session_kind(payload: dict[str, Any]) -> str:
    sport = str(payload.get("sport") or "running").strip().lower()
    if sport in {"mobility", "stretching", "other"}:
        return "strength"
    name = str(payload.get("name") or "").lower()
    description = str(payload.get("description") or "").lower()
    steps = payload.get("steps") or []
    step_text = " ".join(str((step or {}).get("description") or "") for step in steps if isinstance(step, dict)).lower()
    text = " ".join([name, description, step_text])
    total_distance = sum(float((step or {}).get("distance_m") or 0.0) for step in steps if isinstance(step, dict))
    if any(keyword in text for keyword in ["recuperacion", "regenerativo", "reintroduccion", "post-competicion"]):
        return "recovery"
    if any(keyword in text for keyword in ["tirada larga", "long run"]) or total_distance >= 14000:
        return "long_run"
    if any(keyword in text for keyword in ["fuerza", "movilidad", "estiramientos", "strength"]):
        return "strength"
    if any(keyword in text for keyword in ["carrera", "race"]):
        return "race"
    if any(keyword in text for keyword in ["interval", "tempo", "series", "cuesta", "fartlek", "umbral", "bloques"]):
        return "quality"
    return "easy"


def infer_template_id_from_knowledge(knowledge_id: str) -> str | None:
    candidates = []
    for template_id, config in template_knowledge_map().items():
        if not isinstance(config, dict):
            continue
        if knowledge_id in (config.get("preferred_knowledge_ids") or []):
            candidates.append(template_id)
    return candidates[0] if len(candidates) == 1 else None


def trusted_template_id(workout: dict[str, Any]) -> str | None:
    source = str(workout.get("template_id_source") or "").strip().lower()
    template_id = str(workout.get("template_id") or "").strip()
    if template_id and source in {"planner", "manual", "library"}:
        return template_id
    return None


def main() -> None:
    args = parse_args()
    changed: list[str] = []
    for path in sorted(WORKOUTS_DIR.glob("*.yaml")):
        if path.name in {"library_run_templates.yaml", "workout_template.yaml"}:
            continue
        payload = load_yaml(path)
        workout = payload.get("workout") if isinstance(payload.get("workout"), dict) else None
        if not isinstance(workout, dict):
            continue
        schedule_date = str(workout.get("schedule_date") or "")
        if args.start_date and schedule_date and schedule_date < args.start_date:
            continue
        if args.end_date and schedule_date and schedule_date > args.end_date:
            continue
        kind = classify_session_kind(workout)
        trusted_template = trusted_template_id(workout)
        lookup_payload = {key: value for key, value in workout.items() if key not in {"knowledge_id", "knowledge_label", "primary_goal", "template_id", "template_id_source"}}
        knowledge = match_workout_knowledge(lookup_payload, kind, template_id=trusted_template, prefer_existing=False)
        if not knowledge:
            stale_keys = ["template_id", "template_id_source", "knowledge_id", "knowledge_label", "primary_goal"]
            had_stale = any(workout.get(key) is not None for key in stale_keys)
            for key in stale_keys:
                workout.pop(key, None)
            if had_stale:
                payload["workout"] = workout
                save_yaml(path, payload)
                changed.append(str(path.relative_to(ROOT)))
            continue
        next_label = knowledge.get("label")
        next_goal = knowledge.get("primary_goal")
        next_knowledge_id = knowledge.get("id")
        next_template_id = trusted_template or infer_template_id_from_knowledge(str(next_knowledge_id or ""))
        if workout.get("knowledge_label") == next_label and workout.get("primary_goal") == next_goal and workout.get("knowledge_id") == next_knowledge_id and workout.get("template_id") == next_template_id:
            continue
        if next_template_id:
            workout["template_id"] = next_template_id
            workout["template_id_source"] = "planner" if trusted_template else "inferred"
        workout["knowledge_id"] = next_knowledge_id
        workout["knowledge_label"] = next_label
        workout["primary_goal"] = next_goal
        payload["workout"] = workout
        save_yaml(path, payload)
        changed.append(str(path.relative_to(ROOT)))
    print(json.dumps({"changed": changed, "count": len(changed)}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
