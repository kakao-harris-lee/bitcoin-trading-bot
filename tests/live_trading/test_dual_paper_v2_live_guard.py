import os
import pytest


def test_dual_paper_v2_live_mode_requires_env_guard():
    """LIVE 모드는 ENABLE_LIVE_TRADING=1 없으면 즉시 막혀야 한다."""
    from trading_engine_v2.trading_engine import DualPaperTradingEngine

    os.environ.pop("ENABLE_LIVE_TRADING", None)

    with pytest.raises(ValueError, match=r"ENABLE_LIVE_TRADING=1"):
        DualPaperTradingEngine(execution_mode="live", telegram_enabled=False)
