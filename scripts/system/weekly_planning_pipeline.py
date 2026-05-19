#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_WEEK_PATH = ROOT / "planning" / "weeks" / "semana_actual.md"
PREPARED_WEEKS_DIR = ROOT / "planning" / "weeks" / "prepared"
ARCHIVED_WEEKS_DIR = ROOT / "planning" / "weeks" / "archived"
STATE_PATH = ROOT / "system" / "state" / "weekly_planning_state.json"
TELEGRAM_CONFIG_PATH = ROOT / "telegram" / "bot_config.yaml"
PDF_SCRIPT = ROOT / "scripts" / "notifications" / "semana_pdf_telegram.py"
GARMIN_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
ENRICH_WORKOUTS_SCRIPT = ROOT / "scripts" / "system" / "enrich_planned_workouts.py"
DEFAULT_MODEL = "openai/gpt-5.4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weekly planning pipeline with safe prepare/activate flow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_next = subparsers.add_parser("plan-next", help="Prepare the next week without touching the active one")
    plan_next.add_argument("--force", action="store_true", help="Regenerate even if the next week was already prepared")
    plan_next.add_argument("--source", default="manual", help="Trigger source label (manual, web, timer)")

    activate = subparsers.add_parser("activate-next", help="Activate the prepared next week")
    activate.add_argument("--source", default="manual", help="Trigger source label (manual, web, timer)")
    activate.add_argument("--week-start", default="", help="Optional explicit prepared week start date YYYY-MM-DD")

    status = subparsers.add_parser("status", help="Show pipeline status as JSON")
    status.add_argument("--week-start", default="", help="Optional explicit week start date YYYY-MM-DD")
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"prepared_weeks": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_week_date_window(content: str) -> tuple[date | None, date | None]:
    match = re.search(r"Del `(?P<start>\d{4}-\d{2}-\d{2})` al `(?P<end>\d{4}-\d{2}-\d{2})`", content)
    if not match:
        return None, None
    return parse_iso_date(match.group("start")), parse_iso_date(match.group("end"))


def active_week_title(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "semana_actual"


def next_monday_after(day_value: date) -> date:
    offset = 7 - day_value.weekday()
    if offset <= 0:
        offset += 7
    return day_value + timedelta(days=offset)


def week_bounds_for_next_range(active_end: date) -> tuple[date, date]:
    start = next_monday_after(active_end)
    return start, start + timedelta(days=6)


def prepared_week_path(start: date, end: date) -> Path:
    return PREPARED_WEEKS_DIR / str(start.year) / f"{start.isoformat()}_{end.isoformat()}.md"


def archived_week_path(start: date, end: date, title: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_") or "semana"
    return ARCHIVED_WEEKS_DIR / str(start.year) / f"{start.isoformat()}_{end.isoformat()}_{slug}.md"


def current_active_week_info() -> dict[str, Any]:
    content = read_text(ACTIVE_WEEK_PATH)
    start_date, end_date = parse_week_date_window(content)
    return {
        "exists": ACTIVE_WEEK_PATH.exists(),
        "path": display_path(ACTIVE_WEEK_PATH),
        "title": active_week_title(content),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }


def opencode_model() -> str:
    config = load_yaml(TELEGRAM_CONFIG_PATH)
    remote = config.get("opencode_remote", {}) if isinstance(config.get("opencode_remote"), dict) else {}
    model = str(remote.get("model") or os.getenv("OPENCODE_MODEL") or DEFAULT_MODEL).strip()
    return model or DEFAULT_MODEL


def build_planning_prompt(target_start: date, target_end: date, output_path: Path) -> str:
    return (
        "Actua como el planificador semanal de este repositorio y trabaja directamente sobre los archivos del proyecto. "
        "Tu objetivo es preparar la siguiente semana sin tocar planning/weeks/semana_actual.md.\n\n"
        f"Semana objetivo: del {target_start.isoformat()} al {target_end.isoformat()} (lunes a domingo).\n"
        f"Archivo de salida obligatorio: {display_path(output_path)}\n\n"
        "Instrucciones obligatorias:\n"
        "1. Lee AGENT.md, .agents/memory/project_snapshot.md, .agents/workflows/weekly_coaching_cycle.md, planning/context_automation_policy.md, planning/coaching_playbook.md, planning/workout_knowledge.yaml, planning/workout_template_knowledge_map.yaml, planning/session_selection_matrix.yaml, planning/workout_evaluation_rules.md, athlete/response_profile.yaml, planning/master_plan.md, la semana activa actual y el bloque relevante.\n"
        "2. Usa tambien athlete/profile.yaml, athlete/preferences.yaml, athlete/zones.yaml, athlete/shoes.yaml, athlete/health.yaml, athlete/shin_tracker.yaml, planning/goal_gates.yaml y carreras relevantes.\n"
        "3. Genera la semana objetivo en el archivo indicado con el mismo formato operativo habitual del proyecto: titulo, fechas, contexto si hace falta, tabla diaria con dia, descripcion, distancia, ritmo o FC y zapatillas.\n"
        "4. No modifiques planning/weeks/semana_actual.md. Solo prepara la siguiente semana en el archivo de salida.\n"
        "5. Crea o actualiza los YAML necesarios en training/planned/workouts/ para las sesiones fechadas de esa semana. Siempre que puedas, incluye `template_id`, `knowledge_id`, `knowledge_label` y `primary_goal` alineados con training/planned/workouts/library_run_templates.yaml, planning/workout_template_knowledge_map.yaml y planning/workout_knowledge.yaml. Si la sesion es de bicicleta, usa `sport: cycling`, no `fitness_equipment`. Si la sesion es de natacion, usa `sport: swimming`.\n"
        "6. Mantente conservador con la tibia, la decision del coach y las reglas del ciclo.\n"
        "7. Al terminar, deja los archivos escritos en el repositorio.\n"
    )


def run_command(command: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)


def execute_opencode_planning(target_start: date, target_end: date, output_path: Path) -> tuple[bool, str, dict[str, Any]]:
    prompt = build_planning_prompt(target_start, target_end, output_path)
    command = ["opencode", "run", "--dir", str(ROOT), "--model", opencode_model(), "--print-logs", prompt]
    try:
        result = run_command(command)
    except FileNotFoundError:
        return False, "No se encontro el binario `opencode`; no puedo preparar la siguiente semana automaticamente.", {"command": " ".join(command[:-1]), "returncode": None}
    detail = {
        "command": " ".join(command[:-1]),
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }
    if result.returncode != 0:
        return False, "OpenCode no pudo preparar la siguiente semana.", detail
    if not output_path.exists():
        return False, "OpenCode termino, pero no se genero el archivo esperado de la siguiente semana.", detail
    generated_start, generated_end = parse_week_date_window(read_text(output_path))
    if generated_start != target_start or generated_end != target_end:
        return False, "La semana preparada no coincide con el rango objetivo esperado.", detail
    return True, "Siguiente semana preparada.", detail


def planned_upload_record_path(workout_path: Path, workout_date: str) -> Path:
    return ROOT / "training" / "planned" / "workouts" / workout_date / f"{workout_path.stem}.garmin_upload.json"


def workout_yaml_files_for_range(target_start: date, target_end: date) -> list[Path]:
    items: list[Path] = []
    for path in sorted((ROOT / "training" / "planned" / "workouts").glob("*.yaml")):
        if path.name in {"library_run_templates.yaml", "workout_template.yaml"}:
            continue
        payload = load_yaml(path).get("workout", {})
        workout_date = parse_iso_date(str(payload.get("schedule_date") or ""))
        if workout_date and target_start <= workout_date <= target_end:
            items.append(path)
    return items


def should_sync_workout(workout_path: Path, workout_date: str) -> bool:
    upload_path = planned_upload_record_path(workout_path, workout_date)
    if not upload_path.exists():
        return True
    return workout_path.stat().st_mtime > upload_path.stat().st_mtime


def sync_workouts_to_garmin(target_start: date, target_end: date) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for workout_path in workout_yaml_files_for_range(target_start, target_end):
        payload = load_yaml(workout_path).get("workout", {})
        workout_date = str(payload.get("schedule_date") or "").strip()
        if not workout_date:
            continue
        if not should_sync_workout(workout_path, workout_date):
            results.append({"file": display_path(workout_path), "status": "skipped", "message": "Sin cambios frente al ultimo upload registrado."})
            continue
        command = [sys.executable, str(GARMIN_SYNC_SCRIPT), "schedule-workout-file", str(workout_path)]
        result = run_command(command, timeout=300)
        ok = result.returncode == 0
        results.append(
            {
                "file": display_path(workout_path),
                "status": "ok" if ok else "error",
                "message": (result.stdout or result.stderr or "Sin salida").strip()[-1000:],
            }
        )
    synced = sum(1 for item in results if item["status"] == "ok")
    failed = sum(1 for item in results if item["status"] == "error")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    return {"items": results, "synced": synced, "failed": failed, "skipped": skipped}


def enrich_workouts_with_knowledge(target_start: date, target_end: date) -> tuple[bool, dict[str, Any]]:
    command = [sys.executable, str(ENRICH_WORKOUTS_SCRIPT), "--start-date", target_start.isoformat(), "--end-date", target_end.isoformat()]
    result = run_command(command, timeout=300)
    if result.returncode != 0:
        return False, {"command": " ".join(command), "returncode": result.returncode, "stderr": (result.stderr or result.stdout or "").strip()[-1000:]}
    try:
        payload = json.loads((result.stdout or "{}").strip() or "{}")
    except json.JSONDecodeError:
        payload = {"raw_output": (result.stdout or "").strip()[-1000:]}
    return True, payload if isinstance(payload, dict) else {}


def send_active_week_pdf() -> tuple[bool, str]:
    command = [sys.executable, str(PDF_SCRIPT), "send-now", "--force"]
    result = run_command(command, timeout=300)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "Error enviando PDF").strip()[-1000:]
    return True, (result.stdout or "PDF generado y enviado.").strip()[-1000:]


def ensure_prepared_entry(state: dict[str, Any], target_start: date, target_end: date, path: Path, source: str) -> dict[str, Any]:
    prepared = state.setdefault("prepared_weeks", {})
    key = target_start.isoformat()
    entry = prepared.get(key) if isinstance(prepared.get(key), dict) else {}
    entry.update(
        {
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "path": display_path(path),
            "status": entry.get("status") or "prepared",
            "updated_at": datetime.now().isoformat(),
            "source": source,
        }
    )
    prepared[key] = entry
    return entry


def plan_next_week(force: bool, source: str) -> dict[str, Any]:
    state = load_state()
    active = current_active_week_info()
    active_end = parse_iso_date(active.get("end_date"))
    if not active_end:
        return {"ok": False, "message": "No se pudo resolver el rango de la semana activa.", "code": "active_week_missing_dates"}
    target_start, target_end = week_bounds_for_next_range(active_end)
    output_path = prepared_week_path(target_start, target_end)
    if output_path.exists() and not force:
        entry = ensure_prepared_entry(state, target_start, target_end, output_path, source)
        state["last_plan"] = {"status": "already_prepared", "target_start": target_start.isoformat(), "target_end": target_end.isoformat(), "updated_at": datetime.now().isoformat(), "source": source}
        save_state(state)
        return {"ok": True, "message": "La siguiente semana ya estaba preparada; no se ha pisado nada.", "code": "already_prepared", "prepared_week": entry}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, message, detail = execute_opencode_planning(target_start, target_end, output_path)
    if not ok:
        state["last_plan"] = {"status": "error", "target_start": target_start.isoformat(), "target_end": target_end.isoformat(), "updated_at": datetime.now().isoformat(), "source": source, "detail": detail}
        save_state(state)
        return {"ok": False, "message": message, "code": "planning_failed", "detail": detail}
    enrich_ok, enrich_detail = enrich_workouts_with_knowledge(target_start, target_end)
    garmin_sync = sync_workouts_to_garmin(target_start, target_end)
    entry = ensure_prepared_entry(state, target_start, target_end, output_path, source)
    entry["status"] = "prepared"
    entry["generated_at"] = datetime.now().isoformat()
    entry["knowledge_enrichment"] = {"ok": enrich_ok, **enrich_detail}
    entry["garmin_sync"] = garmin_sync
    entry["planner_detail"] = {k: v for k, v in detail.items() if k != "stdout"}
    state["last_plan"] = {"status": "prepared", "target_start": target_start.isoformat(), "target_end": target_end.isoformat(), "updated_at": datetime.now().isoformat(), "source": source, "knowledge_enrichment": {"ok": enrich_ok, **enrich_detail}, "garmin_sync": garmin_sync}
    save_state(state)
    return {"ok": True, "message": message, "code": "prepared", "prepared_week": entry, "garmin_sync": garmin_sync}


def activate_prepared_week(source: str, week_start: str = "") -> dict[str, Any]:
    state = load_state()
    active = current_active_week_info()
    active_start = parse_iso_date(active.get("start_date"))
    active_end = parse_iso_date(active.get("end_date"))
    reference_end = active_end
    if week_start:
        target_start = parse_iso_date(week_start)
        if not target_start:
            return {"ok": False, "message": "Fecha de semana preparada no valida.", "code": "invalid_week_start"}
        prepared_entry = state.get("prepared_weeks", {}).get(target_start.isoformat()) if isinstance(state.get("prepared_weeks"), dict) else None
        target_end = parse_iso_date((prepared_entry or {}).get("end_date")) if isinstance(prepared_entry, dict) else None
    else:
        if not reference_end:
            return {"ok": False, "message": "No se pudo resolver el siguiente rango a activar.", "code": "active_week_missing_dates"}
        target_start, target_end = week_bounds_for_next_range(reference_end)
        prepared_entry = state.get("prepared_weeks", {}).get(target_start.isoformat()) if isinstance(state.get("prepared_weeks"), dict) else None
    if not target_end:
        return {"ok": False, "message": "No existe una semana preparada valida para activar.", "code": "prepared_week_missing"}
    prepared_path = prepared_week_path(target_start, target_end)
    if not prepared_path.exists():
        return {"ok": False, "message": "No se encontro el archivo de la semana preparada.", "code": "prepared_file_missing"}
    if active_start and active_end and (active_start.isoformat(), active_end.isoformat()) == (target_start.isoformat(), target_end.isoformat()):
        return {"ok": True, "message": "La semana objetivo ya es la activa; no se ha cambiado nada.", "code": "already_active"}
    archived_path = None
    if ACTIVE_WEEK_PATH.exists() and active_start and active_end:
        archived_path = archived_week_path(active_start, active_end, active.get("title") or "semana")
        archived_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ACTIVE_WEEK_PATH, archived_path)
    shutil.copy2(prepared_path, ACTIVE_WEEK_PATH)
    pdf_ok, pdf_message = send_active_week_pdf()
    garmin_sync = sync_workouts_to_garmin(target_start, target_end)
    prepared_weeks = state.setdefault("prepared_weeks", {})
    entry = prepared_weeks.get(target_start.isoformat()) if isinstance(prepared_weeks.get(target_start.isoformat()), dict) else {}
    entry.update(
        {
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "path": display_path(prepared_path),
            "status": "activated",
            "activated_at": datetime.now().isoformat(),
            "source": source,
            "garmin_sync": garmin_sync,
        }
    )
    prepared_weeks[target_start.isoformat()] = entry
    state["active_week"] = {"start_date": target_start.isoformat(), "end_date": target_end.isoformat(), "path": display_path(ACTIVE_WEEK_PATH), "activated_at": datetime.now().isoformat()}
    state["last_activation"] = {"status": "activated", "target_start": target_start.isoformat(), "target_end": target_end.isoformat(), "updated_at": datetime.now().isoformat(), "source": source, "archived_path": display_path(archived_path) if archived_path else None, "pdf": {"ok": pdf_ok, "message": pdf_message}, "garmin_sync": garmin_sync}
    save_state(state)
    return {"ok": True, "message": "Semana preparada activada.", "code": "activated", "archived_path": display_path(archived_path) if archived_path else None, "pdf": {"ok": pdf_ok, "message": pdf_message}, "garmin_sync": garmin_sync}


def pipeline_status(week_start: str = "") -> dict[str, Any]:
    state = load_state()
    active = current_active_week_info()
    active_end = parse_iso_date(active.get("end_date"))
    target_start = parse_iso_date(week_start) if week_start else None
    target_end = None
    if target_start and isinstance(state.get("prepared_weeks", {}).get(target_start.isoformat()), dict):
        target_end = parse_iso_date(state["prepared_weeks"][target_start.isoformat()].get("end_date"))
    elif active_end:
        target_start, target_end = week_bounds_for_next_range(active_end)
    prepared_entry = None
    prepared_exists = False
    if target_start and target_end:
        prepared_path = prepared_week_path(target_start, target_end)
        prepared_exists = prepared_path.exists()
        prepared_entry = state.get("prepared_weeks", {}).get(target_start.isoformat()) if isinstance(state.get("prepared_weeks"), dict) else None
        if not isinstance(prepared_entry, dict) and prepared_exists:
            prepared_entry = {
                "start_date": target_start.isoformat(),
                "end_date": target_end.isoformat(),
                "path": display_path(prepared_path),
                "status": "prepared",
            }
    return {
        "ok": True,
        "active_week": active,
        "next_target": {"start_date": target_start.isoformat() if target_start else None, "end_date": target_end.isoformat() if target_end else None},
        "prepared_exists": prepared_exists,
        "prepared_week": prepared_entry,
        "last_plan": state.get("last_plan"),
        "last_activation": state.get("last_activation"),
    }


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
    raise SystemExit(exit_code)


def main() -> None:
    args = parse_args()
    if args.command == "plan-next":
        result = plan_next_week(force=bool(args.force), source=str(args.source or "manual"))
        emit(result, 0 if result.get("ok") else 1)
    if args.command == "activate-next":
        result = activate_prepared_week(source=str(args.source or "manual"), week_start=str(args.week_start or ""))
        emit(result, 0 if result.get("ok") else 1)
    if args.command == "status":
        emit(pipeline_status(week_start=str(args.week_start or "")), 0)


if __name__ == "__main__":
    main()
