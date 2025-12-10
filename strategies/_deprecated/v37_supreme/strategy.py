#!/usr/bin/env python3
"""
v37 Supreme Strategy - Adaptive Multi-Strategy System

핵심 혁신:
1. 선행 지표 기반 5단계 시장 분류 (MA20 기울기, ADX, 변동성)
2. 시장 상태별 전략 자동 전환
3. 동적 임계값 (quantile 기반)
4. 장기 추세 추종 (BULL_STRONG: 90일 보유)

목표:
  2020-2024: 60-70% 연평균 수익
  2025 검증: Buy&Hold의 70-90% (안정성 우선)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
import sys
sys.path.append('../..')

from strategies.v37_supreme.market_classifier_v37 import MarketClassifierV37
from strategies.v37_supreme.dynamic_thresholds import DynamicThresholds
from strategies.v37_supreme.strategies.trend_following import TrendFollowingStrategy
from strategies.v37_supreme.strategies.swing_trading import SwingTradingStrategy
from strategies.v37_supreme.strategies.sideways_strategy import SidewaysStrategy
from strategies.v37_supreme.strategies.defensive_trading import DefensiveTradingStrategy


class V37SupremeStrategy:
    """
    v37 Supreme: 적응형 Multi-Strategy 시스템

    시장 분류 → 전략 선택 → 실행
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 하이퍼파라미터 설정 딕셔너리
        """
        self.config = config

        # 시장 분류기
        self.classifier = MarketClassifierV37()

        # 동적 임계값 관리자
        self.dynamic_thresholds = DynamicThresholds(config)

        # 전략 모듈 (5개)
        self.trend_following = TrendFollowingStrategy(config)
        self.swing_trading = SwingTradingStrategy(config)
        self.sideways_strategy = SidewaysStrategy(config)
        self.defensive_trading = DefensiveTradingStrategy(config)

        # 전역 상태
        self.current_market_state = 'UNKNOWN'
        self.current_strategy = None  # 현재 활성 전략
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.entry_market_state = 'UNKNOWN'

        # 통계
        self.state_transitions = []
        self.strategy_switches = []

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        Args:
            df: 지표가 포함된 전체 데이터프레임
            i: 현재 인덱스

        Returns:
            {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0, 'reason': str}
        """

        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        # 1. 시장 상태 분류
        current_row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None
        df_recent = df.iloc[max(0, i-60):i+1] if i >= 60 else df.iloc[:i+1]

        market_state = self.classifier.classify_market_state(
            current_row=current_row,
            prev_row=prev_row,
            df_recent=df_recent
        )

        # 시장 상태 변화 기록
        if market_state != self.current_market_state:
            self.state_transitions.append({
                'time': current_row.name,
                'from': self.current_market_state,
                'to': market_state
            })
            self.current_market_state = market_state

        # 2. 동적 임계값 계산
        dynamic_thresholds = self.dynamic_thresholds.get_all_dynamic_thresholds(df_recent, current_row)

        # 3. 시장 상태별 전략 선택
        active_strategy = self._select_strategy(market_state)

        # 전략 전환 기록
        if active_strategy != self.current_strategy:
            self.strategy_switches.append({
                'time': current_row.name,
                'from': self.current_strategy,
                'to': active_strategy,
                'market_state': market_state
            })
            self.current_strategy = active_strategy

        # 4. 전략별 동적 임계값 적용
        self._apply_dynamic_thresholds(active_strategy, dynamic_thresholds)

        # 5. 전략별 시장 상태 동기화
        if active_strategy == 'defensive':
            self.defensive_trading.set_market_state(market_state)

        # 6. 선택된 전략 실행
        signal = self._execute_selected_strategy(df, i, active_strategy, market_state)

        # 5. 포지션 상태 추적
        if signal['action'] == 'buy' and not self.in_position:
            self.in_position = True
            self.entry_price = current_row['close']
            self.entry_time = current_row.name
            self.entry_market_state = market_state
            signal['market_state'] = market_state
            signal['strategy_type'] = active_strategy

        elif signal['action'] == 'sell' and self.in_position:
            self.in_position = False
            self.entry_price = 0
            self.entry_time = None
            self.entry_market_state = 'UNKNOWN'
            signal['market_state'] = market_state
            signal['strategy_type'] = active_strategy

        return signal

    def _apply_dynamic_thresholds(self, active_strategy: str, thresholds: Dict):
        """
        전략별 동적 임계값 적용

        Args:
            active_strategy: 활성 전략명
            thresholds: 동적 임계값 딕셔너리

        주의: BULL 시장에서는 고정 임계값이 더 우수함 (2024년 검증)
              동적 임계값은 SIDEWAYS/BEAR에서만 활성화
        """

        # BULL 시장: 동적 임계값 비활성화 (고정값 유지)
        if active_strategy in ['trend_following', 'swing_trading']:
            pass  # 고정 임계값 사용

        # SIDEWAYS: 동적 임계값 활성화
        elif active_strategy == 'sideways':
            # RSI, Volume 임계값 오버라이드
            self.sideways_strategy.config['rsi_bb_oversold'] = thresholds['rsi_oversold']
            self.sideways_strategy.config['rsi_bb_overbought'] = thresholds['rsi_overbought']
            self.sideways_strategy.config['volume_breakout_mult'] = thresholds['volume_mult']

        # BEAR: 동적 임계값 활성화 (더 보수적)
        elif active_strategy == 'defensive':
            self.defensive_trading.config['defensive_rsi_oversold'] = max(20, thresholds['rsi_oversold'] - 5)

    def _select_strategy(self, market_state: str) -> str:
        """
        시장 상태별 전략 선택

        Returns:
            'trend_following', 'swing_trading', 'sideways', 'defensive'
        """

        if market_state == 'BULL_STRONG':
            return 'trend_following'

        elif market_state == 'BULL_MODERATE':
            return 'swing_trading'

        elif market_state == 'SIDEWAYS':
            return 'sideways'

        elif market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
            return 'defensive'

        else:  # UNKNOWN
            return 'sideways'  # 기본값: 보수적으로 SIDEWAYS 전략

    def _execute_selected_strategy(self, df: pd.DataFrame, i: int,
                                    active_strategy: str, market_state: str) -> Dict:
        """선택된 전략 실행"""

        if active_strategy == 'trend_following':
            signal = self.trend_following.execute(df, i)

        elif active_strategy == 'swing_trading':
            signal = self.swing_trading.execute(df, i)

        elif active_strategy == 'sideways':
            signal = self.sideways_strategy.execute(df, i)

        elif active_strategy == 'defensive':
            signal = self.defensive_trading.execute(df, i)

        else:
            signal = {'action': 'hold', 'reason': f'UNKNOWN_STRATEGY ({active_strategy})'}

        return signal

    def get_state_statistics(self) -> Dict:
        """
        시장 상태 및 전략 전환 통계

        Returns:
            {
                'total_state_transitions': int,
                'total_strategy_switches': int,
                'state_distribution': {...},
                'recent_transitions': [...]
            }
        """

        return {
            'total_state_transitions': len(self.state_transitions),
            'total_strategy_switches': len(self.strategy_switches),
            'current_market_state': self.current_market_state,
            'current_strategy': self.current_strategy,
            'in_position': self.in_position,
            'entry_market_state': self.entry_market_state if self.in_position else None,
            'recent_transitions': self.state_transitions[-10:] if len(self.state_transitions) >= 10 else self.state_transitions,
            'recent_switches': self.strategy_switches[-10:] if len(self.strategy_switches) >= 10 else self.strategy_switches
        }

    def reset(self):
        """상태 초기화 (백테스팅용)"""
        self.current_market_state = 'UNKNOWN'
        self.current_strategy = None
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.entry_market_state = 'UNKNOWN'
        self.state_transitions = []
        self.strategy_switches = []

        # 각 전략 초기화
        self.trend_following = TrendFollowingStrategy(self.config)
        self.swing_trading = SwingTradingStrategy(self.config)
        self.sideways_strategy = SidewaysStrategy(self.config)
        self.defensive_trading = DefensiveTradingStrategy(self.config)


if __name__ == '__main__':
    """테스트"""
    import json
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    print("="*70)
    print("  v37 Supreme Strategy - 통합 테스트")
    print("="*70)

    # 기본 Config (Optuna 최적화 전)
    config = {
        # 추세 추종 (BULL_STRONG)
        'trend_adx_threshold': 25,
        'trend_stop_loss': -0.10,
        'trend_trailing_stop': -0.05,
        'trend_trailing_trigger': 0.20,
        'trend_max_hold_days': 90,

        # 스윙 트레이딩 (BULL_MODERATE)
        'swing_rsi_oversold': 40,
        'swing_tp_1': 0.10,
        'swing_tp_2': 0.15,
        'swing_stop_loss': -0.03,
        'swing_max_hold_days': 40,

        # SIDEWAYS
        'use_rsi_bb': True,
        'use_stoch': True,
        'use_volume_breakout': True,
        'rsi_bb_oversold': 30,
        'rsi_bb_overbought': 70,
        'stoch_oversold': 20,
        'stoch_overbought': 80,
        'volume_breakout_mult': 2.0,
        'sideways_position_size': 0.4,
        'sideways_tp_1': 0.02,
        'sideways_tp_2': 0.04,
        'sideways_tp_3': 0.06,
        'sideways_stop_loss': -0.02,
        'sideways_max_hold_days': 20,

        # Defensive (BEAR)
        'defensive_rsi_oversold': 25,
        'defensive_position_size': 0.2,
        'defensive_bear_strong_size': 0.1,
        'defensive_take_profit_1': 0.05,
        'defensive_take_profit_2': 0.10,
        'defensive_stop_loss': -0.05,
        'defensive_tp_bear_strong': 0.03,
        'defensive_max_hold_days': 20
    }

    # 2024 데이터로 테스트 (다양한 시장 상태 포함)
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'adx', 'atr', 'bb', 'stoch', 'mfi'])

    # 전략 테스트
    strategy = V37SupremeStrategy(config)
    signals = []
    market_states = []

    for i in range(30, min(200, len(df))):
        signal = strategy.execute(df, i)

        if signal['action'] != 'hold':
            signals.append({
                'date': df.iloc[i].name,
                'action': signal['action'],
                'reason': signal['reason'],
                'price': df.iloc[i]['close'],
                'market_state': signal.get('market_state', 'UNKNOWN'),
                'strategy': signal.get('strategy_type', 'unknown')
            })

        market_states.append({
            'date': df.iloc[i].name,
            'state': strategy.current_market_state,
            'strategy': strategy.current_strategy
        })

    print(f"\n[시그널 발생: {len(signals)}개]")
    for sig in signals[:15]:
        print(f"  {sig['date']} | {sig['action']:4s} | {sig['market_state']:15s} | "
              f"{sig['strategy']:15s} | {sig['reason']:40s} | {sig['price']:,.0f}원")

    # 통계
    stats = strategy.get_state_statistics()
    print(f"\n[통계]")
    print(f"  시장 상태 전환: {stats['total_state_transitions']}회")
    print(f"  전략 전환: {stats['total_strategy_switches']}회")
    print(f"  현재 시장: {stats['current_market_state']}")
    print(f"  현재 전략: {stats['current_strategy']}")

    print(f"\n[최근 시장 상태 전환]")
    for trans in stats['recent_transitions'][-5:]:
        print(f"  {trans['time']} | {trans['from']:15s} → {trans['to']:15s}")

    print(f"\n[최근 전략 전환]")
    for switch in stats['recent_switches'][-5:]:
        print(f"  {switch['time']} | {switch['from']:15s} → {switch['to']:15s} (시장: {switch['market_state']})")

    print(f"\n테스트 완료!")
    print(f"v37 Supreme Strategy 통합 완료 ✅")
    print(f"\n다음 단계:")
    print(f"  1. 동적 임계값 시스템 (Phase 3)")
    print(f"  2. 멀티 타임프레임 통합 (Phase 4)")
    print(f"  3. Optuna 최적화 (Phase 5)")
    print(f"  4. 2025 검증 (Phase 6)")
