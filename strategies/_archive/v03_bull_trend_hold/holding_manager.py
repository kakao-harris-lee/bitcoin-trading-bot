#!/usr/bin/env python3
"""
holding_manager.py
최대 보유 기간 관리 모듈
"""

from datetime import datetime, timedelta
from typing import Optional, Dict


class HoldingManager:
    """포지션 보유 기간 관리자"""

    def __init__(
        self,
        timeframe: str = 'minute5',
        max_holding_candles: int = 2016,  # 7일 기본값 (minute5)
        extended_candles: int = 4032       # 14일 (연장)
    ):
        """
        Args:
            timeframe: 타임프레임 ('minute5', 'minute15', etc.)
            max_holding_candles: 최대 보유 캔들 수 (기본)
            extended_candles: 연장 시 최대 캔들 수
        """
        self.timeframe = timeframe
        self.max_holding_candles = max_holding_candles
        self.extended_candles = extended_candles

        # 포지션 정보
        self.entry_idx: Optional[int] = None
        self.entry_price: float = 0.0
        self.is_extended: bool = False

    def on_entry(self, idx: int, price: float):
        """매수 진입 시 호출"""
        self.entry_idx = idx
        self.entry_price = price
        self.is_extended = False

    def on_exit(self):
        """매도 청산 시 호출"""
        self.entry_idx = None
        self.entry_price = 0.0
        self.is_extended = False

    def is_holding(self) -> bool:
        """보유 중인지 확인"""
        return self.entry_idx is not None

    def get_holding_period(self, current_idx: int) -> int:
        """현재 보유 기간 (캔들 수)"""
        if not self.is_holding():
            return 0
        return current_idx - self.entry_idx

    def should_force_exit(
        self,
        current_idx: int,
        current_price: float,
        profit_threshold: float = 0.05
    ) -> Dict:
        """
        강제 청산 여부 판단

        Args:
            current_idx: 현재 인덱스
            current_price: 현재 가격
            profit_threshold: 연장 조건 수익률 (5% = 0.05)

        Returns:
            {
                'should_exit': bool,
                'reason': str,
                'holding_period': int (캔들 수),
                'profit': float (%)
            }
        """
        if not self.is_holding():
            return {
                'should_exit': False,
                'reason': 'no_position',
                'holding_period': 0,
                'profit': 0.0
            }

        holding_period = self.get_holding_period(current_idx)
        profit = (current_price - self.entry_price) / self.entry_price

        # 기본 최대 보유 기간 도달
        if holding_period >= self.max_holding_candles:
            # 수익 5% 이상 + 아직 연장 안 됨 → 연장
            if profit >= profit_threshold and not self.is_extended:
                self.is_extended = True
                return {
                    'should_exit': False,
                    'reason': 'extended',
                    'holding_period': holding_period,
                    'profit': profit
                }

            # 연장 기간도 도달 → 강제 청산
            if self.is_extended and holding_period >= self.extended_candles:
                return {
                    'should_exit': True,
                    'reason': 'max_holding_extended',
                    'holding_period': holding_period,
                    'profit': profit
                }

            # 수익 미달 → 강제 청산
            if profit < profit_threshold:
                return {
                    'should_exit': True,
                    'reason': 'max_holding_base',
                    'holding_period': holding_period,
                    'profit': profit
                }

        # 아직 보유 유지
        return {
            'should_exit': False,
            'reason': 'holding',
            'holding_period': holding_period,
            'profit': profit
        }

    @staticmethod
    def get_recommended_max_candles(timeframe: str) -> tuple:
        """
        타임프레임별 권장 최대 보유 캔들 수

        Returns:
            (기본 캔들 수, 연장 캔들 수)
        """
        mapping = {
            'minute5': (2016, 4032),    # 7일, 14일
            'minute15': (672, 1344),    # 7일, 14일
            'minute30': (480, 960),     # 10일, 20일
            'minute60': (336, 672),     # 14일, 28일
            'minute240': (126, 252),    # 21일, 42일
            'day': (30, 60),            # 30일, 60일
        }
        return mapping.get(timeframe, (2016, 4032))


# 사용 예제
if __name__ == "__main__":
    # minute5 기준 7일 보유
    manager = HoldingManager(timeframe='minute5')

    # 매수 진입
    manager.on_entry(idx=100, price=100_000_000)
    print(f"✅ 매수 진입: 100번 캔들, 1억원")

    # 7일 후 (2016 캔들)
    current_idx = 100 + 2016
    current_price = 105_000_000  # 5% 수익

    result = manager.should_force_exit(current_idx, current_price)
    print(f"\n7일 경과 (2016 캔들):")
    print(f"   강제 청산: {result['should_exit']}")
    print(f"   사유: {result['reason']}")
    print(f"   수익: {result['profit']:.2%}")

    # 14일 후 (4032 캔들)
    current_idx = 100 + 4032
    current_price = 107_000_000  # 7% 수익

    result = manager.should_force_exit(current_idx, current_price)
    print(f"\n14일 경과 (4032 캔들, 연장 후):")
    print(f"   강제 청산: {result['should_exit']}")
    print(f"   사유: {result['reason']}")
    print(f"   수익: {result['profit']:.2%}")
