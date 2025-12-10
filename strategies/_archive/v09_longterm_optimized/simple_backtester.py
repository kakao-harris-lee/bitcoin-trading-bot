#!/usr/bin/env python3
"""Simple Backtester for v07"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict


@dataclass
class Trade:
    """거래 기록"""
    entry_time: datetime
    entry_price: float
    exit_time: datetime = None
    exit_price: float = None
    quantity: float = 0.0
    profit_loss: float = None
    profit_loss_pct: float = None
    reason: str = ""


class SimpleBacktester:
    """Simple backtester for single strategy"""

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

        # Account
        self.cash = initial_capital
        self.position = 0.0  # BTC quantity
        self.entry_price = 0.0

        # Records
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []

    def execute_buy(self, timestamp, price: float, fraction: float) -> bool:
        """매수"""
        available = self.cash * fraction
        if available < 10_000:
            return False

        exec_price = price * (1 + self.slippage)
        quantity = available / (exec_price * (1 + self.fee_rate))
        cost = quantity * exec_price * (1 + self.fee_rate)

        if cost > self.cash:
            return False

        self.cash -= cost
        self.position += quantity
        self.entry_price = exec_price

        # Record
        self.trades.append(Trade(
            entry_time=timestamp,
            entry_price=exec_price,
            quantity=quantity
        ))

        return True

    def execute_sell(self, timestamp, price: float, fraction: float) -> bool:
        """매도"""
        if self.position <= 0:
            return False

        sell_qty = self.position * fraction
        exec_price = price * (1 - self.slippage)
        proceeds = sell_qty * exec_price * (1 - self.fee_rate)

        if proceeds < 10_000 and fraction < 1.0:
            return False

        # Calculate P&L
        last_trade = None
        for t in reversed(self.trades):
            if t.exit_time is None:
                last_trade = t
                break

        if last_trade:
            last_trade.exit_time = timestamp
            last_trade.exit_price = exec_price
            last_trade.profit_loss = (exec_price - last_trade.entry_price) * sell_qty
            last_trade.profit_loss_pct = ((exec_price - last_trade.entry_price) / last_trade.entry_price) * 100

        self.cash += proceeds
        self.position -= sell_qty

        return True

    def record_equity(self, timestamp, day_price: float, layer2_price: float = None):
        """자산 기록"""
        position_value = self.position * day_price
        total_equity = self.cash + position_value

        self.equity_curve.append({
            'timestamp': timestamp,
            'cash': self.cash,
            'position_value': position_value,
            'total_equity': total_equity
        })

    def get_results(self) -> Dict:
        """결과 반환"""
        # Finalize trades
        completed_trades = [t for t in self.trades if t.exit_time is not None]
        winning = [t for t in completed_trades if t.profit_loss > 0]
        losing = [t for t in completed_trades if t.profit_loss <= 0]

        # Equity curve
        equity_df = pd.DataFrame(self.equity_curve)
        final_equity = equity_df.iloc[-1]['total_equity'] if len(equity_df) > 0 else self.initial_capital

        # Returns
        equity_df['returns'] = equity_df['total_equity'].pct_change()

        # Drawdown
        equity_df['cummax'] = equity_df['total_equity'].cummax()
        equity_df['drawdown'] = (equity_df['total_equity'] - equity_df['cummax']) / equity_df['cummax']
        max_drawdown = abs(equity_df['drawdown'].min()) * 100 if len(equity_df) > 0 else 0

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_equity,
            'total_return': ((final_equity - self.initial_capital) / self.initial_capital) * 100,
            'total_trades': len(completed_trades),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': len(winning) / len(completed_trades) if completed_trades else 0,
            'avg_profit': np.mean([t.profit_loss_pct for t in winning]) if winning else 0,
            'avg_loss': np.mean([t.profit_loss_pct for t in losing]) if losing else 0,
            'profit_factor': (
                sum([t.profit_loss for t in winning]) / abs(sum([t.profit_loss for t in losing]))
                if losing and sum([t.profit_loss for t in losing]) != 0 else 0
            ),
            'max_drawdown': max_drawdown,
            'equity_curve': equity_df,
            'trades': self.trades
        }
