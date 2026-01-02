#!/usr/bin/env python3
# lstm_trainer/src/export_data.py
"""Export H4 data from SQLite to Parquet for training."""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd


def export_h4_data(
    db_path: str,
    output_path: str = "data/processed/h4_candles.parquet",
) -> pd.DataFrame:
    """
    Export H4 (minute240) candles from SQLite to Parquet.

    Args:
        db_path: Path to upbit_bitcoin.db
        output_path: Output parquet file path

    Returns:
        DataFrame with exported data
    """
    print(f"Connecting to {db_path}...")

    conn = sqlite3.connect(db_path)

    # Upbit schema uses different column names
    query = """
    SELECT
        timestamp,
        opening_price AS open,
        high_price AS high,
        low_price AS low,
        trade_price AS close,
        candle_acc_trade_volume AS volume
    FROM bitcoin_minute240
    ORDER BY timestamp ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"Loaded {len(df):,} H4 candles")
    print(f"Date range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Save to parquet
    df.to_parquet(output_path, index=False)
    print(f"Saved to {output_path}")

    return df


def main():
    parser = argparse.ArgumentParser(description="Export H4 data for LSTM training")
    parser.add_argument(
        "--db-path",
        default="../data/upbit_bitcoin.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--output",
        default="data/processed/h4_candles.parquet",
        help="Output parquet file path",
    )

    args = parser.parse_args()
    export_h4_data(args.db_path, args.output)


if __name__ == "__main__":
    main()
