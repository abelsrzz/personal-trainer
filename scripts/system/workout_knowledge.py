#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from scripts.system.library_templates import template_knowledge_map


ROOT = Path(__file__).resolve().parents[2]
WORKOUT_KNOWLEDGE_PATH = ROOT / "planning" / "workout_knowledge.yaml"


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def normalize_text(*values: Any) -> str:
    combined = " ".join(str(value or "") for value in values).lower()
    for source, target in {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "-": " ",
        "/": " ",
        "@": " ",
        "+": " + ",
    }.items():
        combined = combined.replace(source, target)
    return " ".join(combined.split())


def stable_slug(value: str) -> str:
    normalized = normalize_text(value)
    allowed = []
    for char in normalized:
        if char.isalnum():
            allowed.append(char)
        else:
            allowed.append("_")
    slug = "".join(allowed)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def load_workout_knowledge() -> dict[str, Any]:
    payload = load_optional_yaml(WORKOUT_KNOWLEDGE_PATH).get("workout_knowledge", {})
    return payload if isinstance(payload, dict) else {}


def goal_label(goal: str) -> str:
    return str(goal or "").replace("_", " ").strip().capitalize()


def parse_duration_text(value: str | None) -> float | None:
    if not value:
        return None
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return None


def pace_text_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("/km"):
        text = text[:-3]
    return parse_duration_text(text)


def derived_primary_goal(payload: dict[str, Any], session_kind: str, fallback_goal: str | None = None) -> str | None:
    if session_kind not in {"quality", "easy"}:
        return fallback_goal
    steps = payload.get("steps") or []
    if not isinstance(steps, list):
        return fallback_goal
    pace_targets: list[float] = []
    has_warmup_or_cooldown = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("step_type") in {"warmup", "cooldown"}:
            has_warmup_or_cooldown = True
        target = step.get("target") or {}
        if step.get("type") == "repeat_group":
            nested = step.get("steps") or []
            for nested_step in nested:
                if not isinstance(nested_step, dict):
                    continue
                nested_target = nested_step.get("target") or {}
                if nested_target.get("type") == "pace_range":
                    values = [
                        pace_text_to_seconds(nested_target.get("min_pace")),
                        pace_text_to_seconds(nested_target.get("max_pace")),
                    ]
                    valid = [value for value in values if value and value > 0]
                    if valid:
                        pace_targets.append(sum(valid) / len(valid))
            continue
        if target.get("type") == "pace_range":
            values = [
                pace_text_to_seconds(target.get("min_pace")),
                pace_text_to_seconds(target.get("max_pace")),
            ]
            valid = [value for value in values if value and value > 0]
            if valid:
                pace_targets.append(sum(valid) / len(valid))
    if not pace_targets:
        return fallback_goal
    target_pace_s = sum(pace_targets) / len(pace_targets)
    if has_warmup_or_cooldown and target_pace_s <= 320:
        return "Umbral lactico"
    if target_pace_s <= 255:
        return "Ritmo 5k"
    if target_pace_s <= 285:
        return "Ritmo 10k"
    if target_pace_s <= 320:
        return "Umbral lactico"
    return fallback_goal


def knowledge_entry_id(entry: dict[str, Any]) -> str | None:
    explicit = str(entry.get("id") or "").strip()
    if explicit:
        return explicit
    label = str(entry.get("label") or "").strip()
    return stable_slug(label) if label else None


def iter_knowledge_entries() -> list[dict[str, Any]]:
    knowledge = load_workout_knowledge()
    categories = knowledge.get("categories") if isinstance(knowledge.get("categories"), dict) else {}
    entries: list[dict[str, Any]] = []
    for category_key, raw_entries in categories.items():
        if isinstance(raw_entries, dict):
            raw_entries = raw_entries.get("sessions") or []
        if not isinstance(raw_entries, list):
            continue
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            entry_id = knowledge_entry_id(entry)
            if not entry_id:
                continue
            entries.append({**entry, "id": entry_id, "category": category_key})
    return entries


def knowledge_entry_by_id(entry_id: str) -> dict[str, Any] | None:
    target = str(entry_id or "").strip()
    if not target:
        return None
    for entry in iter_knowledge_entries():
        if entry.get("id") == target:
            return entry
    return None


def knowledge_entry_by_label(label: str) -> dict[str, Any] | None:
    target = str(label or "").strip()
    if not target:
        return None
    normalized_target = normalize_text(target)
    for entry in iter_knowledge_entries():
        if normalize_text(entry.get("label")) == normalized_target:
            return entry
    return None


def summarized_entry(entry: dict[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    result["goal_labels"] = [goal_label(goal) for goal in result.get("goals") or []]
    result["primary_goal"] = result["goal_labels"][0] if result.get("goal_labels") else None
    result["summary"] = (
        f"Esta sesion se usa sobre todo para {str(result['primary_goal']).lower()}."
        if result.get("primary_goal")
        else "Esta sesion tiene un objetivo operativo reconocido."
    )
    if len(result.get("goal_labels") or []) > 1:
        secondaries = [item.lower() for item in result["goal_labels"][1:3] if item]
        if secondaries:
            result["summary"] += f" Tambien aporta {', '.join(secondaries)}."
    return result


def apply_primary_goal_override(match: dict[str, Any], payload: dict[str, Any], session_kind: str) -> dict[str, Any]:
    result = dict(match)
    result["primary_goal"] = derived_primary_goal(payload, session_kind, result.get("primary_goal"))
    primary_goal = str(result.get("primary_goal") or "").strip()
    secondary = [item.lower() for item in (result.get("goal_labels") or [])[1:3] if item]
    result["summary"] = f"Esta sesion se usa sobre todo para {primary_goal.lower()}." if primary_goal else "Esta sesion tiene un objetivo operativo reconocido."
    if secondary:
        result["summary"] += f" Tambien aporta {', '.join(secondary)}."
    return result


def easy_recovery_fallback(payload: dict[str, Any], session_kind: str) -> dict[str, Any] | None:
    if session_kind not in {"easy", "recovery"}:
        return None
    description = normalize_text(payload.get("name"), payload.get("description"), json.dumps(payload.get("steps") or [], ensure_ascii=False))
    duration_s = int(payload.get("estimated_duration_s") or 0)
    duration_min = duration_s / 60.0 if duration_s else 0.0
    candidate_id = None
    if "post competicion" in description:
        candidate_id = "25_suave_post_competicion"
    elif any(keyword in description for keyword in ["reintroduccion", "recuperacion", "regenerativo"]):
        candidate_id = "30_regenerativo_muy_suave" if duration_min <= 35 else "40_regenerativo_muy_suave"
    elif "z2" in description:
        if duration_min >= 80:
            candidate_id = "90_en_z2_estable"
        elif duration_min >= 60:
            candidate_id = "70_en_z2_estable"
        else:
            candidate_id = "50_en_z2_estable"
    elif any(keyword in description for keyword in ["progresivos", "rectas"]):
        candidate_id = "45_suave_6x100_progresivos" if duration_min <= 50 else "60_suave_8x100_progresivos"
    else:
        if duration_min <= 35:
            candidate_id = "30_suave"
        elif duration_min <= 45:
            candidate_id = "40_suave"
        elif duration_min <= 55:
            candidate_id = "50_suave"
        elif duration_min <= 65:
            candidate_id = "60_suave"
        elif duration_min <= 80:
            candidate_id = "75_suave"
        elif duration_min <= 100:
            candidate_id = "90_suave"
        elif duration_min <= 135:
            candidate_id = "2h_suave"
        else:
            candidate_id = "2h30_suave"
    return summarized_entry(knowledge_entry_by_id(candidate_id)) if candidate_id and knowledge_entry_by_id(candidate_id) else None


def match_workout_knowledge(payload: dict[str, Any], session_kind: str, template_id: str | None = None, prefer_existing: bool = True) -> dict[str, Any] | None:
    if prefer_existing:
        explicit_knowledge_id = str(payload.get("knowledge_id") or "").strip()
        if explicit_knowledge_id:
            entry = knowledge_entry_by_id(explicit_knowledge_id)
            if entry:
                return apply_primary_goal_override(summarized_entry(entry), payload, session_kind)

        explicit_knowledge_label = str(payload.get("knowledge_label") or "").strip()
        if explicit_knowledge_label:
            entry = knowledge_entry_by_label(explicit_knowledge_label)
            if entry:
                return apply_primary_goal_override(summarized_entry(entry), payload, session_kind)

    resolved_template_id = str(template_id or payload.get("template_id") or "").strip()
    if resolved_template_id:
        mapping = template_knowledge_map().get(resolved_template_id) if isinstance(template_knowledge_map().get(resolved_template_id), dict) else None
        for knowledge_id in (mapping or {}).get("preferred_knowledge_ids", []):
            entry = knowledge_entry_by_id(str(knowledge_id))
            if entry:
                return apply_primary_goal_override(summarized_entry(entry), payload, session_kind)

    name_text = str(payload.get("name") or "")
    description_text = str(payload.get("description") or "")
    steps = payload.get("steps") or []
    if session_kind in {"strength", "race", "rest"} and not resolved_template_id:
        return None
    haystack = normalize_text(name_text, description_text, json.dumps(steps, ensure_ascii=False))
    best_match = None
    best_score = 0
    for entry in iter_knowledge_entries():
        label = str(entry.get("label") or "").strip()
        if not label:
            continue
        goals = entry.get("goals") if isinstance(entry.get("goals"), list) else []
        if session_kind in {"easy", "recovery"} and not any(goal in goals for goal in {"recuperacion", "base_aerobica", "resistencia_aerobica", "eficiencia_aerobica", "fondo_largo"}):
            continue
        score = 0
        normalized_label = normalize_text(label)
        if normalized_label and normalized_label in haystack:
            score += len(normalized_label) + 10
        for token in [piece.strip() for piece in normalized_label.replace("+", " ").split() if len(piece.strip()) >= 3]:
            if token in haystack:
                score += 1
        if session_kind == "quality" and any(goal in goals for goal in {"vo2max", "umbral_lactico", "ritmo_10k", "ritmo_5k", "potencia_aerobica"}):
            score += 3
        if session_kind == "long_run" and any(goal in goals for goal in {"fondo_largo", "resistencia_especifica_maraton", "resistencia_especifica_21k"}):
            score += 3
        if session_kind in {"easy", "recovery"} and any(goal in goals for goal in {"recuperacion", "base_aerobica", "resistencia_aerobica", "eficiencia_aerobica"}):
            score += 3
        if session_kind == "strength":
            score -= 100
        if session_kind == "race":
            score -= 100
        if score > best_score and score >= 8:
            best_score = score
            best_match = entry
    if not best_match:
        fallback = easy_recovery_fallback(payload, session_kind)
        if fallback:
            return apply_primary_goal_override(fallback, payload, session_kind)
        return fallback
    return apply_primary_goal_override(summarized_entry(best_match), payload, session_kind)
