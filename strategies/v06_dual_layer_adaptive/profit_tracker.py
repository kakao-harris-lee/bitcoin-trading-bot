#!/usr/bin/env python3
"""
profit_tracker.py
DAY 전략 수익 추적 및 Layer 2 자본 계산
"""

from typing import Dict, Optional


class ProfitTracker:
    """DAY 전략 수익 추적 및 Layer 2 자본 관리"""

    def __init__(self, initial_capital: float, config: dict):
        """
        Args:
            initial_capital: 초기 자본
            config: layer2_scalping 설정
        """
        self.initial_capital = initial_capital
        self.config = config

        # Layer 1 (DAY) 상태
        self.day_cash = initial_capital
        self.day_position_value = 0.0
        self.day_entry_price = 0.0
        self.day_position_size = 0.0

        # Layer 2 상태
        self.layer2_allocated = 0.0
        self.layer2_cash = 0.0
        self.layer2_position_value = 0.0
        self.layer2_cumulative_pnl = 0.0

        # 설정
        self.capital_fraction = config.get('capital_fraction', 0.50)
        self.max_exposure = config.get('max_exposure', 0.15)

    def update_day_position(
        self,
        action: str,
        price: float,
        quantity: float = 0.0
    ):
        """DAY 포지션 업데이트"""
        if action == 'buy':
            self.day_entry_price = price
            self.day_position_size = quantity
            self.day_position_value = quantity * price

        elif action == 'sell':
            self.day_entry_price = 0.0
            self.day_position_size = 0.0
            self.day_position_value = 0.0

        else:  # update
            if self.day_position_size > 0:
                self.day_position_value = self.day_position_size * price

    def get_day_unrealized_profit(self, current_price: float) -> float:
        """DAY 미실현 이익 (금액)"""
        if self.day_position_size == 0 or self.day_entry_price == 0:
            return 0.0

        profit = (current_price - self.day_entry_price) * self.day_position_size
        return profit

    def get_day_profit_pct(self, current_price: float) -> float:
        """DAY 미실현 이익률"""
        if self.day_entry_price == 0:
            return 0.0

        return (current_price - self.day_entry_price) / self.day_entry_price

    def calculate_layer2_capital(self, current_price: float) -> float:
        """Layer 2 사용 가능 자본 계산"""
        unrealized_profit = self.get_day_unrealized_profit(current_price)

        if unrealized_profit <= 0:
            return 0.0

        # 미실현 이익의 capital_fraction만큼
        available = unrealized_profit * self.capital_fraction

        # 최대 노출 제한 (총 자본의 max_exposure)
        total_capital = self.day_cash + self.day_position_value
        max_allowed = total_capital * self.max_exposure

        return min(available, max_allowed)

    def allocate_layer2(self, amount: float):
        """Layer 2에 자본 할당"""
        self.layer2_allocated += amount
        self.layer2_cash += amount

    def deallocate_layer2(self, amount: float):
        """Layer 2 자본 회수"""
        self.layer2_allocated -= amount
        self.layer2_cash -= amount

    def update_layer2_position(self, position_value: float):
        """Layer 2 포지션 가치 업데이트"""
        self.layer2_position_value = position_value

    def record_layer2_trade(self, pnl: float):
        """Layer 2 거래 손익 기록"""
        self.layer2_cumulative_pnl += pnl

    def get_layer2_loss_pct(self) -> float:
        """Layer 2 누적 손실률 (DAY 수익 대비)"""
        if self.day_position_value == 0:
            return 0.0

        day_profit = self.day_position_value - (self.day_position_size * self.day_entry_price)

        if day_profit <= 0:
            return 0.0

        return abs(self.layer2_cumulative_pnl) / day_profit if self.layer2_cumulative_pnl < 0 else 0.0

    def should_shutdown_layer2(self, max_loss_pct: float = 0.20) -> bool:
        """Layer 2 비활성화 조건 체크"""
        loss_pct = self.get_layer2_loss_pct()
        return loss_pct >= max_loss_pct

    def get_total_equity(self, day_price: float, layer2_price: float = 0.0) -> float:
        """전체 자본 계산"""
        day_equity = self.day_cash + (self.day_position_size * day_price)
        layer2_equity = self.layer2_cash + self.layer2_position_value

        return day_equity + layer2_equity

    def get_status(self, day_price: float) -> Dict:
        """현재 상태 요약"""
        return {
            'initial_capital': self.initial_capital,
            'day_cash': self.day_cash,
            'day_position_value': self.day_position_size * day_price,
            'day_unrealized_profit': self.get_day_unrealized_profit(day_price),
            'day_profit_pct': self.get_day_profit_pct(day_price),
            'layer2_allocated': self.layer2_allocated,
            'layer2_cash': self.layer2_cash,
            'layer2_position_value': self.layer2_position_value,
            'layer2_cumulative_pnl': self.layer2_cumulative_pnl,
            'layer2_loss_pct': self.get_layer2_loss_pct(),
            'total_equity': self.get_total_equity(day_price),
            'total_return_pct': (self.get_total_equity(day_price) - self.initial_capital) / self.initial_capital
        }
