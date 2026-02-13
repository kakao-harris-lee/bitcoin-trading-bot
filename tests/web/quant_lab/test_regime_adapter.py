"""Tests for regime-aware strategy adapter."""
import pytest
from unittest.mock import MagicMock, patch
from web.quant_lab.optimizer.regime_adapter import RegimeAwareAdapter


class TestRegimeAwareAdapter:
    """Test regime-aware strategy switching."""

    def test_adapter_selects_entry_based_on_regime(self):
        """Adapter should use regime-specific entry component."""
        config = {
            "BULL_STRONG": {
                "entry": "SidewaysEntry",
                "exit": "SidewaysExit",
                "params": {"entry": {"mfi_threshold": 55}, "exit": {}},
            },
            "BEAR_STRONG": {
                "entry": "SidewaysEntry",
                "exit": "SidewaysExit",
                "params": {"entry": {"rsi_overbought": 75}, "exit": {}},
            },
        }

        adapter = RegimeAwareAdapter(
            regime_config=config,
            symbol="BTCUSDT",
        )

        # Test that _get_entry_for_regime returns correct entry name
        entry_name = adapter._get_entry_for_regime("BULL_STRONG")
        assert entry_name == "SidewaysEntry"

        entry_name = adapter._get_entry_for_regime("BEAR_STRONG")
        assert entry_name == "SidewaysEntry"

    def test_adapter_returns_none_for_none_entry(self):
        """Adapter should return None when entry is None."""
        config = {
            "SIDEWAYS_FLAT": {
                "entry": "None",
                "exit": "SidewaysExit",
                "params": {"entry": {}, "exit": {}},
            },
        }

        adapter = RegimeAwareAdapter(
            regime_config=config,
            symbol="BTCUSDT",
        )

        entry = adapter._get_entry_for_regime("SIDEWAYS_FLAT")
        assert entry is None
