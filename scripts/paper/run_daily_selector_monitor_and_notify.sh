#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs/paper_soak"
RUN_TS="$(date '+%Y%m%d_%H%M%S')"
RUN_LOG="${LOG_DIR}/cron_selector_monitor_${RUN_TS}.log"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

LOOKBACK_DAYS="${LOOKBACK_DAYS:-7}"
LOOKBACK_HOURS="${LOOKBACK_HOURS:-0}"
STRATEGY_NAME="${STRATEGY_NAME:-mlp_direction_bnb}"
ENTRY_WINDOW_MINUTES="${ENTRY_WINDOW_MINUTES:-240}"

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

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') selector monitor cron started"
if [[ "${LOOKBACK_HOURS}" =~ ^[0-9]+$ ]] && (( LOOKBACK_HOURS > 0 )); then
  LOOKBACK_ARGS=(--lookback-hours "${LOOKBACK_HOURS}")
  LOOKBACK_LABEL="${LOOKBACK_HOURS}h"
else
  LOOKBACK_ARGS=(--lookback-days "${LOOKBACK_DAYS}")
  LOOKBACK_LABEL="${LOOKBACK_DAYS}d"
fi
echo "[INFO] lookback=${LOOKBACK_LABEL} strategy=${STRATEGY_NAME} entry_window_minutes=${ENTRY_WINDOW_MINUTES}"

STATUS="SUCCESS"
ERROR_STEP=""

if ! "${PYTHON_BIN}" scripts/paper/selector_signal_monitor_7d.py \
  "${LOOKBACK_ARGS[@]}" \
  --strategy "${STRATEGY_NAME}" \
  --entry-window-minutes "${ENTRY_WINDOW_MINUTES}" \
  --report-dir logs/paper_soak; then
  STATUS="FAILED"
  ERROR_STEP="selector_signal_monitor_7d"
fi

LATEST_SUMMARY_JSON="$(ls -1t "${LOG_DIR}"/selector_monitor_7d_*_summary.json 2>/dev/null | head -n 1 || true)"
export LATEST_SUMMARY_JSON

TELEGRAM_MESSAGE="$("${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path

root = Path(".")
summary_env = os.getenv("LATEST_SUMMARY_JSON", "").strip()
summary_path = Path(summary_env).resolve() if summary_env else None
if summary_path is None or (not summary_path.exists()) or summary_path.is_dir():
    candidates = sorted((root / "logs" / "paper_soak").glob("selector_monitor_7d_*_summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    summary_path = candidates[0].resolve() if candidates else None

if summary_path is None or not summary_path.exists() or summary_path.is_dir():
    print("[Selector Monitor] no summary json found.")
    raise SystemExit(0)

payload = json.loads(summary_path.read_text(encoding="utf-8"))
criteria = payload.get("criteria", [])
passed = sum(1 for c in criteria if c.get("ok"))
total = len(criteria)
entry = (payload.get("conversion") or {}).get("ENTRY_READY", {})
cand = (payload.get("conversion") or {}).get("NEW_CANDIDATE", {})

def pct(v):
    return f"{float(v)*100:.2f}%"

lines = ["[Selector Monitor] 7D KPI"]
lines.append(f"- window: {payload.get('lookback_label', '-')}")
lines.append(f"- strategy: {payload.get('strategy', '-')}")
lines.append(f"- selector_events: {int(payload.get('selector_events', 0))}")
lines.append(f"- events_per_day: {float(payload.get('events_per_day', 0.0)):.2f}")
lines.append(
    f"- entry_ready_conv: {int(entry.get('converted', 0))}/{int(entry.get('total', 0))} ({pct(entry.get('conversion_ratio', 0.0))})"
)
lines.append(
    f"- new_candidate_conv: {int(cand.get('converted', 0))}/{int(cand.get('total', 0))} ({pct(cand.get('conversion_ratio', 0.0))})"
)
lines.append(f"- avg_dq_blocked_ratio: {pct(payload.get('avg_dq_blocked_ratio', 0.0))}")
lines.append(f"- stale_reject_ratio: {pct(payload.get('stale_reject_ratio', 0.0))}")
lines.append(f"- criteria_pass: {passed}/{total}")
try:
    rel = summary_path.relative_to(root.resolve())
except Exception:
    rel = summary_path
lines.append(f"- report: {rel}")
print("\n".join(lines))
PY
)" || TELEGRAM_MESSAGE="[Selector Monitor] summary parse failed."

if [[ "${STATUS}" == "FAILED" ]]; then
  TELEGRAM_MESSAGE=$'[Selector Monitor] FAILED at '"${ERROR_STEP}"$'\n'"${TELEGRAM_MESSAGE}"$'\n- log: '"${RUN_LOG}"
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

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') selector monitor cron finished: ${STATUS}"

if [[ "${STATUS}" == "FAILED" ]]; then
  exit 1
fi
exit 0
