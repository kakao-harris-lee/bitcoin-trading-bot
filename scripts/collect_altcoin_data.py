#!/usr/bin/env python3
"""
Upbit Altcoin Data Collector

Generalized data collector for any Upbit-listed cryptocurrency.
Supports ETH, SOL, XRP, and any KRW-paired asset.

Usage:
    python scripts/collect_altcoin_data.py ETH           # Collect ETH data
    python scripts/collect_altcoin_data.py SOL           # Collect SOL data
    python scripts/collect_altcoin_data.py ETH SOL XRP   # Collect multiple
    python scripts/collect_altcoin_data.py --list        # Show available assets
    python scripts/collect_altcoin_data.py ETH --timeframe minute60  # Specific timeframe
"""

import argparse
import requests
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent


# Asset configurations
SUPPORTED_ASSETS = {
    "ETH": {
        "name": "Ethereum",
        "market": "KRW-ETH",
        "db_name": "upbit_ethereum.db",
        "table_prefix": "ethereum"
    },
    "SOL": {
        "name": "Solana",
        "market": "KRW-SOL",
        "db_name": "upbit_solana.db",
        "table_prefix": "solana"
    },
    "XRP": {
        "name": "Ripple",
        "market": "KRW-XRP",
        "db_name": "upbit_xrp.db",
        "table_prefix": "xrp"
    },
    "DOGE": {
        "name": "Dogecoin",
        "market": "KRW-DOGE",
        "db_name": "upbit_doge.db",
        "table_prefix": "doge"
    },
    "ADA": {
        "name": "Cardano",
        "market": "KRW-ADA",
        "db_name": "upbit_ada.db",
        "table_prefix": "ada"
    },
    "AVAX": {
        "name": "Avalanche",
        "market": "KRW-AVAX",
        "db_name": "upbit_avax.db",
        "table_prefix": "avax"
    },
}

# Timeframes supported by Upbit API
TIMEFRAMES = {
    'minute1': 1,
    'minute3': 3,
    'minute5': 5,
    'minute10': 10,
    'minute15': 15,
    'minute30': 30,
    'minute60': 60,
    'minute240': 240,
    'day': 1440,
    'week': 10080,
    'month': 43200
}


class UpbitAltcoinCollector:
    """Generalized Upbit altcoin data collector."""

    API_URL = "https://api.upbit.com/v1/candles"
    MAX_COUNT = 200

    def __init__(self, symbol: str, db_path: Optional[str] = None):
        """
        Initialize collector for a specific asset.

        Args:
            symbol: Asset symbol (ETH, SOL, XRP, etc.)
            db_path: Optional custom DB path
        """
        if symbol not in SUPPORTED_ASSETS:
            raise ValueError(f"Unsupported asset: {symbol}. Supported: {list(SUPPORTED_ASSETS.keys())}")

        self.symbol = symbol
        self.config = SUPPORTED_ASSETS[symbol]
        self.market = self.config["market"]
        self.table_prefix = self.config["table_prefix"]

        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = PROJECT_ROOT / "data" / self.config["db_name"]

        self.conn = None
        self._init_database()

    def _init_database(self):
        """Initialize database with tables for all timeframes."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        cursor = self.conn.cursor()

        for timeframe in TIMEFRAMES.keys():
            table_name = f"{self.table_prefix}_{timeframe}"
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TEXT PRIMARY KEY,
                    opening_price REAL NOT NULL,
                    high_price REAL NOT NULL,
                    low_price REAL NOT NULL,
                    trade_price REAL NOT NULL,
                    candle_acc_trade_volume REAL NOT NULL,
                    candle_acc_trade_price REAL NOT NULL,
                    is_interpolated INTEGER DEFAULT 0
                )
            """)

        self.conn.commit()
        print(f"[OK] Database initialized: {self.db_path}")

    def fetch_candles(self, timeframe: str, to: Optional[str] = None) -> List[Dict]:
        """Fetch candle data from Upbit API."""
        if timeframe.startswith('minute'):
            unit = timeframe.replace('minute', '')
            url = f"{self.API_URL}/minutes/{unit}"
        elif timeframe == 'day':
            url = f"{self.API_URL}/days"
        elif timeframe == 'week':
            url = f"{self.API_URL}/weeks"
        elif timeframe == 'month':
            url = f"{self.API_URL}/months"
        else:
            raise ValueError(f"Unknown timeframe: {timeframe}")

        params = {
            'market': self.market,
            'count': self.MAX_COUNT
        }

        if to:
            params['to'] = to

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            time.sleep(0.1)  # Rate limit compliance
            return response.json()
        except Exception as e:
            print(f"[ERR] API request failed ({timeframe}): {e}")
            return []

    def save_candles(self, timeframe: str, candles: List[Dict]) -> int:
        """Save candle data to database. Returns number of new records."""
        table_name = f"{self.table_prefix}_{timeframe}"
        cursor = self.conn.cursor()

        inserted = 0
        for candle in candles:
            try:
                cursor.execute(f"""
                    SELECT COUNT(*) FROM {table_name}
                    WHERE timestamp = ?
                """, (candle['candle_date_time_kst'],))

                if cursor.fetchone()[0] == 0:
                    cursor.execute(f"""
                        INSERT INTO {table_name}
                        (timestamp, opening_price, high_price, low_price,
                         trade_price, candle_acc_trade_volume, candle_acc_trade_price, is_interpolated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """, (
                        candle['candle_date_time_kst'],
                        candle['opening_price'],
                        candle['high_price'],
                        candle['low_price'],
                        candle['trade_price'],
                        candle['candle_acc_trade_volume'],
                        candle['candle_acc_trade_price']
                    ))
                    inserted += 1
            except Exception as e:
                print(f"[ERR] Save failed: {e}")

        self.conn.commit()
        return inserted

    def collect_timeframe(self, timeframe: str, min_year: int = 2019):
        """
        Collect all available data for a specific timeframe.

        Args:
            timeframe: Timeframe to collect (minute60, day, etc.)
            min_year: Stop collection when reaching this year
        """
        print(f"\n{'='*60}")
        print(f"[{self.symbol}] Collecting {timeframe} data...")
        print(f"{'='*60}")

        total_count = 0
        to_timestamp = None
        iteration = 0
        prev_oldest = None

        while True:
            iteration += 1
            candles = self.fetch_candles(timeframe, to_timestamp)

            if not candles:
                print("  [!] No more data available")
                break

            oldest = candles[-1]
            current_oldest = oldest['candle_date_time_kst']

            # Detect repeated data
            if prev_oldest == current_oldest:
                print("  [!] Repeated data detected, stopping")
                break

            saved = self.save_candles(timeframe, candles)
            total_count += saved

            to_timestamp = oldest['candle_date_time_utc']
            prev_oldest = current_oldest

            print(f"  Iter {iteration}: fetched {len(candles)}, saved {saved} (total: {total_count})")
            print(f"    Latest: {candles[0]['candle_date_time_kst']}")
            print(f"    Oldest: {current_oldest}")

            if saved == 0:
                print("  [!] All data already exists, stopping")
                break

            # Check year limit
            try:
                oldest_year = datetime.fromisoformat(to_timestamp.replace('Z', '+00:00')).year
                if oldest_year < min_year:
                    print(f"  [OK] Reached {min_year}, collection complete")
                    break
            except:
                pass

            time.sleep(0.2)

        print(f"\n[OK] Total {total_count} candles collected for {timeframe}")
        self._interpolate_missing(timeframe)

    def _interpolate_missing(self, timeframe: str):
        """Linear interpolation for missing data points."""
        print(f"\n[*] Interpolating {timeframe} gaps...")

        table_name = f"{self.table_prefix}_{timeframe}"
        cursor = self.conn.cursor()

        cursor.execute(f"""
            SELECT timestamp, opening_price, high_price, low_price,
                   trade_price, candle_acc_trade_volume, candle_acc_trade_price
            FROM {table_name}
            WHERE is_interpolated = 0
            ORDER BY timestamp ASC
        """)

        rows = cursor.fetchall()
        if len(rows) < 2:
            print("  Not enough data for interpolation")
            return

        interval_minutes = TIMEFRAMES[timeframe]
        interpolated = 0

        for i in range(len(rows) - 1):
            current_time = datetime.fromisoformat(rows[i][0])
            next_time = datetime.fromisoformat(rows[i+1][0])

            expected_next = current_time + timedelta(minutes=interval_minutes)

            if next_time > expected_next:
                gap = (next_time - current_time).total_seconds() / 60 / interval_minutes
                missing_count = int(gap) - 1

                if missing_count > 0:
                    current_values = rows[i][1:]
                    next_values = rows[i+1][1:]

                    for j in range(1, missing_count + 1):
                        ratio = j / (missing_count + 1)
                        interp_time = current_time + timedelta(minutes=interval_minutes * j)

                        interp_values = [
                            current_values[k] + (next_values[k] - current_values[k]) * ratio
                            for k in range(len(current_values))
                        ]

                        cursor.execute(f"""
                            INSERT OR REPLACE INTO {table_name}
                            (timestamp, opening_price, high_price, low_price,
                             trade_price, candle_acc_trade_volume, candle_acc_trade_price, is_interpolated)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                        """, (interp_time.isoformat(), *interp_values))

                        interpolated += 1

        self.conn.commit()
        print(f"[OK] Interpolated {interpolated} missing candles")

    def collect_all_timeframes(self):
        """Collect data for all timeframes."""
        print(f"\n{'='*60}")
        print(f"[{self.symbol}] {self.config['name']} Full Data Collection")
        print(f"{'='*60}")

        for timeframe in TIMEFRAMES.keys():
            try:
                self.collect_timeframe(timeframe)
            except Exception as e:
                print(f"[ERR] {timeframe} collection failed: {e}")
                continue

        print(f"\n[OK] All timeframes collected for {self.symbol}")
        self.print_statistics()

    def collect_backtesting_timeframes(self):
        """Collect only timeframes needed for backtesting (minute60+)."""
        print(f"\n{'='*60}")
        print(f"[{self.symbol}] {self.config['name']} Backtesting Data Collection")
        print(f"{'='*60}")

        backtesting_timeframes = ['minute60', 'minute240', 'day', 'week', 'month']

        for timeframe in backtesting_timeframes:
            try:
                self.collect_timeframe(timeframe)
            except Exception as e:
                print(f"[ERR] {timeframe} collection failed: {e}")
                continue

        print(f"\n[OK] Backtesting timeframes collected for {self.symbol}")
        self.print_statistics()

    def print_statistics(self):
        """Print collected data statistics."""
        print(f"\n[{self.symbol}] Data Statistics:")
        print("-" * 60)

        cursor = self.conn.cursor()

        for timeframe in TIMEFRAMES.keys():
            table_name = f"{self.table_prefix}_{timeframe}"
            try:
                cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN is_interpolated = 0 THEN 1 ELSE 0 END) as original,
                        SUM(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as interpolated,
                        MIN(timestamp) as oldest,
                        MAX(timestamp) as newest
                    FROM {table_name}
                """)

                stats = cursor.fetchone()
                if stats[0] > 0:
                    print(f"\n{timeframe}:")
                    print(f"  Total: {stats[0]:,}")
                    print(f"  Original: {stats[1] or 0:,}")
                    print(f"  Interpolated: {stats[2] or 0:,}")
                    print(f"  Range: {stats[3]} ~ {stats[4]}")
            except:
                pass

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            print(f"\n[OK] Database connection closed")


def list_available_assets():
    """Print available assets."""
    print("\nAvailable Assets:")
    print("-" * 40)
    for symbol, config in SUPPORTED_ASSETS.items():
        print(f"  {symbol:6} - {config['name']:15} ({config['market']})")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Collect Upbit altcoin historical data for backtesting"
    )
    parser.add_argument(
        'symbols',
        nargs='*',
        help='Asset symbols to collect (ETH, SOL, XRP, etc.)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List available assets'
    )
    parser.add_argument(
        '--timeframe',
        type=str,
        help='Collect specific timeframe only (e.g., minute60)'
    )
    parser.add_argument(
        '--backtesting',
        action='store_true',
        help='Collect only backtesting timeframes (minute60+)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Collect all supported assets'
    )

    args = parser.parse_args()

    if args.list:
        list_available_assets()
        return

    if args.all:
        symbols = list(SUPPORTED_ASSETS.keys())
    elif not args.symbols:
        print("Error: No symbols specified. Use --list to see available assets.")
        return
    else:
        symbols = [s.upper() for s in args.symbols]

    # Validate symbols
    invalid = [s for s in symbols if s not in SUPPORTED_ASSETS]
    if invalid:
        print(f"Error: Unsupported assets: {invalid}")
        list_available_assets()
        return

    print("\n" + "="*60)
    print("Upbit Altcoin Data Collector")
    print("="*60)
    print(f"\nAssets to collect: {symbols}")
    if args.timeframe:
        print(f"Timeframe: {args.timeframe}")
    elif args.backtesting:
        print("Mode: Backtesting (minute60+)")
    else:
        print("Mode: All timeframes")
    print()

    for symbol in symbols:
        collector = UpbitAltcoinCollector(symbol)
        try:
            if args.timeframe:
                if args.timeframe not in TIMEFRAMES:
                    print(f"Error: Invalid timeframe {args.timeframe}")
                    print(f"Valid: {list(TIMEFRAMES.keys())}")
                    return
                collector.collect_timeframe(args.timeframe)
            elif args.backtesting:
                collector.collect_backtesting_timeframes()
            else:
                collector.collect_all_timeframes()
        except KeyboardInterrupt:
            print("\n\n[!] Interrupted by user. Progress saved.")
        except Exception as e:
            print(f"\n[ERR] Collection failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            collector.close()

    print("\n" + "="*60)
    print("[DONE] Data collection complete")
    print("="*60)


if __name__ == "__main__":
    main()
