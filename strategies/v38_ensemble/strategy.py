#!/usr/bin/env python3
"""
v38 Ensemble Strategy

v35 (SIDEWAYS 특화) + v37 (BULL 특화) 앙상블
시장 상태별 최적 전략 자동 선택
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
import sys
sys.path.append('../..')

from strategies.v38_ensemble.market_meta_classifier import MarketMetaClassifier
from strategies.v37_supreme.strategies.trend_following import TrendFollowingStrategy
from strategies.v37_supreme.strategies.swing_trading import SwingTradingStrategy
from strategies.v37_supreme.strategies.defensive_trading import DefensiveTradingStrategy
from strategies.v35_optimized.sideways_enhanced import SidewaysEnhancedStrategies
from strategies.v35_optimized.dynamic_exit_manager import DynamicExitManager


class V38EnsembleStrategy:
    """
    v38 Ensemble: 시장 상태별 최적 전략 라우터

    시장 분류 → 전략 선택 → 실행
    - BULL_STRONG → v37 Trend Following (장기 보유)
    - BULL_MODERATE → v37 Swing Trading (단기 스윙)
    - SIDEWAYS → v35 SIDEWAYS Strategies
    - BEAR → v37 Defensive Trading
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 전체 설정 (v35 + v37 파라미터)
        """
        self.config = config

        # Meta 분류기
        self.meta_classifier = MarketMetaClassifier(config.get('meta_classifier'))

        # v37 전략들
        v37_config = config.get('v37_strategies', {})
        self.trend_following = TrendFollowingStrategy(v37_config)
        self.swing_trading = SwingTradingStrategy(v37_config)
        self.defensive_trading = DefensiveTradingStrategy(v37_config)

        # v35 전략들
        v35_config = config.get('v35_strategies', {})
        self.sideways_strategies = SidewaysEnhancedStrategies(v35_config)
        self.v35_exit_manager = DynamicExitManager(v35_config)

        # 포지션 상태
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.entry_market_state = 'UNKNOWN'
        self.active_strategy = None  # 'v37_trend', 'v37_swing', 'v35_sideways', 'v37_defensive'

        # 통계
        self.strategy_usage_count = {
            'v37_trend': 0,
            'v37_swing': 0,
            'v35_sideways': 0,
            'v37_defensive': 0
        }
        self.market_state_history = []

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        Args:
            df: 지표가 포함된 전체 데이터프레임
            i: 현재 인덱스

        Returns:
            {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0, 'reason': str}
        """
        if i < 60:  # MA20 계산 및 warm-up
            return {'action': 'hold', 'reason': 'WARMUP'}

        current_row = df.iloc[i]
        df_recent = df.iloc[max(0, i-60):i+1]

        # 1. 시장 상태 분류
        market_state = self.meta_classifier.classify_market_state(current_row, df_recent)
        self.market_state_history.append({
            'time': current_row.name,
            'state': market_state
        })

        # 2. 포지션이 있을 때: Exit 처리
        if self.in_position:
            exit_signal = self._check_exit(df, i, market_state)
            if exit_signal and exit_signal['action'] == 'sell':
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.entry_market_state = 'UNKNOWN'
                self.active_strategy = None
                # v35 Exit Manager 리셋
                self.v35_exit_manager.reset()
                return exit_signal

        # 3. 포지션이 없을 때: Entry 처리
        else:
            entry_signal = self._check_entry(df, i, market_state)
            if entry_signal and entry_signal['action'] == 'buy':
                self.in_position = True
                self.entry_price = current_row['close']
                self.entry_time = current_row.name
                self.entry_market_state = market_state

                # v35 전략 사용 시 Exit Manager 초기화
                if self.active_strategy == 'v35_sideways':
                    self.v35_exit_manager.set_entry(self.entry_price, market_state)

                return entry_signal

        return {'action': 'hold', 'reason': f'NO_SIGNAL_{market_state}'}

    def _check_entry(self, df: pd.DataFrame, i: int, market_state: str) -> Optional[Dict]:
        """
        시장 상태별 Entry 전략 선택 및 실행

        Args:
            df: 전체 데이터
            i: 현재 인덱스
            market_state: 시장 상태

        Returns:
            Entry 신호 또는 None
        """
        current_row = df.iloc[i]

        # BULL_STRONG → v37 Trend Following
        if market_state == 'BULL_STRONG':
            signal = self.trend_following.execute(df, i)
            if signal and signal.get('action') == 'buy':
                self.active_strategy = 'v37_trend'
                self.strategy_usage_count['v37_trend'] += 1
                signal['strategy'] = 'v37_trend'
                signal['market_state'] = market_state
                return signal

        # BULL_MODERATE → v37 Swing Trading
        elif market_state == 'BULL_MODERATE':
            signal = self.swing_trading.execute(df, i)
            if signal and signal.get('action') == 'buy':
                self.active_strategy = 'v37_swing'
                self.strategy_usage_count['v37_swing'] += 1
                signal['strategy'] = 'v37_swing'
                signal['market_state'] = market_state
                return signal

        # SIDEWAYS → v35 SIDEWAYS Strategies
        elif market_state == 'SIDEWAYS':
            current_row = df.iloc[i]
            prev_row = df.iloc[i-1] if i > 0 else None
            signal = self.sideways_strategies.check_all_entries(current_row, prev_row, df, i)
            if signal and signal.get('action') == 'buy':
                self.active_strategy = 'v35_sideways'
                self.strategy_usage_count['v35_sideways'] += 1
                signal['strategy'] = 'v35_sideways'
                signal['market_state'] = market_state
                return signal

        # BEAR → v37 Defensive Trading
        else:  # BEAR
            signal = self.defensive_trading.execute(df, i)
            if signal and signal.get('action') == 'buy':
                self.active_strategy = 'v37_defensive'
                self.strategy_usage_count['v37_defensive'] += 1
                signal['strategy'] = 'v37_defensive'
                signal['market_state'] = market_state
                return signal

        return None

    def _check_exit(self, df: pd.DataFrame, i: int, market_state: str) -> Optional[Dict]:
        """
        활성 전략별 Exit 처리

        Args:
            df: 전체 데이터
            i: 현재 인덱스
            market_state: 현재 시장 상태

        Returns:
            Exit 신호 또는 None
        """
        current_row = df.iloc[i]

        # 포지션 정보 구성
        position_info = {
            'entry_price': self.entry_price,
            'entry_time': self.entry_time,
            'entry_market_state': self.entry_market_state
        }

        # v37 전략 Exit (내부적으로 포지션 관리)
        if self.active_strategy in ['v37_trend', 'v37_swing', 'v37_defensive']:
            if self.active_strategy == 'v37_trend':
                signal = self.trend_following.execute(df, i)
            elif self.active_strategy == 'v37_swing':
                signal = self.swing_trading.execute(df, i)
            else:  # v37_defensive
                signal = self.defensive_trading.execute(df, i)

            if signal and signal.get('action') == 'sell':
                signal['strategy'] = self.active_strategy
                return signal

        # v35 SIDEWAYS Exit (Dynamic Exit Manager 사용)
        elif self.active_strategy == 'v35_sideways':
            signal = self.v35_exit_manager.check_exit(
                current_price=current_row['close'],
                current_market_state=market_state,
                macd=current_row.get('macd', 0),
                macd_signal=current_row.get('macd_signal', 0)
            )
            if signal and signal.get('action') == 'sell':
                signal['strategy'] = 'v35_sideways'
                return signal

        return None

    def get_strategy_stats(self) -> Dict:
        """
        전략 사용 통계

        Returns:
            {
                'v37_trend': N회,
                'v37_swing': N회,
                'v35_sideways': N회,
                'v37_defensive': N회,
                'market_state_distribution': {...}
            }
        """
        # 시장 상태 분포
        from collections import Counter
        state_counts = Counter([h['state'] for h in self.market_state_history])

        total_states = len(self.market_state_history)
        state_distribution = {
            state: count / total_states * 100
            for state, count in state_counts.items()
        } if total_states > 0 else {}

        return {
            'strategy_usage': self.strategy_usage_count,
            'market_state_distribution': state_distribution
        }


if __name__ == '__main__':
    print("v38 Ensemble Strategy")
    print("\n전략 라우팅:")
    print("  BULL_STRONG → v37 Trend Following")
    print("  BULL_MODERATE → v37 Swing Trading")
    print("  SIDEWAYS → v35 SIDEWAYS Strategies")
    print("  BEAR → v37 Defensive Trading")
    print("\n목표:")
    print("  2024 BULL: 80-90%")
    print("  2025 SIDEWAYS: 12-15%")
    print("  연평균: 40-50%")
