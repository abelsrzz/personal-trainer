#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${OPENCODE_LOG_DIR:-/tmp/opencode}"
HOST="${OPENCODE_HOST:-127.0.0.1}"
PORT="${OPENCODE_PORT:-4096}"
WEB_HOST="${RUNNING_WEB_HOST:-0.0.0.0}"
WEB_PORT="${RUNNING_WEB_PORT:-8090}"
WEB_ENABLED="${RUNNING_WEB_ENABLED:-1}"
POST_WORKOUT_REFRESH_ENABLED="${POST_WORKOUT_REFRESH_ENABLED:-1}"
POST_WORKOUT_REFRESH_INTERVAL_SECONDS="${POST_WORKOUT_REFRESH_INTERVAL_SECONDS:-300}"
OPENCODE_BIN="${OPENCODE_BIN:-opencode}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-python3}"
INSTALL_OPENCODE="${INSTALL_OPENCODE:-1}"

SERVER_PID_FILE="$LOG_DIR/personal-trainer-opencode-serve.pid"
BOT_PID_FILE="$LOG_DIR/personal-trainer-telegram-bot.pid"
WEB_PID_FILE="$LOG_DIR/personal-trainer-web.pid"
POST_WORKOUT_REFRESH_PID_FILE="$LOG_DIR/personal-trainer-post-workout-refresh.pid"
SERVER_LOG="$LOG_DIR/personal-trainer-opencode-serve.log"
BOT_LOG="$LOG_DIR/personal-trainer-telegram-bot.log"
WEB_LOG="$LOG_DIR/personal-trainer-web.log"
POST_WORKOUT_REFRESH_LOG="$LOG_DIR/personal-trainer-post-workout-refresh.log"
WEB_CONFIG_FILE="$ROOT_DIR/web_v2/web_config.yaml"

usage() {
  cat <<EOF
Usage: ./start_server.sh [install|start|stop|restart|status|logs]

Commands:
  install   Install Python dependencies, prepare config, and install/check OpenCode
  start     Start opencode server, Telegram bot, and web portal (default)
  stop      Stop all processes started by this script
  restart   Stop and start again
  status    Show process status
  logs      Follow both log files

Environment overrides:
  OPENCODE_HOST=$HOST
  OPENCODE_PORT=$PORT
  RUNNING_WEB_HOST=$WEB_HOST
  RUNNING_WEB_PORT=$WEB_PORT
  RUNNING_WEB_ENABLED=$WEB_ENABLED
  POST_WORKOUT_REFRESH_ENABLED=$POST_WORKOUT_REFRESH_ENABLED
  POST_WORKOUT_REFRESH_INTERVAL_SECONDS=$POST_WORKOUT_REFRESH_INTERVAL_SECONDS
  OPENCODE_LOG_DIR=$LOG_DIR
  OPENCODE_BIN=$OPENCODE_BIN
  PYTHON_BIN=$PYTHON_BIN
  PYTHON_BOOTSTRAP=$PYTHON_BOOTSTRAP
  INSTALL_OPENCODE=$INSTALL_OPENCODE  # set to 0 to skip automatic OpenCode install
  web_v2/web_config.yaml              # local file with username/password/secret
  RUNNING_WEB_USERNAME=...            # optional override for username
  RUNNING_WEB_PASSWORD=...            # optional override for password
  RUNNING_WEB_SECRET=...              # optional override for session secret
EOF
}

resolve_opencode() {
  if command -v "$OPENCODE_BIN" >/dev/null 2>&1; then
    return 0
  fi

  if [[ -x "$HOME/.opencode/bin/opencode" ]]; then
    OPENCODE_BIN="$HOME/.opencode/bin/opencode"
    return 0
  fi

  return 1
}

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(<"$pid_file")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

wait_for_http() {
  local url="$1"
  local attempts="${2:-20}"
  local sleep_seconds="${3:-0.5}"
  local attempt=1

  while (( attempt <= attempts )); do
    if "$PYTHON_BIN" -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1)' "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
    ((attempt += 1))
  done

  return 1
}

require_runtime() {
  mkdir -p "$LOG_DIR"

  if ! resolve_opencode; then
    echo "ERROR: opencode binary not found: $OPENCODE_BIN" >&2
    echo "Run: ./start_server.sh install" >&2
    exit 1
  fi

  export PATH="$(dirname "$OPENCODE_BIN"):$PATH"

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python virtualenv not found or not executable: $PYTHON_BIN" >&2
    echo "Run: ./start_server.sh install" >&2
    exit 1
  fi

  if [[ ! -f "$ROOT_DIR/telegram/bot_config.yaml" ]]; then
    echo "ERROR: Missing telegram/bot_config.yaml" >&2
    echo "Create it from telegram/bot_config.yaml.example and set bot_token/chat_id." >&2
    exit 1
  fi
}

web_config_ready() {
  [[ "$WEB_ENABLED" != "1" ]] && return 0
  if [[ -f "$WEB_CONFIG_FILE" ]]; then
    return 0
  fi
  [[ -n "${RUNNING_WEB_USERNAME:-}" && -n "${RUNNING_WEB_PASSWORD:-}" ]]
}

install_runtime() {
  cd "$ROOT_DIR"
  mkdir -p "$LOG_DIR"

  echo "== Checking Python bootstrap"
  if ! command -v "$PYTHON_BOOTSTRAP" >/dev/null 2>&1; then
    echo "ERROR: Python bootstrap binary not found: $PYTHON_BOOTSTRAP" >&2
    echo "Install python3 and python3-venv with your OS package manager, then retry." >&2
    exit 1
  fi

  echo "== Creating/updating virtualenv"
  "$PYTHON_BOOTSTRAP" -m venv "$ROOT_DIR/.venv"

  echo "== Installing Python dependencies"
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"

  echo "== Checking OpenCode"
  if resolve_opencode; then
    echo "OpenCode found: $OPENCODE_BIN"
  else
    if [[ "$INSTALL_OPENCODE" == "1" ]]; then
      if ! command -v curl >/dev/null 2>&1; then
        echo "ERROR: curl is required to install OpenCode automatically." >&2
        echo "Install curl or set INSTALL_OPENCODE=0 and install OpenCode manually." >&2
        exit 1
      fi
      echo "Installing OpenCode via official installer"
      curl -fsSL https://opencode.ai/install | bash
      if ! resolve_opencode; then
        echo "ERROR: OpenCode installer finished but opencode was not found." >&2
        echo "Set OPENCODE_BIN=/path/to/opencode and retry." >&2
        exit 1
      fi
      echo "OpenCode installed: $OPENCODE_BIN"
    else
      echo "WARNING: OpenCode not installed. Install it manually before running start." >&2
    fi
  fi

  echo "== Preparing Telegram config"
  if [[ -f "$ROOT_DIR/telegram/bot_config.yaml" ]]; then
    echo "telegram/bot_config.yaml already exists; not overwriting."
  else
    cp "$ROOT_DIR/telegram/bot_config.yaml.example" "$ROOT_DIR/telegram/bot_config.yaml"
    echo "Created telegram/bot_config.yaml from example. Edit bot_token, chat_id and allowed_chat_ids before starting."
  fi

  echo "== Validating bot config"
  if "$PYTHON_BIN" scripts/telegram/opencode_bot.py --check-config >/dev/null 2>&1; then
    echo "Bot config OK"
  else
    echo "Bot config not ready yet. Edit telegram/bot_config.yaml, then run:" >&2
    echo "  $PYTHON_BIN scripts/telegram/opencode_bot.py --check-config" >&2
  fi

  if [[ "$WEB_ENABLED" == "1" ]]; then
    if web_config_ready; then
      echo "Web config OK"
    else
      echo "Web portal credentials not set yet. Create web_v2/web_config.yaml from web_v2/web_config.yaml.example or define RUNNING_WEB_USERNAME and RUNNING_WEB_PASSWORD." >&2
    fi
  fi

  echo "== Install complete"
  echo "Start the server with: ./start_server.sh start"
}

start_server() {
  require_runtime
  cd "$ROOT_DIR"
  local web_probe_host="$WEB_HOST"
  "$PYTHON_BIN" scripts/telegram/opencode_bot.py --check-config >/dev/null

  if [[ "$web_probe_host" == "0.0.0.0" ]]; then
    web_probe_host="127.0.0.1"
  fi

  if is_running "$SERVER_PID_FILE"; then
    echo "OpenCode server already running (pid $(<"$SERVER_PID_FILE"))"
  else
    nohup "$OPENCODE_BIN" serve --hostname "$HOST" --port "$PORT" >"$SERVER_LOG" 2>&1 &
    echo "$!" >"$SERVER_PID_FILE"
    echo "Started OpenCode server (pid $(<"$SERVER_PID_FILE"))"
  fi

  sleep 2

  if is_running "$BOT_PID_FILE"; then
    echo "Telegram bot already running (pid $(<"$BOT_PID_FILE"))"
  else
    nohup "$PYTHON_BIN" scripts/telegram/opencode_bot.py >"$BOT_LOG" 2>&1 &
    echo "$!" >"$BOT_PID_FILE"
    echo "Started Telegram bot (pid $(<"$BOT_PID_FILE"))"
  fi

  if [[ "$WEB_ENABLED" != "1" ]]; then
    echo "Web portal disabled (RUNNING_WEB_ENABLED=$WEB_ENABLED)"
  elif ! web_config_ready; then
    echo "Web portal skipped: create web_v2/web_config.yaml from web_v2/web_config.yaml.example or define RUNNING_WEB_USERNAME and RUNNING_WEB_PASSWORD first." >&2
  elif is_running "$WEB_PID_FILE"; then
    echo "Web portal already running (pid $(<"$WEB_PID_FILE"))"
  else
    nohup "$PYTHON_BIN" -m uvicorn scripts.web_v2.app:app --app-dir "$ROOT_DIR" --host "$WEB_HOST" --port "$WEB_PORT" --proxy-headers --forwarded-allow-ips='*' >"$WEB_LOG" 2>&1 &
    echo "$!" >"$WEB_PID_FILE"
    if is_running "$WEB_PID_FILE" && wait_for_http "http://$web_probe_host:$WEB_PORT/login"; then
      echo "Started web portal (pid $(<"$WEB_PID_FILE"))"
    else
      echo "Web portal failed to start. Check $WEB_LOG" >&2
    fi
  fi

  if [[ "$POST_WORKOUT_REFRESH_ENABLED" != "1" ]]; then
    echo "Post-workout refresh daemon disabled (POST_WORKOUT_REFRESH_ENABLED=$POST_WORKOUT_REFRESH_ENABLED)"
  elif is_running "$POST_WORKOUT_REFRESH_PID_FILE"; then
    echo "Post-workout refresh daemon already running (pid $(<"$POST_WORKOUT_REFRESH_PID_FILE"))"
  else
    nohup "$PYTHON_BIN" scripts/garmin/post_workout_refresh_daemon.py --interval-seconds "$POST_WORKOUT_REFRESH_INTERVAL_SECONDS" >"$POST_WORKOUT_REFRESH_LOG" 2>&1 &
    echo "$!" >"$POST_WORKOUT_REFRESH_PID_FILE"
    sleep 1
    if is_running "$POST_WORKOUT_REFRESH_PID_FILE"; then
      echo "Started post-workout refresh daemon (pid $(<"$POST_WORKOUT_REFRESH_PID_FILE"))"
    else
      echo "Post-workout refresh daemon failed to start. Check $POST_WORKOUT_REFRESH_LOG" >&2
    fi
  fi

  echo ""
  echo "OpenCode server: http://$HOST:$PORT"
  if is_running "$WEB_PID_FILE"; then
    echo "Web portal: http://$WEB_HOST:$WEB_PORT"
  fi
  echo "Logs:"
  echo "  $SERVER_LOG"
  echo "  $BOT_LOG"
  if [[ "$WEB_ENABLED" == "1" ]]; then
    echo "  $WEB_LOG"
  fi
  if [[ "$POST_WORKOUT_REFRESH_ENABLED" == "1" ]]; then
    echo "  $POST_WORKOUT_REFRESH_LOG"
  fi
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  if is_running "$pid_file"; then
    local pid
    pid="$(<"$pid_file")"
    kill "$pid"
    echo "Stopped $name (pid $pid)"
  else
    echo "$name is not running"
  fi
}

ensure_runtime_or_install() {
  if [[ -x "$PYTHON_BIN" ]]; then
    return 0
  fi
  echo "Python runtime not found. Running install first..."
  install_runtime
}

stop_server() {
  stop_process "Post-workout refresh daemon" "$POST_WORKOUT_REFRESH_PID_FILE"
  stop_process "Web portal" "$WEB_PID_FILE"
  stop_process "Telegram bot" "$BOT_PID_FILE"
  stop_process "OpenCode server" "$SERVER_PID_FILE"
}

status_server() {
  if is_running "$SERVER_PID_FILE"; then
    echo "OpenCode server: running (pid $(<"$SERVER_PID_FILE"))"
  else
    echo "OpenCode server: stopped"
  fi

  if is_running "$BOT_PID_FILE"; then
    echo "Telegram bot: running (pid $(<"$BOT_PID_FILE"))"
  else
    echo "Telegram bot: stopped"
  fi

  if is_running "$WEB_PID_FILE"; then
    echo "Web portal: running (pid $(<"$WEB_PID_FILE"))"
  else
    echo "Web portal: stopped"
  fi

  if is_running "$POST_WORKOUT_REFRESH_PID_FILE"; then
    echo "Post-workout refresh daemon: running (pid $(<"$POST_WORKOUT_REFRESH_PID_FILE"))"
  else
    echo "Post-workout refresh daemon: stopped"
  fi
}

logs_server() {
  mkdir -p "$LOG_DIR"
  touch "$SERVER_LOG" "$BOT_LOG" "$WEB_LOG" "$POST_WORKOUT_REFRESH_LOG"
  tail -f "$SERVER_LOG" "$BOT_LOG" "$WEB_LOG" "$POST_WORKOUT_REFRESH_LOG"
}

command="${1:-start}"

case "$command" in
  start)
    start_server
    ;;
  install)
    install_runtime
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    sleep 1
    ensure_runtime_or_install
    start_server
    ;;
  status)
    status_server
    ;;
  logs)
    logs_server
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
