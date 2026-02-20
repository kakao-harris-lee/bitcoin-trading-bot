#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs/paper_soak"
RUN_TS="$(date '+%Y%m%d_%H%M%S')"
RUN_LOG="${LOG_DIR}/cron_aggressive_${RUN_TS}.log"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

LOOKBACK_HOURS="${LOOKBACK_HOURS:-1}"
LOOKBACK_SECONDS=$((LOOKBACK_HOURS * 3600))

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

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') aggressive soak cron started"
echo "[INFO] lookback_hours=${LOOKBACK_HOURS} lookback_seconds=${LOOKBACK_SECONDS}"

STATUS="SUCCESS"
ERROR_STEP=""

if ! "${PYTHON_BIN}" scripts/paper/collect_daily_mlp_soak_metrics.py --lookback-hours "${LOOKBACK_HOURS}"; then
  STATUS="FAILED"
  ERROR_STEP="collect_daily_mlp_soak_metrics"
fi

if [[ "${STATUS}" == "SUCCESS" ]]; then
  if ! "${PYTHON_BIN}" scripts/paper/run_soak_vs_bnh.py --no-run --lookback-seconds "${LOOKBACK_SECONDS}" --blocked-horizon-minutes 60 --blocked-threshold-pct 0.3 --output-dir logs/paper_soak; then
    STATUS="FAILED"
    ERROR_STEP="run_soak_vs_bnh"
  fi
fi

TELEGRAM_MESSAGE="$("${PYTHON_BIN}" - <<'PY'
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

root = Path(".")
lookback_hours = int(os.getenv("LOOKBACK_HOURS", "1"))
cutoff = datetime.now() - timedelta(hours=lookback_hours)

json_files = sorted((root / "logs" / "paper_soak").glob("paper_soak_vs_bnh_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
latest = json_files[0] if json_files else None

lines = [f"[Aggressive Soak] {lookback_hours}h Summary"]
if latest:
    payload = json.loads(latest.read_text(encoding="utf-8"))
    symbols = payload.get("symbols", [])
    lines.append(f"- report: {latest.relative_to(root)}")
    lines.append(f"- portfolio_return: {payload.get('portfolio', {}).get('return_pct', 0.0):+.4f}%")

    top_trades = sorted(symbols, key=lambda s: int(s.get("trade_count", 0)), reverse=True)[:5]
    trade_frag = ", ".join(f"{s.get('symbol')}:{int(s.get('trade_count', 0))}" for s in top_trades if int(s.get("trade_count", 0)) > 0)
    lines.append(f"- top_trade_count: {trade_frag if trade_frag else 'none'}")

    blocked = sorted(
        symbols,
        key=lambda s: float((s.get("blocked_opportunity") or {}).get("event_ratio", 0.0)),
        reverse=True,
    )[:3]
    blocked_frag = ", ".join(
        f"{s.get('symbol')}:{float((s.get('blocked_opportunity') or {}).get('event_ratio', 0.0)):.2f}"
        for s in blocked
    )
    lines.append(f"- top_blocked_ratio: {blocked_frag if blocked_frag else 'none'}")
else:
    lines.append("- report: none")

err_count = 0
warn_count = 0
log_file = root / "logs" / "bot.log"
if log_file.exists():
    for raw in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if len(raw) < 23:
            continue
        prefix = raw[:23]
        try:
            ts = datetime.strptime(prefix, "%Y-%m-%d %H:%M:%S,%f")
        except ValueError:
            continue
        if ts < cutoff:
            continue
        if " [ERROR] " in raw:
            err_count += 1
        elif " [WARNING] " in raw:
            warn_count += 1

lines.append(f"- log_errors_{lookback_hours}h: {err_count}")
lines.append(f"- log_warnings_{lookback_hours}h: {warn_count}")
print("\n".join(lines))
PY
)"

if [[ "${STATUS}" == "FAILED" ]]; then
  TELEGRAM_MESSAGE=$'[Aggressive Soak] FAILED at '"${ERROR_STEP}"$'\n'"${TELEGRAM_MESSAGE}"$'\n- log: '"${RUN_LOG}"
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
    print(f"[WARN] telegram send failed: {type(e).__name__}: {e}")
PY

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') aggressive soak cron finished: ${STATUS}"

if [[ "${STATUS}" == "FAILED" ]]; then
  exit 1
fi
exit 0
