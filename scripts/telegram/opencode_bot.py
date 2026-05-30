#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import suppress
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

logger = logging.getLogger("telegram.opencode_bot")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram bot bridge for remote OpenCode access")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--check-config", action="store_true", help="Validate config without starting polling")
    return parser.parse_args()


def setup_logging() -> None:
    # Keep logs simple and greppable in systemd/nohup.
    level_name = str(os.getenv("TELEGRAM_BOT_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


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


async def keep_chat_action(chat, action: ChatAction, interval_s: float = 4.0) -> None:
    while True:
        await chat.send_action(action)
        await asyncio.sleep(interval_s)


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
    logger.info("Session cleared chat_id=%s", chat_id(update))
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
    current_chat_id = chat_id(update)
    logger.info(
        "Incoming message chat_id=%s confirmed=%s chars=%s",
        current_chat_id,
        confirmed,
        len(text or ""),
    )
    policy_error = blocked_by_policy(text, config)
    if policy_error:
        logger.warning("Blocked by policy chat_id=%s reason=%s", current_chat_id, policy_error)
        await send_long_text(update, policy_error)
        return

    if not confirmed:
        reason = confirmation_reason(text, config.opencode.require_confirmation_patterns)
        if reason:
            confirmation_id = get_store(context).set_confirmation(chat_id(update), text, reason)
            logger.warning(
                "Sensitive action requires confirmation chat_id=%s reason=%s confirmation_id=%s",
                current_chat_id,
                reason,
                confirmation_id,
            )
            await send_long_text(update, f"Accion sensible bloqueada: {reason}\nConfirma con /confirm {confirmation_id}")
            return

    locks = get_locks(context)
    lock = locks.setdefault(chat_id(update), asyncio.Lock())
    if lock.locked():
        logger.warning("Per-chat lock already held chat_id=%s", current_chat_id)
        await send_long_text(update, "Ya hay una tarea OpenCode en curso para este chat. Espera a que termine.")
        return

    async with lock:
        action_task = asyncio.create_task(keep_chat_action(update.effective_chat, ChatAction.TYPING))
        try:
            bridge = get_bridge(context)
            health = await bridge.health_check()
            logger.info(
                "OpenCode health chat_id=%s ok=%s attach=%s detail=%s version=%s",
                current_chat_id,
                health.ok,
                health.attach,
                health.detail,
                health.opencode_version,
            )
            if not health.ok:
                logger.error("OpenCode health failed chat_id=%s detail=%s", current_chat_id, health.detail)
                await send_long_text(update, health.user_message)
                return

            async def notify_started(message: str) -> None:
                await send_long_text(update, message)

            result = await bridge.send(chat_id(update), text, health=health, on_started=notify_started)
        except Exception as exc:
            logger.exception("Unexpected OpenCode failure chat_id=%s error=%s", current_chat_id, exc)
            await send_long_text(
                update,
                "Problema operativo mientras OpenCode procesaba la respuesta. Revisa el log del bot para ver el detalle.",
            )
            return
        finally:
            action_task.cancel()
            with suppress(asyncio.CancelledError):
                await action_task
        response = result.text
        if result.returncode != 0:
            logger.error(
                "OpenCode error trace_id=%s chat_id=%s exit=%s model=%s session_id=%s stderr_len=%s stderr_preview=%s",
                result.trace_id or "-",
                current_chat_id,
                result.returncode,
                result.model,
                result.session_id or "-",
                len(result.stderr or ""),
                " ".join((result.stderr or "").split())[:220],
            )
            response = f"OpenCode devolvio exit {result.returncode}.\n\n{response}"
        else:
            logger.info(
                "OpenCode success trace_id=%s chat_id=%s model=%s session_id=%s response_chars=%s",
                result.trace_id or "-",
                current_chat_id,
                result.model,
                result.session_id or "-",
                len(response or ""),
            )
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
    setup_logging()
    config = load_config(args.config)
    if args.check_config:
        print(json.dumps(sanitized_config(config), indent=2, ensure_ascii=True))
        return
    logger.info(
        "Starting bot allowed_chat_ids=%s server_url=%s project_dir=%s default_model=%s",
        ",".join(config.telegram.allowed_chat_ids),
        config.opencode.server_url,
        str(config.opencode.project_dir),
        config.opencode.model,
    )
    application = build_application(config)
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
