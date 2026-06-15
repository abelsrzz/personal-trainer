#!/usr/bin/env python3
"""Gemini agentic fallback — alternativa completa a OpenCode cuando GPT-5.4 no está disponible.

Implementa un bucle agente con function calling de Gemini:
- Leer/escribir archivos del repositorio
- Ejecutar comandos de shell y scripts de Garmin/planificación
- Buscar y listar archivos
- Todo lo que puede hacer OpenCode
"""

from __future__ import annotations

import asyncio
import glob as glob_module
import json
import logging
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("telegram.gemini_fallback")

ROOT = Path(__file__).resolve().parents[2]
MAX_AGENT_ITERATIONS = 25

_QUOTA_ERROR_MARKERS = (
    "429", "quota", "rate limit", "resource exhausted", "too many requests",
    "503", "service unavailable", "unavailable", "high demand", "overloaded",
)

# ---------------------------------------------------------------------------
# Declaraciones de herramientas para Gemini function calling
# ---------------------------------------------------------------------------

_TOOL_DECLARATIONS = {
    "functionDeclarations": [
        {
            "name": "read_file",
            "description": "Lee el contenido de un archivo del proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa a la raiz del proyecto"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Escribe o crea un archivo en el proyecto. Reemplaza el contenido completo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa a la raiz del proyecto"},
                    "content": {"type": "string", "description": "Contenido completo del archivo"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "run_command",
            "description": (
                "Ejecuta un comando de shell en el directorio del proyecto. "
                "Util para scripts de Garmin, planificacion, PDF, sincronizacion, etc. "
                "Usa python3 para scripts Python del proyecto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando de shell a ejecutar"},
                },
                "required": ["command"],
            },
        },
        {
            "name": "list_files",
            "description": "Lista archivos del proyecto que coincidan con un patron glob.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Patron glob, ej: training/planned/workouts/*.yaml",
                    },
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "search_files",
            "description": "Busca texto en archivos del proyecto. Devuelve rutas de archivos que contienen el patron.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Texto o regex a buscar"},
                    "path": {
                        "type": "string",
                        "description": "Directorio o archivo donde buscar (relativo al proyecto). Por defecto: raiz.",
                    },
                },
                "required": ["pattern"],
            },
        },
    ]
}

# ---------------------------------------------------------------------------
# Implementaciones de herramientas
# ---------------------------------------------------------------------------


def _safe_path(path: str) -> Path:
    p = (ROOT / path).resolve()
    if not str(p).startswith(str(ROOT.resolve())):
        raise ValueError(f"Ruta fuera del proyecto: {path}")
    return p


def _tool_read_file(path: str) -> str:
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"Archivo no encontrado: {path}"
        if p.is_dir():
            children = sorted(str(c.relative_to(ROOT)) for c in p.iterdir())[:50]
            return "Es un directorio. Contenido:\n" + "\n".join(children)
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 60000:
            content = content[:60000] + "\n\n[... archivo truncado por tamano ...]"
        return content
    except Exception as exc:
        return f"Error leyendo {path}: {exc}"


def _tool_write_file(path: str, content: str) -> str:
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK — {path} escrito ({len(content)} chars)"
    except Exception as exc:
        return f"Error escribiendo {path}: {exc}"


def _tool_run_command(command: str) -> str:
    # Sustituir python3/python por el interprete actual para usar el venv
    venv_python = sys.executable
    for placeholder in ("python3 ", "python "):
        if command.startswith(placeholder):
            command = venv_python + " " + command[len(placeholder):]
            break
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 12000:
            output = output[:12000] + "\n[... salida truncada ...]"
        return output or f"(sin salida, exit {result.returncode})"
    except subprocess.TimeoutExpired:
        return "El comando supero el tiempo limite (300s)"
    except Exception as exc:
        return f"Error ejecutando comando: {exc}"


def _tool_list_files(pattern: str) -> str:
    try:
        matches = glob_module.glob(str(ROOT / pattern), recursive=True)
        if not matches:
            return "No se encontraron archivos con ese patron."
        rel = sorted(str(Path(m).relative_to(ROOT)) for m in matches)[:100]
        return "\n".join(rel)
    except Exception as exc:
        return f"Error listando archivos: {exc}"


def _tool_search_files(pattern: str, path: str = ".") -> str:
    try:
        search_path = str(_safe_path(path)) if path and path not in (".", "") else str(ROOT)
        result = subprocess.run(
            [
                "grep", "-r", "-l",
                "--include=*.yaml", "--include=*.md",
                "--include=*.json", "--include=*.py",
                "-m", "1", pattern, search_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = result.stdout.strip()
        if not out:
            return "No se encontraron coincidencias."
        lines = []
        for line in out.splitlines():
            try:
                lines.append(str(Path(line).relative_to(ROOT)))
            except ValueError:
                lines.append(line)
        return "\n".join(lines[:50])
    except Exception as exc:
        return f"Error buscando: {exc}"


def _execute_tool(name: str, args: dict) -> str:
    if name == "read_file":
        return _tool_read_file(str(args.get("path") or ""))
    if name == "write_file":
        return _tool_write_file(str(args.get("path") or ""), str(args.get("content") or ""))
    if name == "run_command":
        return _tool_run_command(str(args.get("command") or ""))
    if name == "list_files":
        return _tool_list_files(str(args.get("pattern") or "*"))
    if name == "search_files":
        return _tool_search_files(str(args.get("pattern") or ""), str(args.get("path") or "."))
    return f"Herramienta desconocida: {name}"


# ---------------------------------------------------------------------------
# Gemini API
# ---------------------------------------------------------------------------


def _api_post(api_key: str, model: str, payload: dict) -> dict:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Gemini API error {exc.code}: {body}") from exc


def _build_agent_system_prompt(channel: str) -> str:
    channel_name = "Telegram" if channel == "telegram" else "web"
    response_target = "Telegram" if channel == "telegram" else "la web"
    return (
        f"Contexto remoto {channel_name} para el proyecto personal-trainer.\n"
        "Eres el asistente de coaching de running de Abel, actuando como alternativa completa a OpenCode.\n"
        f"Responde de forma clara, breve y apta para {response_target}.\n"
        "Tienes acceso completo al repositorio mediante herramientas: leer archivos, escribirlos, ejecutar comandos, buscar.\n"
        "Lee AGENT.md como primer paso obligatorio para obtener el contexto del proyecto.\n"
        "Puedes editar archivos y ejecutar comandos si el usuario lo pide.\n"
        "Solo hagas commit o push si el usuario lo pide explicitamente. Sigue protocolo git seguro.\n"
        "Regla obligatoria: si el usuario pide planificar, agendar, crear o poner un entrenamiento, "
        "la tarea NO esta completa hasta que exista el YAML en training/planned/workouts, "
        "se haya intentado subir/agendar en Garmin y la respuesta indique resultado real. "
        "No respondas solo con una propuesta en chat salvo que el usuario pida explicitamente no agendarlo.\n"
        "Si el entrenamiento no encaja como running estructurado, usa fallback Garmin tipo other y, si falla, fitness_equipment.\n"
        "Puedes modificar datos operativos: athlete/, races/, planning/, training/ y generar salidas derivadas "
        "como status_dashboard, coach_decision o PDF semanal cuando corresponda.\n"
        "No narres pasos intermedios, comandos ejecutados, archivos modificados ni detalles tecnicos "
        "salvo que el usuario los pida explicitamente.\n"
        "No expliques como lo has hecho. Da primero el resultado final.\n"
        "Si la tarea salio bien, responde en 2-6 lineas maximo con lenguaje natural y facil de leer en movil.\n"
        "Si hace falta dar detalle, prioriza: que se hizo, para cuando quedo agendado y si hubo algun problema real.\n"
        "Responde en español.\n"
    )


def gemini_agent_run(api_key: str, model: str, user_message: str, channel: str = "telegram") -> str:
    """Bucle agente Gemini completo con function calling. Devuelve la respuesta final en texto."""
    contents: list[dict] = [{"role": "user", "parts": [{"text": user_message}]}]
    payload_base = {
        "systemInstruction": {"parts": [{"text": _build_agent_system_prompt(channel)}]},
        "tools": [_TOOL_DECLARATIONS],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192},
    }

    for iteration in range(MAX_AGENT_ITERATIONS):
        response = _api_post(api_key, model, {**payload_base, "contents": contents})
        candidate = (response.get("candidates") or [{}])[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []

        if not parts:
            finish_reason = candidate.get("finishReason", "unknown")
            return f"(Gemini no devolvio respuesta. finishReason={finish_reason})"

        function_calls = [p for p in parts if "functionCall" in p]
        text_parts = [p.get("text", "") for p in parts if "text" in p]

        if not function_calls:
            # Respuesta final de texto
            return " ".join(text_parts).strip() or "(sin respuesta de texto)"

        # Guardar turno del modelo con las llamadas a herramientas
        contents.append({"role": "model", "parts": parts})

        # Ejecutar herramientas y devolver resultados
        function_responses = []
        for fc in function_calls:
            fn = fc["functionCall"]
            fn_name = fn.get("name", "")
            fn_args = fn.get("args") or {}
            logger.info(
                "Gemini tool call iter=%d tool=%s args=%s",
                iteration, fn_name, list(fn_args.keys()),
            )
            result_text = _execute_tool(fn_name, fn_args)
            function_responses.append({
                "functionResponse": {
                    "name": fn_name,
                    "response": {"output": result_text},
                }
            })

        contents.append({"role": "user", "parts": function_responses})

    return "(Se alcanzo el limite maximo de iteraciones del agente Gemini)"


# ---------------------------------------------------------------------------
# Cadena de modelos (fallback en cascada)
# ---------------------------------------------------------------------------


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _QUOTA_ERROR_MARKERS)


def call_gemini_chain(api_key: str, models: list[str], user_message: str, channel: str = "telegram") -> tuple[str, str]:
    """Intenta modelos en orden usando el agente completo. Devuelve (texto, modelo_usado)."""
    last_exc: Exception = RuntimeError("No hay modelos Gemini configurados")
    for model in models:
        try:
            text = gemini_agent_run(api_key, model, user_message, channel)
            logger.info("Gemini agent succeeded model=%s", model)
            return text, model
        except Exception as exc:
            if _is_quota_error(exc):
                logger.warning("Model %s quota/unavailable, trying next. error=%s", model, exc)
                last_exc = exc
                continue
            raise
    raise last_exc


async def gemini_respond_async(
    message: str,
    api_key: str,
    models: list[str],
    channel: str = "telegram",
) -> tuple[str, str]:
    """Llama al agente Gemini en un executor para no bloquear el event loop. Devuelve (texto, modelo_usado)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call_gemini_chain, api_key, models, message, channel)


# ---------------------------------------------------------------------------
# Alerta Telegram
# ---------------------------------------------------------------------------


def send_gemini_fallback_alert(reason: str, model: str) -> None:
    """Envia aviso por Telegram cuando se activa el fallback Gemini."""
    try:
        from scripts.notifications.telegram_utils import load_telegram_config, send_text_message

        cfg = load_telegram_config()
        text = (
            "\u26a0\ufe0f Modo fallback Gemini activado\n"
            f"GPT-5.4 no disponible: {reason[:180]}\n"
            f"Respondiendo con: {model}\n"
            "Capacidades completas activas: lectura, escritura de archivos, Garmin, planificacion, etc."
        )
        send_text_message(text, config=cfg)
    except Exception as exc:
        logger.warning("Could not send Gemini fallback alert: %s", exc)
