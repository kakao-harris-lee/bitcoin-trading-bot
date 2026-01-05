"""
Trading Engine V2 - Short V2 Hedge Strategy
Binance Short hedge strategy (SHORT_V2)

Defensive hedge strategy for BEAR_STRONG regime:
- Only activates during BEAR_STRONG regime
- Uses EMA 30/100 + ADX >= 20 entry conditions
- Matches long exposure size for hedging
- Exits on regime change or 5% stop-loss
- Uses 2x leverage with no take-profit
- No re-entry after stop-loss in same regime
"""

import logging
from typing import Optional, Dict, Any
import pandas as pd

from .base import BaseStrategy
from ..indicators import technical as ta
from ..core.config import Config
from core.types import Exchange, Direction

logger = logging.getLogger(__name__)


class ShortV2Strategy(BaseStrategy):
    """
    SHORT_V2 Strategy (Binance Futures - Hedge)

    Defensive hedge strategy for BEAR_STRONG regime:
    - EMA30 < EMA100 (bearish trend)
    - ADX >= 20 (trending market)
    - -DI > +DI (downward momentum)
    - Only enters when long exposure exists
    - Exits on regime change or stop-loss
    """

    # Default configuration
    DEFAULT_CONFIG = {
        # Indicator settings
        'ema_fast': 30,
        'ema_slow': 100,
        'adx_period': 14,
        'adx_threshold': 20,

        # Leverage (hedge uses 2x)
        'leverage': 2,

        # Risk management
        'stop_loss_pct': 5.0,  # 5% stop-loss
        'take_profit_pct': None,  # No take-profit for hedge

        # Buffer
        'buffer_size': 150,
    }

    def __init__(
        self,
        config: Optional[Config] = None,
        strategy_config: Optional[Dict] = None,
    ):
        # Merge configuration
        merged_config = {**self.DEFAULT_CONFIG, **(strategy_config or {})}

        super().__init__(
            strategy_name="short-v2",
            exchange=Exchange.BINANCE,
            direction=Direction.SHORT,
            symbol="BTCUSDT",
            config=config,
            strategy_config=merged_config,
        )

        # Position management
        self.stop_loss_price = 0.0

        # Re-entry prevention flag
        self._stopped_out_this_regime = False

        # Track current regime for change detection
        self._current_regime: Optional[str] = None

    def _min_buffer_size(self) -> int:
        """Minimum buffer size for EMA 100 warm-up."""
        return 100

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add EMA, ADX, and DI indicators."""
        # EMA (using talib via shared library)
        df['ema_fast'] = ta.ema(df['close'], period=self.strategy_config['ema_fast'])
        df['ema_slow'] = ta.ema(df['close'], period=self.strategy_config['ema_slow'])

        # ADX, +DI, -DI (using talib via shared library)
        period = self.strategy_config['adx_period']
        df['adx'], df['plus_di'], df['minus_di'] = ta.adx(
            df['high'], df['low'], df['close'], period=period
        )

        return df

    def generate_signal(
        self,
        df: pd.DataFrame,
        i: int,
        regime: str = None,
        long_exposure_krw: float = 0,
    ) -> Optional[Dict]:
        """
        Generate trading signal.

        Args:
            df: DataFrame with indicators
            i: Current index
            regime: Current market regime (required for SHORT_V2)
            long_exposure_krw: Current long exposure in KRW (for hedge sizing)

        Returns:
            Signal dict or None
        """
        row = df.iloc[i]

        # Handle regime change
        if regime != self._current_regime:
            old_regime = self._current_regime
            self._current_regime = regime

            # Reset stopped-out flag on regime change
            if old_regime is not None:
                self._stopped_out_this_regime = False

        # If in position: check exit conditions
        if self.in_position:
            exit_signal = self._check_exit(row, regime)
            if exit_signal:
                if 'STOP_LOSS' in exit_signal.get('reason', ''):
                    self._stopped_out_this_regime = True
                self.clear_position()
                return exit_signal
            return None  # Hold position

        # Not in position: check entry conditions
        entry_signal = self._check_entry(row, regime, long_exposure_krw)
        if entry_signal:
            self.set_position(row['close'], entry_signal['reason'])
            # Calculate stop-loss price
            stop_loss_pct = self.strategy_config['stop_loss_pct']
            self.stop_loss_price = row['close'] * (1 + stop_loss_pct / 100)
            return entry_signal

        return None

    def _check_entry(
        self,
        row: pd.Series,
        regime: str,
        long_exposure_krw: float,
    ) -> Optional[Dict]:
        """Check entry conditions."""
        # Condition 0: Must be in BEAR_STRONG regime
        if regime != 'BEAR_STRONG':
            return None

        # Condition 0b: Must have long exposure to hedge
        if long_exposure_krw <= 0:
            return None

        # Condition 0c: No re-entry after stop-loss in same regime
        if self._stopped_out_this_regime:
            return None

        # Condition 1: Bearish EMA (fast < slow)
        ema_fast = row.get('ema_fast', 0)
        ema_slow = row.get('ema_slow', 0)
        if ema_fast >= ema_slow:
            return None

        # Condition 2: ADX >= threshold (trending)
        adx = row.get('adx', 0)
        adx_threshold = self.strategy_config['adx_threshold']
        if adx < adx_threshold:
            return None

        # Condition 3: Bearish DI (-DI > +DI)
        plus_di = row.get('plus_di', 0)
        minus_di = row.get('minus_di', 0)
        if minus_di <= plus_di:
            return None

        # All conditions met - generate entry signal
        reasons = [
            'EMA_BEARISH',
            f'ADX_{adx:.0f}',
            'DI_BEARISH',
            'HEDGE'
        ]

        return {
            'action': 'open_short',
            'fraction': 1.0,
            'reason': '+'.join(reasons),
            'confidence': 0.8,
            'leverage': self.strategy_config['leverage'],
            'stop_loss_pct': self.strategy_config['stop_loss_pct'],
            'take_profit_pct': None,  # No take-profit for hedge
            'metadata': {
                'regime': regime,
                'adx': adx,
                'plus_di': plus_di,
                'minus_di': minus_di,
                'ema_fast': ema_fast,
                'ema_slow': ema_slow,
                'long_exposure_krw': long_exposure_krw,
            }
        }

    def _check_exit(self, row: pd.Series, regime: str) -> Optional[Dict]:
        """Check exit conditions."""
        current_price = row['close']
        high_price = row.get('high', current_price)

        # Exit condition 1: Stop-loss hit (price rises above stop-loss)
        if self.stop_loss_price > 0 and high_price >= self.stop_loss_price:
            pnl_pct = (self.entry_price - self.stop_loss_price) / self.entry_price * 100
            return {
                'action': 'close_short',
                'fraction': 1.0,
                'reason': f'STOP_LOSS_HIT_{pnl_pct:.2f}%',
                'confidence': 0.95,
                'metadata': {
                    'exit_price': self.stop_loss_price,
                    'entry_price': self.entry_price,
                }
            }

        # Exit condition 2: Regime change (exit hedge when not BEAR_STRONG)
        if regime != 'BEAR_STRONG':
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100
            return {
                'action': 'close_short',
                'fraction': 1.0,
                'reason': f'REGIME_CHANGE_{regime}_{pnl_pct:.2f}%',
                'confidence': 0.9,
                'metadata': {
                    'exit_price': current_price,
                    'entry_price': self.entry_price,
                    'old_regime': 'BEAR_STRONG',
                    'new_regime': regime,
                }
            }

        return None

    def on_regime_change(self, new_regime: str):
        """
        Handle regime change notification.

        Resets the stopped-out flag when regime changes,
        allowing re-entry when BEAR_STRONG returns.
        """
        if new_regime != self._current_regime:
            self._current_regime = new_regime
            self._stopped_out_this_regime = False
            logger.info(f"SHORT_V2: Regime changed to {new_regime}, reset stopped-out flag")

    def get_position_size(self, long_exposure_krw: float, fx_rate: float) -> float:
        """
        Calculate position size to match long exposure.

        Args:
            long_exposure_krw: Long exposure amount in KRW
            fx_rate: USD/KRW exchange rate

        Returns:
            Position size in USDT
        """
        if long_exposure_krw <= 0 or fx_rate <= 0:
            return 0.0

        return long_exposure_krw / fx_rate

    def clear_position(self):
        """Clear position (extended)."""
        super().clear_position()
        self.stop_loss_price = 0.0

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics (extended)."""
        stats = super().get_stats()
        stats.update({
            'stop_loss_price': self.stop_loss_price,
            'stopped_out_this_regime': self._stopped_out_this_regime,
            'current_regime': self._current_regime,
        })
        return stats
