import pandas as pd

from scripts.backtest import _regime_lookup


def test_regime_lookup_prev_day_fallback():
    idx = pd.to_datetime(["2020-01-01", "2020-01-03"])
    series = pd.Series(["BULL", "BEAR"], index=idx)

    # exact
    assert _regime_lookup(series, pd.Timestamp("2020-01-01 12:00")) == "BULL"

    # missing day -> previous
    assert _regime_lookup(series, pd.Timestamp("2020-01-02 12:00")) == "BULL"

    # after second
    assert _regime_lookup(series, pd.Timestamp("2020-01-04 12:00")) == "BEAR"
