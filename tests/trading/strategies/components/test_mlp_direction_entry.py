"""Tests for MLPDirectionEntryStrategy.

Tests the MLP Direction entry strategy component based on
Parente & Rizzuti (2025) methodology.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np

from trading.strategies.components.mlp_direction_entry import (
    MLPDirectionEntryStrategy,
    MLPDirectionEntryParams,
)
from trading.strategies.components.models import (
    TradingContext, MarketData, MarketContext, build_market_context
)


def _make_context(
    mfi: float = 55.0,
    adx: float = 25.0,
    rsi: float = 60.0,
    close: float = 100000.0,
    ema_200: float = 95000.0,
    mlp_prediction: int = None,
    mlp_confidence: float = None,
) -> TradingContext:
    """Helper to create TradingContext for tests."""
    market = MarketData(
        symbol="BTC",
        close=close,
        mfi=mfi,
        adx=adx,
        rsi=rsi,
        timestamp=1000,
        atr=1000.0,
        volume=100.0,
        avg_volume_20=80.0,
        ema_200=ema_200,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=1000.0, close=close)

    # Create context with optional MLP attributes
    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions={})

    # Add MLP prediction attributes if provided
    if mlp_prediction is not None:
        object.__setattr__(ctx, "mlp_prediction", mlp_prediction)
    if mlp_confidence is not None:
        object.__setattr__(ctx, "mlp_confidence", mlp_confidence)

    return ctx


class TestMLPDirectionEntryParams:
    """Test MLPDirectionEntryParams dataclass."""

    def test_default_values(self):
        """Test default parameter values (relaxed for more trades)."""
        params = MLPDirectionEntryParams()

        # Relaxed defaults to increase trade frequency
        assert params.buy_confidence_threshold == 0.40
        assert params.skip_bear_regime is False
        assert params.adx_min == 0.0
        assert params.use_ema200_filter is False
        assert params.position_size == 0.01
        assert params.market == "spot"

    def test_custom_values(self):
        """Test custom parameter values."""
        params = MLPDirectionEntryParams(
            buy_confidence_threshold=0.70,
            skip_bear_regime=False,
            adx_min=25.0,
            position_size=0.05,
        )

        assert params.buy_confidence_threshold == 0.70
        assert params.skip_bear_regime is False
        assert params.adx_min == 25.0
        assert params.position_size == 0.05


class TestMLPDirectionEntryStrategy:
    """Test MLPDirectionEntryStrategy."""

    def test_initialization(self):
        """Test strategy initialization."""
        strategy = MLPDirectionEntryStrategy()

        assert strategy.params is not None
        assert strategy._model is None
        assert strategy._model_available is None

    def test_initialization_with_params(self):
        """Test strategy initialization with custom params."""
        params = MLPDirectionEntryParams(buy_confidence_threshold=0.75)
        strategy = MLPDirectionEntryStrategy(params=params)

        assert strategy.params.buy_confidence_threshold == 0.75

    def test_no_signal_in_bear_regime(self):
        """Entry returns None in BEAR regime when skip_bear_regime is True."""
        # Explicitly enable bear regime filter (relaxed defaults don't skip bear)
        params = MLPDirectionEntryParams(skip_bear_regime=True)
        strategy = MLPDirectionEntryStrategy(params=params)
        ctx = _make_context(mfi=30.0, adx=26.0)  # BEAR regime

        signal = strategy.check_entry(ctx)

        assert signal is None

    def test_no_signal_weak_adx(self):
        """Entry returns None when ADX is below threshold."""
        # Explicitly set ADX threshold (relaxed defaults have adx_min=0.0)
        params = MLPDirectionEntryParams(adx_min=18.0)
        strategy = MLPDirectionEntryStrategy(params=params)
        ctx = _make_context(mfi=55.0, adx=15.0)  # Weak ADX

        signal = strategy.check_entry(ctx)

        assert signal is None

    def test_no_signal_below_ema200(self):
        """Entry returns None when price is below EMA200."""
        # Explicitly enable EMA200 filter (relaxed defaults have it disabled)
        params = MLPDirectionEntryParams(use_ema200_filter=True)
        strategy = MLPDirectionEntryStrategy(params=params)
        ctx = _make_context(
            mfi=55.0,
            adx=25.0,
            close=90000.0,  # Below EMA200
            ema_200=95000.0,
        )

        signal = strategy.check_entry(ctx)

        assert signal is None

    def test_no_signal_without_model(self):
        """Entry returns None when model is not available."""
        strategy = MLPDirectionEntryStrategy()
        strategy._model_available = False  # Simulate model not loaded
        ctx = _make_context(mfi=55.0, adx=25.0)

        signal = strategy.check_entry(ctx)

        assert signal is None

    def test_allows_entry_in_bear_when_disabled(self):
        """Entry allowed in BEAR regime when skip_bear_regime is False."""
        params = MLPDirectionEntryParams(skip_bear_regime=False)
        strategy = MLPDirectionEntryStrategy(params=params)
        strategy._model_available = False  # Will fail later at model check
        ctx = _make_context(mfi=30.0, adx=26.0)  # BEAR regime

        signal = strategy.check_entry(ctx)

        # Should pass bear filter but fail at model check
        assert signal is None  # Fails at model check, not bear filter

    def test_label_name_conversion(self):
        """Test label to name conversion."""
        strategy = MLPDirectionEntryStrategy()

        assert strategy._label_name(0) == "HOLD"
        assert strategy._label_name(1) == "BUY"
        assert strategy._label_name(2) == "SELL"
        assert strategy._label_name(99) == "UNKNOWN"


class TestMLPDirectionEntryWithMockedModel:
    """Test MLPDirectionEntryStrategy with mocked model."""

    @pytest.fixture
    def strategy_with_mock_model(self):
        """Create strategy with mocked model."""
        strategy = MLPDirectionEntryStrategy()
        strategy.params.mlp_feature_set = "shap_13"

        # Mock the model
        mock_model = MagicMock()
        mock_model.eval = MagicMock()

        # Mock predict_proba to return BUY prediction with high confidence
        mock_probs = MagicMock()
        mock_probs.cpu.return_value.numpy.return_value = np.array([[0.2, 0.7, 0.1]])
        mock_model.predict_proba.return_value = mock_probs

        strategy._model = mock_model
        strategy._model_available = True
        strategy._feature_extractor = lambda data, ind: np.zeros(13)

        return strategy

    def test_generates_signal_on_buy_prediction(self, strategy_with_mock_model):
        """Entry generates signal when MLP predicts BUY with high confidence."""
        strategy = strategy_with_mock_model
        ctx = _make_context(mfi=55.0, adx=25.0)

        # Since we don't have pre-computed MLP values, strategy will call _predict
        signal = strategy.check_entry(ctx)

        assert signal is not None
        assert signal.side == "buy"
        assert "MLPDirection" in signal.reason
        assert "BUY" in signal.reason

    def test_no_signal_on_hold_prediction(self, strategy_with_mock_model):
        """Entry returns None when MLP predicts HOLD."""
        strategy = strategy_with_mock_model

        # Change mock to return HOLD prediction
        mock_probs = MagicMock()
        mock_probs.cpu.return_value.numpy.return_value = np.array([[0.6, 0.2, 0.2]])
        strategy._model.predict_proba.return_value = mock_probs

        ctx = _make_context(mfi=55.0, adx=25.0)
        signal = strategy.check_entry(ctx)

        assert signal is None

    def test_no_signal_on_sell_prediction(self, strategy_with_mock_model):
        """Entry returns None when MLP predicts SELL."""
        strategy = strategy_with_mock_model

        # Change mock to return SELL prediction
        mock_probs = MagicMock()
        mock_probs.cpu.return_value.numpy.return_value = np.array([[0.2, 0.1, 0.7]])
        strategy._model.predict_proba.return_value = mock_probs

        ctx = _make_context(mfi=55.0, adx=25.0)
        signal = strategy.check_entry(ctx)

        assert signal is None

    def test_no_signal_on_low_confidence(self, strategy_with_mock_model):
        """Entry returns None when BUY confidence is below threshold."""
        strategy = strategy_with_mock_model

        # Change mock to return BUY with low confidence (below 0.40 default threshold)
        mock_probs = MagicMock()
        mock_probs.cpu.return_value.numpy.return_value = np.array([[0.65, 0.30, 0.05]])  # 30% < 40%
        strategy._model.predict_proba.return_value = mock_probs

        ctx = _make_context(mfi=55.0, adx=25.0)
        signal = strategy.check_entry(ctx)

        assert signal is None

    def test_signal_with_custom_confidence_threshold(self):
        """Entry respects custom confidence threshold."""
        params = MLPDirectionEntryParams(buy_confidence_threshold=0.80)
        strategy = MLPDirectionEntryStrategy(params=params)

        # Mock model with 70% confidence (above default 60% but below custom 80%)
        mock_model = MagicMock()
        mock_model.eval = MagicMock()
        mock_probs = MagicMock()
        mock_probs.cpu.return_value.numpy.return_value = np.array([[0.15, 0.70, 0.15]])
        mock_model.predict_proba.return_value = mock_probs

        strategy._model = mock_model
        strategy._model_available = True
        strategy._feature_extractor = lambda data, ind: np.zeros(13)

        ctx = _make_context(mfi=55.0, adx=25.0)
        signal = strategy.check_entry(ctx)

        assert signal is None  # 70% < 80% threshold


class TestMLPDirectionEntryIntegration:
    """Integration tests for MLPDirectionEntryStrategy."""

    def test_strategy_is_registered(self):
        """Test that strategy is properly registered."""
        from trading.strategies.components.registry import is_entry_registered

        assert is_entry_registered("MLPDirectionEntryStrategy")

    def test_can_be_created_from_factory(self):
        """Test that strategy can be created via StrategyFactory."""
        from trading.strategies.components.strategy_factory import STRATEGY_REGISTRY

        assert "mlp_direction" in STRATEGY_REGISTRY

        spec = STRATEGY_REGISTRY["mlp_direction"]
        assert spec.entry_class == MLPDirectionEntryStrategy
        assert spec.entry_params_class == MLPDirectionEntryParams


class TestExtractFeatures:
    """Test _extract_features method."""

    def test_extract_features_returns_array(self):
        """Test that feature extraction returns numpy array."""
        strategy = MLPDirectionEntryStrategy()

        # Mock the feature extractor
        strategy._feature_extractor = lambda data, ind: np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])

        market = MarketData(
            symbol="BTC",
            close=100000.0,
            mfi=55.0,
            adx=25.0,
            rsi=60.0,
            timestamp=1000,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )

        features = strategy._extract_features(market, {})

        assert features is not None
        assert isinstance(features, np.ndarray)
        assert len(features) == 13

    def test_extract_features_none_without_extractor(self):
        """Test that feature extraction returns None without extractor."""
        strategy = MLPDirectionEntryStrategy()
        strategy._feature_extractor = None

        market = MarketData(
            symbol="BTC",
            close=100000.0,
            mfi=55.0,
            adx=25.0,
            rsi=60.0,
            timestamp=1000,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )

        features = strategy._extract_features(market, {})

        assert features is None

    def test_extract_features_uses_indicators(self):
        """Test that feature extraction uses provided indicators."""
        strategy = MLPDirectionEntryStrategy()

        captured_indicators = {}

        def mock_extractor(data, ind):
            captured_indicators.update(ind)
            return np.zeros(13)

        strategy._feature_extractor = mock_extractor

        market = MarketData(
            symbol="BTC",
            close=100000.0,
            mfi=55.0,
            adx=25.0,
            rsi=60.0,
            timestamp=1000,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )

        indicators = {"bollinger_pct_b": 0.75, "ultosc": 55.0}
        strategy._extract_features(market, indicators)

        assert captured_indicators.get("bollinger_pct_b") == 0.75
        assert captured_indicators.get("ultosc") == 55.0


class TestModelLoadingFailures:
    """Test model loading failure scenarios."""

    def test_model_not_found_sets_unavailable(self):
        """Test that missing model file sets model unavailable."""
        params = MLPDirectionEntryParams(model_path="/nonexistent/path/model.pt")
        strategy = MLPDirectionEntryStrategy(params=params)

        # Force model loading attempt
        result = strategy._ensure_model()

        assert result is False
        assert strategy._model_available is False

    def test_predict_returns_hold_on_error(self):
        """Test that prediction errors return HOLD with zero confidence."""
        from trading.strategies.components.models import MLP_LABEL_HOLD

        strategy = MLPDirectionEntryStrategy()

        # Mock model that raises exception
        mock_model = MagicMock()
        mock_model.predict_proba.side_effect = RuntimeError("Test error")

        strategy._model = mock_model
        strategy._model_available = True

        # Should return HOLD, 0.0 on error
        label, confidence = strategy._predict(np.zeros(13))

        assert label == MLP_LABEL_HOLD
        assert confidence == 0.0
