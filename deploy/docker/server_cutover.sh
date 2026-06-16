#!/usr/bin/env bash
#
# One-time cutover of the live file-based deployment to the dockerized SQL stack.
# Run ONCE on the server (root@192.168.2.81) from /opt/personal-trainer after the
# docker-branch code is in place.
#
#   ssh root@192.168.2.81
#   cd /opt/personal-trainer
#   bash deploy/docker/server_cutover.sh
#
# Idempotent where practical. Re-running after success just refreshes the stack.

set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/personal-trainer}"
cd "$DEPLOY_PATH"

PROJECT="$(basename "$DEPLOY_PATH")"           # compose project name -> volume prefix
GARMIN_VOLUME="${PROJECT}_garmin-token-store"
OPENCODE_VOLUME="${PROJECT}_opencode-home"
HOST_GARMIN_TOKENS="${HOST_GARMIN_TOKENS:-/root/.garminconnect}"
HOST_OPENCODE_BIN="${HOST_OPENCODE_BIN:-/home/abel/.opencode/bin/opencode}"

log() { printf '\n=== %s ===\n' "$*"; }

# ---------------------------------------------------------------------------
log "Pre-flight checks"
command -v docker >/dev/null || { echo "Docker no instalado en el servidor." >&2; exit 1; }
docker compose version >/dev/null || { echo "docker compose no disponible." >&2; exit 1; }
if [[ ! -f .env ]]; then
  echo "Falta $DEPLOY_PATH/.env. Copia .env.example, rellena POSTGRES_PASSWORD," >&2
  echo "DATABASE_URL, secretos de Garmin/Telegram/OpenAI/Gemini y vuelve a ejecutar." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
log "Stopping the old file-based services (systemd + nohup)"
# systemd units (ignore those that do not exist)
for unit in opencode-telegram-bot opencode-web opencode-server post-workout-refresh \
            running-coach-automation.timer weekly-planning-pipeline.timer \
            running-coach-morning-brief.timer; do
  systemctl stop "$unit" 2>/dev/null || true
  systemctl disable "$unit" 2>/dev/null || true
done
# nohup-based launcher, if it was used
if [[ -x ./start_server.sh ]]; then
  ./start_server.sh stop 2>/dev/null || true
fi
# Make sure nothing still holds the Telegram getUpdates long-poll or port 8090.
pkill -f 'scripts/telegram/opencode_bot.py' 2>/dev/null || true
pkill -f 'uvicorn scripts.web_v2.app:app' 2>/dev/null || true
pkill -f 'post_workout_refresh_daemon.py' 2>/dev/null || true

# ---------------------------------------------------------------------------
log "Seeding the Garmin token volume from $HOST_GARMIN_TOKENS"
if [[ -f "$HOST_GARMIN_TOKENS/garmin_tokens.json" || -f "$HOST_GARMIN_TOKENS/oauth1_token.json" ]]; then
  docker volume create "$GARMIN_VOLUME" >/dev/null
  docker run --rm -v "$GARMIN_VOLUME:/tokens" -v "$HOST_GARMIN_TOKENS:/seed:ro" alpine \
    sh -c 'cp -a /seed/. /tokens/ && chown -R 1000:1000 /tokens && chmod -R go-rwx /tokens' \
    && echo "Garmin tokens copiados al volumen."
else
  echo "AVISO: no se encontraron tokens en $HOST_GARMIN_TOKENS." >&2
  echo "       El contenedor pedira MFA en el primer sync de Garmin." >&2
fi

# ---------------------------------------------------------------------------
log "Seeding the OpenCode binary volume from $HOST_OPENCODE_BIN"
if [[ -x "$HOST_OPENCODE_BIN" ]]; then
  docker volume create "$OPENCODE_VOLUME" >/dev/null
  docker run --rm -v "$OPENCODE_VOLUME:/home/app/.opencode" -v "$(dirname "$HOST_OPENCODE_BIN"):/seed:ro" alpine \
    sh -c 'mkdir -p /home/app/.opencode/bin && cp /seed/opencode /home/app/.opencode/bin/opencode && chmod 755 /home/app/.opencode/bin/opencode && chown -R 1000:1000 /home/app/.opencode' \
    && echo "Binario opencode sembrado en el volumen."
else
  echo "AVISO: no hay binario opencode en $HOST_OPENCODE_BIN." >&2
  echo "       El servicio opencode intentara descargarlo de opencode.ai en runtime." >&2
fi

# ---------------------------------------------------------------------------
log "Building images"
docker compose build

log "Importing the live file data into PostgreSQL (one-shot migrate)"
docker compose up -d db
docker compose run --rm migrate   # --apply --validate --prune (from compose command)

log "Starting the full stack"
docker compose up -d --remove-orphans

# ---------------------------------------------------------------------------
log "Post-cutover status"
docker compose ps
echo "Health check:"
sleep 5
curl -fsS "http://127.0.0.1:${RUNNING_WEB_PORT:-8090}/healthz" && echo " -> web OK" || echo " -> web no responde aun, revisa logs."

cat <<'NOTE'

Cutover done. Verifica:
  docker compose logs --tail=120 web
  docker compose logs --tail=120 telegram
  docker compose logs --tail=120 opencode
  docker compose logs --tail=120 garmin

Si todo va bien, deja el reverse proxy apuntando a 127.0.0.1:8090 como hasta ahora.
La reconciliacion archivo->DB corre cada 5 min en el servicio `reconcile`.
NOTE
