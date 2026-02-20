#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs/paper_soak"
LOG_FILE="${LOG_DIR}/paper_bot_guard.log"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

mkdir -p "${LOG_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python || true)"
fi

cd "${ROOT_DIR}"

now="$(date '+%Y-%m-%d %H:%M:%S %Z')"

is_running_ps() {
  # Match only real trading-bot python invocations, not shell commands containing text snippets.
  ps -eo args= | awk '
    $0 ~ /python/ &&
    $0 ~ /run\.py[[:space:]]+--trend(=|[[:space:]])paper([[:space:]]|$)/ {
      found=1
      exit
    }
    END { exit(found ? 0 : 1) }
  '
}

is_running() {
  if ./bot.sh status >/dev/null 2>&1; then
    return 0
  fi
  if is_running_ps; then
    return 0
  fi
  return 1
}

if is_running; then
  echo "[${now}] status=running (healthy)" >> "${LOG_FILE}"
  exit 0
fi

echo "[${now}] status=down (first_check)" >> "${LOG_FILE}"

# Avoid false restart during short startup windows (PID rewrite / log rotation).
sleep 15
if is_running; then
  echo "[${now}] status=running (recovered_before_restart)" >> "${LOG_FILE}"
  exit 0
fi

echo "[${now}] status=down -> restarting paper bot" >> "${LOG_FILE}"
START_OUT="$(./bot.sh start --trend=paper 2>&1 || true)"
echo "${START_OUT}" >> "${LOG_FILE}"

if is_running; then
  STATUS="RECOVERED"
  MSG="[Paper Guard] bot restarted successfully at ${now}"
else
  STATUS="FAILED"
  MSG="[Paper Guard] restart failed at ${now}"
fi

export GUARD_TELEGRAM_MESSAGE="${MSG}"
export GUARD_TELEGRAM_STATUS="${STATUS}"

"${PYTHON_BIN}" - <<'PY'
import os
import requests
from pathlib import Path

def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

load_env(Path(".env"))
token = os.getenv("TELEGRAM_BOT_TOKEN", "")
chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
msg = os.getenv("GUARD_TELEGRAM_MESSAGE", "")
status = os.getenv("GUARD_TELEGRAM_STATUS", "UNKNOWN")

if not token or not chat_id or not msg:
    raise SystemExit(0)

if status == "RECOVERED":
    body = msg + "\n- action: ./bot.sh start --trend=paper"
else:
    body = msg + "\n- check: logs/bot.log\n- check: logs/paper_soak/paper_bot_guard.log"

url = f"https://api.telegram.org/bot{token}/sendMessage"
try:
    requests.post(url, json={"chat_id": chat_id, "text": body}, timeout=10)
except Exception:
    pass
PY

if [[ "${STATUS}" == "FAILED" ]]; then
  exit 1
fi
exit 0
