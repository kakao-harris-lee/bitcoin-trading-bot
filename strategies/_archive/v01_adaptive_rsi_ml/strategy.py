#!/usr/bin/env python3
"""
strategy.py
v01 전략: Adaptive RSI + ML 검증

3단계 시스템:
1. MarketClassifier → 시장 상태 파악
2. AdaptiveThreshold → 동적 RSI 임계값 계산
3. MLSignalValidator → 신호 검증
"""

import sys
sys.path.append('../..')

from adaptive_threshold import AdaptiveThreshold
from market_classifier import MarketClassifier
from ml_model import MLSignalValidator


class AdaptiveRSIMLStrategy:
    """v01: Adaptive RSI + ML 전략"""

    def __init__(self, config: dict, ml_model: MLSignalValidator):
        """
        Args:
            config: config.json 내용
            ml_model: 학습된 ML 모델
        """
        self.config = config

        # 1. 시장 분류기
        self.market_classifier = MarketClassifier(
            window=config['rolling_window'],
            adx_period=config['adx_period'],
            adx_threshold=config['adx_threshold']
        )

        # 2. 적응형 임계값 계산기
        self.adaptive_threshold = AdaptiveThreshold(
            window=config['rolling_window'],
            base_oversold=config['adaptive_rsi']['base_oversold'],
            base_overbought=config['adaptive_rsi']['base_overbought'],
            adjustment_range=config['adaptive_rsi']['adjustment_range'],
            volatility_threshold_high=config['volatility_threshold']['high'],
            volatility_threshold_low=config['volatility_threshold']['low']
        )

        # 3. ML 검증기
        self.ml_validator = ml_model

        # 상태 추적
        self.position = None  # None | 'long'
        self.entry_price = 0.0

    def generate_signal(self, df, i: int) -> dict:
        """
        매 캔들마다 호출되는 신호 생성 함수

        Returns:
            {
                'action': 'buy' | 'sell' | 'hold',
                'fraction': float (0~1, 매수/매도 비율),
                'reason': str (판단 근거)
            }
        """
        # 최소 데이터 확보
        if i < self.config['rolling_window']:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        # 1단계: 시장 상태 분류
        market = self.market_classifier.classify(df, i)

        # 2단계: 적응형 RSI 임계값 계산
        thresholds = self.adaptive_threshold.calculate_thresholds(df, i)

        # 현재 RSI
        rsi = df.iloc[i]['rsi']

        # 3단계: 신호 생성 (규칙 기반)
        raw_signal = None
        reason = ""

        # 매수 신호: RSI < 과매도 임계값
        if rsi < thresholds['oversold']:
            raw_signal = 'buy'
            reason = f"RSI({rsi:.1f}) < oversold({thresholds['oversold']:.1f}), market={market['state']}"

        # 매도 신호: RSI > 과매수 임계값
        elif rsi > thresholds['overbought']:
            raw_signal = 'sell'
            reason = f"RSI({rsi:.1f}) > overbought({thresholds['overbought']:.1f}), market={market['state']}"

        # 보유 중일 때 손절/익절 체크
        elif self.position == 'long':
            current_price = df.iloc[i]['close']
            pnl_ratio = (current_price - self.entry_price) / self.entry_price

            # 익절 1차 (5%)
            if pnl_ratio >= self.config['risk_management']['take_profit_1']:
                raw_signal = 'sell'
                reason = f"take_profit_1 ({pnl_ratio:.2%})"

            # 익절 2차 (10%)
            elif pnl_ratio >= self.config['risk_management']['take_profit_2']:
                raw_signal = 'sell'
                reason = f"take_profit_2 ({pnl_ratio:.2%})"

            # 손절 (-3%)
            elif pnl_ratio <= self.config['risk_management']['stop_loss']:
                raw_signal = 'sell'
                reason = f"stop_loss ({pnl_ratio:.2%})"

        # 4단계: ML 검증
        if raw_signal in ['buy', 'sell']:
            ml_result = self.ml_validator.predict(df, i)

            # ML이 승인하지 않으면 hold
            if not ml_result['approved']:
                return {
                    'action': 'hold',
                    'fraction': 0.0,
                    'reason': f"ML rejected: {raw_signal} (confidence={ml_result['confidence']:.2%})"
                }

            reason += f" [ML approved: {ml_result['confidence']:.2%}]"

        # 최종 신호 반환
        if raw_signal == 'buy' and self.position is None:
            return {
                'action': 'buy',
                'fraction': self.config['kelly_fraction'],
                'reason': reason
            }

        elif raw_signal == 'sell' and self.position == 'long':
            return {
                'action': 'sell',
                'fraction': 1.0,  # 전량 매도
                'reason': reason
            }

        else:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'no_signal'}

    def on_buy(self, price: float):
        """매수 체결 시 호출"""
        self.position = 'long'
        self.entry_price = price

    def on_sell(self):
        """매도 체결 시 호출"""
        self.position = None
        self.entry_price = 0.0


def v01_strategy_wrapper(df, i, params):
    """
    Backtester 호환 래퍼 함수

    Args:
        df: 데이터프레임
        i: 현재 인덱스
        params: {'strategy_instance': AdaptiveRSIMLStrategy 인스턴스}

    Returns:
        {'action': 'buy'|'sell'|'hold', 'fraction': float}
    """
    strategy = params['strategy_instance']
    signal = strategy.generate_signal(df, i)

    # 매수/매도 시 상태 업데이트
    if signal['action'] == 'buy':
        strategy.on_buy(df.iloc[i]['close'])
    elif signal['action'] == 'sell':
        strategy.on_sell()

    return signal
