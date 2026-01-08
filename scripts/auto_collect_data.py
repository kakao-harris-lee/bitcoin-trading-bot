#!/usr/bin/env python3
"""
Auto data collector for bitcoin trading bot.

Runs periodically to keep database updated with latest candles.
Designed to be run from cron without interactive input.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collectors.upbit_collector import UpbitBitcoinCollector
from scripts.collectors.binance_collector import BinanceSQLiteCollector


def collect_upbit():
    """Collect Upbit data."""
    db_path = PROJECT_ROOT / "data" / "upbit_bitcoin.db"
    timeframes = ["day", "minute240", "minute60"]

    collector = UpbitBitcoinCollector(str(db_path))

    try:
        print(f"[Upbit] Collecting data...")
        for tf in timeframes:
            try:
                collector.collect_all_data(tf)
                collector.interpolate_missing_data(tf)
                print(f"  {tf}: updated")
            except Exception as e:
                print(f"  {tf}: ERROR - {e}")
    finally:
        collector.close()


def collect_binance():
    """Collect Binance data."""
    db_path = PROJECT_ROOT / "data" / "binance_bitcoin.db"
    timeframes = ["day", "minute240", "minute60"]

    collector = BinanceSQLiteCollector(db_path)

    try:
        print(f"[Binance] Collecting data...")
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        for tf in timeframes:
            try:
                collector.collect_timeframe(tf, start_date, end_date, update_mode=True)
                print(f"  {tf}: updated")
            except Exception as e:
                print(f"  {tf}: ERROR - {e}")

        # Also collect funding rates
        try:
            collector.collect_funding(start_date, end_date)
            print(f"  funding_rate: updated")
        except Exception as e:
            print(f"  funding_rate: ERROR - {e}")

    finally:
        collector.close()


def main():
    """Collect missing data for key timeframes."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection started")

    collect_upbit()
    collect_binance()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection completed")


if __name__ == "__main__":
    main()
