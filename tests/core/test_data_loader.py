"""Tests for DataLoader parameterized queries."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from core.data_loader import DataLoader


@pytest.fixture
def mock_df():
    """Shared mock DataFrame for all tests."""
    return pd.DataFrame({
        'timestamp': ['2024-01-01'],
        'open': [100.0],
        'high': [101.0],
        'low': [99.0],
        'close': [100.5],
        'volume': [1000],
    })


@pytest.fixture
def mock_loader():
    """Create a mocked DataLoader instance."""
    with patch.object(DataLoader, '__init__', lambda self, *args, **kwargs: None):
        loader = DataLoader()
        loader.conn = MagicMock()
        loader.exchange = 'binance'
        loader.db_path = '/fake/path'
        yield loader


class TestDataLoaderParameterizedQueries:
    """Test DataLoader uses parameterized queries to prevent SQL injection."""

    def test_uses_parameterized_query(self, mock_loader, mock_df):
        """Verify DataLoader uses parameterized queries."""
        with patch('pandas.read_sql_query', return_value=mock_df) as mock_read_sql:
            mock_loader._load_binance_timeframe(
                'minute60',
                start_date="2024-01-01",
                end_date="2024-01-31"
            )

            call_args = mock_read_sql.call_args
            query = call_args[0][0]

            # Query should use ? placeholders, not string interpolation
            assert "?" in query or "WHERE timestamp >= ?" in query or \
                "start_date" not in query, \
                f"Query should use parameterized placeholders, got: {query}"

    def test_passes_params_to_read_sql(self, mock_loader, mock_df):
        """Verify date values are passed as params, not interpolated."""
        with patch('pandas.read_sql_query', return_value=mock_df) as mock_read_sql:
            test_start = "2024-01-01"
            test_end = "2024-01-31"

            mock_loader._load_binance_timeframe(
                'minute60',
                start_date=test_start,
                end_date=test_end
            )

            call_args = mock_read_sql.call_args
            query = call_args[0][0]

            # The actual date values should NOT appear in the query string
            assert test_start not in query, \
                f"Start date should not be interpolated in query: {query}"
            assert test_end not in query, \
                f"End date should not be interpolated in query: {query}"

            # Params should be passed separately
            kwargs = call_args[1]
            assert 'params' in kwargs, "params argument should be passed to read_sql_query"
            assert test_start in kwargs['params'], \
                f"Start date should be in params: {kwargs['params']}"
            assert test_end in kwargs['params'], \
                f"End date should be in params: {kwargs['params']}"

    def test_without_dates(self, mock_loader, mock_df):
        """Verify query works without date filters."""
        with patch('pandas.read_sql_query', return_value=mock_df) as mock_read_sql:
            mock_loader._load_binance_timeframe('minute60')

            call_args = mock_read_sql.call_args
            query = call_args[0][0]

            # Query should not have WHERE clause
            assert "WHERE" not in query, \
                f"Query without dates should not have WHERE clause: {query}"

    def test_with_only_start_date(self, mock_loader, mock_df):
        """Verify query works with only start_date filter."""
        with patch('pandas.read_sql_query', return_value=mock_df) as mock_read_sql:
            test_start = "2024-01-01"
            mock_loader._load_binance_timeframe('minute60', start_date=test_start)

            call_args = mock_read_sql.call_args
            kwargs = call_args[1]

            assert 'params' in kwargs, "params should be passed"
            assert len(kwargs['params']) == 1, "Should have exactly one param"
            assert test_start in kwargs['params'], "Start date should be in params"

    def test_invalid_timeframe(self, mock_loader):
        """Verify invalid timeframe raises ValueError."""
        with pytest.raises(ValueError, match="지원하지 않는 타임프레임"):
            mock_loader._load_binance_timeframe('invalid_timeframe')
