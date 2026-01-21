"""Regime-aware strategy adapter for backtesting."""
from typing import Dict, Any, Optional


# Component class mappings (name -> module path)
ENTRY_CLASS_MAP = {
    "V35Entry": "trading.strategies.components.v35_entry.V35EntryStrategy",
    "SidewaysEntry": "trading.strategies.components.sideways_entry.SidewaysEntryStrategy",
    "ShortEntry": "trading.strategies.components.short_entry.ShortEntryStrategy",
    "None": None,
}

EXIT_CLASS_MAP = {
    "V35TrailingExit": "trading.strategies.components.v35_trailing_exit.V35TrailingExitStrategy",
    "V35PersistentExit": "trading.strategies.components.v35_persistent_exit.V35PersistentExitStrategy",
    "ExperimentalExit": "trading.strategies.components.experimental_exit.ExperimentalExitStrategy",
    "SidewaysExit": "trading.strategies.components.sideways_exit.SidewaysExitStrategy",
}


class RegimeAwareAdapter:
    """
    Adapter that switches entry/exit strategies based on market regime.

    Used for backtesting regime-based strategy configurations.
    """

    def __init__(
        self,
        regime_config: Dict[str, Dict[str, Any]],
        symbol: str,
    ):
        """
        Initialize adapter with regime configuration.

        Args:
            regime_config: Dict mapping regime -> {entry, exit, params}
            symbol: Trading symbol
        """
        self.regime_config = regime_config
        self.symbol = symbol

    def _get_entry_for_regime(self, regime: str) -> Optional[str]:
        """
        Get entry component name for the given regime.

        Args:
            regime: Market regime name

        Returns:
            Entry component name or None if "None" entry
        """
        config = self.regime_config.get(regime, {})
        entry_name = config.get("entry", "None")
        if entry_name == "None":
            return None
        return entry_name

    def _get_exit_for_regime(self, regime: str) -> Optional[str]:
        """
        Get exit component name for the given regime.

        Args:
            regime: Market regime name

        Returns:
            Exit component name
        """
        config = self.regime_config.get(regime, {})
        return config.get("exit")

    def _get_entry_params(self, regime: str) -> Dict[str, Any]:
        """Get entry parameters for the given regime."""
        config = self.regime_config.get(regime, {})
        return config.get("params", {}).get("entry", {})

    def _get_exit_params(self, regime: str) -> Dict[str, Any]:
        """Get exit parameters for the given regime."""
        config = self.regime_config.get(regime, {})
        return config.get("params", {}).get("exit", {})

    def get_config_for_regime(self, regime: str) -> Dict[str, Any]:
        """
        Get complete configuration for a regime.

        Returns dict with entry, exit, and their params.
        """
        return {
            "entry": self._get_entry_for_regime(regime),
            "exit": self._get_exit_for_regime(regime),
            "entry_params": self._get_entry_params(regime),
            "exit_params": self._get_exit_params(regime),
        }
