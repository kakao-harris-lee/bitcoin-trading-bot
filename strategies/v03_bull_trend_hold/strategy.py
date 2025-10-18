#!/usr/bin/env python3
"""
strategy.py
v03 전략: Bull Trend Hold + Adaptive RSI + ML

핵심 개선:
1. 상승장 감지 시 보유 전략 (15% 익절 목표)
2. 최대 보유 기간 관리 (7일 → 수익 시 14일 연장)
3. 하락장에서는 빠른 청산 (기존 로직 유지)
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict

from strategies.v01_adaptive_rsi_ml.adaptive_threshold import AdaptiveThreshold
from strategies.v01_adaptive_rsi_ml.market_classifier import MarketClassifier
from strategies.v01_adaptive_rsi_ml.ml_model import MLSignalValidator

from trend_detector import TrendDetector
from holding_manager import HoldingManager


class BullTrendHoldStrategy:
    """v03: 상승장 보유 + 적응형 RSI + ML 전략"""

    def __init__(self, config: dict, ml_model: MLSignalValidator):
        """
        Args:
            config: config.json 내용
            ml_model: 학습된 ML 모델
        """
        self.config = config

        # 1. 시장 분류기 (v01)
        self.market_classifier = MarketClassifier(
            window=config['rolling_window'],
            adx_period=config['adx_period'],
            adx_threshold=config['adx_threshold']
        )

        # 2. 적응형 임계값 (v01)
        self.adaptive_threshold = AdaptiveThreshold(
            window=config['rolling_window'],
            base_oversold=config['adaptive_rsi']['base_oversold'],
            base_overbought=config['adaptive_rsi']['base_overbought'],
            adjustment_range=config['adaptive_rsi']['adjustment_range'],
            volatility_threshold_high=config['volatility_threshold']['high'],
            volatility_threshold_low=config['volatility_threshold']['low']
        )

        # 3. ML 검증기 (v01)
        self.ml_validator = ml_model

        # 4. 추세 감지기 (v03 신규)
        self.trend_detector = TrendDetector(
            adx_threshold=config['trend_detection']['adx_threshold'],
            recent_period=config['trend_detection']['recent_period'],
            trend_threshold=config['trend_detection']['trend_threshold']
        )

        # 5. 보유 기간 관리자 (v03 신규)
        max_candles, extended_candles = HoldingManager.get_recommended_max_candles(
            config['timeframe']
        )
        self.holding_manager = HoldingManager(
            timeframe=config['timeframe'],
            max_holding_candles=max_candles,
            extended_candles=extended_candles
        )

        # 상태 추적
        self.position = None  # None | 'long'
        self.entry_price = 0.0
        self.kelly_fraction = config['kelly_fraction']

    def generate_signal(self, df: pd.DataFrame, i: int) -> Dict:
        """
        매 캔들마다 호출되는 신호 생성 함수

        Returns:
            {
                'action': 'buy' | 'sell' | 'hold',
                'fraction': float (0~1),
                'reason': str
            }
        """
        # 최소 데이터 확보
        if i < self.config['rolling_window']:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        # === 추세 감지 ===
        trend_info = self.trend_detector.detect_trend(df, i)
        is_bull = (trend_info['trend'] == 'bull')
        is_bear = (trend_info['trend'] == 'bear')

        # === RSI 임계값 ===
        thresholds = self.adaptive_threshold.calculate_thresholds(df, i)
        rsi = df.iloc[i]['rsi']

        # === 포지션 없을 때: 매수 신호 ===
        if self.position is None:
            # RSI 과매도 + ML 승인
            if rsi < thresholds['oversold']:
                raw_signal = 'buy'
                reason = f"RSI({rsi:.1f}) < oversold({thresholds['oversold']:.1f})"

                # ML 검증
                ml_result = self.ml_validator.predict(df, i)
                if not ml_result['approved']:
                    return {
                        'action': 'hold',
                        'fraction': 0.0,
                        'reason': f"ML rejected buy (confidence={ml_result['confidence']:.2%})"
                    }

                reason += f" [ML: {ml_result['confidence']:.2%}]"

                return {
                    'action': 'buy',
                    'fraction': self.kelly_fraction,
                    'reason': reason
                }

        # === 포지션 있을 때: 매도 신호 ===
        elif self.position == 'long':
            current_price = df.iloc[i]['close']
            pnl_ratio = (current_price - self.entry_price) / self.entry_price

            # 1. 최대 보유 기간 체크 (v03 핵심)
            holding_check = self.holding_manager.should_force_exit(
                i, current_price,
                profit_threshold=self.config['bull_hold']['extension_profit']
            )

            if holding_check['should_exit']:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f"max_holding ({holding_check['reason']}, "
                              f"{holding_check['holding_period']} candles, {pnl_ratio:.2%})"
                }

            # 2. 상승장 보유 전략 (v03 핵심)
            if is_bull:
                # 상승장에서는 15% 익절 목표
                bull_tp = self.config['bull_hold']['take_profit']
                if pnl_ratio >= bull_tp:
                    return {
                        'action': 'sell',
                        'fraction': 1.0,
                        'reason': f"bull_take_profit ({pnl_ratio:.2%}, target={bull_tp:.1%})"
                    }

                # 상승장 손절 (-5%)
                bull_sl = self.config['bull_hold']['stop_loss']
                if pnl_ratio <= bull_sl:
                    return {
                        'action': 'sell',
                        'fraction': 1.0,
                        'reason': f"bull_stop_loss ({pnl_ratio:.2%})"
                    }

                # 상승장 중에는 보유 유지
                return {'action': 'hold', 'fraction': 0.0, 'reason': f'bull_holding ({pnl_ratio:.2%})'}

            # 3. 일반 익절/손절 (하락장 또는 횡보장)
            # 익절 1차 (5%)
            if pnl_ratio >= self.config['risk_management']['take_profit_1']:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f"take_profit_1 ({pnl_ratio:.2%})"
                }

            # 손절 (-3%)
            if pnl_ratio <= self.config['risk_management']['stop_loss']:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f"stop_loss ({pnl_ratio:.2%})"
                }

            # RSI 과매수 (70 이상)
            if rsi > thresholds['overbought']:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f"RSI overbought ({rsi:.1f})"
                }

        # 홀드
        return {'action': 'hold', 'fraction': 0.0, 'reason': 'no_signal'}

    def on_buy(self, idx: int, price: float):
        """매수 체결 시 호출"""
        self.position = 'long'
        self.entry_price = price
        self.holding_manager.on_entry(idx, price)

    def on_sell(self):
        """매도 체결 시 호출"""
        self.position = None
        self.entry_price = 0.0
        self.holding_manager.on_exit()


def v03_strategy_wrapper(df, i, params):
    """
    Backtester 호환 래퍼 함수

    Args:
        df: 데이터프레임
        i: 현재 인덱스
        params: {'strategy_instance': BullTrendHoldStrategy 인스턴스}

    Returns:
        {'action': 'buy'|'sell'|'hold', 'fraction': float}
    """
    strategy = params['strategy_instance']
    signal = strategy.generate_signal(df, i)

    # 매수/매도 시 상태 업데이트
    if signal['action'] == 'buy':
        strategy.on_buy(i, df.iloc[i]['close'])
    elif signal['action'] == 'sell':
        strategy.on_sell()

    return signal
