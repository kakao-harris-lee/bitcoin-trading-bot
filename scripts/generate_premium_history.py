#!/usr/bin/env python3
"""
Generate Historical Kimchi Premium Data

Calculates Kimchi Premium for each asset (BTC, ETH, SOL, XRP) by comparing
Upbit KRW prices with Binance USD prices adjusted by FX rates.

Formula: premium_pct = (upbit_krw / (binance_usd * fx_rate) - 1) * 100

Usage:
    python scripts/generate_premium_history.py
"""

import sqlite3
from pathlib import Path
import pandas as pd

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Asset configurations
ASSETS = {
    "bitcoin": {
        "symbol": "BTC",
        "upbit_db": "upbit_bitcoin.db",
        "upbit_table": "bitcoin_day",
        "binance_db": "binance_bitcoin.db",
        "binance_table": "binance_day",  # BTC uses binance_day
    },
    "ethereum": {
        "symbol": "ETH",
        "upbit_db": "upbit_ethereum.db",
        "upbit_table": "ethereum_day",
        "binance_db": "binance_ethereum.db",
        "binance_table": "ethereum_day",  # Altcoins use {asset}_day
    },
    "solana": {
        "symbol": "SOL",
        "upbit_db": "upbit_solana.db",
        "upbit_table": "solana_day",
        "binance_db": "binance_solana.db",
        "binance_table": "solana_day",
    },
    "xrp": {
        "symbol": "XRP",
        "upbit_db": "upbit_xrp.db",
        "upbit_table": "xrp_day",
        "binance_db": "binance_xrp.db",
        "binance_table": "xrp_day",
    },
}


def load_upbit_data(db_path: Path, table_name: str) -> pd.DataFrame:
    """Load Upbit price data from SQLite database."""
    conn = sqlite3.connect(db_path)
    query = f"""
        SELECT timestamp, trade_price as close_krw
        FROM {table_name}
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    # Extract date from timestamp (format: 2020-01-01T09:00:00)
    df["date"] = df["timestamp"].str[:10]
    df = df.drop(columns=["timestamp"])

    return df


def load_binance_data(db_path: Path, table_name: str) -> pd.DataFrame:
    """Load Binance price data from SQLite database."""
    conn = sqlite3.connect(db_path)
    query = f"""
        SELECT timestamp, close as close_usd
        FROM {table_name}
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    # Extract date from timestamp (format: 2020-01-01T00:00:00)
    df["date"] = df["timestamp"].str[:10]
    df = df.drop(columns=["timestamp"])

    return df


def load_fx_rates(db_path: Path) -> pd.DataFrame:
    """Load USD/KRW exchange rates from SQLite database."""
    conn = sqlite3.connect(db_path)
    query = """
        SELECT date, rate as fx_rate
        FROM usd_krw
        ORDER BY date
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    return df


def calculate_premium(
    upbit_df: pd.DataFrame,
    binance_df: pd.DataFrame,
    fx_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate Kimchi Premium by merging price data and FX rates.

    Formula: premium_pct = (upbit_krw / (binance_usd * fx_rate) - 1) * 100
    """
    # Merge Upbit and Binance on date
    merged = pd.merge(upbit_df, binance_df, on="date", how="inner")

    # Merge with FX rates
    merged = pd.merge(merged, fx_df, on="date", how="inner")

    # Calculate premium
    merged["upbit_usd"] = merged["close_krw"] / merged["fx_rate"]
    merged["premium_pct"] = (
        (merged["close_krw"] / (merged["close_usd"] * merged["fx_rate"])) - 1
    ) * 100

    # Rename columns for output
    result = merged.rename(columns={
        "close_krw": "upbit_krw",
        "close_usd": "binance_usd",
    })

    # Select and order columns
    result = result[["date", "upbit_krw", "binance_usd", "fx_rate", "premium_pct", "upbit_usd"]]

    return result.sort_values("date").reset_index(drop=True)


def insert_premium_data(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame) -> None:
    """Insert premium data into the database."""
    table_name = f"{symbol.lower()}_premium"

    # Drop existing table and recreate with proper schema
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.execute(f"""
        CREATE TABLE {table_name} (
            date TEXT PRIMARY KEY,
            upbit_krw REAL,
            binance_usd REAL,
            fx_rate REAL,
            premium_pct REAL,
            upbit_usd REAL
        )
    """)

    # Insert data row by row to maintain PRIMARY KEY constraint
    for _, row in df.iterrows():
        conn.execute(
            f"""INSERT INTO {table_name}
                (date, upbit_krw, binance_usd, fx_rate, premium_pct, upbit_usd)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (row["date"], row["upbit_krw"], row["binance_usd"],
             row["fx_rate"], row["premium_pct"], row["upbit_usd"])
        )
    conn.commit()


def print_statistics(symbol: str, df: pd.DataFrame) -> None:
    """Print summary statistics for premium data."""
    print(f"\n{'='*60}")
    print(f"{symbol} Premium Statistics")
    print(f"{'='*60}")
    print(f"  Date Range: {df['date'].min()} to {df['date'].max()}")
    print(f"  Total Days: {len(df)}")
    print(f"\n  Premium (%):")
    print(f"    Mean:   {df['premium_pct'].mean():>8.2f}%")
    print(f"    Median: {df['premium_pct'].median():>8.2f}%")
    print(f"    Min:    {df['premium_pct'].min():>8.2f}%")
    print(f"    Max:    {df['premium_pct'].max():>8.2f}%")
    print(f"    Std:    {df['premium_pct'].std():>8.2f}%")
    print(f"\n  Average Prices:")
    print(f"    Upbit KRW:   {df['upbit_krw'].mean():>15,.0f} KRW")
    print(f"    Binance USD: {df['binance_usd'].mean():>15,.2f} USD")
    print(f"    FX Rate:     {df['fx_rate'].mean():>15,.2f} KRW/USD")


def main():
    """Main function to generate premium history for all assets."""
    print("=" * 60)
    print("Generating Historical Kimchi Premium Data")
    print("=" * 60)

    # Load FX rates (shared across all assets)
    fx_path = DATA_DIR / "fx_rates.db"
    if not fx_path.exists():
        print(f"ERROR: FX rates database not found: {fx_path}")
        return

    fx_df = load_fx_rates(fx_path)
    print(f"\nLoaded {len(fx_df)} FX rate records")
    print(f"  Date Range: {fx_df['date'].min()} to {fx_df['date'].max()}")

    # Create output database
    output_db = DATA_DIR / "premium_history.db"
    output_conn = sqlite3.connect(output_db)

    results = {}

    for asset_name, config in ASSETS.items():
        symbol = config["symbol"]
        print(f"\n{'-'*60}")
        print(f"Processing {symbol} ({asset_name})")
        print(f"{'-'*60}")

        # Check if databases exist
        upbit_path = DATA_DIR / config["upbit_db"]
        binance_path = DATA_DIR / config["binance_db"]

        if not upbit_path.exists():
            print(f"  WARNING: Upbit database not found: {upbit_path}")
            continue

        if not binance_path.exists():
            print(f"  WARNING: Binance database not found: {binance_path}")
            continue

        try:
            # Load price data
            upbit_df = load_upbit_data(upbit_path, config["upbit_table"])
            print(f"  Upbit records: {len(upbit_df)}")

            binance_df = load_binance_data(binance_path, config["binance_table"])
            print(f"  Binance records: {len(binance_df)}")

            # Calculate premium
            premium_df = calculate_premium(upbit_df, binance_df, fx_df)
            print(f"  Merged records: {len(premium_df)}")

            if len(premium_df) == 0:
                print(f"  WARNING: No overlapping dates found for {symbol}")
                continue

            # Insert data (creates table with proper schema)
            insert_premium_data(output_conn, symbol, premium_df)

            results[symbol] = premium_df

        except Exception as e:
            print(f"  ERROR processing {symbol}: {e}")
            continue

    output_conn.close()

    # Print statistics for all successful assets
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if not results:
        print("No premium data was generated.")
        return

    for symbol, df in results.items():
        print_statistics(symbol, df)

    print(f"\n{'='*60}")
    print(f"Premium history saved to: {output_db}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
