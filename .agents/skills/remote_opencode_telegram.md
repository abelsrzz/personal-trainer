# Skill: Remote OpenCode Telegram

## Purpose

Operate this project remotely through Telegram while preserving the same repository-aware OpenCode behavior.

## Runtime Commands

```bash
opencode serve --hostname 127.0.0.1 --port 4096
source .venv/bin/activate
python scripts/telegram/opencode_bot.py
```

## Check Commands

```bash
python scripts/telegram/opencode_bot.py --check-config
python scripts/telegram/opencode_bridge.py --check-config
```

## Telegram Commands

- `/status`: show coach decision.
- `/dashboard`: show athlete dashboard.
- `/sync`: run Garmin coach sync.
- `/sync_local`: run local coach sync.
- `/week`: show active week.
- `/pdf_week`: generate and send weekly PDF.
- `/git`: show repository status.
- `/model`: show active model.
- `/model openai/gpt-5.4`: set model for this chat.
- `/model reset`: reset to default model.
- `/new_session`: start a fresh OpenCode session on next message.
- normal text: forward to OpenCode.

## Safety Rules

- Only allowed chat ids may use the bot.
- The OpenCode server must bind to `127.0.0.1`.
- Default model is `openai/gpt-5.4`; do not pass a reasoning variant unless explicitly implemented later.
- Commits and pushes are allowed only by explicit user request.
- Destructive patterns require `/confirm <id>`.
- Never print bot tokens or Garmin credentials.
