#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_CYCLE_PATH = ROOT / "planning" / "cycles" / "active.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def copy_if_exists(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive the active cycle into planning/cycles/<cycle_id>")
    parser.add_argument("--closing-note", default="", help="Optional closing note for the archived cycle")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    active = load_yaml(ACTIVE_CYCLE_PATH).get("cycle", {})
    if not active:
        raise SystemExit("No active cycle manifest found")
    cycle_id = str(active.get("id") or "").strip()
    if not cycle_id:
        raise SystemExit("Active cycle has no id")

    archive_root = ROOT / "planning" / "cycles" / cycle_id
    archive_root.mkdir(parents=True, exist_ok=True)

    copy_if_exists(ROOT / str(active.get("master_plan_path") or "planning/master_plan.md"), archive_root / "master_plan.md")
    copy_if_exists(ROOT / str(active.get("blocks_path") or "planning/blocks"), archive_root / "blocks")
    copy_if_exists(ROOT / str(active.get("weeks_path") or "planning/weeks"), archive_root / "weeks")
    copy_if_exists(ROOT / str(active.get("goal_gates_path") or "planning/goal_gates.yaml"), archive_root / "goal_gates.yaml")
    copy_if_exists(ROOT / "planning" / "coach_decision.json", archive_root / "coach_decision.json")
    copy_if_exists(ROOT / "planning" / "coach_decision.md", archive_root / "coach_decision.md")
    copy_if_exists(ROOT / "athlete" / "status_dashboard.md", archive_root / "status_dashboard.md")

    archived_manifest = {
        "cycle": {
            **active,
            "status": "closed",
            "closed_at": datetime.now(UTC).isoformat(),
            "closing_note": args.closing_note or None,
        }
    }
    save_yaml(archive_root / "cycle_manifest.yaml", archived_manifest)
    (archive_root / "closing_report.md").write_text(
        "# Closing Report\n\n"
        f"- Cycle id: `{cycle_id}`\n"
        f"- Closed at: `{archived_manifest['cycle']['closed_at']}`\n"
        f"- Note: {args.closing_note or '-'}\n",
        encoding="utf-8",
    )
    print(f"Archived active cycle into {archive_root.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
