#!/usr/bin/env bash
set -euo pipefail

# SCP-based deploy for the LIVE docker-compose service.
# - Does NOT overwrite server .env by default (secrets stay on server)
# - Excludes large local artifacts (DB/logs/.git)

SERVER_HOST=${SERVER_HOST:-"49.247.171.64"}
SERVER_USER=${SERVER_USER:-"deploy"}
SERVER_DIR=${SERVER_DIR:-"/home/deploy/bitcoin-trading-bot"}
SERVICES=${SERVICES:-"paper-trading dashboard"}
SERVICE_MAIN=${SERVICE_MAIN:-"paper-trading"}
DASHBOARD_PORT=${DASHBOARD_PORT:-"8081"}

NO_CACHE=0
TAIL_LOGS=1

usage() {
  cat <<EOF
Usage: $(basename "$0") [--no-cache] [--no-logs]

Environment overrides:
  SERVER_HOST (default: 49.247.171.64)
  SERVER_USER (default: deploy)
  SERVER_DIR  (default: ~/bitcoin-trading-bot)
  SERVICES    (default: "paper-trading dashboard")
  SERVICE_MAIN (default: paper-trading)
  DASHBOARD_PORT (optional: host port for dashboard, e.g. 8081)

Examples:
  $(basename "$0")
  $(basename "$0") --no-cache
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-cache)
      NO_CACHE=1
      shift
      ;;
    --no-logs)
      TAIL_LOGS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP_TGZ=$(mktemp -t bitcoin-trading-bot_deploy.XXXXXX.tgz)

cleanup() {
  rm -f "$TMP_TGZ"
}
trap cleanup EXIT

echo "[1/4] Packaging repo (excluding .env, DB, logs)…"
(
  cd "$REPO_ROOT"
  tar -czf "$TMP_TGZ" \
    --exclude ".git" \
    --exclude ".DS_Store" \
    --exclude "__pycache__" \
    --exclude "**/__pycache__" \
    --exclude ".pytest_cache" \
    --exclude "**/.pytest_cache" \
    --exclude "*.pyc" \
    --exclude "*.tgz" \
    --exclude ".env" \
    --exclude "logs" \
    --exclude "upbit_bitcoin.db" \
    --exclude "trading_results.db" \
    .
)

echo "[2/4] Uploading archive via scp…"
scp "$TMP_TGZ" "${SERVER_USER}@${SERVER_HOST}:bitcoin-trading-bot_deploy.tgz"

echo "[3/4] Extracting + rebuilding + restarting on server…"
ssh "${SERVER_USER}@${SERVER_HOST}" \
  "SERVER_DIR='${SERVER_DIR}' SERVICES='${SERVICES}' SERVICE_MAIN='${SERVICE_MAIN}' NO_CACHE='${NO_CACHE}' DASHBOARD_PORT='${DASHBOARD_PORT}'" \
  'bash -s' <<'REMOTE'
set -euo pipefail

cd "${SERVER_DIR}"

# Extract repo overlay (archive is placed in remote HOME)
if [[ -f "$HOME/bitcoin-trading-bot_deploy.tgz" ]]; then
  tar -xzf "$HOME/bitcoin-trading-bot_deploy.tgz" -C "${SERVER_DIR}"
  rm -f "$HOME/bitcoin-trading-bot_deploy.tgz"
else
  echo "ERROR: deploy archive not found at $HOME/bitcoin-trading-bot_deploy.tgz" >&2
  exit 1
fi

echo "--- .env TELEGRAM keys (masked) ---"
if [[ -f .env ]]; then
  awk -F= '
    /^TELEGRAM_BOT_TOKEN=/ { v=$2; sub(/\r$/, "", v); printf("TELEGRAM_BOT_TOKEN=%s... (len=%d)\n", substr(v,1,8), length(v)); }
    /^TELEGRAM_CHAT_ID=/  { v=$2; sub(/\r$/, "", v); printf("TELEGRAM_CHAT_ID=%s (len=%d)\n", v, length(v)); }
  ' .env || true
else
  echo "WARN: .env not found in ${SERVER_DIR}"
fi

echo "--- port 8080 usage (docker) ---"
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -E '(^|\s)0\.0\.0\.0:8080->|(^|\s)\[::\]:8080->' || true

if [[ "${NO_CACHE}" -eq 1 ]]; then
  # shellcheck disable=SC2086
  docker compose build --no-cache ${SERVICES}
else
  # shellcheck disable=SC2086
  docker compose build ${SERVICES}
fi

# shellcheck disable=SC2086
docker compose up -d ${SERVICES}

echo "--- container env check (token not printed) ---"
docker compose exec -T "${SERVICE_MAIN}" python - <<'PY'
import os
print('TELEGRAM_BOT_TOKEN set:', bool(os.getenv('TELEGRAM_BOT_TOKEN')))
chat = os.getenv('TELEGRAM_CHAT_ID', '')
print('TELEGRAM_CHAT_ID set:', bool(chat), 'value:', chat)
PY
REMOTE

if [[ $TAIL_LOGS -eq 1 ]]; then
  echo "[4/4] Tailing logs…"
  ssh "${SERVER_USER}@${SERVER_HOST}" "cd ${SERVER_DIR} && docker compose logs --tail=200 -f ${SERVICES}"
else
  echo "[4/4] Done. (logs skipped)"
fi
