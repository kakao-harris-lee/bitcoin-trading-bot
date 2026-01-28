"""Combo1-C Entry Strategy: VBS + LSTM + RF combined entry.

Implements the paper-described combination of:
1. Volatility Breakout Strategy (VBS): current_price > target_price
2. LSTM Prediction: predicted_price > target_price
3. Random Forest Filter: RF confidence > 60%

All three conditions must be met for entry.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from .models import MarketData, Signal, TradingContext, _classify_regime
from .registry import entry_strategy

logger = logging.getLogger(__name__)


@dataclass
class Combo1CEntryParams:
    """Parameters for Combo1-C entry strategy."""

    # VBS parameters
    breakout_k: float = 0.5  # Range multiplier for target price
    require_up_close: bool = True  # Require close > open (up candle)

    # LSTM + RF parameters (matches trained model config)
    lstm_model_path: str = "lstm_trainer/models/hybrid_lstm.pth"
    rf_model_path: str = "lstm_trainer/models/noise_filter_rf.pkl"
    db_path: str = "data/binance_bitcoin.db"  # Database for scaling params
    lstm_seq_len: int = 60  # Sequence length for LSTM input (must match model)
    lstm_input_size: int = 22  # Number of scaled features (must match model)
    lstm_hidden_size: int = 64  # LSTM hidden state dimension (must match model)
    rf_confidence_threshold: float = 0.6  # Minimum RF confidence (60% as per paper)
    scaler_rolling_window: int = 720  # Rolling window for LiveScaler (match training)

    # Position sizing
    position_size: float = 0.01
    market: Literal["futures"] = "futures"


@entry_strategy(params_class=Combo1CEntryParams)
class Combo1CEntryStrategy:
    """VBS + LSTM + RF combined entry strategy.

    Entry conditions (all must be met):
    1. VBS Breakout: current_price > target_price (open + prev_day_range * k)
    2. LSTM Prediction: predicted_price > target_price
    3. RF Confidence: confidence > 60%

    This implements the Combo1-C strategy from the research paper.
    """

    def __init__(self, params: Combo1CEntryParams | None = None):
        self.params = params or Combo1CEntryParams()

        # Lazy-loaded hybrid predictor and scaler
        self._predictor = None
        self._predictor_available: bool | None = None
        self._scaler = None

        # History buffer for LSTM input (raw OHLC)
        self._seq_history: dict[str, deque] = {}
        self._history_window = max(self.params.lstm_seq_len, self.params.scaler_rolling_window)

        # Day state for VBS (fallback if MarketData.target_price is not set)
        self._day_state: dict[str, dict[str, float]] = {}

        # Statistics
        self._stats: dict[str, int] = {}
        self._rej_stats: dict[str, int] = {}
        self._logs: list[dict[str, Any]] = []

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        """Check entry conditions for Combo1-C strategy.

        Args:
            ctx: Trading context with market data and regime.

        Returns:
            Signal if all entry conditions met, None otherwise.
        """
        market_data = ctx.market
        symbol = market_data.symbol

        # Update internal state
        self._update_day_state(symbol, market_data)
        self._update_seq_history(symbol, market_data)

        # 1. VBS Breakout Check
        target_price = self._get_target_price(symbol, market_data)
        if target_price is None or target_price <= 0:
            self._rej_stats["no_target_price"] = self._rej_stats.get("no_target_price", 0) + 1
            return None

        current_price = market_data.close
        if current_price <= target_price:
            self._rej_stats["vbs_below_target"] = self._rej_stats.get("vbs_below_target", 0) + 1
            return None

        # Optional: require up close (close > open approximation)
        if self.params.require_up_close:
            day_state = self._day_state.get(symbol)
            if day_state and current_price < day_state.get("day_open", current_price):
                self._rej_stats["vbs_not_up_close"] = self._rej_stats.get("vbs_not_up_close", 0) + 1
                return None

        self._stats["vbs_breakout"] = self._stats.get("vbs_breakout", 0) + 1

        # 2. LSTM + RF Prediction Check
        prediction_result = self._get_hybrid_prediction(symbol, market_data)
        if prediction_result is None:
            self._rej_stats["prediction_unavailable"] = self._rej_stats.get("prediction_unavailable", 0) + 1
            return None

        predicted_price = prediction_result["predicted_price"]
        rf_confidence = prediction_result["confidence"]

        # Log prediction for analysis
        self._logs.append({
            "symbol": symbol,
            "current_price": current_price,
            "target_price": target_price,
            "predicted_price": predicted_price,
            "rf_confidence": rf_confidence,
            "timestamp": market_data.timestamp,
        })

        # Check LSTM prediction > target_price
        if predicted_price <= target_price:
            self._rej_stats["lstm_below_target"] = self._rej_stats.get("lstm_below_target", 0) + 1
            logger.debug(
                f"[Combo1C] {symbol}: LSTM pred {predicted_price:.2f} <= target {target_price:.2f}"
            )
            return None

        self._stats["lstm_above_target"] = self._stats.get("lstm_above_target", 0) + 1

        # 3. RF Confidence Check (> 60%)
        if rf_confidence <= self.params.rf_confidence_threshold:
            self._rej_stats["rf_low_confidence"] = self._rej_stats.get("rf_low_confidence", 0) + 1
            logger.debug(
                f"[Combo1C] {symbol}: RF confidence {rf_confidence:.2%} <= threshold {self.params.rf_confidence_threshold:.0%}"
            )
            return None

        self._stats["rf_high_confidence"] = self._stats.get("rf_high_confidence", 0) + 1
        self._stats["signals_generated"] = self._stats.get("signals_generated", 0) + 1

        # All conditions met - generate entry signal
        reason = (
            f"combo1c_entry: VBS breakout {current_price:.2f}>{target_price:.2f}; "
            f"LSTM pred {predicted_price:.2f}; RF conf {rf_confidence:.1%}"
        )

        logger.info(f"[Combo1C] {symbol}: Entry signal - {reason}")

        signal = Signal(
            symbol=symbol,
            side="buy",
            market=self.params.market,
            quantity=self.params.position_size,
            reason=reason,
        )

        # Debug: verify signal is being returned
        if signal:
            self._stats["signal_returned"] = self._stats.get("signal_returned", 0) + 1

        return signal

    def _get_target_price(self, symbol: str, market_data: MarketData) -> float | None:
        """Get VBS target price.

        Uses MarketData.target_price if available, otherwise calculates from day state.

        Args:
            symbol: Trading symbol.
            market_data: Current market data.

        Returns:
            Target price or None if unavailable.
        """
        # Prefer pre-computed target_price from MarketData
        if market_data.target_price and market_data.target_price > 0:
            return market_data.target_price

        # Fallback: calculate from internal day state
        state = self._day_state.get(symbol)
        if not state:
            return None

        prev_range = state.get("prev_range")
        day_open = state.get("day_open")
        if prev_range is None or day_open is None or prev_range <= 0:
            return None

        return float(day_open) + self.params.breakout_k * float(prev_range)

    def _get_hybrid_prediction(
        self,
        symbol: str,
        market_data: MarketData,
    ) -> dict[str, Any] | None:
        """Get LSTM prediction with RF confidence.

        Args:
            symbol: Trading symbol.
            market_data: Current market data.

        Returns:
            Dict with predicted_price, raw_prediction, confidence, or None.
        """
        predictor = self._get_predictor()
        if predictor is None:
            return None

        # Check history buffer
        history = self._seq_history.get(symbol)
        if not history or len(history) < self.params.lstm_seq_len:
            return None

        # Get scaler and prepare properly scaled data
        scaler = self._get_scaler()
        if scaler:
            df = scaler.prepare_sequence(list(history))
        else:
            # Fallback to raw DataFrame
            df = pd.DataFrame(list(history))

        if df is None or len(df) < self.params.lstm_seq_len:
            return None

        # Build market context for RF
        market_context = {
            "mfi": market_data.mfi,
            "adx": market_data.adx,
            "volatility": market_data.atr / market_data.close if market_data.close > 0 else 0.02,
            "regime": self._get_regime_string(market_data),
            "breakout_signal": market_data.breakout_signal,
        }

        try:
            result = predictor.predict(df, market_context)

            # Convert price delta to absolute predicted price
            current_price = market_data.close
            raw_prediction = result.get("raw_prediction", 0.0)
            confidence = result.get("confidence", 0.5)

            # raw_prediction is a price delta (percentage change)
            # Convert to absolute price
            predicted_price = current_price * (1 + raw_prediction)

            return {
                "predicted_price": predicted_price,
                "raw_prediction": raw_prediction,
                "confidence": confidence,
                "direction": result.get("direction", "SIDEWAYS"),
                "signal": result.get("signal", "HOLD"),
            }

        except Exception as exc:
            logger.warning(f"[Combo1C] Prediction failed: {exc}")
            return None

    def _get_scaler(self):
        """Lazy-load LiveScaler.

        Returns:
            LiveScaler instance or None.
        """
        if self._scaler is not None:
            return self._scaler

        try:
            from lstm_trainer.src.live_scaler import LiveScaler

            # Get feature columns from predictor if available
            feature_columns = None
            if self._predictor and hasattr(self._predictor, "scaled_columns"):
                feature_columns = self._predictor.scaled_columns

            self._scaler = LiveScaler(
                db_path=self.params.db_path,
                rolling_window=self.params.scaler_rolling_window,
                feature_columns=feature_columns or [],
            )
            logger.info("[Combo1C] LiveScaler initialized")
            return self._scaler

        except ImportError as exc:
            logger.warning(f"[Combo1C] Failed to import LiveScaler: {exc}")
        except Exception as exc:
            logger.warning(f"[Combo1C] Failed to initialize LiveScaler: {exc}")

        return None

    def _get_predictor(self):
        """Lazy-load HybridPredictor.

        Returns:
            HybridPredictor instance or None.
        """
        if self._predictor_available is False:
            return None

        if self._predictor is not None:
            return self._predictor

        try:
            from lstm_trainer.src.hybrid_predictor import HybridPredictor

            model_path = Path(self.params.lstm_model_path)
            rf_path = Path(self.params.rf_model_path)

            if model_path.exists() and rf_path.exists():
                self._predictor = HybridPredictor.load(
                    model_path=model_path,
                    rf_path=rf_path,
                    device="cpu",
                )
                self._predictor_available = True
                logger.info(f"[Combo1C] Loaded HybridPredictor from {model_path}")
                return self._predictor
            else:
                logger.warning(
                    f"[Combo1C] Model files not found: {model_path} or {rf_path}"
                )
                self._predictor_available = False

        except ImportError as exc:
            logger.warning(f"[Combo1C] Failed to import HybridPredictor: {exc}")
            self._predictor_available = False
        except Exception as exc:
            logger.warning(f"[Combo1C] Failed to load HybridPredictor: {exc}")
            self._predictor_available = False

        return None

    def _update_day_state(self, symbol: str, m: MarketData) -> None:
        """Update daily state for VBS calculation fallback.

        Args:
            symbol: Trading symbol.
            m: Current market data.
        """
        from datetime import datetime

        ts = m.timestamp
        day = datetime.utcfromtimestamp(ts / 1000).date()
        state = self._day_state.get(symbol)

        if state is None:
            self._day_state[symbol] = {
                "day": day,
                "day_open": m.open or m.close,
                "day_high": m.high or m.close,
                "day_low": m.low or m.close,
                "prev_range": None,
            }
            return

        if state["day"] != day:
            # New day - compute previous day's range
            prev_range = float(state["day_high"]) - float(state["day_low"])
            state["prev_range"] = max(prev_range, 0.0)
            state["day"] = day
            state["day_open"] = m.open or m.close
            state["day_high"] = m.high or m.close
            state["day_low"] = m.low or m.close
            return

        # Same day - update high/low
        state["day_high"] = max(float(state["day_high"]), m.high or m.close)
        state["day_low"] = min(float(state["day_low"]), m.low or m.close)

    def _update_seq_history(self, symbol: str, m: MarketData) -> None:
        """Update sequence history buffer for LSTM.

        Stores raw OHLC data which will be scaled by LiveScaler.

        Args:
            symbol: Trading symbol.
            m: Current market data.
        """
        history = self._seq_history.setdefault(
            symbol, deque(maxlen=self._history_window)
        )

        # Store raw OHLC data - LiveScaler will handle scaling
        row = {
            "open": m.open or m.close,
            "high": m.high or m.close,
            "low": m.low or m.close,
            "close": m.close,
            "volume": m.volume,
            "timestamp": m.timestamp,
        }

        history.append(row)

    def _get_regime_string(self, market_data: MarketData) -> str:
        """Get regime string for RF features.

        Args:
            market_data: Current market data.

        Returns:
            Regime string (e.g., "BULL_STRONG").
        """
        # Approximate regime from MFI/ADX
        mfi = market_data.mfi or 50
        adx = market_data.adx or 20

        if mfi >= 54 and adx >= 25:
            return "BULL_STRONG"
        elif mfi >= 54 and adx >= 18:
            return "BULL_MODERATE"
        elif mfi >= 49:
            return "SIDEWAYS_UP"
        elif mfi >= 41:
            return "SIDEWAYS_FLAT"
        elif mfi >= 34:
            return "SIDEWAYS_DOWN"
        elif adx >= 25:
            return "BEAR_STRONG"
        else:
            return "BEAR_MODERATE"

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify regime for decision logging.

        Uses default V35 thresholds via models._classify_regime.

        Args:
            mfi: Money Flow Index value.
            adx: Average Directional Index value.

        Returns:
            Regime classification string.
        """
        return _classify_regime(mfi, adx)

    def get_stats(self) -> dict[str, int]:
        """Get entry statistics.

        Returns:
            Dict with entry condition hit counts.
        """
        return dict(self._stats)

    def get_rejection_stats(self) -> dict[str, int]:
        """Get rejection statistics.

        Returns:
            Dict with rejection reason counts.
        """
        return dict(self._rej_stats)

    def get_prediction_logs(self) -> list[dict[str, Any]]:
        """Get prediction logs for analysis.

        Returns:
            List of prediction dicts.
        """
        return list(self._logs)
