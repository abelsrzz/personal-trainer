#!/usr/bin/env python3

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
AUTOMATION_SAFETY_PATH = ROOT / "system" / "automation_safety.yaml"
INTERACTIVE_SOURCES = {"manual", "web", "telegram", "chat"}


def load_policy() -> dict[str, Any]:
    if not AUTOMATION_SAFETY_PATH.exists():
        return {}
    with AUTOMATION_SAFETY_PATH.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload.get("automation_safety", {}) if isinstance(payload, dict) else {}


@dataclass
class PolicyDecision:
    action: str
    allowed: bool
    reason: str
    level: str
    source: str


class PolicyGateError(RuntimeError):
    pass


def decide(action: str, *, source: str = "manual", confirmed: bool = False) -> PolicyDecision:
    policy = load_policy()
    action_name = str(action or "").strip()
    source_name = str(source or "manual").strip().lower()
    allow_auto = set(policy.get("allow_auto") or [])
    require_confirmation = set(policy.get("require_confirmation") or [])
    never_auto = set(policy.get("never_auto") or [])

    if action_name in never_auto:
        if source_name in INTERACTIVE_SOURCES and confirmed:
            return PolicyDecision(action=action_name, allowed=True, reason="Accion sensible permitida con confirmacion explicita.", level="confirmed", source=source_name)
        return PolicyDecision(action=action_name, allowed=False, reason="La politica marca esta accion como no automatizable.", level="blocked", source=source_name)

    if action_name in require_confirmation:
        if source_name in INTERACTIVE_SOURCES or confirmed:
            return PolicyDecision(action=action_name, allowed=True, reason="Accion permitida en contexto interactivo o confirmada.", level="confirmed", source=source_name)
        return PolicyDecision(action=action_name, allowed=False, reason="La politica requiere confirmacion explicita para esta accion.", level="confirmation_required", source=source_name)

    if action_name in allow_auto or source_name in INTERACTIVE_SOURCES:
        return PolicyDecision(action=action_name, allowed=True, reason="Accion permitida por la politica actual.", level="allowed", source=source_name)

    return PolicyDecision(action=action_name, allowed=True, reason="Accion no clasificada; permitida por defecto fuera de lista bloqueada.", level="allowed", source=source_name)


def enforce(action: str, *, source: str = "manual", confirmed: bool = False) -> PolicyDecision:
    decision = decide(action, source=source, confirmed=confirmed)
    if not decision.allowed:
        raise PolicyGateError(decision.reason)
    return decision


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Evaluate or enforce automation safety policy")
    parser.add_argument("action", help="Action name to evaluate")
    parser.add_argument("--source", default="manual", help="Trigger source")
    parser.add_argument("--confirmed", action="store_true", help="Mark the action as explicitly confirmed")
    parser.add_argument("--enforce", action="store_true", help="Exit non-zero when the action is blocked")
    args = parser.parse_args()

    try:
        decision = enforce(args.action, source=args.source, confirmed=bool(args.confirmed)) if args.enforce else decide(args.action, source=args.source, confirmed=bool(args.confirmed))
    except PolicyGateError as exc:
        sys.stdout.write(json.dumps({"ok": False, "action": args.action, "source": args.source, "reason": str(exc)}, indent=2, ensure_ascii=True) + "\n")
        raise SystemExit(1)

    sys.stdout.write(
        json.dumps(
            {
                "ok": decision.allowed,
                "action": decision.action,
                "source": decision.source,
                "level": decision.level,
                "reason": decision.reason,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
