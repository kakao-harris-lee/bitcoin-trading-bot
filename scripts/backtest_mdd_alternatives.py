#!/usr/bin/env python3
"""Backtest alternative MDD improvement approaches.

Tests configurations that reduce MDD without sacrificing returns as much.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.backtester import Backtester
from core.data_loader import DataLoader
from trading.indicators import add_all_indicators
from trading.strategies.components.strategy_factory import StrategyFactory
from scripts.backtest_regime_compare import RegimeTrackingAdapter
from scripts.backtest._common import compute_metrics


def load_data(db_path: str, timeframe: str, start: str, end: str):
    """Load data using DataLoader."""
    with DataLoader(db_path, exchange="binance") as loader:
        return loader.load_timeframe(timeframe, start, end)


def run_backtest(df, strategy_name, config, regime_version, capital, fee_rate, slippage):
    """Run backtest with given config."""
    factory = StrategyFactory()
    adapter = RegimeTrackingAdapter(
        factory,
        strategy_name=strategy_name,
        config=config,
        regime_version=regime_version,
    )
    backtester = Backtester(
        initial_capital=capital,
        fee_rate=fee_rate,
        slippage=slippage,
        min_order_amount=10,
    )
    results = backtester.run(df, adapter, {})
    return results, adapter


def print_results(name, results, adapter, timeframe):
    """Print formatted results."""
    metrics = compute_metrics(results.get("equity_curve"), timeframe)

    trades = results.get("trades", [])
    n_trades = len(trades)
    win_rate = results.get("win_rate", 0.0)
    avg_profit = results.get("avg_profit", 0.0)
    avg_loss = results.get("avg_loss", 0.0)
    profit_factor = results.get("profit_factor", 0.0)

    print(f"\n{'='*60}")
    print(f" {name}")
    print("="*60)
    print(f" Trades:          {n_trades}")
    print(f" Win Rate:        {win_rate*100:.1f}%")
    print(f" Total Return:    {metrics['total_return']:+.2f}%")
    print(f" Sharpe Ratio:    {metrics['sharpe']:.2f}")
    print(f" Max Drawdown:    {metrics['mdd']:.2f}%")

    return {
        "name": name,
        "trades": n_trades,
        "win_rate": win_rate,
        "return_pct": metrics["total_return"],
        "sharpe": metrics["sharpe"],
        "mdd": metrics["mdd"],
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest MDD improvement alternatives")
    parser.add_argument("--strategy", default="v35_long", help="Strategy name")
    parser.add_argument("--timeframe", default="minute60", help="Timeframe")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital")
    parser.add_argument("--start", default="2024-01-01", help="Start date")
    parser.add_argument("--end", default="2025-12-31", help="End date")
    args = parser.parse_args()

    # Load data
    db_path = "data/binance_bitcoin.db"
    print(f"Loading data: {db_path} [{args.timeframe}] {args.start} -> {args.end}")
    df = load_data(db_path, args.timeframe, args.start, args.end)
    if df.empty:
        raise SystemExit("No data found for the requested range.")
    print(f"Loaded {len(df):,} candles. Computing indicators...")
    df = add_all_indicators(df.copy())

    fee_rate = 0.0005
    slippage = 0.0004

    # Base config (Hybrid - best performing from regime comparison)
    base_config = {
        "regime_persistence": 2,
        "bbw_block_threshold": 20,
        "volume_block_ratio": 0.7,
        "volume_boost_ratio": 1.2,
        "entry": {"class": "V35EntryStrategy"},
        "exit": {"class": "V35TrailingExitStrategy"},
    }

    # === ALTERNATIVE 1: Moderate tighter stop (1.8% vs 1.5%) ===
    # Less aggressive than 1.5%, still tighter than 2.1%
    moderate_stop_config = {
        **base_config,
        "custom_stop_loss_pct": 1.8,
    }

    # === ALTERNATIVE 2: 1.9% stop (even gentler) ===
    gentle_stop_config = {
        **base_config,
        "custom_stop_loss_pct": 1.9,
    }

    # === ALTERNATIVE 3: Cooling period only (no tighter stop) ===
    # After 3 consecutive losses, pause for 6 bars
    cooling_only_config = {
        **base_config,
        "max_consecutive_losses": 3,
        "cooling_period": 6,
    }

    # === ALTERNATIVE 4: Volatility filter enabled ===
    volatility_filter_config = {
        **base_config,
        "volatility_filter": True,
        "volatility_threshold": 3.0,  # Skip entries when ATR% > 3%
    }

    # === ALTERNATIVE 5: Stop 1.8% + cooling period ===
    stop_and_cooling_config = {
        **base_config,
        "custom_stop_loss_pct": 1.8,
        "max_consecutive_losses": 3,
        "cooling_period": 4,  # Shorter cooling
    }

    # === ALTERNATIVE 6: Stop 1.9% + cooling period ===
    gentle_stop_cooling_config = {
        **base_config,
        "custom_stop_loss_pct": 1.9,
        "max_consecutive_losses": 4,  # More tolerance
        "cooling_period": 3,  # Shorter cooling
    }

    # === ALTERNATIVE 7: Original Hybrid+MDD (1.5% stop, 3 loss cooling) ===
    original_hybrid_mdd_config = {
        **base_config,
        "custom_stop_loss_pct": 1.5,
        "max_consecutive_losses": 3,
        "cooling_period": 6,
        "volatility_filter": False,
    }

    all_stats = []

    # Run baseline
    print("\n" + "="*60)
    print(" Running BASELINE (Hybrid, no MDD changes)...")
    print("="*60)
    results, adapter = run_backtest(
        df, args.strategy, base_config, "hybrid", args.capital, fee_rate, slippage
    )
    stats = print_results("Baseline (Hybrid)", results, adapter, args.timeframe)
    all_stats.append(stats)
    baseline_mdd = stats["mdd"]
    baseline_return = stats["return_pct"]

    # Run alternatives
    configs = [
        ("Stop 1.8%", moderate_stop_config),
        ("Stop 1.9%", gentle_stop_config),
        ("Cooling Only (3 loss/6 bar)", cooling_only_config),
        ("Volatility Filter", volatility_filter_config),
        ("Stop 1.8% + Cooling", stop_and_cooling_config),
        ("Stop 1.9% + Cooling", gentle_stop_cooling_config),
        ("Original Hybrid+MDD (1.5%)", original_hybrid_mdd_config),
    ]

    for name, config in configs:
        print(f"\n{'='*60}")
        print(f" Running {name}...")
        print("="*60)
        results, adapter = run_backtest(
            df, args.strategy, config, "hybrid", args.capital, fee_rate, slippage
        )
        stats = print_results(name, results, adapter, args.timeframe)
        all_stats.append(stats)

    # Summary comparison
    print("\n" + "="*70)
    print(" MDD IMPROVEMENT ALTERNATIVES - SUMMARY")
    print("="*70)
    print(f" {'Variant':<28} {'MDD':>8} {'Δ MDD':>8} {'Return%':>10} {'Δ Ret':>8} {'Sharpe':>7}")
    print("-" * 80)

    for s in all_stats:
        mdd_delta = baseline_mdd - s["mdd"]  # Positive = improvement
        ret_delta = s["return_pct"] - baseline_return
        print(f" {s['name']:<28} {s['mdd']:>7.1f}% {mdd_delta:>+7.1f}% {s['return_pct']:>9.2f}% {ret_delta:>+7.2f}% {s['sharpe']:>6.2f}")

    # Analysis
    print("\n" + "-"*70)
    print(" ANALYSIS:")

    # Best MDD with acceptable return loss (< 5%)
    acceptable_5 = [s for s in all_stats[1:] if s["return_pct"] >= baseline_return - 5]
    if acceptable_5:
        best_mdd_5 = min(acceptable_5, key=lambda x: x["mdd"])
        mdd_imp = (baseline_mdd - best_mdd_5["mdd"]) / baseline_mdd * 100
        print(f"\n   Best MDD (return loss <5%): {best_mdd_5['name']}")
        print(f"     MDD: {best_mdd_5['mdd']:.1f}% (improvement: {mdd_imp:.1f}%)")
        print(f"     Return: {best_mdd_5['return_pct']:.2f}%")

    # Best MDD with acceptable return loss (< 10%)
    acceptable_10 = [s for s in all_stats[1:] if s["return_pct"] >= baseline_return - 10]
    if acceptable_10:
        best_mdd_10 = min(acceptable_10, key=lambda x: x["mdd"])
        mdd_imp = (baseline_mdd - best_mdd_10["mdd"]) / baseline_mdd * 100
        print(f"\n   Best MDD (return loss <10%): {best_mdd_10['name']}")
        print(f"     MDD: {best_mdd_10['mdd']:.1f}% (improvement: {mdd_imp:.1f}%)")
        print(f"     Return: {best_mdd_10['return_pct']:.2f}%")

    # 20% MDD improvement check
    print("\n" + "-"*70)
    print(" 20% MDD IMPROVEMENT CHECK:")
    print(f" {'Variant':<28} {'MDD Imp%':>10} {'Status':>10} {'Ret Δ':>10}")
    print("-" * 60)

    for s in all_stats[1:]:
        mdd_imp_pct = (baseline_mdd - s["mdd"]) / baseline_mdd * 100
        ret_delta = s["return_pct"] - baseline_return
        if mdd_imp_pct >= 20:
            status = "✓ PASS"
        elif mdd_imp_pct >= 10:
            status = "~ CLOSE"
        else:
            status = "✗ FAIL"
        ret_status = "✓ OK" if ret_delta >= -5 else "✗ HIGH COST"
        print(f" {s['name']:<28} {mdd_imp_pct:>9.1f}% {status:>10} {ret_delta:>+9.2f}% {ret_status}")

    # Recommendation
    print("\n" + "="*70)
    print(" RECOMMENDATION:")
    print("="*70)

    # Find best trade-off
    best_tradeoff = None
    best_score = -999
    for s in all_stats[1:]:
        mdd_imp_pct = (baseline_mdd - s["mdd"]) / baseline_mdd * 100
        ret_delta = s["return_pct"] - baseline_return
        # Score: MDD improvement % - (return loss % * 2)
        # Penalize return loss more heavily
        score = mdd_imp_pct - (max(0, -ret_delta) * 2)
        if score > best_score:
            best_score = score
            best_tradeoff = s

    if best_tradeoff:
        mdd_imp = (baseline_mdd - best_tradeoff["mdd"]) / baseline_mdd * 100
        ret_delta = best_tradeoff["return_pct"] - baseline_return
        print(f"\n   Best Trade-off: {best_tradeoff['name']}")
        print(f"   - MDD: {best_tradeoff['mdd']:.1f}% ({mdd_imp:+.1f}% improvement)")
        print(f"   - Return: {best_tradeoff['return_pct']:.2f}% ({ret_delta:+.2f}% vs baseline)")
        print(f"   - Sharpe: {best_tradeoff['sharpe']:.2f}")


if __name__ == "__main__":
    main()
