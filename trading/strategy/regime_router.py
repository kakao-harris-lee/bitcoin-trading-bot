"""Operational regime routing for live/paper trading.

Goal: decide which strategy should be active based on recent daily market regime.

This intentionally mirrors the simple V35-style regime thresholds used elsewhere:
- MFI drives bull/sideways/bear bias
- ADX drives trend strength

We keep this module dependency-light so it can run inside docker-compose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional, TYPE_CHECKING

import pandas as pd

from core.data_loader import DataLoader
from trading.indicators import technical as ta

if TYPE_CHECKING:
    from trading.data.data_cache import DataCache

MarketState = Literal[
    "BULL_STRONG",
    "BULL_MODERATE",
    "SIDEWAYS_BULL",
    "SIDEWAYS_NEUTRAL",
    "SIDEWAYS_BEAR",
    "BEAR_MODERATE",
    "BEAR_STRONG",
]

Regime = Literal["BULL", "SIDEWAYS", "BEAR"]


@dataclass(frozen=True)
class RegimeDecision:
    market_state: MarketState
    regime: Regime
    upbit_strategy: str | None
    binance_strategy: str | None


class RegimeRouter:
    def __init__(
        self,
        lookback_days: int = 180,
        mfi_period: int = 14,
        adx_period: int = 14,
        # Thresholds (match earlier router/backtest logic)
        mfi_bull: float = 52.0,
        mfi_bear: float = 48.0,
        adx_strong: float = 25.0,
        adx_trend: float = 20.0,
        adx_weak: float = 15.0,
        # Operational policy knobs (kept simple for docker-compose)
        bull_policy: str = "v35",
        sideways_policy: str = "sideways_v2",
        sideways_bear_policy: str | None = None,
        bear_moderate_policy: str | None = None,
        bear_strong_policy: str | None = None,
        binance_gate_mode: str = "bear_only",
        binance_policy: str = "short_v1",  # 'short_v1' | 'h4_short' | 'hold'
        # Data cache for efficient data loading
        data_cache: Optional["DataCache"] = None,
    ):
        self.lookback_days = int(lookback_days)
        self.mfi_period = int(mfi_period)
        self.adx_period = int(adx_period)

        self.mfi_bull = float(mfi_bull)
        self.mfi_bear = float(mfi_bear)
        self.adx_strong = float(adx_strong)
        self.adx_trend = float(adx_trend)
        self.adx_weak = float(adx_weak)

        # Policies
        self.bull_policy = str(bull_policy)
        self.sideways_policy = str(sideways_policy)
        self.sideways_bear_policy = str(sideways_bear_policy) if sideways_bear_policy is not None else None
        self.bear_moderate_policy = str(bear_moderate_policy) if bear_moderate_policy is not None else None
        self.bear_strong_policy = str(bear_strong_policy) if bear_strong_policy is not None else None
        self.binance_gate_mode = str(binance_gate_mode)
        self.binance_policy = str(binance_policy)

        # Data cache
        self.data_cache = data_cache

    def get_recent_daily_df(self, end_dt: datetime | None = None) -> pd.DataFrame:
        """Load daily candles for lookback window.

        Uses DataCache if available, otherwise falls back to direct DataLoader.
        Returns a DataFrame with columns: timestamp, open, high, low, close, volume
        """
        # Try cache first
        if self.data_cache:
            df = self.data_cache.get('day', periods=self.lookback_days)
            if df is not None and len(df) > 0:
                return df

        # Fallback to direct DataLoader
        if end_dt is None:
            end_dt = datetime.utcnow()

        start_date = (end_dt - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")

        with DataLoader() as loader:
            df = loader.load_timeframe(
                "day",
                start_date=start_date,
                end_date=end_date,
            )

        return df

    def decide_from_market_state(self, market_state: MarketState) -> RegimeDecision:
        regime: Regime
        if market_state.startswith("BULL"):
            regime = "BULL"
        elif market_state.startswith("SIDEWAYS"):
            regime = "SIDEWAYS"
        else:
            regime = "BEAR"

        # ------------------------
        # Upbit strategy selection
        # ------------------------
        upbit_strategy: str | None
        if regime == "BULL":
            if self.bull_policy == "hold_long":
                upbit_strategy = "bull_hold"
            elif self.bull_policy == "v35":
                upbit_strategy = "v35"
            elif self.bull_policy == "sideways_v2":
                upbit_strategy = "sideways_v2"
            elif self.bull_policy == "hold":
                upbit_strategy = None
            else:
                upbit_strategy = "v35"

        elif regime == "SIDEWAYS":
            policy = self.sideways_policy
            if market_state == "SIDEWAYS_BEAR" and self.sideways_bear_policy is not None:
                policy = self.sideways_bear_policy

            if policy == "sideways_v2":
                upbit_strategy = "sideways_v2"
            elif policy == "h4_conservative":
                upbit_strategy = "h4_conservative"
            elif policy == "v35":
                upbit_strategy = "v35"
            elif policy == "hold":
                upbit_strategy = None
            else:
                upbit_strategy = "sideways_v2"

        else:
            # BEAR defaults to hold (avoid longs), unless overridden
            policy: str | None = None
            if market_state == "BEAR_STRONG":
                policy = self.bear_strong_policy
            elif market_state == "BEAR_MODERATE":
                policy = self.bear_moderate_policy

            if policy == "v35":
                upbit_strategy = "v35"
            elif policy == "sideways_v2":
                upbit_strategy = "sideways_v2"
            elif policy == "h4_conservative":
                upbit_strategy = "h4_conservative"
            else:
                upbit_strategy = None

        # --------------------------
        # Binance strategy selection
        # --------------------------
        allow_binance = False
        if self.binance_gate_mode == "bear_only":
            allow_binance = regime == "BEAR"
        elif self.binance_gate_mode == "sideways_and_bear":
            allow_binance = regime in {"SIDEWAYS", "BEAR"}
        elif self.binance_gate_mode == "bear_or_sideways_bear":
            allow_binance = (regime == "BEAR") or (market_state == "SIDEWAYS_BEAR")
        elif self.binance_gate_mode == "bear_strong_only":
            allow_binance = market_state == "BEAR_STRONG"
        elif self.binance_gate_mode == "bear_strong_or_sideways_bear":
            allow_binance = market_state in {"BEAR_STRONG", "SIDEWAYS_BEAR"}
        elif self.binance_gate_mode == "always":
            allow_binance = True
        else:
            allow_binance = regime == "BEAR"

        # binance_policy에 따라 전략 선택
        binance_strategy: str | None = None
        if allow_binance:
            if self.binance_policy == "hold":
                binance_strategy = None
            elif self.binance_policy == "h4_short":
                binance_strategy = "h4_short"
            elif self.binance_policy == "short_v2":
                binance_strategy = "short_v2"
            else:
                binance_strategy = "short_v1"

        return RegimeDecision(
            market_state=market_state,
            regime=regime,
            upbit_strategy=upbit_strategy,
            binance_strategy=binance_strategy,
        )

    def classify_from_values(self, mfi: float, adx: float) -> MarketState:
        """Deterministic mapping for unit tests and for low-dependency routing."""
        if pd.isna(mfi) or pd.isna(adx):
            # Conservative default (avoid entering) when indicators are not ready.
            return "SIDEWAYS_NEUTRAL"

        if mfi >= self.mfi_bull:
            if adx >= self.adx_strong:
                return "BULL_STRONG"
            if adx >= self.adx_trend:
                return "BULL_MODERATE"
            return "SIDEWAYS_BULL"

        if mfi <= self.mfi_bear:
            if adx >= self.adx_trend:
                return "BEAR_STRONG"
            if adx >= self.adx_weak:
                return "BEAR_MODERATE"
            return "SIDEWAYS_BEAR"

        return "SIDEWAYS_NEUTRAL"

    def classify_market_state(self, df_day: pd.DataFrame) -> MarketState:
        df = df_day.copy()
        if len(df) < max(self.mfi_period, self.adx_period) + 5:
            return "SIDEWAYS_NEUTRAL"

        df["mfi"] = _calc_mfi(df, period=self.mfi_period)
        df["adx"] = _calc_adx(df, period=self.adx_period)

        mfi = float(df["mfi"].iloc[-1])
        adx = float(df["adx"].iloc[-1])
        return self.classify_from_values(mfi=mfi, adx=adx)

    def recommend(self, df_day: pd.DataFrame) -> RegimeDecision:
        market_state = self.classify_market_state(df_day)
        return self.decide_from_market_state(market_state)


def _calc_mfi(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate MFI using talib."""
    return ta.mfi(df["high"], df["low"], df["close"], df["volume"], period=period)


def _calc_adx(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate ADX using talib.

    Note: talib uses EMA smoothing (more accurate) vs the previous
    rolling mean implementation. This may result in slightly different
    values but is the industry-standard calculation.
    """
    adx_val, _, _ = ta.adx(df["high"], df["low"], df["close"], period=period)
    return adx_val.fillna(0.0)
