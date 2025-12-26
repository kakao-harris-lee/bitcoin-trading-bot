"""
Trading Engine V2 - Phase 3 Unit Tests
전략 모듈 및 리스크 매니저 테스트

테스트 대상:
- MarketClassifier: 시장 상태 분류
- DynamicExitManager: 동적 익절/손절 관리
- V35LongStrategy: Upbit Long 전략
- ShortV1Strategy: Binance Short 전략
- RiskManager: 신호 검증 및 위험 관리
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 테스트 대상 모듈
from trading.strategy.v35_long import (
    V35LongStrategy, MarketClassifier, DynamicExitManager
)
from trading.strategy.short_v1 import ShortV1Strategy
from trading.risk.risk_manager import RiskManager, RiskState
from core.types import (
    PriceMessage, SignalMessage, Exchange, Direction, Action, EventType
)
from trading.core.config import Config


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_ohlcv_df():
    """테스트용 OHLCV DataFrame"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range(start='2024-01-01', periods=n, freq='1h')

    # 상승 트렌드 데이터 생성
    close = 50000000 + np.cumsum(np.random.randn(n) * 100000)
    high = close + np.abs(np.random.randn(n) * 50000)
    low = close - np.abs(np.random.randn(n) * 50000)
    open_ = close + np.random.randn(n) * 30000
    volume = np.abs(np.random.randn(n) * 1000) + 500

    return pd.DataFrame({
        'timestamp': dates,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


@pytest.fixture
def mock_config():
    """Mock Config"""
    config = MagicMock(spec=Config)
    config.redis = MagicMock()
    config.redis.streams = {
        'prices': 'market:prices',
        'signals': 'strategy:signals',
        'pending_orders': 'orders:pending',
        'events': 'system:events',
    }
    config.trading = MagicMock()
    config.trading.upbit_enabled = True
    config.trading.binance_enabled = True
    return config


@pytest.fixture
def classifier_config():
    """MarketClassifier 설정"""
    return {
        'mfi_bull_strong': 52,
        'mfi_bull_moderate': 45,
        'mfi_sideways_up': 42,
        'mfi_bear_moderate': 38,
        'mfi_bear_strong': 35,
        'adx_strong_trend': 20,
        'adx_moderate_trend': 15,
    }


@pytest.fixture
def exit_manager_config():
    """DynamicExitManager 설정"""
    return {
        'stop_loss': -0.015,
        'tp_bull_strong_1': 0.05,
        'tp_bull_strong_2': 0.10,
        'tp_bull_strong_3': 0.20,
        'tp_bull_moderate_1': 0.03,
        'tp_bull_moderate_2': 0.07,
        'tp_bull_moderate_3': 0.12,
        'tp_sideways_1': 0.02,
        'tp_sideways_2': 0.04,
        'tp_sideways_3': 0.06,
    }


# =============================================================================
# MarketClassifier Tests
# =============================================================================

class TestMarketClassifier:
    """MarketClassifier 단위 테스트"""

    def test_init(self, classifier_config):
        """초기화 테스트"""
        classifier = MarketClassifier(classifier_config)
        assert classifier.mfi_bull_strong == 52
        assert classifier.adx_strong_trend == 20

    def test_classify_bull_strong(self, classifier_config):
        """BULL_STRONG 분류 테스트"""
        classifier = MarketClassifier(classifier_config)

        # BULL_STRONG: MFI >= 52, ADX >= 20
        row = pd.Series({'mfi': 60, 'adx': 25})
        state = classifier.classify(row)
        assert state == 'BULL_STRONG'

    def test_classify_bull_moderate(self, classifier_config):
        """BULL_MODERATE 분류 테스트"""
        classifier = MarketClassifier(classifier_config)

        # BULL_MODERATE: MFI >= 45, ADX >= 15
        row = pd.Series({'mfi': 48, 'adx': 18})
        state = classifier.classify(row)
        assert state == 'BULL_MODERATE'

    def test_classify_bear_strong(self, classifier_config):
        """BEAR_STRONG 분류 테스트"""
        classifier = MarketClassifier(classifier_config)

        # BEAR_STRONG: MFI < 35, ADX >= 20
        row = pd.Series({'mfi': 30, 'adx': 25})
        state = classifier.classify(row)
        assert state == 'BEAR_STRONG'

    def test_classify_bear_moderate(self, classifier_config):
        """BEAR_MODERATE 분류 테스트"""
        classifier = MarketClassifier(classifier_config)

        # BEAR_MODERATE: MFI < 35, ADX < 20
        row = pd.Series({'mfi': 30, 'adx': 15})
        state = classifier.classify(row)
        assert state == 'BEAR_MODERATE'

    def test_classify_sideways(self, classifier_config):
        """SIDEWAYS 분류 테스트"""
        classifier = MarketClassifier(classifier_config)

        # SIDEWAYS_UP: 42 <= MFI < 45
        row = pd.Series({'mfi': 43, 'adx': 10})
        state = classifier.classify(row)
        assert state == 'SIDEWAYS_UP'

        # SIDEWAYS_FLAT: 38 <= MFI < 42
        row = pd.Series({'mfi': 40, 'adx': 10})
        state = classifier.classify(row)
        assert state == 'SIDEWAYS_FLAT'

        # SIDEWAYS_DOWN: 35 <= MFI < 38
        row = pd.Series({'mfi': 36, 'adx': 10})
        state = classifier.classify(row)
        assert state == 'SIDEWAYS_DOWN'


# =============================================================================
# DynamicExitManager Tests
# =============================================================================

class TestDynamicExitManager:
    """DynamicExitManager 단위 테스트"""

    @pytest.fixture
    def exit_manager(self, exit_manager_config):
        return DynamicExitManager(exit_manager_config)

    def test_init(self, exit_manager):
        """초기화 테스트"""
        assert exit_manager.entry_price == 0.0
        assert exit_manager.market_state == 'UNKNOWN'
        assert exit_manager.partial_exits == 0

    def test_set_entry(self, exit_manager):
        """진입 설정 테스트"""
        exit_manager.set_entry(50000000, 'BULL_STRONG')
        assert exit_manager.entry_price == 50000000
        assert exit_manager.market_state == 'BULL_STRONG'
        assert exit_manager.partial_exits == 0

    def test_reset(self, exit_manager):
        """리셋 테스트"""
        exit_manager.set_entry(50000000, 'BULL_STRONG')
        exit_manager.reset()
        assert exit_manager.entry_price == 0.0
        assert exit_manager.market_state == 'UNKNOWN'

    def test_no_exit_without_entry(self, exit_manager):
        """진입 없이 청산 없음"""
        result = exit_manager.check_exit(50100000, 'BULL_STRONG')
        assert result is None

    def test_no_exit_on_small_profit(self, exit_manager):
        """작은 이익에서 청산 없음"""
        exit_manager.set_entry(50000000, 'BULL_STRONG')
        result = exit_manager.check_exit(50100000, 'BULL_STRONG')  # +0.2%
        # TP1 (5%) 미달
        assert result is None

    def test_stop_loss_trigger(self, exit_manager):
        """스탑로스 트리거"""
        exit_manager.set_entry(50000000, 'BULL_STRONG')
        result = exit_manager.check_exit(49000000, 'BULL_STRONG')  # -2%
        assert result is not None
        assert result['action'] == 'sell'
        assert 'STOP_LOSS' in result['reason']

    def test_partial_exit_tp1_bull_strong(self, exit_manager):
        """BULL_STRONG TP1 (5%) 도달 시 부분 청산"""
        exit_manager.set_entry(50000000, 'BULL_STRONG')
        result = exit_manager.check_exit(52600000, 'BULL_STRONG')  # +5.2%
        assert result is not None
        assert result['action'] == 'sell'
        assert result['fraction'] == 0.4  # 40% 청산
        assert 'TP_LEVEL_1' in result['reason']

    def test_macd_dead_cross_exit(self, exit_manager):
        """MACD 데드크로스 청산"""
        exit_manager.set_entry(50000000, 'BULL_STRONG')
        result = exit_manager.check_exit(
            50500000,  # +1%
            'BULL_STRONG',
            macd=-0.5,
            macd_signal=0.5
        )
        assert result is not None
        assert result['action'] == 'sell'
        assert 'MACD_DEAD_CROSS' in result['reason']


# =============================================================================
# V35LongStrategy Tests
# =============================================================================

class TestV35LongStrategy:
    """V35LongStrategy 단위 테스트"""

    @pytest.fixture
    def strategy(self):
        """전략 인스턴스 (Redis 없이)"""
        with patch.object(V35LongStrategy, 'redis', new_callable=MagicMock):
            strat = V35LongStrategy(config=None)
            return strat

    def test_init(self, strategy):
        """초기화 테스트"""
        assert strategy.strategy_name == "v35-long"
        assert strategy.exchange == Exchange.UPBIT
        assert strategy.direction == Direction.LONG
        assert strategy.symbol == "KRW-BTC"

    def test_add_indicators(self, strategy, sample_ohlcv_df):
        """지표 추가 테스트"""
        df = strategy.add_indicators(sample_ohlcv_df.copy())

        # 필수 지표 존재 확인
        assert 'rsi' in df.columns
        assert 'macd' in df.columns
        assert 'macd_signal' in df.columns
        assert 'bb_upper' in df.columns
        assert 'bb_lower' in df.columns
        assert 'adx' in df.columns
        assert 'mfi' in df.columns

    def test_min_buffer_size(self, strategy):
        """최소 버퍼 크기"""
        assert strategy._min_buffer_size() == 30

    def test_has_classifier_and_exit_manager(self, strategy):
        """MarketClassifier와 DynamicExitManager 존재 확인"""
        assert isinstance(strategy.classifier, MarketClassifier)
        assert isinstance(strategy.exit_manager, DynamicExitManager)


# =============================================================================
# ShortV1Strategy Tests
# =============================================================================

class TestShortV1Strategy:
    """ShortV1Strategy 단위 테스트"""

    @pytest.fixture
    def strategy(self):
        """전략 인스턴스 (Redis 없이)"""
        with patch.object(ShortV1Strategy, 'redis', new_callable=MagicMock):
            strat = ShortV1Strategy(config=None)
            return strat

    def test_init(self, strategy):
        """초기화 테스트"""
        assert strategy.strategy_name == "short-v1"
        assert strategy.exchange == Exchange.BINANCE
        assert strategy.direction == Direction.SHORT
        assert strategy.symbol == "BTCUSDT"

    def test_add_indicators(self, strategy, sample_ohlcv_df):
        """EMA/ADX/DI 지표 추가 테스트"""
        df = strategy.add_indicators(sample_ohlcv_df.copy())

        # 필수 지표 존재 확인
        assert 'ema_fast' in df.columns
        assert 'ema_slow' in df.columns
        assert 'adx' in df.columns
        assert 'plus_di' in df.columns
        assert 'minus_di' in df.columns
        assert 'death_cross' in df.columns
        assert 'golden_cross' in df.columns
        assert 'trend' in df.columns

    def test_min_buffer_size(self, strategy):
        """최소 버퍼 크기 (EMA 200)"""
        assert strategy._min_buffer_size() == 200

    def test_death_cross_detection(self, strategy):
        """데드크로스 감지 테스트"""
        # 데드크로스 시나리오: EMA50이 EMA200 아래로
        n = 250
        df = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=n, freq='1h'),
            'close': np.concatenate([
                np.linspace(55000, 52000, 125),  # 전반: 약간 하락
                np.linspace(52000, 45000, 125),  # 후반: 급락
            ]),
        })
        df['high'] = df['close'] * 1.01
        df['low'] = df['close'] * 0.99
        df['open'] = df['close']
        df['volume'] = 100

        df = strategy.add_indicators(df)

        # 후반부에 death_cross True가 있어야 함
        assert df['death_cross'].any(), "데드크로스가 감지되어야 함"


# =============================================================================
# RiskManager Tests
# =============================================================================

class TestRiskManager:
    """RiskManager 단위 테스트"""

    @pytest.fixture
    def risk_manager(self):
        """RiskManager 인스턴스 (Redis 없이)"""
        with patch.object(RiskManager, 'redis', new_callable=MagicMock):
            rm = RiskManager(
                config=None,
                initial_capital=10_000_000,
                risk_params={
                    'max_drawdown_pct': 20.0,
                    'daily_loss_limit_pct': 5.0,
                    'max_daily_trades': 10,
                    'cooldown_seconds': 60,
                }
            )
            return rm

    def test_initial_state(self, risk_manager):
        """초기 상태 테스트"""
        state = risk_manager.get_risk_state()
        assert state['total_equity'] == 10_000_000
        assert state['daily_pnl'] == 0
        assert state['current_drawdown'] == 0
        assert state['daily_trades'] == 0

    def test_approve_valid_signal(self, risk_manager):
        """유효한 신호 승인"""
        signal = {
            'strategy': 'v35_long',
            'exchange': 'upbit',
            'action': 'buy',
            'fraction': 0.3,
        }

        result = risk_manager._validate_signal(signal)
        assert result['approved'] is True
        assert result['adjusted_fraction'] > 0

    def test_reject_on_daily_loss_limit(self, risk_manager):
        """일일 손실 한도 초과 시 거부"""
        # 일일 손실 5% 초과 설정
        risk_manager.state.daily_pnl_pct = -6.0

        signal = {
            'strategy': 'v35_long',
            'exchange': 'upbit',
            'action': 'buy',
            'fraction': 0.3,
        }

        result = risk_manager._validate_signal(signal)
        assert result['approved'] is False
        assert 'DAILY_LOSS_LIMIT' in result['reason']

    def test_reject_on_max_drawdown(self, risk_manager):
        """최대 낙폭 초과 시 거부"""
        risk_manager.state.current_drawdown = 25.0  # 20% 초과

        signal = {
            'strategy': 'short_v1',
            'exchange': 'binance',
            'action': 'open_short',
            'fraction': 0.5,
        }

        result = risk_manager._validate_signal(signal)
        assert result['approved'] is False
        assert 'MAX_DRAWDOWN' in result['reason']

    def test_reject_on_max_trades(self, risk_manager):
        """일일 거래 횟수 초과 시 거부"""
        risk_manager.state.daily_trades = 15  # 10 초과

        signal = {
            'strategy': 'v35_long',
            'exchange': 'upbit',
            'action': 'buy',
            'fraction': 0.2,
        }

        result = risk_manager._validate_signal(signal)
        assert result['approved'] is False
        assert 'MAX_DAILY_TRADES' in result['reason']

    def test_cooldown_enforcement(self, risk_manager):
        """쿨다운 시행 테스트"""
        # 첫 번째 신호 승인
        signal = {
            'strategy': 'v35_long',
            'exchange': 'upbit',
            'action': 'buy',
            'fraction': 0.3,
        }
        result1 = risk_manager._validate_signal(signal)
        assert result1['approved'] is True

        # 즉시 두 번째 신호 (쿨다운 중)
        result2 = risk_manager._validate_signal(signal)
        assert result2['approved'] is False
        assert 'COOLDOWN' in result2['reason']

    def test_update_equity(self, risk_manager):
        """자산 업데이트 테스트"""
        risk_manager.update_equity(12_000_000)  # 20% 이익

        state = risk_manager.get_risk_state()
        assert state['total_equity'] == 12_000_000
        assert state['daily_pnl'] == 2_000_000
        assert state['daily_pnl_pct'] == 20.0

    def test_drawdown_calculation(self, risk_manager):
        """낙폭 계산 테스트"""
        # 피크 형성
        risk_manager.update_equity(11_000_000)
        assert risk_manager.state.peak_equity == 11_000_000

        # 낙폭 발생
        risk_manager.update_equity(9_500_000)

        expected_dd = (11_000_000 - 9_500_000) / 11_000_000 * 100
        assert abs(risk_manager.state.current_drawdown - expected_dd) < 0.1

    def test_position_update(self, risk_manager):
        """포지션 업데이트 테스트"""
        risk_manager.update_position(
            exchange='upbit',
            symbol='KRW-BTC',
            quantity=0.1,
            entry_price=50000000,
            current_price=52000000,
            direction='long',
            leverage=1
        )

        assert len(risk_manager.state.positions) == 1
        assert risk_manager.state.long_exposure > 0

    def test_hedge_ratio_calculation(self, risk_manager):
        """헤지 비율 계산 테스트"""
        # Long 포지션
        risk_manager.update_position(
            exchange='upbit',
            symbol='KRW-BTC',
            quantity=0.1,
            entry_price=50000000,
            current_price=50000000,
            direction='long'
        )

        # Short 포지션
        risk_manager.update_position(
            exchange='binance',
            symbol='BTCUSDT',
            quantity=0.05,
            entry_price=50000,
            current_price=50000,
            direction='short'
        )

        # 헤지 비율 = short / long
        assert risk_manager.state.hedge_ratio > 0

    def test_create_order(self, risk_manager):
        """주문 생성 테스트"""
        signal = {
            'id': 'sig-001',
            'strategy': 'v35_long',
            'exchange': 'upbit',
            'symbol': 'KRW-BTC',
            'action': 'buy',
            'direction': 'long',
            'leverage': 1,
            'stop_loss_pct': 2.0,
            'take_profit_pct': 5.0,
            'metadata': {'reason': 'MOMENTUM_ENTRY'},
        }

        validation = {
            'approved': True,
            'reason': 'APPROVED',
            'adjusted_fraction': 0.25,
        }

        order = risk_manager._create_order(signal, validation)

        assert order['signal_id'] == 'sig-001'
        assert order['exchange'] == 'upbit'
        assert order['quantity'] == 0.25
        assert order['status'] == 'pending'

    def test_get_stats(self, risk_manager):
        """통계 조회 테스트"""
        # 신호 처리
        risk_manager._signals_received = 100
        risk_manager._signals_approved = 80
        risk_manager._signals_rejected = 20

        stats = risk_manager.get_stats()

        assert stats['signals_received'] == 100
        assert stats['signals_approved'] == 80
        assert stats['signals_rejected'] == 20
        assert stats['approval_rate'] == 80.0


# =============================================================================
# Integration Tests
# =============================================================================

class TestPhase3Integration:
    """Phase 3 통합 테스트"""

    @pytest.fixture
    def full_pipeline(self):
        """전체 파이프라인 설정"""
        with patch.object(V35LongStrategy, 'redis', new_callable=MagicMock), \
             patch.object(ShortV1Strategy, 'redis', new_callable=MagicMock), \
             patch.object(RiskManager, 'redis', new_callable=MagicMock):

            v35 = V35LongStrategy(config=None)
            short_v1 = ShortV1Strategy(config=None)
            risk_mgr = RiskManager(config=None)

            return {
                'v35': v35,
                'short_v1': short_v1,
                'risk_manager': risk_mgr,
            }

    def test_strategy_signal_format(self, full_pipeline, sample_ohlcv_df):
        """전략 신호 포맷 검증"""
        v35 = full_pipeline['v35']

        # 지표 추가
        df = v35.add_indicators(sample_ohlcv_df.copy())

        # 마지막 행으로 classifier 테스트
        last_row = df.iloc[-1]
        market_state = v35.classifier.classify(last_row)

        # 시장 상태는 유효한 값이어야 함
        valid_states = [
            'BULL_STRONG', 'BULL_MODERATE',
            'SIDEWAYS_UP', 'SIDEWAYS_FLAT', 'SIDEWAYS_DOWN',
            'BEAR_MODERATE', 'BEAR_STRONG'
        ]
        assert market_state in valid_states

    def test_risk_manager_validates_signals(self, full_pipeline):
        """리스크 매니저 신호 검증"""
        risk_mgr = full_pipeline['risk_manager']

        # 정상 신호
        signal = {
            'strategy': 'v35_long',
            'exchange': 'upbit',
            'action': 'buy',
            'fraction': 0.3,
        }

        result = risk_mgr._validate_signal(signal)
        assert 'approved' in result
        assert 'adjusted_fraction' in result
        assert 'reason' in result

    def test_multiple_strategies_hedge(self, full_pipeline):
        """다중 전략 헤지 비율"""
        risk_mgr = full_pipeline['risk_manager']

        # Long 진입
        risk_mgr.update_position(
            exchange='upbit',
            symbol='KRW-BTC',
            quantity=1.0,
            entry_price=50000000,
            current_price=50000000,
            direction='long'
        )

        # Short 진입
        risk_mgr.update_position(
            exchange='binance',
            symbol='BTCUSDT',
            quantity=0.4,
            entry_price=50000,
            current_price=50000,
            direction='short'
        )

        state = risk_mgr.get_risk_state()

        # Long + Short 모두 존재
        assert state['long_exposure'] > 0
        assert state['short_exposure'] > 0
        assert 0 < state['hedge_ratio'] < 1


# =============================================================================
# Run tests
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
