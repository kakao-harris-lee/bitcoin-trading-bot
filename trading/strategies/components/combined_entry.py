"""Combined entry: daily volatility breakout AND LSTM price confirmation (+ optional MA)."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .models import MarketData, Signal, TradingContext, _classify_regime
from .registry import entry_strategy
from trading.strategy.lstm_price import LSTMPricePredictor

logger = logging.getLogger(__name__)


@dataclass
class CombinedEntryParams:
    """Parameters for combined entry strategy."""

    # Volatility breakout (daily): close >= prev_high + breakout_k * prev_range
    breakout_k: float = 0.5
    require_up_close: bool = True

    # LSTM price confirmation
    require_lstm: bool = True
    lstm_model_path: str = "models/trading_lstm_price.pth"
    lstm_seq_len: int = 120  # minute60 window length
    lstm_price_buffer_pct: float = 0.0  # require pred > target (no buffer by default)
    lstm_hidden_size: int = 96
    lstm_num_layers: int = 2
    lstm_dropout: float = 0.2
    lstm_min_uplift_pct: float = 0.0  # require pred > last_close * (1+uplift)

    # Optional MA confirmation (AND)
    ma_confirm_required: bool = False
    ema_fast: int = 20
    ema_slow: int = 50

    # Position sizing
    position_size: float = 0.01
    market: Literal["futures"] = "futures"


@entry_strategy(params_class=CombinedEntryParams)
class CombinedEntryStrategy:
    """Daily volatility breakout confirmed by LSTM price (and optional MA cross)."""

    def __init__(self, params: CombinedEntryParams | None = None):
        self.params = params or CombinedEntryParams()
        self._day_state: dict[str, dict[str, float]] = {}
        self._seq_history: dict[str, deque] = {}
        self._ema_state: dict[str, tuple[float, float]] = {}
        self._stats: dict[str, int] = {}
        self._rej_stats: dict[str, int] = {}
        self._logs: list[tuple[str, float, float]] = []  # (symbol, pred_price, target)
        self._lstm_predictor: LSTMPricePredictor | None = None
        self._lstm_available: bool | None = None

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        market_data = ctx.market
        symbol = market_data.symbol

        self._update_day_state(symbol, market_data)
        self._update_seq_history(symbol, market_data)

        # 1) Volatility breakout (daily)
        target = self._breakout_target(symbol)
        if target is None or market_data.close < target:
            return None
        if self.params.require_up_close and market_data.close < float(self._day_state[symbol]["day_open"]):
            return None
        reasons = [f"volatility_breakout target={target:.2f}"]
        self._stats["volatility_breakout"] = self._stats.get("volatility_breakout", 0) + 1

        # 2) LSTM price confirmation
        if self.params.require_lstm:
            ok, reason = self._lstm_price_bullish(symbol, target)
            if not ok:
                return None
            reasons.append(reason)
            self._stats[reason] = self._stats.get(reason, 0) + 1

        # 3) Optional MA confirmation
        if self.params.ma_confirm_required:
            if not self._ma_cross_bullish(symbol, market_data):
                return None
            reasons.append("ma_cross")
            self._stats["ma_cross"] = self._stats.get("ma_cross", 0) + 1

        return Signal(
            symbol=symbol,
            side="buy",
            market=self.params.market,
            quantity=self.params.position_size,
            reason="; ".join(reasons),
        )

    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)

    def get_rejection_stats(self) -> dict[str, int]:
        return dict(self._rej_stats)

    # --- Helpers ---
    def _update_day_state(self, symbol: str, m: MarketData) -> None:
        ts = m.timestamp
        day = datetime.utcfromtimestamp(ts / 1000).date()
        state = self._day_state.get(symbol)
        if state is None:
            self._day_state[symbol] = {
                "day": day,
                "day_open": m.close,
                "day_high": m.high or m.close,
                "day_low": m.low or m.close,
                "prev_high": None,
                "prev_range": None,
            }
            return

        if state["day"] != day:
            prev_range = float(state["day_high"]) - float(state["day_low"])
            state["prev_high"] = float(state["day_high"])
            state["prev_range"] = max(prev_range, 0.0)
            state["day"] = day
            state["day_open"] = m.close
            state["day_high"] = m.high or m.close
            state["day_low"] = m.low or m.close
            return

        state["day_high"] = max(float(state["day_high"]), m.high or m.close)
        state["day_low"] = min(float(state["day_low"]), m.low or m.close)

    def _breakout_target(self, symbol: str) -> float | None:
        state = self._day_state.get(symbol)
        if not state:
            return None
        prev_high = state.get("prev_high")
        prev_range = state.get("prev_range")
        if prev_high is None or prev_range is None or prev_range <= 0:
            return None
        return float(prev_high) + self.params.breakout_k * float(prev_range)

    def _update_seq_history(self, symbol: str, m: MarketData) -> None:
        history = self._seq_history.setdefault(symbol, deque(maxlen=self.params.lstm_seq_len))
        history.append(
            {
                "open": m.close,  # lacking open in MarketData; approximate with close
                "high": m.high,
                "low": m.low,
                "close": m.close,
                "volume": m.volume,
                "timestamp": m.timestamp,
            }
        )

    def _lstm_price_bullish(self, symbol: str, target_price: float) -> tuple[bool, str]:
        predictor = self._get_lstm_predictor()
        if predictor is None:
            self._rej_stats["lstm_unavailable"] = self._rej_stats.get("lstm_unavailable", 0) + 1
            return False, "lstm_unavailable"

        history = self._seq_history.get(symbol)
        if not history or len(history) < self.params.lstm_seq_len:
            self._rej_stats["lstm_insufficient_data"] = self._rej_stats.get("lstm_insufficient_data", 0) + 1
            return False, "lstm_insufficient_data"

        try:
            import pandas as pd
        except ImportError:
            self._rej_stats["lstm_no_pandas"] = self._rej_stats.get("lstm_no_pandas", 0) + 1
            return False, "lstm_no_pandas"

        df = pd.DataFrame(list(history))
        pred_price = predictor.predict_price(df)
        if not pred_price or pred_price != pred_price:  # NaN check
            self._rej_stats["lstm_nan"] = self._rej_stats.get("lstm_nan", 0) + 1
            return False, "lstm_nan"

        last_close = df["close"].iloc[-1]
        buffer = 1 + self.params.lstm_price_buffer_pct
        uplift_gate = last_close * (1 + self.params.lstm_min_uplift_pct)
        target_gate = max(target_price, uplift_gate) * buffer
        self._logs.append((symbol, pred_price, target_gate, target_price, last_close))

        if pred_price <= target_gate:
            self._rej_stats["lstm_pred_below_target"] = self._rej_stats.get("lstm_pred_below_target", 0) + 1
            return False, f"lstm_pred_below_target ({pred_price:.2f} <= {target_gate:.2f})"

        return True, f"lstm_pred_bullish {pred_price:.2f}"

    def _get_lstm_predictor(self) -> LSTMPricePredictor | None:
        if self._lstm_available is False:
            return None
        if self._lstm_predictor is not None:
            return self._lstm_predictor
        try:
            self._lstm_predictor = LSTMPricePredictor(
                model_path=self.params.lstm_model_path,
                seq_len=self.params.lstm_seq_len,
                hidden_size=self.params.lstm_hidden_size,
                num_layers=self.params.lstm_num_layers,
                dropout=self.params.lstm_dropout,
            )
            self._lstm_available = True
            return self._lstm_predictor
        except FileNotFoundError as exc:
            logger.warning("LSTM price model not found: %s", exc)
            self._lstm_available = False
        except Exception as exc:
            logger.warning("Failed to initialize LSTM price predictor: %s", exc)
            self._lstm_available = False
        return None

    def _ma_cross_bullish(self, symbol: str, market_data: MarketData) -> bool:
        indicators = market_data.indicators or {}
        ema_fast = indicators.get(f"ema_{self.params.ema_fast}")
        ema_slow = indicators.get(f"ema_{self.params.ema_slow}")

        if ema_fast is None or ema_slow is None:
            return False

        prev = self._ema_state.get(symbol)
        self._ema_state[symbol] = (float(ema_fast), float(ema_slow))

        if prev is None:
            return False

        prev_fast, prev_slow = prev
        return prev_fast <= prev_slow and ema_fast > ema_slow

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify regime for decision logging.

        Uses default V35 thresholds since CombinedEntryStrategy
        doesn't have regime-specific parameters.

        Args:
            mfi: Money Flow Index value.
            adx: Average Directional Index value.

        Returns:
            Regime classification string.
        """
        return _classify_regime(mfi, adx)
