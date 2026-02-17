# trading/strategies/indicators.py
"""Technical indicators using OHLCV data from database."""
# pylint: disable=no-member,broad-exception-caught

from __future__ import annotations
import logging
import sqlite3
from pathlib import Path
import numpy as np
import talib

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
    source = _resolve_ohlcv_source(symbol)
    if source is None:
        return None
    db_path, table_name = source

    try:
        rows = _fetch_ohlcv_rows(db_path, table_name, periods)
        if len(rows) < 20:
            logger.warning("Insufficient data for %s: %d rows", symbol, len(rows))
            return None
        return _rows_to_ohlcv(rows)
    except Exception as e:
        logger.error("Failed to load OHLCV for %s: %s", symbol, e)
        return None


def _resolve_ohlcv_source(symbol: str) -> tuple[Path, str] | None:
    db_path = DB_MAPPING.get(symbol)
    table_name = TABLE_MAPPING.get(symbol)
    if not db_path or not table_name:
        logger.warning("No database mapping for %s", symbol)
        return None
    if not db_path.exists():
        logger.warning("Database not found: %s", db_path)
        return None
    return db_path, table_name


def _fetch_ohlcv_rows(db_path: Path, table_name: str, periods: int) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (periods,),
        )
        return cursor.fetchall()


def _rows_to_ohlcv(rows: list[tuple]) -> dict:
    chronological_rows = list(reversed(rows))
    return {
        "timestamp": [r[0] for r in chronological_rows],
        "open": np.array([r[1] for r in chronological_rows]),
        "high": np.array([r[2] for r in chronological_rows]),
        "low": np.array([r[3] for r in chronological_rows]),
        "close": np.array([r[4] for r in chronological_rows]),
        "volume": np.array([r[5] for r in chronological_rows]),
    }


def calculate_mfi(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  volume: np.ndarray, period: int = 14) -> float:
    """
    Calculate Money Flow Index (MFI).

    MFI = 100 - (100 / (1 + Money Flow Ratio))
    where Money Flow Ratio = Positive Money Flow / Negative Money Flow
    """
    if len(close) < period + 1:
        return 50.0  # Neutral default
    values = talib.MFI(
        np.asarray(high, dtype=np.float64),
        np.asarray(low, dtype=np.float64),
        np.asarray(close, dtype=np.float64),
        np.asarray(volume, dtype=np.float64),
        timeperiod=period,
    )
    last = values[-1]
    return float(last) if np.isfinite(last) else 50.0


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
    values = talib.ADX(
        np.asarray(high, dtype=np.float64),
        np.asarray(low, dtype=np.float64),
        np.asarray(close, dtype=np.float64),
        timeperiod=period,
    )
    last = values[-1]
    if not np.isfinite(last):
        return 0.0
    return float(min(100.0, max(0.0, last)))


def _calculate_true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    n = len(close)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    return tr


def _calculate_directional_movement(high: np.ndarray, low: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(high)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
    return plus_dm, minus_dm


def _wilder_ema(data: np.ndarray, period: int) -> np.ndarray:
    alpha = 1.0 / period
    result = np.zeros(len(data))
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def _calculate_directional_indices(
    atr: np.ndarray,
    smooth_plus_dm: np.ndarray,
    smooth_minus_dm: np.ndarray,
    period: int,
) -> tuple[np.ndarray, np.ndarray]:
    n = len(atr)
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    for i in range(period - 1, n):
        if atr[i] > 0:
            plus_di[i] = 100 * smooth_plus_dm[i] / atr[i]
            minus_di[i] = 100 * smooth_minus_dm[i] / atr[i]
    return plus_di, minus_di


def _calculate_dx(plus_di: np.ndarray, minus_di: np.ndarray, period: int) -> np.ndarray:
    n = len(plus_di)
    dx = np.zeros(n)
    for i in range(period - 1, n):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum
    return dx


def calculate_rsi(close: np.ndarray, period: int = 14) -> float:
    """
    Calculate Relative Strength Index (RSI).

    RSI = 100 - (100 / (1 + RS))
    where RS = Average Gain / Average Loss
    """
    if len(close) < period + 1:
        return 50.0  # Neutral default
    values = talib.RSI(np.asarray(close, dtype=np.float64), timeperiod=period)
    last = values[-1]
    return float(last) if np.isfinite(last) else 50.0


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
        logger.error("Indicator calculation failed for %s: %s", symbol, e)
        return None
