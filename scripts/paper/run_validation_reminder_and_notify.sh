#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs/paper_soak"
RUN_TS="$(date '+%Y%m%d_%H%M%S')"
RUN_LOG="${LOG_DIR}/cron_validation_reminder_${RUN_TS}.log"
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

echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') validation reminder started"
"${PYTHON_BIN}" scripts/paper/send_validation_reminder.py "$@"
RC=$?
echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S %Z') validation reminder finished rc=${RC}"
exit ${RC}
