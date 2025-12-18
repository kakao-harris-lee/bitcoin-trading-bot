import pandas as pd
import numpy as np

from trading_engine_v2.modules.sideways_v1_strategy import SideWaysV1Strategy
from trading_engine_v2.modules.strategies.sideways_v2 import SideWaysV2Strategy


def _make_ohlcv_df(n: int = 80) -> pd.DataFrame:
    # Stable-ish series; indicators will be overwritten in tests anyway.
    ts = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(100 + np.linspace(0, 1, n), index=ts)
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close.values,
            "high": (close * 1.002).values,
            "low": (close * 0.998).values,
            "close": close.values,
            "volume": np.full(n, 1000.0),
        }
    )
    return df


def test_sideways_v1_entry_rsi_bb_triggers_buy():
    strategy = SideWaysV1Strategy(strategy_config={"volatility_threshold": 0.08})
    df = _make_ohlcv_df()
    df_ind = strategy.add_indicators(df)

    i = 30
    # Force RSI+BB oversold setup.
    df_ind.loc[i, "rsi"] = 10
    df_ind.loc[i, "bb_position"] = 0.1
    # Ensure filters pass.
    df_ind.loc[i, "volatility_ratio_20"] = 0.01
    df_ind.loc[i, "atr"] = 1.0
    df_ind.loc[i, "atr_ma14"] = 1.0

    sig = strategy.generate_signal(df_ind, i)
    assert sig is not None
    assert sig["action"] == "buy"
    assert sig["fraction"] > 0
    assert sig.get("strategy") == "rsi_bb"


def test_sideways_v1_volatility_filter_blocks_entry():
    strategy = SideWaysV1Strategy(strategy_config={"volatility_threshold": 0.08})
    df = _make_ohlcv_df()
    df_ind = strategy.add_indicators(df)

    i = 30
    # Force entry conditions but fail volatility filter.
    df_ind.loc[i, "rsi"] = 10
    df_ind.loc[i, "bb_position"] = 0.1
    df_ind.loc[i, "volatility_ratio_20"] = 0.25  # > threshold
    df_ind.loc[i, "atr"] = 1.0
    df_ind.loc[i, "atr_ma14"] = 1.0

    sig = strategy.generate_signal(df_ind, i)
    assert sig is None


def test_sideways_v2_obv_downtrend_filter_blocks_entry():
    strategy = SideWaysV2Strategy(strategy_config={"obv_downtrend_threshold": -0.05})
    df = _make_ohlcv_df()
    df_ind = strategy.add_indicators(df)

    i = 30
    # Force RSI+BB entry conditions.
    df_ind.loc[i, "rsi"] = 10
    df_ind.loc[i, "bb_position"] = 0.1
    # Force OBV downtrend.
    df_ind.loc[i, "obv_slope"] = -0.2

    sig = strategy.generate_signal(df_ind, i)
    assert sig is None


def test_sideways_v2_entry_when_obv_not_downtrend():
    strategy = SideWaysV2Strategy(strategy_config={"obv_downtrend_threshold": -0.05})
    df = _make_ohlcv_df()
    df_ind = strategy.add_indicators(df)

    i = 30
    df_ind.loc[i, "rsi"] = 10
    df_ind.loc[i, "bb_position"] = 0.1
    df_ind.loc[i, "obv_slope"] = 0.0

    sig = strategy.generate_signal(df_ind, i)
    assert sig is not None
    assert sig["action"] == "buy"


def test_sideways_v1_exit_tp3_closes_position():
    strategy = SideWaysV1Strategy(strategy_config={"take_profit_3": 0.055})
    df = _make_ohlcv_df()

    # Precompute indicators and then force a profitable bar.
    df_ind = strategy.add_indicators(df)
    i = 31
    df_ind.loc[i, "close"] = 106.0
    df_ind.loc[i, "high"] = 106.5
    df_ind.loc[i, "low"] = 105.5

    strategy.in_position = True
    strategy.entry_price = 100.0
    strategy.hold_bars = 10
    # TP ladder 특성상 TP1/TP2를 이미 수행했다고 가정해야 TP3(전량 청산)가 바로 발생한다.
    strategy.partial_exits = 2

    sig = strategy.generate_signal(df_ind, i)
    assert sig is not None
    assert sig["action"] == "sell"
    assert sig["fraction"] == 1.0
