#!/usr/bin/env python3
"""
backtester.py
백테스팅 엔진 - 가격 데이터 기반 거래 시뮬레이션
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Trade:
    """거래 기록"""
    entry_time: datetime
    entry_price: float
    quantity: float
    side: str  # 'buy' or 'sell'
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None
    reason: str = ""

class Backtester:
    """백테스팅 엔진"""

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,  # 0.05%
        slippage: float = 0.0002,   # 0.02%
        min_order_amount: float = 10_000
    ):
        """
        Args:
            initial_capital: 초기 자본 (원)
            fee_rate: 수수료율
            slippage: 슬리피지
            min_order_amount: 최소 주문 금액 (원)
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.min_order_amount = min_order_amount

        # 상태 변수
        self.cash = initial_capital
        self.position = 0.0  # 보유 수량
        self.position_value = 0.0
        self.trades: List[Trade] = []
        self.equity_curve = []

    def reset(self):
        """상태 초기화"""
        self.cash = self.initial_capital
        self.position = 0.0
        self.position_value = 0.0
        self.trades = []
        self.equity_curve = []

    def run(
        self,
        df: pd.DataFrame,
        strategy_func: Callable,
        strategy_params: Dict = None
    ) -> Dict:
        """
        백테스팅 실행

        Args:
            df: 가격 데이터 (timestamp, open, high, low, close, volume)
            strategy_func: 전략 함수 (df, i, params) -> {'action': 'buy'/'sell'/'hold', 'fraction': 0.5}
            strategy_params: 전략 파라미터

        Returns:
            백테스팅 결과 딕셔너리
        """
        self.reset()

        if strategy_params is None:
            strategy_params = {}

        for i in range(len(df)):
            row = df.iloc[i]
            timestamp = row['timestamp']
            price = row['close']

            # 전략 시그널 생성
            signal = strategy_func(df, i, strategy_params)
            action = signal.get('action', 'hold')
            fraction = signal.get('fraction', 1.0)  # 투자 비율

            # 액션 실행
            if action == 'buy':
                self._execute_buy(timestamp, price, fraction)
            elif action == 'sell':
                self._execute_sell(timestamp, price, fraction)

            # 포지션 가치 업데이트
            if self.position > 0:
                self.position_value = self.position * price
            else:
                self.position_value = 0.0

            # Equity curve 기록
            total_equity = self.cash + self.position_value
            self.equity_curve.append({
                'timestamp': timestamp,
                'cash': self.cash,
                'position_value': self.position_value,
                'total_equity': total_equity
            })

        # 마지막 포지션 정리 (남은 포지션 매도)
        if self.position > 0:
            last_row = df.iloc[-1]
            self._execute_sell(last_row['timestamp'], last_row['close'], 1.0)

        return self._generate_results()

    def _execute_buy(self, timestamp: datetime, price: float, fraction: float):
        """매수 실행"""
        # 투자 가능 금액
        available_cash = self.cash * fraction

        if available_cash < self.min_order_amount:
            return  # 최소 주문 금액 미달

        # 슬리피지 적용 (매수 시 불리하게)
        execution_price = price * (1 + self.slippage)

        # 수수료 포함 구매 가능 수량
        quantity = available_cash / (execution_price * (1 + self.fee_rate))

        # 실제 사용 금액
        cost = quantity * execution_price * (1 + self.fee_rate)

        if cost > self.cash:
            return  # 잔액 부족

        # 매수 실행
        self.cash -= cost
        self.position += quantity

        # 거래 기록
        trade = Trade(
            entry_time=timestamp,
            entry_price=execution_price,
            quantity=quantity,
            side='buy',
            reason=f'Buy {fraction*100:.1f}% of cash'
        )
        self.trades.append(trade)

    def _execute_sell(self, timestamp: datetime, price: float, fraction: float):
        """매도 실행"""
        if self.position <= 0:
            return  # 보유 없음

        # 매도 수량
        quantity = self.position * fraction

        # 슬리피지 적용 (매도 시 불리하게)
        execution_price = price * (1 - self.slippage)

        # 수수료 차감 후 수령 금액
        proceeds = quantity * execution_price * (1 - self.fee_rate)

        if proceeds < self.min_order_amount:
            return  # 최소 주문 금액 미달

        # 매도 실행
        self.cash += proceeds
        self.position -= quantity

        # 매칭되는 매수 거래 찾기 (FIFO)
        for trade in self.trades:
            if trade.side == 'buy' and trade.exit_time is None:
                # 손익 계산
                trade.exit_time = timestamp
                trade.exit_price = execution_price
                trade.profit_loss = (execution_price - trade.entry_price) * trade.quantity
                trade.profit_loss_pct = ((execution_price - trade.entry_price) / trade.entry_price) * 100
                trade.reason += f' -> Sell {fraction*100:.1f}%'
                break

    def _generate_results(self) -> Dict:
        """결과 생성"""
        final_equity = self.cash + self.position_value
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100

        # 완료된 거래만 추출
        closed_trades = [t for t in self.trades if t.exit_time is not None]

        if not closed_trades:
            return {
                'initial_capital': self.initial_capital,
                'final_capital': final_equity,
                'total_return': total_return,
                'total_trades': 0,
                'equity_curve': pd.DataFrame(self.equity_curve)
            }

        # 승리/패배 거래
        winning_trades = [t for t in closed_trades if t.profit_loss > 0]
        losing_trades = [t for t in closed_trades if t.profit_loss <= 0]

        # 통계
        win_rate = len(winning_trades) / len(closed_trades) if closed_trades else 0
        avg_profit = np.mean([t.profit_loss for t in winning_trades]) if winning_trades else 0
        avg_loss = abs(np.mean([t.profit_loss for t in losing_trades])) if losing_trades else 0
        profit_factor = sum(t.profit_loss for t in winning_trades) / abs(sum(t.profit_loss for t in losing_trades)) if losing_trades else 0

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_equity,
            'total_return': total_return,
            'total_trades': len(closed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'trades': closed_trades,
            'equity_curve': pd.DataFrame(self.equity_curve)
        }


# 사용 예제
if __name__ == "__main__":
    from data_loader import DataLoader

    # 간단한 전략 예제: RSI 기반
    def simple_rsi_strategy(df, i, params):
        """RSI 30 이하 매수, 70 이상 매도"""
        if i < 14:
            return {'action': 'hold'}

        # RSI 계산 (간단 버전)
        window = 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=window).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = rsi.iloc[i]

        if current_rsi < 30:
            return {'action': 'buy', 'fraction': 0.5}
        elif current_rsi > 70:
            return {'action': 'sell', 'fraction': 1.0}
        else:
            return {'action': 'hold'}

    # 데이터 로드
    with DataLoader() as loader:
        df = loader.load_timeframe("minute5", start_date="2024-01-01", end_date="2024-01-31")

    # 백테스팅 실행
    backtester = Backtester()
    results = backtester.run(df, simple_rsi_strategy)

    print("✅ 백테스팅 결과:")
    print(f"   초기 자본: {results['initial_capital']:,.0f}원")
    print(f"   최종 자본: {results['final_capital']:,.0f}원")
    print(f"   총 수익률: {results['total_return']:.2f}%")
    print(f"   총 거래: {results['total_trades']}회")
    print(f"   승률: {results['win_rate']:.1%}")
    print(f"   Profit Factor: {results['profit_factor']:.2f}")
