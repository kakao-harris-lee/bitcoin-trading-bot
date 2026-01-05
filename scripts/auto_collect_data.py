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

from upbit_history_db.upbit_bitcoin_collector import UpbitBitcoinCollector


def main():
    """Collect missing data for key timeframes."""
    db_path = PROJECT_ROOT / "data" / "upbit_bitcoin.db"

    # Only update timeframes needed for regime classification and trading
    timeframes = ["day", "minute240", "minute60"]

    collector = UpbitBitcoinCollector(str(db_path))

    try:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection started")

        for tf in timeframes:
            try:
                # Collect recent data (will skip existing)
                collector.collect_all_data(tf)
                # Interpolate gaps
                collector.interpolate_missing_data(tf)
                print(f"  {tf}: updated")
            except Exception as e:
                print(f"  {tf}: ERROR - {e}")

        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection completed")

    finally:
        collector.close()


if __name__ == "__main__":
    main()
