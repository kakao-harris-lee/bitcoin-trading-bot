"""ShortV1 Entry Strategy - extracted from ShortV1Task.

Implements IEntryStrategy protocol for short entry in bear markets.
Entry conditions: BEAR_STRONG regime + RSI overbought.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import (
    MarketContext,
    MarketData,
    Signal,
    TradingContext,
    BULLISH_NO_SHORT_REGIMES,
    SIDEWAYS_VOLATILE_REGIMES,
    BEAR_REGIMES,
)
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class ShortEntryParams:
    """Parameters for Short entry strategy.

    Supports both:
    1. Regime-based RSI Mean Reversion (Original Component)
    2. EMA/ADX Trend Following (Legacy ShortV1)
    """

    # MFI threshold for bear regime
    mfi_bear: float = 48.0
    mfi_bull: float = 52.0

    # ADX threshold for trend strength
    adx_trend: float = 20.0

    # RSI threshold for short entry (overbought)
    rsi_overbought: float = 70.0

    # Legacy ShortV1 Params (Trend Following)
    ema_fast: int = 68
    ema_slow: int = 128
    adx_min: float = 25.0
    require_death_cross: bool = False
    di_negative_dominant: bool = False
    require_adx_not_declining: bool = False

    # Optional: use params-based regime classification for entry filters
    use_param_regime: bool = False

    # Bypass all regime checks (for ablation study)
    regime_bypass: bool = False

    # Position sizing
    position_size: float = 0.01
    market: Literal["futures"] = "futures"


@entry_strategy(params_class=ShortEntryParams)
class ShortEntryStrategy:
    """Short entry strategy for bear markets.

    Enters short positions when:
    1. Market regime is BEAR_STRONG (MFI <= mfi_bear and ADX >= adx_trend)
       AND RSI is overbought (Mean Reversion)
    OR
    2. EMA Death Cross + Strong ADX (Trend Following, if enabled)

    Note: Returns Signal with side="sell" to open a short position.

    Implements IEntryStrategy protocol (structural subtyping).
    """

    def __init__(self, params: ShortEntryParams | None = None):
        """Initialize with entry parameters.

        Args:
            params: Entry parameters. Uses defaults if not provided.
        """
        self.params = params or ShortEntryParams()

    def check_entry(
        self,
        ctx: TradingContext,
    ) -> Signal | None:
        """Check entry conditions and return signal if criteria met.

        Safety filters (Binance Futures):
        - Skip if BULL regime (never short in bull market)
        - Allow BEAR regimes (BEAR_STRONG, BEAR_MODERATE)
        - Allow SIDEWAYS_FLAT/DOWN only with extreme volatility

        Args:
            ctx: Trading context containing market data and regime.

        Returns:
            Signal with side="sell" to open short if conditions met, None otherwise.
        """
        market_data = ctx.market
        context = ctx.regime
        symbol = market_data.symbol
        regime = self._resolve_regime(market_data, context)

        if not self.params.regime_bypass:
            if self._is_blocked_by_bullish_regime(regime):
                logger.debug(
                    f"{symbol}: Skipping short entry - bullish regime ({regime})"
                )
                return None

        legacy_signal = self._try_death_cross_entry(market_data)
        if legacy_signal is not None:
            return legacy_signal

        if not self.params.regime_bypass:
            # === SAFETY FILTER 2: SIDEWAYS requires extreme volatility ===
            # Only short in SIDEWAYS_FLAT/DOWN if market is volatile
            if not self._passes_sideways_volatility_gate(regime, context):
                logger.debug(
                    f"{symbol}: Skipping short entry - SIDEWAYS without "
                    f"extreme volatility ({context.volatility_score*100:.2f}%)"
                )
                return None

            # === Regime check ===
            # BEAR_STRONG, BEAR_MODERATE: Always allow
            # SIDEWAYS_FLAT, SIDEWAYS_DOWN: Only if extreme volatility (checked above)
            if not self._should_enter(regime, context.is_extreme_volatility):
                return None

        # Short when RSI is overbought in bear market
        if market_data.rsi > self.params.rsi_overbought:
            return self._build_mean_reversion_signal(market_data, regime)

        return None

    def _resolve_regime(self, market_data: MarketData, context: MarketContext) -> str:
        regime = context.regime
        if self.params.use_param_regime:
            regime = self._classify_regime(market_data.mfi, market_data.adx)
        return regime

    def _is_blocked_by_bullish_regime(self, regime: str) -> bool:
        if regime not in BULLISH_NO_SHORT_REGIMES:
            return False
        return not self.params.require_death_cross

    def _try_death_cross_entry(self, market_data: MarketData) -> Signal | None:
        if not self.params.require_death_cross:
            return None

        inds = market_data.indicators or {}
        ema_fast = inds.get("ema_fast")
        ema_slow = inds.get("ema_slow")
        plus_di = inds.get("plus_di")
        minus_di = inds.get("minus_di")
        adx_slope = inds.get("adx_slope", 0)

        if ema_fast is None or ema_slow is None:
            return None

        if not self._meets_death_cross_conditions(
            market_data=market_data,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            plus_di=plus_di,
            minus_di=minus_di,
            adx_slope=adx_slope,
        ):
            return None

        reason = f"ShortV1 Trend Entry: EMA Dead Cross, ADX={market_data.adx:.1f}"
        return Signal(
            symbol=market_data.symbol,
            side="sell",
            market=self.params.market,
            quantity=self.params.position_size,
            reason=reason,
        )

    def _meets_death_cross_conditions(
        self,
        market_data: MarketData,
        ema_fast: float,
        ema_slow: float,
        plus_di: float | None,
        minus_di: float | None,
        adx_slope: float,
    ) -> bool:
        is_death_cross = ema_fast < ema_slow
        is_strong_adx = market_data.adx >= self.params.adx_min
        is_di_bearish = self._is_di_bearish(plus_di, minus_di)
        is_adx_stable = self._is_adx_stable(adx_slope)
        return is_death_cross and is_strong_adx and is_di_bearish and is_adx_stable

    def _is_di_bearish(self, plus_di: float | None, minus_di: float | None) -> bool:
        if not self.params.di_negative_dominant:
            return True
        if plus_di is None or minus_di is None:
            return True
        return minus_di > plus_di

    def _is_adx_stable(self, adx_slope: float) -> bool:
        if not self.params.require_adx_not_declining:
            return True
        return adx_slope >= -1.0

    def _passes_sideways_volatility_gate(
        self,
        regime: str,
        context: MarketContext,
    ) -> bool:
        if regime not in SIDEWAYS_VOLATILE_REGIMES:
            return True
        return context.is_extreme_volatility

    def _build_mean_reversion_signal(self, market_data: MarketData, regime: str) -> Signal:
        reason = f"ShortV1 entry: {regime}, RSI={market_data.rsi:.1f} (overbought)"
        logger.info(f"{market_data.symbol}: {reason}")
        return Signal(
            symbol=market_data.symbol,
            side="sell",
            market=self.params.market,
            quantity=self.params.position_size,
            reason=reason,
        )

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify regime using ShortEntryParams thresholds.

        This is intentionally simpler than the global regime classification
        and is used only when use_param_regime=True.
        """
        p = self.params
        if mfi >= p.mfi_bull and adx >= p.adx_trend:
            return "BULL_MODERATE"
        if mfi >= p.mfi_bull:
            return "SIDEWAYS_UP"
        if mfi <= p.mfi_bear and adx >= p.adx_trend:
            return "BEAR_STRONG"
        if mfi <= p.mfi_bear:
            return "BEAR_MODERATE"
        return "SIDEWAYS_FLAT"

    def _should_enter(self, regime: str, is_extreme_volatility: bool = False) -> bool:
        """Check if regime is suitable for short entry.

        Allowed regimes:
        - BEAR_STRONG: Always allowed (strong bearish trend)
        - BEAR_MODERATE: Always allowed (moderate bearish trend)
        - SIDEWAYS_FLAT/DOWN: Only with extreme volatility

        Args:
            regime: Market regime classification.
            is_extreme_volatility: Whether volatility exceeds threshold.

        Returns:
            True if should enter short position.
        """
        # BEAR regimes: Always allow shorting
        if regime in BEAR_REGIMES:
            return True

        # SIDEWAYS_FLAT/DOWN: Only with extreme volatility
        if regime in SIDEWAYS_VOLATILE_REGIMES:
            return is_extreme_volatility

        # BULL regimes and SIDEWAYS_UP: Never short
        return False
