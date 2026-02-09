#!/usr/bin/env python3
"""Analyze Bear Short entry quality.

For each bear short entry signal, examine:
- Entry conditions at time of signal
- Forward returns (1, 3, 6, 12 candles ahead)
- Whether the entry was a winner or loser
- Patterns that distinguish good vs bad entries
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators
from scripts.backtest._common import load_data

ASSET_DB = {
    "BTC": "data/binance_bitcoin.db",
    "ETH": "data/binance_ethereum.db",
    "SOL": "data/binance_solana.db",
}


def load_bear_config(asset: str) -> dict:
    """Load bear config from allocation.json for the given asset."""
    alloc_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    with open(alloc_path) as f:
        allocation = json.load(f)
    strategies = allocation.get("strategies", {})
    cfg = strategies.get(f"bear_short_{asset.lower()}")
    if cfg:
        return dict(cfg)
    return strategies.get("bear_short", {})


def analyze_entries(asset: str = "BTC", timeframe: str = "minute240"):
    """Analyze bear short entry signals for a given asset."""
    db_path = str(PROJECT_ROOT / ASSET_DB[asset])
    df = load_data(db_path, timeframe, "2020-01-01", "2025-12-31")
    print(f"\n{'='*80}")
    print(f"  BEAR SHORT ENTRY ANALYSIS: {asset}")
    print(f"{'='*80}")
    print(f"  Loaded {len(df)} candles ({timeframe})")

    # Build adapter (same as combined_hybrid.py)
    bear_config = load_bear_config(asset)
    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="bear_short",
        config=bear_config,
    )
    adapter.symbol = asset

    # Prepare data with indicators
    cached_df = add_all_indicators(df.copy())

    # Get exit params for context
    exit_params = bear_config.get("exit", {}).get("params", {})
    sl_pct = exit_params.get("stop_loss_pct", 3.0)
    tp_pct = exit_params.get("take_profit_pct", 5.0)
    print(f"  Config: SL={sl_pct}%, TP={tp_pct}%")

    # Collect entries
    entries = []
    for i in range(200, len(df)):
        sig = adapter(cached_df, i, {})
        if sig.get("action") == "open_short":
            row = cached_df.iloc[i]
            entry = {
                "idx": i,
                "timestamp": row["timestamp"],
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
                "macd": float(row.get("macd", 0)),
                "macd_signal": float(row.get("macd_signal", 0)),
                "macd_hist": float(row.get("macd", 0)) - float(row.get("macd_signal", 0)),
                "rsi": float(row.get("rsi", 50)),
                "adx": float(row.get("adx", 0)),
                "mfi": float(row.get("mfi", 50)),
                "bb_upper": float(row.get("bb_upper", 0)),
                "bb_lower": float(row.get("bb_lower", 0)),
                "ema200": float(row.get("ema200", 0)),
            }

            # Forward returns: how much price moved after entry
            for fwd in [1, 2, 3, 6, 12, 24]:
                if i + fwd < len(cached_df):
                    fwd_price = float(cached_df.iloc[i + fwd]["close"])
                    # For shorts: positive = profitable (price dropped)
                    entry[f"fwd_{fwd}"] = ((entry["close"] - fwd_price) / entry["close"]) * 100
                else:
                    entry[f"fwd_{fwd}"] = np.nan

            # Max favorable excursion (MFE) and max adverse excursion (MAE) in next 24 candles
            lookahead = min(24, len(cached_df) - i - 1)
            if lookahead > 0:
                future_lows = cached_df.iloc[i+1:i+1+lookahead]["low"].astype(float)
                future_highs = cached_df.iloc[i+1:i+1+lookahead]["high"].astype(float)
                # MFE: max profit for short = max drop from entry
                entry["mfe_24"] = ((entry["close"] - future_lows.min()) / entry["close"]) * 100
                # MAE: max loss for short = max rise from entry
                entry["mae_24"] = ((future_highs.max() - entry["close"]) / entry["close"]) * 100
            else:
                entry["mfe_24"] = np.nan
                entry["mae_24"] = np.nan

            # Price relative to EMA200
            if entry["ema200"] > 0:
                entry["price_vs_ema200"] = ((entry["close"] - entry["ema200"]) / entry["ema200"]) * 100
            else:
                entry["price_vs_ema200"] = np.nan

            # BB width
            if entry["bb_upper"] > 0 and entry["bb_lower"] > 0:
                mid = (entry["bb_upper"] + entry["bb_lower"]) / 2
                entry["bb_width_pct"] = ((entry["bb_upper"] - entry["bb_lower"]) / mid) * 100 if mid > 0 else 0
            else:
                entry["bb_width_pct"] = np.nan

            entries.append(entry)

    edf = pd.DataFrame(entries)
    print(f"  Total entries: {len(edf)}")

    if edf.empty:
        print("  No entries found!")
        return

    # Classify by forward 12-candle return (2 days for 4h candles)
    edf["win_12"] = edf["fwd_12"] > 0  # price dropped = short profit

    wins = edf[edf["win_12"]]
    losses = edf[~edf["win_12"]]
    print(f"  Winners (12-candle): {len(wins)} ({len(wins)/len(edf)*100:.1f}%)")
    print(f"  Losers  (12-candle): {len(losses)} ({len(losses)/len(edf)*100:.1f}%)")

    # Summary stats
    print(f"\n{'─'*80}")
    print(f"  FORWARD RETURNS (short P&L, positive = price dropped)")
    print(f"{'─'*80}")
    for fwd in [1, 2, 3, 6, 12, 24]:
        col = f"fwd_{fwd}"
        mean = edf[col].mean()
        median = edf[col].median()
        pct_positive = (edf[col] > 0).mean() * 100
        print(f"  Fwd {fwd:2d} candles: mean={mean:+.2f}%  median={median:+.2f}%  "
              f"profitable={pct_positive:.1f}%")

    # MFE/MAE analysis
    print(f"\n{'─'*80}")
    print(f"  MAX FAVORABLE / ADVERSE EXCURSION (24 candles = 4 days)")
    print(f"{'─'*80}")
    print(f"  Avg MFE (max drop from entry):  {edf['mfe_24'].mean():.2f}%")
    print(f"  Avg MAE (max rise from entry):  {edf['mae_24'].mean():.2f}%")
    print(f"  Entries where MFE >= TP ({tp_pct}%):  {(edf['mfe_24'] >= tp_pct).sum()} "
          f"({(edf['mfe_24'] >= tp_pct).mean()*100:.1f}%)")
    print(f"  Entries where MAE >= SL ({sl_pct}%):  {(edf['mae_24'] >= sl_pct).sum()} "
          f"({(edf['mae_24'] >= sl_pct).mean()*100:.1f}%)")
    print(f"  Entries where MFE > MAE:         {(edf['mfe_24'] > edf['mae_24']).sum()} "
          f"({(edf['mfe_24'] > edf['mae_24']).mean()*100:.1f}%)")

    # Compare indicators for winners vs losers
    print(f"\n{'─'*80}")
    print(f"  INDICATOR COMPARISON: Winners vs Losers (12-candle horizon)")
    print(f"{'─'*80}")
    indicators = ["macd_hist", "rsi", "adx", "mfi", "bb_width_pct", "price_vs_ema200"]
    print(f"  {'Indicator':<20} {'Winners':>12} {'Losers':>12} {'Delta':>10}")
    print(f"  {'-'*54}")
    for ind in indicators:
        if ind in edf.columns:
            w_mean = wins[ind].mean() if len(wins) > 0 else np.nan
            l_mean = losses[ind].mean() if len(losses) > 0 else np.nan
            delta = w_mean - l_mean if not (np.isnan(w_mean) or np.isnan(l_mean)) else np.nan
            print(f"  {ind:<20} {w_mean:>12.2f} {l_mean:>12.2f} {delta:>+10.2f}")

    # Year-by-year
    edf["timestamp"] = pd.to_datetime(edf["timestamp"])
    edf["year"] = edf["timestamp"].dt.year

    print(f"\n{'─'*80}")
    print(f"  YEAR-BY-YEAR ENTRY QUALITY")
    print(f"{'─'*80}")
    print(f"  {'Year':<6} {'Entries':>8} {'WR(12c)':>10} {'AvgFwd12':>12} {'AvgMFE':>10} {'AvgMAE':>10}")
    print(f"  {'-'*56}")
    for year, grp in edf.groupby("year"):
        wr = (grp["fwd_12"] > 0).mean() * 100
        avg_fwd = grp["fwd_12"].mean()
        avg_mfe = grp["mfe_24"].mean()
        avg_mae = grp["mae_24"].mean()
        print(f"  {int(year):<6} {len(grp):>8} {wr:>9.1f}% {avg_fwd:>+11.2f}% {avg_mfe:>9.2f}% {avg_mae:>9.2f}%")

    # Consecutive entries analysis
    print(f"\n{'─'*80}")
    print(f"  ENTRY CLUSTERING")
    print(f"{'─'*80}")
    edf["gap"] = edf["idx"].diff()
    # Back-to-back: adapter opens short, next candle adapter returns hold (in position),
    # then after exit it may re-enter. Gap=1 means immediate re-entry.
    close_entries = (edf["gap"] <= 3).sum() - 1  # exclude first NaN
    print(f"  Entries within 3 candles of previous: {close_entries} "
          f"({close_entries/max(len(edf)-1, 1)*100:.1f}%)")
    far_entries = (edf["gap"] > 12).sum()
    print(f"  Entries >12 candles apart:            {far_entries} "
          f"({far_entries/max(len(edf)-1, 1)*100:.1f}%)")

    # MACD histogram distribution at entry
    print(f"\n{'─'*80}")
    print(f"  MACD HISTOGRAM AT ENTRY (negative = bearish)")
    print(f"{'─'*80}")
    hist = edf["macd_hist"]
    pcts = [10, 25, 50, 75, 90]
    vals = np.percentile(hist.dropna(), pcts)
    for p, v in zip(pcts, vals):
        print(f"  P{p:2d}: {v:+.2f}")

    # ADX distribution
    print(f"\n{'─'*80}")
    print(f"  ADX AT ENTRY (trend strength)")
    print(f"{'─'*80}")
    adx = edf["adx"]
    vals = np.percentile(adx.dropna(), pcts)
    for p, v in zip(pcts, vals):
        print(f"  P{p:2d}: {v:.1f}")

    # RSI distribution
    print(f"\n{'─'*80}")
    print(f"  RSI AT ENTRY")
    print(f"{'─'*80}")
    rsi = edf["rsi"]
    vals = np.percentile(rsi.dropna(), pcts)
    for p, v in zip(pcts, vals):
        print(f"  P{p:2d}: {v:.1f}")


if __name__ == "__main__":
    for asset in ["BTC", "ETH", "SOL"]:
        analyze_entries(asset)
