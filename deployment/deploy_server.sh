#!/usr/bin/env bash
set -euo pipefail

# Git-based deploy for the LIVE docker-compose service.
# - Commits and pushes local changes
# - Pulls on remote server via git
# - Does NOT transfer bulk files (rsync/scp prohibited)

SERVER_HOST=${SERVER_HOST:-"chsvr.duckdns.org"}
SERVER_USER=${SERVER_USER:-"deploy"}
SERVER_DIR=${SERVER_DIR:-"/home/deploy/bitcoin-trading-bot"}
SERVICES=${SERVICES:-"paper-trading dashboard"}
SERVICE_MAIN=${SERVICE_MAIN:-"paper-trading"}
DASHBOARD_PORT=${DASHBOARD_PORT:-"8081"}
BRANCH=${BRANCH:-"main"}

NO_CACHE=0
TAIL_LOGS=1
SKIP_PUSH=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--no-cache] [--no-logs] [--skip-push]

Git-based deployment (rsync/scp prohibited):
  1. Push local commits to origin
  2. Pull on remote server
  3. Rebuild and restart Docker services

Options:
  --no-cache   Build Docker images without cache
  --no-logs    Skip tailing logs after deploy
  --skip-push  Skip git push (assume remote is up-to-date)

Environment overrides:
  SERVER_HOST  (default: chsvr.duckdns.org)
  SERVER_USER  (default: deploy)
  SERVER_DIR   (default: ~/bitcoin-trading-bot)
  SERVICES     (default: "paper-trading dashboard")
  SERVICE_MAIN (default: paper-trading)
  BRANCH       (default: main)

Examples:
  $(basename "$0")
  $(basename "$0") --no-cache
  $(basename "$0") --skip-push
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
    --skip-push)
      SKIP_PUSH=1
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
cd "$REPO_ROOT"

echo "[1/4] Checking local git status…"
if [[ -n $(git status --porcelain) ]]; then
  echo "WARNING: Uncommitted changes detected:"
  git status --short
  echo ""
  read -p "Continue without committing? (y/N) " -n 1 -r
  echo ""
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted. Please commit your changes first."
    exit 1
  fi
fi

if [[ $SKIP_PUSH -eq 0 ]]; then
  echo "[2/4] Pushing to origin/${BRANCH}…"
  git push origin "${BRANCH}"
else
  echo "[2/4] Skipping git push (--skip-push)"
fi

echo "[3/4] Pulling and rebuilding on server…"
ssh "${SERVER_USER}@${SERVER_HOST}" \
  "SERVER_DIR='${SERVER_DIR}' SERVICES='${SERVICES}' SERVICE_MAIN='${SERVICE_MAIN}' NO_CACHE='${NO_CACHE}' DASHBOARD_PORT='${DASHBOARD_PORT}' BRANCH='${BRANCH}'" \
  'bash -s' <<'REMOTE'
set -euo pipefail

cd "${SERVER_DIR}"

echo "--- git pull ---"
git fetch origin
git reset --hard "origin/${BRANCH}"

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
