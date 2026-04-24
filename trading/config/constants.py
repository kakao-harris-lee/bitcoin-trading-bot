"""Trading system constants.

Centralizes hardcoded values used across the trading system.
Change values here instead of hunting through multiple files.
"""


class FeeRates:
    """Exchange fee rates."""

    SPOT = 0.0005  # 0.05% (0.1% with BNB discount)
    SPOT_SLIPPAGE = 0.0  # Minimal for spot


class TimePeriods:
    """Time-based constants (in candles for hourly timeframe)."""

    # LSTM/RF model requirements
    RF_HISTORY_WINDOW = 720  # Rolling window for LiveScaler (30 days)
    MIN_HISTORY_REQUIRED = 60  # Minimum candles for prediction

    # Backtest settings
    BACKTEST_WARMUP = 200  # Warmup period before first trade

    # Risk management timing
    STOP_LOSS_COOLDOWN = 24  # 1 day cooldown after stop loss
    CONSECUTIVE_LOSS_PAUSE = 48  # 2 day pause after consecutive losses

    # Technical indicator periods
    EMA_200_PERIOD = 200
    EMA_120_PERIOD = 120

    # Metrics calculation
    TRADING_DAYS_PER_YEAR = 252  # For annualized Sharpe ratio
