"""
Custom exceptions for daily backtest comparison reports.
"""
# pylint: disable=unnecessary-ellipsis


class ComparisonError(Exception):
    """Base exception for comparison report errors."""
    ...


class DataNotFoundError(ComparisonError):
    """Raised when required data is not available."""
    ...


class DatabaseError(ComparisonError):
    """Raised when database operations fail."""
    ...


class BacktestError(ComparisonError):
    """Raised when backtest execution fails."""
    ...


class ConfigurationError(ComparisonError):
    """Raised when configuration is invalid or missing."""
    ...
