#!/usr/bin/env python3
"""
Ensemble Manager
Multi-Timeframe 전략 통합 관리자

역할:
1. Day, Minute240, Minute60 3개 전략의 시그널 통합
2. 포지션 충돌 관리
3. 자본 배분 관리
4. Day 필터 전파
"""

from typing import Dict, List, Optional
import pandas as pd
import numpy as np


class EnsembleManager:
    """Multi-Timeframe 전략 통합 관리자"""

    def __init__(self, config: Dict):
        """
        Args:
            config: 통합 설정
        """
        self.config = config

        # 자본 배분
        self.capital_allocation = {
            'day': config.get('day_capital', 0.4),       # 40%
            'minute240': config.get('m240_capital', 0.3), # 30%
            'minute60': config.get('m60_capital', 0.3)    # 30%
        }

        # 포지션 상태
        self.positions = {
            'day': {'in_position': False, 'entry_price': 0, 'shares': 0},
            'minute240': {'in_position': False, 'entry_price': 0, 'shares': 0},
            'minute60': {'in_position': False, 'entry_price': 0, 'shares': 0}
        }

        # Day 시장 상태 (필터로 사용)
        self.day_market_state = 'UNKNOWN'

    def set_day_market_state(self, state: str):
        """Day 시장 상태 업데이트"""
        self.day_market_state = state

    def get_day_market_state(self) -> str:
        """현재 Day 시장 상태 반환"""
        return self.day_market_state

    def process_signals(self, day_signal: Dict, m240_signal: Dict, m60_signal: Dict) -> List[Dict]:
        """
        3개 타임프레임 시그널 통합 처리

        Args:
            day_signal: Day 시그널
            m240_signal: Minute240 시그널
            m60_signal: Minute60 시그널

        Returns:
            실행할 시그널 리스트 (우선순위 순)
        """
        actions = []

        # ===== 우선순위 1: BEAR 시그널 (즉시 청산) =====
        if self.day_market_state in ['BEAR_STRONG', 'BEAR_MODERATE']:
            # 모든 타임프레임 포지션 청산
            for tf in ['day', 'minute240', 'minute60']:
                if self.positions[tf]['in_position']:
                    actions.append({
                        'timeframe': tf,
                        'action': 'sell',
                        'fraction': 1.0,
                        'reason': f'ENSEMBLE_BEAR_FORCE_EXIT',
                        'priority': 1
                    })

        # ===== 우선순위 2: Day Exit =====
        if day_signal['action'] == 'sell':
            actions.append({
                'timeframe': 'day',
                'action': 'sell',
                'fraction': day_signal.get('fraction', 1.0),
                'reason': day_signal.get('reason', 'DAY_EXIT'),
                'priority': 2
            })

        # ===== 우선순위 3: Minute240 Exit =====
        if m240_signal['action'] == 'sell':
            actions.append({
                'timeframe': 'minute240',
                'action': 'sell',
                'fraction': m240_signal.get('fraction', 1.0),
                'reason': m240_signal.get('reason', 'M240_EXIT'),
                'priority': 3
            })

        # ===== 우선순위 4: Minute60 Exit =====
        if m60_signal['action'] == 'sell':
            actions.append({
                'timeframe': 'minute60',
                'action': 'sell',
                'fraction': m60_signal.get('fraction', 1.0),
                'reason': m60_signal.get('reason', 'M60_EXIT'),
                'priority': 4
            })

        # ===== 우선순위 5: Day Entry =====
        if day_signal['action'] == 'buy' and not self.positions['day']['in_position']:
            # Day는 항상 진입 가능
            actions.append({
                'timeframe': 'day',
                'action': 'buy',
                'fraction': day_signal.get('fraction', 0.5),
                'capital_fraction': self.capital_allocation['day'],
                'reason': day_signal.get('reason', 'DAY_ENTRY'),
                'priority': 5
            })

        # ===== 우선순위 6: Minute240 Entry =====
        if m240_signal['action'] == 'buy' and not self.positions['minute240']['in_position']:
            # Day 필터 확인
            if self.day_market_state in ['BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS_UP']:
                actions.append({
                    'timeframe': 'minute240',
                    'action': 'buy',
                    'fraction': m240_signal.get('fraction', 0.3),
                    'capital_fraction': self.capital_allocation['minute240'],
                    'reason': m240_signal.get('reason', 'M240_ENTRY'),
                    'priority': 6
                })

        # ===== 우선순위 7: Minute60 Entry =====
        if m60_signal['action'] == 'buy' and not self.positions['minute60']['in_position']:
            # Day 필터 확인 (BEAR만 제외)
            if self.day_market_state not in ['BEAR_STRONG', 'BEAR_MODERATE']:
                actions.append({
                    'timeframe': 'minute60',
                    'action': 'buy',
                    'fraction': m60_signal.get('fraction', 0.3),
                    'capital_fraction': self.capital_allocation['minute60'],
                    'reason': m60_signal.get('reason', 'M60_ENTRY'),
                    'priority': 7
                })

        # 우선순위 순으로 정렬
        actions.sort(key=lambda x: x['priority'])

        return actions

    def update_position(self, timeframe: str, action: str, entry_price: float = 0, shares: float = 0):
        """포지션 상태 업데이트"""
        if action == 'buy':
            self.positions[timeframe]['in_position'] = True
            self.positions[timeframe]['entry_price'] = entry_price
            self.positions[timeframe]['shares'] = shares
        elif action == 'sell':
            self.positions[timeframe]['in_position'] = False
            self.positions[timeframe]['entry_price'] = 0
            self.positions[timeframe]['shares'] = 0

    def get_current_leverage(self) -> float:
        """현재 레버리지 계산"""
        total_allocation = 0
        for tf, pos in self.positions.items():
            if pos['in_position']:
                total_allocation += self.capital_allocation[tf]
        return total_allocation

    def can_enter(self, timeframe: str) -> bool:
        """진입 가능 여부 확인"""
        # 이미 포지션 있으면 불가
        if self.positions[timeframe]['in_position']:
            return False

        # 최대 레버리지 확인 (100%)
        new_leverage = self.get_current_leverage() + self.capital_allocation[timeframe]
        if new_leverage > 1.0:
            return False

        return True

    def get_position_summary(self) -> Dict:
        """현재 포지션 요약"""
        return {
            'day': {
                'in_position': self.positions['day']['in_position'],
                'entry_price': self.positions['day']['entry_price']
            },
            'minute240': {
                'in_position': self.positions['minute240']['in_position'],
                'entry_price': self.positions['minute240']['entry_price']
            },
            'minute60': {
                'in_position': self.positions['minute60']['in_position'],
                'entry_price': self.positions['minute60']['entry_price']
            },
            'leverage': self.get_current_leverage(),
            'day_state': self.day_market_state
        }


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  Ensemble Manager - 테스트")
    print("="*70)

    config = {
        'day_capital': 0.4,
        'm240_capital': 0.3,
        'm60_capital': 0.3
    }

    manager = EnsembleManager(config)

    # 시나리오 1: Day BULL_STRONG 상태
    print("\n[시나리오 1: Day BULL_STRONG, 모두 매수 시그널]")
    manager.set_day_market_state('BULL_STRONG')

    day_signal = {'action': 'buy', 'fraction': 0.5, 'reason': 'DAY_MOMENTUM'}
    m240_signal = {'action': 'buy', 'fraction': 0.3, 'reason': 'M240_SWING'}
    m60_signal = {'action': 'buy', 'fraction': 0.3, 'reason': 'M60_SCALP'}

    actions = manager.process_signals(day_signal, m240_signal, m60_signal)

    print(f"  실행할 시그널: {len(actions)}개")
    for act in actions:
        print(f"    {act['priority']}. {act['timeframe']:10s} | {act['action']:4s} | {act['reason']}")

    # 포지션 업데이트 시뮬레이션
    for act in actions:
        if act['action'] == 'buy':
            manager.update_position(act['timeframe'], 'buy', entry_price=100000, shares=10)

    print(f"\n  레버리지: {manager.get_current_leverage()*100:.0f}%")

    # 시나리오 2: Day BEAR 전환
    print("\n[시나리오 2: Day BEAR 전환]")
    manager.set_day_market_state('BEAR_STRONG')

    day_signal = {'action': 'hold'}
    m240_signal = {'action': 'hold'}
    m60_signal = {'action': 'hold'}

    actions = manager.process_signals(day_signal, m240_signal, m60_signal)

    print(f"  실행할 시그널: {len(actions)}개 (모두 청산)")
    for act in actions:
        print(f"    {act['priority']}. {act['timeframe']:10s} | {act['action']:4s} | {act['reason']}")

    print(f"\n테스트 완료!")
