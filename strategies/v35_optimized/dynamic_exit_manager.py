#!/usr/bin/env python3
"""
Dynamic Exit Manager
시장 상태에 따라 익절/손절 목표를 자동 조정하는 시스템

핵심 기능:
1. 시장 상태별 TP 레벨 자동 조정
2. Trailing Stop (고점 추적 손절)
3. 분할 익절 (TP1 40%, TP2 30%, TP3 30%)
4. Momentum 반전 감지 Exit
"""

from typing import Dict, Optional
import pandas as pd


class DynamicExitManager:
    """동적 익절/손절 관리자"""

    def __init__(self, config: Dict):
        """
        Args:
            config: 하이퍼파라미터 딕셔너리
        """
        self.config = config

        # 시장 상태별 TP 레벨
        self.tp_levels = {
            'BULL_STRONG': [
                config.get('tp_bull_strong_1', 0.05),   # 5%
                config.get('tp_bull_strong_2', 0.10),   # 10%
                config.get('tp_bull_strong_3', 0.20),   # 20%
            ],
            'BULL_MODERATE': [
                config.get('tp_bull_moderate_1', 0.03),  # 3%
                config.get('tp_bull_moderate_2', 0.07),  # 7%
                config.get('tp_bull_moderate_3', 0.12),  # 12%
            ],
            'SIDEWAYS_UP': [
                config.get('tp_sideways_1', 0.02),      # 2%
                config.get('tp_sideways_2', 0.04),      # 4%
                config.get('tp_sideways_3', 0.06),      # 6%
            ],
            'SIDEWAYS_FLAT': [
                config.get('tp_sideways_1', 0.02),
                config.get('tp_sideways_2', 0.04),
                config.get('tp_sideways_3', 0.06),
            ],
            'SIDEWAYS_DOWN': [
                config.get('tp_sideways_1', 0.02),
                config.get('tp_sideways_2', 0.04),
                config.get('tp_sideways_3', 0.06),
            ]
        }

        # Trailing Stop 레벨
        self.trailing_stop = {
            'BULL_STRONG': config.get('trailing_bull_strong', 0.05),    # 고점 대비 -5%
            'BULL_MODERATE': config.get('trailing_bull_moderate', 0.03), # 고점 대비 -3%
            'SIDEWAYS_UP': 0.0,     # Trailing Stop 비활성화
            'SIDEWAYS_FLAT': 0.0,
            'SIDEWAYS_DOWN': 0.0
        }

        # 분할 익절 비율
        self.exit_fractions = [
            config.get('exit_fraction_1', 0.4),  # TP1: 40%
            config.get('exit_fraction_2', 0.3),  # TP2: 30%
            config.get('exit_fraction_3', 0.3),  # TP3: 30%
        ]

        # Stop Loss
        self.stop_loss = config.get('stop_loss', -0.015)  # -1.5%

        # 상태 추적
        self.entry_price = 0
        self.entry_market_state = 'UNKNOWN'
        self.current_position_fraction = 1.0  # 남은 포지션 비율
        self.highest_price_since_entry = 0   # 진입 후 최고가
        self.tp_reached = [False, False, False]  # TP1, TP2, TP3 도달 여부

    def set_entry(self, entry_price: float, market_state: str):
        """포지션 진입 시 초기화"""
        self.entry_price = entry_price
        self.entry_market_state = market_state
        self.current_position_fraction = 1.0
        self.highest_price_since_entry = entry_price
        self.tp_reached = [False, False, False]

    def check_exit(self, current_price: float, current_market_state: str,
                   macd: float = 0, macd_signal: float = 0) -> Optional[Dict]:
        """
        Exit 조건 확인

        Args:
            current_price: 현재 가격
            current_market_state: 현재 시장 상태
            macd: MACD 값
            macd_signal: MACD Signal 값

        Returns:
            Exit 시그널 딕셔너리 or None
        """
        if self.entry_price == 0:
            return None

        # 최고가 업데이트
        if current_price > self.highest_price_since_entry:
            self.highest_price_since_entry = current_price

        # 현재 수익률
        profit = (current_price - self.entry_price) / self.entry_price

        # ===== 1. Stop Loss (최우선) =====
        if profit <= self.stop_loss:
            return {
                'action': 'sell',
                'fraction': 1.0,  # 전량 매도
                'reason': f'STOP_LOSS_{int(abs(self.stop_loss)*100)}%'
            }

        # ===== 2. Market Switch to BEAR (긴급 청산) =====
        if current_market_state in ['BEAR_STRONG', 'BEAR_MODERATE']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MARKET_SWITCH_{current_market_state}'
            }

        # ===== 3. Take Profit (분할 익절) =====
        # 진입 시 시장 상태 기준 TP 레벨 사용
        tp_levels = self.tp_levels.get(self.entry_market_state, self.tp_levels['SIDEWAYS_FLAT'])

        # TP1 체크
        if not self.tp_reached[0] and profit >= tp_levels[0]:
            self.tp_reached[0] = True
            self.current_position_fraction -= self.exit_fractions[0]
            return {
                'action': 'sell',
                'fraction': self.exit_fractions[0],
                'reason': f'TAKE_PROFIT_1_{int(tp_levels[0]*100)}%'
            }

        # TP2 체크
        if self.tp_reached[0] and not self.tp_reached[1] and profit >= tp_levels[1]:
            self.tp_reached[1] = True
            fraction = self.exit_fractions[1] / self.current_position_fraction
            self.current_position_fraction -= self.exit_fractions[1]
            return {
                'action': 'sell',
                'fraction': fraction,
                'reason': f'TAKE_PROFIT_2_{int(tp_levels[1]*100)}%'
            }

        # TP3 체크
        if self.tp_reached[1] and not self.tp_reached[2] and profit >= tp_levels[2]:
            self.tp_reached[2] = True
            return {
                'action': 'sell',
                'fraction': 1.0,  # 남은 전량
                'reason': f'TAKE_PROFIT_3_{int(tp_levels[2]*100)}%'
            }

        # ===== 4. Trailing Stop =====
        trailing_pct = self.trailing_stop.get(self.entry_market_state, 0)
        if trailing_pct > 0 and profit > 0.05:  # 수익 5% 이상일 때만
            drawdown_from_high = (current_price - self.highest_price_since_entry) / self.highest_price_since_entry

            if drawdown_from_high <= -trailing_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TRAILING_STOP_{int(trailing_pct*100)}%'
                }

        # ===== 5. Momentum Reverse (Momentum 전략 한정) =====
        if 'MOMENTUM' in self.entry_market_state.upper():
            if profit > 0.03 and macd < macd_signal:  # 수익 3% 이상 + MACD 데드크로스
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': 'MOMENTUM_REVERSE'
                }

        return None

    def reset(self):
        """포지션 청산 후 리셋"""
        self.entry_price = 0
        self.entry_market_state = 'UNKNOWN'
        self.current_position_fraction = 1.0
        self.highest_price_since_entry = 0
        self.tp_reached = [False, False, False]


if __name__ == '__main__':
    """테스트"""
    import json

    # 테스트 설정
    config = {
        'tp_bull_strong_1': 0.05,
        'tp_bull_strong_2': 0.10,
        'tp_bull_strong_3': 0.20,
        'trailing_bull_strong': 0.05,
        'stop_loss': -0.015,
        'exit_fraction_1': 0.4,
        'exit_fraction_2': 0.3,
        'exit_fraction_3': 0.3
    }

    manager = DynamicExitManager(config)

    print("="*70)
    print("  Dynamic Exit Manager - 테스트")
    print("="*70)

    # 시나리오 1: BULL_STRONG 진입 → TP1, TP2, TP3 순차 익절
    print("\n[시나리오 1: BULL_STRONG 분할 익절]")
    manager.set_entry(entry_price=100_000, market_state='BULL_STRONG')

    prices = [100_000, 103_000, 105_500, 110_500, 120_500]
    for price in prices:
        signal = manager.check_exit(price, 'BULL_STRONG')
        profit = (price - 100_000) / 100_000 * 100
        if signal:
            print(f"  가격: {price:,}원 (+{profit:.1f}%) → {signal['reason']} (매도 {signal['fraction']*100:.0f}%)")
        else:
            print(f"  가격: {price:,}원 (+{profit:.1f}%) → HOLD")

    # 시나리오 2: Trailing Stop
    print("\n[시나리오 2: Trailing Stop]")
    manager.reset()
    manager.set_entry(entry_price=100_000, market_state='BULL_STRONG')

    prices = [100_000, 107_000, 110_000, 112_000, 106_000]
    for price in prices:
        signal = manager.check_exit(price, 'BULL_STRONG')
        profit = (price - 100_000) / 100_000 * 100
        if signal:
            print(f"  가격: {price:,}원 (+{profit:.1f}%) → {signal['reason']}")
            break
        else:
            print(f"  가격: {price:,}원 (+{profit:.1f}%) → HOLD (최고가: {manager.highest_price_since_entry:,}원)")

    # 시나리오 3: Stop Loss
    print("\n[시나리오 3: Stop Loss]")
    manager.reset()
    manager.set_entry(entry_price=100_000, market_state='BULL_MODERATE')

    prices = [100_000, 99_000, 98_000, 98_300]
    for price in prices:
        signal = manager.check_exit(price, 'BULL_MODERATE')
        profit = (price - 100_000) / 100_000 * 100
        if signal:
            print(f"  가격: {price:,}원 ({profit:+.1f}%) → {signal['reason']}")
            break
        else:
            print(f"  가격: {price:,}원 ({profit:+.1f}%) → HOLD")

    print("\n테스트 완료!")
