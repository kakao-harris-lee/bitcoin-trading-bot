#!/usr/bin/env python3
"""
Multi-Asset 4H OHLCV Data Collector for MLP Training.

Collects historical 4-hour candlestick data from Binance for 400+ USDT pairs.
Based on Parente & Rizzuti (2025) methodology:
- Training data: All USDT pairs EXCEPT BTC and ETH
- Validation data: BTC and ETH only (collected separately)

Output: Parquet files for efficient ML processing.

Usage:
    python scripts/collectors/multi_asset_collector.py --output data/multi_asset_4h
    python scripts/collectors/multi_asset_collector.py --validation-only --output data/validation_4h
"""

import argparse
import asyncio
import aiohttp
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "multi_asset_4h"

# Binance API
BINANCE_API_URL = "https://api.binance.com/api/v3"
BINANCE_FUTURES_URL = "https://fapi.binance.com/fapi/v1"

# Rate limiting (tunable via CLI)
MAX_CONCURRENT_REQUESTS = 10
REQUEST_DELAY = 0.1  # seconds between requests

# Validation symbols (excluded from training)
VALIDATION_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# Minimum data requirements
MIN_SAMPLES = 1000  # Minimum 4H candles required (~166 days)


class MultiAssetCollector:
    """
    Async collector for multi-asset 4H OHLCV data from Binance.

    Designed for MLP training dataset creation following the paper's methodology:
    - Collect 400+ USDT pairs for training (exclude BTC/ETH)
    - Collect BTC/ETH separately for validation
    """

    def __init__(
        self,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
        request_delay: float = REQUEST_DELAY,
        symbol_concurrent: int | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.request_delay = request_delay
        self.symbol_concurrent = symbol_concurrent or max_concurrent
        self.symbol_semaphore = asyncio.Semaphore(self.symbol_concurrent)

    async def _collect_symbol_wrapper(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str,
        idx: int,
        total: int,
    ) -> tuple[str, Optional[pd.DataFrame]]:
        """Collect history for a symbol with concurrency control."""
        async with self.symbol_semaphore:
            logger.info(f"[{idx}/{total}] Collecting {symbol}...")
            df = await self.collect_symbol_history(
                session, symbol, start_date, end_date, interval
            )
            return symbol, df

    async def get_all_usdt_pairs(self, session: aiohttp.ClientSession) -> list[str]:
        """Fetch all available USDT trading pairs from Binance."""
        url = f"{BINANCE_API_URL}/exchangeInfo"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch exchange info: {resp.status}")
                    return []

                data = await resp.json()

            pairs = [
                s["symbol"]
                for s in data["symbols"]
                if s["quoteAsset"] == "USDT"
                and s["status"] == "TRADING"
                and s["isSpotTradingAllowed"]
            ]

            logger.info(f"Found {len(pairs)} USDT trading pairs")
            return sorted(pairs)

        except Exception as e:
            logger.error(f"Error fetching exchange info: {e}")
            return []

    async def fetch_klines(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        interval: str = "4h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> list:
        """Fetch klines for a single symbol."""
        url = f"{BINANCE_API_URL}/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        async with self.semaphore:
            try:
                await asyncio.sleep(self.request_delay)  # Rate limiting
                async with session.get(url, params=params) as resp:
                    if resp.status == 429:  # Rate limited
                        logger.warning(f"Rate limited on {symbol}, waiting...")
                        await asyncio.sleep(60)
                        return await self.fetch_klines(
                            session, symbol, interval, start_time, end_time, limit
                        )

                    if resp.status != 200:
                        logger.warning(f"Failed to fetch {symbol}: {resp.status}")
                        return []

                    return await resp.json()

            except Exception as e:
                logger.warning(f"Error fetching {symbol}: {e}")
                return []

    async def collect_symbol_history(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "4h",
    ) -> Optional[pd.DataFrame]:
        """Collect full history for a single symbol."""
        start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)

        all_data = []
        current_start = start_ts

        while current_start < end_ts:
            klines = await self.fetch_klines(
                session,
                symbol,
                interval,
                start_time=current_start,
                end_time=end_ts,
            )

            if not klines:
                break

            all_data.extend(klines)

            # Move to next batch
            last_ts = klines[-1][0]
            if last_ts <= current_start:
                break
            current_start = last_ts + 1

            if len(klines) < 1000:
                break

        if not all_data:
            return None

        # Convert to DataFrame
        df = pd.DataFrame(
            all_data,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )

        # Clean and format
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)

        df["symbol"] = symbol

        # Select relevant columns
        df = df[["timestamp", "open", "high", "low", "close", "volume", "symbol"]]

        # Remove duplicates
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        df = df.sort_values("timestamp").reset_index(drop=True)

        return df

    async def collect_training_data(
        self,
        start_date: str = "2017-08-17",
        end_date: str = "2024-12-31",
        max_pairs: int = 400,
    ) -> dict[str, pd.DataFrame]:
        """
        Collect training data from all USDT pairs except BTC/ETH.

        Args:
            start_date: Start date for data collection
            end_date: End date for data collection
            max_pairs: Maximum number of pairs to collect

        Returns:
            Dict mapping symbol to DataFrame
        """
        logger.info(f"Collecting training data from {start_date} to {end_date}")

        async with aiohttp.ClientSession() as session:
            # Get all pairs
            all_pairs = await self.get_all_usdt_pairs(session)

            # Exclude validation symbols
            train_pairs = [p for p in all_pairs if p not in VALIDATION_SYMBOLS]
            train_pairs = train_pairs[:max_pairs]

            logger.info(f"Collecting {len(train_pairs)} pairs (excluding BTC/ETH)")

            datasets = {}
            failed = []

            interval = "4h"

            tasks = [
                asyncio.create_task(
                    self._collect_symbol_wrapper(
                        session,
                        symbol,
                        start_date,
                        end_date,
                        interval,
                        i + 1,
                        len(train_pairs),
                    )
                )
                for i, symbol in enumerate(train_pairs)
            ]

            for task in asyncio.as_completed(tasks):
                symbol, df = await task

                if df is not None and len(df) >= MIN_SAMPLES:
                    datasets[symbol] = df
                    logger.info(f"  ✓ {symbol}: {len(df)} samples")
                else:
                    failed.append(symbol)
                    samples = len(df) if df is not None else 0
                    logger.warning(f"  ✗ {symbol}: insufficient data ({samples} samples)")

            logger.info(
                f"Collection complete: {len(datasets)} successful, {len(failed)} failed"
            )

            return datasets

    async def collect_validation_data(
        self,
        start_date: str = "2017-08-17",
        end_date: str = "2024-12-31",
    ) -> dict[str, pd.DataFrame]:
        """
        Collect validation data for BTC and ETH only.

        These are kept separate from training data per the paper's methodology.
        """
        logger.info(f"Collecting validation data (BTC/ETH) from {start_date} to {end_date}")

        async with aiohttp.ClientSession() as session:
            datasets = {}
            tasks = [
                asyncio.create_task(
                    self._collect_symbol_wrapper(
                        session,
                        symbol,
                        start_date,
                        end_date,
                        "4h",
                        i + 1,
                        len(VALIDATION_SYMBOLS),
                    )
                )
                for i, symbol in enumerate(VALIDATION_SYMBOLS)
            ]

            for task in asyncio.as_completed(tasks):
                symbol, df = await task
                if df is not None:
                    datasets[symbol] = df
                    logger.info(f"  ✓ {symbol}: {len(df)} samples")
                else:
                    logger.error(f"  ✗ Failed to collect {symbol}")

            return datasets

    def save_datasets(
        self,
        datasets: dict[str, pd.DataFrame],
        prefix: str = "train",
    ) -> Path:
        """
        Save datasets to parquet files.

        Args:
            datasets: Dict mapping symbol to DataFrame
            prefix: Filename prefix ('train' or 'validation')

        Returns:
            Path to saved file
        """
        if not datasets:
            logger.error("No datasets to save")
            return None

        # Combine all DataFrames
        combined = pd.concat(datasets.values(), ignore_index=True)
        combined = combined.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

        # Save to parquet
        output_path = self.output_dir / f"{prefix}_4h.parquet"
        combined.to_parquet(output_path, index=False, compression="snappy")

        logger.info(f"Saved {len(combined)} samples to {output_path}")
        logger.info(f"  Symbols: {len(datasets)}")
        logger.info(f"  Date range: {combined['timestamp'].min()} to {combined['timestamp'].max()}")

        # Also save individual files for flexibility
        individual_dir = self.output_dir / prefix
        individual_dir.mkdir(exist_ok=True)

        for symbol, df in datasets.items():
            symbol_path = individual_dir / f"{symbol}.parquet"
            df.to_parquet(symbol_path, index=False, compression="snappy")

        logger.info(f"Saved individual files to {individual_dir}/")

        return output_path

    def load_datasets(self, prefix: str = "train") -> pd.DataFrame:
        """Load combined dataset from parquet."""
        path = self.output_dir / f"{prefix}_4h.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        return pd.read_parquet(path)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Collect multi-asset 4H OHLCV data for MLP training"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for parquet files",
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2017-08-17",
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default="2024-12-31",
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=400,
        help="Maximum number of pairs to collect",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=MAX_CONCURRENT_REQUESTS,
        help="Maximum concurrent requests",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=REQUEST_DELAY,
        help="Delay between requests (seconds)",
    )
    parser.add_argument(
        "--symbol-concurrent",
        type=int,
        default=None,
        help="Maximum concurrent symbols collected",
    )
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="Only collect validation data (BTC/ETH)",
    )
    parser.add_argument(
        "--training-only",
        action="store_true",
        help="Only collect training data (exclude BTC/ETH)",
    )

    args = parser.parse_args()

    collector = MultiAssetCollector(
        output_dir=args.output,
        max_concurrent=args.max_concurrent,
        request_delay=args.request_delay,
        symbol_concurrent=args.symbol_concurrent,
    )

    start_time = time.time()

    if args.validation_only:
        # Collect only BTC/ETH
        datasets = await collector.collect_validation_data(args.start, args.end)
        collector.save_datasets(datasets, prefix="validation")

    elif args.training_only:
        # Collect training pairs only
        datasets = await collector.collect_training_data(
            args.start, args.end, args.max_pairs
        )
        collector.save_datasets(datasets, prefix="train")

    else:
        # Collect both
        logger.info("=" * 60)
        logger.info("Collecting training data...")
        logger.info("=" * 60)
        train_datasets = await collector.collect_training_data(
            args.start, args.end, args.max_pairs
        )
        collector.save_datasets(train_datasets, prefix="train")

        logger.info("")
        logger.info("=" * 60)
        logger.info("Collecting validation data...")
        logger.info("=" * 60)
        val_datasets = await collector.collect_validation_data(args.start, args.end)
        collector.save_datasets(val_datasets, prefix="validation")

    elapsed = time.time() - start_time
    logger.info(f"\nTotal time: {elapsed:.1f} seconds")


if __name__ == "__main__":
    asyncio.run(main())
