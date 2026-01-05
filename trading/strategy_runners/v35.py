"""
V35 Long Strategy - Standalone Coroutine

Upbit long strategy with momentum-based entries.
Generates signals in ALL market states (no internal gating).
Uses regime info for position sizing and TP levels only.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import pandas as pd
import numpy as np

from .base import StandaloneStrategy, Signal
from core.data_loader import DataLoader

logger = logging.getLogger(__name__)


class V35Strategy(StandaloneStrategy):
    """V35 Long Strategy - generates signals autonomously."""

    def __init__(self, redis_client, config):
        super().__init__(redis_client, config)

        # Strategy config
        self.strategy_config = getattr(config, 'v35', {})
        if isinstance(self.strategy_config, dict):
            cfg = self.strategy_config
        else:
            cfg = {}

        # Indicator periods
        self.rsi_period = cfg.get('rsi_period', 14)
        self.mfi_period = cfg.get('mfi_period', 14)
        self.adx_period = cfg.get('adx_period', 14)
        self.macd_fast = cfg.get('macd_fast', 12)
        self.macd_slow = cfg.get('macd_slow', 26)
        self.macd_signal = cfg.get('macd_signal', 9)

        # Entry/exit thresholds
        self.stop_loss = cfg.get('stop_loss', -0.015)
        self.rsi_oversold = cfg.get('rsi_oversold', 30)
        self.rsi_overbought = cfg.get('rsi_overbought', 70)

        # State
        self._market_state = "UNKNOWN"
        self._current_regime = "UNKNOWN"
        self._indicators: Dict[str, float] = {}
        self._df_cache: Optional[pd.DataFrame] = None
        self._last_data_load = None
        self._last_price = 0.0

    @property
    def name(self) -> str:
        return "v35"

    @property
    def exchange(self) -> str:
        return "upbit"

    @property
    def subscribed_streams(self) -> List[str]:
        return ["market:upbit:prices", "market:regime"]

    async def on_regime(self, regime_data: dict) -> None:
        """Update regime info (advisory only, no gating)."""
        self._current_regime = regime_data.get("regime", "UNKNOWN")
        self._market_state = regime_data.get("market_state", "UNKNOWN")
        self.logger.debug(f"Regime update: {self._current_regime} ({self._market_state})")

    async def on_price(self, price_data: dict) -> Optional[Signal]:
        """Process price update and generate signal if conditions met."""
        price = price_data.get("price", 0)
        volume = price_data.get("volume", 0)

        if price <= 0:
            return None

        # Load/refresh data periodically
        await self._ensure_data_loaded()

        if self._df_cache is None or len(self._df_cache) < 50:
            return None

        # Update with latest price
        self._update_indicators(price, volume)

        # Check for exit first if in position
        if self.in_position:
            exit_signal = self._check_exit(price)
            if exit_signal:
                self.exit_position()
                return exit_signal

        # Check for entry if not in position
        if not self.in_position:
            entry_signal = self._check_entry(price)
            if entry_signal:
                self.enter_position(price, entry_signal.size)
                return entry_signal

        return None

    async def _ensure_data_loaded(self):
        """Load historical data if needed."""
        now = datetime.now()

        # Refresh every 5 minutes
        if self._last_data_load and (now - self._last_data_load) < timedelta(minutes=5):
            return

        try:
            with DataLoader() as loader:
                df = loader.load_timeframe('minute60', start_date='2025-01-01')

            if df is not None and len(df) > 0:
                df = self._add_indicators(df)
                self._df_cache = df.tail(500)
                self._last_data_load = now

                # Update indicators from latest row
                if len(self._df_cache) > 0:
                    last_row = self._df_cache.iloc[-1]
                    self._indicators = {
                        'rsi': last_row.get('rsi', 50),
                        'mfi': last_row.get('mfi', 50),
                        'adx': last_row.get('adx', 20),
                        'macd': last_row.get('macd', 0),
                        'macd_signal': last_row.get('macd_signal', 0),
                    }

        except Exception as e:
            self.logger.error(f"Data load error: {e}")

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators to dataframe."""
        df = df.copy()

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))

        # MFI
        tp = (df['high'] + df['low'] + df['close']) / 3
        raw_mf = tp * df['volume']
        direction = tp.diff()
        pos_mf = raw_mf.where(direction > 0, 0)
        neg_mf = raw_mf.where(direction < 0, 0).abs()
        mf_ratio = pos_mf.rolling(self.mfi_period).sum() / neg_mf.rolling(self.mfi_period).sum().replace(0, np.nan)
        df['mfi'] = 100 - (100 / (1 + mf_ratio))

        # MACD
        ema_fast = df['close'].ewm(span=self.macd_fast).mean()
        ema_slow = df['close'].ewm(span=self.macd_slow).mean()
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=self.macd_signal).mean()

        # ADX
        high = df['high']
        low = df['low']
        close = df['close']
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)

        plus_dm = high.diff().where((high.diff() > -low.diff()) & (high.diff() > 0), 0)
        minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0)

        atr = tr.rolling(self.adx_period).mean()
        plus_di = 100 * plus_dm.rolling(self.adx_period).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.rolling(self.adx_period).mean() / atr.replace(0, np.nan)

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        df['adx'] = dx.rolling(self.adx_period).mean()

        return df.ffill().fillna(0)

    def _update_indicators(self, price: float, volume: float):
        """Update indicators with latest price (simplified update)."""
        # For real-time updates, we rely on periodic data refresh
        # This just tracks the latest price for P&L calculations
        self._last_price = price

    def _check_entry(self, price: float) -> Optional[Signal]:
        """Check entry conditions - generates signals in ALL market states."""
        rsi = self._indicators.get('rsi', 50)
        mfi = self._indicators.get('mfi', 50)
        adx = self._indicators.get('adx', 20)
        macd = self._indicators.get('macd', 0)
        macd_sig = self._indicators.get('macd_signal', 0)

        # Momentum entry: MACD cross up + MFI bullish
        if macd > macd_sig and mfi > 50:
            # Aggressive in BULL, conservative otherwise
            if self._market_state in ['BULL_STRONG', 'BULL_MODERATE']:
                size = 0.15  # Larger position in bull
                reason = f"MOMENTUM_BULL_MFI{mfi:.0f}_ADX{adx:.0f}"
            else:
                size = 0.08  # Smaller position otherwise
                reason = f"MOMENTUM_ENTRY_MFI{mfi:.0f}_ADX{adx:.0f}"

            return Signal(
                action="buy",
                price=price,
                reason=reason,
                size=size,
                strategy=self.name,
                metadata={"market_state": self._market_state}
            )

        # Oversold bounce entry (works in any market)
        if rsi < self.rsi_oversold and macd > macd_sig:
            return Signal(
                action="buy",
                price=price,
                reason=f"OVERSOLD_BOUNCE_RSI{rsi:.0f}",
                size=0.05,  # Small size for counter-trend
                strategy=self.name,
                metadata={"market_state": self._market_state}
            )

        return None

    def _check_exit(self, price: float) -> Optional[Signal]:
        """Check exit conditions."""
        if not self.in_position or self.entry_price <= 0:
            return None

        pnl_pct = (price - self.entry_price) / self.entry_price

        # Stop loss
        if pnl_pct <= self.stop_loss:
            return Signal(
                action="sell",
                price=price,
                reason=f"STOP_LOSS_{pnl_pct*100:.1f}%",
                size=1.0,  # Full exit
                strategy=self.name,
            )

        # Take profit levels based on market state
        tp_levels = self._get_tp_levels()

        for tp_pct, fraction in tp_levels:
            if pnl_pct >= tp_pct:
                return Signal(
                    action="sell",
                    price=price,
                    reason=f"TAKE_PROFIT_{pnl_pct*100:.1f}%",
                    size=fraction,
                    strategy=self.name,
                )

        # MACD death cross exit
        macd = self._indicators.get('macd', 0)
        macd_sig = self._indicators.get('macd_signal', 0)
        if macd < macd_sig and pnl_pct > 0:
            return Signal(
                action="sell",
                price=price,
                reason=f"MACD_CROSS_DOWN_{pnl_pct*100:.1f}%",
                size=1.0,
                strategy=self.name,
            )

        return None

    def _get_tp_levels(self) -> List[tuple]:
        """Get take profit levels based on market state."""
        if self._market_state in ['BULL_STRONG']:
            return [(0.03, 0.3), (0.05, 0.3), (0.08, 0.4)]
        elif self._market_state in ['BULL_MODERATE']:
            return [(0.02, 0.3), (0.04, 0.4), (0.06, 0.3)]
        else:
            # Tighter TP in sideways/bear
            return [(0.015, 0.5), (0.025, 0.5)]
