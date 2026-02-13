"""Regression tests for backtest visualizer module importability."""

from core.backtest_visualizer import BacktestVisualizer


def test_backtest_visualizer_can_be_instantiated():
    """Visualizer should import and construct without NameError at module load."""
    visualizer = BacktestVisualizer()
    assert visualizer is not None
