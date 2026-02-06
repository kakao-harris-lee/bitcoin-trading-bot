#!/usr/bin/env python3
"""
Combined Hedge Backtest: MLP Direction + Drawdown-Triggered Bear Short

Unlike combined_hybrid.py (independent capital split), this backtester
shares equity tracking between MLP and bear short. The PortfolioHedgeManager
monitors combined drawdown and toggles bear short on/off.

Capital model:
    - MLP Direction: 100% spot capital (always active, never blocked)
    - Bear Short: reserved futures hedge budget (active only during hedge mode)
    - Additive-only: MLP always trades freely, bear short toggles on/off

Usage:
    python scripts/backtest/combined_hedge.py
    python scripts/backtest/combined_hedge.py --assets BTC ETH SOL --by-year
    python scripts/backtest/combined_hedge.py --activate-dd 10 --deactivate-dd 5
    python scripts/backtest/combined_hedge.py --hedge-budget 0.20
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
from scripts.backtest.backtest_mlp import (
    MLPDirectionBacktester,
    load_strategy_config,
)
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators
from trading.risk.portfolio_hedge_manager import PortfolioHedgeManager

# Asset database paths
ASSET_DB = {
    "BTC": ("data/binance_bitcoin.db", "BTC"),
    "ETH": ("data/binance_ethereum.db", "ETH"),
    "SOL": ("data/binance_solana.db", "SOL"),
}

MLP_STRATEGY_IDS = {
    "BTC": "mlp_direction_btc",
    "ETH": "mlp_direction_eth",
    "SOL": "mlp_direction_sol",
}

BEAR_SHORT_CONFIG = {
    "market": "futures",
    "leverage": 3,
    "position_pct": 0.90,
    "dynamic_sizing": True,
    "drawdown_enabled": False,
    "stop_loss_cooldown": 0,
    "entry": {
        "class": "BearShortEntryStrategy",
        "params": {
            "volume_ratio_threshold": 1.5,
            "position_size": 0.90,
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


def load_optimized_bear_config() -> dict[str, Any]:
    """Load optimized bear short params if available."""
    opt_path = PROJECT_ROOT / "config" / "strategies" / "bear_short_optimized.json"
    if opt_path.exists():
        with open(opt_path) as f:
            opt = json.load(f)
        params = opt.get("optimized_params", {})
        config = dict(BEAR_SHORT_CONFIG)
        config["entry"] = dict(config["entry"])
        config["entry"]["params"] = dict(config["entry"]["params"])
        config["exit"] = dict(config["exit"])
        config["exit"]["params"] = dict(config["exit"]["params"])
        config["entry"]["params"]["volume_ratio_threshold"] = params.get(
            "volume_ratio_threshold", 1.5
        )
        config["exit"]["params"]["stop_loss_pct"] = params.get("stop_loss_pct", 3.0)
        config["exit"]["params"]["take_profit_pct"] = params.get(
            "take_profit_pct", 5.0
        )
        return config
    return dict(BEAR_SHORT_CONFIG)


def run_hedge_backtest(
    asset: str,
    df_raw: pd.DataFrame,
    capital: float,
    config_path: str,
    hedge_manager: PortfolioHedgeManager,
    bear_config: dict[str, Any],
    track_spot_only: bool = True,
) -> dict:
    """Run unified candle-by-candle backtest with shared equity tracking.

    Additive-only model: MLP always trades freely. Bear short toggles on/off
    based on drawdown. Hedge is purely additive protection.

    Args:
        asset: Trading symbol (BTC, ETH, SOL).
        df_raw: Raw OHLCV DataFrame.
        capital: Total capital for this asset (MLP gets 100%).
        config_path: Path to allocation.json.
        hedge_manager: Shared PortfolioHedgeManager instance.
        bear_config: Bear short strategy configuration.
        track_spot_only: Track drawdown on spot equity only (recommended).

    Returns:
        Results dict with equity curve, trades, and hedge events.
    """
    # Load MLP strategy config
    try:
        _, strategy_id, strategy_config = load_strategy_config(
            config_path=config_path,
            symbol=asset,
            mode="paper",
            strategy_id=MLP_STRATEGY_IDS.get(asset),
        )
    except ValueError:
        print(f"  WARNING: No MLP config for {asset}, skipping")
        return {}

    model_path = Path(strategy_config.get("model_path", ""))
    if not model_path.exists():
        print(f"  WARNING: Model not found at {model_path}, skipping {asset}")
        return {}

    # Prepare MLP adapter
    mlp_bt_obj = MLPDirectionBacktester(
        symbol=asset,
        config=strategy_config,
        strategy_label=strategy_id,
    )
    df = mlp_bt_obj.prepare_data(df_raw.copy())

    factory = StrategyFactory(redis=None)
    mlp_adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="mlp_direction",
        config=strategy_config,
    )
    mlp_adapter.symbol = asset
    mlp_adapter.precompute_mlp_predictions(df)

    # Prepare bear short adapter
    bear_adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="bear_short",
        config=bear_config,
    )
    bear_adapter.symbol = asset

    # Also add indicators for bear short (already done by mlp prepare_data)
    df_bear = add_all_indicators(df_raw.copy())

    # Spot backtester (MLP Direction)
    spot_bt = Backtester(
        initial_capital=capital,
        fee_rate=0.001,  # Spot 0.1%
        slippage=0.0002,
    )
    spot_bt.reset()

    # Futures backtester (Bear Short) using hedge budget
    hedge_budget = hedge_manager.hedge_budget
    futures_bt = ShortMarginBacktester(
        initial_capital=hedge_budget,
        fee_rate=0.0005,  # Futures 0.05%
        slippage=0.0002,
        min_order_amount=10,
        action_open="open_short",
        action_close="close_short",
    )

    # Candle-by-candle loop
    equity_curve = []
    hedge_events = []
    bear_activations = 0
    warmup = 200

    for i in range(len(df)):
        row = df.iloc[i]
        ts = row["timestamp"]
        price = float(row["close"])

        if price <= 0:
            continue

        # 1. Calculate equity
        spot_eq = spot_bt.cash + (spot_bt.position * price if spot_bt.position > 0 else 0.0)
        futures_eq = futures_bt._equity(price)

        # 2. Update hedge manager (track spot equity only for drawdown)
        tracking_eq = spot_eq if track_spot_only else (spot_eq + futures_eq)
        state = hedge_manager.update(tracking_eq)

        # 3. MLP Direction (ALWAYS trades freely — additive-only hedge)
        mlp_signal = {"action": "hold"}
        if i >= warmup:
            if hasattr(mlp_adapter, "update_equity"):
                mlp_adapter.update_equity(spot_eq)
            mlp_signal = mlp_adapter(df, i, {})

        # Execute MLP signal on spot backtester
        mlp_action = mlp_signal.get("action", "hold")
        mlp_fraction = mlp_signal.get("fraction", 1.0)
        if mlp_action == "buy":
            spot_bt._execute_buy(ts, price, mlp_fraction)
        elif mlp_action == "sell":
            spot_bt._execute_sell(ts, price, mlp_fraction)

        # Update spot position tracking
        if spot_bt.position > 0:
            spot_bt.position_value = spot_bt.position * price
        else:
            spot_bt.position_value = 0.0

        # 4. Bear Short (only when hedge active)
        bear_signal = {"action": "hold"}
        if i >= warmup:
            if state.mode == "hedge":
                bear_signal = bear_adapter(df_bear, i, {})
            elif futures_bt.in_short:
                # Force close when hedge deactivates
                bear_signal = {"action": "close_short"}

        bear_action = bear_signal.get("action", "hold")
        bear_fraction = min(1.0, max(0.0, float(bear_signal.get("fraction", 1.0))))
        if bear_action == "open_short":
            futures_bt._open_short(ts, price, bear_fraction)
            if not any(e.get("type") == "activate" and e.get("ts") == ts for e in hedge_events):
                bear_activations += 1
        elif bear_action == "close_short":
            futures_bt._close_short(ts, price)

        # 5. Record combined equity
        spot_eq_post = spot_bt.cash + (spot_bt.position * price if spot_bt.position > 0 else 0.0)
        futures_eq_post = futures_bt._equity(price)
        combined_post = spot_eq_post + futures_eq_post

        equity_curve.append({
            "timestamp": ts,
            "spot_equity": spot_eq_post,
            "futures_equity": futures_eq_post,
            "total_equity": combined_post,
            "hedge_mode": 1 if state.mode == "hedge" else 0,
            "drawdown_pct": state.drawdown_pct,
        })

        # Track hedge transitions
        if len(equity_curve) >= 2:
            prev_hedge = equity_curve[-2].get("hedge_mode", 0)
            curr_hedge = equity_curve[-1].get("hedge_mode", 0)
            if prev_hedge == 0 and curr_hedge == 1:
                hedge_events.append({"type": "activate", "ts": ts, "dd": state.drawdown_pct})
            elif prev_hedge == 1 and curr_hedge == 0:
                hedge_events.append({"type": "deactivate", "ts": ts, "dd": state.drawdown_pct})

    # Force close remaining positions at end
    if spot_bt.position > 0 and len(df) > 0:
        last = df.iloc[-1]
        spot_bt._execute_sell(last["timestamp"], float(last["close"]), 1.0)
    if futures_bt.in_short and len(df) > 0:
        last = df.iloc[-1]
        futures_bt._close_short(last["timestamp"], float(last["close"]))

    # Build results
    eq_df = pd.DataFrame(equity_curve) if equity_curve else pd.DataFrame()
    final_equity = eq_df["total_equity"].iloc[-1] if not eq_df.empty else capital + hedge_budget
    initial_total = capital + hedge_budget
    total_return = ((final_equity - initial_total) / initial_total) * 100

    # Collect trade stats
    spot_closed = [t for t in spot_bt.trades if t.exit_time is not None]
    futures_closed = [t for t in futures_bt.trades if t.get("exit_time") is not None]

    return {
        "initial_capital": initial_total,
        "final_capital": final_equity,
        "total_return": total_return,
        "equity_curve": eq_df,
        "spot_trades": len(spot_closed),
        "futures_trades": len(futures_closed),
        "total_trades": len(spot_closed) + len(futures_closed),
        "hedge_events": hedge_events,
        "hedge_activations": hedge_manager.activation_count,
        "spot_results": spot_bt._generate_results() if hasattr(spot_bt, '_generate_results') else {},
        "futures_results": futures_bt._generate_results(),
    }


def print_comparison_table(results: dict[str, dict], capital: float):
    """Print side-by-side comparison of backtest modes."""
    print(f"\n{'═'*90}")
    print("COMPARISON TABLE")
    print(f"{'═'*90}")
    print(
        f"  {'Mode':<25} {'Return%':>10} {'CAGR%':>8} {'Sharpe':>8} "
        f"{'MDD%':>9} {'Trades':>7} {'Hedge#':>7}"
    )
    print(f"  {'─'*84}")

    for label, res in results.items():
        eq = res.get("equity_curve")
        if eq is None or (isinstance(eq, pd.DataFrame) and eq.empty):
            continue
        if isinstance(eq, pd.DataFrame) and "total_equity" in eq.columns:
            metrics = compute_metrics(eq[["timestamp", "total_equity"]], "minute240")
        else:
            metrics = {"cagr": 0, "sharpe": 0, "mdd": 0}

        ret = res.get("total_return", 0)
        trades = res.get("total_trades", 0)
        hedges = res.get("hedge_activations", "—")

        print(
            f"  {label:<25} {ret:>+10.2f} {metrics.get('cagr', 0):>+8.2f} "
            f"{metrics.get('sharpe', 0):>+8.2f} {metrics.get('mdd', 0):>9.2f} "
            f"{trades:>7} {str(hedges):>7}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Combined Hedge Backtest: MLP Direction + Drawdown-Triggered Bear Short"
    )
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument(
        "--activate-dd",
        type=float,
        default=10.0,
        help="Activate hedge at this drawdown %% (default: 10)",
    )
    parser.add_argument(
        "--deactivate-dd",
        type=float,
        default=5.0,
        help="Deactivate hedge below this drawdown %% (default: 5)",
    )
    parser.add_argument(
        "--hedge-budget",
        type=float,
        default=0.20,
        help="Fraction of capital reserved for hedge (default: 0.20)",
    )
    parser.add_argument("--by-year", action="store_true")
    parser.add_argument(
        "--use-optimized-bear",
        action="store_true",
        help="Use Optuna-optimized bear short params",
    )
    parser.add_argument(
        "--track-combined",
        action="store_true",
        help="Track combined equity for drawdown (default: spot only)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Also run MLP-only and always-on modes for comparison",
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to allocation config",
    )
    args = parser.parse_args()

    # Per-asset capital
    n_assets = len(args.assets)
    per_asset_capital = args.capital / n_assets

    # Load bear config
    if args.use_optimized_bear:
        bear_config = load_optimized_bear_config()
    else:
        bear_config = dict(BEAR_SHORT_CONFIG)

    print("=" * 90)
    print("COMBINED HEDGE BACKTEST")
    print(f"  MLP Direction (Spot) + Drawdown-Triggered Bear Short (Futures)")
    print("=" * 90)
    print(f"Assets:          {', '.join(args.assets)}")
    print(f"Period:          {args.start_date} to {args.end_date}")
    print(f"Timeframe:       {args.timeframe}")
    print(f"Capital:         ${args.capital:,.0f} total (${per_asset_capital:,.0f}/asset)")
    print(f"Activate DD:     {args.activate_dd:.1f}%")
    print(f"Deactivate DD:   {args.deactivate_dd:.1f}%")
    print(f"Hedge Budget:    {args.hedge_budget*100:.0f}%")
    print(f"DD Tracking:     {'combined' if args.track_combined else 'spot only'}")
    print(f"Mode:            additive (MLP always trades, bear short toggles)")
    print("=" * 90)

    all_hedge_eq = []
    all_results = {}

    for asset in args.assets:
        if asset not in ASSET_DB:
            print(f"\nWARNING: Unknown asset {asset}, skipping")
            continue

        db_rel, symbol = ASSET_DB[asset]
        db_path = str(PROJECT_ROOT / db_rel)

        print(f"\n{'─'*90}")
        print(f"  {asset}")
        print(f"{'─'*90}")

        df_raw = load_data(db_path, args.timeframe, args.start_date, args.end_date, exchange="binance")
        if df_raw.empty:
            print(f"  No data for {asset}")
            continue
        print(f"  Loaded {len(df_raw):,} candles")

        # Create per-asset hedge manager
        hedge_manager = PortfolioHedgeManager(
            initial_capital=per_asset_capital,
            activate_drawdown_pct=args.activate_dd,
            deactivate_drawdown_pct=args.deactivate_dd,
            hedge_budget_pct=args.hedge_budget,
        )

        print(f"  Running hedge backtest (spot=${per_asset_capital:,.0f}, hedge_budget=${hedge_manager.hedge_budget:,.0f})...")
        results = run_hedge_backtest(
            asset=asset,
            df_raw=df_raw,
            capital=per_asset_capital,
            config_path=args.config,
            hedge_manager=hedge_manager,
            bear_config=bear_config,
            track_spot_only=not args.track_combined,
        )

        if not results:
            continue

        eq = results.get("equity_curve", pd.DataFrame())
        if not eq.empty:
            metrics = compute_metrics(eq[["timestamp", "total_equity"]], args.timeframe)
        else:
            metrics = {"cagr": 0, "sharpe": 0, "mdd": 0}

        ret = results.get("total_return", 0)
        print(
            f"  Return={ret:+.2f}%  CAGR={metrics.get('cagr', 0):+.2f}%  "
            f"Sharpe={metrics.get('sharpe', 0):+.2f}  MDD={metrics.get('mdd', 0):.2f}%"
        )
        print(
            f"  Spot trades={results.get('spot_trades', 0)}  "
            f"Futures trades={results.get('futures_trades', 0)}  "
            f"Hedge activations={results.get('hedge_activations', 0)}"
        )

        # Print hedge events
        for event in results.get("hedge_events", []):
            etype = "ACTIVATE" if event["type"] == "activate" else "DEACTIVATE"
            print(f"    {etype} at {event['ts']} (DD={event['dd']:.1f}%)")

        if not eq.empty:
            eq["asset"] = asset
            all_hedge_eq.append(eq)

        all_results[f"Hedge {asset}"] = results

    # Portfolio summary
    print(f"\n{'═'*90}")
    print("PORTFOLIO SUMMARY (HEDGE MODE)")
    print(f"{'═'*90}")

    if all_hedge_eq:
        all_dfs = []
        for eq_df in all_hedge_eq:
            asset_name = eq_df["asset"].iloc[0]
            all_dfs.append(
                eq_df[["timestamp", "total_equity"]].rename(
                    columns={"total_equity": f"eq_{asset_name}"}
                )
            )

        portfolio = all_dfs[0]
        for extra in all_dfs[1:]:
            portfolio = pd.merge(portfolio, extra, on="timestamp", how="outer")
        portfolio = portfolio.sort_values("timestamp")

        eq_cols = [c for c in portfolio.columns if c.startswith("eq_")]
        for col in eq_cols:
            portfolio[col] = portfolio[col].ffill().bfill()
        portfolio["total_equity"] = portfolio[eq_cols].sum(axis=1)

        portfolio_metrics = compute_metrics(
            portfolio[["timestamp", "total_equity"]], args.timeframe
        )
        final_equity = portfolio["total_equity"].iloc[-1]
        total_return = (final_equity - args.capital) / args.capital * 100

        total_spot = sum(r.get("spot_trades", 0) for r in all_results.values())
        total_futures = sum(r.get("futures_trades", 0) for r in all_results.values())
        total_hedges = sum(r.get("hedge_activations", 0) for r in all_results.values())

        print(f"\n  Initial Capital:   ${args.capital:>12,.2f}")
        print(f"  Final Equity:      ${final_equity:>12,.2f}")
        print(f"  Total Return:      {total_return:>+11.2f}%")
        print(f"  CAGR:              {portfolio_metrics.get('cagr', 0):>+11.2f}%")
        print(f"  Max Drawdown:      {portfolio_metrics.get('mdd', 0):>11.2f}%")
        print(f"  Sharpe Ratio:      {portfolio_metrics.get('sharpe', 0):>+11.2f}")
        print(f"  Spot Trades:       {total_spot:>11}")
        print(f"  Futures Trades:    {total_futures:>11}")
        print(f"  Hedge Activations: {total_hedges:>11}")

        if args.by_year:
            print(f"\n{'─'*90}")
            print("PORTFOLIO YEAR-BY-YEAR")
            print_yearly_table(portfolio[["timestamp", "total_equity"]])

        # Comparison mode: also run MLP-only
        if args.compare:
            print(f"\n{'─'*90}")
            print("Running MLP-only for comparison...")
            from scripts.backtest.backtest_mlp import run_backtest as run_mlp_single

            mlp_only_eq_list = []
            for asset in args.assets:
                if asset not in ASSET_DB:
                    continue
                db_rel, _ = ASSET_DB[asset]
                db_path = str(PROJECT_ROOT / db_rel)
                try:
                    _, sid, sconfig = load_strategy_config(
                        config_path=args.config,
                        symbol=asset,
                        mode="paper",
                        strategy_id=MLP_STRATEGY_IDS.get(asset),
                    )
                except ValueError:
                    continue
                mlp_res = run_mlp_single(
                    symbol=asset,
                    db_path=db_path,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    timeframe=args.timeframe,
                    initial_capital=per_asset_capital,
                    strategy_config=sconfig,
                    strategy_label=sid,
                )
                if mlp_res:
                    meq = mlp_res.get("equity_curve", pd.DataFrame())
                    if not meq.empty:
                        meq = meq.rename(columns={"total_equity": f"eq_{asset}"})
                        mlp_only_eq_list.append(meq[["timestamp", f"eq_{asset}"]])

            if mlp_only_eq_list:
                mlp_portfolio = mlp_only_eq_list[0]
                for extra in mlp_only_eq_list[1:]:
                    mlp_portfolio = pd.merge(mlp_portfolio, extra, on="timestamp", how="outer")
                mlp_portfolio = mlp_portfolio.sort_values("timestamp")
                mcols = [c for c in mlp_portfolio.columns if c.startswith("eq_")]
                for col in mcols:
                    mlp_portfolio[col] = mlp_portfolio[col].ffill().bfill()
                mlp_portfolio["total_equity"] = mlp_portfolio[mcols].sum(axis=1)

                mlp_final = mlp_portfolio["total_equity"].iloc[-1]
                mlp_return = (mlp_final - args.capital) / args.capital * 100

                comparison = {
                    "MLP Only": {
                        "equity_curve": mlp_portfolio,
                        "total_return": mlp_return,
                        "total_trades": "—",
                        "hedge_activations": "—",
                    },
                    "Hedge Mode": {
                        "equity_curve": portfolio,
                        "total_return": total_return,
                        "total_trades": total_spot + total_futures,
                        "hedge_activations": total_hedges,
                    },
                }
                print_comparison_table(comparison, args.capital)

    else:
        print("  No results to combine.")

    print()


if __name__ == "__main__":
    main()
