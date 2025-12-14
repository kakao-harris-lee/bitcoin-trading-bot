import pandas as pd
import numpy as np

from trading_engine_v2.scripts.optimize_short_v1 import (
    ShortV1StrategyOptimized,
    QuickBacktester,
    _normalize_config,
)


def _sample_df(n: int = 300) -> pd.DataFrame:
    # 단조 증가 + 노이즈: 지표 계산이 NaN만 나오지 않도록 구성
    rng = np.random.default_rng(42)
    close = np.linspace(100, 130, n) + rng.normal(0, 0.5, n)
    high = close + rng.normal(0.2, 0.2, n)
    low = close - rng.normal(0.2, 0.2, n)
    open_ = close + rng.normal(0, 0.2, n)
    volume = rng.integers(100, 200, n)

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=n, freq="4h"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    return df


def test_add_indicators_creates_columns():
    df = _sample_df()
    cfg = {
        "ema_fast": 20,
        "ema_slow": 50,
        "adx_threshold": 20,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "use_death_cross": True,
        "use_rsi_overbought": True,
        "use_bb_rejection": True,
        "use_trend_follow": True,
        "entry_mode": "any",
        "min_signals": 1,
        "position_size": 0.3,
        "leverage": 3,
        "max_hold_bars": 50,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "bb_upper_threshold": 0.95,
        "slope_threshold": -0.5,
    }

    strat = ShortV1StrategyOptimized(cfg)
    out = strat.add_indicators(df)

    for col in [
        "ema_fast",
        "ema_slow",
        "death_cross",
        "golden_cross",
        "adx",
        "rsi",
        "bb_upper",
        "bb_lower",
        "bb_pct",
        "momentum",
    ]:
        assert col in out.columns


def test_quick_backtester_returns_metrics_keys():
    df = _sample_df()
    cfg = {
        "ema_fast": 20,
        "ema_slow": 50,
        "adx_threshold": 20,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "use_death_cross": True,
        "use_rsi_overbought": False,
        "use_bb_rejection": False,
        "use_trend_follow": True,
        "entry_mode": "any",
        "min_signals": 1,
        "position_size": 0.3,
        "leverage": 3,
        "max_hold_bars": 50,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "bb_upper_threshold": 0.95,
        "slope_threshold": -0.5,
    }

    strat = ShortV1StrategyOptimized(cfg)
    bt = QuickBacktester(leverage=3)
    res = bt.run(df, strat)

    for key in ["total_return", "total_trades", "win_rate", "sharpe_ratio", "max_drawdown", "profit_factor"]:
        assert key in res


def test_normalize_config_drops_unused_params():
    cfg = {
        "use_rsi_overbought": False,
        "rsi_overbought": 75,
        "use_bb_rejection": False,
        "bb_upper_threshold": 0.93,
        "use_trend_follow": False,
        "slope_threshold": -0.5,
    }

    normalized = _normalize_config(cfg)
    assert "rsi_overbought" not in normalized
    assert "bb_upper_threshold" not in normalized
    assert "slope_threshold" not in normalized
