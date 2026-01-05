# SHORT_V2 Hedge Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement SHORT_V2, a defensive hedge strategy that opens short positions matching long exposure during BEAR_STRONG regime.

**Architecture:** SHORT_V2 extends BaseStrategy with regime-gated entry (BEAR_STRONG only), exposure-matched sizing via MultiAssetAlphaManager, and simplified exits (regime change or 5% stop-loss).

**Tech Stack:** Python, pandas, talib indicators, pytest

---

## Task 1: Create SHORT_V2 Config File

**Files:**
- Create: `config/strategies/short_v2.json`

**Step 1: Create config file**

```json
{
  "strategy_name": "SHORT_V2",
  "description": "BEAR_STRONG hedge strategy - offsets long position losses",
  "symbol": "BTCUSDT",
  "timeframe": "4h",
  "indicators": {
    "ema_fast": 30,
    "ema_slow": 100,
    "adx_period": 14
  },
  "entry": {
    "regime_required": "BEAR_STRONG",
    "adx_min": 20,
    "di_negative_dominant": true
  },
  "exit": {
    "stop_loss_pct": 5.0,
    "exit_on_regime_change": true,
    "exit_on_long_close": true
  },
  "sizing": {
    "mode": "match_long_exposure"
  },
  "risk_management": {
    "margin_type": "ISOLATED",
    "leverage": 2,
    "no_reentry_after_stop": true
  },
  "backtest": {
    "initial_capital": 10000,
    "fee_rate": 0.0004,
    "slippage": 0.0005
  }
}
```

**Step 2: Commit**

```bash
git add config/strategies/short_v2.json
git commit -m "config: add SHORT_V2 hedge strategy configuration"
```

---

## Task 2: Create SHORT_V2 Strategy Class

**Files:**
- Create: `trading/strategy/short_v2.py`
- Reference: `trading/strategy/short_v1.py`, `trading/strategy/base.py`

**Step 1: Write the test file**

Create `tests/trading/test_short_v2.py`:

```python
"""Tests for SHORT_V2 hedge strategy."""
import pandas as pd
import numpy as np
import pytest

from trading.strategy.short_v2 import ShortV2Strategy


def _sample_df(n: int = 150) -> pd.DataFrame:
    """Create sample OHLCV data with bearish trend."""
    rng = np.random.default_rng(42)
    # Downward trend for bearish conditions
    close = np.linspace(100, 80, n) + rng.normal(0, 0.5, n)
    high = close + rng.uniform(0.5, 1.5, n)
    low = close - rng.uniform(0.5, 1.5, n)
    open_ = close + rng.normal(0, 0.3, n)
    volume = rng.integers(1000, 2000, n).astype(float)

    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="4h"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestShortV2Indicators:
    """Test indicator calculations."""

    def test_add_indicators_creates_required_columns(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        result = strategy.add_indicators(df)

        required_cols = ["ema_fast", "ema_slow", "adx", "plus_di", "minus_di"]
        for col in required_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_ema_values_are_valid(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        result = strategy.add_indicators(df)

        # After warmup, EMAs should have valid values
        assert not result["ema_fast"].iloc[-1] != result["ema_fast"].iloc[-1]  # not NaN
        assert not result["ema_slow"].iloc[-1] != result["ema_slow"].iloc[-1]


class TestShortV2Entry:
    """Test entry conditions."""

    def test_no_entry_without_bear_strong_regime(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # Without regime context, should not enter
        signal = strategy.generate_signal(df, len(df) - 1, regime="BULL_STRONG")
        assert signal is None or signal.get("action") == "hold"

    def test_entry_on_bear_strong_with_conditions_met(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # Force bearish conditions
        df.loc[df.index[-1], "ema_fast"] = 80
        df.loc[df.index[-1], "ema_slow"] = 90
        df.loc[df.index[-1], "adx"] = 25
        df.loc[df.index[-1], "minus_di"] = 30
        df.loc[df.index[-1], "plus_di"] = 15

        signal = strategy.generate_signal(df, len(df) - 1, regime="BEAR_STRONG")
        assert signal is not None
        assert signal["action"] == "open_short"

    def test_no_entry_when_adx_below_threshold(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # ADX below threshold
        df.loc[df.index[-1], "ema_fast"] = 80
        df.loc[df.index[-1], "ema_slow"] = 90
        df.loc[df.index[-1], "adx"] = 15  # Below 20
        df.loc[df.index[-1], "minus_di"] = 30
        df.loc[df.index[-1], "plus_di"] = 15

        signal = strategy.generate_signal(df, len(df) - 1, regime="BEAR_STRONG")
        assert signal is None or signal.get("action") != "open_short"


class TestShortV2Exit:
    """Test exit conditions."""

    def test_exit_on_stop_loss(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # Simulate position with entry price
        strategy.set_position(entry_price=100.0, reason="TEST")
        strategy.stop_loss_price = 105.0  # 5% stop

        # Price hits stop loss
        df.loc[df.index[-1], "high"] = 106.0
        df.loc[df.index[-1], "close"] = 105.5

        signal = strategy.generate_signal(df, len(df) - 1, regime="BEAR_STRONG")
        assert signal is not None
        assert signal["action"] == "close_short"
        assert "STOP_LOSS" in signal["reason"]

    def test_exit_on_regime_change(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # Simulate position
        strategy.set_position(entry_price=100.0, reason="TEST")
        strategy.stop_loss_price = 105.0

        # Regime changes to non-BEAR_STRONG
        signal = strategy.generate_signal(df, len(df) - 1, regime="SIDEWAYS_NEUTRAL")
        assert signal is not None
        assert signal["action"] == "close_short"
        assert "REGIME" in signal["reason"]


class TestShortV2Sizing:
    """Test position sizing."""

    def test_sizing_mode_is_match_long_exposure(self):
        strategy = ShortV2Strategy()
        assert strategy.strategy_config.get("sizing_mode") == "match_long_exposure"

    def test_get_position_size_returns_exposure(self):
        strategy = ShortV2Strategy()
        # With 10M KRW long exposure
        size = strategy.get_position_size(long_exposure_krw=10_000_000, fx_rate=1450)
        # Should return ~$6,896 USDT equivalent
        assert 6000 < size < 7500


class TestShortV2NoReentry:
    """Test no re-entry after stop-loss."""

    def test_no_reentry_flag_set_after_stop_loss(self):
        df = _sample_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # Simulate stop-loss exit
        strategy.set_position(entry_price=100.0, reason="TEST")
        strategy.stop_loss_price = 105.0
        df.loc[df.index[-1], "high"] = 106.0

        signal = strategy.generate_signal(df, len(df) - 1, regime="BEAR_STRONG")
        assert signal["action"] == "close_short"

        # Mark as stopped out
        strategy.mark_stopped_out()

        # Try to enter again - should be blocked
        df.loc[df.index[-1], "ema_fast"] = 80
        df.loc[df.index[-1], "ema_slow"] = 90
        df.loc[df.index[-1], "adx"] = 25
        df.loc[df.index[-1], "high"] = 80  # Reset high

        signal = strategy.generate_signal(df, len(df) - 1, regime="BEAR_STRONG")
        assert signal is None or signal.get("action") != "open_short"
```

**Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. python -m pytest tests/trading/test_short_v2.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'trading.strategy.short_v2'"

**Step 3: Write SHORT_V2 strategy implementation**

Create `trading/strategy/short_v2.py`:

```python
"""
SHORT_V2: BEAR_STRONG Hedge Strategy

Defensive hedge strategy that:
- Only activates during BEAR_STRONG regime
- Uses EMA 30/100 + ADX >= 20 entry conditions
- Matches long exposure size for hedging
- Exits on regime change or 5% stop-loss
- Uses 2x leverage with no take-profit
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd
import numpy as np

from .base import BaseStrategy
from ..indicators import technical as ta
from ..core.config import Config
from core.types import Exchange, Direction

logger = logging.getLogger(__name__)

# Default config path
DEFAULT_CONFIG_PATH = Path("config/strategies/short_v2.json")


class ShortV2Strategy(BaseStrategy):
    """
    SHORT_V2 Hedge Strategy (Binance Futures)

    BEAR_STRONG regime hedge:
    - EMA 30 < EMA 100 (bearish alignment)
    - ADX >= 20 (trend strength)
    - -DI > +DI (bearish dominance)
    - Only activates in BEAR_STRONG regime
    """

    DEFAULT_CONFIG = {
        # Indicators
        "ema_fast": 30,
        "ema_slow": 100,
        "adx_period": 14,

        # Entry conditions
        "regime_required": "BEAR_STRONG",
        "adx_min": 20,
        "di_negative_dominant": True,

        # Exit conditions
        "stop_loss_pct": 5.0,
        "exit_on_regime_change": True,
        "exit_on_long_close": True,

        # Sizing
        "sizing_mode": "match_long_exposure",

        # Risk management
        "leverage": 2,
        "no_reentry_after_stop": True,

        # Buffer
        "buffer_size": 150,
    }

    def __init__(
        self,
        config: Optional[Config] = None,
        strategy_config: Optional[Dict] = None,
    ):
        # Load from file if not provided
        if strategy_config is None:
            strategy_config = self._load_config()

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
        self.position_leverage = self.strategy_config.get("leverage", 2)

        # Re-entry control
        self._stopped_out_this_regime = False
        self._last_regime: Optional[str] = None

    def _load_config(self) -> Dict:
        """Load config from file."""
        if DEFAULT_CONFIG_PATH.exists():
            try:
                return json.loads(DEFAULT_CONFIG_PATH.read_text())
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
        return {}

    def _min_buffer_size(self) -> int:
        """EMA 100 warmup required."""
        return self.strategy_config.get("ema_slow", 100)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add EMA, ADX, DI indicators."""
        df = df.copy()

        # EMAs
        df["ema_fast"] = ta.ema(df["close"], period=self.strategy_config["ema_fast"])
        df["ema_slow"] = ta.ema(df["close"], period=self.strategy_config["ema_slow"])

        # ADX, +DI, -DI
        period = self.strategy_config["adx_period"]
        df["adx"], df["plus_di"], df["minus_di"] = ta.adx(
            df["high"], df["low"], df["close"], period=period
        )

        return df

    def generate_signal(
        self,
        df: pd.DataFrame,
        i: int,
        regime: Optional[str] = None,
        long_exposure_krw: float = 0.0,
    ) -> Optional[Dict]:
        """
        Generate trading signal.

        Args:
            df: DataFrame with indicators
            i: Current index
            regime: Current market regime from RegimeRouter
            long_exposure_krw: Current long position exposure in KRW

        Returns:
            Signal dict or None
        """
        row = df.iloc[i]

        # Track regime changes for re-entry control
        if regime != self._last_regime:
            if self._last_regime is not None:
                # Regime changed - reset stopped out flag
                self._stopped_out_this_regime = False
            self._last_regime = regime

        # With position: check exits
        if self.in_position:
            return self._check_exit(row, regime)

        # Without position: check entry
        return self._check_entry(row, regime, long_exposure_krw)

    def _check_entry(
        self,
        row: pd.Series,
        regime: Optional[str],
        long_exposure_krw: float,
    ) -> Optional[Dict]:
        """Check entry conditions."""
        # Regime gate: BEAR_STRONG only
        required_regime = self.strategy_config.get("regime_required", "BEAR_STRONG")
        if regime != required_regime:
            return None

        # No re-entry after stop-loss in same regime
        if self._stopped_out_this_regime:
            return None

        # Must have long exposure to hedge
        if long_exposure_krw <= 0:
            return None

        # Condition 1: EMA bearish alignment
        ema_fast = row.get("ema_fast", 0)
        ema_slow = row.get("ema_slow", 0)
        if pd.isna(ema_fast) or pd.isna(ema_slow):
            return None
        if ema_fast >= ema_slow:
            return None

        # Condition 2: ADX >= threshold
        adx = row.get("adx", 0)
        adx_min = self.strategy_config.get("adx_min", 20)
        if pd.isna(adx) or adx < adx_min:
            return None

        # Condition 3: -DI > +DI
        if self.strategy_config.get("di_negative_dominant", True):
            minus_di = row.get("minus_di", 0)
            plus_di = row.get("plus_di", 0)
            if pd.isna(minus_di) or pd.isna(plus_di):
                return None
            if minus_di <= plus_di:
                return None

        # Calculate stop-loss price
        entry_price = row["close"]
        stop_loss_pct = self.strategy_config.get("stop_loss_pct", 5.0)
        stop_loss = entry_price * (1 + stop_loss_pct / 100)

        return {
            "action": "open_short",
            "fraction": 1.0,
            "reason": f"HEDGE_BEAR_STRONG|ADX_{adx:.0f}",
            "confidence": 0.8,
            "leverage": self.strategy_config.get("leverage", 2),
            "stop_loss": stop_loss,
            "stop_loss_pct": stop_loss_pct,
            "sizing_mode": "match_long_exposure",
            "long_exposure_krw": long_exposure_krw,
            "metadata": {
                "regime": regime,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "adx": adx,
                "plus_di": row.get("plus_di", 0),
                "minus_di": row.get("minus_di", 0),
            },
        }

    def _check_exit(self, row: pd.Series, regime: Optional[str]) -> Optional[Dict]:
        """Check exit conditions."""
        current_price = row["close"]
        high_price = row["high"]

        # Exit 1: Regime change (no longer BEAR_STRONG)
        required_regime = self.strategy_config.get("regime_required", "BEAR_STRONG")
        if self.strategy_config.get("exit_on_regime_change", True):
            if regime != required_regime:
                pnl_pct = (self.entry_price - current_price) / self.entry_price * 100
                self.clear_position()
                return {
                    "action": "close_short",
                    "fraction": 1.0,
                    "reason": f"REGIME_EXIT_{regime}|PnL_{pnl_pct:.2f}%",
                    "confidence": 0.9,
                    "metadata": {"exit_price": current_price, "regime": regime},
                }

        # Exit 2: Stop-loss hit
        if self.stop_loss_price > 0 and high_price >= self.stop_loss_price:
            pnl_pct = (self.entry_price - self.stop_loss_price) / self.entry_price * 100
            self._stopped_out_this_regime = True
            self.clear_position()
            return {
                "action": "close_short",
                "fraction": 1.0,
                "reason": f"STOP_LOSS_HIT|PnL_{pnl_pct:.2f}%",
                "confidence": 0.95,
                "metadata": {"exit_price": self.stop_loss_price},
            }

        return None

    def get_position_size(
        self,
        long_exposure_krw: float,
        fx_rate: float = 1450.0,
    ) -> float:
        """
        Calculate position size matching long exposure.

        Args:
            long_exposure_krw: Long position value in KRW
            fx_rate: USD/KRW exchange rate

        Returns:
            Position size in USDT
        """
        return long_exposure_krw / fx_rate

    def set_position(self, entry_price: float, reason: str):
        """Set position with stop-loss calculation."""
        super().set_position(entry_price, reason)
        stop_loss_pct = self.strategy_config.get("stop_loss_pct", 5.0)
        self.stop_loss_price = entry_price * (1 + stop_loss_pct / 100)

    def mark_stopped_out(self):
        """Mark that position was stopped out (no re-entry in this regime)."""
        self._stopped_out_this_regime = True

    def clear_position(self):
        """Clear position state."""
        super().clear_position()
        self.stop_loss_price = 0.0

    def get_stats(self) -> Dict[str, Any]:
        """Get strategy stats."""
        stats = super().get_stats()
        stats.update({
            "stop_loss_price": self.stop_loss_price,
            "position_leverage": self.position_leverage,
            "stopped_out_this_regime": self._stopped_out_this_regime,
            "last_regime": self._last_regime,
        })
        return stats
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. python -m pytest tests/trading/test_short_v2.py -v
```

Expected: All tests PASS

**Step 5: Commit**

```bash
git add trading/strategy/short_v2.py tests/trading/test_short_v2.py
git commit -m "feat: add SHORT_V2 hedge strategy with tests"
```

---

## Task 3: Update RegimeRouter for SHORT_V2

**Files:**
- Modify: `trading/strategy/regime_router.py` (lines 64-66, 197-206)

**Step 1: Write test for short_v2 routing**

Add to existing test file or create new test:

```python
# In tests/trading/test_regime_router.py, add:

def test_router_selects_short_v2_on_bear_strong():
    """Test that router selects short_v2 for BEAR_STRONG with correct gate mode."""
    from trading.strategy.regime_router import RegimeRouter

    router = RegimeRouter(
        binance_gate_mode="bear_strong_only",
        binance_policy="short_v2",
    )

    decision = router.decide_from_market_state("BEAR_STRONG")

    assert decision.binance_strategy == "short_v2"
    assert decision.regime == "BEAR"


def test_router_no_short_v2_on_bear_moderate():
    """Test that short_v2 does NOT activate on BEAR_MODERATE."""
    from trading.strategy.regime_router import RegimeRouter

    router = RegimeRouter(
        binance_gate_mode="bear_strong_only",
        binance_policy="short_v2",
    )

    decision = router.decide_from_market_state("BEAR_MODERATE")

    assert decision.binance_strategy is None
```

**Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. python -m pytest tests/trading/test_regime_router.py::test_router_selects_short_v2_on_bear_strong -v
```

Expected: FAIL (short_v2 not in policy options)

**Step 3: Update RegimeRouter to support short_v2**

In `trading/strategy/regime_router.py`, modify the Binance strategy selection section (around line 197-206):

```python
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
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. python -m pytest tests/trading/test_regime_router.py -v
```

Expected: All tests PASS

**Step 5: Commit**

```bash
git add trading/strategy/regime_router.py tests/trading/test_regime_router.py
git commit -m "feat: add short_v2 policy support to RegimeRouter"
```

---

## Task 4: Add Long Exposure Query to MultiAssetAlphaManager

**Files:**
- Modify: `trading/execution/multi_asset_alpha_manager.py`

**Step 1: Write test for get_long_exposure method**

```python
# Add to tests/trading/test_multi_asset_alpha_manager.py or create new file

def test_get_long_exposure_returns_active_position_value():
    """Test that get_long_exposure returns correct KRW value."""
    from unittest.mock import MagicMock
    from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

    # Mock portfolio
    mock_portfolio = MagicMock()
    mock_portfolio.get_symbols.return_value = ["BTC"]

    manager = MultiAssetAlphaManager(
        portfolio=mock_portfolio,
        config={"assets": {"BTC": {"enabled": True}}},
    )

    # Set up state with active position
    manager._states["BTC"].active = True
    manager._states["BTC"].quantity = 0.1
    manager._states["BTC"].current_price = 100_000_000  # 1억원

    exposure = manager.get_long_exposure_krw("BTC")
    assert exposure == 10_000_000  # 0.1 * 100M = 10M KRW


def test_get_long_exposure_returns_zero_when_no_position():
    """Test that get_long_exposure returns 0 when no position."""
    from unittest.mock import MagicMock
    from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

    mock_portfolio = MagicMock()
    mock_portfolio.get_symbols.return_value = ["BTC"]

    manager = MultiAssetAlphaManager(
        portfolio=mock_portfolio,
        config={"assets": {"BTC": {"enabled": True}}},
    )

    exposure = manager.get_long_exposure_krw("BTC")
    assert exposure == 0.0
```

**Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. python -m pytest tests/trading/test_multi_asset_alpha_manager.py::test_get_long_exposure_returns_active_position_value -v
```

Expected: FAIL (method doesn't exist)

**Step 3: Add get_long_exposure_krw method**

Add to `trading/execution/multi_asset_alpha_manager.py` after `get_exposure_by_symbol` method (around line 666):

```python
    def get_long_exposure_krw(self, symbol: str = "BTC") -> float:
        """
        Get long exposure value in KRW for hedge sizing.

        Args:
            symbol: Asset symbol (default BTC)

        Returns:
            Position value in KRW (quantity * current_price)
        """
        state = self._states.get(symbol)
        if state and state.active and state.quantity > 0:
            return state.quantity * state.current_price
        return 0.0

    def get_total_long_exposure_krw(self) -> float:
        """
        Get total long exposure across all assets in KRW.

        Returns:
            Total position value in KRW
        """
        return sum(
            self.get_long_exposure_krw(symbol)
            for symbol in self._states.keys()
        )
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. python -m pytest tests/trading/test_multi_asset_alpha_manager.py -v
```

Expected: All tests PASS

**Step 5: Commit**

```bash
git add trading/execution/multi_asset_alpha_manager.py tests/trading/test_multi_asset_alpha_manager.py
git commit -m "feat: add get_long_exposure_krw method for hedge sizing"
```

---

## Task 5: Integration Test

**Files:**
- Create: `tests/integration/test_short_v2_integration.py`

**Step 1: Write integration test**

```python
"""Integration test for SHORT_V2 hedge strategy."""
import pandas as pd
import numpy as np
import pytest

from trading.strategy.short_v2 import ShortV2Strategy
from trading.strategy.regime_router import RegimeRouter


def _make_bear_market_df(n: int = 200) -> pd.DataFrame:
    """Create DataFrame simulating bear market conditions."""
    rng = np.random.default_rng(123)

    # Strong downtrend
    close = np.linspace(50000, 35000, n) + rng.normal(0, 200, n)
    high = close + rng.uniform(100, 500, n)
    low = close - rng.uniform(100, 500, n)
    open_ = close + rng.normal(0, 100, n)
    volume = rng.integers(1000, 5000, n).astype(float)

    return pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=n, freq="4h"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestShortV2Integration:
    """Integration tests for SHORT_V2 with RegimeRouter."""

    def test_full_hedge_cycle(self):
        """Test complete hedge cycle: entry -> hold -> exit."""
        df = _make_bear_market_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # Simulate BEAR_STRONG regime with long exposure
        long_exposure = 10_000_000  # 10M KRW

        # Find entry point
        entry_signal = None
        entry_idx = None
        for i in range(120, len(df)):
            signal = strategy.generate_signal(
                df, i,
                regime="BEAR_STRONG",
                long_exposure_krw=long_exposure,
            )
            if signal and signal.get("action") == "open_short":
                entry_signal = signal
                entry_idx = i
                strategy.set_position(df.iloc[i]["close"], signal["reason"])
                break

        assert entry_signal is not None, "Should find entry point in bear market"
        assert entry_signal["sizing_mode"] == "match_long_exposure"

        # Simulate regime change exit
        exit_signal = strategy.generate_signal(
            df, len(df) - 1,
            regime="SIDEWAYS_NEUTRAL",
            long_exposure_krw=long_exposure,
        )

        assert exit_signal is not None
        assert exit_signal["action"] == "close_short"
        assert "REGIME_EXIT" in exit_signal["reason"]

    def test_no_hedge_without_long_exposure(self):
        """Test that hedge doesn't open without long position."""
        df = _make_bear_market_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # No long exposure
        for i in range(120, len(df)):
            signal = strategy.generate_signal(
                df, i,
                regime="BEAR_STRONG",
                long_exposure_krw=0,  # No long position
            )
            if signal and signal.get("action") == "open_short":
                pytest.fail("Should not enter hedge without long exposure")

    def test_router_integration(self):
        """Test RegimeRouter correctly routes to short_v2."""
        router = RegimeRouter(
            binance_gate_mode="bear_strong_only",
            binance_policy="short_v2",
        )

        # BEAR_STRONG should activate short_v2
        decision = router.decide_from_market_state("BEAR_STRONG")
        assert decision.binance_strategy == "short_v2"

        # BEAR_MODERATE should NOT activate
        decision = router.decide_from_market_state("BEAR_MODERATE")
        assert decision.binance_strategy is None

        # BULL should NOT activate
        decision = router.decide_from_market_state("BULL_STRONG")
        assert decision.binance_strategy is None
```

**Step 2: Run integration test**

```bash
PYTHONPATH=. python -m pytest tests/integration/test_short_v2_integration.py -v
```

Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_short_v2_integration.py
git commit -m "test: add SHORT_V2 integration tests"
```

---

## Task 6: Update Allocation Config

**Files:**
- Modify: `config/strategies/allocation.json`

**Step 1: Add short_v2 to allocation config**

Add `short_v2` section under `binance` in the legacy section and update gate mode:

```json
{
  "binance": {
    "short_v1": { "ratio": 1.0, "enabled": false, "regimes": ["SIDEWAYS", "BEAR"], "hedge_mode": true },
    "short_v2": { "ratio": 1.0, "enabled": true, "regimes": ["BEAR"], "hedge_mode": true, "regime_required": "BEAR_STRONG" }
  }
}
```

**Step 2: Commit**

```bash
git add config/strategies/allocation.json
git commit -m "config: enable SHORT_V2 hedge in allocation config"
```

---

## Task 7: Final Verification

**Step 1: Run all tests**

```bash
PYTHONPATH=. python -m pytest tests/trading/test_short_v2.py tests/trading/test_regime_router.py tests/integration/test_short_v2_integration.py -v
```

Expected: All tests PASS

**Step 2: Run full test suite**

```bash
PYTHONPATH=. python -m pytest tests/ -v --ignore=tests/live_trading
```

Expected: No regressions

**Step 3: Final commit if any fixes needed**

```bash
git status
# If changes needed, commit them
```

---

## Summary

| Task | Files | Description |
|------|-------|-------------|
| 1 | `config/strategies/short_v2.json` | Config file |
| 2 | `trading/strategy/short_v2.py`, `tests/trading/test_short_v2.py` | Strategy class + tests |
| 3 | `trading/strategy/regime_router.py` | Add short_v2 policy |
| 4 | `trading/execution/multi_asset_alpha_manager.py` | Add exposure query |
| 5 | `tests/integration/test_short_v2_integration.py` | Integration tests |
| 6 | `config/strategies/allocation.json` | Enable short_v2 |
| 7 | - | Final verification |
