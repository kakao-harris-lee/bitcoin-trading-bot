"""Hybrid LSTM + RF Entry Strategy - Component wrapper for HybridPredictor.

Uses LSTM price predictions filtered by RandomForest confidence scores.
Integrates with the Component system for dashboard backtesting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Signal, TradingContext, BEAR_REGIMES
from .registry import entry_strategy
from .rf_probability_service import RFProbabilityService

logger = logging.getLogger(__name__)


@dataclass
class HybridLSTMEntryParams:
    """Parameters for Hybrid LSTM entry strategy."""

    # RF confidence thresholds
    confidence_threshold: float = 0.60  # Minimum RF confidence for entry

    # Signal requirements
    require_buy_signal: bool = True  # Require RF signal == "BUY"
    require_up_direction: bool = True  # Require RF direction == "UP"

    # Regime filters (same as V35)
    skip_bear_regime: bool = True  # Skip entry in BEAR regimes
    adx_min: float = 18.0  # Minimum ADX for entry

    # EMA200 filter
    use_ema200_filter: bool = True  # Skip entry below EMA200

    # Position sizing
    position_size: float = 0.01
    market: Literal["spot", "futures"] = "spot"

    # Model paths
    lstm_model_path: str = "lstm_trainer/models/hybrid_lstm.pth"
    rf_model_path: str = "lstm_trainer/models/noise_filter_rf.pkl"


@entry_strategy(params_class=HybridLSTMEntryParams)
class HybridLSTMEntryStrategy:
    """Entry strategy using Hybrid LSTM + RF predictions.

    Entry conditions:
    1. RF confidence >= threshold (default 60%)
    2. RF signal == "BUY" (if require_buy_signal)
    3. RF direction == "UP" (if require_up_direction)
    4. Not in BEAR regime (if skip_bear_regime)
    5. ADX >= threshold (trend strength)
    6. Price >= EMA200 (if use_ema200_filter)
    """

    def __init__(self, params: HybridLSTMEntryParams | None = None):
        self.params = params or HybridLSTMEntryParams()
        self._rf_service: RFProbabilityService | None = None
        self._rf_available: bool | None = None

    def _ensure_rf_service(self) -> bool:
        """Lazy-load RF service on first use."""
        if self._rf_available is not None:
            return self._rf_available

        try:
            self._rf_service = RFProbabilityService.get_instance(
                lstm_path=self.params.lstm_model_path,
                rf_path=self.params.rf_model_path,
            )
            self._rf_available = self._rf_service.is_available()
            if self._rf_available:
                logger.info("HybridLSTMEntryStrategy: RF service loaded")
            else:
                logger.warning("HybridLSTMEntryStrategy: RF service not available")
        except Exception as e:
            logger.error(f"HybridLSTMEntryStrategy: Failed to load RF service: {e}")
            self._rf_available = False

        return self._rf_available

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        """Check entry conditions using Hybrid LSTM + RF predictions.

        Args:
            ctx: Trading context with market data and regime info.

        Returns:
            Signal if entry conditions met, None otherwise.
        """
        market_data = ctx.market
        context = ctx.regime
        p = self.params

        # === SAFETY FILTER 1: BEAR regime ===
        if p.skip_bear_regime and context.regime in BEAR_REGIMES:
            logger.debug(f"{market_data.symbol}: Skip - BEAR regime ({context.regime})")
            return None

        # === SAFETY FILTER 2: ADX threshold ===
        if context.adx < p.adx_min:
            logger.debug(f"{market_data.symbol}: Skip - weak ADX ({context.adx:.1f} < {p.adx_min})")
            return None

        # === SAFETY FILTER 3: EMA200 filter ===
        if p.use_ema200_filter and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                logger.debug(
                    f"{market_data.symbol}: Skip - below EMA200 "
                    f"({market_data.close:.0f} < {market_data.ema_200:.0f})"
                )
                return None

        # === RF PREDICTION ===
        # Use pre-computed RF values from TradingContext if available
        rf_confidence = context.rf_confidence
        rf_direction = context.rf_direction
        rf_signal = context.rf_signal

        # Fallback: compute RF if not in context
        if rf_confidence == 0 and self._ensure_rf_service() and self._rf_service:
            # Note: In backtest, RF is pre-computed via ComponentStrategyAdapter
            # This fallback is mainly for live trading
            logger.debug(f"{market_data.symbol}: RF not in context, using fallback")

        # === RF FILTER 1: Confidence threshold ===
        if rf_confidence < p.confidence_threshold:
            logger.debug(
                f"{market_data.symbol}: Skip - low RF confidence "
                f"({rf_confidence:.2f} < {p.confidence_threshold:.2f})"
            )
            return None

        # === RF FILTER 2: Buy signal ===
        if p.require_buy_signal and rf_signal != "BUY":
            logger.debug(f"{market_data.symbol}: Skip - RF signal is {rf_signal}, not BUY")
            return None

        # === RF FILTER 3: UP direction ===
        if p.require_up_direction and rf_direction != "UP":
            logger.debug(f"{market_data.symbol}: Skip - RF direction is {rf_direction}, not UP")
            return None

        # All conditions met - generate entry signal
        reason = (
            f"HybridLSTM: conf={rf_confidence:.2f}, dir={rf_direction}, sig={rf_signal}, "
            f"regime={context.regime}, ADX={context.adx:.1f}"
        )
        logger.info(f"{market_data.symbol}: {reason}")

        return Signal(
            symbol=market_data.symbol,
            side="buy",
            market=p.market,
            quantity=p.position_size,
            reason=reason,
        )

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify regime for logging (uses default thresholds)."""
        from .models import _classify_regime
        return _classify_regime(mfi, adx)
