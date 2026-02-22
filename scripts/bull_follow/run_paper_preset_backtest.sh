#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DATA_DIR_DEFAULT="/home/deploy/project/bitcoin-trading-bot/data/universe_backtest_4h"
DATA_DIR="${DATA_DIR:-$DATA_DIR_DEFAULT}"

python "$ROOT_DIR/scripts/bull_follow/run_altcoin_research_backtest.py" \
  --data-dir "$DATA_DIR" \
  --config "$ROOT_DIR/config/strategies/allocation.json" \
  --strategy-id mlp_direction_bnb \
  --timeframe minute240 \
  --start-date 2020-01-01 \
  --end-date 2026-02-22 \
  --train-end-date 2024-12-31 \
  --paper-preset \
  "$@"
