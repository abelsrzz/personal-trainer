#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.system.athlete_state import write_athlete_state
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.athlete_state import write_athlete_state


ROOT = Path(__file__).resolve().parents[2]
GARMIN_IMPORT_ROOT = ROOT / "training" / "completed" / "imports" / "garmin"
PROFILE_IMPORT_PATH = GARMIN_IMPORT_ROOT / "profile" / "athlete_profile_snapshot.json"
PROFILE_YAML_PATH = ROOT / "athlete" / "profile.yaml"
HEALTH_YAML_PATH = ROOT / "athlete" / "health.yaml"
ZONES_YAML_PATH = ROOT / "athlete" / "zones.yaml"
SHOES_YAML_PATH = ROOT / "athlete" / "shoes.yaml"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_profile_snapshot() -> dict[str, Any]:
    if not PROFILE_IMPORT_PATH.exists():
        return {}
    payload = load_json(PROFILE_IMPORT_PATH)
    return payload if isinstance(payload, dict) else {}


def first_present(source: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    return None


def update_profile(snapshot: dict[str, Any]) -> bool:
    current = load_yaml(PROFILE_YAML_PATH)
    athlete = current.get("athlete", {})
    changed = False

    full_name = first_present(snapshot, ["full_name", "display_name", "name"])
    gender = first_present(snapshot, ["gender", "sex"])
    birth_date = first_present(snapshot, ["birth_date", "dob"])
    weight_kg = first_present(snapshot, ["weight_kg", "weight"])
    height_cm = first_present(snapshot, ["height_cm", "height"])
    training_days = first_present(snapshot, ["training_days"])
    preferred_long_training_days = first_present(snapshot, ["preferred_long_training_days"])

    updates = {
        "name": full_name,
        "sex": gender,
        "birth_date": birth_date,
        "weight_kg": weight_kg,
        "height_cm": height_cm,
    }
    for key, value in updates.items():
        if value is not None and athlete.get(key) != value:
            athlete[key] = value
            changed = True

    availability = athlete.get("availability", {}) if isinstance(athlete.get("availability"), dict) else {}
    if isinstance(training_days, list) and availability.get("garmin_training_days") != training_days:
        availability["garmin_training_days"] = training_days
        changed = True
    if isinstance(preferred_long_training_days, list) and availability.get("garmin_preferred_long_training_days") != preferred_long_training_days:
        availability["garmin_preferred_long_training_days"] = preferred_long_training_days
        changed = True
    if availability:
        athlete["availability"] = availability

    source = athlete.get("data_sources", {})
    garmin_source = source.get("garmin", {})
    garmin_source["last_sync"] = snapshot.get("synced_at") or utc_now()
    garmin_source["profile_snapshot"] = str(PROFILE_IMPORT_PATH.relative_to(ROOT))
    source["garmin"] = garmin_source
    athlete["data_sources"] = source
    current["athlete"] = athlete

    if changed:
        save_yaml(PROFILE_YAML_PATH, current)
    else:
        save_yaml(PROFILE_YAML_PATH, current)
    return changed


def update_health(snapshot: dict[str, Any]) -> bool:
    current = load_yaml(HEALTH_YAML_PATH)
    health = current.get("health", {})
    changed = False

    resting_hr = first_present(snapshot, ["resting_heart_rate", "resting_hr"])
    max_hr = first_present(snapshot, ["max_heart_rate", "max_hr"])
    vo2max = first_present(snapshot, ["vo2max", "vo2_max"])
    lactate_threshold_hr = first_present(snapshot, ["lactate_threshold_heart_rate"])

    garmin_data = health.get("garmin_metrics", {})
    desired = {
        "resting_hr": resting_hr,
        "max_hr": max_hr,
        "vo2max": vo2max,
        "lactate_threshold_hr": lactate_threshold_hr,
        "last_sync": snapshot.get("synced_at") or utc_now(),
    }
    for key, value in desired.items():
        if value is not None and garmin_data.get(key) != value:
            garmin_data[key] = value
            changed = True
    health["garmin_metrics"] = garmin_data
    current["health"] = health

    save_yaml(HEALTH_YAML_PATH, current)
    return changed


def update_zones(snapshot: dict[str, Any]) -> bool:
    current = load_yaml(ZONES_YAML_PATH)
    zones = current.get("zones", {})
    heart_rate = zones.get("heart_rate", {})
    changed = False

    resting_hr = first_present(snapshot, ["resting_heart_rate", "resting_hr"])
    max_hr = first_present(snapshot, ["max_heart_rate", "max_hr"])

    if resting_hr is not None and heart_rate.get("resting_hr") != resting_hr:
        heart_rate["resting_hr"] = resting_hr
        changed = True
    if max_hr is not None and heart_rate.get("max_hr") != max_hr:
        heart_rate["max_hr"] = max_hr
        changed = True

    source = zones.get("data_sources", {})
    garmin_source = source.get("garmin", {})
    garmin_source["last_sync"] = snapshot.get("synced_at") or utc_now()
    garmin_source["profile_snapshot"] = str(PROFILE_IMPORT_PATH.relative_to(ROOT))
    source["garmin"] = garmin_source
    zones["data_sources"] = source
    zones["heart_rate"] = heart_rate
    current["zones"] = zones

    save_yaml(ZONES_YAML_PATH, current)
    return changed


def update_shoes(snapshot: dict[str, Any]) -> bool:
    gear = snapshot.get("gear") or []
    if not isinstance(gear, list):
        return False

    current = load_yaml(SHOES_YAML_PATH)
    shoes = current.get("shoes", [])
    if not isinstance(shoes, list):
        shoes = []

    by_model = {str(item.get("model")): item for item in shoes if isinstance(item, dict) and item.get("model")}
    changed = False

    for item in gear:
        if not isinstance(item, dict):
            continue
        model = first_present(item, ["display_name", "model", "gear_name", "name"])
        if not model:
            continue
        distance_km = first_present(item, ["distance_km", "distance", "total_distance_km"])
        if distance_km is not None and float(distance_km) > 1000:
            distance_km = round(float(distance_km) / 1000.0, 3)
        existing = by_model.get(str(model))
        if existing is None:
            shoes.append(
                {
                    "model": model,
                    "usage": "Imported from Garmin; review manually",
                    "distance_km": distance_km or 0,
                    "notes": "Auto-imported from Garmin gear snapshot",
                }
            )
            changed = True
            continue
        if distance_km is not None and existing.get("distance_km") != distance_km:
            existing["distance_km"] = distance_km
            changed = True

    if changed:
        current["shoes"] = shoes
        save_yaml(SHOES_YAML_PATH, current)
    return changed


def main() -> None:
    snapshot = read_profile_snapshot()
    if not snapshot:
        raise SystemExit("No Garmin athlete profile snapshot found")

    result = {
        "profile_updated": update_profile(snapshot),
        "health_updated": update_health(snapshot),
        "zones_updated": update_zones(snapshot),
        "shoes_updated": update_shoes(snapshot),
        "source": str(PROFILE_IMPORT_PATH.relative_to(ROOT)),
    }
    write_athlete_state()
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
