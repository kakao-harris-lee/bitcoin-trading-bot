"""Experimental Exit Strategy.

A simple experimental exit strategy that uses a tight trailing stop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Position, Signal, TradingContext
from .v35_trailing_exit import V35TrailingExitStrategy, V35ExitParams
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class ExperimentalExitParams(V35ExitParams):
    """Parameters for Experimental exit strategy."""
    # Tighter trailing stop
    trailing_activation: float = 0.5
    trailing_distance: float = 0.5

    # Very tight stop loss
    stop_loss_pct: float = 0.5


@exit_strategy(params_class=ExperimentalExitParams)
class ExperimentalExitStrategy(V35TrailingExitStrategy):
    """Experimental exit strategy based on V35 but with tighter constraints.

    Inherits from V35TrailingExitStrategy to reuse logic but applies
    different default parameters and potentially different override logic.
    """

    def __init__(self, params: ExperimentalExitParams | None = None):
        """Initialize with experimental parameters."""
        super().__init__(params=params or ExperimentalExitParams())
