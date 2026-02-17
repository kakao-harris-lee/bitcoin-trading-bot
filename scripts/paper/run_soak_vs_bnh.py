#!/usr/bin/env python3
"""Run/Analyze paper soak interval and compare against Buy & Hold."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import redis


BULL_REGIMES = {"BULL_STRONG", "BULL_MODERATE"}
BEARISH_OR_SIDEWAYS = {
    "BEAR_STRONG",
    "BEAR_MODERATE",
    "SIDEWAYS_UP",
    "SIDEWAYS_FLAT",
    "SIDEWAYS_DOWN",
}


@dataclass
class SymbolSoakStats:
    symbol: str
    first_price: float
    last_price: float
    bnh_return_pct: float
    stream_points: int
    trade_count: int
    realized_pnl: float


@dataclass
class DecisionRecord:
    symbol: str
    timestamp_iso: str
    ts_ms: int
    price: float
    regime: str
    decision: str
    reason: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run/Analyze paper soak and compare with BnH")
    p.add_argument("--duration", type=int, default=900, help="Soak duration in seconds (run mode)")
    p.add_argument("--no-run", action="store_true", help="Skip launching run.py and analyze lookback window")
    p.add_argument("--lookback-seconds", type=int, default=21600, help="Window size for --no-run mode")
    p.add_argument("--baseline-equity", type=float, default=10000.0, help="Baseline equity for no-run mode")
    p.add_argument("--blocked-horizon-minutes", type=int, default=120, help="Forward window for blocked-opportunity check")
    p.add_argument("--blocked-threshold-pct", type=float, default=0.5, help="Threshold for blocked-opportunity event")
    p.add_argument("--config", default="config/strategies/allocation.json")
    p.add_argument("--db", default="data/paper_trading_results.db")
    p.add_argument("--output-dir", default="logs/paper_soak")
    return p.parse_args()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(v: str | None, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _to_int(v: str | None, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def _sum_account_balance(account_hash: dict[str, str]) -> float:
    return _to_float(account_hash.get("spot_balance"))


def _next_stream_id(stream_id: str) -> str:
    ms, seq = stream_id.split("-", 1)
    return f"{ms}-{int(seq) + 1}"


def _collect_symbol_market_series(
    r: redis.Redis,
    symbols: list[str],
    start_ms: int,
    end_ms: int,
) -> dict[str, list[tuple[int, float]]]:
    """Collect per-symbol (timestamp_ms, price) from market:prices stream."""
    key = "market:prices"
    min_id = f"{start_ms}-0"
    max_id = f"{end_ms}-999999"

    wanted = set(symbols)
    series: dict[str, list[tuple[int, float]]] = {s: [] for s in symbols}

    cursor = min_id
    while True:
        batch = r.xrange(key, min=cursor, max=max_id, count=2000)
        if not batch:
            break

        for _, fields in batch:
            sym = fields.get("symbol", "")
            if sym not in wanted:
                continue
            if fields.get("market") != "spot":
                continue
            px = _to_float(fields.get("price"))
            ts = _to_int(fields.get("timestamp"))
            if px <= 0 or ts <= 0:
                continue
            # Exclude warmup/historical candles injected into stream outside the target interval.
            if ts < start_ms or ts > end_ms:
                continue
            series[sym].append((ts, px))

        if len(batch) < 2000:
            break
        cursor = _next_stream_id(batch[-1][0])

    for sym in symbols:
        series[sym].sort(key=lambda x: x[0])
    return series


def _summarize_symbol_price_series(series: dict[str, list[tuple[int, float]]]) -> dict[str, tuple[float, float, int]]:
    out: dict[str, tuple[float, float, int]] = {}
    for sym, points in series.items():
        if not points:
            out[sym] = (0.0, 0.0, 0)
            continue
        out[sym] = (points[0][1], points[-1][1], len(points))
    return out


def _query_trade_stats(
    db_path: Path,
    start_iso: str,
    end_iso: str,
) -> dict[str, tuple[int, float]]:
    out: dict[str, tuple[int, float]] = {}
    if not db_path.exists():
        return out

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute(
        """
        SELECT symbol, COUNT(*), COALESCE(SUM(COALESCE(profit, 0)), 0)
        FROM trades
        WHERE timestamp >= ? AND timestamp <= ?
        GROUP BY symbol
        """,
        (start_iso, end_iso),
    )
    for sym, cnt, pnl in cur.fetchall():
        out[str(sym)] = (int(cnt), float(pnl or 0.0))
    con.close()
    return out


def _query_decision_records(
    r: redis.Redis,
    start_iso: str,
    end_iso: str,
    symbols: list[str],
) -> dict[str, list[DecisionRecord]]:
    entries = r.xrevrange("strategy:decisions", count=50000)
    wanted = set(symbols)
    out: dict[str, list[DecisionRecord]] = {s: [] for s in symbols}
    for _, fields in entries:
        ts_iso = fields.get("timestamp", "")
        sym = fields.get("symbol", "")
        if sym not in wanted or not ts_iso:
            continue
        if not (start_iso <= ts_iso <= end_iso):
            continue
        ts_ms = _to_int(fields.get("timestamp_ms"))
        if ts_ms <= 0:
            try:
                ts_ms = int(datetime.fromisoformat(ts_iso).timestamp() * 1000)
            except Exception:
                ts_ms = 0
        out[sym].append(
            DecisionRecord(
                symbol=sym,
                timestamp_iso=ts_iso,
                ts_ms=ts_ms,
                price=_to_float(fields.get("price")),
                regime=fields.get("regime", ""),
                decision=fields.get("decision", ""),
                reason=fields.get("reason", ""),
            )
        )
    for sym in symbols:
        out[sym].sort(key=lambda d: d.ts_ms)
    return out


def _compute_regime_mix(records: list[DecisionRecord]) -> dict[str, Any]:
    regime_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for r in records:
        regime_counts[r.regime] = regime_counts.get(r.regime, 0) + 1
        decision_counts[r.decision] = decision_counts.get(r.decision, 0) + 1
    total = len(records)
    bear_sideways = sum(c for rg, c in regime_counts.items() if rg in BEARISH_OR_SIDEWAYS)
    bull = sum(c for rg, c in regime_counts.items() if rg in BULL_REGIMES)
    return {
        "total_decisions": total,
        "regime_counts": regime_counts,
        "decision_counts": decision_counts,
        "bear_sideways_ratio": (bear_sideways / total) if total else 0.0,
        "bull_ratio": (bull / total) if total else 0.0,
    }


def _max_forward_return_pct(series: list[tuple[int, float]], ts_ms: int, px: float, horizon_min: int) -> float:
    if px <= 0 or ts_ms <= 0 or not series:
        return 0.0
    end_ms = ts_ms + (horizon_min * 60 * 1000)
    max_px = px
    for p_ts, p_px in series:
        if p_ts <= ts_ms:
            continue
        if p_ts > end_ms:
            break
        if p_px > max_px:
            max_px = p_px
    return ((max_px / px) - 1.0) * 100.0 if max_px > 0 else 0.0


def _compute_blocked_opportunity(
    records: list[DecisionRecord],
    series: list[tuple[int, float]],
    horizon_min: int,
    threshold_pct: float,
) -> dict[str, Any]:
    blocked_candidates = [r for r in records if r.decision == "WAIT" and r.reason.lower().startswith("no entry")]
    if not blocked_candidates:
        return {
            "candidates": 0,
            "events": 0,
            "event_ratio": 0.0,
            "avg_forward_max_pct": 0.0,
            "max_forward_max_pct": 0.0,
        }

    forward_vals: list[float] = [
        _max_forward_return_pct(series, r.ts_ms, r.price, horizon_min)
        for r in blocked_candidates
    ]
    events = sum(1 for v in forward_vals if v >= threshold_pct)
    return {
        "candidates": len(blocked_candidates),
        "events": events,
        "event_ratio": (events / len(blocked_candidates)) if blocked_candidates else 0.0,
        "avg_forward_max_pct": (sum(forward_vals) / len(forward_vals)) if forward_vals else 0.0,
        "max_forward_max_pct": max(forward_vals) if forward_vals else 0.0,
    }


def _compute_transition_metrics(records: list[DecisionRecord]) -> dict[str, Any]:
    transitions = 0
    captured = 0
    lag_steps: list[int] = []

    for i in range(1, len(records)):
        prev = records[i - 1]
        cur = records[i]
        if prev.regime in BEARISH_OR_SIDEWAYS and cur.regime in BULL_REGIMES:
            transitions += 1
            lag = None
            for j in range(i, len(records)):
                if records[j].decision == "BUY":
                    lag = j - i
                    break
            if lag is not None:
                captured += 1
                lag_steps.append(lag)

    return {
        "transitions": transitions,
        "captured": captured,
        "capture_ratio": (captured / transitions) if transitions else 0.0,
        "avg_capture_lag_steps": (sum(lag_steps) / len(lag_steps)) if lag_steps else None,
    }


def _compute_shadow_bull_follow(records: list[DecisionRecord]) -> dict[str, Any]:
    """Simple shadow strategy on decision candles.

    Entry: first decision in bull regime when flat.
    Exit: first decision outside bull regime.
    """
    in_pos = False
    entry_px = 0.0
    entry_ts = ""
    trades: list[dict[str, Any]] = []

    for r in records:
        is_bull = r.regime in BULL_REGIMES
        if not in_pos and is_bull and r.price > 0:
            in_pos = True
            entry_px = r.price
            entry_ts = r.timestamp_iso
            continue

        if in_pos and (not is_bull) and r.price > 0:
            ret_pct = ((r.price / entry_px) - 1.0) * 100.0 if entry_px > 0 else 0.0
            trades.append(
                {
                    "entry_ts": entry_ts,
                    "exit_ts": r.timestamp_iso,
                    "entry_px": entry_px,
                    "exit_px": r.price,
                    "ret_pct": ret_pct,
                }
            )
            in_pos = False
            entry_px = 0.0
            entry_ts = ""

    if in_pos and records and entry_px > 0 and records[-1].price > 0:
        ret_pct = ((records[-1].price / entry_px) - 1.0) * 100.0
        trades.append(
            {
                "entry_ts": entry_ts,
                "exit_ts": records[-1].timestamp_iso,
                "entry_px": entry_px,
                "exit_px": records[-1].price,
                "ret_pct": ret_pct,
            }
        )

    compounded = 1.0
    for t in trades:
        compounded *= 1.0 + (t["ret_pct"] / 100.0)
    total_ret_pct = (compounded - 1.0) * 100.0

    return {
        "trade_count": len(trades),
        "total_return_pct": total_ret_pct,
        "trades": trades,
    }


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[2]
    cfg_path = project_root / args.config
    db_path = project_root / args.db
    out_dir = project_root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = _load_json(cfg_path)
    symbols = list(cfg.get("symbols", ["BTC", "ETH", "SOL", "BNB"]))

    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.ping()

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / f"paper_soak_{run_tag}.log"
    csv_path = out_dir / f"paper_soak_vs_bnh_{run_tag}.csv"
    md_path = out_dir / f"paper_soak_vs_bnh_{run_tag}.md"
    json_path = out_dir / f"paper_soak_vs_bnh_{run_tag}.json"

    account_before = r.hgetall("account:paper")
    balance_before_snapshot = _sum_account_balance(account_before)

    if args.no_run:
        end_dt = datetime.now()
        start_dt = end_dt.fromtimestamp(end_dt.timestamp() - args.lookback_seconds)
        rc = 0
    else:
        start_dt = datetime.now()
        cmd = ["timeout", str(args.duration), "python", "run.py", "--trend", "paper"]
        with log_path.open("w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, cwd=str(project_root), stdout=f, stderr=subprocess.STDOUT, check=False).returncode
        end_dt = datetime.now()

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    start_iso = start_dt.isoformat(timespec="seconds")
    end_iso = end_dt.isoformat(timespec="seconds")

    account_after = r.hgetall("account:paper")
    balance_after_snapshot = _sum_account_balance(account_after)

    market_series = _collect_symbol_market_series(r, symbols, start_ms, end_ms)
    price_map = _summarize_symbol_price_series(market_series)

    trade_stats = _query_trade_stats(db_path, start_iso, end_iso)
    decision_records = _query_decision_records(r, start_iso, end_iso, symbols)
    decision_counts = {s: len(decision_records.get(s, [])) for s in symbols}

    rows: list[SymbolSoakStats] = []
    for symbol in symbols:
        first_price, last_price, point_count = price_map.get(symbol, (0.0, 0.0, 0))
        bnh_ret = ((last_price / first_price) - 1.0) * 100.0 if first_price > 0 and last_price > 0 else 0.0
        trade_count, realized_pnl = trade_stats.get(symbol, (0, 0.0))
        rows.append(
            SymbolSoakStats(
                symbol=symbol,
                first_price=first_price,
                last_price=last_price,
                bnh_return_pct=bnh_ret,
                stream_points=point_count,
                trade_count=trade_count,
                realized_pnl=realized_pnl,
            )
        )

    duration_s = int((end_dt - start_dt).total_seconds())
    total_realized_pnl = sum(rw.realized_pnl for rw in rows)

    if args.no_run:
        balance_before = float(args.baseline_equity)
        balance_after = balance_before + total_realized_pnl
        portfolio_note = "derived_from_realized_pnl"
    else:
        balance_before = balance_before_snapshot
        balance_after = balance_after_snapshot
        portfolio_note = "account_snapshot"

    portfolio_return_pct = ((balance_after / balance_before) - 1.0) * 100.0 if balance_before > 0 else 0.0

    regime_analysis: dict[str, Any] = {}
    blocked_analysis: dict[str, Any] = {}
    transition_analysis: dict[str, Any] = {}
    shadow_analysis: dict[str, Any] = {}

    for sym in symbols:
        recs = decision_records.get(sym, [])
        series = market_series.get(sym, [])
        regime_analysis[sym] = _compute_regime_mix(recs)
        blocked_analysis[sym] = _compute_blocked_opportunity(
            recs,
            series,
            horizon_min=args.blocked_horizon_minutes,
            threshold_pct=args.blocked_threshold_pct,
        )
        transition_analysis[sym] = _compute_transition_metrics(recs)
        shadow_analysis[sym] = _compute_shadow_bull_follow(recs)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "symbol",
                "first_price",
                "last_price",
                "bnh_return_pct",
                "stream_points",
                "trade_count",
                "realized_pnl",
                "decision_count",
                "bull_ratio",
                "bear_sideways_ratio",
                "blocked_candidates",
                "blocked_events",
                "blocked_event_ratio",
                "shadow_return_pct",
                "relative_vs_flat_pct",
            ]
        )
        for row in rows:
            rg = regime_analysis[row.symbol]
            bl = blocked_analysis[row.symbol]
            sh = shadow_analysis[row.symbol]
            writer.writerow(
                [
                    row.symbol,
                    f"{row.first_price:.6f}",
                    f"{row.last_price:.6f}",
                    f"{row.bnh_return_pct:.4f}",
                    row.stream_points,
                    row.trade_count,
                    f"{row.realized_pnl:.4f}",
                    decision_counts.get(row.symbol, 0),
                    f"{rg['bull_ratio']:.4f}",
                    f"{rg['bear_sideways_ratio']:.4f}",
                    bl["candidates"],
                    bl["events"],
                    f"{bl['event_ratio']:.4f}",
                    f"{sh['total_return_pct']:.4f}",
                    f"{-row.bnh_return_pct:.4f}",
                ]
            )

    lines = [
        "# Paper Soak vs BnH Report",
        "",
        f"- Mode: `{'no-run lookback' if args.no_run else 'run soak'}`",
        f"- Start: `{start_iso}`",
        f"- End: `{end_iso}`",
        f"- Duration (sec): `{duration_s}`",
        f"- Run exit code (timeout=expected 124 in run mode): `{rc}`",
        f"- Portfolio balance: `{balance_before:.2f} -> {balance_after:.2f}`",
        f"- Portfolio return (%): `{portfolio_return_pct:.4f}`",
        f"- Portfolio source: `{portfolio_note}`",
        f"- Blocked opportunity rule: `{args.blocked_horizon_minutes}m forward max >= {args.blocked_threshold_pct:.2f}%`",
        f"- CSV: `{csv_path.relative_to(project_root)}`",
    ]
    if args.no_run:
        lines.append("- Log: `n/a (existing running session analyzed)`")
    else:
        lines.append(f"- Soak log: `{log_path.relative_to(project_root)}`")

    lines.extend(
        [
            "",
            "## Symbol Comparison",
            "",
            "| Symbol | BnH % | Trades | Realized PnL | Decisions | Bull Ratio | Bear/Sideways Ratio | Blocked Event Ratio | Shadow Bull-Follow % |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        rg = regime_analysis[row.symbol]
        bl = blocked_analysis[row.symbol]
        sh = shadow_analysis[row.symbol]
        lines.append(
            f"| {row.symbol} | {row.bnh_return_pct:.4f} | {row.trade_count} | {row.realized_pnl:.4f} | {decision_counts.get(row.symbol, 0)} | {rg['bull_ratio']:.2f} | {rg['bear_sideways_ratio']:.2f} | {bl['event_ratio']:.2f} | {sh['total_return_pct']:.4f} |"
        )

    lines.extend(["", "## Regime-Conditional Validation", ""])
    for sym in symbols:
        rg = regime_analysis[sym]
        tr = transition_analysis[sym]
        lines.append(
            f"- `{sym}`: decisions={rg['total_decisions']}, bull_ratio={rg['bull_ratio']:.2f}, "
            f"bear_sideways_ratio={rg['bear_sideways_ratio']:.2f}, transitions(B/S->BULL)={tr['transitions']}, "
            f"capture_ratio={tr['capture_ratio']:.2f}"
        )

    lines.extend(["", "## Blocked Opportunity", ""])
    for sym in symbols:
        bl = blocked_analysis[sym]
        lines.append(
            f"- `{sym}`: candidates={bl['candidates']}, events={bl['events']}, event_ratio={bl['event_ratio']:.2f}, "
            f"avg_forward_max={bl['avg_forward_max_pct']:.4f}%"
        )

    lines.extend(["", "## Problem Areas (vs flat/no-trade baseline)", "", "- 기준: 구간 내 trade가 없으면 전략 수익률을 0%로 보고 BnH 대비 상대열위를 표시."])
    for row in sorted(rows, key=lambda x: x.bnh_return_pct):
        if row.bnh_return_pct > 0:
            lines.append(f"- `{row.symbol}`: BnH `+{row.bnh_return_pct:.4f}%` while strategy stayed mostly flat.")
        elif row.bnh_return_pct < 0:
            lines.append(f"- `{row.symbol}`: BnH `{row.bnh_return_pct:.4f}%`; flat strategy avoided drawdown.")
        else:
            lines.append(f"- `{row.symbol}`: BnH near flat (`{row.bnh_return_pct:.4f}%`).")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "mode": "no_run" if args.no_run else "run",
        "start": start_iso,
        "end": end_iso,
        "duration_seconds": duration_s,
        "exit_code": rc,
        "portfolio": {
            "balance_before": balance_before,
            "balance_after": balance_after,
            "return_pct": portfolio_return_pct,
            "source": portfolio_note,
        },
        "symbols": [
            {
                "symbol": row.symbol,
                "first_price": row.first_price,
                "last_price": row.last_price,
                "bnh_return_pct": row.bnh_return_pct,
                "stream_points": row.stream_points,
                "trade_count": row.trade_count,
                "realized_pnl": row.realized_pnl,
                "decision_count": decision_counts.get(row.symbol, 0),
                "regime_validation": regime_analysis[row.symbol],
                "blocked_opportunity": blocked_analysis[row.symbol],
                "transition_metrics": transition_analysis[row.symbol],
                "shadow_bull_follow": shadow_analysis[row.symbol],
            }
            for row in rows
        ],
        "artifacts": {
            "csv": str(csv_path.relative_to(project_root)),
            "md": str(md_path.relative_to(project_root)),
            "log": None if args.no_run else str(log_path.relative_to(project_root)),
        },
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not args.no_run:
        print(f"Wrote: {log_path.relative_to(project_root)}")
    print(f"Wrote: {csv_path.relative_to(project_root)}")
    print(f"Wrote: {md_path.relative_to(project_root)}")
    print(f"Wrote: {json_path.relative_to(project_root)}")
    print(f"Portfolio return: {portfolio_return_pct:.4f}% ({portfolio_note})")
    for row in rows:
        bl = blocked_analysis[row.symbol]
        tr = transition_analysis[row.symbol]
        print(
            f"{row.symbol}: BnH={row.bnh_return_pct:.4f}% trades={row.trade_count} pnl={row.realized_pnl:.4f} "
            f"decisions={decision_counts.get(row.symbol, 0)} blocked={bl['event_ratio']:.2f} transitions={tr['transitions']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
