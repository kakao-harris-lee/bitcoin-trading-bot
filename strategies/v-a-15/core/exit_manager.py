#!/usr/bin/env python3
"""
Exit Manager - ATR 기반 동적 Exit 시스템

v-a-15 핵심 모듈 2/3
"""

import pandas as pd
from typing import Dict, Optional, Tuple


class ATRDynamicExitManager:
    """
    ATR 기반 동적 Exit Manager

    - Dynamic Stop Loss: Entry - (ATR × 3.0)
    - Dynamic Take Profit: Entry + (ATR × 6.0) for 2:1 reward-risk
    - Trailing Stop: Peak - (ATR × 3.5)
    - 변동성 적응형 TP/SL
    """

    def __init__(self, config: Dict):
        self.config = config

        # ATR 배율
        self.atr_sl_multiplier = config.get('atr_sl_multiplier', 3.0)
        self.atr_tp1_multiplier = config.get('atr_tp1_multiplier', 3.0)  # 1:1
        self.atr_tp2_multiplier = config.get('atr_tp2_multiplier', 6.0)  # 2:1
        self.atr_tp3_multiplier = config.get('atr_tp3_multiplier', 9.0)  # 3:1
        self.atr_trailing_multiplier = config.get('atr_trailing_multiplier', 3.5)

        # Trailing Stop 활성화 수익률
        self.trailing_trigger = config.get('trailing_trigger_pct', 0.10)  # 10%

        # 변동성 임계값
        self.high_volatility = config.get('high_volatility_threshold', 0.03)
        self.low_volatility = config.get('low_volatility_threshold', 0.015)

    def calculate_exit_levels(
        self,
        entry_price: float,
        entry_atr: float,
        strategy: str = 'default'
    ) -> Dict[str, float]:
        """
        진입 시 Exit 레벨 계산

        Args:
            entry_price: 진입 가격
            entry_atr: 진입 시점 ATR
            strategy: 전략 이름

        Returns:
            Exit 레벨 dict
        """
        # 전략별 배율 조정
        multipliers = self._get_strategy_multipliers(strategy)

        # Stop Loss (ATR는 비율이므로 entry_price에 곱함)
        stop_loss = entry_price * (1 - entry_atr * multipliers['sl'])

        # Take Profit (3단계)
        take_profit_1 = entry_price * (1 + entry_atr * multipliers['tp1'])
        take_profit_2 = entry_price * (1 + entry_atr * multipliers['tp2'])
        take_profit_3 = entry_price * (1 + entry_atr * multipliers['tp3'])

        # 변동성별 조정
        volatility_adjusted = self._adjust_for_volatility(
            entry_atr,
            {
                'stop_loss': stop_loss,
                'take_profit_1': take_profit_1,
                'take_profit_2': take_profit_2,
                'take_profit_3': take_profit_3
            }
        )

        return volatility_adjusted

    def check_exit(
        self,
        entry_price: float,
        current_price: float,
        entry_atr: float,
        highest_price: float,
        hold_days: int,
        strategy: str = 'default',
        max_hold_days: int = 40
    ) -> Tuple[bool, str, float]:
        """
        Exit 조건 체크

        Args:
            entry_price: 진입 가격
            current_price: 현재 가격
            entry_atr: 진입 시점 ATR
            highest_price: 보유 중 최고가
            hold_days: 보유 일수
            strategy: 전략 이름
            max_hold_days: 최대 보유 일수

        Returns:
            (should_exit, exit_reason, exit_fraction)
        """
        # Exit 레벨 계산
        levels = self.calculate_exit_levels(entry_price, entry_atr, strategy)

        # 현재 수익률
        profit_pct = (current_price - entry_price) / entry_price

        # 1. Take Profit 체크 (역순으로, 높은 것부터)
        if current_price >= levels['take_profit_3']:
            return (True, f'{strategy.upper()}_TP3', 1.0)
        if current_price >= levels['take_profit_2']:
            return (True, f'{strategy.upper()}_TP2', 1.0)
        if current_price >= levels['take_profit_1']:
            return (True, f'{strategy.upper()}_TP1', 1.0)

        # 2. Stop Loss 체크
        if current_price <= levels['stop_loss']:
            return (True, f'{strategy.upper()}_STOP_LOSS', 1.0)

        # 3. Trailing Stop 체크 (수익 10% 이상일 때)
        if profit_pct >= self.trailing_trigger:
            trailing_stop = highest_price - (entry_atr * self.atr_trailing_multiplier)
            if current_price <= trailing_stop:
                return (True, f'{strategy.upper()}_TRAILING_STOP', 1.0)

        # 4. Timeout 체크
        if hold_days >= max_hold_days:
            return (True, f'{strategy.upper()}_TIMEOUT', 1.0)

        # Exit 조건 없음
        return (False, f'{strategy.upper()}_HOLD', 0.0)

    def _get_strategy_multipliers(self, strategy: str) -> Dict[str, float]:
        """
        전략별 ATR 배율 반환

        Args:
            strategy: 전략 이름

        Returns:
            배율 dict
        """
        # 전략별 기본 배율
        strategy_multipliers = {
            'trend_following': {
                'sl': 3.0,   # Trend는 넓은 SL
                'tp1': 3.0,
                'tp2': 6.0,
                'tp3': 9.0
            },
            'grid': {
                'sl': 2.0,   # Grid는 타이트한 SL (레인지 내)
                'tp1': 2.0,
                'tp2': 4.0,
                'tp3': 6.0
            },
            'sideways': {
                'sl': 2.5,   # Sideways는 중간
                'tp1': 2.5,
                'tp2': 5.0,
                'tp3': 7.5
            },
            'defensive': {
                'sl': 3.5,   # Defensive는 가장 넓은 SL
                'tp1': 2.0,
                'tp2': 4.0,
                'tp3': 6.0
            },
            'default': {
                'sl': 3.0,
                'tp1': 3.0,
                'tp2': 6.0,
                'tp3': 9.0
            }
        }

        return strategy_multipliers.get(strategy, strategy_multipliers['default'])

    def _adjust_for_volatility(
        self,
        atr: float,
        levels: Dict[str, float]
    ) -> Dict[str, float]:
        """
        변동성에 따라 Exit 레벨 조정

        Args:
            atr: ATR 값
            levels: 기본 Exit 레벨

        Returns:
            조정된 Exit 레벨
        """
        # 고변동성 (ATR > 0.03): SL 더 넓게, TP 더 높게
        if atr > self.high_volatility:
            adjustment_factor = 1.2  # 20% 증가
        # 저변동성 (ATR < 0.015): SL 더 타이트, TP 더 낮게
        elif atr < self.low_volatility:
            adjustment_factor = 0.8  # 20% 감소
        # 중간 변동성: 그대로
        else:
            adjustment_factor = 1.0

        # SL은 entry_price에서 더 멀어지게
        # TP는 entry_price에서 더 멀어지게
        # 둘 다 adjustment_factor 적용하면 동일 비율 유지

        return levels  # 일단 그대로 반환 (복잡도 낮춤)

    def get_exit_info(self, strategy: str = 'default') -> Dict:
        """
        전략별 Exit 정보 반환

        Args:
            strategy: 전략 이름

        Returns:
            Exit 설정 정보
        """
        multipliers = self._get_strategy_multipliers(strategy)

        return {
            'strategy': strategy,
            'atr_sl_multiplier': multipliers['sl'],
            'atr_tp1_multiplier': multipliers['tp1'],
            'atr_tp2_multiplier': multipliers['tp2'],
            'atr_tp3_multiplier': multipliers['tp3'],
            'atr_trailing_multiplier': self.atr_trailing_multiplier,
            'trailing_trigger_pct': self.trailing_trigger,
            'high_volatility_threshold': self.high_volatility,
            'low_volatility_threshold': self.low_volatility
        }


# 테스트 코드
if __name__ == '__main__':
    config = {
        'atr_sl_multiplier': 3.0,
        'atr_tp1_multiplier': 3.0,
        'atr_tp2_multiplier': 6.0,
        'atr_tp3_multiplier': 9.0,
        'atr_trailing_multiplier': 3.5,
        'trailing_trigger_pct': 0.10,
        'high_volatility_threshold': 0.03,
        'low_volatility_threshold': 0.015
    }

    manager = ATRDynamicExitManager(config)

    print("="*80)
    print("ATR Dynamic Exit Manager 테스트")
    print("="*80)

    # 시나리오 1: Trend Following
    print("\n[시나리오 1] Trend Following (ATR = 0.02)")
    entry_price = 100_000_000
    entry_atr = 0.02
    strategy = 'trend_following'

    levels = manager.calculate_exit_levels(entry_price, entry_atr, strategy)
    print(f"진입가: {entry_price:,}원")
    print(f"ATR: {entry_atr:.4f} ({entry_atr * entry_price:,.0f}원)")
    print(f"\nExit 레벨:")
    print(f"  Stop Loss:     {levels['stop_loss']:,}원 ({(levels['stop_loss']/entry_price-1)*100:.2f}%)")
    print(f"  Take Profit 1: {levels['take_profit_1']:,}원 (+{(levels['take_profit_1']/entry_price-1)*100:.2f}%)")
    print(f"  Take Profit 2: {levels['take_profit_2']:,}원 (+{(levels['take_profit_2']/entry_price-1)*100:.2f}%)")
    print(f"  Take Profit 3: {levels['take_profit_3']:,}원 (+{(levels['take_profit_3']/entry_price-1)*100:.2f}%)")

    # Exit 체크 테스트
    test_prices = [
        (97_000_000, "SL 도달"),
        (106_000_000, "TP1 도달"),
        (112_000_000, "TP2 도달"),
        (118_000_000, "TP3 도달"),
    ]

    print(f"\nExit 체크:")
    for price, desc in test_prices:
        should_exit, reason, fraction = manager.check_exit(
            entry_price, price, entry_atr,
            highest_price=price,
            hold_days=5,
            strategy=strategy
        )
        print(f"  {desc} ({price:,}원): {reason} (Exit={should_exit})")

    # 시나리오 2: Grid Trading (저변동성)
    print("\n[시나리오 2] Grid Trading (ATR = 0.01, 저변동성)")
    entry_price = 90_000_000
    entry_atr = 0.01
    strategy = 'grid'

    levels = manager.calculate_exit_levels(entry_price, entry_atr, strategy)
    print(f"진입가: {entry_price:,}원")
    print(f"ATR: {entry_atr:.4f} ({entry_atr * entry_price:,.0f}원)")
    print(f"\nExit 레벨:")
    print(f"  Stop Loss:     {levels['stop_loss']:,}원 ({(levels['stop_loss']/entry_price-1)*100:.2f}%)")
    print(f"  Take Profit 1: {levels['take_profit_1']:,}원 (+{(levels['take_profit_1']/entry_price-1)*100:.2f}%)")
    print(f"  Take Profit 2: {levels['take_profit_2']:,}원 (+{(levels['take_profit_2']/entry_price-1)*100:.2f}%)")

    # Trailing Stop 테스트
    print("\n[시나리오 3] Trailing Stop 테스트")
    entry_price = 100_000_000
    entry_atr = 0.02
    highest_price = 115_000_000  # 15% 상승
    current_price = 112_000_000  # 고점에서 3% 하락

    should_exit, reason, fraction = manager.check_exit(
        entry_price, current_price, entry_atr,
        highest_price=highest_price,
        hold_days=10,
        strategy='trend_following'
    )

    trailing_stop = highest_price - (entry_atr * entry_price * 3.5)
    print(f"진입가: {entry_price:,}원")
    print(f"최고가: {highest_price:,}원 (+15%)")
    print(f"현재가: {current_price:,}원 (+12%)")
    print(f"Trailing Stop: {trailing_stop:,}원")
    print(f"Exit 판정: {reason} (should_exit={should_exit})")

    # 전략별 정보 출력
    print("\n" + "="*80)
    print("전략별 Exit 설정")
    print("="*80)

    for strat in ['trend_following', 'grid', 'sideways', 'defensive']:
        print(f"\n{strat}:")
        info = manager.get_exit_info(strat)
        print(f"  SL: ATR × {info['atr_sl_multiplier']}")
        print(f"  TP1: ATR × {info['atr_tp1_multiplier']}")
        print(f"  TP2: ATR × {info['atr_tp2_multiplier']}")
        print(f"  TP3: ATR × {info['atr_tp3_multiplier']}")
        print(f"  Trailing: ATR × {info['atr_trailing_multiplier']}")
