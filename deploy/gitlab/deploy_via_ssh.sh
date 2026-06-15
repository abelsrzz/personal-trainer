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
REMOTE_PRESERVE_DIR="$DEPLOY_PATH/.deploy-preserve"

preserve_remote_operational_changes() {
  ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "DEPLOY_PATH='$DEPLOY_PATH' REMOTE_PRESERVE_DIR='$REMOTE_PRESERVE_DIR' python3 - <<'PY'
from __future__ import annotations

import json
import subprocess
import tarfile
from pathlib import Path

deploy_path = Path(__import__('os').environ['DEPLOY_PATH'])
preserve_dir = Path(__import__('os').environ['REMOTE_PRESERVE_DIR'])
roots = ['athlete', 'planning', 'races', 'training', 'system/state']

if not deploy_path.exists():
    raise SystemExit(0)

preserve_dir.mkdir(parents=True, exist_ok=True)
status = subprocess.run(
    ['git', 'status', '--porcelain=v1', '--untracked-files=all', '--', *roots],
    cwd=deploy_path,
    check=False,
    capture_output=True,
    text=True,
)

files: list[str] = []
deleted: list[str] = []
for raw_line in status.stdout.splitlines():
    line = raw_line.rstrip('\n')
    if not line:
        continue
    code = line[:2]
    rel = line[3:]
    if ' -> ' in rel:
        rel = rel.split(' -> ', 1)[1]
    target = deploy_path / rel
    if 'D' in code:
        deleted.append(rel)
    elif target.exists():
        files.append(rel)

files = sorted(set(files))
deleted = sorted(set(deleted))
(preserve_dir / 'files.json').write_text(json.dumps(files, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
(preserve_dir / 'deleted.json').write_text(json.dumps(deleted, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')

with tarfile.open(preserve_dir / 'files.tar', 'w') as tar:
    for rel in files:
        tar.add(deploy_path / rel, arcname=rel)

print(json.dumps({'preserved_files': len(files), 'preserved_deleted': len(deleted)}, ensure_ascii=True))
PY"
}

restore_remote_operational_changes() {
  ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "DEPLOY_PATH='$DEPLOY_PATH' REMOTE_PRESERVE_DIR='$REMOTE_PRESERVE_DIR' python3 - <<'PY'
from __future__ import annotations

import json
import shutil
import tarfile
from pathlib import Path

deploy_path = Path(__import__('os').environ['DEPLOY_PATH'])
preserve_dir = Path(__import__('os').environ['REMOTE_PRESERVE_DIR'])
files_tar = preserve_dir / 'files.tar'
deleted_json = preserve_dir / 'deleted.json'

if files_tar.exists():
    with tarfile.open(files_tar, 'r') as tar:
        tar.extractall(deploy_path)

if deleted_json.exists():
    deleted = json.loads(deleted_json.read_text(encoding='utf-8'))
    for rel in deleted:
        target = deploy_path / rel
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)

shutil.rmtree(preserve_dir, ignore_errors=True)
print(json.dumps({'restored': True}, ensure_ascii=True))
PY"
}

ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "mkdir -p '$DEPLOY_PATH'"

preserve_remote_operational_changes

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

restore_remote_operational_changes

if [[ -n "$DEPLOY_POST_SYNC_COMMAND" ]]; then
  ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "cd '$DEPLOY_PATH' && $DEPLOY_POST_SYNC_COMMAND"
fi

ssh "${SSH_OPTS[@]}" "$REMOTE_TARGET" "cd '$DEPLOY_PATH' && $DEPLOY_RESTART_COMMAND"
