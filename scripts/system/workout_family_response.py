#!/usr/bin/env python3

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REVIEW_ROOT = ROOT / "training" / "completed" / "reviews"
OUTPUT_PATH = ROOT / "system" / "state" / "workout_family_response.json"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def review_family(payload: dict[str, Any]) -> str | None:
    planned = payload.get("planned", {}) if isinstance(payload.get("planned"), dict) else {}
    for key in ("knowledge_id", "knowledge_label", "primary_goal", "session_kind"):
        value = planned.get(key)
        if value:
            return str(value)
    return None


def build_workout_family_response() -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "scores": [], "risks": defaultdict(int), "latest_date": None, "examples": []})
    for path in sorted(REVIEW_ROOT.glob("*.analysis.json")):
        payload = load_json(path)
        if not payload:
            continue
        family = review_family(payload)
        if not family:
            continue
        item = grouped[family]
        item["count"] += 1
        if payload.get("score") is not None:
            item["scores"].append(int(payload.get("score") or 0))
        risk = str(payload.get("risk_level") or "unknown")
        item["risks"][risk] += 1
        review_date = str((payload.get("planned") or {}).get("date") or "")
        if review_date and (item["latest_date"] is None or review_date >= item["latest_date"]):
            item["latest_date"] = review_date
        if len(item["examples"]) < 3:
            item["examples"].append(path.stem.replace(".analysis", ""))
    families = []
    for family, item in sorted(grouped.items()):
        scores = item.pop("scores")
        avg_score = round(sum(scores) / len(scores), 2) if scores else None
        risks = dict(item.pop("risks"))
        families.append({"family": family, "avg_score": avg_score, "risks": risks, **item})
    return {"generated_at": utcnow_iso(), "families": families}


def write_workout_family_response() -> dict[str, Any]:
    payload = build_workout_family_response()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    print(json.dumps(write_workout_family_response(), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
