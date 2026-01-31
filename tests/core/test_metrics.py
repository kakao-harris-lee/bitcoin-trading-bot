"""Tests for judgment metrics in core/metrics.py"""

import pytest
import pandas as pd
import numpy as np
from core.metrics import calculate_cagr, calculate_sortino_ratio, calculate_calmar_ratio


def test_calculate_cagr():
    """Test CAGR calculation with simple growth."""
    df = pd.DataFrame({'total_equity': [10000, 11000, 12100]})
    # ~10% growth each period, 2 years = 10% CAGR
    cagr = calculate_cagr(df, years=2)
    assert 9 < cagr < 11


def test_calculate_cagr_zero_years():
    """Test CAGR with zero years returns 0."""
    df = pd.DataFrame({'total_equity': [10000, 11000]})
    cagr = calculate_cagr(df, years=0)
    assert cagr == 0.0


def test_calculate_cagr_negative_years():
    """Test CAGR with negative years returns 0."""
    df = pd.DataFrame({'total_equity': [10000, 11000]})
    cagr = calculate_cagr(df, years=-1)
    assert cagr == 0.0


def test_calculate_cagr_empty_df():
    """Test CAGR with empty DataFrame returns 0."""
    df = pd.DataFrame()
    cagr = calculate_cagr(df, years=1)
    assert cagr == 0.0


def test_calculate_cagr_zero_start():
    """Test CAGR with zero start equity returns 0."""
    df = pd.DataFrame({'total_equity': [0, 11000]})
    cagr = calculate_cagr(df, years=1)
    assert cagr == 0.0


def test_calculate_sortino_ratio():
    """Test Sortino ratio calculation."""
    # Create equity curve with realistic volatility
    df = pd.DataFrame({'total_equity': [10000, 10100, 9900, 10200, 10300, 10100, 10500]})
    sortino = calculate_sortino_ratio(df)
    # Should be a valid number (not NaN or inf)
    assert not np.isnan(sortino)
    assert not np.isinf(sortino)


def test_calculate_sortino_ratio_empty():
    """Test Sortino ratio with empty DataFrame returns 0."""
    df = pd.DataFrame()
    sortino = calculate_sortino_ratio(df)
    assert sortino == 0.0


def test_calculate_sortino_ratio_missing_column():
    """Test Sortino ratio with missing column returns 0."""
    df = pd.DataFrame({'wrong_column': [100, 105]})
    sortino = calculate_sortino_ratio(df)
    assert sortino == 0.0


def test_calculate_sortino_ratio_insufficient_data():
    """Test Sortino ratio with single data point returns 0."""
    df = pd.DataFrame({'total_equity': [100]})
    sortino = calculate_sortino_ratio(df)
    assert sortino == 0.0


def test_calculate_calmar_ratio():
    """Test Calmar ratio calculation."""
    calmar = calculate_calmar_ratio(cagr=15.0, max_drawdown=10.0)
    assert calmar == 1.5


def test_calculate_calmar_ratio_zero_mdd():
    """Test Calmar ratio with zero drawdown returns 0."""
    calmar = calculate_calmar_ratio(cagr=15.0, max_drawdown=0.0)
    assert calmar == 0.0


def test_calculate_calmar_ratio_negative_mdd():
    """Test Calmar ratio with negative drawdown (absolute value used)."""
    calmar = calculate_calmar_ratio(cagr=15.0, max_drawdown=-10.0)
    assert calmar == 1.5


def test_calculate_sortino_ratio_no_downside():
    """Test Sortino ratio with no downside returns (all positive)."""
    # Create equity curve with only positive returns
    df = pd.DataFrame({'total_equity': [100, 105, 110, 115, 120]})
    sortino = calculate_sortino_ratio(df)
    # Should return 0 when there's no downside deviation
    assert sortino == 0.0
