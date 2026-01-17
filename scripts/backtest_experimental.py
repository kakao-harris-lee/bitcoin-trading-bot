#!/usr/bin/env python3
"""
Backtest Experimental Strategy using Component Architecture.

This script demonstrates how to use the ComponentStrategyAdapter to bridge
the new StrategyFactory components with the existing Backtester.
"""
import sys
import json
import asyncio
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.backtester import Backtester
from core.data_loader import DataLoader
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components import StrategyFactory
from trading.indicators import add_all_indicators

def load_config(strategy_name: str) -> dict:
    """Load strategy config from JSON file."""
    root = Path(__file__).parent.parent
    config_path = root / "config" / "strategies" / f"{strategy_name}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path) as f:
        return json.load(f)

def main():
    try:
        # 1. Load Data
        print("Loading data...")
        loader = DataLoader() # Defaults to binance_bitcoin.db

        # Check if DB exists
        if not loader.db_path.exists():
            print(f"ERROR: DB not found at {loader.db_path}")
            return

        # Using 'day' timeframe as V35 is a daily strategy
        df = loader.load_timeframe(timeframe="day", start_date="2023-01-01")

        if df.empty:
            print("No data found!")
            return

        print(f"Loaded {len(df)} rows.")

        # 2. Add Indicators
        print("Calculating indicators...")
        df = add_all_indicators(df)

        # 3. Setup Strategy via Factory
        strategy_name = "v35_experimental"
        print(f"Initializing strategy: {strategy_name}")
        config = load_config(strategy_name)

        factory = StrategyFactory(redis=None) # No redis needed for backtest

        # 4. Create Adapter
        adapter = ComponentStrategyAdapter(factory, strategy_name, config)

        # 5. Run Backtest
        print("Running backtest...")
        backtester = Backtester(initial_capital=10000.0) # USD
        results = backtester.run(df, adapter)

        # 6. Report
        print("\n" + "="*50)
        print(f"BACKTEST RESULTS: {strategy_name}")
        print("="*50)
        print(f"Total Return: {results['total_return']:.2f}%")
        print(f"Trades: {results['total_trades']}")
        print(f"Win Rate: {results['win_rate']*100 if results['total_trades'] > 0 else 0:.2f}%")
        print(f"Profit Factor: {results['profit_factor'] if results['profit_factor'] else 0.0:.2f}")
        # print(f"Max Drawdown: {results['max_drawdown']:.2f}%") # Unavailable in current backtester
        print("="*50)

        # Show last few trades
        if results['trades']:
            print("\nLast 5 Trades:")
            for t in results['trades'][-5:]:
                entry_date = t.entry_time.date() if hasattr(t.entry_time, 'date') else t.entry_time
                exit_date = t.exit_time.date() if t.exit_time and hasattr(t.exit_time, 'date') else 'OPEN'

                print(f"{entry_date} {t.side} @ {t.entry_price:.2f} -> "
                      f"{exit_date} "
                      f"Result: {t.profit_loss_pct if t.profit_loss_pct else 0:.2f}%")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    main()
