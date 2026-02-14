#!/usr/bin/env python3
"""Compare B&H, current MLP baseline, and Regime Long-Only Swing v1.

Regime Long-Only Swing v1 logic (daily):
- Entry: at least 3 risk-on days in recent 4 days, close > EMA20, no cooldown.
- Hold: stay invested while no hard exit trigger.
- Exit: any of
  1) 1d return <= -6%
  2) 3d return <= -10%
  3) close < EMA100 for 2 consecutive days
  4) drawdown from post-entry peak >= 12%
- Re-entry: after cooldown (3 days), evaluate entry again.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import compute_metrics, load_data
from scripts.backtest.backtest_mlp import MLPDirectionBacktester, load_strategy_config


ASSET_DB = {
    "BTC": PROJECT_ROOT / "data" / "binance_bitcoin.db",
    "ETH": PROJECT_ROOT / "data" / "binance_ethereum.db",
    "SOL": PROJECT_ROOT / "data" / "binance_solana.db",
    "BNB": PROJECT_ROOT / "data" / "binance_bnb.db",
}


@dataclass
class RegimeParams:
    ema_fast: int = 20
    ema_slow: int = 100
    rsi_period: int = 14
    momentum_lookback: int = 20
    entry_lookback_days: int = 4
    entry_quorum: int = 3
    drop_1d_pct: float = -0.06
    drop_3d_pct: float = -0.10
    peak_dd_exit_pct: float = 0.12
    cooldown_days: int = 3
    fee_rate: float = 0.001


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare B&H vs MLP vs Regime Long-Only Swing v1",
    )
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2026-02-13")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "BNB"])
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--config", default="config/strategies/allocation.json")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--strategy-label", default="RegimeLongSwing_v1")
    parser.add_argument("--entry-lookback-days", type=int, default=4)
    parser.add_argument("--entry-quorum", type=int, default=3)
    parser.add_argument("--drop-1d-pct", type=float, default=-0.06)
    parser.add_argument("--drop-3d-pct", type=float, default=-0.10)
    parser.add_argument("--peak-dd-exit-pct", type=float, default=0.12)
    parser.add_argument("--cooldown-days", type=int, default=3)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    return parser.parse_args()


def _to_daily(df_4h: pd.DataFrame) -> pd.DataFrame:
    if df_4h.empty:
        return df_4h
    daily = (
        df_4h.set_index("timestamp")
        .resample("1D")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    return daily


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _prepare_regime_frame(daily: pd.DataFrame, p: RegimeParams) -> pd.DataFrame:
    df = daily.copy()
    df["ema_fast"] = df["close"].ewm(span=p.ema_fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=p.ema_slow, adjust=False).mean()
    df["rsi"] = _compute_rsi(df["close"], p.rsi_period)
    df["ret_1d"] = df["close"].pct_change()
    df["ret_3d"] = df["close"].pct_change(3)
    df["ret_lookback"] = df["close"].pct_change(p.momentum_lookback)

    score = (
        (df["close"] > df["ema_fast"]).astype(int)
        + (df["ema_fast"] > df["ema_slow"]).astype(int)
        + (df["rsi"] > 50.0).astype(int)
        + (df["ret_lookback"] > 0.0).astype(int)
    )
    df["risk_on_day"] = score >= 3
    df["risk_on_recent"] = (
        df["risk_on_day"]
        .rolling(window=p.entry_lookback_days, min_periods=p.entry_lookback_days)
        .sum()
    )
    df["entry_signal"] = (
        (df["risk_on_recent"] >= p.entry_quorum)
        & (df["close"] > df["ema_fast"])
    )
    df["below_ema_slow_2d"] = (
        (df["close"] < df["ema_slow"])
        & (df["close"].shift(1) < df["ema_slow"].shift(1))
    )
    return df


def _build_bnh_equity(daily: pd.DataFrame, capital: float) -> pd.DataFrame:
    out = daily[["timestamp", "close"]].copy()
    out["total_equity"] = capital * (out["close"] / float(out["close"].iloc[0]))
    return out[["timestamp", "total_equity"]]


def _compute_trade_stats(trade_returns: list[float]) -> tuple[int, float]:
    if not trade_returns:
        return 0, 0.0
    wins = sum(1 for x in trade_returns if x > 0)
    return len(trade_returns), (wins / len(trade_returns)) * 100.0


def run_regime_long_only(
    daily: pd.DataFrame,
    capital: float,
    p: RegimeParams,
) -> dict[str, Any]:
    df = _prepare_regime_frame(daily, p)
    cash = capital
    qty = 0.0
    in_pos = False
    cooldown = 0
    entry_price = 0.0
    peak_price = 0.0
    trade_returns: list[float] = []
    equity_rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        price = float(row["close"])
        ts = row["timestamp"]

        if in_pos:
            peak_price = max(peak_price, price)
            dd_from_peak = (price / peak_price) - 1.0 if peak_price > 0 else 0.0
            exit_signal = bool(
                (row["ret_1d"] <= p.drop_1d_pct)
                or (row["ret_3d"] <= p.drop_3d_pct)
                or row["below_ema_slow_2d"]
                or (dd_from_peak <= -p.peak_dd_exit_pct)
            )
            if exit_signal:
                gross = qty * price
                fee = gross * p.fee_rate
                cash = gross - fee
                trade_returns.append((price / entry_price) - 1.0 - (2 * p.fee_rate))
                qty = 0.0
                in_pos = False
                cooldown = p.cooldown_days
                entry_price = 0.0
                peak_price = 0.0

        else:
            if cooldown > 0:
                cooldown -= 1
            else:
                if bool(row["entry_signal"]):
                    fee = cash * p.fee_rate
                    investable = cash - fee
                    if investable > 0:
                        qty = investable / price
                        cash = 0.0
                        in_pos = True
                        entry_price = price
                        peak_price = price

        equity = cash + (qty * price if in_pos else 0.0)
        equity_rows.append({"timestamp": ts, "total_equity": equity})

    if in_pos:
        final_price = float(df["close"].iloc[-1])
        gross = qty * final_price
        fee = gross * p.fee_rate
        cash = gross - fee
        trade_returns.append((final_price / entry_price) - 1.0 - (2 * p.fee_rate))
        equity_rows[-1]["total_equity"] = cash

    eq = pd.DataFrame(equity_rows)
    metrics = compute_metrics(eq, timeframe="day")
    total_trades, win_rate = _compute_trade_stats(trade_returns)

    return {
        "equity_curve": eq,
        "metrics": metrics,
        "total_return_pct": metrics["total_return"],
        "cagr_pct": metrics["cagr"],
        "mdd_pct": abs(metrics["mdd"]),
        "sharpe": metrics["sharpe"],
        "trades": total_trades,
        "win_rate_pct": win_rate,
    }


def run_mlp_symbol(
    symbol: str,
    df_4h: pd.DataFrame,
    config_path: str,
    capital: float,
) -> dict[str, Any]:
    _, strategy_id, strategy_cfg = load_strategy_config(
        config_path=config_path,
        symbol=symbol,
        mode="paper",
        strategy_id=f"mlp_direction_{symbol.lower()}",
    )
    bt = MLPDirectionBacktester(
        symbol=symbol,
        config=strategy_cfg,
        strategy_label=strategy_id,
    )
    prepared = bt.prepare_data(df_4h.copy())
    results = bt.run(prepared, initial_capital=capital)
    eq = results.get("equity_curve")
    metrics = compute_metrics(eq, timeframe="minute240")

    return {
        "equity_curve": eq,
        "total_return_pct": float(results.get("total_return", 0.0)),
        "cagr_pct": metrics["cagr"],
        "mdd_pct": abs(metrics["mdd"]),
        "sharpe": metrics["sharpe"],
        "trades": int(results.get("total_trades", 0)),
        "win_rate_pct": float(results.get("win_rate", 0.0)) * 100.0,
    }


def _compare_row(
    symbol: str,
    method: str,
    result: dict[str, Any],
    bnh_return_pct: float,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "method": method,
        "return_pct": float(result["total_return_pct"]),
        "cagr_pct": float(result["cagr_pct"]),
        "mdd_pct": float(result["mdd_pct"]),
        "sharpe": float(result["sharpe"]),
        "trades": int(result["trades"]),
        "win_rate_pct": float(result["win_rate_pct"]),
        "alpha_vs_bnh_pctp": float(result["total_return_pct"] - bnh_return_pct),
    }


def _build_markdown(summary_df: pd.DataFrame, detail_df: pd.DataFrame, meta: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Regime Long-Only Swing v1 Comparison")
    lines.append("")
    lines.append(f"- Generated: {meta['generated_at']}")
    lines.append(f"- Period: {meta['start_date']} to {meta['end_date']}")
    lines.append(f"- Symbols: {', '.join(meta['symbols'])}")
    lines.append("")
    lines.append("## Method Summary")
    lines.append("")
    lines.append("| Method | Mean Return % | Mean CAGR % | Mean MDD % | Mean Sharpe | Mean Alpha vs B&H %p | Total Trades | Mean Win Rate % | Beating Symbols |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in summary_df.iterrows():
        lines.append(
            f"| {r['method']} | {r['mean_return_pct']:.2f} | {r['mean_cagr_pct']:.2f} | "
            f"{r['mean_mdd_pct']:.2f} | {r['mean_sharpe']:.2f} | {r['mean_alpha_vs_bnh_pctp']:.2f} | "
            f"{int(r['total_trades'])} | {r['mean_win_rate_pct']:.2f} | {int(r['beating_symbols'])} |"
        )
    lines.append("")
    lines.append("## Per Symbol Detail")
    lines.append("")
    lines.append("| Symbol | Method | Return % | CAGR % | MDD % | Sharpe | Trades | Win Rate % | Alpha vs B&H %p |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in detail_df.sort_values(["symbol", "method"]).iterrows():
        lines.append(
            f"| {r['symbol']} | {r['method']} | {r['return_pct']:.2f} | {r['cagr_pct']:.2f} | "
            f"{r['mdd_pct']:.2f} | {r['sharpe']:.2f} | {int(r['trades'])} | {r['win_rate_pct']:.2f} | "
            f"{r['alpha_vs_bnh_pctp']:.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    symbols = [s.upper() for s in args.symbols]
    p = RegimeParams(
        entry_lookback_days=args.entry_lookback_days,
        entry_quorum=args.entry_quorum,
        drop_1d_pct=args.drop_1d_pct,
        drop_3d_pct=args.drop_3d_pct,
        peak_dd_exit_pct=args.peak_dd_exit_pct,
        cooldown_days=args.cooldown_days,
        fee_rate=args.fee_rate,
    )

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []

    for symbol in symbols:
        db_path = ASSET_DB.get(symbol)
        if db_path is None or not db_path.exists():
            skipped.append(symbol)
            continue

        df_4h = load_data(
            db_path=str(db_path),
            timeframe="minute240",
            start_date=args.start_date,
            end_date=args.end_date,
            exchange="binance",
        )
        if df_4h.empty:
            skipped.append(symbol)
            continue

        daily = _to_daily(df_4h)
        if len(daily) < 200:
            skipped.append(symbol)
            continue

        bnh_eq = _build_bnh_equity(daily, args.capital)
        bnh_metrics = compute_metrics(bnh_eq, timeframe="day")
        bnh = {
            "total_return_pct": bnh_metrics["total_return"],
            "cagr_pct": bnh_metrics["cagr"],
            "mdd_pct": abs(bnh_metrics["mdd"]),
            "sharpe": bnh_metrics["sharpe"],
            "trades": 1,
            "win_rate_pct": 100.0,
        }

        mlp = run_mlp_symbol(
            symbol=symbol,
            df_4h=df_4h,
            config_path=args.config,
            capital=args.capital,
        )
        regime = run_regime_long_only(
            daily=daily,
            capital=args.capital,
            p=p,
        )

        bnh_ret = bnh["total_return_pct"]
        rows.append(_compare_row(symbol, "B&H", bnh, bnh_ret))
        rows.append(_compare_row(symbol, "MLP(current)", mlp, bnh_ret))
        rows.append(_compare_row(symbol, args.strategy_label, regime, bnh_ret))

    if not rows:
        print("No symbols were evaluated. Check data availability.")
        return 1

    detail_df = pd.DataFrame(rows)
    summary_df = (
        detail_df.groupby("method", as_index=False)
        .agg(
            mean_return_pct=("return_pct", "mean"),
            mean_cagr_pct=("cagr_pct", "mean"),
            mean_mdd_pct=("mdd_pct", "mean"),
            mean_sharpe=("sharpe", "mean"),
            mean_alpha_vs_bnh_pctp=("alpha_vs_bnh_pctp", "mean"),
            total_trades=("trades", "sum"),
            mean_win_rate_pct=("win_rate_pct", "mean"),
            beating_symbols=("alpha_vs_bnh_pctp", lambda s: int((s > 0).sum())),
        )
        .sort_values("mean_alpha_vs_bnh_pctp", ascending=False)
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"regime_long_only_v1_compare_{ts}.csv"
    json_path = out_dir / f"regime_long_only_v1_compare_{ts}.json"
    md_path = out_dir / f"regime_long_only_v1_compare_{ts}.md"

    detail_df.to_csv(csv_path, index=False)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "symbols": symbols,
        "skipped_symbols": skipped,
        "strategy_label": args.strategy_label,
        "params": p.__dict__,
        "summary": summary_df.to_dict(orient="records"),
        "detail": detail_df.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(
        _build_markdown(summary_df, detail_df, payload),
        encoding="utf-8",
    )

    print(f"Saved: {csv_path}")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")
    if skipped:
        print(f"Skipped symbols: {', '.join(skipped)}")
    print("\nMethod summary:")
    print(summary_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
