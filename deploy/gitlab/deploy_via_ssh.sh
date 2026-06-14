#!/usr/bin/env bash

set -euo pipefail

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    printf 'Missing required variable: %s\n' "$name" >&2
    exit 1
  fi
}

resolve_secret_value() {
  local raw_value="$1"
  if [[ -f "$raw_value" ]]; then
    cat "$raw_value"
  else
    printf '%s' "$raw_value"
  fi
}

require_var DEPLOY_HOST
require_var DEPLOY_USER
require_var DEPLOY_SSH_PRIVATE_KEY
require_var DEPLOY_RESTART_COMMAND

DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/personal-trainer}"
DEPLOY_POST_SYNC_COMMAND="${DEPLOY_POST_SYNC_COMMAND:-}"
SSH_DIR="$HOME/.ssh"
SSH_KEY_FILE="$SSH_DIR/id_ed25519"
DEPLOY_SSH_PRIVATE_KEY_VALUE="$(resolve_secret_value "$DEPLOY_SSH_PRIVATE_KEY")"
DEPLOY_SSH_KNOWN_HOSTS_VALUE="${DEPLOY_SSH_KNOWN_HOSTS:-}"

if [[ -n "$DEPLOY_SSH_KNOWN_HOSTS_VALUE" ]]; then
  DEPLOY_SSH_KNOWN_HOSTS_VALUE="$(resolve_secret_value "$DEPLOY_SSH_KNOWN_HOSTS_VALUE")"
fi

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"
printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY_VALUE" > "$SSH_KEY_FILE"
chmod 600 "$SSH_KEY_FILE"

if [[ -n "$DEPLOY_SSH_KNOWN_HOSTS_VALUE" ]]; then
  printf '%s\n' "$DEPLOY_SSH_KNOWN_HOSTS_VALUE" > "$SSH_DIR/known_hosts"
else
  ssh-keyscan -p "$DEPLOY_PORT" -H "$DEPLOY_HOST" > "$SSH_DIR/known_hosts"
fi
chmod 600 "$SSH_DIR/known_hosts"

SSH_OPTS=(
  -i "$SSH_KEY_FILE"
  -p "$DEPLOY_PORT"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
)

REMOTE_TARGET="$DEPLOY_USER@$DEPLOY_HOST"

ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "mkdir -p '$DEPLOY_PATH'"

rsync -az --delete \
  --exclude '.git/' \
  --exclude '.gitlab-ci.yml' \
  --exclude '.venv/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'telegram/opencode_sessions.json' \
  --exclude 'telegram/.semana_actual_state.json' \
  ./ "$REMOTE_TARGET:$DEPLOY_PATH/"

if [[ -n "$DEPLOY_POST_SYNC_COMMAND" ]]; then
  ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "cd '$DEPLOY_PATH' && $DEPLOY_POST_SYNC_COMMAND"
fi

ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "cd '$DEPLOY_PATH' && $DEPLOY_RESTART_COMMAND"
