#!/usr/bin/env bash
set -euo pipefail

# Git-based deploy for the trading bot.
# - Commits and pushes local changes
# - Pulls on remote server via git
# - Restarts bot with bot.sh
# - Does NOT transfer bulk files (rsync/scp prohibited)

SERVER_HOST=${SERVER_HOST:-"chsvr.duckdns.org"}
SERVER_USER=${SERVER_USER:-"deploy"}
SERVER_DIR=${SERVER_DIR:-"/home/deploy/bitcoin-trading-bot"}
BRANCH=${BRANCH:-"main"}
MODE=${MODE:-"paper"}

TAIL_LOGS=1
SKIP_PUSH=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--no-logs] [--skip-push] [--mode paper|live]

Git-based deployment (rsync/scp prohibited):
  1. Push local commits to origin
  2. Pull on remote server
  3. Restart bot with bot.sh

Options:
  --no-logs    Skip tailing logs after deploy
  --skip-push  Skip git push (assume remote is up-to-date)
  --mode       Bot mode: paper (default) or live

Environment overrides:
  SERVER_HOST  (default: chsvr.duckdns.org)
  SERVER_USER  (default: deploy)
  SERVER_DIR   (default: ~/bitcoin-trading-bot)
  BRANCH       (default: main)

Examples:
  $(basename "$0")
  $(basename "$0") --mode live
  $(basename "$0") --skip-push --no-logs
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-logs)
      TAIL_LOGS=0
      shift
      ;;
    --skip-push)
      SKIP_PUSH=1
      shift
      ;;
    --mode)
      MODE="$2"
      shift 2
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

echo "[3/4] Pulling and restarting on server…"
ssh "${SERVER_USER}@${SERVER_HOST}" \
  "SERVER_DIR='${SERVER_DIR}' BRANCH='${BRANCH}' MODE='${MODE}'" \
  'bash -s' <<'REMOTE'
set -euo pipefail

cd "${SERVER_DIR}"

echo "--- git pull ---"
git fetch origin
git reset --hard "origin/${BRANCH}"

echo "--- .env check ---"
if [[ -f .env ]]; then
  echo ".env exists"
else
  echo "WARN: .env not found in ${SERVER_DIR}"
  echo "Please create .env with required secrets"
fi

echo "--- pip install (if requirements changed) ---"
source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && source .venv/bin/activate
pip install -q -r requirements.txt

echo "--- restarting bot (mode: ${MODE}) ---"
./bot.sh stop 2>/dev/null || true
sleep 2
./bot.sh start "${MODE}"
./bot.sh status
REMOTE

if [[ $TAIL_LOGS -eq 1 ]]; then
  echo "[4/4] Tailing logs…"
  ssh "${SERVER_USER}@${SERVER_HOST}" "cd ${SERVER_DIR} && ./bot.sh logs"
else
  echo "[4/4] Done. (logs skipped)"
fi
