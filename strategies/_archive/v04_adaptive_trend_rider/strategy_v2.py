#!/usr/bin/env python3
"""
strategy_v2.py
v04 전략: Adaptive Hybrid Strategy (범용 적응형)

핵심 철학: "시장이 무엇을 하든 대응한다"
- 동적 시장 분석 (실시간 추세/변동성/모멘텀)
- 혼합 진입 신호 (추세 추종 OR 역추세 반등)
- 적응형 청산 (시장 상태별 규칙 자동 조정)
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, Optional

from dynamic_market_analyzer import DynamicMarketAnalyzer
from hybrid_signal_generator import HybridSignalGenerator
from exit_manager_v2 import ExitManagerV2


class AdaptiveHybridStrategy:
    """v04: 적응형 혼합 전략 (범용)"""

    def __init__(self, config: dict):
        """
        Args:
            config: config.json 내용
        """
        self.config = config

        # === 모듈 초기화 ===

        # 1. 동적 시장 분석기
        self.market_analyzer = DynamicMarketAnalyzer()

        # 2. 혼합 신호 생성기
        signal_cfg = config['signals']
        self.signal_generator = HybridSignalGenerator(
            trend_min_strength=signal_cfg['trend_min_strength'],
            trend_rsi_max=signal_cfg['trend_rsi_max'],
            reversion_rsi_min=signal_cfg['reversion_rsi_min'],
            reversion_drop_min=signal_cfg['reversion_drop_min'],
            reversion_lookback=signal_cfg['reversion_lookback']
        )

        # 3. 청산 관리자
        self.exit_manager = ExitManagerV2()

        # === 상태 추적 ===
        self.position = None  # None | 'long'

    def generate_signal(
        self,
        df: pd.DataFrame,
        i: int,
        current_capital: float
    ) -> Dict:
        """
        매 캔들마다 호출되는 신호 생성 함수

        Args:
            df: 거래 타임프레임 데이터 (지표 포함)
            i: 현재 인덱스
            current_capital: 현재 자본

        Returns:
            {
                'action': 'buy' | 'sell' | 'hold',
                'fraction': float (0~1),
                'reason': str
            }
        """
        # === 최소 데이터 확보 ===
        if i < 50:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        # === 1. 시장 상태 동적 분석 ===
        market_state = self.market_analyzer.analyze(df, i)

        # 디버깅용 설명
        market_desc = self.market_analyzer.get_description(market_state)

        # === 포지션 없을 때: 매수 신호 ===
        if self.position is None:
            # 2. 진입 신호 생성 (Track A OR Track B)
            entry_signal = self.signal_generator.generate_entry_signal(
                df, i, market_state
            )

            if entry_signal['should_buy']:
                # 3. 포지션 사이징 (변동성 기반)
                fraction = self._calculate_position_size(
                    market_state,
                    current_capital
                )

                return {
                    'action': 'buy',
                    'fraction': fraction,
                    'reason': f"{market_desc} | {entry_signal['reason']}",
                    'entry_track': entry_signal['track']
                }

        # === 포지션 있을 때: 매도 신호 ===
        elif self.position == 'long':
            # 4. 신호 기반 매도 체크
            signal_exit = self.signal_generator.generate_exit_signal(
                df, i, market_state
            )

            # 5. 적응형 청산 규칙 체크
            exit_decision = self.exit_manager.check_exit(
                df, i, market_state, signal_exit
            )

            if exit_decision['should_exit']:
                return {
                    'action': 'sell',
                    'fraction': exit_decision['fraction'],
                    'reason': f"{market_desc} | {exit_decision['reason']}"
                }

        # 홀드
        return {
            'action': 'hold',
            'fraction': 0.0,
            'reason': f'{market_desc} | holding' if self.position else f'{market_desc} | no_signal'
        }

    def _calculate_position_size(
        self,
        market_state: Dict,
        current_capital: float
    ) -> float:
        """
        변동성 기반 포지션 사이징

        Args:
            market_state: 시장 상태
            current_capital: 현재 자본

        Returns:
            fraction: 투자 비율 (0~1)
        """
        vol_level = market_state['volatility']['level']
        trend_strength = market_state['trend']['strength']

        # 기본 비율 (변동성 기반)
        if vol_level == 'low':
            base_fraction = 0.40
        elif vol_level == 'medium':
            base_fraction = 0.25
        else:  # high
            base_fraction = 0.15

        # 추세 강도 보너스 (강한 추세 시 증액)
        if trend_strength >= 30:
            base_fraction *= 1.2
        elif trend_strength >= 20:
            base_fraction *= 1.1

        # 최대 50% 제한
        return min(base_fraction, 0.5)

    def on_buy(
        self,
        idx: int,
        price: float,
        entry_track: str
    ):
        """매수 체결 시 호출"""
        self.position = 'long'
        self.exit_manager.on_entry(idx, price, entry_track)

    def on_sell(self):
        """매도 체결 시 호출"""
        self.position = None
        self.exit_manager.on_exit()


def v04_strategy_wrapper(df, i, params):
    """
    Backtester 호환 래퍼 함수

    Args:
        df: 거래 타임프레임 데이터
        i: 현재 인덱스
        params: {
            'strategy_instance': AdaptiveHybridStrategy 인스턴스,
            'backtester': Backtester 인스턴스
        }

    Returns:
        {'action': 'buy'|'sell'|'hold', 'fraction': float}
    """
    strategy = params['strategy_instance']
    backtester = params['backtester']

    # 현재 자본 = 현금 + 포지션 가치
    current_capital = backtester.cash + backtester.position_value

    signal = strategy.generate_signal(df, i, current_capital)

    # 매수/매도 시 상태 업데이트
    if signal['action'] == 'buy':
        entry_track = signal.get('entry_track', 'unknown')
        strategy.on_buy(i, df.iloc[i]['close'], entry_track)

    elif signal['action'] == 'sell':
        strategy.on_sell()

    return signal
