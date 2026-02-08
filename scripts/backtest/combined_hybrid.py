#!/usr/bin/env python3
"""
Combined Hybrid Backtest: MLP Direction (Spot/Long) + Bear Short (Futures/Short)

Simulates the hybrid trading mode where:
- MLP Direction handles spot entries (long) during non-bear regimes
- Bear Short handles futures shorts during BEAR_STRONG regimes

Each strategy operates with its own capital allocation.
Combined equity = spot equity + futures equity.

Usage:
    python scripts/backtest/combined_hybrid.py
    python scripts/backtest/combined_hybrid.py --assets BTC ETH SOL --by-year
    python scripts/backtest/combined_hybrid.py --spot-pct 0.7 --futures-pct 0.3
    python scripts/backtest/combined_hybrid.py --use-optimized-bear
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    load_data,
    compute_metrics,
    print_yearly_table,
    ShortMarginBacktester,
)
from scripts.backtest.backtest_mlp import MLPDirectionBacktester, load_strategy_config
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators

# Asset database paths
ASSET_DB = {
    "BTC": ("data/binance_bitcoin.db", "BTC"),
    "ETH": ("data/binance_ethereum.db", "ETH"),
    "SOL": ("data/binance_solana.db", "SOL"),
}

# MLP model mapping (per-asset configs from allocation.json)
MLP_STRATEGY_IDS = {
    "BTC": "mlp_direction_btc",
    "ETH": "mlp_direction_eth",
    "SOL": "mlp_direction_sol",
}

# Fallback bear short config (used only if allocation.json has no bear_short)
_BEAR_SHORT_FALLBACK = {
    "market": "futures",
    "leverage": 3,
    "position_pct": 0.10,
    "drawdown_enabled": False,
    "stop_loss_cooldown": 0,
    "entry": {
        "class": "BearShortEntryStrategy",
        "params": {
            "volume_ratio_threshold": 1.5,
            "position_size": 0.01,
        },
    },
    "exit": {
        "class": "BearShortExitStrategy",
        "params": {
            "stop_loss_pct": 3.0,
            "take_profit_pct": 5.0,
        },
    },
}


def load_bear_config(
    config_path: str = "config/strategies/allocation.json",
    asset: str | None = None,
) -> dict[str, Any]:
    """Load bear short config from allocation.json (same source as dashboard).

    Looks for per-symbol key first (e.g. bear_short_btc), then falls back to
    generic bear_short, then to _BEAR_SHORT_FALLBACK.
    """
    alloc_path = PROJECT_ROOT / config_path
    if alloc_path.exists():
        with open(alloc_path) as f:
            allocation = json.load(f)
        strategies = allocation.get("strategies", {})
        # Per-symbol key first (bear_short_btc, bear_short_eth, ...)
        if asset:
            bear_cfg = strategies.get(f"bear_short_{asset.lower()}")
            if bear_cfg:
                return dict(bear_cfg)
        # Generic fallback
        bear_cfg = strategies.get("bear_short")
        if bear_cfg:
            return dict(bear_cfg)
    return dict(_BEAR_SHORT_FALLBACK)


def load_optimized_bear_config(base_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load optimized bear short params if available, applied on top of base config."""
    config = dict(base_config or load_bear_config())
    opt_path = PROJECT_ROOT / "config" / "strategies" / "bear_short_optimized.json"
    if opt_path.exists():
        with open(opt_path) as f:
            opt = json.load(f)
        params = opt.get("optimized_params", {})
        if "entry" in config and "params" in config["entry"]:
            config["entry"]["params"]["volume_ratio_threshold"] = params.get(
                "volume_ratio_threshold",
                config["entry"]["params"].get("volume_ratio_threshold", 1.5),
            )
        if "exit" in config and "params" in config["exit"]:
            config["exit"]["params"]["stop_loss_pct"] = params.get(
                "stop_loss_pct", config["exit"]["params"].get("stop_loss_pct", 3.0)
            )
            config["exit"]["params"]["take_profit_pct"] = params.get(
                "take_profit_pct", config["exit"]["params"].get("take_profit_pct", 5.0)
            )
    return config


def run_mlp_backtest(
    asset: str,
    df: pd.DataFrame,
    capital: float,
    config_path: str,
) -> dict:
    """Run MLP Direction (spot/long) backtest for one asset."""
    try:
        _, strategy_id, strategy_config = load_strategy_config(
            config_path=config_path,
            symbol=asset,
            mode="paper",
            strategy_id=MLP_STRATEGY_IDS.get(asset),
        )
    except ValueError:
        print(f"  WARNING: No MLP config for {asset}, skipping spot")
        return {}

    model_path = Path(strategy_config.get("model_path", ""))
    if not model_path.exists():
        print(f"  WARNING: Model not found at {model_path}, skipping {asset} spot")
        return {}

    backtester_obj = MLPDirectionBacktester(
        symbol=asset,
        config=strategy_config,
        strategy_label=strategy_id,
    )

    df_prepared = backtester_obj.prepare_data(df.copy())
    results = backtester_obj.run(df_prepared, initial_capital=capital)
    return results


def run_bear_short_backtest(
    asset: str,
    df: pd.DataFrame,
    capital: float,
    bear_config: dict[str, Any],
) -> dict:
    """Run Bear Short (futures/short) backtest for one asset."""
    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="bear_short",
        config=bear_config,
    )
    _, symbol = ASSET_DB[asset]
    adapter.symbol = symbol

    leverage = float(bear_config.get("leverage", 3))

    cached_df = add_all_indicators(df.copy())
    position_pct = float(bear_config.get("position_pct", 0.10))

    def strategy_func(df_data, i, params):
        if i < 200:
            return {"action": "hold"}
        sig = adapter(cached_df, i, params)
        # Adapter returns fraction as position_size (BTC qty), but
        # ShortMarginBacktester expects fraction as % of cash.
        # Override with position_pct from config for correct sizing.
        if sig.get("action") == "open_short":
            sig["fraction"] = position_pct
        return sig

    bt = ShortMarginBacktester(
        initial_capital=capital,
        fee_rate=0.0005,
        slippage=0.0002,
        leverage=leverage,
        min_order_amount=10,
        action_open="open_short",
        action_close="close_short",
    )
    results = bt.run(df, strategy_func, {})
    return results


def combine_equity_curves(
    spot_eq: pd.DataFrame,
    futures_eq: pd.DataFrame,
) -> pd.DataFrame:
    """Merge two equity curves into a combined curve."""
    if spot_eq.empty and futures_eq.empty:
        return pd.DataFrame()
    if spot_eq.empty:
        return futures_eq.copy()
    if futures_eq.empty:
        return spot_eq.copy()

    # Merge on timestamp
    spot = spot_eq[["timestamp", "total_equity"]].rename(
        columns={"total_equity": "spot_equity"}
    )
    futures = futures_eq[["timestamp", "total_equity"]].rename(
        columns={"total_equity": "futures_equity"}
    )

    merged = pd.merge(spot, futures, on="timestamp", how="outer").sort_values(
        "timestamp"
    )
    merged["spot_equity"] = merged["spot_equity"].ffill().bfill()
    merged["futures_equity"] = merged["futures_equity"].ffill().bfill()
    merged["total_equity"] = merged["spot_equity"] + merged["futures_equity"]
    return merged


def print_strategy_summary(label: str, results: dict, metrics: dict):
    """Print summary for a single strategy run."""
    ret = results.get("total_return", 0)
    trades = results.get("total_trades", 0)
    wr = results.get("win_rate", 0) * 100
    sharpe = metrics.get("sharpe", 0)
    mdd = metrics.get("mdd", 0)
    cagr = metrics.get("cagr", 0)
    pf = results.get("profit_factor", 0)
    print(
        f"  {label:<30} Return={ret:+8.2f}%  CAGR={cagr:+6.2f}%  "
        f"Trades={trades:>4}  WR={wr:>5.1f}%  Sharpe={sharpe:+6.2f}  "
        f"MDD={mdd:>7.2f}%  PF={pf:.2f}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Combined Hybrid Backtest: MLP Direction + Bear Short"
    )
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument(
        "--spot-pct", type=float, default=0.7, help="Capital allocation to spot (0-1)"
    )
    parser.add_argument(
        "--futures-pct",
        type=float,
        default=0.3,
        help="Capital allocation to futures (0-1)",
    )
    parser.add_argument("--by-year", action="store_true")
    parser.add_argument(
        "--use-optimized-bear",
        action="store_true",
        help="Use Optuna-optimized bear short params",
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to allocation config",
    )
    args = parser.parse_args()

    spot_capital = args.capital * args.spot_pct
    futures_capital = args.capital * args.futures_pct

    # Bear config loaded per-asset inside the loop (bear_short_btc, bear_short_eth, etc.)
    use_optimized = args.use_optimized_bear

    print("=" * 80)
    print("COMBINED HYBRID BACKTEST")
    print(f"  MLP Direction (Spot/Long) + Bear Short (Futures/Short)")
    print("=" * 80)
    print(f"Assets:     {', '.join(args.assets)}")
    print(f"Period:     {args.start_date} to {args.end_date}")
    print(f"Timeframe:  {args.timeframe}")
    print(f"Capital:    ${args.capital:,.0f} total")
    print(f"  Spot:     ${spot_capital:,.0f} ({args.spot_pct*100:.0f}%)")
    print(f"  Futures:  ${futures_capital:,.0f} ({args.futures_pct*100:.0f}%)")
    print("=" * 80)

    # Per-asset spot capital split evenly
    n_assets = len(args.assets)
    per_asset_spot = spot_capital / n_assets
    per_asset_futures = futures_capital / n_assets

    all_spot_results = {}
    all_bear_results = {}
    all_combined_eq = []

    for asset in args.assets:
        if asset not in ASSET_DB:
            print(f"\nWARNING: Unknown asset {asset}, skipping")
            continue

        db_rel, symbol = ASSET_DB[asset]
        db_path = str(PROJECT_ROOT / db_rel)

        print(f"\n{'─'*80}")
        print(f"  {asset}")
        print(f"{'─'*80}")

        # Load data once for both strategies
        df = load_data(db_path, args.timeframe, args.start_date, args.end_date, exchange="binance")
        if df.empty:
            print(f"  No data for {asset}")
            continue
        print(f"  Loaded {len(df):,} candles")

        # --- MLP Direction (Spot) ---
        print(f"  Running MLP Direction (spot, ${per_asset_spot:,.0f})...")
        spot_results = run_mlp_backtest(asset, df, per_asset_spot, args.config)
        spot_eq = spot_results.get("equity_curve", pd.DataFrame())

        if spot_results and spot_results.get("total_trades", 0) > 0:
            spot_metrics = compute_metrics(spot_eq, args.timeframe)
            all_spot_results[asset] = (spot_results, spot_metrics)
            print_strategy_summary(f"MLP Direction ({asset})", spot_results, spot_metrics)
        else:
            spot_metrics = {"sharpe": 0, "mdd": 0, "cagr": 0}
            # Create flat equity curve for combination
            if not df.empty:
                spot_eq = pd.DataFrame({
                    "timestamp": df["timestamp"],
                    "total_equity": per_asset_spot,
                })
            print(f"  MLP Direction ({asset}): No trades (model may not exist)")

        # --- Bear Short (Futures) ---
        bear_config = load_bear_config(args.config, asset)
        if use_optimized:
            bear_config = load_optimized_bear_config(bear_config)
        exit_p = bear_config.get("exit", {}).get("params", {})
        entry_p = bear_config.get("entry", {}).get("params", {})
        print(
            f"  Running Bear Short (futures, ${per_asset_futures:,.0f}, "
            f"SL={exit_p.get('stop_loss_pct', '?')}%, TP={exit_p.get('take_profit_pct', '?')}%)..."
        )
        bear_results = run_bear_short_backtest(asset, df, per_asset_futures, bear_config)
        bear_eq = bear_results.get("equity_curve", pd.DataFrame())

        if bear_results and bear_results.get("total_trades", 0) > 0:
            bear_metrics = compute_metrics(bear_eq, args.timeframe)
            all_bear_results[asset] = (bear_results, bear_metrics)
            print_strategy_summary(f"Bear Short ({asset})", bear_results, bear_metrics)
        else:
            bear_metrics = {"sharpe": 0, "mdd": 0, "cagr": 0}
            if not df.empty:
                bear_eq = pd.DataFrame({
                    "timestamp": df["timestamp"],
                    "total_equity": per_asset_futures,
                })
            print(f"  Bear Short ({asset}): No trades")

        # Combine equity curves for this asset
        combined = combine_equity_curves(spot_eq, bear_eq)
        if not combined.empty:
            combined["asset"] = asset
            all_combined_eq.append(combined)

            # Per-asset combined metrics
            asset_total_capital = per_asset_spot + per_asset_futures
            combined_metrics = compute_metrics(
                combined[["timestamp", "total_equity"]], args.timeframe
            )
            combined_return = (
                (combined["total_equity"].iloc[-1] - asset_total_capital)
                / asset_total_capital
                * 100
            )
            spot_trades = spot_results.get("total_trades", 0) if spot_results else 0
            bear_trades = bear_results.get("total_trades", 0) if bear_results else 0
            print(
                f"  {'Combined '+asset:<30} Return={combined_return:+8.2f}%  "
                f"CAGR={combined_metrics.get('cagr',0):+6.2f}%  "
                f"Trades={spot_trades+bear_trades:>4}  "
                f"Sharpe={combined_metrics.get('sharpe',0):+6.2f}  "
                f"MDD={combined_metrics.get('mdd',0):>7.2f}%"
            )

    # ═══════════════════════════════════════════════════════════════
    # PORTFOLIO SUMMARY
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'═'*80}")
    print("PORTFOLIO SUMMARY")
    print(f"{'═'*80}")

    # Build full portfolio equity curve
    if all_combined_eq:
        # Sum all asset equity curves by timestamp
        all_dfs = []
        for eq_df in all_combined_eq:
            all_dfs.append(
                eq_df[["timestamp", "total_equity"]].rename(
                    columns={"total_equity": f"eq_{eq_df['asset'].iloc[0]}"}
                )
            )

        portfolio = all_dfs[0]
        for extra in all_dfs[1:]:
            portfolio = pd.merge(portfolio, extra, on="timestamp", how="outer")
        portfolio = portfolio.sort_values("timestamp")

        # Fill and sum
        eq_cols = [c for c in portfolio.columns if c.startswith("eq_")]
        for col in eq_cols:
            portfolio[col] = portfolio[col].ffill().bfill()
        portfolio["total_equity"] = portfolio[eq_cols].sum(axis=1)

        portfolio_metrics = compute_metrics(
            portfolio[["timestamp", "total_equity"]], args.timeframe
        )
        final_equity = portfolio["total_equity"].iloc[-1]
        total_return = (final_equity - args.capital) / args.capital * 100

        total_spot_trades = sum(
            r.get("total_trades", 0) for r, _ in all_spot_results.values()
        )
        total_bear_trades = sum(
            r.get("total_trades", 0) for r, _ in all_bear_results.values()
        )

        print(f"\n  Initial Capital:   ${args.capital:>12,.2f}")
        print(f"  Final Equity:      ${final_equity:>12,.2f}")
        print(f"  Total Return:      {total_return:>+11.2f}%")
        print(f"  CAGR:              {portfolio_metrics.get('cagr', 0):>+11.2f}%")
        print(f"  Max Drawdown:      {portfolio_metrics.get('mdd', 0):>11.2f}%")
        print(f"  Sharpe Ratio:      {portfolio_metrics.get('sharpe', 0):>+11.2f}")
        print(f"  Spot Trades:       {total_spot_trades:>11}")
        print(f"  Futures Trades:    {total_bear_trades:>11}")
        print(f"  Total Trades:      {total_spot_trades + total_bear_trades:>11}")

        # Strategy breakdown table
        print(f"\n{'─'*80}")
        print("PER-STRATEGY BREAKDOWN")
        print(f"{'─'*80}")
        print(
            f"  {'Strategy':<30} {'Return%':>10} {'CAGR%':>8} {'Trades':>7} "
            f"{'WR%':>7} {'Sharpe':>8} {'MDD%':>9}"
        )
        print(f"  {'-'*78}")

        for asset in args.assets:
            if asset in all_spot_results:
                r, m = all_spot_results[asset]
                print(
                    f"  {'MLP ' + asset + ' (spot)':<30} "
                    f"{r.get('total_return', 0):>+10.2f} "
                    f"{m.get('cagr', 0):>+8.2f} "
                    f"{r.get('total_trades', 0):>7} "
                    f"{r.get('win_rate', 0)*100:>7.1f} "
                    f"{m.get('sharpe', 0):>+8.2f} "
                    f"{m.get('mdd', 0):>9.2f}"
                )
            if asset in all_bear_results:
                r, m = all_bear_results[asset]
                print(
                    f"  {'Bear ' + asset + ' (futures)':<30} "
                    f"{r.get('total_return', 0):>+10.2f} "
                    f"{m.get('cagr', 0):>+8.2f} "
                    f"{r.get('total_trades', 0):>7} "
                    f"{r.get('win_rate', 0)*100:>7.1f} "
                    f"{m.get('sharpe', 0):>+8.2f} "
                    f"{m.get('mdd', 0):>9.2f}"
                )

        # Year-by-year for portfolio
        if args.by_year:
            print(f"\n{'─'*80}")
            print("PORTFOLIO YEAR-BY-YEAR")
            print_yearly_table(portfolio[["timestamp", "total_equity"]])

    else:
        print("  No results to combine.")

    print()


if __name__ == "__main__":
    main()
