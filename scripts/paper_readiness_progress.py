#!/usr/bin/env python3
"""Show paper readiness progress based on structured trade logs."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.core.paper_readiness import evaluate_paper_readiness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track paper readiness progress (EXIT counts and gaps)."
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Allocation config path.",
    )
    parser.add_argument(
        "--trades-log",
        default="logs/trades.runtime.jsonl",
        help="Structured trades jsonl path.",
    )
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--min-exits-per-strategy", type=int, default=10)
    parser.add_argument("--min-total-exits", type=int, default=40)
    parser.add_argument("--min-win-rate-pct", type=float, default=45.0)
    parser.add_argument("--min-profit-factor", type=float, default=1.0)
    parser.add_argument("--allow-negative-pnl", action="store_true")
    parser.add_argument(
        "--watch-seconds",
        type=int,
        default=0,
        help="Refresh every N seconds; 0 runs once.",
    )
    return parser.parse_args()


def _last_event_time(path: Path) -> str:
    if not path.exists():
        return "n/a"
    last_ts = ""
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = evt.get("ts")
            if isinstance(ts, str) and ts:
                last_ts = ts
    return last_ts or "n/a"


def _print_progress(args: argparse.Namespace) -> None:
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

    log_path = Path(args.trades_log)
    missing_total = max(0, args.min_total_exits - report.total_exits)

    print("=" * 72)
    print(f"Now: {datetime.now().isoformat(timespec='seconds')}")
    print(f"Window: {report.window_start.isoformat()} -> {report.window_end.isoformat()}")
    print(f"Trades log: {args.trades_log} (last event ts: {_last_event_time(log_path)})")
    print(
        f"Totals: exits={report.total_exits} (need {args.min_total_exits}, missing {missing_total}) | "
        f"win_rate={report.win_rate:.2f}% | pnl={report.total_pnl:.2f} | pf={report.profit_factor:.2f}"
    )
    print("Per-strategy gaps:")
    for name in report.enabled_strategies:
        m = report.metrics.get(name)
        exits = m.exits if m is not None else 0
        missing = max(0, args.min_exits_per_strategy - exits)
        print(
            f"  - {name}: exits={exits} (need {args.min_exits_per_strategy}, missing {missing}), "
            f"win_rate={m.win_rate if m else 0.0:.2f}%, pnl={m.pnl if m else 0.0:.2f}, "
            f"pf={m.profit_factor if m else 0.0:.2f}"
        )
    if report.warnings:
        print("Warnings:")
        for w in report.warnings:
            print(f"  - {w}")
    print(f"Ready: {'YES' if report.ready else 'NO'}")


def main() -> int:
    args = parse_args()
    if args.watch_seconds <= 0:
        _print_progress(args)
        return 0

    while True:
        _print_progress(args)
        time.sleep(args.watch_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
