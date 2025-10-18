#!/usr/bin/env python3
"""
dual_backtester.py
이중 레이어 백테스팅 엔진

Layer 1 (DAY): 100% 자본으로 기본 트렌드 추종
Layer 2 (minute60/240): DAY 수익금의 일부로 scalping
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass


@dataclass
class Trade:
    """거래 기록"""
    layer: str  # 'day' or 'layer2'
    entry_time: datetime
    entry_price: float
    exit_time: datetime = None
    exit_price: float = None
    quantity: float = 0.0
    profit_loss: float = None
    profit_loss_pct: float = None
    reason: str = ""


class DualLayerBacktester:
    """이중 레이어 백테스팅 엔진"""

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

        # Layer 1 (DAY)
        self.day_cash = initial_capital
        self.day_position = 0.0  # BTC 수량
        self.day_entry_price = 0.0

        # Layer 2 (scalping)
        self.layer2_cash = 0.0
        self.layer2_position = 0.0
        self.layer2_entry_price = 0.0
        self.layer2_allocated = 0.0  # DAY에서 할당받은 총액
        self.layer2_cumulative_pnl = 0.0

        # 거래 기록
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []

        # Layer 2 제어
        self.layer2_enabled = True
        self.layer2_shutdown = False

    def execute_day_buy(self, timestamp, price: float, fraction: float) -> bool:
        """DAY 매수"""
        available = self.day_cash * fraction
        if available < 10_000:
            return False

        exec_price = price * (1 + self.slippage)
        quantity = available / (exec_price * (1 + self.fee_rate))
        cost = quantity * exec_price * (1 + self.fee_rate)

        if cost > self.day_cash:
            return False

        self.day_cash -= cost
        self.day_position += quantity
        self.day_entry_price = exec_price

        # 거래 기록
        self.trades.append(Trade(
            layer='day',
            entry_time=timestamp,
            entry_price=exec_price,
            quantity=quantity
        ))

        return True

    def execute_day_sell(self, timestamp, price: float, fraction: float) -> Tuple[bool, float]:
        """DAY 매도"""
        if self.day_position <= 0:
            return False, 0.0

        sell_qty = self.day_position * fraction
        exec_price = price * (1 - self.slippage)
        proceeds = sell_qty * exec_price * (1 - self.fee_rate)

        if proceeds < 10_000:
            return False, 0.0

        self.day_cash += proceeds
        self.day_position -= sell_qty

        # 손익 계산
        pnl = (exec_price - self.day_entry_price) * sell_qty
        pnl_pct = ((exec_price - self.day_entry_price) / self.day_entry_price) * 100

        # 거래 기록 업데이트
        for trade in reversed(self.trades):
            if trade.layer == 'day' and trade.exit_time is None:
                trade.exit_time = timestamp
                trade.exit_price = exec_price
                trade.profit_loss = pnl
                trade.profit_loss_pct = pnl_pct
                trade.reason = f'DAY sell {fraction*100:.0f}%'
                break

        return True, pnl

    def calculate_layer2_capital(self, current_day_price: float, config: dict) -> float:
        """Layer 2 사용 가능 자본 계산"""
        if self.day_position <= 0 or self.day_entry_price == 0:
            return 0.0

        # DAY 미실현 이익
        unrealized_profit = (current_day_price - self.day_entry_price) * self.day_position

        if unrealized_profit <= 0:
            return 0.0

        # 설정된 비율만큼만 사용
        capital_fraction = config.get('capital_fraction', 0.50)
        available = unrealized_profit * capital_fraction

        # 최대 노출 제한
        total_capital = self.day_cash + (self.day_position * current_day_price)
        max_exposure = config.get('max_exposure', 0.15)
        max_allowed = total_capital * max_exposure

        return min(available, max_allowed)

    def execute_layer2_buy(self, timestamp, price: float, allocated_capital: float) -> bool:
        """Layer 2 매수"""
        if allocated_capital < 10_000:
            return False

        # Layer 2에 자본 할당
        if self.layer2_cash < allocated_capital:
            shortage = allocated_capital - self.layer2_cash
            self.layer2_cash += shortage
            self.layer2_allocated += shortage

        exec_price = price * (1 + self.slippage)
        quantity = allocated_capital / (exec_price * (1 + self.fee_rate))
        cost = quantity * exec_price * (1 + self.fee_rate)

        if cost > self.layer2_cash:
            return False

        self.layer2_cash -= cost
        self.layer2_position += quantity
        self.layer2_entry_price = exec_price

        # 거래 기록
        self.trades.append(Trade(
            layer='layer2',
            entry_time=timestamp,
            entry_price=exec_price,
            quantity=quantity
        ))

        return True

    def execute_layer2_sell(self, timestamp, price: float, fraction: float) -> Tuple[bool, float]:
        """Layer 2 매도"""
        if self.layer2_position <= 0:
            return False, 0.0

        sell_qty = self.layer2_position * fraction
        exec_price = price * (1 - self.slippage)
        proceeds = sell_qty * exec_price * (1 - self.fee_rate)

        if proceeds < 10_000:
            return False, 0.0

        self.layer2_cash += proceeds
        self.layer2_position -= sell_qty

        # 손익 계산
        pnl = (exec_price - self.layer2_entry_price) * sell_qty
        pnl_pct = ((exec_price - self.layer2_entry_price) / self.layer2_entry_price) * 100

        self.layer2_cumulative_pnl += pnl

        # 거래 기록 업데이트
        for trade in reversed(self.trades):
            if trade.layer == 'layer2' and trade.exit_time is None:
                trade.exit_time = timestamp
                trade.exit_price = exec_price
                trade.profit_loss = pnl
                trade.profit_loss_pct = pnl_pct
                trade.reason = f'Layer2 sell {fraction*100:.0f}%'
                break

        return True, pnl

    def get_total_equity(self, day_price: float, layer2_price: float = 0.0) -> float:
        """전체 자본 계산"""
        day_equity = self.day_cash + (self.day_position * day_price)

        if layer2_price == 0.0:
            layer2_price = day_price

        layer2_equity = self.layer2_cash + (self.layer2_position * layer2_price)

        return day_equity + layer2_equity

    def check_layer2_shutdown(self, max_loss_pct: float = 0.20) -> bool:
        """Layer 2 비활성화 조건 체크"""
        if self.day_position <= 0 or self.day_entry_price == 0:
            return False

        day_profit = (self.day_position * self.day_entry_price) - (self.day_entry_price * self.day_position)

        if day_profit <= 0 or self.layer2_cumulative_pnl >= 0:
            return False

        loss_ratio = abs(self.layer2_cumulative_pnl) / day_profit
        return loss_ratio >= max_loss_pct

    def record_equity(self, timestamp, day_price: float, layer2_price: float = 0.0):
        """Equity curve 기록"""
        self.equity_curve.append({
            'timestamp': timestamp,
            'day_cash': self.day_cash,
            'day_position_value': self.day_position * day_price,
            'layer2_cash': self.layer2_cash,
            'layer2_position_value': self.layer2_position * (layer2_price if layer2_price > 0 else day_price),
            'total_equity': self.get_total_equity(day_price, layer2_price)
        })

    def get_results(self) -> Dict:
        """백테스팅 결과 생성"""
        df_equity = pd.DataFrame(self.equity_curve)
        final_equity = df_equity.iloc[-1]['total_equity'] if len(df_equity) > 0 else self.initial_capital

        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100

        # 레이어별 통계
        day_trades = [t for t in self.trades if t.layer == 'day' and t.exit_time is not None]
        layer2_trades = [t for t in self.trades if t.layer == 'layer2' and t.exit_time is not None]

        # Layer 1 통계
        day_stats = self._calc_trade_stats(day_trades)

        # Layer 2 통계
        layer2_stats = self._calc_trade_stats(layer2_trades)

        # 전체 거래 통계 (Evaluator 호환성)
        all_trades = day_trades + layer2_trades
        all_winning = [t for t in all_trades if t.profit_loss > 0]
        all_losing = [t for t in all_trades if t.profit_loss <= 0]

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_equity,
            'total_return': total_return,
            'total_trades': len(all_trades),
            'winning_trades': len(all_winning),
            'losing_trades': len(all_losing),
            'win_rate': len(all_winning) / len(all_trades) if all_trades else 0.0,
            'avg_profit': np.mean([t.profit_loss for t in all_winning]) if all_winning else 0.0,
            'avg_loss': abs(np.mean([t.profit_loss for t in all_losing])) if all_losing else 0.0,
            'profit_factor': (sum(t.profit_loss for t in all_winning) / abs(sum(t.profit_loss for t in all_losing))) if all_losing and sum(t.profit_loss for t in all_losing) != 0 else 0.0,
            'equity_curve': df_equity,
            'trades': self.trades,
            'day_stats': day_stats,
            'layer2_stats': layer2_stats,
            'layer2_cumulative_pnl': self.layer2_cumulative_pnl,
            'layer2_shutdown': self.layer2_shutdown
        }

    def _calc_trade_stats(self, trades: List[Trade]) -> Dict:
        """거래 통계 계산"""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_profit': 0.0,
                'avg_loss': 0.0
            }

        winning = [t for t in trades if t.profit_loss > 0]
        losing = [t for t in trades if t.profit_loss <= 0]

        return {
            'total_trades': len(trades),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': len(winning) / len(trades) if trades else 0,
            'total_pnl': sum(t.profit_loss for t in trades),
            'avg_profit': np.mean([t.profit_loss for t in winning]) if winning else 0,
            'avg_loss': abs(np.mean([t.profit_loss for t in losing])) if losing else 0
        }
