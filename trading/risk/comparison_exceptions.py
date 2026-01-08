"""
Custom exceptions for daily backtest comparison reports.
"""


class ComparisonError(Exception):
    """Base exception for comparison report errors."""
    pass


class DataNotFoundError(ComparisonError):
    """Raised when required data is not available."""
    pass


class DatabaseError(ComparisonError):
    """Raised when database operations fail."""
    pass


class BacktestError(ComparisonError):
    """Raised when backtest execution fails."""
    pass


class ConfigurationError(ComparisonError):
    """Raised when configuration is invalid or missing."""
    pass
