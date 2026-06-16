#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.system.automation_health import write_automation_health
    from scripts.system.context_engine import write_all_contexts
    from scripts.system.planning_validator import validate_prepared_week
    from scripts.system.policy_gate import PolicyGateError, enforce
    from scripts.system.service_sync import service_sync
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.system.automation_health import write_automation_health
    from scripts.system.context_engine import write_all_contexts
    from scripts.system.planning_validator import validate_prepared_week

try:
    from scripts.system import pipeline_progress as _progress
except Exception:  # pragma: no cover
    _progress = None  # type: ignore[assignment]


def _step(n: int, label: str) -> None:
    if _progress is not None:
        try:
            _progress.update(n, label)
        except Exception:
            pass


def _finish_progress(ok: bool, message: str = "") -> None:
    if _progress is not None:
        try:
            _progress.finish(ok, message)
        except Exception:
            pass


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_WEEK_PATH = ROOT / "planning" / "weeks" / "semana_actual.md"
PREPARED_WEEKS_DIR = ROOT / "planning" / "weeks" / "prepared"
ARCHIVED_WEEKS_DIR = ROOT / "planning" / "weeks" / "archived"
STATE_PATH = ROOT / "system" / "state" / "weekly_planning_state.json"
GLOBAL_LOCK_PATH = ROOT / "system" / "state" / "automation.lock"
PLANNING_RUNS_DIR = ROOT / "system" / "state" / "planning_runs"
TELEGRAM_CONFIG_PATH = ROOT / "telegram" / "bot_config.yaml"
PDF_SCRIPT = ROOT / "scripts" / "notifications" / "semana_pdf_telegram.py"
GARMIN_SYNC_SCRIPT = ROOT / "scripts" / "garmin" / "sync_garmin.py"
ENRICH_WORKOUTS_SCRIPT = ROOT / "scripts" / "system" / "enrich_planned_workouts.py"
PLANNED_WORKOUTS_DIR = ROOT / "training" / "planned" / "workouts"
DEFAULT_MODEL = "openai/gpt-5.4"


class OperationLockError(RuntimeError):
    pass


@contextlib.contextmanager
def global_operation_lock(name: str):
    import fcntl

    GLOBAL_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    timeout_s = max(1, int(os.getenv("AUTOMATION_LOCK_TIMEOUT_S") or "10"))
    deadline = time.monotonic() + timeout_s
    with GLOBAL_LOCK_PATH.open("w", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise OperationLockError(f"Ya hay una operacion de automatizacion en curso; reintenta en unos minutos ({name}).") from exc
                time.sleep(0.5)
        handle.write(json.dumps({"operation": name, "pid": os.getpid(), "started_at": datetime.now().isoformat()}, ensure_ascii=True) + "\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


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

    plan_range = subparsers.add_parser("plan-range", help="Plan or regenerate workouts inside an arbitrary date range")
    plan_range.add_argument("--start-date", required=True, help="Range start YYYY-MM-DD")
    plan_range.add_argument("--end-date", required=True, help="Range end YYYY-MM-DD")
    plan_range.add_argument("--premise", default="", help="Free-text planning premise for the agent")
    plan_range.add_argument("--source", default="manual", help="Trigger source label (manual, web, timer)")

    replan_range = subparsers.add_parser("replan-range", help="Replan workouts inside an arbitrary date range")
    replan_range.add_argument("--start-date", required=True, help="Range start YYYY-MM-DD")
    replan_range.add_argument("--end-date", required=True, help="Range end YYYY-MM-DD")
    replan_range.add_argument("--premise", default="", help="Free-text replanning premise for the agent")
    replan_range.add_argument("--source", default="manual", help="Trigger source label (manual, web, timer)")

    replan_workout = subparsers.add_parser("replan-workout", help="Replan one planned workout through OpenCode")
    replan_workout.add_argument("--slug", required=True, help="Workout slug / YAML stem")
    replan_workout.add_argument("--premise", default="", help="Free-text replanning premise for the agent")
    replan_workout.add_argument("--source", default="manual", help="Trigger source label (manual, web, timer)")
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
    stale = bool(end_date and date.today() > end_date)
    return {
        "exists": ACTIVE_WEEK_PATH.exists(),
        "path": display_path(ACTIVE_WEEK_PATH),
        "title": active_week_title(content),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "stale": stale,
        "stale_reason": "La fecha actual supera el fin de la semana activa." if stale else None,
    }


def opencode_model() -> str:
    config = load_yaml(TELEGRAM_CONFIG_PATH)
    remote = config.get("opencode_remote", {}) if isinstance(config.get("opencode_remote"), dict) else {}
    model = str(remote.get("model") or os.getenv("OPENCODE_MODEL") or DEFAULT_MODEL).strip()
    return model or DEFAULT_MODEL


def opencode_variant() -> str:
    config = load_yaml(TELEGRAM_CONFIG_PATH)
    remote = config.get("opencode_remote", {}) if isinstance(config.get("opencode_remote"), dict) else {}
    return str(remote.get("variant") or os.getenv("OPENCODE_VARIANT") or "high").strip() or "high"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_planning_run(run_id: str, payload: dict[str, Any]) -> Path:
    PLANNING_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLANNING_RUNS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")
    return path


def monday_for(day_value: date) -> date:
    return day_value - timedelta(days=day_value.weekday())


def sunday_for(day_value: date) -> date:
    return monday_for(day_value) + timedelta(days=6)


def week_ranges_between(start_date: date, end_date: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = monday_for(start_date)
    final = monday_for(end_date)
    while cursor <= final:
        windows.append((cursor, cursor + timedelta(days=6)))
        cursor += timedelta(days=7)
    return windows


def operative_week_paths_for_range(start_date: date, end_date: date) -> list[Path]:
    active = current_active_week_info()
    active_start = parse_iso_date(active.get("start_date"))
    active_end = parse_iso_date(active.get("end_date"))
    paths: list[Path] = []
    for week_start, week_end in week_ranges_between(start_date, end_date):
        if active_start == week_start and active_end == week_end:
            paths.append(ACTIVE_WEEK_PATH)
        else:
            paths.append(prepared_week_path(week_start, week_end))
    return paths


def planned_workout_path(slug: str) -> Path:
    return PLANNED_WORKOUTS_DIR / f"{slug}.yaml"


def pre_operation_sync(day: str) -> dict[str, Any]:
    payload = service_sync(day, skip_garmin=False)
    return payload if isinstance(payload, dict) else {"ok": False, "summary": "Service sync devolvio una respuesta no valida."}


def collect_range_snapshot(start_date: date, end_date: date) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for week_path in operative_week_paths_for_range(start_date, end_date):
        if week_path.exists():
            snapshot[display_path(week_path)] = file_sha256(week_path)
    for workout_path in workout_yaml_files_for_range(start_date, end_date):
        snapshot[display_path(workout_path)] = file_sha256(workout_path)
    return snapshot


def changed_paths_against_snapshot(snapshot: dict[str, str], start_date: date, end_date: date) -> list[str]:
    current: dict[str, str] = {}
    for week_path in operative_week_paths_for_range(start_date, end_date):
        if week_path.exists():
            current[display_path(week_path)] = file_sha256(week_path)
    for workout_path in workout_yaml_files_for_range(start_date, end_date):
        current[display_path(workout_path)] = file_sha256(workout_path)
    changed = {
        path
        for path in set(snapshot) | set(current)
        if snapshot.get(path) != current.get(path)
    }
    return sorted(changed)


def build_range_prompt(target_start: date, target_end: date, premise: str, *, mode: str) -> str:
    week_paths = operative_week_paths_for_range(target_start, target_end)
    week_lines = "\n".join(f"- {display_path(path)}" for path in week_paths)
    mode_line = "planificar" if mode == "plan" else "replanificar"
    extra_rules = (
        "Si una carrera o sesion deja de tener sentido dentro del rango, elimina o actualiza su archivo YAML y cualquier referencia semanal correspondiente."
        if mode == "replan"
        else "Si necesitas crear semanas futuras que todavia no existan en planning/weeks/prepared/, hazlo siguiendo el formato operativo habitual."
    )
    return (
        "Actua como el planificador operativo de este repositorio y trabaja directamente sobre los archivos del proyecto. "
        f"Tu objetivo es {mode_line} el rango indicado respetando el conocimiento y las reglas ya guardadas.\n\n"
        "MODO EJECUCION OBLIGATORIO: trabajas en una sesion automatica no interactiva. Debes EJECUTAR los cambios "
        "usando las herramientas de escritura (write/edit) en este mismo turno. NO describas lo que vas a hacer ni "
        "termines con frases de intencion como 'voy a' o 'ahora leere': realiza las lecturas y despues ESCRIBE los "
        "archivos de verdad. No finalices la tarea hasta haber creado/actualizado el markdown semanal y todos los "
        "YAMLs fechados del rango con la herramienta de escritura.\n\n"
        f"Rango objetivo: del {target_start.isoformat()} al {target_end.isoformat()}.\n"
        f"Premisa adicional obligatoria del usuario: {premise.strip() or 'Sin premisa adicional; usa el contexto operativo actual.'}\n\n"
        "Archivos semanales canonicos que debes actualizar dentro de este rango:\n"
        f"{week_lines}\n\n"
        "Instrucciones obligatorias:\n"
        "1. Lee AGENT.md, planning/context_automation_policy.md, .agents/memory/project_snapshot.md, .agents/workflows/weekly_coaching_cycle.md, planning/coaching_playbook.md, planning/workout_knowledge.yaml, planning/workout_template_knowledge_map.yaml, planning/session_selection_matrix.yaml, planning/workout_evaluation_rules.md, athlete/response_profile.yaml, athlete/status_dashboard.md, planning/coach_decision.md, system/state/athlete_state.json, athlete/profile.yaml, athlete/preferences.yaml, athlete/zones.yaml, athlete/shoes.yaml, athlete/health.yaml, athlete/shin_tracker.yaml, planning/goal_gates.yaml, athlete/supplements.yaml, planning/fueling_operational.md y carreras relevantes.\n"
        "2. Modifica solo los archivos necesarios para que la fuente de verdad quede canonica: markdown semanal afectado y YAMLs fechados en training/planned/workouts/ dentro del rango. No uses overlays temporales.\n"
        "3. Mantén intacto lo que quede fuera del rango salvo dependencias estrictamente necesarias.\n"
        "4. Siempre que toques sesiones futuras, deja los YAMLs coherentes con el markdown semanal y con Garmin: pasos ejecutables, duration_s o distance_m cuando haga falta, sport correcto y metadata util (`template_id`, `knowledge_id`, `knowledge_label`, `primary_goal`) cuando proceda.\n"
        f"5. {extra_rules}\n"
        "6. Si la accion implica retirar sesiones del rango, elimina tambien los YAMLs y deja el markdown semanal consistente.\n"
        "7. Antes de terminar, VERIFICA que has usado la herramienta de escritura para cada YAML del rango y para el "
        "markdown semanal. Si no has escrito ningun archivo todavia, hazlo ahora: la tarea no esta completa hasta que "
        "los archivos esten escritos en el repositorio. No hagas commit.\n"
    )


def build_workout_replan_prompt(slug: str, workout_path: Path, schedule_date: date, premise: str) -> str:
    week_paths = operative_week_paths_for_range(schedule_date, schedule_date)
    week_lines = "\n".join(f"- {display_path(path)}" for path in week_paths)
    return (
        "Actua como el replanificador operativo de este repositorio y trabaja directamente sobre los archivos del proyecto. "
        "Debes replanificar una sola sesion planificada respetando el conocimiento y las reglas guardadas.\n\n"
        f"Sesion objetivo: {slug}\n"
        f"Archivo YAML canonico obligatorio: {display_path(workout_path)}\n"
        f"Fecha operativa: {schedule_date.isoformat()}\n"
        f"Premisa adicional obligatoria del usuario: {premise.strip() or 'Sin premisa adicional; usa el contexto operativo actual.'}\n\n"
        "Archivos semanales canonicos que debes actualizar si hace falta:\n"
        f"{week_lines}\n\n"
        "Instrucciones obligatorias:\n"
        "1. Lee AGENT.md, planning/context_automation_policy.md, planning/coaching_playbook.md, planning/workout_knowledge.yaml, planning/workout_template_knowledge_map.yaml, planning/session_selection_matrix.yaml, planning/workout_evaluation_rules.md, athlete/response_profile.yaml, athlete/status_dashboard.md, planning/coach_decision.md, system/state/athlete_state.json, athlete/health.yaml, athlete/zones.yaml, athlete/shin_tracker.yaml, athlete/supplements.yaml y planning/fueling_operational.md.\n"
        "2. Replanifica solo esta sesion. Conserva el mismo slug y el mismo archivo YAML; no lo renombres ni lo muevas.\n"
        "3. Mantén la fecha y la referencia del workout, salvo que la premisa exija otra cosa de forma inequívoca. Si cambias la fecha, deja el markdown semanal consistente y actualiza el workout dentro del mismo archivo.\n"
        "4. El resultado final debe quedar canonico en el YAML real y en el markdown semanal. No uses overlays ni archivos temporales.\n"
        "5. Asegura que los pasos resultantes sean ejecutables por Garmin y que la descripcion refleje con claridad el cambio pedido.\n"
        "6. Al terminar, deja los archivos escritos en el repositorio y no hagas commit.\n"
    )


def build_planning_prompt(target_start: date, target_end: date, output_path: Path) -> str:
    return (
        "Actua como el planificador semanal de este repositorio y trabaja directamente sobre los archivos del proyecto. "
        "Tu objetivo es preparar la siguiente semana sin tocar planning/weeks/semana_actual.md.\n\n"
        f"Semana objetivo: del {target_start.isoformat()} al {target_end.isoformat()} (lunes a domingo).\n"
        f"Archivo de salida obligatorio: {display_path(output_path)}\n\n"
        "Instrucciones obligatorias:\n"
        "1. Lee AGENT.md, .agents/memory/project_snapshot.md, .agents/workflows/weekly_coaching_cycle.md, planning/context_automation_policy.md, planning/coaching_playbook.md, planning/workout_knowledge.yaml, planning/workout_template_knowledge_map.yaml, planning/session_selection_matrix.yaml, planning/workout_evaluation_rules.md, garmin/strength_mobility_exercise_knowledge.yaml, athlete/response_profile.yaml, planning/master_plan.md, la semana activa actual y el bloque relevante.\n"
        "2. Usa tambien athlete/profile.yaml, athlete/preferences.yaml, athlete/zones.yaml, athlete/shoes.yaml, athlete/health.yaml, athlete/shin_tracker.yaml, planning/goal_gates.yaml y carreras relevantes.\n"
        "3. Genera la semana objetivo en el archivo indicado con el mismo formato operativo habitual del proyecto: titulo, fechas, contexto si hace falta, tabla diaria con dia, descripcion, distancia, ritmo o FC y zapatillas.\n"
        "4. No modifiques planning/weeks/semana_actual.md. Solo prepara la siguiente semana en el archivo de salida.\n"
        "5. Crea o actualiza los YAML necesarios en training/planned/workouts/ para las sesiones fechadas de esa semana. Siempre que puedas, incluye `template_id`, `knowledge_id`, `knowledge_label` y `primary_goal` alineados con training/planned/workouts/library_run_templates.yaml, planning/workout_template_knowledge_map.yaml y planning/workout_knowledge.yaml. Si la sesion es de bicicleta, usa `sport: cycling`, no `fitness_equipment`. Si la sesion es de natacion, usa `sport: swimming`. Si la sesion es de eliptica, usa `sport: elliptical`. Incluye preferentemente una sesion especifica de movilidad por semana si el contexto del atleta no desaconseja meterla. Si la sesion es de fuerza o movilidad, no uses un bloque unico con todos los ejercicios en la descripcion: crea un paso por ejercicio. Usa `garmin/strength_mobility_exercise_knowledge.yaml` para asignar el ejercicio Garmin exacto o la familia Garmin mas cercana permitida para cada movimiento. Si el conocimiento local marca `upload_strategy: closest_garmin_family`, rellena `exercise_name` y `category` con esa seleccion Garmin y deja la instruccion exacta en `description`. Si marca `description_only`, deja esos campos vacios. Solo usa `provider_exercise_source_id` cuando exista una referencia exacta confirmada. Si el ejercicio va por series y repeticiones, por ejemplo `4x8`, no lo representes por tiempo: crea un `repeat_group` con `iterations: 4` y dentro un paso del ejercicio con `repetitions: 8`; solo usa `duration_s` para descansos o bloques realmente temporales. En movilidad aplica la misma filosofia: ejercicios explicitos, iteraciones si hacen falta y descripcion precisa.\n"
        "6. Cuando el atleta vuelva a correr, reintroduce la carga de impacto de forma progresiva: usa como default aproximadamente `+5%` de volumen semanal de running sobre la ultima semana realmente absorbida, salvo que el contexto obligue a mantener o reducir. Si una semana tambien sube intensidad de running, estrecha la progresion hacia `0-5%` o incluso manten estable la carga. No subas a la vez volumen e intensidad de running en una semana fragil.\n"
        "7. Mantén al menos una sesion de bicicleta en la mayoria de semanas mientras la durabilidad de carrera no sea claramente estable. La bici puede servir para base aerobica y tambien para apoyo tempo/VO2 sin impacto si eso protege mejor la tibia.\n"
        "8. Introduce fartlek con regularidad en la vuelta al impacto y base temprana como puente entre rodajes faciles y trabajo mas denso.\n"
        "9. A lo largo de los bloques, la carga debe crecer lo suficiente para sostener el objetivo de febrero de 2027, pero solo cuando los checkpoints y la tolerancia tisular lo permitan; no te quedes cronificado en carga de rehabilitacion si la evolucion ya permite mas.\n"
        "10. Progresa automaticamente ritmos de series/tempo/fartlek desde la evidencia reciente del atleta: carreras, tests, sesiones absorbidas, tendencia de FC y repetibilidad actual. No congeles ritmos antiguos ni uses el objetivo aspiracional como ritmo prescrito directo.\n"
        "11. Mantente conservador con la tibia, la decision del coach y las reglas del ciclo.\n"
        "12. Al terminar, deja los archivos escritos en el repositorio.\n"
    )


def run_command(command: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)


_OPENCODE_QUOTA_PATTERNS = [
    "insufficient_quota", "insufficient_credits", "billing_hard_limit",
    "rate_limit_exceeded", "quota_exceeded", "quota exceeded",
    "credit limit", "no credits", "out of credits", "payment required",
    "too many requests", "usage limit", "usage limit has been reached",
    "ai_apicallerror", "ai_retryerror", "model_not_found", "model not found",
]


def _opencode_quota_error(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0 and result.stdout.strip():
        return False
    combined = (result.stdout + " " + result.stderr).lower()
    return any(p in combined for p in _OPENCODE_QUOTA_PATTERNS) or result.returncode in (124,) or result.returncode < 0


def _gemini_config() -> tuple[str, list[str]]:
    config = load_yaml(TELEGRAM_CONFIG_PATH)
    remote = config.get("opencode_remote", {}) if isinstance(config.get("opencode_remote"), dict) else {}
    fallback = remote.get("gemini_fallback", {}) if isinstance(remote.get("gemini_fallback"), dict) else {}
    api_key = str(fallback.get("api_key") or os.getenv("GEMINI_API_KEY") or "").strip()
    models = fallback.get("models") if isinstance(fallback.get("models"), list) else []
    if not models:
        models = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]
    return api_key, [str(m) for m in models]


def _execute_via_gemini(prompt: str, run_id: str) -> tuple[bool, str, dict[str, Any]]:
    try:
        api_key, models = _gemini_config()
        if not api_key:
            return False, "Gemini API key no configurada (GEMINI_API_KEY).", {"run_id": run_id, "fallback": "gemini"}
        from scripts.telegram.gemini_fallback import call_gemini_chain
        text, model_used = call_gemini_chain(api_key, models, prompt, channel="planning")
        save_planning_run(run_id, {"run_id": run_id, "finished_at": datetime.now().isoformat(), "status": "ok", "fallback": "gemini", "model": model_used, "response": text[:2000]})
        return True, f"Planificacion completada via Gemini ({model_used}).", {"run_id": run_id, "fallback": "gemini", "model": model_used}
    except Exception as exc:
        save_planning_run(run_id, {"run_id": run_id, "status": "error", "fallback": "gemini", "error": str(exc)})
        return False, f"Gemini no pudo completar la planificacion: {exc}", {"run_id": run_id, "fallback": "gemini"}


def execute_opencode_prompt(prompt: str) -> tuple[bool, str, dict[str, Any]]:
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "_" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    # --variant forces an explicit reasoning effort. The opencode default hangs
    # the OpenAI/Codex (OAuth) stream mid-run on gpt-5.x; any explicit variant
    # avoids the freeze that was leaving plan-range/replan-range stuck.
    command = ["opencode", "run", "--dir", str(ROOT), "--model", opencode_model(), "--variant", opencode_variant(), "--print-logs", prompt]
    prompt_path = save_planning_run(
        run_id,
        {
            "run_id": run_id,
            "started_at": datetime.now().isoformat(),
            "model": opencode_model(),
            "command": " ".join(command[:-1]),
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "status": "started",
        },
    )
    # Un plan completo de semana con gpt-5.4 --variant high razona durante
    # varios minutos legítimamente. El hang real ya está resuelto (variant),
    # así que damos margen amplio; el timeout solo cubre cuelgues residuales.
    _OPENCODE_PIPELINE_TIMEOUT = int(os.getenv("OPENCODE_PIPELINE_TIMEOUT") or 1800)
    try:
        result = run_command(command, timeout=_OPENCODE_PIPELINE_TIMEOUT)
    except subprocess.TimeoutExpired:
        save_planning_run(run_id, {"run_id": run_id, "status": "timeout", "message": f"opencode timed out after {_OPENCODE_PIPELINE_TIMEOUT}s", "prompt_path": display_path(prompt_path)})
        return _execute_via_gemini(prompt, run_id)
    except FileNotFoundError:
        save_planning_run(run_id, {"run_id": run_id, "status": "error", "message": "opencode missing", "prompt_path": display_path(prompt_path)})
        return _execute_via_gemini(prompt, run_id)

    if _opencode_quota_error(result):
        save_planning_run(run_id, {"run_id": run_id, "status": "quota_error", "returncode": result.returncode,
                                   "stderr_preview": result.stderr[-500:], "prompt_path": display_path(prompt_path)})
        return _execute_via_gemini(prompt, run_id)

    detail = {
        "command": " ".join(command[:-1]),
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "run_id": run_id,
        "prompt_path": display_path(prompt_path),
    }
    save_planning_run(run_id, {"run_id": run_id, "finished_at": datetime.now().isoformat(), "status": "ok" if result.returncode == 0 else "error", "detail": detail, "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()})
    if result.returncode != 0:
        return False, "OpenCode no pudo completar la operacion solicitada.", detail
    return True, "Operacion OpenCode completada.", detail


def execute_opencode_planning(target_start: date, target_end: date, output_path: Path) -> tuple[bool, str, dict[str, Any]]:
    prompt = build_planning_prompt(target_start, target_end, output_path)
    ok, message, detail = execute_opencode_prompt(prompt)
    if not ok:
        return False, "OpenCode no pudo preparar la siguiente semana.", detail
    if not output_path.exists():
        return False, "OpenCode termino, pero no se genero el archivo esperado de la siguiente semana.", detail
    generated_start, generated_end = parse_week_date_window(read_text(output_path))
    if generated_start != target_start or generated_end != target_end:
        return False, "La semana preparada no coincide con el rango objetivo esperado.", detail
    return True, message, detail


def execute_range_agent_prompt(prompt: str, target_start: date, target_end: date, snapshot: dict[str, str]) -> tuple[bool, str, dict[str, Any], list[str]]:
    ok, message, detail = execute_opencode_prompt(prompt)
    changed_paths = changed_paths_against_snapshot(snapshot, target_start, target_end)
    if not ok or changed_paths:
        return ok, message, detail, changed_paths

    run_id = str(detail.get("run_id") or datetime.now().strftime("%Y%m%dT%H%M%S"))
    fallback_ok, fallback_message, fallback_detail = _execute_via_gemini(prompt, f"{run_id}_nochange")
    fallback_changed_paths = changed_paths_against_snapshot(snapshot, target_start, target_end)
    if fallback_ok and fallback_changed_paths:
        return True, fallback_message, {"opencode_no_changes": detail, "fallback": fallback_detail}, fallback_changed_paths
    return (
        False,
        "La IA termino sin modificar archivos del rango; no se acepta como plan generado.",
        {"opencode_no_changes": detail, "fallback": fallback_detail},
        fallback_changed_paths,
    )


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


def sync_planned_workouts_verified() -> dict[str, Any]:
    command = [sys.executable, str(GARMIN_SYNC_SCRIPT), "sync-planned-workouts"]
    result = run_command(command, timeout=1800)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    try:
        payload = json.loads(stdout or "{}") if stdout else {}
    except json.JSONDecodeError:
        payload = {"raw_output": stdout or stderr}
    failed = int(payload.get("failed") or 0) if isinstance(payload, dict) else 0
    ok = result.returncode == 0 and failed == 0
    return {
        "ok": ok,
        "command": " ".join(command),
        "returncode": result.returncode,
        "message": (stdout or stderr or "Sin salida")[-2000:],
        "payload": payload if isinstance(payload, dict) else {"raw_output": stdout or stderr},
    }


def verify_workout_upload(workout_path: Path) -> tuple[bool, str, dict[str, Any]]:
    payload = load_yaml(workout_path).get("workout", {})
    schedule_date = str(payload.get("schedule_date") or "").strip()
    if not schedule_date:
        return False, "El workout no define schedule_date tras la replanificacion.", {}
    upload_path = planned_upload_record_path(workout_path, schedule_date)
    if not upload_path.exists():
        return False, "No existe el registro .garmin_upload.json esperado tras la sincronizacion.", {"expected_upload_path": display_path(upload_path)}
    try:
        upload = json.loads(upload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "El registro de Garmin generado no es JSON valido.", {"expected_upload_path": display_path(upload_path)}
    expected_hash = file_sha256(workout_path)
    if upload.get("status") != "scheduled":
        return False, "Garmin no devolvio estado scheduled para la sesion replanificada.", upload
    if str(upload.get("workout_file") or "") != display_path(workout_path):
        return False, "El registro Garmin apunta a un archivo distinto del YAML canonico.", upload
    if str(upload.get("workout_hash") or "") != expected_hash:
        return False, "El hash del upload Garmin no coincide con el YAML canonico actual.", upload
    return True, "Workout sincronizado y verificado en Garmin.", upload


def sync_single_workout_and_verify(workout_path: Path) -> dict[str, Any]:
    command = [sys.executable, str(GARMIN_SYNC_SCRIPT), "schedule-workout-file", str(workout_path)]
    result = run_command(command, timeout=600)
    if result.returncode != 0:
        return {
            "ok": False,
            "command": " ".join(command),
            "returncode": result.returncode,
            "message": ((result.stdout or result.stderr or "Fallo Garmin")[-2000:]),
        }
    ok, message, payload = verify_workout_upload(workout_path)
    return {
        "ok": ok,
        "command": " ".join(command),
        "returncode": result.returncode,
        "message": message,
        "payload": payload,
    }


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


def refresh_operational_artifacts() -> None:
    write_all_contexts(refresh_capabilities=False)
    write_automation_health()


def save_last_operation(entry: dict[str, Any]) -> None:
    state = load_state()
    state["last_range_operation"] = entry
    save_state(state)


def parse_required_date(value: str, *, field_name: str) -> date:
    parsed = parse_iso_date(value)
    if not parsed:
        raise ValueError(f"Fecha no valida para {field_name}: {value}")
    return parsed


def plan_range(start_date_text: str, end_date_text: str, premise: str, source: str) -> dict[str, Any]:
    try:
        with global_operation_lock("plan_range"):
            return _plan_range(start_date_text, end_date_text, premise, source)
    except OperationLockError as exc:
        _finish_progress(False, str(exc))
        return {"ok": False, "message": str(exc), "code": "operation_busy"}


def _plan_range(start_date_text: str, end_date_text: str, premise: str, source: str) -> dict[str, Any]:
    try:
        target_start = parse_required_date(start_date_text, field_name="start_date")
        target_end = parse_required_date(end_date_text, field_name="end_date")
    except ValueError as exc:
        _finish_progress(False, str(exc))
        return {"ok": False, "message": str(exc), "code": "invalid_date"}
    if target_end < target_start:
        _finish_progress(False, "Rango de fechas inválido.")
        return {"ok": False, "message": "La fecha final no puede ser anterior a la inicial.", "code": "invalid_range"}
    _step(1, "Sincronizando datos con Garmin…")
    pre_sync = pre_operation_sync(date.today().isoformat())
    if not pre_sync.get("ok"):
        _finish_progress(False, "Fallo en sincronización previa con Garmin.")
        save_last_operation({
            "status": "blocked_pre_sync",
            "operation": "plan_range",
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "premise": premise,
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "pre_sync": pre_sync,
        })
        return {"ok": False, "message": "No se puede planificar porque la sincronizacion previa con Garmin/coach ha fallado.", "code": "pre_sync_failed", "pre_sync": pre_sync}
    _step(2, "Preparando contexto del rango…")
    snapshot = collect_range_snapshot(target_start, target_end)
    _step(3, "Generando plan con IA…")
    ok, message, detail, changed_paths = execute_range_agent_prompt(build_range_prompt(target_start, target_end, premise, mode="plan"), target_start, target_end, snapshot)
    if not ok:
        _finish_progress(False, f"Error al generar el plan: {message}")
        save_last_operation({
            "status": "planning_failed",
            "operation": "plan_range",
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "premise": premise,
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "detail": detail,
            "pre_sync": pre_sync,
        })
        return {"ok": False, "message": message, "code": "planning_failed", "detail": detail, "pre_sync": pre_sync}
    _step(4, "Subiendo entrenamientos a Garmin…")
    garmin_sync = sync_planned_workouts_verified()
    _step(5, "Actualizando resumen…")
    refresh_operational_artifacts()
    entry = {
        "status": "planned" if garmin_sync.get("ok") else "garmin_failed",
        "operation": "plan_range",
        "start_date": target_start.isoformat(),
        "end_date": target_end.isoformat(),
        "premise": premise,
        "updated_at": datetime.now().isoformat(),
        "source": source,
        "changed_paths": changed_paths,
        "planner_detail": {k: v for k, v in detail.items() if k != "stdout"},
        "pre_sync": pre_sync,
        "garmin_sync": garmin_sync,
    }
    save_last_operation(entry)
    if not garmin_sync.get("ok"):
        _finish_progress(False, "Plan generado, pero fallo la verificación Garmin.")
        return {"ok": False, "message": "Plan generado, pero la verificacion Garmin posterior ha fallado.", "code": "garmin_sync_failed", "changed_paths": changed_paths, "garmin_sync": garmin_sync}
    _finish_progress(True, "Plan generado y sincronizado con Garmin.")
    return {"ok": True, "message": "Plan generado y sincronizado con Garmin.", "code": "planned", "changed_paths": changed_paths, "garmin_sync": garmin_sync}


def replan_range(start_date_text: str, end_date_text: str, premise: str, source: str) -> dict[str, Any]:
    try:
        with global_operation_lock("replan_range"):
            return _replan_range(start_date_text, end_date_text, premise, source)
    except OperationLockError as exc:
        _finish_progress(False, str(exc))
        return {"ok": False, "message": str(exc), "code": "operation_busy"}


def _replan_range(start_date_text: str, end_date_text: str, premise: str, source: str) -> dict[str, Any]:
    try:
        target_start = parse_required_date(start_date_text, field_name="start_date")
        target_end = parse_required_date(end_date_text, field_name="end_date")
    except ValueError as exc:
        _finish_progress(False, str(exc))
        return {"ok": False, "message": str(exc), "code": "invalid_date"}
    if target_end < target_start:
        _finish_progress(False, "Rango de fechas inválido.")
        return {"ok": False, "message": "La fecha final no puede ser anterior a la inicial.", "code": "invalid_range"}
    _step(1, "Sincronizando datos con Garmin…")
    pre_sync = pre_operation_sync(date.today().isoformat())
    if not pre_sync.get("ok"):
        _finish_progress(False, "Fallo en sincronización previa con Garmin.")
        save_last_operation({
            "status": "blocked_pre_sync",
            "operation": "replan_range",
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "premise": premise,
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "pre_sync": pre_sync,
        })
        return {"ok": False, "message": "No se puede replanificar porque la sincronizacion previa con Garmin/coach ha fallado.", "code": "pre_sync_failed", "pre_sync": pre_sync}
    _step(2, "Preparando contexto del rango…")
    snapshot = collect_range_snapshot(target_start, target_end)
    _step(3, "Generando plan con IA…")
    ok, message, detail, changed_paths = execute_range_agent_prompt(build_range_prompt(target_start, target_end, premise, mode="replan"), target_start, target_end, snapshot)
    if not ok:
        _finish_progress(False, f"Error al replanificar: {message}")
        save_last_operation({
            "status": "replanning_failed",
            "operation": "replan_range",
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "premise": premise,
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "detail": detail,
            "pre_sync": pre_sync,
        })
        return {"ok": False, "message": message, "code": "replanning_failed", "detail": detail, "pre_sync": pre_sync}
    _step(4, "Subiendo entrenamientos a Garmin…")
    garmin_sync = sync_planned_workouts_verified()
    _step(5, "Actualizando resumen…")
    refresh_operational_artifacts()
    entry = {
        "status": "replanned" if garmin_sync.get("ok") else "garmin_failed",
        "operation": "replan_range",
        "start_date": target_start.isoformat(),
        "end_date": target_end.isoformat(),
        "premise": premise,
        "updated_at": datetime.now().isoformat(),
        "source": source,
        "changed_paths": changed_paths,
        "planner_detail": {k: v for k, v in detail.items() if k != "stdout"},
        "pre_sync": pre_sync,
        "garmin_sync": garmin_sync,
    }
    save_last_operation(entry)
    if not garmin_sync.get("ok"):
        _finish_progress(False, "Replan generado, pero falló la verificación Garmin.")
        return {"ok": False, "message": "Replan generado, pero la verificacion Garmin posterior ha fallado.", "code": "garmin_sync_failed", "changed_paths": changed_paths, "garmin_sync": garmin_sync}
    _finish_progress(True, "Replan generado y sincronizado con Garmin.")
    return {"ok": True, "message": "Replan generado y sincronizado con Garmin.", "code": "replanned", "changed_paths": changed_paths, "garmin_sync": garmin_sync}


def replan_workout(slug: str, premise: str, source: str) -> dict[str, Any]:
    try:
        with global_operation_lock("replan_workout"):
            return _replan_workout(slug, premise, source)
    except OperationLockError as exc:
        return {"ok": False, "message": str(exc), "code": "operation_busy"}


def _replan_workout(slug: str, premise: str, source: str) -> dict[str, Any]:
    workout_path = planned_workout_path(slug)
    if not workout_path.exists():
        return {"ok": False, "message": f"No existe el workout planificado `{display_path(workout_path)}`.", "code": "workout_missing"}
    spec = load_yaml(workout_path)
    workout = spec.get("workout", {}) if isinstance(spec, dict) else {}
    schedule_date = parse_iso_date(str(workout.get("schedule_date") or ""))
    if not schedule_date:
        return {"ok": False, "message": "La sesion no tiene una fecha valida para replanificar.", "code": "workout_missing_date"}
    pre_sync = pre_operation_sync(date.today().isoformat())
    if not pre_sync.get("ok"):
        save_last_operation({
            "status": "blocked_pre_sync",
            "operation": "replan_workout",
            "slug": slug,
            "premise": premise,
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "pre_sync": pre_sync,
        })
        return {"ok": False, "message": "No se puede replanificar la sesion porque la sincronizacion previa con Garmin/coach ha fallado.", "code": "pre_sync_failed", "pre_sync": pre_sync}
    previous_hash = file_sha256(workout_path)
    ok, message, detail = execute_opencode_prompt(build_workout_replan_prompt(slug, workout_path, schedule_date, premise))
    changed = [display_path(workout_path)] if workout_path.exists() and file_sha256(workout_path) != previous_hash else []
    if not ok:
        save_last_operation({
            "status": "replanning_failed",
            "operation": "replan_workout",
            "slug": slug,
            "premise": premise,
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "detail": detail,
            "pre_sync": pre_sync,
        })
        return {"ok": False, "message": message, "code": "replanning_failed", "detail": detail, "pre_sync": pre_sync}
    garmin_sync = sync_single_workout_and_verify(workout_path)
    refresh_operational_artifacts()
    entry = {
        "status": "replanned" if garmin_sync.get("ok") else "garmin_failed",
        "operation": "replan_workout",
        "slug": slug,
        "premise": premise,
        "updated_at": datetime.now().isoformat(),
        "source": source,
        "changed_paths": changed,
        "planner_detail": {k: v for k, v in detail.items() if k != "stdout"},
        "pre_sync": pre_sync,
        "garmin_sync": garmin_sync,
    }
    save_last_operation(entry)
    if not garmin_sync.get("ok"):
        return {"ok": False, "message": "La sesion se ha replanificado localmente, pero la verificacion Garmin ha fallado.", "code": "garmin_sync_failed", "changed_paths": changed, "garmin_sync": garmin_sync}
    return {"ok": True, "message": "Sesion replanificada y sincronizada con Garmin.", "code": "replanned", "changed_paths": changed, "garmin_sync": garmin_sync}


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
    try:
        with global_operation_lock("plan_next_week"):
            return _plan_next_week(force, source)
    except OperationLockError as exc:
        return {"ok": False, "message": str(exc), "code": "operation_busy"}


def _plan_next_week(force: bool, source: str) -> dict[str, Any]:
    try:
        if force:
            enforce("regenerate_prepared_week", source=source)
    except PolicyGateError as exc:
        return {"ok": False, "message": str(exc), "code": "policy_blocked"}
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
    validation = validate_prepared_week(output_path)
    entry = ensure_prepared_entry(state, target_start, target_end, output_path, source)
    entry["status"] = "prepared"
    entry["generated_at"] = datetime.now().isoformat()
    entry["knowledge_enrichment"] = {"ok": enrich_ok, **enrich_detail}
    entry["garmin_sync"] = garmin_sync
    entry["validation"] = validation
    entry["planner_detail"] = {k: v for k, v in detail.items() if k != "stdout"}
    state["last_plan"] = {"status": "prepared", "target_start": target_start.isoformat(), "target_end": target_end.isoformat(), "updated_at": datetime.now().isoformat(), "source": source, "knowledge_enrichment": {"ok": enrich_ok, **enrich_detail}, "garmin_sync": garmin_sync, "validation": validation}
    save_state(state)
    refresh_operational_artifacts()
    return {"ok": True, "message": message, "code": "prepared", "prepared_week": entry, "garmin_sync": garmin_sync, "validation": validation}


def activate_prepared_week(source: str, week_start: str = "") -> dict[str, Any]:
    try:
        with global_operation_lock("activate_prepared_week"):
            return _activate_prepared_week(source, week_start)
    except OperationLockError as exc:
        return {"ok": False, "message": str(exc), "code": "operation_busy"}


def _activate_prepared_week(source: str, week_start: str = "") -> dict[str, Any]:
    try:
        enforce("activate_prepared_week", source=source)
    except PolicyGateError as exc:
        return {"ok": False, "message": str(exc), "code": "policy_blocked"}
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
    validation = validate_prepared_week(prepared_path)
    if not validation.get("ok"):
        return {"ok": False, "message": "La semana preparada no pasa la validacion operativa.", "code": "prepared_week_invalid", "validation": validation}
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
    refresh_operational_artifacts()
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
    if args.command == "plan-range":
        result = plan_range(str(args.start_date or ""), str(args.end_date or ""), str(args.premise or ""), str(args.source or "manual"))
        emit(result, 0 if result.get("ok") else 1)
    if args.command == "replan-range":
        result = replan_range(str(args.start_date or ""), str(args.end_date or ""), str(args.premise or ""), str(args.source or "manual"))
        emit(result, 0 if result.get("ok") else 1)
    if args.command == "replan-workout":
        result = replan_workout(str(args.slug or ""), str(args.premise or ""), str(args.source or "manual"))
        emit(result, 0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
