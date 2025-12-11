#!/usr/bin/env python3
"""
Paper Trading Engine
모의 거래 엔진 (실제 API 호출 없이 시뮬레이션)
"""

from typing import Dict, Optional, List
from datetime import datetime
import json


class PaperTradingAccount:
    """Paper Trading 계좌"""

    def __init__(self, initial_capital: float, exchange: str):
        """
        Args:
            initial_capital: 초기 자본 (KRW 또는 USDT)
            exchange: 'upbit' 또는 'binance'
        """
        self.exchange = exchange
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.btc_balance = 0.0
        self.position_size = 0.0
        self.entry_price = 0.0
        self.leverage = 1
        self.trades: List[Dict] = []
        self.is_short = (exchange == 'binance')

    def get_balance(self) -> tuple:
        """잔고 조회"""
        return (self.cash, self.btc_balance)

    def get_total_value(self, current_price: float) -> float:
        """총 자산 가치"""
        btc_value = self.btc_balance * current_price
        return self.cash + btc_value

    def buy(self, amount: float, price: float) -> Dict:
        """매수 (Long)"""
        if amount > self.cash:
            return {'success': False, 'error': '잔고 부족'}

        btc_qty = amount / price
        fee = amount * 0.0005  # 0.05%

        self.cash -= (amount + fee)
        self.btc_balance += btc_qty
        self.entry_price = price

        trade = {
            'timestamp': datetime.now().isoformat(),
            'type': 'buy',
            'price': price,
            'amount': amount,
            'btc_qty': btc_qty,
            'fee': fee,
            'balance_after': self.cash
        }
        self.trades.append(trade)

        return {
            'success': True,
            'executed_volume': btc_qty,
            'executed_price': price,
            'fee': fee,
            'trade': trade
        }

    def sell(self, btc_qty: float, price: float) -> Dict:
        """매도"""
        if btc_qty > self.btc_balance:
            return {'success': False, 'error': 'BTC 부족'}

        sell_amount = btc_qty * price
        fee = sell_amount * 0.0005

        self.cash += (sell_amount - fee)
        self.btc_balance -= btc_qty

        pnl = (price - self.entry_price) * btc_qty - fee if self.entry_price > 0 else 0

        trade = {
            'timestamp': datetime.now().isoformat(),
            'type': 'sell',
            'price': price,
            'btc_qty': btc_qty,
            'amount': sell_amount,
            'fee': fee,
            'pnl': pnl,
            'balance_after': self.cash
        }
        self.trades.append(trade)

        return {
            'success': True,
            'executed_volume': btc_qty,
            'executed_price': price,
            'total_value': sell_amount - fee,
            'pnl': pnl,
            'fee': fee,
            'trade': trade
        }

    def open_short(self, usdt_amount: float, price: float, leverage: int = 1) -> Dict:
        """숏 포지션 오픈 (Binance 선물)"""
        if self.exchange != 'binance':
            return {'success': False, 'error': 'Binance만 지원'}

        if usdt_amount > self.cash:
            return {'success': False, 'error': '증거금 부족'}

        btc_qty = (usdt_amount * leverage) / price
        fee = usdt_amount * 0.0004  # 0.04% (선물)

        self.position_size = btc_qty
        self.entry_price = price
        self.leverage = leverage
        self.cash -= fee  # 증거금은 유지, 수수료만 차감

        trade = {
            'timestamp': datetime.now().isoformat(),
            'type': 'open_short',
            'price': price,
            'size': btc_qty,
            'leverage': leverage,
            'margin': usdt_amount,
            'fee': fee
        }
        self.trades.append(trade)

        return {
            'success': True,
            'executed_qty': btc_qty,
            'avg_price': price,
            'leverage': leverage,
            'margin': usdt_amount,
            'fee': fee,
            'trade': trade
        }

    def close_short(self, price: float) -> Dict:
        """숏 포지션 청산"""
        if self.position_size == 0:
            return {'success': False, 'error': '포지션 없음'}

        # 손익 계산: 숏이므로 가격 하락 시 이익
        pnl = (self.entry_price - price) * self.position_size * self.leverage
        fee = abs(pnl) * 0.0004

        self.cash += (pnl - fee)
        realized_pnl = pnl - fee

        trade = {
            'timestamp': datetime.now().isoformat(),
            'type': 'close_short',
            'price': price,
            'size': self.position_size,
            'entry_price': self.entry_price,
            'pnl': pnl,
            'fee': fee,
            'realized_pnl': realized_pnl,
            'balance_after': self.cash
        }
        self.trades.append(trade)

        self.position_size = 0.0
        self.entry_price = 0.0
        self.leverage = 1

        return {
            'success': True,
            'realized_pnl': realized_pnl,
            'fee': fee,
            'trade': trade
        }

    def get_position(self) -> Optional[Dict]:
        """현재 포지션 조회"""
        if self.position_size == 0:
            return None

        return {
            'size': self.position_size,
            'entry_price': self.entry_price,
            'leverage': self.leverage,
            'is_short': self.is_short
        }

    def get_statistics(self) -> Dict:
        """통계 조회"""
        total_trades = len([t for t in self.trades if t['type'] in ['sell', 'close_short']])
        total_pnl = sum(t.get('realized_pnl', t.get('pnl', 0)) for t in self.trades)
        total_fees = sum(t.get('fee', 0) for t in self.trades)

        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0 or t.get('realized_pnl', 0) > 0]
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0

        return {
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'net_pnl': total_pnl - total_fees,
            'win_rate': win_rate,
            'initial_capital': self.initial_capital,
            'current_cash': self.cash,
            'return_pct': ((self.cash - self.initial_capital) / self.initial_capital) * 100
        }

    def save_log(self, filepath: str = 'logs/paper_trading.json'):
        """거래 로그 저장"""
        import os
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        log = {
            'exchange': self.exchange,
            'initial_capital': self.initial_capital,
            'current_cash': self.cash,
            'btc_balance': self.btc_balance,
            'position_size': self.position_size,
            'trades': self.trades,
            'statistics': self.get_statistics()
        }

        with open(filepath, 'w') as f:
            json.dump(log, f, indent=2)

        print(f"✅ Paper Trading 로그 저장: {filepath}")
