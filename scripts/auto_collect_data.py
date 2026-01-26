#!/usr/bin/env python3
"""
Auto data collector for bitcoin trading bot.

Collects OHLCV data for BTC, ETH, and SOL from Binance.
Runs periodically via cron to keep database updated with latest candles.

Usage:
    python scripts/auto_collect_data.py           # Collect all assets
    python scripts/auto_collect_data.py --btc     # BTC only
    python scripts/auto_collect_data.py --altcoins # ETH/SOL only
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# BTC collector
from scripts.collectors.binance_collector import BinanceSQLiteCollector

# ccxt for altcoins
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False


# Altcoin configurations
ALTCOINS = {
    "ETH": {
        "symbol": "ETH/USDT:USDT",
        "db_name": "binance_ethereum.db",
        "table_name": "ethereum_minute60",
    },
    "SOL": {
        "symbol": "SOL/USDT:USDT",
        "db_name": "binance_solana.db",
        "table_name": "solana_minute60",
    },
}


def collect_btc():
    """Collect BTC data using existing collector."""
    db_path = PROJECT_ROOT / "data" / "binance_bitcoin.db"

    collector = BinanceSQLiteCollector(db_path)

    try:
        print(f"[BTC] Collecting data...")
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')

        # Collect daily data first (needed for volatility breakout calculation)
        try:
            collector.collect_timeframe("day", start_date, end_date, update_mode=True)
            print(f"  day: updated")
        except Exception as e:
            print(f"  day: ERROR - {e}")

        # Collect hourly data (most important for indicators)
        try:
            collector.collect_timeframe("minute60", start_date, end_date, update_mode=True)
            print(f"  minute60: updated")
        except Exception as e:
            print(f"  minute60: ERROR - {e}")

        # Also collect funding rates
        try:
            collector.collect_funding(start_date, end_date)
            print(f"  funding_rate: updated")
        except Exception as e:
            print(f"  funding_rate: ERROR - {e}")

        # Calculate volatility breakout features (Larry Williams strategy)
        try:
            updated = collector.add_volatility_breakout(timeframe='minute60', k=0.5)
            print(f"  breakout features: {updated} rows updated")
        except Exception as e:
            print(f"  breakout features: ERROR - {e}")

        # Update LSTM scaling for recent data (rolling window handles new data)
        try:
            added = collector.add_scaled_columns(timeframe='minute60', rolling_window=720)
            print(f"  scaling: {added} columns maintained")
        except Exception as e:
            print(f"  scaling: ERROR - {e}")

    finally:
        collector.close()


def collect_altcoins():
    """Collect ETH and SOL data using ccxt."""
    if not CCXT_AVAILABLE:
        print("[Altcoins] ERROR: ccxt not installed. Run: pip install ccxt")
        return

    exchange = ccxt.binanceusdm({
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })

    for asset, config in ALTCOINS.items():
        print(f"[{asset}] Collecting data...")

        db_path = PROJECT_ROOT / "data" / config["db_name"]

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Create table if not exists
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {config['table_name']} (
                    timestamp TEXT PRIMARY KEY,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL
                )
            """)

            # Get last timestamp
            cursor.execute(f"SELECT MAX(timestamp) FROM {config['table_name']}")
            last_ts = cursor.fetchone()[0]

            if last_ts:
                # Resume from last candle
                since = int(datetime.fromisoformat(last_ts).replace(tzinfo=timezone.utc).timestamp() * 1000)
                since += 3600000  # Add 1 hour to get next candle
                print(f"  Resuming from: {last_ts}")
            else:
                # Start from 7 days ago
                since = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)

            # Fetch candles
            candles = exchange.fetch_ohlcv(config["symbol"], "1h", since=since, limit=500)

            if not candles:
                print(f"  No new data")
                conn.close()
                continue

            # Insert candles
            inserted = 0
            for candle in candles:
                ts_iso = datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
                try:
                    cursor.execute(f"""
                        INSERT OR REPLACE INTO {config['table_name']}
                        (timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (ts_iso, candle[1], candle[2], candle[3], candle[4], candle[5]))
                    inserted += 1
                except Exception:
                    pass

            conn.commit()
            conn.close()

            print(f"  minute60: {inserted} candles updated")

        except Exception as e:
            print(f"  ERROR: {e}")

        time.sleep(0.2)  # Rate limiting


def main():
    parser = argparse.ArgumentParser(description="Auto data collector for trading bot")
    parser.add_argument("--btc", action="store_true", help="Collect BTC only")
    parser.add_argument("--altcoins", action="store_true", help="Collect ETH/SOL only")
    args = parser.parse_args()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection started")

    if args.btc:
        collect_btc()
    elif args.altcoins:
        collect_altcoins()
    else:
        # Collect all
        collect_btc()
        collect_altcoins()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection completed")


if __name__ == "__main__":
    main()
