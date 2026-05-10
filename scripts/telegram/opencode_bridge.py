#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import secrets
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "telegram" / "bot_config.yaml"
DEFAULT_OPENCODE_MODEL = "openai/gpt-5.4"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

logger = logging.getLogger("telegram.opencode_bridge")


def setup_logging() -> None:
    level_name = str(os.getenv("TELEGRAM_BRIDGE_LOG_LEVEL") or os.getenv("TELEGRAM_BOT_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    caption_prefix: str
    allowed_chat_ids: tuple[str, ...]


@dataclass(frozen=True)
class OpenCodeRemoteConfig:
    enabled: bool
    server_url: str
    project_dir: Path
    session_store: Path
    timeout_s: int
    allow_commit: bool
    allow_push: bool
    dangerously_skip_permissions: bool
    model: str | None
    max_response_chars: int
    require_confirmation_patterns: tuple[str, ...]


@dataclass(frozen=True)
class RemoteBotConfig:
    telegram: TelegramConfig
    opencode: OpenCodeRemoteConfig


@dataclass
class BridgeResult:
    text: str
    session_id: str | None
    model: str
    returncode: int
    stderr: str = ""
    trace_id: str = ""


@dataclass(frozen=True)
class BridgeHealth:
    ok: bool
    attach: bool
    user_message: str
    detail: str = ""
    opencode_version: str = ""


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def normalize_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> RemoteBotConfig:
    if not path.exists():
        raise FileNotFoundError(f"Missing Telegram config: {path}")

    data = load_yaml(path)
    telegram_data = data.get("telegram", {})
    opencode_data = data.get("opencode_remote", {})

    bot_token = str(os.getenv("TELEGRAM_BOT_TOKEN") or telegram_data.get("bot_token") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID") or telegram_data.get("chat_id") or "").strip()
    if not bot_token or not chat_id:
        raise ValueError("telegram.bot_token and telegram.chat_id are required")

    allowed = telegram_data.get("allowed_chat_ids") or [chat_id]
    allowed_chat_ids = tuple(str(item).strip() for item in allowed if str(item).strip())
    if chat_id not in allowed_chat_ids:
        allowed_chat_ids = (*allowed_chat_ids, chat_id)

    project_dir = normalize_path(opencode_data.get("project_dir") or ROOT)
    session_store = normalize_path(opencode_data.get("session_store") or "telegram/opencode_sessions.json")

    return RemoteBotConfig(
        telegram=TelegramConfig(
            bot_token=bot_token,
            chat_id=chat_id,
            caption_prefix=str(telegram_data.get("caption_prefix") or "Running Coach").strip(),
            allowed_chat_ids=allowed_chat_ids,
        ),
        opencode=OpenCodeRemoteConfig(
            enabled=bool(opencode_data.get("enabled", True)),
            server_url=str(opencode_data.get("server_url") or "http://127.0.0.1:4096").strip(),
            project_dir=project_dir,
            session_store=session_store,
            timeout_s=int(opencode_data.get("timeout_s") or 3600),
            allow_commit=bool(opencode_data.get("allow_commit", True)),
            allow_push=bool(opencode_data.get("allow_push", True)),
            dangerously_skip_permissions=bool(opencode_data.get("dangerously_skip_permissions", False)),
            model=normalize_model_name(opencode_data.get("model") or DEFAULT_OPENCODE_MODEL),
            max_response_chars=int(opencode_data.get("max_response_chars") or 12000),
            require_confirmation_patterns=tuple(
                str(item).lower() for item in opencode_data.get("require_confirmation_patterns", [])
            ),
        ),
    )


def sanitized_config(config: RemoteBotConfig) -> dict[str, Any]:
    return {
        "telegram": {
            "bot_token": "set" if config.telegram.bot_token else "missing",
            "chat_id": config.telegram.chat_id,
            "allowed_chat_ids": list(config.telegram.allowed_chat_ids),
        },
        "opencode_remote": {
            "enabled": config.opencode.enabled,
            "server_url": config.opencode.server_url,
            "project_dir": str(config.opencode.project_dir),
            "session_store": str(config.opencode.session_store),
            "timeout_s": config.opencode.timeout_s,
            "allow_commit": config.opencode.allow_commit,
            "allow_push": config.opencode.allow_push,
            "dangerously_skip_permissions": config.opencode.dangerously_skip_permissions,
            "model": config.opencode.model,
        },
    }


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sessions": {}, "confirmations": {}}
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        data.setdefault("sessions", {})
        data.setdefault("confirmations", {})
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        tmp_path.replace(self.path)

    def get_session(self, chat_id: int | str) -> str | None:
        data = self.load()
        session = data["sessions"].get(str(chat_id), {})
        return session.get("session_id")

    def get_session_backend(self, chat_id: int | str) -> str | None:
        data = self.load()
        session = data["sessions"].get(str(chat_id), {})
        backend = session.get("backend")
        return str(backend) if backend else None

    def get_model(self, chat_id: int | str) -> str | None:
        data = self.load()
        session = data["sessions"].get(str(chat_id), {})
        return session.get("model")

    def set_model(self, chat_id: int | str, model: str) -> None:
        data = self.load()
        session = data["sessions"].setdefault(str(chat_id), {})
        session["model"] = normalize_model_name(model)
        session["model_updated_at"] = datetime.now(UTC).isoformat()
        self.save(data)

    def clear_model(self, chat_id: int | str) -> None:
        data = self.load()
        session = data["sessions"].setdefault(str(chat_id), {})
        session.pop("model", None)
        session["model_updated_at"] = datetime.now(UTC).isoformat()
        self.save(data)

    def set_session(self, chat_id: int | str, session_id: str, title: str, backend: str) -> None:
        data = self.load()
        existing = data["sessions"].get(str(chat_id), {})
        data["sessions"][str(chat_id)] = {
            "session_id": session_id,
            "title": title,
            "backend": backend,
            **({"model": existing["model"]} if existing.get("model") else {}),
            **({"model_updated_at": existing["model_updated_at"]} if existing.get("model_updated_at") else {}),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.save(data)

    def clear_session(self, chat_id: int | str) -> None:
        data = self.load()
        session = data["sessions"].get(str(chat_id), {})
        model = session.get("model")
        if model:
            data["sessions"][str(chat_id)] = {
                "model": model,
                "model_updated_at": session.get("model_updated_at"),
            }
        else:
            data["sessions"].pop(str(chat_id), None)
        self.save(data)

    def set_confirmation(self, chat_id: int | str, message: str, reason: str) -> str:
        data = self.load()
        confirmation_id = secrets.token_hex(3)
        data["confirmations"][str(chat_id)] = {
            "id": confirmation_id,
            "message": message,
            "reason": reason,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.save(data)
        return confirmation_id

    def pop_confirmation(self, chat_id: int | str, confirmation_id: str) -> dict[str, Any] | None:
        data = self.load()
        pending = data["confirmations"].get(str(chat_id))
        if not pending or pending.get("id") != confirmation_id:
            return None
        data["confirmations"].pop(str(chat_id), None)
        self.save(data)
        return pending


def strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value).strip()


def normalize_model_name(value: Any) -> str:
    text = str(value or DEFAULT_OPENCODE_MODEL).strip()
    if not text or text.lower() in {"default", "null", "none"}:
        return DEFAULT_OPENCODE_MODEL
    text = text.replace(" ", "-")
    if "/" not in text and text.startswith("gpt"):
        # If the user types just "gpt-5.2", keep the same provider as default.
        provider = DEFAULT_OPENCODE_MODEL.split("/", 1)[0] if "/" in DEFAULT_OPENCODE_MODEL else "openai"
        return f"{provider}/{text}"
    return text


def _server_host_port(server_url: str) -> tuple[str, int] | None:
    try:
        parsed = urlparse(server_url)
    except Exception:
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.hostname, port


def probe_opencode_server(server_url: str, timeout_s: float = 2.0) -> str | None:
    """Fast reachability probe to avoid long hangs.

    Note: some server setups accept TCP but never answer HTTP. We treat that as
    unresponsive and avoid using --attach.
    """
    target = _server_host_port(server_url)
    if not target:
        return f"OpenCode server_url invalida: {server_url}"
    host, port = target
    try:
        with socket.create_connection((host, port), timeout=timeout_s) as sock:
            sock.settimeout(timeout_s)
            request = (
                f"GET /config HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n"
            ).encode("ascii", errors="ignore")
            sock.sendall(request)
            first = sock.recv(1)
            if first:
                return None
            return f"OpenCode server no devuelve respuesta HTTP en {server_url}"
    except OSError as exc:
        # In practice `socket.timeout`/`TimeoutError` can bubble up as OSError.
        if isinstance(exc, TimeoutError) or getattr(exc, "errno", None) is None and "timed out" in str(exc).lower():
            return (
                f"OpenCode server no responde a HTTP en {server_url} ({host}:{port}): timeout. "
                "Puede estar colgado; reinicia `opencode serve` o deja que el bot use ejecucion local."
            )
        return (
            f"OpenCode server no alcanzable en {server_url} ({host}:{port}): {exc}. "
            "Asegurate de tener `opencode serve` corriendo y que el bot use la URL correcta."
        )


def preview_text(value: str, limit: int = 500) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


async def run_command(
    command: list[str],
    cwd: Path,
    timeout_s: int,
    on_started: Callable[[], Awaitable[None]] | None = None,
) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return 127, "", f"Command failed to start: {exc}"
    if on_started is not None:
        await on_started()
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 124, "", (
            f"Command timed out after {timeout_s}s. "
            "La tarea de OpenCode excedio el limite del bot; prueba una peticion mas concreta o aumenta opencode_remote.timeout_s."
        )
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    rc = process.returncode or 0
    clean_stdout = strip_ansi(stdout)
    clean_stderr = strip_ansi(stderr)
    # Some opencode runs can succeed but produce no output depending on mode.
    # Keep a short debug sample to understand what's happening.
    if rc == 0 and not clean_stdout and not clean_stderr:
        logger.warning(
            "Command produced no output rc=0 cmd=%s",
            " ".join(command[:8]) + (" ..." if len(command) > 8 else ""),
        )
    return rc, clean_stdout, clean_stderr


def extract_sessions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        sessions: list[dict[str, Any]] = []
        for item in payload:
            sessions.extend(extract_sessions(item))
        return sessions
    if not isinstance(payload, dict):
        return []
    if any(key in payload for key in ["id", "sessionID", "sessionId"]):
        return [payload]
    sessions = []
    for value in payload.values():
        sessions.extend(extract_sessions(value))
    return sessions


def session_id_from_item(item: dict[str, Any]) -> str | None:
    for key in ["id", "sessionID", "sessionId"]:
        if item.get(key):
            return str(item[key])
    return None


def session_title_from_item(item: dict[str, Any]) -> str:
    for key in ["title", "name", "description"]:
        if item.get(key):
            return str(item[key])
    return ""


class OpenCodeBridge:
    def __init__(self, config: OpenCodeRemoteConfig) -> None:
        self.config = config
        self.store = SessionStore(config.session_store)

    def build_prompt(self, message: str) -> str:
        return (
            "Contexto remoto Telegram para el proyecto personal-trainer.\n"
            "Actua como OpenCode dentro de este repositorio. Responde de forma clara, breve y apta para Telegram.\n"
            "Puedes editar archivos y ejecutar comandos si el usuario lo pide.\n"
            "Solo hagas commit o push si el usuario lo pide explicitamente. Sigue protocolo git seguro: no force push, no reset destructivo sin confirmacion.\n"
            "Regla obligatoria: si el usuario pide planificar, agendar, crear o poner un entrenamiento, la tarea NO esta completa hasta que exista el YAML en training/planned/workouts, se haya intentado subir/agendar en Garmin y la respuesta indique resultado real. No respondas solo con una propuesta en chat salvo que el usuario pida explicitamente no agendarlo.\n"
            "Si el entrenamiento no encaja como running estructurado, usa fallback Garmin tipo other y, si falla, fitness_equipment.\n"
            "Desde Telegram SI puedes modificar datos operativos del entrenador: athlete/, races/, planning/, training/ y generar salidas derivadas como status_dashboard, coach_decision o PDF semanal cuando corresponda.\n"
            "Desde Telegram NO puedes modificar la web, el sistema agentico, scripts, prompts, .agents, system, deploy, requirements, configuraciones del bot o el funcionamiento del programa.\n"
            "Si el usuario pide cambiar comportamiento del sistema o codigo, no lo hagas desde Telegram: responde que esa clase de cambio debe hacerse fuera del canal remoto.\n"
            "No narres pasos intermedios, progreso interno, comandos ejecutados, archivos modificados ni detalles tecnicos salvo que el usuario los pida explicitamente.\n"
            "No expliques como lo has hecho. Da primero el resultado final.\n"
            "Si la tarea salio bien, responde en 2-6 lineas maximo, con lenguaje natural y facil de leer en movil.\n"
            "Si hace falta dar detalle, prioriza: que se hizo, para cuando quedo agendado y si hubo algun problema real.\n"
            "Usa los archivos AGENT.md, .agents/, athlete/status_dashboard.md, planning/coach_decision.md y el contexto obligatorio descrito en el repositorio cuando aplique.\n\n"
            f"Mensaje del usuario:\n{message}"
        )

    async def health_check(self) -> BridgeHealth:
        if not self.config.enabled:
            return BridgeHealth(
                ok=False,
                attach=False,
                user_message="Problema operativo: el bridge de OpenCode esta deshabilitado en la configuracion.",
                detail="OpenCode remote bridge disabled in config.",
            )
        if not self.config.project_dir.exists():
            return BridgeHealth(
                ok=False,
                attach=False,
                user_message=f"Problema operativo: no existe el directorio del proyecto `{self.config.project_dir}`.",
                detail=f"Project dir does not exist: {self.config.project_dir}",
            )

        returncode, stdout, stderr = await run_command(["opencode", "--version"], self.config.project_dir, 10)
        version = (stdout or stderr).strip()
        if returncode != 0:
            detail = stderr or stdout or "opencode --version failed"
            return BridgeHealth(
                ok=False,
                attach=False,
                user_message=(
                    "Problema operativo: no puedo arrancar OpenCode en este momento. "
                    "Revisa la instalacion o el entorno del bot."
                ),
                detail=detail,
                opencode_version=version,
            )

        probe_error = probe_opencode_server(self.config.server_url)
        if probe_error is None:
            return BridgeHealth(
                ok=True,
                attach=True,
                user_message="OpenCode procesando respuesta.",
                detail="OpenCode server reachable.",
                opencode_version=version,
            )

        return BridgeHealth(
            ok=True,
            attach=False,
            user_message=(
                "OpenCode procesando respuesta. El servidor remoto no responde, pero sigo en modo local."
            ),
            detail=probe_error,
            opencode_version=version,
        )

    def build_run_command(
        self,
        prompt: str,
        session_id: str | None,
        title: str | None,
        model: str,
        *,
        attach: bool,
    ) -> list[str]:
        command = ["opencode", "run"]
        if attach:
            command.extend(["--attach", self.config.server_url])
        command.extend(["--dir", str(self.config.project_dir)])
        command.extend(["--model", model])
        # Keep default format so stdout contains the assistant answer.
        # Also print internal logs to stderr to help debugging if stdout is empty.
        command.append("--print-logs")
        if self.config.dangerously_skip_permissions:
            command.append("--dangerously-skip-permissions")
        if session_id:
            command.extend(["--session", session_id])
        elif title:
            command.extend(["--title", title])
        command.append(prompt)
        return command

    async def discover_session_id(self, title: str) -> str | None:
        command = ["opencode", "session", "list", "--format", "json", "--max-count", "20"]
        logger.info("Discovering session id by title=%s", title)
        returncode, stdout, _stderr = await run_command(command, self.config.project_dir, 30)
        if returncode != 0 or not stdout:
            logger.warning("Session list failed: exit=%s stdout_len=%s", returncode, len(stdout or ""))
            return None
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("Session list returned invalid JSON")
            return None
        sessions = extract_sessions(payload)
        for item in sessions:
            if session_title_from_item(item) == title:
                return session_id_from_item(item)
        return session_id_from_item(sessions[0]) if sessions else None

    async def send(
        self,
        chat_id: int | str,
        message: str,
        health: BridgeHealth | None = None,
        on_started: Callable[[str], Awaitable[None]] | None = None,
    ) -> BridgeResult:
        health = health or await self.health_check()
        if not health.ok:
            return BridgeResult(health.user_message, None, self.config.model, 1, stderr=health.detail)

        session_id = self.store.get_session(chat_id)
        session_backend = self.store.get_session_backend(chat_id)
        model = self.store.get_model(chat_id) or self.config.model
        trace_id = secrets.token_hex(4)
        title = None if session_id else f"telegram-{chat_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        prompt = self.build_prompt(message)

        probe_error = health.detail if not health.attach else None
        attach = health.attach
        if not attach:
            logger.warning("OpenCode server unresponsive; using local run (no --attach): %s", probe_error)

        backend = "attach" if attach else "local"
        # If the previous session was created using a different backend, do not
        # attempt to continue it.
        if session_id and session_backend and session_backend != backend:
            logger.warning(
                "Session backend mismatch chat_id=%s session_backend=%s current_backend=%s; starting new session",
                str(chat_id),
                session_backend,
                backend,
            )
            session_id = None
            title = f"telegram-{chat_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

        # Legacy stored sessions (before backend tracking) are unsafe for attach.
        # They are the exact source of the current Telegram hang.
        if attach and session_id and not session_backend:
            logger.warning(
                "Legacy attach session without backend metadata chat_id=%s session_id=%s; starting fresh",
                str(chat_id),
                session_id,
            )
            session_id = None
            title = f"telegram-{chat_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

        command = self.build_run_command(prompt, session_id, title, model, attach=attach)

        # Do not log the full prompt (can include user/private data).
        command_preview = command[:-1]
        logger.info(
            "OpenCode run start trace_id=%s chat_id=%s session_id=%s model=%s title=%s cmd=%s prompt_chars=%s message_preview=%s",
            trace_id,
            str(chat_id),
            session_id or "-",
            model,
            title or "-",
            " ".join(command_preview),
            len(prompt),
            preview_text(message, 180),
        )
        started_message = (
            "OpenCode ya esta procesando la respuesta."
            if attach
            else "OpenCode ya esta procesando la respuesta en modo local."
        )

        async def notify_started_once() -> None:
            if on_started is not None:
                await on_started(started_message)

        started = asyncio.get_running_loop().time()
        first_timeout_s = min(self.config.timeout_s, 25) if attach else self.config.timeout_s
        returncode, stdout, stderr = await run_command(
            command,
            self.config.project_dir,
            first_timeout_s,
            on_started=notify_started_once,
        )
        elapsed_s = asyncio.get_running_loop().time() - started
        logger.info(
            "OpenCode run done trace_id=%s chat_id=%s exit=%s elapsed_s=%.2f timeout_s=%s stdout_len=%s stderr_len=%s stdout_preview=%s stderr_preview=%s",
            trace_id,
            str(chat_id),
            returncode,
            elapsed_s,
            first_timeout_s,
            len(stdout or ""),
            len(stderr or ""),
            preview_text(stdout, 220),
            preview_text(stderr, 220),
        )

        if attach and returncode == 124:
            logger.warning("Attach run timed out; retrying locally trace_id=%s chat_id=%s", trace_id, str(chat_id))
            command = self.build_run_command(prompt, session_id, title, model, attach=False)
            started_retry = asyncio.get_running_loop().time()
            returncode, stdout, stderr = await run_command(command, self.config.project_dir, self.config.timeout_s)
            elapsed_retry_s = asyncio.get_running_loop().time() - started_retry
            logger.info(
                "OpenCode local retry done trace_id=%s chat_id=%s exit=%s elapsed_s=%.2f stdout_len=%s stderr_len=%s stdout_preview=%s stderr_preview=%s",
                trace_id,
                str(chat_id),
                returncode,
                elapsed_retry_s,
                len(stdout or ""),
                len(stderr or ""),
                preview_text(stdout, 220),
                preview_text(stderr, 220),
            )

        # On some setups, `opencode run --attach` can succeed but return no
        # assistant text. If that happens, retry locally once.
        if attach and returncode == 0 and not (stdout or "").strip():
            logger.warning(
                "Attach run produced no stdout; retrying locally trace_id=%s chat_id=%s stderr_len=%s",
                trace_id,
                str(chat_id),
                len(stderr or ""),
            )
            # Avoid continuing an attach-created session when switching backend.
            session_id = None
            command = self.build_run_command(prompt, session_id, title, model, attach=False)
            started_retry2 = asyncio.get_running_loop().time()
            returncode, stdout, stderr = await run_command(command, self.config.project_dir, self.config.timeout_s)
            elapsed_retry2_s = asyncio.get_running_loop().time() - started_retry2
            logger.info(
                "OpenCode local retry2 done trace_id=%s chat_id=%s exit=%s elapsed_s=%.2f stdout_len=%s stderr_len=%s stdout_preview=%s stderr_preview=%s",
                trace_id,
                str(chat_id),
                returncode,
                elapsed_retry2_s,
                len(stdout or ""),
                len(stderr or ""),
                preview_text(stdout, 220),
                preview_text(stderr, 220),
            )

        if not session_id and title and returncode == 0:
            discovered = await self.discover_session_id(title)
            if discovered:
                session_id = discovered
                self.store.set_session(chat_id, session_id, title, backend=backend)
                logger.info("Session stored chat_id=%s session_id=%s title=%s", str(chat_id), session_id, title)
            else:
                logger.warning("Could not discover session id for title=%s", title)

        text = (stdout or "").strip()
        if not text:
            # Do not dump internal logs to Telegram; instruct to check bot logs.
            text = (
                "OpenCode no devolvio respuesta de texto. "
                "Revisa el log del bot/bridge para ver el motivo (timeout, provider, permisos)."
            )
        if len(text) > self.config.max_response_chars:
            text = text[: self.config.max_response_chars] + "\n\n[Respuesta truncada por limite del bot]"
        return BridgeResult(text=text, session_id=session_id, model=model, returncode=returncode, stderr=stderr, trace_id=trace_id)


def command_mentions_commit_or_push(text: str) -> tuple[bool, bool]:
    lower = text.lower()
    wants_commit = "commit" in lower or "commite" in lower or "commitea" in lower
    wants_push = "push" in lower or "pushea" in lower or "sube los cambios" in lower
    return wants_commit, wants_push


def confirmation_reason(text: str, patterns: tuple[str, ...]) -> str | None:
    lower = text.lower()
    for pattern in patterns:
        if pattern and pattern in lower:
            return f"Patron sensible detectado: {pattern}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCode bridge utilities for Telegram bot")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--chat-id", default="local-test")
    parser.add_argument("--message", help="Send a test message through the bridge")
    args = parser.parse_args()
    setup_logging()
    config = load_config(args.config)
    if args.check_config:
        print(json.dumps(sanitized_config(config), indent=2, ensure_ascii=True))
        return
    if args.message:
        result = asyncio.run(OpenCodeBridge(config.opencode).send(args.chat_id, args.message))
        print(result.text)


if __name__ == "__main__":
    main()
