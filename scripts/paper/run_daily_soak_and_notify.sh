#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs/paper_soak"
RUN_TS="$(date '+%Y%m%d_%H%M%S')"
RUN_LOG="${LOG_DIR}/cron_daily_${RUN_TS}.log"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

mkdir -p "${LOG_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python || true)"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "python interpreter not found" | tee -a "${RUN_LOG}"
  exit 1
fi

cd "${ROOT_DIR}"
exec >> "${RUN_LOG}" 2>&1

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') daily soak cron started"

STATUS="SUCCESS"
ERROR_STEP=""

if ! "${PYTHON_BIN}" scripts/paper/collect_daily_mlp_soak_metrics.py --lookback-hours 24; then
  STATUS="FAILED"
  ERROR_STEP="collect_daily_mlp_soak_metrics"
fi

if [[ "${STATUS}" == "SUCCESS" ]]; then
  if ! "${PYTHON_BIN}" scripts/paper/run_soak_vs_bnh.py --no-run --lookback-seconds 86400 --output-dir logs/paper_soak; then
    STATUS="FAILED"
    ERROR_STEP="run_soak_vs_bnh"
  fi
fi

REPORT_JSON="$(ls -1t "${LOG_DIR}"/paper_soak_vs_bnh_*.json 2>/dev/null | head -n 1 || true)"

TELEGRAM_MESSAGE="$("${PYTHON_BIN}" - <<'PY'
import csv
import glob
import os
from pathlib import Path

root = Path(".")
history_csv = root / "logs" / "paper_soak" / "mlp_daily_metrics.csv"

rows = []
if history_csv.exists():
    with history_csv.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

if not rows:
    print("Daily Soak: no metric rows found.")
    raise SystemExit(0)

run_ts = rows[-1].get("run_ts", "")
daily = [r for r in rows if r.get("run_ts", "") == run_ts]

lines = ["[Daily Soak] 24h Summary"]
if run_ts:
    lines.append(f"- run_ts: {run_ts}")

for r in daily:
    symbol = r.get("symbol", "")
    up_alpha = float(r.get("up_market_alpha_pct", 0) or 0)
    early = float(r.get("early_exit_rate_pct", 0) or 0)
    alpha = float(r.get("alpha_pct", 0) or 0)
    decisions = int(float(r.get("decision_count", 0) or 0))
    lines.append(
        f"- {symbol}: up_alpha={up_alpha:+.3f}%p, early_exit={early:.1f}%, alpha={alpha:+.3f}%p, decisions={decisions}"
    )

print("\n".join(lines))
PY
)"

if [[ "${STATUS}" == "FAILED" ]]; then
  TELEGRAM_MESSAGE=$'[Daily Soak] FAILED at '"${ERROR_STEP}"$'\n'"${TELEGRAM_MESSAGE}"$'\n- log: '"${RUN_LOG}"
else
  TELEGRAM_MESSAGE="${TELEGRAM_MESSAGE}"$'\n- log: '"${RUN_LOG}"
fi

export CRON_TELEGRAM_MESSAGE="${TELEGRAM_MESSAGE}"

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
msg = os.getenv("CRON_TELEGRAM_MESSAGE", "")

if not token or not chat_id or not msg:
    raise SystemExit(0)

url = f"https://api.telegram.org/bot{token}/sendMessage"
try:
    requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
except Exception as e:
    # Keep token-safe logging: never print URL/token.
    print(f"[WARN] telegram send failed: {type(e).__name__}: {e}")
PY

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') daily soak cron finished: ${STATUS}"

if [[ "${STATUS}" == "FAILED" ]]; then
  exit 1
fi
exit 0
