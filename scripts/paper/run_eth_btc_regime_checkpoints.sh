#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs/paper_soak"
RUN_TS="$(date '+%Y%m%d_%H%M%S')"
RUN_LOG="${LOG_DIR}/cron_eth_btc_regime_checkpoints_${RUN_TS}.log"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

LOOKBACK_DAYS="${LOOKBACK_DAYS:-7}"
PATCH_TS="${PATCH_TS:-2026-04-23T10:08:29}"
FOCUS_EXIT_TS="${FOCUS_EXIT_TS:-2026-04-23T09:16:49}"
OUTPUT_PATH="${LOG_DIR}/eth_btc_regime_checkpoints_${RUN_TS}.md"

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

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') eth/btc regime checkpoints started"
echo "[INFO] lookback_days=${LOOKBACK_DAYS} patch_ts=${PATCH_TS} focus_exit_ts=${FOCUS_EXIT_TS}"

if ! "${PYTHON_BIN}" scripts/paper/report_eth_btc_regime_checkpoints.py \
  --lookback-days "${LOOKBACK_DAYS}" \
  --patch-ts "${PATCH_TS}" \
  --focus-exit-ts "${FOCUS_EXIT_TS}" \
  --output "${OUTPUT_PATH}"; then
  echo "[ERROR] report_eth_btc_regime_checkpoints failed"
  exit 1
fi

echo "[INFO] report=${OUTPUT_PATH}"
echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') eth/btc regime checkpoints finished"
exit 0
