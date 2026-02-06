#!/usr/bin/env python3
"""V35 Strategy Diagnostic Analysis.

Runs detailed backtests capturing per-trade data including:
- Entry/exit reasons
- Trade duration
- Regime at entry
- P&L distribution
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import numpy as np
from collections import Counter, defaultdict
from core.data_loader import DataLoader
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components import StrategyFactory
from trading.indicators import add_all_indicators


def load_data(symbol="BTC"):
    """Load full data range with indicators."""
    db_map = {
        "BTC": "data/binance_bitcoin.db",
        "ETH": "data/binance_ethereum.db",
        "SOL": "data/binance_solana.db",
    }
    db_path = project_root / db_map.get(symbol, db_map["BTC"])
    loader = DataLoader(db_path=str(db_path))
    df = loader.load_timeframe(
        timeframe="minute60", start_date="2020-01-01", end_date="2026-12-31"
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = add_all_indicators(df)
    return df


def run_diagnostic_backtest(df, strategy_name, config, symbol="BTC"):
    """Run backtest with full trade capture."""
    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name=strategy_name,
        config=config,
    )
    adapter.symbol = symbol

    market = factory.get_market(strategy_name)
    backtester = Backtester(
        initial_capital=10_000,
        fee_rate=0.001,  # spot
        slippage=0.0004,
        market="spot",
    )

    # Run with CSV logging for detailed per-candle data
    results = backtester.run(
        df, adapter,
        csv_log=True,
        csv_log_dir=str(project_root / "logs" / "v35_diagnostic"),
        strategy_name=strategy_name,
        symbol=symbol,
    )

    return results, adapter


def analyze_trades(results, strategy_name):
    """Analyze per-trade performance patterns."""
    trades = results.get("trades", [])
    if not trades:
        print(f"  No trades for {strategy_name}")
        return

    print(f"\n{'='*70}")
    print(f"  {strategy_name} - Trade-Level Analysis")
    print(f"{'='*70}")

    # Basic stats
    closed = [t for t in trades if t.exit_time is not None]
    wins = [t for t in closed if t.profit_loss and t.profit_loss > 0]
    losses = [t for t in closed if t.profit_loss and t.profit_loss <= 0]

    print(f"\n  Total Trades: {len(closed)}")
    print(f"  Winners: {len(wins)} ({len(wins)/len(closed)*100:.1f}%)")
    print(f"  Losers:  {len(losses)} ({len(losses)/len(closed)*100:.1f}%)")

    # P&L distribution
    pnls_pct = [t.profit_loss_pct for t in closed if t.profit_loss_pct is not None]
    if pnls_pct:
        pnls_arr = np.array(pnls_pct)
        print(f"\n  P&L Distribution (%):")
        print(f"    Mean:   {np.mean(pnls_arr):+.3f}%")
        print(f"    Median: {np.median(pnls_arr):+.3f}%")
        print(f"    StdDev: {np.std(pnls_arr):.3f}%")
        print(f"    Min:    {np.min(pnls_arr):+.3f}%")
        print(f"    Max:    {np.max(pnls_arr):+.3f}%")

        # P&L buckets
        buckets = [(-100, -5), (-5, -2), (-2, -1), (-1, 0), (0, 1), (1, 2), (2, 5), (5, 100)]
        print(f"\n  P&L Buckets:")
        for lo, hi in buckets:
            count = sum(1 for p in pnls_arr if lo <= p < hi)
            pct = count / len(pnls_arr) * 100
            bar = "#" * int(pct / 2)
            print(f"    [{lo:+5.0f}%, {hi:+5.0f}%): {count:4d} ({pct:5.1f}%) {bar}")

    # Win/Loss magnitude
    if wins:
        avg_win = np.mean([t.profit_loss_pct for t in wins])
        print(f"\n  Avg Win:  {avg_win:+.3f}%")
    if losses:
        avg_loss = np.mean([t.profit_loss_pct for t in losses])
        print(f"  Avg Loss: {avg_loss:+.3f}%")

    if wins and losses:
        ratio = abs(np.mean([t.profit_loss_pct for t in wins])) / abs(np.mean([t.profit_loss_pct for t in losses]))
        print(f"  Win/Loss Ratio: {ratio:.2f}x")

    # Trade duration
    durations = []
    for t in closed:
        if t.entry_time and t.exit_time:
            if hasattr(t.entry_time, 'timestamp') and hasattr(t.exit_time, 'timestamp'):
                dur_hours = (t.exit_time - t.entry_time).total_seconds() / 3600
            else:
                dur_hours = 0
            durations.append(dur_hours)

    if durations:
        dur_arr = np.array(durations)
        print(f"\n  Trade Duration (hours):")
        print(f"    Mean:   {np.mean(dur_arr):.1f}h ({np.mean(dur_arr)/24:.1f}d)")
        print(f"    Median: {np.median(dur_arr):.1f}h ({np.median(dur_arr)/24:.1f}d)")
        print(f"    Min:    {np.min(dur_arr):.1f}h")
        print(f"    Max:    {np.max(dur_arr):.1f}h ({np.max(dur_arr)/24:.1f}d)")

        # Duration vs P&L correlation
        if len(durations) == len(pnls_pct):
            corr = np.corrcoef(dur_arr, pnls_arr)[0, 1]
            print(f"    Duration-PnL Correlation: {corr:.3f}")

    # Exit reason analysis
    print(f"\n  Exit Reasons:")
    exit_reasons = Counter()
    reason_pnl = defaultdict(list)
    for t in closed:
        reason = t.reason.split(" -> ")[1] if " -> " in t.reason else t.reason
        # Categorize
        if "stop" in reason.lower() or "stoploss" in reason.lower():
            cat = "STOP_LOSS"
        elif "take_profit" in reason.lower() or "tp_" in reason.lower():
            cat = "TAKE_PROFIT"
        elif "trail" in reason.lower():
            cat = "TRAILING_STOP"
        elif "macd" in reason.lower() or "dead_cross" in reason.lower():
            cat = "MACD_EXIT"
        elif "drawdown" in reason.lower():
            cat = "DRAWDOWN"
        elif "ema" in reason.lower() or "ma120" in reason.lower():
            cat = "MA_EXIT"
        elif "regime" in reason.lower():
            cat = "REGIME_CHANGE"
        else:
            cat = reason[:40] if reason else "UNKNOWN"
        exit_reasons[cat] += 1
        if t.profit_loss_pct:
            reason_pnl[cat].append(t.profit_loss_pct)

    for reason, count in exit_reasons.most_common():
        pct = count / len(closed) * 100
        avg_pnl = np.mean(reason_pnl[reason]) if reason_pnl[reason] else 0
        total_pnl = np.sum(reason_pnl[reason]) if reason_pnl[reason] else 0
        print(f"    {reason:<25s}: {count:4d} ({pct:5.1f}%)  avg={avg_pnl:+.2f}%  total={total_pnl:+.1f}%")

    # Per-year performance
    print(f"\n  Per-Year Performance:")
    year_trades = defaultdict(list)
    for t in closed:
        if hasattr(t.entry_time, 'year'):
            year_trades[t.entry_time.year].append(t)

    for year in sorted(year_trades.keys()):
        yt = year_trades[year]
        yr_wins = [t for t in yt if t.profit_loss and t.profit_loss > 0]
        yr_pnl = sum(t.profit_loss_pct for t in yt if t.profit_loss_pct)
        wr = len(yr_wins) / len(yt) * 100 if yt else 0
        print(f"    {year}: {len(yt):3d} trades, WR={wr:5.1f}%, cumPnL={yr_pnl:+.1f}%")

    # Largest wins and losses
    sorted_trades = sorted(closed, key=lambda t: t.profit_loss_pct or 0)
    print(f"\n  Top 5 Losses:")
    for t in sorted_trades[:5]:
        print(f"    {t.entry_time} -> {t.exit_time}: {t.profit_loss_pct:+.2f}%  "
              f"(${t.profit_loss:+.2f})  reason: {t.reason[:60]}")

    print(f"\n  Top 5 Wins:")
    for t in sorted_trades[-5:]:
        print(f"    {t.entry_time} -> {t.exit_time}: {t.profit_loss_pct:+.2f}%  "
              f"(${t.profit_loss:+.2f})  reason: {t.reason[:60]}")


def analyze_csv_log(strategy_name):
    """Analyze CSV log for regime-level insights."""
    log_dir = project_root / "logs" / "v35_diagnostic"
    csv_files = list(log_dir.glob(f"{strategy_name}*.csv"))
    if not csv_files:
        print(f"  No CSV log found for {strategy_name}")
        return

    csv_path = csv_files[0]
    df_log = pd.read_csv(csv_path)

    if "regime" not in df_log.columns or "signal" not in df_log.columns:
        print(f"  CSV log missing regime/signal columns")
        return

    # Entry signals by regime
    entries = df_log[df_log["signal"] == "buy"]
    if len(entries) > 0:
        print(f"\n  Entry Signals by Regime:")
        regime_counts = entries["regime"].value_counts()
        for regime, count in regime_counts.items():
            print(f"    {regime}: {count} entries")


if __name__ == "__main__":
    print("Loading BTC data...")
    df = load_data("BTC")
    print(f"Loaded {len(df)} candles ({df['timestamp'].min()} to {df['timestamp'].max()})")

    strategies = {
        "v35_classic_wide": {
            "market": "spot",
            "position_pct": 0.02,
        },
        "tuned_v35_long_v2_core_overlay_v2": {
            "market": "spot",
            "position_pct": 0.02,
        },
    }

    for name, config in strategies.items():
        print(f"\nRunning {name}...")
        results, adapter = run_diagnostic_backtest(df, name, config)

        print(f"\n  Summary: Return={results['total_return']:+.2f}%  "
              f"Trades={results['total_trades']}  "
              f"WR={results['win_rate']*100:.1f}%  "
              f"Sharpe={results['sharpe_ratio']:.2f}  "
              f"MDD={results['max_drawdown_pct']:.2f}%  "
              f"PF={results['profit_factor']:.2f}")

        analyze_trades(results, name)
        analyze_csv_log(name)

    print("\n\nDone. CSV logs saved to logs/v35_diagnostic/")
