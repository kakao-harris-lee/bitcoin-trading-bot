"""Tests for state persistence in Alpha and Hedge managers."""

import json
import pytest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, MagicMock

from trading.execution.multi_asset_alpha_manager import (
    MultiAssetAlphaManager,
    AssetState,
)
from trading.execution.multi_asset_hedge_manager import (
    MultiAssetHedgeManager,
    AssetHedgePosition,
)


class TestHedgeManagerStatePersistence:
    """Test state persistence for MultiAssetHedgeManager."""

    @pytest.fixture
    def temp_state_file(self):
        """Create temporary state file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "hedge_state.json"

    def test_state_file_created_on_position(self, temp_state_file):
        """State file is created after opening a position."""
        manager = MultiAssetHedgeManager(
            hedgeable_symbols=["BTC"],
            binance_accounts={"BTC": Mock()},
            execution_mode="paper",
            state_file=temp_state_file,
        )

        # Simulate opening a position
        manager._positions["BTC"] = AssetHedgePosition(
            symbol="BTC",
            qty=0.01,
            entry_price=95000,
            entry_premium=3.5,
            entry_time=datetime.now(),
        )

        # Trigger state save
        manager._save_state()

        # Verify state file exists and has correct structure
        assert temp_state_file.exists()

        with open(temp_state_file) as f:
            state_data = json.load(f)

        assert "version" in state_data
        assert "positions" in state_data
        assert "BTC" in state_data["positions"]
        assert state_data["positions"]["BTC"]["qty"] == 0.01

    def test_state_recovered_on_startup(self, temp_state_file):
        """Positions are recovered when manager starts."""
        # Create a state file with position data
        state_data = {
            "version": 1,
            "saved_at": datetime.now().isoformat(),
            "execution_mode": "paper",
            "positions": {
                "BTC": {
                    "symbol": "BTC",
                    "qty": 0.02,
                    "entry_price": 94000,
                    "entry_premium": 4.0,
                    "entry_time": datetime.now().isoformat(),
                    "accumulated_funding": 50.0,
                }
            },
            "capital_per_asset": {"BTC": 5000},
            "trades": {},
        }

        temp_state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        manager = MultiAssetHedgeManager(
            hedgeable_symbols=["BTC"],
            binance_accounts={"BTC": Mock()},
            execution_mode="paper",
            state_file=temp_state_file,
        )

        # Verify position was recovered
        assert "BTC" in manager._positions
        assert manager._positions["BTC"].qty == 0.02
        assert manager._positions["BTC"].entry_price == 94000
        assert manager._positions["BTC"].accumulated_funding == 50.0

    def test_invalid_state_file_ignored(self, temp_state_file):
        """Invalid state file is handled gracefully."""
        temp_state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_state_file, "w") as f:
            f.write("corrupted data")

        # Should not raise exception
        manager = MultiAssetHedgeManager(
            hedgeable_symbols=["BTC"],
            binance_accounts={"BTC": Mock()},
            execution_mode="paper",
            state_file=temp_state_file,
        )

        # Manager should initialize normally with no positions
        assert len(manager._positions) == 0
