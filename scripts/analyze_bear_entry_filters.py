#!/usr/bin/env python3
"""Test all filter combinations for Bear Short entry improvement.

Filters tested:
  A: EMA200  - price < EMA200 (confirms actual downtrend)
  B: MACD_STR - MACD histogram below asset-specific median (strong momentum)
  C: RSI     - RSI < threshold (confirms bearish pressure)
  D: CONSEC  - N consecutive BEAR_STRONG candles (confirms regime stability)

Tests: base + all singles + all pairs + all triples + all quads
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trading.indicators import add_all_indicators
from scripts.backtest._common import load_data, ShortMarginBacktester

ASSET_DB = {
    "BTC": "data/binance_bitcoin.db",
    "ETH": "data/binance_ethereum.db",
    "SOL": "data/binance_solana.db",
}

BEAR_CONFIG = {
    "BTC": {"sl": 3.0, "tp": 6.0, "trail_act": 2.0, "trail_dist": 1.5},
    "ETH": {"sl": 4.0, "tp": 8.0, "trail_act": 2.5, "trail_dist": 2.0},
    "SOL": {"sl": 5.0, "tp": 10.0, "trail_act": 3.0, "trail_dist": 2.5},
}


def classify_regime(mfi: float, adx: float) -> str:
    """Simplified regime classification matching models.py."""
    if mfi >= 54:
        return "BULL_STRONG" if adx >= 25 else "BULL_MODERATE"
    elif mfi >= 49:
        return "SIDEWAYS_UP"
    elif mfi >= 41:
        return "SIDEWAYS_FLAT" if adx < 18 else ("SIDEWAYS_DOWN" if adx < 25 else "SIDEWAYS_FLAT")
    elif mfi >= 34:
        return "BEAR_MODERATE"
    else:
        return "BEAR_STRONG" if adx >= 25 else "BEAR_MODERATE"


def compute_regimes(df: pd.DataFrame) -> pd.Series:
    """Compute regime for each row."""
    regimes = []
    for _, row in df.iterrows():
        mfi = float(row.get("mfi", 50))
        adx = float(row.get("adx", 0))
        regimes.append(classify_regime(mfi, adx))
    return pd.Series(regimes, index=df.index)


def consecutive_regime_count(regimes: pd.Series, target: str) -> pd.Series:
    """For each row, count how many consecutive `target` regimes ending at that row."""
    counts = []
    streak = 0
    for r in regimes:
        if r == target:
            streak += 1
        else:
            streak = 0
        counts.append(streak)
    return pd.Series(counts, index=regimes.index)


def run_filter_backtest(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    asset: str,
    capital: float = 1000.0,
    leverage: float = 3.0,
    position_pct: float = 0.10,
) -> dict:
    """Run a simplified short backtest using a boolean entry mask.

    Uses the exit strategy logic (SL/TP/trailing/regime) from the adapter.
    """
    cfg = BEAR_CONFIG[asset]
    sl_pct = cfg["sl"] / 100
    tp_pct = cfg["tp"] / 100
    trail_act = cfg["trail_act"] / 100
    trail_dist = cfg["trail_dist"] / 100

    bt = ShortMarginBacktester(
        initial_capital=capital,
        fee_rate=0.0005,
        slippage=0.0002,
        leverage=leverage,
        min_order_amount=5,
        action_open="open_short",
        action_close="close_short",
    )

    # We simulate exit logic inline since we need the mask-based entries
    regimes = compute_regimes(df)
    hold_regimes = {"BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN", "SIDEWAYS_FLAT"}

    def strategy_func(df_data, i, params):
        if i < 200:
            return {"action": "hold"}

        # If we're in a short position, check exit conditions
        if bt.in_short:
            price = float(df_data.iloc[i]["close"])
            pnl_pct = (bt.entry_price - price) / bt.entry_price

            # SL
            if pnl_pct <= -sl_pct:
                return {"action": "close_short"}
            # TP
            if pnl_pct >= tp_pct:
                return {"action": "close_short"}
            # Trailing: track LWM
            lwm = params.get("_lwm", bt.entry_price)
            if price < lwm:
                lwm = price
                params["_lwm"] = lwm
            lwm_pnl = (bt.entry_price - lwm) / bt.entry_price
            if lwm_pnl >= trail_act:
                trail_price = lwm * (1 + trail_dist)
                if price >= trail_price:
                    return {"action": "close_short"}
            # Regime grace
            regime = regimes.iloc[i] if i < len(regimes) else "UNKNOWN"
            grace = params.get("_grace", 0)
            if regime not in hold_regimes:
                grace += 1
                params["_grace"] = grace
                if grace >= 3:
                    return {"action": "close_short"}
            else:
                params["_grace"] = 0
            return {"action": "hold"}

        # Not in position: check entry
        if entry_mask.iloc[i]:
            params["_lwm"] = float(df_data.iloc[i]["close"])
            params["_grace"] = 0
            return {"action": "open_short", "fraction": position_pct}

        return {"action": "hold"}

    results = bt.run(df, strategy_func, {})
    return results


def test_asset(asset: str):
    """Test all filter combinations for one asset."""
    db_path = str(PROJECT_ROOT / ASSET_DB[asset])
    df = load_data(db_path, "minute240", "2020-01-01", "2025-12-31")
    df = add_all_indicators(df.copy())

    print(f"\n{'='*90}")
    print(f"  FILTER COMBINATION TEST: {asset}")
    print(f"  Config: SL={BEAR_CONFIG[asset]['sl']}%, TP={BEAR_CONFIG[asset]['tp']}%")
    print(f"{'='*90}")

    # Compute base conditions
    regimes = compute_regimes(df)
    consec_bear = consecutive_regime_count(regimes, "BEAR_STRONG")

    base_mask = (regimes == "BEAR_STRONG") & (df["macd"] < df["macd_signal"])
    # Shift base_mask to start from index 200
    base_mask[:200] = False

    # Compute EMA200 (check if column exists)
    if "ema200" not in df.columns:
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

    # Compute MACD histogram median per-asset (from entries only)
    base_entries = df[base_mask]
    macd_hist = (df["macd"] - df["macd_signal"])
    macd_hist_at_entries = macd_hist[base_mask]
    macd_p25 = macd_hist_at_entries.quantile(0.25)
    macd_p50 = macd_hist_at_entries.quantile(0.50)

    print(f"  Base entries (BEAR_STRONG + MACD<Signal): {base_mask.sum()}")
    print(f"  MACD hist at entries: P25={macd_p25:.2f}, P50={macd_p50:.2f}")

    # Define filters
    filters = {
        "A:EMA200": df["close"] < df["ema200"],
        "B:MACD_P50": macd_hist <= macd_p50,
        "B:MACD_P25": macd_hist <= macd_p25,
        "C:RSI<40": df["rsi"] < 40,
        "C:RSI<35": df["rsi"] < 35,
        "C:RSI<30": df["rsi"] < 30,
        "D:CONSEC>=2": consec_bear >= 2,
        "D:CONSEC>=3": consec_bear >= 3,
    }

    # Build all filter combinations to test
    # For B and C, test the best variant only (we'll show all variants initially)
    all_single_keys = list(filters.keys())

    # First: test all singles
    results_table = []

    # Base case
    res = run_filter_backtest(df, base_mask, asset)
    results_table.append({
        "filters": "BASE",
        "entries": res["total_trades"],
        "wr": res["win_rate"] * 100,
        "return": res["total_return"],
        "pf": res["profit_factor"],
        "avg_win": res["avg_profit"],
        "avg_loss": res["avg_loss"],
    })

    # All individual filters
    for name, filt in filters.items():
        mask = base_mask & filt
        if mask.sum() == 0:
            results_table.append({
                "filters": name,
                "entries": 0, "wr": 0, "return": 0, "pf": 0,
                "avg_win": 0, "avg_loss": 0,
            })
            continue
        res = run_filter_backtest(df, mask, asset)
        results_table.append({
            "filters": name,
            "entries": res["total_trades"],
            "wr": res["win_rate"] * 100,
            "return": res["total_return"],
            "pf": res["profit_factor"],
            "avg_win": res["avg_profit"],
            "avg_loss": res["avg_loss"],
        })

    # Best single from each group
    # Group A: EMA200 (only one)
    # Group B: MACD_P50 vs MACD_P25
    # Group C: RSI<40 vs RSI<35 vs RSI<30
    # Group D: CONSEC>=2 vs CONSEC>=3

    # Pick representative filters for combinations
    combo_filters = {
        "A": filters["A:EMA200"],
        "B25": filters["B:MACD_P25"],
        "B50": filters["B:MACD_P50"],
        "C40": filters["C:RSI<40"],
        "C35": filters["C:RSI<35"],
        "D2": filters["D:CONSEC>=2"],
        "D3": filters["D:CONSEC>=3"],
    }

    # Key combinations to test (not exhaustive but covers important ones)
    combos = [
        # Pairs
        ("A+B50", ["A", "B50"]),
        ("A+C40", ["A", "C40"]),
        ("A+C35", ["A", "C35"]),
        ("A+D2", ["A", "D2"]),
        ("A+D3", ["A", "D3"]),
        ("B50+C40", ["B50", "C40"]),
        ("B50+D2", ["B50", "D2"]),
        ("C40+D2", ["C40", "D2"]),
        ("C35+D2", ["C35", "D2"]),
        # Triples
        ("A+B50+C40", ["A", "B50", "C40"]),
        ("A+B50+D2", ["A", "B50", "D2"]),
        ("A+C40+D2", ["A", "C40", "D2"]),
        ("A+C35+D2", ["A", "C35", "D2"]),
        ("B50+C40+D2", ["B50", "C40", "D2"]),
        ("A+B25+C35", ["A", "B25", "C35"]),
        # Quads
        ("A+B50+C40+D2", ["A", "B50", "C40", "D2"]),
        ("A+B25+C35+D2", ["A", "B25", "C35", "D2"]),
        ("A+B50+C35+D3", ["A", "B50", "C35", "D3"]),
    ]

    for name, keys in combos:
        mask = base_mask.copy()
        for k in keys:
            mask = mask & combo_filters[k]
        if mask.sum() == 0:
            results_table.append({
                "filters": name,
                "entries": 0, "wr": 0, "return": 0, "pf": 0,
                "avg_win": 0, "avg_loss": 0,
            })
            continue
        res = run_filter_backtest(df, mask, asset)
        results_table.append({
            "filters": name,
            "entries": res["total_trades"],
            "wr": res["win_rate"] * 100,
            "return": res["total_return"],
            "pf": res["profit_factor"],
            "avg_win": res["avg_profit"],
            "avg_loss": res["avg_loss"],
        })

    # Print results table
    rdf = pd.DataFrame(results_table)
    print(f"\n{'─'*90}")
    print(f"  {'Filters':<22} {'Trades':>7} {'WR%':>7} {'Return%':>9} {'PF':>6} "
          f"{'AvgWin':>8} {'AvgLoss':>8}")
    print(f"  {'─'*68}")
    for _, row in rdf.iterrows():
        pf_str = f"{row['pf']:.2f}" if row['pf'] < 100 else "inf"
        print(f"  {row['filters']:<22} {row['entries']:>7} {row['wr']:>6.1f}% "
              f"{row['return']:>+8.1f}% {pf_str:>6} "
              f"{row['avg_win']:>8.1f} {row['avg_loss']:>8.1f}")

    # Highlight best combinations
    profitable = rdf[rdf["return"] > 0].sort_values("return", ascending=False)
    if not profitable.empty:
        print(f"\n  TOP PROFITABLE COMBINATIONS:")
        for _, row in profitable.head(5).iterrows():
            pf_str = f"{row['pf']:.2f}" if row['pf'] < 100 else "inf"
            print(f"    {row['filters']:<22} Return={row['return']:>+.1f}%  "
                  f"WR={row['wr']:.1f}%  Trades={row['entries']:.0f}  PF={pf_str}")
    else:
        print(f"\n  No profitable combinations found.")

    # Best by Sharpe-like metric (return / trades for efficiency)
    rdf_active = rdf[rdf["entries"] > 10].copy()
    if not rdf_active.empty:
        rdf_active["efficiency"] = rdf_active["return"] / rdf_active["entries"]
        best_eff = rdf_active.sort_values("efficiency", ascending=False).head(3)
        print(f"\n  MOST EFFICIENT (return/trade):")
        for _, row in best_eff.iterrows():
            print(f"    {row['filters']:<22} {row['return']/row['entries']:>+.2f}%/trade  "
                  f"Trades={row['entries']:.0f}  Total={row['return']:>+.1f}%")

    return rdf


if __name__ == "__main__":
    all_results = {}
    for asset in ["BTC", "ETH", "SOL"]:
        rdf = test_asset(asset)
        all_results[asset] = rdf

    # Cross-asset summary
    print(f"\n\n{'='*90}")
    print(f"  CROSS-ASSET SUMMARY: Best filter per asset")
    print(f"{'='*90}")
    for asset, rdf in all_results.items():
        active = rdf[rdf["entries"] >= 5]
        if active.empty:
            print(f"  {asset}: No combinations with >= 5 trades")
            continue
        best = active.sort_values("return", ascending=False).iloc[0]
        pf_str = f"{best['pf']:.2f}" if best['pf'] < 100 else "inf"
        print(f"  {asset}: {best['filters']:<22} Return={best['return']:>+.1f}%  "
              f"WR={best['wr']:.1f}%  Trades={best['entries']:.0f}  PF={pf_str}")
