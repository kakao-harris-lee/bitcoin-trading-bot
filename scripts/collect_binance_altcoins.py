#!/usr/bin/env python3
"""
Binance Futures Altcoin Data Collector

Collects OHLCV data and funding rate history for altcoins from Binance Futures.
Supports ETH, SOL, XRP perpetual futures contracts.

Usage:
    python scripts/collect_binance_altcoins.py                    # Collect all altcoins
    python scripts/collect_binance_altcoins.py ETH                # Collect ETH only
    python scripts/collect_binance_altcoins.py ETH SOL            # Collect specific altcoins
    python scripts/collect_binance_altcoins.py --list             # List available symbols
    python scripts/collect_binance_altcoins.py --timeframe 1h     # Specific timeframe
    python scripts/collect_binance_altcoins.py --stats            # Show statistics only
"""

import argparse
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import ccxt

PROJECT_ROOT = Path(__file__).parent.parent


# Asset configurations for Binance Futures
SUPPORTED_ASSETS = {
    "ETH": {
        "name": "Ethereum",
        "symbol": "ETH/USDT:USDT",
        "db_name": "binance_ethereum.db",
        "table_prefix": "ethereum"
    },
    "SOL": {
        "name": "Solana",
        "symbol": "SOL/USDT:USDT",
        "db_name": "binance_solana.db",
        "table_prefix": "solana"
    },
    "XRP": {
        "name": "Ripple",
        "symbol": "XRP/USDT:USDT",
        "db_name": "binance_xrp.db",
        "table_prefix": "xrp"
    },
}

# Timeframes to collect (matching task requirements)
TIMEFRAMES = {
    '1d': {
        'ccxt_timeframe': '1d',
        'table_suffix': 'day',
        'interval_minutes': 1440
    },
    '1h': {
        'ccxt_timeframe': '1h',
        'table_suffix': 'minute60',
        'interval_minutes': 60
    },
    '15m': {
        'ccxt_timeframe': '15m',
        'table_suffix': 'minute15',
        'interval_minutes': 15
    },
}

# Collection start date
START_DATE = datetime(2020, 1, 1, tzinfo=timezone.utc)


class BinanceAltcoinCollector:
    """Binance Futures altcoin data collector using ccxt."""

    # Rate limiting: Binance allows 1200 requests per minute
    REQUEST_DELAY = 0.1  # 100ms between requests
    MAX_CANDLES_PER_REQUEST = 1000  # Binance limit

    def __init__(self, symbol_key: str, db_path: Optional[str] = None):
        """
        Initialize collector for a specific asset.

        Args:
            symbol_key: Asset key (ETH, SOL, XRP)
            db_path: Optional custom DB path
        """
        if symbol_key not in SUPPORTED_ASSETS:
            raise ValueError(f"Unsupported asset: {symbol_key}. Supported: {list(SUPPORTED_ASSETS.keys())}")

        self.symbol_key = symbol_key
        self.config = SUPPORTED_ASSETS[symbol_key]
        self.symbol = self.config["symbol"]
        self.table_prefix = self.config["table_prefix"]

        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = PROJECT_ROOT / "data" / self.config["db_name"]

        # Initialize ccxt Binance Futures
        self.exchange = ccxt.binanceusdm({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
            }
        })

        self.conn = None
        self._init_database()

    def _init_database(self):
        """Initialize database with tables for all timeframes and funding rate."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        cursor = self.conn.cursor()

        # Create OHLCV tables for each timeframe
        for tf_key, tf_config in TIMEFRAMES.items():
            table_name = f"{self.table_prefix}_{tf_config['table_suffix']}"
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TEXT PRIMARY KEY,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL,
                    trades INTEGER,
                    funding_rate REAL DEFAULT 0.0
                )
            """)

        # Create funding rate table
        table_name = f"{self.table_prefix}_funding_rate"
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                timestamp TEXT PRIMARY KEY,
                funding_rate REAL NOT NULL,
                mark_price REAL
            )
        """)

        self.conn.commit()
        print(f"[OK] Database initialized: {self.db_path}")

    def _timestamp_to_iso(self, timestamp_ms: int) -> str:
        """Convert millisecond timestamp to ISO format string."""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return dt.strftime('%Y-%m-%dT%H:%M:%S')

    def _iso_to_timestamp(self, iso_str: str) -> int:
        """Convert ISO format string to millisecond timestamp."""
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    def fetch_ohlcv(self, timeframe: str, since: Optional[int] = None, limit: int = 1000) -> List:
        """
        Fetch OHLCV data from Binance Futures.

        Args:
            timeframe: ccxt timeframe string (1d, 1h, 15m)
            since: Start timestamp in milliseconds
            limit: Number of candles to fetch

        Returns:
            List of OHLCV candles
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                self.symbol,
                timeframe=timeframe,
                since=since,
                limit=limit
            )
            time.sleep(self.REQUEST_DELAY)
            return ohlcv
        except ccxt.RateLimitExceeded as e:
            print(f"  [!] Rate limit hit, waiting 60s...")
            time.sleep(60)
            return self.fetch_ohlcv(timeframe, since, limit)
        except Exception as e:
            print(f"  [ERR] OHLCV fetch failed: {e}")
            return []

    def fetch_funding_rate_history(self, since: Optional[int] = None, limit: int = 1000) -> List[Dict]:
        """
        Fetch funding rate history from Binance Futures.

        Args:
            since: Start timestamp in milliseconds
            limit: Number of records to fetch

        Returns:
            List of funding rate records
        """
        try:
            # Use ccxt's fetch_funding_rate_history
            funding_rates = self.exchange.fetch_funding_rate_history(
                self.symbol,
                since=since,
                limit=limit
            )
            time.sleep(self.REQUEST_DELAY)
            return funding_rates
        except ccxt.RateLimitExceeded as e:
            print(f"  [!] Rate limit hit, waiting 60s...")
            time.sleep(60)
            return self.fetch_funding_rate_history(since, limit)
        except Exception as e:
            print(f"  [ERR] Funding rate fetch failed: {e}")
            return []

    def save_ohlcv(self, timeframe_key: str, candles: List) -> int:
        """
        Save OHLCV data to database.

        Args:
            timeframe_key: Timeframe key (1d, 1h, 15m)
            candles: List of OHLCV candles [timestamp, open, high, low, close, volume]

        Returns:
            Number of new records inserted
        """
        tf_config = TIMEFRAMES[timeframe_key]
        table_name = f"{self.table_prefix}_{tf_config['table_suffix']}"
        cursor = self.conn.cursor()

        inserted = 0
        for candle in candles:
            timestamp_ms, open_price, high, low, close, volume = candle[:6]
            timestamp_iso = self._timestamp_to_iso(timestamp_ms)

            try:
                cursor.execute(f"""
                    INSERT OR IGNORE INTO {table_name}
                    (timestamp, open, high, low, close, volume, quote_volume, trades, funding_rate)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0.0)
                """, (timestamp_iso, open_price, high, low, close, volume))

                if cursor.rowcount > 0:
                    inserted += 1
            except Exception as e:
                print(f"  [ERR] Save failed for {timestamp_iso}: {e}")

        self.conn.commit()
        return inserted

    def save_funding_rates(self, funding_rates: List[Dict]) -> int:
        """
        Save funding rate data to database.

        Args:
            funding_rates: List of funding rate records from ccxt

        Returns:
            Number of new records inserted
        """
        table_name = f"{self.table_prefix}_funding_rate"
        cursor = self.conn.cursor()

        inserted = 0
        for rate in funding_rates:
            try:
                timestamp_ms = rate.get('timestamp')
                funding_rate = rate.get('fundingRate')
                mark_price = rate.get('markPrice')

                if timestamp_ms is None or funding_rate is None:
                    continue

                timestamp_iso = self._timestamp_to_iso(timestamp_ms)

                cursor.execute(f"""
                    INSERT OR IGNORE INTO {table_name}
                    (timestamp, funding_rate, mark_price)
                    VALUES (?, ?, ?)
                """, (timestamp_iso, funding_rate, mark_price))

                if cursor.rowcount > 0:
                    inserted += 1
            except Exception as e:
                print(f"  [ERR] Save funding rate failed: {e}")

        self.conn.commit()
        return inserted

    def get_latest_timestamp(self, table_name: str) -> Optional[int]:
        """Get the latest timestamp in a table."""
        cursor = self.conn.cursor()
        try:
            cursor.execute(f"SELECT MAX(timestamp) FROM {table_name}")
            result = cursor.fetchone()
            if result and result[0]:
                return self._iso_to_timestamp(result[0])
            return None
        except:
            return None

    def collect_ohlcv(self, timeframe_key: str):
        """
        Collect all OHLCV data for a specific timeframe from START_DATE to now.

        Args:
            timeframe_key: Timeframe key (1d, 1h, 15m)
        """
        tf_config = TIMEFRAMES[timeframe_key]
        table_name = f"{self.table_prefix}_{tf_config['table_suffix']}"
        ccxt_tf = tf_config['ccxt_timeframe']

        print(f"\n{'='*60}")
        print(f"[{self.symbol_key}] Collecting {timeframe_key} OHLCV data...")
        print(f"{'='*60}")

        # Check for existing data
        latest_ts = self.get_latest_timestamp(table_name)
        if latest_ts:
            since = latest_ts + 1  # Start from next candle
            print(f"  Resuming from: {self._timestamp_to_iso(since)}")
        else:
            since = int(START_DATE.timestamp() * 1000)
            print(f"  Starting from: {START_DATE.isoformat()}")

        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        total_inserted = 0
        iteration = 0

        while since < now:
            iteration += 1
            candles = self.fetch_ohlcv(ccxt_tf, since=since, limit=self.MAX_CANDLES_PER_REQUEST)

            if not candles:
                print("  [!] No more data available")
                break

            inserted = self.save_ohlcv(timeframe_key, candles)
            total_inserted += inserted

            # Get the latest timestamp from fetched data
            last_candle_ts = candles[-1][0]
            interval_ms = tf_config['interval_minutes'] * 60 * 1000
            since = last_candle_ts + interval_ms

            # Progress update
            oldest_date = self._timestamp_to_iso(candles[0][0])
            newest_date = self._timestamp_to_iso(last_candle_ts)
            print(f"  Iter {iteration}: fetched {len(candles)}, saved {inserted} | {oldest_date} ~ {newest_date}")

            if len(candles) < self.MAX_CANDLES_PER_REQUEST:
                print("  [OK] Reached end of available data")
                break

            # Prevent infinite loop
            if inserted == 0 and len(candles) == self.MAX_CANDLES_PER_REQUEST:
                # Check if we're still making progress
                if since >= now:
                    break

        print(f"\n[OK] Total {total_inserted} candles collected for {timeframe_key}")

    def collect_funding_rates(self):
        """Collect all funding rate history from START_DATE to now."""
        table_name = f"{self.table_prefix}_funding_rate"

        print(f"\n{'='*60}")
        print(f"[{self.symbol_key}] Collecting funding rate history...")
        print(f"{'='*60}")

        # Check for existing data
        latest_ts = self.get_latest_timestamp(table_name)
        if latest_ts:
            since = latest_ts + 1
            print(f"  Resuming from: {self._timestamp_to_iso(since)}")
        else:
            since = int(START_DATE.timestamp() * 1000)
            print(f"  Starting from: {START_DATE.isoformat()}")

        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        total_inserted = 0
        iteration = 0

        while since < now:
            iteration += 1
            funding_rates = self.fetch_funding_rate_history(since=since, limit=1000)

            if not funding_rates:
                print("  [!] No more funding rate data available")
                break

            inserted = self.save_funding_rates(funding_rates)
            total_inserted += inserted

            # Get the latest timestamp
            last_ts = funding_rates[-1].get('timestamp', since)
            # Funding rates are typically every 8 hours
            since = last_ts + 1

            # Progress update
            oldest_date = self._timestamp_to_iso(funding_rates[0]['timestamp'])
            newest_date = self._timestamp_to_iso(last_ts)
            print(f"  Iter {iteration}: fetched {len(funding_rates)}, saved {inserted} | {oldest_date} ~ {newest_date}")

            if len(funding_rates) < 1000:
                print("  [OK] Reached end of available funding rate data")
                break

        print(f"\n[OK] Total {total_inserted} funding rate records collected")

    def collect_all(self):
        """Collect all timeframes and funding rates."""
        print(f"\n{'='*60}")
        print(f"[{self.symbol_key}] {self.config['name']} Full Data Collection")
        print(f"{'='*60}")

        # Collect OHLCV for each timeframe
        for tf_key in TIMEFRAMES.keys():
            try:
                self.collect_ohlcv(tf_key)
            except Exception as e:
                print(f"[ERR] {tf_key} collection failed: {e}")
                continue

        # Collect funding rates
        try:
            self.collect_funding_rates()
        except Exception as e:
            print(f"[ERR] Funding rate collection failed: {e}")

        print(f"\n[OK] All data collected for {self.symbol_key}")
        self.print_statistics()

    def print_statistics(self):
        """Print collected data statistics."""
        print(f"\n[{self.symbol_key}] Data Statistics:")
        print("-" * 60)

        cursor = self.conn.cursor()

        # OHLCV statistics
        for tf_key, tf_config in TIMEFRAMES.items():
            table_name = f"{self.table_prefix}_{tf_config['table_suffix']}"
            try:
                cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        MIN(timestamp) as oldest,
                        MAX(timestamp) as newest
                    FROM {table_name}
                """)

                stats = cursor.fetchone()
                if stats[0] > 0:
                    print(f"\n{tf_key} ({tf_config['table_suffix']}):")
                    print(f"  Total: {stats[0]:,} candles")
                    print(f"  Range: {stats[1]} ~ {stats[2]}")
            except Exception as e:
                print(f"\n{tf_key}: Error reading stats - {e}")

        # Funding rate statistics
        table_name = f"{self.table_prefix}_funding_rate"
        try:
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total,
                    MIN(timestamp) as oldest,
                    MAX(timestamp) as newest,
                    AVG(funding_rate) as avg_rate
                FROM {table_name}
            """)

            stats = cursor.fetchone()
            if stats[0] > 0:
                print(f"\nFunding Rate:")
                print(f"  Total: {stats[0]:,} records")
                print(f"  Range: {stats[1]} ~ {stats[2]}")
                print(f"  Avg Rate: {stats[3]:.6f}")
        except Exception as e:
            print(f"\nFunding Rate: Error reading stats - {e}")

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            print(f"\n[OK] Database connection closed")


def list_available_assets():
    """Print available assets."""
    print("\nAvailable Binance Futures Assets:")
    print("-" * 50)
    for symbol_key, config in SUPPORTED_ASSETS.items():
        print(f"  {symbol_key:6} - {config['name']:15} ({config['symbol']})")
    print(f"\nTimeframes: {list(TIMEFRAMES.keys())}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Collect Binance Futures altcoin historical data for backtesting"
    )
    parser.add_argument(
        'symbols',
        nargs='*',
        help='Asset symbols to collect (ETH, SOL, XRP)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List available assets'
    )
    parser.add_argument(
        '--timeframe',
        type=str,
        choices=list(TIMEFRAMES.keys()),
        help='Collect specific timeframe only (1d, 1h, 15m)'
    )
    parser.add_argument(
        '--funding-only',
        action='store_true',
        help='Collect only funding rates'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show statistics only (no collection)'
    )

    args = parser.parse_args()

    if args.list:
        list_available_assets()
        return

    # Default to all symbols if none specified
    if not args.symbols:
        symbols = list(SUPPORTED_ASSETS.keys())
    else:
        symbols = [s.upper() for s in args.symbols]

    # Validate symbols
    invalid = [s for s in symbols if s not in SUPPORTED_ASSETS]
    if invalid:
        print(f"Error: Unsupported assets: {invalid}")
        list_available_assets()
        return

    print("\n" + "="*60)
    print("Binance Futures Altcoin Data Collector")
    print("="*60)
    print(f"\nAssets to collect: {symbols}")
    if args.timeframe:
        print(f"Timeframe: {args.timeframe}")
    elif args.funding_only:
        print("Mode: Funding rates only")
    elif args.stats:
        print("Mode: Statistics only")
    else:
        print("Mode: All timeframes + funding rates")
    print(f"Date range: {START_DATE.date()} ~ present")
    print()

    for symbol_key in symbols:
        collector = BinanceAltcoinCollector(symbol_key)
        try:
            if args.stats:
                collector.print_statistics()
            elif args.funding_only:
                collector.collect_funding_rates()
                collector.print_statistics()
            elif args.timeframe:
                collector.collect_ohlcv(args.timeframe)
                collector.print_statistics()
            else:
                collector.collect_all()
        except KeyboardInterrupt:
            print("\n\n[!] Interrupted by user. Progress saved.")
            collector.print_statistics()
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
