"""V35 Optuna Entry Strategy - Original 2026-01-12 optimized parameters.

Based on 500-trial Optuna optimization (cf51e472).
Key findings:
- Lower MFI thresholds (42-49 vs 52)
- Sideways entry enabled
- Simple regime-based entry without MACD/RSI/Breakout complexity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import Signal, TradingContext
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class V35OptunaEntryParams:
    """Parameters from original Optuna optimization (BTC, 500 trials).

    These are the actual optimized values, not defaults.
    """

    # MFI thresholds - LOWER than standard V35
    mfi_bull_strong: float = 49.0
    mfi_bull_moderate: float = 42.0
    mfi_sideways: float = 50.0

    # ADX thresholds
    adx_strong: float = 23.0
    adx_moderate: float = 24.0

    # Entry regimes
    enter_bull_strong: bool = True
    enter_bull_moderate: bool = True
    enter_sideways: bool = True  # Optuna found this helpful

    # Position sizing per regime
    position_size_bull_strong: float = 0.65
    position_size_bull_moderate: float = 0.54
    position_size_sideways: float = 0.29

    # EMA200 filter (optional safety)
    use_ema200_filter: bool = True

    market: Literal["spot", "futures"] = "spot"


@entry_strategy(params_class=V35OptunaEntryParams)
class V35OptunaEntryStrategy:
    """V35 Optuna entry strategy - original optimized parameters.

    Entry conditions:
    1. BULL_STRONG: MFI >= 49 and ADX >= 23
    2. BULL_MODERATE: MFI >= 42 and ADX >= 24
    3. SIDEWAYS: MFI >= 50 (optional)
    4. (Optional) Price above EMA200

    Key difference from complex V35:
    - NO MACD crossover requirement
    - NO RSI threshold check
    - NO breakout detection
    - NO stress filter
    - LOWER MFI thresholds = more entries
    """

    def __init__(self, params: V35OptunaEntryParams | None = None):
        self.params = params or V35OptunaEntryParams()

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        """Check entry conditions."""
        market_data = ctx.market
        p = self.params

        # EMA200 filter (optional)
        if p.use_ema200_filter and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                logger.debug(
                    f"{market_data.symbol}: Skip - below EMA200 "
                    f"({market_data.close:.0f} < {market_data.ema_200:.0f})"
                )
                return None

        # Classify regime
        regime = self._classify_regime(market_data.mfi, market_data.adx)

        # Determine position size and entry
        position_size = None

        if regime == "BULL_STRONG" and p.enter_bull_strong:
            position_size = p.position_size_bull_strong
        elif regime == "BULL_MODERATE" and p.enter_bull_moderate:
            position_size = p.position_size_bull_moderate
        elif regime == "SIDEWAYS" and p.enter_sideways:
            position_size = p.position_size_sideways

        if position_size is not None:
            reason = (
                f"V35Optuna entry: {regime}, "
                f"MFI={market_data.mfi:.1f}, ADX={market_data.adx:.1f}"
            )
            if p.use_ema200_filter:
                reason += ", above EMA200"

            logger.info(f"{market_data.symbol}: {reason}")

            return Signal(
                symbol=market_data.symbol,
                side="buy",
                market=p.market,
                quantity=position_size,
                reason=reason,
            )

        return None

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify market regime using Optuna-optimized thresholds."""
        p = self.params

        if mfi >= p.mfi_bull_strong and adx >= p.adx_strong:
            return "BULL_STRONG"
        elif mfi >= p.mfi_bull_moderate and adx >= p.adx_moderate:
            return "BULL_MODERATE"
        elif mfi >= p.mfi_sideways:
            return "SIDEWAYS"
        else:
            return "BEAR"
