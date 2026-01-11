# trading/strategies/indicators.py
"""Technical indicators using OHLCV data from database."""
from __future__ import annotations
import logging
import sqlite3
from pathlib import Path
from functools import lru_cache
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Database paths
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DB_MAPPING = {
    "BTC": DATA_DIR / "binance_bitcoin.db",
    "ETH": DATA_DIR / "binance_ethereum.db",
    "SOL": DATA_DIR / "binance_solana.db",
}
TABLE_MAPPING = {
    "BTC": "binance_minute60",
    "ETH": "ethereum_minute60",
    "SOL": "solana_minute60",
}


def load_ohlcv(symbol: str, periods: int = 100) -> dict | None:
    """Load recent OHLCV data from database."""
    db_path = DB_MAPPING.get(symbol)
    table_name = TABLE_MAPPING.get(symbol)

    if not db_path or not table_name:
        logger.warning(f"No database mapping for {symbol}")
        return None

    if not db_path.exists():
        logger.warning(f"Database not found: {db_path}")
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            ORDER BY timestamp DESC
            LIMIT ?
        """, (periods,))
        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 20:
            logger.warning(f"Insufficient data for {symbol}: {len(rows)} rows")
            return None

        # Reverse to chronological order (oldest first)
        rows = list(reversed(rows))

        return {
            "timestamp": [r[0] for r in rows],
            "open": np.array([r[1] for r in rows]),
            "high": np.array([r[2] for r in rows]),
            "low": np.array([r[3] for r in rows]),
            "close": np.array([r[4] for r in rows]),
            "volume": np.array([r[5] for r in rows]),
        }
    except Exception as e:
        logger.error(f"Failed to load OHLCV for {symbol}: {e}")
        return None


def calculate_mfi(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  volume: np.ndarray, period: int = 14) -> float:
    """
    Calculate Money Flow Index (MFI).

    MFI = 100 - (100 / (1 + Money Flow Ratio))
    where Money Flow Ratio = Positive Money Flow / Negative Money Flow
    """
    if len(close) < period + 1:
        return 50.0  # Neutral default

    # Typical Price
    typical_price = (high + low + close) / 3

    # Raw Money Flow
    raw_money_flow = typical_price * volume

    # Calculate positive and negative money flow
    positive_flow = 0.0
    negative_flow = 0.0

    for i in range(-period, 0):
        if typical_price[i] > typical_price[i - 1]:
            positive_flow += raw_money_flow[i]
        elif typical_price[i] < typical_price[i - 1]:
            negative_flow += raw_money_flow[i]

    # Avoid division by zero
    if negative_flow < 0.0001:
        return 100.0 if positive_flow > 0 else 50.0

    money_flow_ratio = positive_flow / negative_flow
    mfi = 100 - (100 / (1 + money_flow_ratio))

    return float(mfi)


def calculate_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  period: int = 14) -> float:
    """
    Calculate Average Directional Index (ADX).

    ADX measures trend strength (0-100).
    > 25: Strong trend
    < 20: Weak/no trend
    """
    if len(close) < period * 2:
        return 0.0  # No trend default

    n = len(close)

    # True Range
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )

    # Directional Movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Smoothed averages using Wilder's EMA (alpha = 1/period)
    def wilder_ema(data: np.ndarray, period: int) -> np.ndarray:
        alpha = 1.0 / period
        result = np.zeros(len(data))
        result[period - 1] = np.mean(data[:period])  # SMA for first value
        for i in range(period, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    atr = wilder_ema(tr, period)
    smooth_plus_dm = wilder_ema(plus_dm, period)
    smooth_minus_dm = wilder_ema(minus_dm, period)

    # +DI and -DI
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    for i in range(period - 1, n):
        if atr[i] > 0:
            plus_di[i] = 100 * smooth_plus_dm[i] / atr[i]
            minus_di[i] = 100 * smooth_minus_dm[i] / atr[i]

    # DX
    dx = np.zeros(n)
    for i in range(period - 1, n):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum

    # ADX (smoothed DX using Wilder EMA)
    adx_smooth = wilder_ema(dx, period)

    # Return the latest ADX value (clamped to 0-100)
    return float(min(100, max(0, adx_smooth[-1])))


def calculate_rsi(close: np.ndarray, period: int = 14) -> float:
    """
    Calculate Relative Strength Index (RSI).

    RSI = 100 - (100 / (1 + RS))
    where RS = Average Gain / Average Loss
    """
    if len(close) < period + 1:
        return 50.0  # Neutral default

    # Calculate price changes
    deltas = np.diff(close[-(period + 1):])

    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)

    # Minimum movement threshold (0.01% of price)
    min_movement = np.mean(close[-period:]) * 0.0001

    if avg_gain < min_movement and avg_loss < min_movement:
        return 50.0  # No significant movement
    elif avg_loss < min_movement:
        return 100.0  # Only gains
    else:
        rs = avg_gain / max(avg_loss, min_movement)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)


def get_indicators(symbol: str, periods: int = 100) -> dict | None:
    """
    Get all technical indicators for a symbol.

    Returns dict with: mfi, adx, rsi, close, timestamp
    """
    ohlcv = load_ohlcv(symbol, periods)
    if ohlcv is None:
        return None

    try:
        mfi = calculate_mfi(
            ohlcv["high"], ohlcv["low"], ohlcv["close"],
            ohlcv["volume"], period=14
        )
        adx = calculate_adx(
            ohlcv["high"], ohlcv["low"], ohlcv["close"],
            period=14
        )
        rsi = calculate_rsi(ohlcv["close"], period=14)

        return {
            "mfi": mfi,
            "adx": adx,
            "rsi": rsi,
            "close": float(ohlcv["close"][-1]),
            "timestamp": ohlcv["timestamp"][-1],
        }
    except Exception as e:
        logger.error(f"Indicator calculation failed for {symbol}: {e}")
        return None
