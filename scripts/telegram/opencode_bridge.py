#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "telegram" / "bot_config.yaml"
DEFAULT_OPENCODE_MODEL = "openai/gpt-5.4"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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
            timeout_s=int(opencode_data.get("timeout_s") or 1800),
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

    def set_session(self, chat_id: int | str, session_id: str, title: str) -> None:
        data = self.load()
        existing = data["sessions"].get(str(chat_id), {})
        data["sessions"][str(chat_id)] = {
            "session_id": session_id,
            "title": title,
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
            data["sessions"][str(chat_id)] = {"model": model, "model_updated_at": session.get("model_updated_at")}
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
        return f"openai/{text}"
    return text


async def run_command(command: list[str], cwd: Path, timeout_s: int) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 124, "", f"Command timed out after {timeout_s}s"
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return process.returncode or 0, strip_ansi(stdout), strip_ansi(stderr)


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
            "Usa los archivos AGENT.md, .agents/, athlete/status_dashboard.md y planning/coach_decision.md como contexto operativo cuando aplique.\n\n"
            f"Mensaje del usuario:\n{message}"
        )

    def build_run_command(self, prompt: str, session_id: str | None, title: str | None, model: str) -> list[str]:
        command = [
            "opencode",
            "run",
            "--attach",
            self.config.server_url,
            "--dir",
            str(self.config.project_dir),
        ]
        command.extend(["--model", model])
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
        returncode, stdout, _stderr = await run_command(command, self.config.project_dir, 30)
        if returncode != 0 or not stdout:
            return None
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        sessions = extract_sessions(payload)
        for item in sessions:
            if session_title_from_item(item) == title:
                return session_id_from_item(item)
        return session_id_from_item(sessions[0]) if sessions else None

    async def send(self, chat_id: int | str, message: str) -> BridgeResult:
        if not self.config.enabled:
            return BridgeResult("OpenCode remote bridge is disabled in config.", None, self.config.model, 1)
        if not self.config.project_dir.exists():
            return BridgeResult(f"Project dir does not exist: {self.config.project_dir}", None, self.config.model, 1)

        session_id = self.store.get_session(chat_id)
        model = self.store.get_model(chat_id) or self.config.model
        title = None if session_id else f"telegram-{chat_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        prompt = self.build_prompt(message)
        command = self.build_run_command(prompt, session_id, title, model)
        returncode, stdout, stderr = await run_command(command, self.config.project_dir, self.config.timeout_s)

        if not session_id and title and returncode == 0:
            discovered = await self.discover_session_id(title)
            if discovered:
                session_id = discovered
                self.store.set_session(chat_id, session_id, title)

        text = stdout or stderr or "OpenCode finished without output."
        if len(text) > self.config.max_response_chars:
            text = text[: self.config.max_response_chars] + "\n\n[Respuesta truncada por limite del bot]"
        return BridgeResult(text=text, session_id=session_id, model=model, returncode=returncode, stderr=stderr)


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
    config = load_config(args.config)
    if args.check_config:
        print(json.dumps(sanitized_config(config), indent=2, ensure_ascii=True))
        return
    if args.message:
        result = asyncio.run(OpenCodeBridge(config.opencode).send(args.chat_id, args.message))
        print(result.text)


if __name__ == "__main__":
    main()
