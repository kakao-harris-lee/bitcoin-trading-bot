#!/usr/bin/env python3
"""Refresh BNB-sleeve symbol routing using recent forward/live metrics and 4h universe backtests."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest.backtest_mlp import MLPDirectionBacktester, load_strategy_config


@dataclass
class TradeSummary:
    trades: int = 0
    realized_pnl: float = 0.0
    risk_exit_count: int = 0
    fallback_entry_count: int = 0
    avg_hold_sec_sum: float = 0.0


@dataclass
class ForwardSummary:
    days: int = 0
    avg_alpha_pct_sum: float = 0.0
    avg_up_alpha_pct_sum: float = 0.0
    avg_capture_ratio_sum: float = 0.0
    avg_early_exit_rate_pct_sum: float = 0.0
    trade_count: int = 0
    decision_count: int = 0


@dataclass
class SoakSummary:
    days: int = 0
    realized_pnl: float = 0.0
    shadow_trade_count: int = 0
    shadow_return_pct: float = 0.0
    transition_total: int = 0
    transition_captured: int = 0


@dataclass
class BacktestSummary:
    strategy_return_pct: float = 0.0
    bnh_return_pct: float = 0.0
    alpha_vs_bh_pct: float = 0.0
    mdd_pct: float = 0.0
    sharpe: float = 0.0
    trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    candles: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh BNB symbol routing recommendations.")
    parser.add_argument("--config", default="config/strategies/allocation.json")
    parser.add_argument("--strategy-id", default="mlp_direction_bnb")
    parser.add_argument("--live-lookback-days", type=int, default=30)
    parser.add_argument("--backtest-days", type=int, default=90)
    parser.add_argument("--as-of-date", default=datetime.now().date().isoformat())
    parser.add_argument("--output-dir", default="logs/paper_soak")
    parser.add_argument("--skip-backtest", action="store_true")
    parser.add_argument("--symbols", nargs="*", default=None)
    return parser.parse_args()


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _avg(values: list[float]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _classify_entry(reason: str) -> str:
    text = (reason or "").lower()
    if "regime_fallback" in text:
        return "regime_fallback"
    if "hybridlong[mlp]" in text or "mlpdirection" in text:
        return "mlp"
    if "selector" in text:
        return "selector"
    return "other"


def _classify_exit(reason: str) -> str:
    text = (reason or "").lower()
    if "below ema_120" in text:
        return "regime_ema120"
    if "peak drawdown" in text:
        return "regime_drawdown"
    if "stop loss intrabar" in text:
        return "stop_loss_intrabar"
    if "mlpdirection exit: stop loss" in text or text.startswith("stop loss"):
        return "stop_loss"
    if "trailing stop" in text:
        return "trailing_stop"
    if "bear_regime_exit" in text:
        return "bear_regime_exit"
    if "deadcross" in text:
        return "ema_deadcross"
    return "other"


def _is_risk_exit(category: str) -> bool:
    return category in {
        "regime_ema120",
        "regime_drawdown",
        "stop_loss_intrabar",
        "stop_loss",
        "bear_regime_exit",
        "ema_deadcross",
    }


def _load_config(config_path: Path, strategy_id: str) -> tuple[list[str], dict[str, Any]]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    strategy = payload["strategies"][strategy_id]
    universe = [str(symbol).upper() for symbol in strategy.get("symbols", [])]
    return universe, strategy


def _aggregate_trade_metrics(
    trade_path: Path,
    *,
    start: datetime,
    symbols: set[str],
    strategy_id: str,
) -> dict[str, dict[str, float]]:
    reason_map: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    events: list[dict[str, Any]] = []
    with trade_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            ts = _dt(obj["ts"])
            if ts < start:
                continue
            if str(obj.get("strategy", "")) != strategy_id:
                continue
            symbol = str(obj.get("symbol", "")).upper()
            if symbol not in symbols:
                continue
            obj["_ts"] = ts
            events.append(obj)
            if obj.get("event") in {"SIGNAL", "DECISION"} and obj.get("reason"):
                reason_map[(ts.isoformat(), symbol, strategy_id)].append(str(obj["reason"]))

    events.sort(key=lambda row: (row["_ts"], {"DECISION": 0, "SIGNAL": 1, "ENTRY": 2, "EXIT": 3}.get(row.get("event"), 9)))
    open_pos: dict[tuple[str, str], dict[str, Any]] = {}
    summaries: dict[str, TradeSummary] = defaultdict(TradeSummary)

    for event in events:
        key = (strategy_id, str(event.get("symbol", "")).upper())
        if event.get("event") == "ENTRY":
            reasons = reason_map.get((event["_ts"].isoformat(), key[1], strategy_id), [])
            entry_reason = next(
                (
                    reason
                    for reason in reasons
                    if "entry" in reason.lower() or "fallback" in reason.lower() or "buy" in reason.lower()
                ),
                reasons[0] if reasons else "",
            )
            open_pos[key] = {
                "entry_source": _classify_entry(entry_reason),
            }
        elif event.get("event") == "EXIT":
            current = open_pos.pop(key, {"entry_source": "unknown"})
            symbol = key[1]
            summary = summaries[symbol]
            summary.trades += 1
            summary.realized_pnl += float(event.get("pnl", 0.0) or 0.0)
            summary.avg_hold_sec_sum += float(event.get("hold_sec", 0.0) or 0.0)
            if current.get("entry_source") == "regime_fallback":
                summary.fallback_entry_count += 1
            if _is_risk_exit(_classify_exit(str(event.get("reason", "")))):
                summary.risk_exit_count += 1

    out: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        summary = summaries.get(symbol, TradeSummary())
        out[symbol] = {
            "live_trades": summary.trades,
            "live_realized_pnl": summary.realized_pnl,
            "live_risk_exit_share": (summary.risk_exit_count / summary.trades) if summary.trades else 0.0,
            "live_fallback_entry_share": (summary.fallback_entry_count / summary.trades) if summary.trades else 0.0,
            "live_avg_hold_hours": ((summary.avg_hold_sec_sum / summary.trades) / 3600.0) if summary.trades else 0.0,
        }
    return out


def _aggregate_forward_metrics(
    csv_path: Path,
    *,
    start: datetime,
    symbols: set[str],
) -> dict[str, dict[str, float]]:
    summaries: dict[str, ForwardSummary] = defaultdict(ForwardSummary)
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            run_ts = _dt(row["run_ts"])
            if run_ts < start:
                continue
            if row.get("lookback_hours") != "24":
                continue
            symbol = str(row.get("symbol", "")).upper()
            if symbol not in symbols:
                continue
            summary = summaries[symbol]
            summary.days += 1
            summary.avg_alpha_pct_sum += float(row.get("alpha_pct") or 0.0)
            summary.avg_up_alpha_pct_sum += float(row.get("up_market_alpha_pct") or 0.0)
            summary.avg_capture_ratio_sum += float(row.get("up_market_capture_ratio") or 0.0)
            summary.avg_early_exit_rate_pct_sum += float(row.get("early_exit_rate_pct") or 0.0)
            summary.trade_count += int(float(row.get("trade_count") or 0))
            summary.decision_count += int(float(row.get("decision_count") or 0))

    out: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        summary = summaries.get(symbol, ForwardSummary())
        out[symbol] = {
            "forward_days": summary.days,
            "forward_avg_alpha_pct": (summary.avg_alpha_pct_sum / summary.days) if summary.days else 0.0,
            "forward_avg_up_alpha_pct": (summary.avg_up_alpha_pct_sum / summary.days) if summary.days else 0.0,
            "forward_avg_capture_ratio": (summary.avg_capture_ratio_sum / summary.days) if summary.days else 0.0,
            "forward_avg_early_exit_rate_pct": (summary.avg_early_exit_rate_pct_sum / summary.days) if summary.days else 0.0,
            "forward_trade_count": summary.trade_count,
            "forward_decision_count": summary.decision_count,
        }
    return out


def _select_daily_soak_files(output_dir: Path, start: datetime, end: datetime) -> list[Path]:
    files = sorted(output_dir.glob("paper_soak_vs_bnh_*.json"))
    by_date: dict[str, tuple[datetime, Path]] = {}
    for path in files:
        parts = path.stem.split("_")
        if len(parts) < 5:
            continue
        stamp = datetime.strptime(parts[-2] + parts[-1], "%Y%m%d%H%M%S")
        if stamp < start or stamp > end:
            continue
        if stamp.hour != 9 or not (25 <= stamp.minute <= 35):
            continue
        date_key = stamp.date().isoformat()
        prev = by_date.get(date_key)
        if prev is None or stamp > prev[0]:
            by_date[date_key] = (stamp, path)
    return [item[1] for _, item in sorted(by_date.items())]


def _aggregate_soak_metrics(
    output_dir: Path,
    *,
    start: datetime,
    end: datetime,
    symbols: set[str],
) -> dict[str, dict[str, float]]:
    summaries: dict[str, SoakSummary] = defaultdict(SoakSummary)
    for path in _select_daily_soak_files(output_dir, start, end):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("symbols", []):
            symbol = str(row.get("symbol", "")).upper()
            if symbol not in symbols:
                continue
            summary = summaries[symbol]
            summary.days += 1
            summary.realized_pnl += float(row.get("realized_pnl") or 0.0)
            shadow = row.get("shadow_bull_follow") or {}
            summary.shadow_trade_count += int(shadow.get("trade_count") or 0)
            summary.shadow_return_pct += float(shadow.get("total_return_pct") or 0.0)
            transition = row.get("transition_metrics") or {}
            summary.transition_total += int(transition.get("transitions") or 0)
            summary.transition_captured += int(transition.get("captured") or 0)

    out: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        summary = summaries.get(symbol, SoakSummary())
        out[symbol] = {
            "soak_days": summary.days,
            "soak_realized_pnl": summary.realized_pnl,
            "soak_shadow_trade_count": summary.shadow_trade_count,
            "soak_shadow_return_pct": summary.shadow_return_pct,
            "soak_transition_capture_ratio": (
                summary.transition_captured / summary.transition_total
            ) if summary.transition_total else 0.0,
        }
    return out


def _run_backtests(
    *,
    symbols: list[str],
    config_path: str,
    strategy_id: str,
    backtest_days: int,
    requested_end_date: str,
) -> dict[str, BacktestSummary]:
    _, _, strategy_config = load_strategy_config(config_path, "BNB", "paper", strategy_id)
    out: dict[str, BacktestSummary] = {}
    requested_end = pd.Timestamp(requested_end_date)
    for symbol in symbols:
        csv_path = PROJECT_ROOT / "data" / "universe_backtest_4h" / f"{symbol.lower()}_minute240.csv"
        if not csv_path.exists():
            continue
        print(f"[backtest] {symbol} ...", flush=True)
        df = pd.read_csv(csv_path)
        if df.empty:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        effective_end = min(requested_end, df["timestamp"].max())
        effective_start = effective_end - pd.Timedelta(days=backtest_days)
        df = df[(df["timestamp"] >= effective_start) & (df["timestamp"] <= effective_end)].reset_index(drop=True)
        if len(df) < 120:
            continue
        buy_hold_return = ((float(df.iloc[-1]["close"]) / float(df.iloc[0]["close"])) - 1.0) * 100.0
        backtester = MLPDirectionBacktester(symbol=symbol, config=strategy_config, strategy_label=strategy_id)
        prepared = backtester.prepare_data(df)
        results = backtester.run(prepared, initial_capital=10_000)
        out[symbol] = BacktestSummary(
            strategy_return_pct=float(results.get("total_return", 0.0) or 0.0),
            bnh_return_pct=buy_hold_return,
            alpha_vs_bh_pct=float(results.get("total_return", 0.0) or 0.0) - buy_hold_return,
            mdd_pct=float(results.get("max_drawdown_pct", 0.0) or 0.0),
            sharpe=float(results.get("sharpe_ratio", 0.0) or 0.0),
            trades=int(results.get("total_trades", 0) or 0),
            win_rate_pct=float(results.get("win_rate", 0.0) or 0.0) * 100.0,
            profit_factor=float(results.get("profit_factor", 0.0) or 0.0),
            candles=len(df),
        )
    return out


def _score_row(row: dict[str, Any]) -> tuple[float, str, bool]:
    score = 0.0
    score += max(min(row.get("backtest_alpha_vs_bh_pct", 0.0) / 40.0, 1.0), -1.0) * 0.24
    score += max(min(row.get("forward_avg_alpha_pct", 0.0) / 0.5, 1.0), -1.0) * 0.18
    score += max(min(row.get("forward_avg_capture_ratio", 0.0), 1.0), -1.0) * 0.14
    score += math.tanh(row.get("live_realized_pnl", 0.0) / 25.0) * 0.16
    score += math.tanh(row.get("soak_shadow_return_pct", 0.0) / 12.0) * 0.12
    score += max(min(row.get("soak_transition_capture_ratio", 0.0), 1.0), 0.0) * 0.08
    score -= row.get("live_risk_exit_share", 0.0) * 0.22
    score -= row.get("live_fallback_entry_share", 0.0) * 0.10
    score -= (row.get("forward_avg_early_exit_rate_pct", 0.0) / 100.0) * 0.08

    severe_suppress = (
        row.get("live_trades", 0) >= 4
        and row.get("live_realized_pnl", 0.0) <= -15.0
        and row.get("live_risk_exit_share", 0.0) >= 0.75
        and row.get("live_fallback_entry_share", 0.0) >= 0.50
    )
    has_positive_signal = any(
        [
            row.get("backtest_alpha_vs_bh_pct", 0.0) > 0,
            row.get("forward_avg_alpha_pct", 0.0) > 0,
            row.get("soak_shadow_return_pct", 0.0) >= 6.0,
            row.get("soak_transition_capture_ratio", 0.0) >= 0.25,
        ]
    )
    if severe_suppress or score <= -0.18:
        recommendation = "suppress"
    elif score >= 0.20 and has_positive_signal:
        recommendation = "boost"
    elif score >= 0.05 and has_positive_signal:
        recommendation = "watch"
    else:
        recommendation = "neutral"
    return score, recommendation, severe_suppress


def _recommended_multiplier(score: float, recommendation: str, severe_suppress: bool) -> float:
    if severe_suppress:
        return 0.45
    if recommendation == "suppress":
        return 0.70 if score > -0.30 else 0.55
    if recommendation == "boost":
        return 1.10 if score < 0.32 else 1.22
    if recommendation == "watch":
        return 1.05
    return 1.0


def _build_rows(
    *,
    symbols: list[str],
    strategy: dict[str, Any],
    trade_metrics: dict[str, dict[str, float]],
    forward_metrics: dict[str, dict[str, float]],
    soak_metrics: dict[str, dict[str, float]],
    backtests: dict[str, BacktestSummary],
) -> list[dict[str, Any]]:
    current_multipliers = {
        str(symbol).upper(): float(value)
        for symbol, value in (strategy.get("symbol_selector", {}).get("symbol_score_multipliers") or {}).items()
    }
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        row: dict[str, Any] = {
            "symbol": symbol,
            "current_multiplier": current_multipliers.get(symbol, 1.0),
        }
        row.update(trade_metrics.get(symbol, {}))
        row.update(forward_metrics.get(symbol, {}))
        row.update(soak_metrics.get(symbol, {}))
        bt = backtests.get(symbol)
        if bt is not None:
            row.update(
                {
                    "backtest_strategy_return_pct": bt.strategy_return_pct,
                    "backtest_bnh_return_pct": bt.bnh_return_pct,
                    "backtest_alpha_vs_bh_pct": bt.alpha_vs_bh_pct,
                    "backtest_mdd_pct": bt.mdd_pct,
                    "backtest_sharpe": bt.sharpe,
                    "backtest_trades": bt.trades,
                    "backtest_win_rate_pct": bt.win_rate_pct,
                    "backtest_profit_factor": bt.profit_factor,
                    "backtest_candles": bt.candles,
                }
            )
        else:
            row.update(
                {
                    "backtest_strategy_return_pct": 0.0,
                    "backtest_bnh_return_pct": 0.0,
                    "backtest_alpha_vs_bh_pct": 0.0,
                    "backtest_mdd_pct": 0.0,
                    "backtest_sharpe": 0.0,
                    "backtest_trades": 0,
                    "backtest_win_rate_pct": 0.0,
                    "backtest_profit_factor": 0.0,
                    "backtest_candles": 0,
                }
            )
        score, recommendation, severe_suppress = _score_row(row)
        row["routing_score"] = score
        row["recommendation"] = recommendation
        row["severe_suppress"] = severe_suppress
        row["recommended_multiplier"] = _recommended_multiplier(score, recommendation, severe_suppress)
        rows.append(row)
    rows.sort(key=lambda item: (item["recommendation"], item["routing_score"]), reverse=True)
    return rows


def _write_outputs(
    *,
    rows: list[dict[str, Any]],
    output_dir: Path,
    as_of_date: str,
    live_lookback_days: int,
    backtest_days: int,
    strategy_id: str,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"bnb_symbol_routing_refresh_{as_of_date}.md"
    csv_path = output_dir / f"bnb_symbol_routing_refresh_{as_of_date}.csv"
    json_path = output_dir / f"bnb_symbol_routing_refresh_{as_of_date}.json"

    fieldnames = [
        "symbol",
        "recommendation",
        "routing_score",
        "recommended_multiplier",
        "current_multiplier",
        "live_trades",
        "live_realized_pnl",
        "live_risk_exit_share",
        "live_fallback_entry_share",
        "forward_avg_alpha_pct",
        "forward_avg_capture_ratio",
        "forward_avg_early_exit_rate_pct",
        "soak_shadow_return_pct",
        "soak_transition_capture_ratio",
        "backtest_strategy_return_pct",
        "backtest_bnh_return_pct",
        "backtest_alpha_vs_bh_pct",
        "backtest_sharpe",
        "backtest_trades",
        "backtest_profit_factor",
        "severe_suppress",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})

    severe_blocks = [
        row["symbol"]
        for row in rows
        if row["severe_suppress"]
        or (
            row["recommendation"] == "suppress"
            and (
                row.get("routing_score", 0.0) <= -0.35
                or (
                    row.get("live_trades", 0) >= 1
                    and row.get("live_realized_pnl", 0.0) < 0.0
                    and row.get("live_risk_exit_share", 0.0) >= 1.0
                )
            )
        )
    ]
    fallback_allow = [
        row["symbol"]
        for row in rows
        if row["recommendation"] in {"boost", "watch"}
        and (
            row.get("forward_avg_capture_ratio", 0.0) >= 0.20
            or row.get("soak_shadow_return_pct", 0.0) >= 5.0
            or row.get("live_realized_pnl", 0.0) > 0.0
        )
    ]
    multiplier_snippet = {
        row["symbol"]: row["recommended_multiplier"]
        for row in rows
        if abs(float(row["recommended_multiplier"]) - 1.0) >= 0.04
    }
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "strategy_id": strategy_id,
        "live_lookback_days": live_lookback_days,
        "backtest_days": backtest_days,
        "boost_symbols": [row["symbol"] for row in rows if row["recommendation"] == "boost"],
        "watch_symbols": [row["symbol"] for row in rows if row["recommendation"] == "watch"],
        "suppress_symbols": [row["symbol"] for row in rows if row["recommendation"] == "suppress"],
        "fallback_quality_allowlist_symbols": fallback_allow,
        "fallback_blocked_symbols": severe_blocks,
        "symbol_score_multipliers": multiplier_snippet,
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    top_boost = [row for row in rows if row["recommendation"] == "boost"][:12]
    top_suppress = [row for row in rows if row["recommendation"] == "suppress"][:12]
    top_watch = [row for row in rows if row["recommendation"] == "watch"][:12]

    def _table(table_rows: list[dict[str, Any]]) -> str:
        lines = [
            "| Symbol | Rec | Score | Mult | Live PnL | Risk Exit | Fallback | Fwd Alpha | Capture | Shadow | BT Alpha |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in table_rows:
            lines.append(
                "| {symbol} | {recommendation} | {score:.2f} | {mult:.2f} | {live_pnl:.2f} | {risk:.1%} | {fallback:.1%} | {alpha:.2f} | {capture:.2f} | {shadow:.2f} | {bt_alpha:.2f} |".format(
                    symbol=row["symbol"],
                    recommendation=row["recommendation"],
                    score=row["routing_score"],
                    mult=row["recommended_multiplier"],
                    live_pnl=row.get("live_realized_pnl", 0.0),
                    risk=row.get("live_risk_exit_share", 0.0),
                    fallback=row.get("live_fallback_entry_share", 0.0),
                    alpha=row.get("forward_avg_alpha_pct", 0.0),
                    capture=row.get("forward_avg_capture_ratio", 0.0),
                    shadow=row.get("soak_shadow_return_pct", 0.0),
                    bt_alpha=row.get("backtest_alpha_vs_bh_pct", 0.0),
                )
            )
        return "\n".join(lines)

    md_lines = [
        f"# BNB Symbol Routing Refresh ({as_of_date})",
        "",
        f"- Strategy: `{strategy_id}`",
        f"- Live/forward lookback: `{live_lookback_days}` days",
        f"- Backtest window: `{backtest_days}` days",
        f"- Recommended fallback allowlist: `{', '.join(fallback_allow) if fallback_allow else '-'}`",
        f"- Recommended fallback blocked symbols: `{', '.join(severe_blocks) if severe_blocks else '-'}`",
        "",
        "## Boost",
        _table(top_boost) if top_boost else "- None",
        "",
        "## Watch",
        _table(top_watch) if top_watch else "- None",
        "",
        "## Suppress",
        _table(top_suppress) if top_suppress else "- None",
        "",
        "## Suggested Config Snippets",
        "```json",
        json.dumps(
            {
                "fallback_quality_allowlist_symbols": fallback_allow,
                "fallback_blocked_symbols": severe_blocks,
                "symbol_score_multipliers": multiplier_snippet,
            },
            indent=2,
        ),
        "```",
    ]
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return md_path, csv_path, json_path


def main() -> int:
    args = parse_args()
    as_of = datetime.fromisoformat(args.as_of_date)
    live_start = as_of - timedelta(days=args.live_lookback_days)

    config_path = PROJECT_ROOT / args.config
    output_dir = PROJECT_ROOT / args.output_dir
    universe, strategy = _load_config(config_path, args.strategy_id)
    symbols = [symbol for symbol in universe if not args.symbols or symbol in {s.upper() for s in args.symbols}]
    symbol_set = set(symbols)

    trade_metrics = _aggregate_trade_metrics(
        PROJECT_ROOT / "logs" / "trades.runtime.jsonl",
        start=live_start,
        symbols=symbol_set,
        strategy_id=args.strategy_id,
    )
    forward_metrics = _aggregate_forward_metrics(
        PROJECT_ROOT / "logs" / "paper_soak" / "mlp_daily_metrics.csv",
        start=live_start,
        symbols=symbol_set,
    )
    soak_metrics = _aggregate_soak_metrics(
        PROJECT_ROOT / "logs" / "paper_soak",
        start=live_start,
        end=as_of + timedelta(days=1),
        symbols=symbol_set,
    )
    backtests: dict[str, BacktestSummary] = {}
    if not args.skip_backtest:
        backtests = _run_backtests(
            symbols=symbols,
            config_path=str(config_path),
            strategy_id=args.strategy_id,
            backtest_days=args.backtest_days,
            requested_end_date=as_of.date().isoformat(),
        )

    rows = _build_rows(
        symbols=symbols,
        strategy=strategy,
        trade_metrics=trade_metrics,
        forward_metrics=forward_metrics,
        soak_metrics=soak_metrics,
        backtests=backtests,
    )
    md_path, csv_path, json_path = _write_outputs(
        rows=rows,
        output_dir=output_dir,
        as_of_date=as_of.date().isoformat(),
        live_lookback_days=args.live_lookback_days,
        backtest_days=args.backtest_days,
        strategy_id=args.strategy_id,
    )

    recommendation_counts = Counter(row["recommendation"] for row in rows)
    print(f"Wrote: {md_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")
    print(f"Recommendation counts: {dict(recommendation_counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
