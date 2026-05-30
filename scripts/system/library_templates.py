#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
LIBRARY_TEMPLATES_PATH = ROOT / "training" / "planned" / "workouts" / "library_run_templates.yaml"
TEMPLATE_KNOWLEDGE_MAP_PATH = ROOT / "planning" / "workout_template_knowledge_map.yaml"


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def load_library_templates() -> dict[str, Any]:
    payload = load_optional_yaml(LIBRARY_TEMPLATES_PATH).get("library", {})
    return payload if isinstance(payload, dict) else {}


def template_catalog() -> dict[str, dict[str, Any]]:
    templates = load_library_templates().get("templates", {})
    return templates if isinstance(templates, dict) else {}


def template_knowledge_map() -> dict[str, dict[str, Any]]:
    payload = load_optional_yaml(TEMPLATE_KNOWLEDGE_MAP_PATH).get("template_knowledge_map", {})
    return payload if isinstance(payload, dict) else {}
