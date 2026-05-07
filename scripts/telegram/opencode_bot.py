#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from opencode_bridge import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OPENCODE_MODEL,
    OpenCodeBridge,
    RemoteBotConfig,
    SessionStore,
    command_mentions_commit_or_push,
    confirmation_reason,
    load_config,
    normalize_model_name,
    run_command,
    sanitized_config,
)


ROOT = Path(__file__).resolve().parents[2]
MAX_TELEGRAM_MESSAGE = 3900


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram bot bridge for remote OpenCode access")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--check-config", action="store_true", help="Validate config without starting polling")
    return parser.parse_args()


def get_config(context: ContextTypes.DEFAULT_TYPE) -> RemoteBotConfig:
    return context.application.bot_data["config"]


def get_bridge(context: ContextTypes.DEFAULT_TYPE) -> OpenCodeBridge:
    return context.application.bot_data["bridge"]


def get_store(context: ContextTypes.DEFAULT_TYPE) -> SessionStore:
    return context.application.bot_data["store"]


def get_locks(context: ContextTypes.DEFAULT_TYPE) -> dict[str, asyncio.Lock]:
    return context.application.bot_data["locks"]


def active_model(context: ContextTypes.DEFAULT_TYPE, current_chat_id: str) -> str:
    return get_store(context).get_model(current_chat_id) or get_config(context).opencode.model


def chat_id(update: Update) -> str:
    if not update.effective_chat:
        return ""
    return str(update.effective_chat.id)


def is_authorized(update: Update, config: RemoteBotConfig) -> bool:
    current_chat_id = chat_id(update)
    return bool(current_chat_id and current_chat_id in config.telegram.allowed_chat_ids)


async def reject_if_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    config = get_config(context)
    if is_authorized(update, config):
        return False
    if update.effective_message:
        await update.effective_message.reply_text("Acceso no autorizado.")
    return True


async def send_long_text(update: Update, text: str) -> None:
    if not update.effective_message:
        return
    text = text.strip() or "(sin salida)"
    chunks = [text[index : index + MAX_TELEGRAM_MESSAGE] for index in range(0, len(text), MAX_TELEGRAM_MESSAGE)]
    for chunk in chunks:
        await update.effective_message.reply_text(chunk)


def read_text_file(path: Path, max_chars: int = 12000) -> str:
    if not path.exists():
        return f"No existe: {path.relative_to(ROOT)}"
    text = path.read_text(encoding="utf-8")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[Archivo truncado por limite del bot]"
    return text


async def run_project_command(command: list[str], timeout_s: int = 1800) -> str:
    returncode, stdout, stderr = await run_command(command, ROOT, timeout_s)
    output = stdout or stderr or "(sin salida)"
    prefix = "" if returncode == 0 else f"[exit {returncode}]\n"
    return prefix + output


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    config = get_config(context)
    text = (
        "Bot OpenCode remoto activo.\n"
        f"Proyecto: {config.opencode.project_dir}\n"
        f"OpenCode server: {config.opencode.server_url}\n"
        f"Modelo por defecto: {config.opencode.model}\n"
        f"Modelo activo: {active_model(context, chat_id(update))}\n"
        "Usa /help para ver comandos. Cualquier mensaje normal se enviara a OpenCode."
    )
    await send_long_text(update, text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    text = """
Comandos disponibles:

/start - comprobar acceso
/help - ayuda
/new_session - crear nueva sesion OpenCode en el proximo mensaje
/reset_session - olvidar sesion activa
/session - mostrar sesion activa
/model [modelo|reset] - ver o cambiar modelo OpenCode del chat
/status - mostrar planning/coach_decision.md
/dashboard - mostrar athlete/status_dashboard.md
/sync [YYYY-MM-DD] - ejecutar coach_sync con Garmin
/sync_local [YYYY-MM-DD] - ejecutar coach_sync sin contactar Garmin
/week - mostrar planning/weeks/semana_actual.md
/pdf_week - generar y enviar PDF semanal
/git - git status --short
/confirm <id> - confirmar una accion sensible pendiente
/cancel - cancelar confirmacion pendiente

Cualquier otro mensaje se envia a OpenCode como si hablaras con el proyecto.
Commit y push estan permitidos solo si los pides explicitamente.
Modelo por defecto del servicio: openai/gpt-5.4 con razonamiento default.
"""
    await send_long_text(update, text)


async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    get_store(context).clear_session(chat_id(update))
    await send_long_text(update, "Sesion OpenCode olvidada. El proximo mensaje creara una sesion nueva.")


async def session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    session_id = get_store(context).get_session(chat_id(update))
    model = active_model(context, chat_id(update))
    await send_long_text(update, f"Sesion activa: {session_id or '-'}\nModelo activo: {model}")


async def model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    current_chat_id = chat_id(update)
    if not context.args:
        await send_long_text(
            update,
            "\n".join(
                [
                    f"Modelo activo: {active_model(context, current_chat_id)}",
                    f"Modelo por defecto: {get_config(context).opencode.model}",
                    "Razonamiento: default de OpenCode, sin --variant.",
                    "Uso: /model openai/gpt-5.4 | /model gpt-5.5 | /model reset",
                ]
            ),
        )
        return

    raw_model = " ".join(context.args).strip()
    if raw_model.lower() in {"reset", "default", "defecto"}:
        get_store(context).clear_model(current_chat_id)
        await send_long_text(update, f"Modelo reseteado al default: {get_config(context).opencode.model}")
        return

    normalized = normalize_model_name(raw_model)
    get_store(context).set_model(current_chat_id, normalized)
    await send_long_text(
        update,
        f"Modelo activo actualizado a: {normalized}\nRazonamiento: default de OpenCode, sin --variant.",
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    await send_long_text(update, read_text_file(ROOT / "planning" / "coach_decision.md"))


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    await send_long_text(update, read_text_file(ROOT / "athlete" / "status_dashboard.md"))


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    await send_long_text(update, read_text_file(ROOT / "planning" / "weeks" / "semana_actual.md"))


async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    await send_long_text(update, await run_project_command(["git", "status", "--short"], timeout_s=60))


def command_date(context: ContextTypes.DEFAULT_TYPE) -> str:
    if context.args:
        return context.args[0]
    return date.today().isoformat()


async def sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    day = command_date(context)
    await update.effective_chat.send_action(ChatAction.TYPING)
    output = await run_project_command([sys.executable, "scripts/garmin/coach_sync.py", "--date", day], timeout_s=2400)
    await send_long_text(update, output)


async def sync_local(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    day = command_date(context)
    await update.effective_chat.send_action(ChatAction.TYPING)
    output = await run_project_command(
        [sys.executable, "scripts/garmin/coach_sync.py", "--date", day, "--skip-garmin"], timeout_s=1800
    )
    await send_long_text(update, output)


async def pdf_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    await update.effective_chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    output = await run_project_command(
        [sys.executable, "scripts/notifications/semana_pdf_telegram.py", "send-now", "--force"], timeout_s=300
    )
    await send_long_text(update, "PDF semanal generado/enviado.\n" + output)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    data = get_store(context).load()
    data.get("confirmations", {}).pop(chat_id(update), None)
    get_store(context).save(data)
    await send_long_text(update, "Confirmacion pendiente cancelada. Si habia una tarea en ejecucion, espera a que termine.")


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    if not context.args:
        await send_long_text(update, "Uso: /confirm <id>")
        return
    pending = get_store(context).pop_confirmation(chat_id(update), context.args[0])
    if not pending:
        await send_long_text(update, "No hay confirmacion pendiente con ese id.")
        return
    await dispatch_to_opencode(update, context, pending["message"], confirmed=True)


def blocked_by_policy(text: str, config: RemoteBotConfig) -> str | None:
    wants_commit, wants_push = command_mentions_commit_or_push(text)
    if wants_commit and not config.opencode.allow_commit:
        return "Los commits estan deshabilitados en opencode_remote.allow_commit."
    if wants_push and not config.opencode.allow_push:
        return "Los push estan deshabilitados en opencode_remote.allow_push."
    return None


async def dispatch_to_opencode(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, confirmed: bool = False) -> None:
    config = get_config(context)
    policy_error = blocked_by_policy(text, config)
    if policy_error:
        await send_long_text(update, policy_error)
        return

    if not confirmed:
        reason = confirmation_reason(text, config.opencode.require_confirmation_patterns)
        if reason:
            confirmation_id = get_store(context).set_confirmation(chat_id(update), text, reason)
            await send_long_text(update, f"Accion sensible bloqueada: {reason}\nConfirma con /confirm {confirmation_id}")
            return

    locks = get_locks(context)
    lock = locks.setdefault(chat_id(update), asyncio.Lock())
    if lock.locked():
        await send_long_text(update, "Ya hay una tarea OpenCode en curso para este chat. Espera a que termine.")
        return

    async with lock:
        await update.effective_chat.send_action(ChatAction.TYPING)
        result = await get_bridge(context).send(chat_id(update), text)
        response = result.text
        if result.returncode != 0:
            response = f"OpenCode devolvio exit {result.returncode}.\n\n{response}"
        await send_long_text(update, response)


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, context):
        return
    if not update.effective_message or not update.effective_message.text:
        await send_long_text(update, "Por ahora solo proceso mensajes de texto.")
        return
    await dispatch_to_opencode(update, context, update.effective_message.text)


def add_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new_session", new_session))
    application.add_handler(CommandHandler("reset_session", new_session))
    application.add_handler(CommandHandler("session", session))
    application.add_handler(CommandHandler("model", model))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(CommandHandler("week", week))
    application.add_handler(CommandHandler("git", git_status))
    application.add_handler(CommandHandler("sync", sync))
    application.add_handler(CommandHandler("sync_local", sync_local))
    application.add_handler(CommandHandler("pdf_week", pdf_week))
    application.add_handler(CommandHandler("confirm", confirm))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))


def build_application(config: RemoteBotConfig) -> Application:
    application = ApplicationBuilder().token(config.telegram.bot_token).build()
    bridge = OpenCodeBridge(config.opencode)
    application.bot_data["config"] = config
    application.bot_data["bridge"] = bridge
    application.bot_data["store"] = bridge.store
    application.bot_data["locks"] = {}
    add_handlers(application)
    return application


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.check_config:
        print(json.dumps(sanitized_config(config), indent=2, ensure_ascii=True))
        return
    application = build_application(config)
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
