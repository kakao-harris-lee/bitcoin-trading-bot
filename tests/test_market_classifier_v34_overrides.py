import sys
from pathlib import Path

import pandas as pd


def _import_classifier():
    project_root = Path(__file__).resolve().parents[1]
    classifier_dir = project_root / "strategies" / "v34_supreme" / "v34_supreme"
    sys.path.insert(0, str(classifier_dir))
    from market_classifier_v34 import MarketClassifierV34  # type: ignore

    return MarketClassifierV34


def test_market_classifier_threshold_overrides_change_classification():
    MarketClassifierV34 = _import_classifier()

    # Base row: bullish-ish
    row = pd.Series({"mfi": 50, "macd": 1.0, "macd_signal": 0.5, "adx": 22, "close": 100})
    prev = pd.Series({"close": 99.0})

    # Default classifier: mfi_bull_strong=52 so this should NOT be BULL_STRONG
    default = MarketClassifierV34()
    state_default = default.classify_market_state(row, prev)
    assert state_default != "BULL_STRONG"

    # Override mfi_bull_strong lower so it becomes BULL_STRONG
    overridden = MarketClassifierV34({"mfi_bull_strong": 49, "adx_strong_trend": 20})
    state_overridden = overridden.classify_market_state(row, prev)
    assert state_overridden == "BULL_STRONG"
