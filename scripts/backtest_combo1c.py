#!/usr/bin/env python3
"""
Backtest Combo1-C Strategy (VBS + LSTM + RF).

This strategy uses hourly (minute60) data and combines:
1. Volatility Breakout (VBS)
2. LSTM price prediction
3. RandomForest confidence filtering
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
from datetime import datetime

from core.backtester import Backtester
from core.data_loader import DataLoader
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components import StrategyFactory
from trading.indicators import add_all_indicators


def main():
    print("=" * 60)
    print("COMBO1-C BACKTEST (VBS + LSTM + RF)")
    print("=" * 60)

    try:
        # 1. Load Data (hourly for LSTM)
        print("\n[1/5] Loading data...")
        loader = DataLoader()

        if not loader.db_path.exists():
            print(f"ERROR: DB not found at {loader.db_path}")
            return

        # Use minute60 (hourly) for Combo1-C
        df = loader.load_timeframe(
            timeframe="minute60",
            start_date="2024-01-01",
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "target_price",
                "breakout_signal",
            ],
        )

        if df.empty:
            print("No data found!")
            return

        print(f"  Loaded {len(df):,} rows (hourly data)")
        print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

        # 2. Add Indicators
        print("\n[2/5] Calculating indicators...")
        df = add_all_indicators(df)

        # 3. Setup Strategy
        print("\n[3/5] Initializing Combo1-C strategy...")

        # Combo1-C config (new format with entry/exit blocks)
        config = {
            "entry": {
                "class": "Combo1CEntryStrategy",
                "params": {
                    "breakout_k": 0.5,
                    "rf_confidence_threshold": 0.6,
                    "require_up_close": True,
                    "position_size": 0.01,
                }
            },
            "exit": {
                "class": "Combo1CExitStrategy",
                "params": {
                    "exit_at_day_close": True,
                    "emergency_stop_loss_pct": 5.0,
                }
            },
            "market": "futures",
            "leverage": 3,
        }

        factory = StrategyFactory(redis=None)
        adapter = ComponentStrategyAdapter(factory, "combo1c", config)

        # 4. Run Backtest
        print("\n[4/5] Running backtest...")
        backtester = Backtester(initial_capital=10000.0, min_order_amount=10.0)  # USD, not KRW
        results = backtester.run(df, adapter)

        # 5. Report
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS: Combo1-C (VBS + LSTM + RF)")
        print("=" * 60)
        print(f"Initial Capital: $10,000")
        print(f"Final Capital:   ${results.get('final_capital', 10000):.2f}")
        print(f"Total Return:    {results['total_return']:.2f}%")
        print(f"Total Trades:    {results['total_trades']}")

        if results['total_trades'] > 0:
            print(f"Win Rate:        {results['win_rate']*100:.1f}%")
            print(f"Profit Factor:   {results['profit_factor']:.2f}" if results['profit_factor'] else "N/A")

            # Calculate additional metrics
            trades = results.get('trades', [])
            if trades:
                profits = [t.profit_loss_pct for t in trades if t.profit_loss_pct and t.profit_loss_pct > 0]
                losses = [t.profit_loss_pct for t in trades if t.profit_loss_pct and t.profit_loss_pct < 0]

                if profits:
                    print(f"Avg Win:         {sum(profits)/len(profits):.2f}%")
                if losses:
                    print(f"Avg Loss:        {sum(losses)/len(losses):.2f}%")

        print("=" * 60)

        # Show sample trades
        if results.get('trades'):
            print("\nSample Trades (last 10):")
            print("-" * 60)
            for t in results['trades'][-10:]:
                entry_date = t.entry_time.strftime('%Y-%m-%d %H:%M') if hasattr(t.entry_time, 'strftime') else str(t.entry_time)[:16]
                exit_date = t.exit_time.strftime('%Y-%m-%d %H:%M') if t.exit_time and hasattr(t.exit_time, 'strftime') else 'OPEN'
                pnl = t.profit_loss_pct if t.profit_loss_pct else 0
                emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "⏳"

                print(f"  {emoji} {entry_date} -> {exit_date} | "
                      f"Entry: ${t.entry_price:,.0f} | PnL: {pnl:+.2f}%")

        # Get strategy stats
        if hasattr(adapter, 'entry_strategy') and hasattr(adapter.entry_strategy, 'get_stats'):
            print("\n\nEntry Strategy Stats:")
            print("-" * 40)
            for k, v in adapter.entry_strategy.get_stats().items():
                print(f"  {k}: {v}")

            print("\nRejection Stats:")
            for k, v in adapter.entry_strategy.get_rejection_stats().items():
                print(f"  {k}: {v}")

            # Show prediction logs for debugging
            if hasattr(adapter.entry_strategy, 'get_prediction_logs'):
                logs = adapter.entry_strategy.get_prediction_logs()
                if logs:
                    print(f"\nPrediction Logs (last 10 of {len(logs)}):")
                    print("-" * 60)
                    for log in logs[-10:]:
                        pred = log.get('predicted_price', 0)
                        target = log.get('target_price', 0)
                        conf = log.get('rf_confidence', 0)
                        status = "✅" if pred > target and conf > 0.6 else "❌"
                        print(f"  {status} Price: {log.get('current_price', 0):,.0f} | "
                              f"Target: {target:,.0f} | Pred: {pred:,.0f} | "
                              f"Conf: {conf:.1%}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nCRITICAL ERROR: {e}")


if __name__ == "__main__":
    main()
