"""V35 Entry Strategy - extracted from V35LongTask.

Implements IEntryStrategy protocol for V35 long-only entry logic.
Entry conditions match the original V35LongStrategy with full momentum signals:
- BULL_STRONG/BULL_MODERATE: MACD crossover + RSI threshold
- SIDEWAYS_UP: Breakout with volume confirmation
- SIDEWAYS_FLAT/DOWN: Range support bounce + RSI oversold
- BEAR states: Conservative entry (extreme oversold only)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from .models import MarketData, Signal
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class V35EntryParams:
    """Parameters for V35 entry strategy.

    Defaults aligned with Optuna-optimized config from v35_long.json.
    """

    # MFI thresholds for regime classification (from v35_long.json)
    mfi_bull_strong: float = 54.0
    mfi_bull_moderate: float = 54.0
    mfi_sideways_up: float = 49.0
    mfi_bear_moderate: float = 41.0
    mfi_bear_strong: float = 34.0

    # ADX thresholds for trend strength
    adx_strong_trend: float = 25.0
    adx_moderate_trend: float = 18.0

    # Momentum entry conditions (BULL states)
    momentum_rsi_bull_strong: float = 57.0
    momentum_rsi_bull_moderate: float = 55.0

    # Breakout entry conditions (SIDEWAYS_UP)
    breakout_threshold: float = 0.007  # 0.7% above resistance
    breakout_volume_mult: float = 1.23  # Volume must be 1.23x average

    # Range entry conditions (SIDEWAYS_FLAT/DOWN)
    range_support_zone: float = 0.14  # Bottom 14% of range
    range_rsi_oversold: float = 38.0

    # Conservative entry conditions (BEAR states)
    conservative_rsi_threshold: float = 30.0
    conservative_stoch_threshold: float = 20.0
    conservative_support_zone: float = 0.10  # Bottom 10% of range

    # Position sizing
    position_size: float = 0.5
    conservative_position_mult: float = 0.5  # Half size for BEAR entries

    market: Literal["spot", "futures"] = "spot"


@entry_strategy(params_class=V35EntryParams)
class V35EntryStrategy:
    """V35 Long entry strategy with full momentum signal logic.

    Matches original V35LongStrategy entry logic exactly:
    - BULL_STRONG: MACD crossover + RSI > 57 (aggressive momentum)
    - BULL_MODERATE: MACD crossover + RSI > 55 (moderate momentum)
    - SIDEWAYS_UP: Price breakout above 20-period high with volume
    - SIDEWAYS_FLAT/DOWN: Support bounce with RSI oversold
    - BEAR states: Conservative entry on extreme oversold only

    Implements IEntryStrategy protocol (structural subtyping).
    """

    def __init__(self, params: V35EntryParams | None = None):
        """Initialize with entry parameters.

        Args:
            params: Entry parameters. Uses defaults if not provided.
        """
        self.params = params or V35EntryParams()

    def check_entry(self, market_data: MarketData) -> Signal | None:
        """Check entry conditions and return signal if entry criteria met.

        Routes to different entry strategies based on market regime:
        - BULL: Momentum entry (MACD + RSI)
        - SIDEWAYS_UP: Breakout entry
        - SIDEWAYS_FLAT/DOWN: Range entry
        - BEAR: Conservative entry

        Args:
            market_data: Current market state with indicators.

        Returns:
            Signal with side="buy" if entry conditions met, None otherwise.
        """
        regime = self._classify_regime(
            market_data.mfi,
            market_data.adx
        )

        # Route to appropriate entry strategy based on regime
        signal_data = None

        if regime == "BULL_STRONG":
            signal_data = self._momentum_entry(market_data, aggressive=True)
        elif regime == "BULL_MODERATE":
            signal_data = self._momentum_entry(market_data, aggressive=False)
        elif regime == "SIDEWAYS_UP":
            signal_data = self._breakout_entry(market_data)
        elif regime in ("SIDEWAYS_FLAT", "SIDEWAYS_DOWN"):
            signal_data = self._range_entry(market_data)
        elif regime in ("BEAR_MODERATE", "BEAR_STRONG"):
            signal_data = self._conservative_entry(market_data)

        if signal_data:
            reason = (
                f"V35 {signal_data['strategy']}: {regime}, "
                f"MFI={market_data.mfi:.1f}, ADX={market_data.adx:.1f}, "
                f"RSI={market_data.rsi:.1f}"
            )
            logger.info(f"{market_data.symbol}: {reason}")

            return Signal(
                symbol=market_data.symbol,
                side="buy",
                market=self.params.market,
                quantity=signal_data['quantity'],
                reason=reason,
            )

        return None

    def _momentum_entry(
        self,
        market_data: MarketData,
        aggressive: bool
    ) -> dict | None:
        """Momentum entry for BULL states.

        Requires MACD crossover (MACD > Signal) AND RSI above threshold.

        Args:
            market_data: Current market state.
            aggressive: True for BULL_STRONG (lower RSI threshold).

        Returns:
            Entry signal dict or None.
        """
        p = self.params

        # Check MACD crossover (MACD above signal line)
        if market_data.macd <= market_data.macd_signal:
            return None

        # Check RSI threshold
        rsi_threshold = (
            p.momentum_rsi_bull_strong if aggressive
            else p.momentum_rsi_bull_moderate
        )

        if market_data.rsi <= rsi_threshold:
            return None

        strategy_name = "MOMENTUM_STRONG" if aggressive else "MOMENTUM_MODERATE"

        return {
            'strategy': strategy_name,
            'quantity': p.position_size,
        }

    def _breakout_entry(self, market_data: MarketData) -> dict | None:
        """Breakout entry for SIDEWAYS_UP state.

        Requires price above resistance (20-period high) with volume confirmation.

        Args:
            market_data: Current market state.

        Returns:
            Entry signal dict or None.
        """
        p = self.params

        # Need historical data for breakout detection
        if market_data.prev_high_20 <= 0 or market_data.avg_volume_20 <= 0:
            return None

        resistance = market_data.prev_high_20
        threshold = p.breakout_threshold

        # Check price breakout above resistance
        if market_data.close <= resistance * (1 + threshold):
            return None

        # Check volume confirmation
        if market_data.volume <= market_data.avg_volume_20 * p.breakout_volume_mult:
            return None

        return {
            'strategy': 'BREAKOUT_SIDEWAYS_UP',
            'quantity': p.position_size,
        }

    def _range_entry(self, market_data: MarketData) -> dict | None:
        """Range entry for SIDEWAYS_FLAT/DOWN states.

        Requires price near support (20-period low) with RSI oversold.

        Args:
            market_data: Current market state.

        Returns:
            Entry signal dict or None.
        """
        p = self.params

        # Need historical data for range detection
        if market_data.prev_low_20 <= 0 or market_data.prev_high_20 <= 0:
            return None

        support = market_data.prev_low_20
        resistance = market_data.prev_high_20
        range_height = resistance - support

        if range_height <= 0:
            return None

        # Check if price is in support zone (bottom X% of range)
        support_zone_top = support + range_height * p.range_support_zone
        if market_data.close >= support_zone_top:
            return None

        # Check RSI oversold
        if market_data.rsi >= p.range_rsi_oversold:
            return None

        return {
            'strategy': 'RANGE_SUPPORT',
            'quantity': p.position_size,
        }

    def _conservative_entry(self, market_data: MarketData) -> dict | None:
        """Conservative entry for BEAR states.

        Very strict conditions - only enter on extreme oversold with support.
        Uses smaller position size for risk management.

        Args:
            market_data: Current market state.

        Returns:
            Entry signal dict or None.
        """
        p = self.params

        # Very strict RSI condition
        if market_data.rsi >= p.conservative_rsi_threshold:
            return None

        # Very strict Stochastic condition
        if market_data.stoch_k >= p.conservative_stoch_threshold:
            return None

        # Need historical data
        if market_data.prev_low_20 <= 0 or market_data.prev_high_20 <= 0:
            return None

        support = market_data.prev_low_20
        resistance = market_data.prev_high_20
        range_height = resistance - support

        if range_height <= 0:
            return None

        # Price must be in bottom 10% of range
        if market_data.close > support + range_height * p.conservative_support_zone:
            return None

        # All conditions met - half position size
        return {
            'strategy': 'CONSERVATIVE_BEAR_ENTRY',
            'quantity': p.position_size * p.conservative_position_mult,
        }

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify market regime based on MFI and ADX.

        7-level classification matching original V35LongStrategy:
        - BULL_STRONG: Strong bullish trend (high MFI + strong ADX)
        - BULL_MODERATE: Moderate bullish trend (high MFI + moderate ADX)
        - SIDEWAYS_UP: Weak bullish (moderate MFI, any ADX)
        - SIDEWAYS_FLAT: Neutral (moderate MFI, any ADX)
        - SIDEWAYS_DOWN: Weak bearish (low-moderate MFI, any ADX)
        - BEAR_MODERATE: Moderate bearish (low MFI, moderate ADX)
        - BEAR_STRONG: Strong bearish (very low MFI, strong ADX)

        Args:
            mfi: Money Flow Index value (0-100)
            adx: Average Directional Index value

        Returns:
            Regime classification string.
        """
        p = self.params

        # ADX for trend strength
        is_strong_trend = adx >= p.adx_strong_trend
        is_moderate_trend = adx >= p.adx_moderate_trend

        # MFI for direction
        if mfi >= p.mfi_bull_strong and is_strong_trend:
            return "BULL_STRONG"
        elif mfi >= p.mfi_bull_moderate and is_moderate_trend:
            return "BULL_MODERATE"
        elif mfi >= p.mfi_sideways_up:
            return "SIDEWAYS_UP"
        elif mfi >= p.mfi_bear_moderate:
            return "SIDEWAYS_FLAT"
        elif mfi >= p.mfi_bear_strong:
            return "SIDEWAYS_DOWN"
        elif is_strong_trend:
            return "BEAR_STRONG"
        else:
            return "BEAR_MODERATE"

    def _should_enter(self, regime: str) -> bool:
        """Check if regime is suitable for long entry.

        Used by CompositeStrategyTask for decision logging.
        Note: Actual entry also requires momentum/breakout/range signals.

        Args:
            regime: Market regime classification.

        Returns:
            True if regime allows potential entry.
        """
        # All regimes can potentially enter (with different conditions)
        return regime in (
            "BULL_STRONG",
            "BULL_MODERATE",
            "SIDEWAYS_UP",
            "SIDEWAYS_FLAT",
            "SIDEWAYS_DOWN",
            "BEAR_MODERATE",
            "BEAR_STRONG",
        )
