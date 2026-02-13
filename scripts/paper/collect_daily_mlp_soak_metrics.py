#!/usr/bin/env python3
"""Collect daily MLP soak KPIs from live Redis streams.

This script is intended for rolling paper-soak monitoring where historical DB
coverage may not include the latest day.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import redis


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FOUR_HOURS_MS = 4 * 60 * 60 * 1000


@dataclass
class DecisionPoint:
    ts_ms: int
    decision: str
    price: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect rolling daily MLP soak metrics (up_market_alpha/early_exit)."
    )
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--config", default="config/strategies/allocation.json")
    parser.add_argument("--history-csv", default="logs/paper_soak/mlp_daily_metrics.csv")
    return parser.parse_args()


def _load_symbols(config_path: Path) -> list[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols", ["BTC", "ETH", "SOL", "BNB"])
    return [str(s).upper() for s in symbols]


def _to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _to_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except Exception:
        return default


def _collect_market_series(
    r: redis.Redis,
    symbols: list[str],
    start_ms: int,
    end_ms: int,
) -> dict[str, list[tuple[int, float]]]:
    out: dict[str, list[tuple[int, float]]] = {s: [] for s in symbols}
    wanted = set(symbols)
    entries = r.xrange("market:prices", min=f"{start_ms}-0", max=f"{end_ms}-999999", count=200000)
    for _msg_id, data in entries:
        symbol = str(data.get("symbol", "")).upper()
        if symbol not in wanted:
            continue
        ts_ms = _to_int(data.get("timestamp"))
        price = _to_float(data.get("price"))
        if ts_ms <= 0 or price <= 0:
            continue
        if ts_ms < start_ms or ts_ms > end_ms:
            continue
        out[symbol].append((ts_ms, price))
    for symbol in symbols:
        out[symbol].sort(key=lambda x: x[0])
    return out


def _collect_decisions(
    r: redis.Redis,
    symbols: list[str],
    start_ms: int,
    end_ms: int,
    paper_mode: bool = True,
) -> dict[str, list[DecisionPoint]]:
    out: dict[str, list[DecisionPoint]] = {s: [] for s in symbols}
    wanted = set(symbols)
    entries = r.xrevrange("strategy:decisions", count=100000)
    for _msg_id, data in entries:
        symbol = str(data.get("symbol", "")).upper()
        if symbol not in wanted:
            continue
        entry_is_paper = str(data.get("paper", "true")).lower() == "true"
        if entry_is_paper != paper_mode:
            continue

        ts_ms = _to_int(data.get("timestamp_ms"))
        if ts_ms <= 0:
            try:
                ts_ms = int(datetime.fromisoformat(str(data.get("timestamp", ""))).timestamp() * 1000)
            except Exception:
                ts_ms = 0
        if ts_ms <= 0 or ts_ms < start_ms or ts_ms > end_ms:
            continue

        decision = str(data.get("decision", "")).upper()
        price = _to_float(data.get("price"))
        out[symbol].append(DecisionPoint(ts_ms=ts_ms, decision=decision, price=price))

    for symbol in symbols:
        out[symbol].sort(key=lambda d: d.ts_ms)
    return out


def _simulate_decision_strategy(
    decisions: list[DecisionPoint],
    fallback_last_price: float,
) -> tuple[float, int, float]:
    """Return (strategy_return_pct, trade_count, early_exit_rate_pct)."""
    in_pos = False
    entry_price = 0.0
    entry_ts = 0
    returns: list[float] = []
    early_count = 0
    closed_count = 0

    for point in decisions:
        if point.price <= 0:
            continue

        if point.decision == "BUY" and not in_pos:
            in_pos = True
            entry_price = point.price
            entry_ts = point.ts_ms
            continue

        if point.decision == "SELL" and in_pos and entry_price > 0:
            ret = (point.price / entry_price) - 1.0
            returns.append(ret)
            closed_count += 1
            hold_bars = (point.ts_ms - entry_ts) / FOUR_HOURS_MS
            if hold_bars <= 2.0:
                early_count += 1
            in_pos = False
            entry_price = 0.0
            entry_ts = 0

    if in_pos and entry_price > 0 and fallback_last_price > 0:
        returns.append((fallback_last_price / entry_price) - 1.0)
        closed_count += 1
        hold_bars = (FOUR_HOURS_MS if entry_ts <= 0 else (decisions[-1].ts_ms - entry_ts) / FOUR_HOURS_MS)
        if hold_bars <= 2.0:
            early_count += 1

    compounded = 1.0
    for ret in returns:
        compounded *= 1.0 + ret
    strategy_return_pct = (compounded - 1.0) * 100.0
    early_exit_rate_pct = (early_count / closed_count) * 100.0 if closed_count > 0 else 0.0
    return strategy_return_pct, closed_count, early_exit_rate_pct


def _append_history(
    csv_path: Path,
    rows: list[dict[str, str | int | float]],
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "run_ts",
                "lookback_hours",
                "symbol",
                "bnh_return_pct",
                "strategy_return_pct",
                "alpha_pct",
                "up_market_alpha_pct",
                "up_market_capture_ratio",
                "trade_count",
                "early_exit_rate_pct",
                "decision_count",
                "metric_source",
            ],
        )
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    now = datetime.now()
    start = now - timedelta(hours=args.lookback_hours)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    config_path = PROJECT_ROOT / args.config
    symbols = _load_symbols(config_path)

    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.ping()

    risk = r.hgetall("risk") or {}
    paper_mode = str(risk.get("mode", "paper")) == "paper"

    market_series = _collect_market_series(r, symbols, start_ms, end_ms)
    decisions = _collect_decisions(r, symbols, start_ms, end_ms, paper_mode=paper_mode)

    run_ts = now.isoformat(timespec="seconds")
    out_rows: list[dict[str, str | int | float]] = []
    for symbol in symbols:
        series = market_series.get(symbol, [])
        first_price = series[0][1] if series else 0.0
        last_price = series[-1][1] if series else 0.0
        bnh_return_pct = (((last_price / first_price) - 1.0) * 100.0) if first_price > 0 and last_price > 0 else 0.0

        strategy_return_pct, trade_count, early_exit_rate_pct = _simulate_decision_strategy(
            decisions.get(symbol, []),
            fallback_last_price=last_price,
        )
        alpha_pct = strategy_return_pct - bnh_return_pct
        up_market_alpha_pct = alpha_pct if bnh_return_pct > 0 else 0.0
        up_market_capture_ratio = (strategy_return_pct / bnh_return_pct) if bnh_return_pct > 0 else 0.0

        out_rows.append(
            {
                "run_ts": run_ts,
                "lookback_hours": args.lookback_hours,
                "symbol": symbol,
                "bnh_return_pct": round(bnh_return_pct, 6),
                "strategy_return_pct": round(strategy_return_pct, 6),
                "alpha_pct": round(alpha_pct, 6),
                "up_market_alpha_pct": round(up_market_alpha_pct, 6),
                "up_market_capture_ratio": round(up_market_capture_ratio, 6),
                "trade_count": trade_count,
                "early_exit_rate_pct": round(early_exit_rate_pct, 6),
                "decision_count": len(decisions.get(symbol, [])),
                "metric_source": "decision_shadow",
            }
        )

    history_csv = PROJECT_ROOT / args.history_csv
    _append_history(history_csv, out_rows)

    print(f"Updated: {history_csv.relative_to(PROJECT_ROOT)}")
    for row in out_rows:
        print(
            f"{row['symbol']}: up_market_alpha_pct={row['up_market_alpha_pct']:+.4f}, "
            f"early_exit_rate_pct={row['early_exit_rate_pct']:.2f}, "
            f"alpha_pct={row['alpha_pct']:+.4f}, decisions={row['decision_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
