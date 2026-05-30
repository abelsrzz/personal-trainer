# Workflow: Remote OpenCode Via Telegram

## Purpose

Allow Abel to interact with this repository remotely through Telegram as if talking to OpenCode locally.

## Runtime Components

- `opencode serve --hostname 127.0.0.1 --port 4096`
- `python scripts/telegram/opencode_bot.py`

## Normal Message Flow

1. Telegram receives a message from an allowed chat.
2. `scripts/telegram/opencode_bot.py` validates the `chat_id`.
3. The bot routes commands directly or forwards normal text to `scripts/telegram/opencode_bridge.py`.
4. The bridge calls `opencode run --attach http://127.0.0.1:4096 --dir <project>`.
5. The response is split into Telegram-sized messages.

## Session Handling

- Sessions are stored in `telegram/opencode_sessions.json`.
- `/new_session` or `/reset_session` clears the session for the chat.
- `/session` shows the current session id.
- `/model` shows or changes the per-chat model override.
- The default model is `openai/gpt-5.4` with OpenCode default reasoning; no `--variant` is passed.

## Safety

- Only allowed `chat_id` values can use the bot.
- OpenCode server must stay bound to `127.0.0.1`.
- Commit and push are allowed only by explicit user request.
- Destructive patterns require `/confirm <id>`.
- The Telegram token and session state are gitignored.

## Project Commands

- `/status`: show `planning/coach_decision.md`.
- `/dashboard`: show `athlete/status_dashboard.md`.
- `/sync`: run `coach_sync.py` with Garmin.
- `/sync_local`: run `coach_sync.py --skip-garmin`.
- `/week`: show active week.
- `/pdf_week`: generate and send weekly PDF.
- `/git`: show `git status --short`.
- `/model`: show active model.
- `/model openai/gpt-5.4`: change model for the chat.
- `/model reset`: return to default model.
