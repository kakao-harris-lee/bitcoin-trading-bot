#!/usr/bin/env python3
"""CLI for paper trading readiness validation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.core.paper_readiness import (
    evaluate_paper_readiness,
    format_paper_readiness_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check paper-trading readiness for live mode.")
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to allocation config.",
    )
    parser.add_argument(
        "--trades-log",
        default="logs/trades.jsonl",
        help="Path to structured trades log JSONL.",
    )
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--min-exits-per-strategy", type=int, default=10)
    parser.add_argument("--min-total-exits", type=int, default=40)
    parser.add_argument("--min-win-rate-pct", type=float, default=45.0)
    parser.add_argument("--min-profit-factor", type=float, default=1.0)
    parser.add_argument(
        "--allow-negative-pnl",
        action="store_true",
        help="Do not require positive total P&L for readiness.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = evaluate_paper_readiness(
        config_path=args.config,
        trades_log_path=args.trades_log,
        lookback_days=args.lookback_days,
        min_exits_per_strategy=args.min_exits_per_strategy,
        min_total_exits=args.min_total_exits,
        min_win_rate_pct=args.min_win_rate_pct,
        min_profit_factor=args.min_profit_factor,
        require_positive_pnl=not args.allow_negative_pnl,
    )
    print(format_paper_readiness_report(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
