#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "system" / "capabilities" / "registry.yaml"
FRESHNESS_PATH = ROOT / "system" / "state" / "data_freshness.json"


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_command(command: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in command:
        normalized.append(date_token_to_value(item))
    if normalized and normalized[0] == "python":
        normalized[0] = sys.executable
    return normalized


def date_token_to_value(value: str) -> str:
    if value == "today":
        return datetime.now().date().isoformat()
    return value


@dataclass
class CapabilityResult:
    name: str
    attempted_refresh: bool
    refreshed: bool
    stale: bool
    warning: str | None
    error: str | None


class CapabilityEngine:
    def __init__(self) -> None:
        self.registry = load_yaml(REGISTRY_PATH).get("capabilities", {})
        self.freshness = load_json(FRESHNESS_PATH)
        self.freshness.setdefault("capabilities", {})

    def capability(self, name: str) -> dict[str, Any]:
        config = self.registry.get(name)
        if not isinstance(config, dict):
            raise KeyError(f"Unknown capability: {name}")
        return config

    def _state(self, name: str) -> dict[str, Any]:
        state = self.freshness["capabilities"].setdefault(name, {})
        return state

    def _is_stale(self, name: str) -> bool:
        config = self.capability(name)
        max_age_minutes = int(config.get("freshness", {}).get("max_age_minutes", 0))
        last_sync = self._state(name).get("last_successful_sync")
        if not last_sync:
            return True
        try:
            last_sync_dt = datetime.fromisoformat(last_sync)
        except ValueError:
            return True
        return utcnow() - last_sync_dt > timedelta(minutes=max_age_minutes)

    def _record(self, name: str, *, success: bool, error: str | None = None) -> None:
        state = self._state(name)
        state["last_attempted_sync"] = utcnow().isoformat()
        state["last_error"] = error
        if success:
            state["last_successful_sync"] = state["last_attempted_sync"]
        save_json(FRESHNESS_PATH, self.freshness)

    def _run_command(self, command: list[str]) -> tuple[bool, str | None]:
        result = subprocess.run(normalize_command(command), cwd=ROOT, check=False, capture_output=True, text=True)
        if result.returncode == 0:
            return True, None
        stderr = (result.stderr or result.stdout or "").strip()
        return False, stderr or f"Command failed with exit code {result.returncode}"

    def ensure_fresh(self, name: str) -> CapabilityResult:
        config = self.capability(name)
        strategy = str(config.get("freshness", {}).get("strategy") or "refresh_before_read")
        stale_before = self._is_stale(name)
        attempted_refresh = strategy in {"refresh_before_read", "refresh_before_decision"}
        refreshed = False
        warning = None
        error = None

        if attempted_refresh and stale_before:
            sync_command = config.get("sync", {}).get("command") or []
            post_command = config.get("sync", {}).get("post_command") or []
            success = True
            if sync_command:
                success, error = self._run_command(sync_command)
            if success and post_command:
                success, error = self._run_command(post_command)
            self._record(name, success=success, error=error)
            refreshed = success
            if not success and str(config.get("stale_behavior") or "") == "show_cached_with_warning":
                warning = f"{name}: usando cache local; no se pudo refrescar desde la fuente real."

        stale_after = self._is_stale(name)
        if stale_after and not warning and str(config.get("stale_behavior") or "") == "show_cached_with_warning":
            warning = f"{name}: datos potencialmente desactualizados."
        return CapabilityResult(
            name=name,
            attempted_refresh=attempted_refresh,
            refreshed=refreshed,
            stale=stale_after,
            warning=warning,
            error=error,
        )


def ensure_fresh(name: str) -> CapabilityResult:
    return CapabilityEngine().ensure_fresh(name)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/system/capability_engine.py <capability_name>")
    result = ensure_fresh(sys.argv[1])
    print(
        json.dumps(
            {
                "name": result.name,
                "attempted_refresh": result.attempted_refresh,
                "refreshed": result.refreshed,
                "stale": result.stale,
                "warning": result.warning,
                "error": result.error,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
