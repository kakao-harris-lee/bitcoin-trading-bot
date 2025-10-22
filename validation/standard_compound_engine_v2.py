#!/usr/bin/env python3
"""
StandardCompoundEngine v2 - 포지션 누적 지원
=============================================

핵심 개선사항:
1. 동시 다중 포지션 지원 (position_size < 100% 시 누적)
2. 포지션별 독립적인 추적 (개별 진입가, 수량)
3. 부분 청산 지원
4. 가중평균 진입가 계산
5. 검증된 복리 계산 (v1 호환)

사용법:
  engine = StandardCompoundEngineV2()

  # 분할 매수 (누적)
  engine.buy(timestamp, price, fraction=0.2)  # 20% 투자
  engine.buy(timestamp, price, fraction=0.3)  # 30% 추가 (누적 50%)

  # 부분 청산
  engine.sell(timestamp, price, fraction=0.5)  # 50% 청산

  # 전체 청산
  engine.sell(timestamp, price, fraction=1.0)  # 100% 청산
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime


class StandardCompoundEngineV2:
    """
    개선된 복리 계산 엔진 - 포지션 누적 지원

    특징:
    - 포지션 누적: 100% 상한선까지 여러 번 매수 가능
    - 부분 청산: 보유 포지션의 일부만 매도 가능
    - 가중평균 진입가: 여러 진입가의 가중평균으로 수익률 계산
    - 복리 효과: 수익금은 즉시 자본에 반영되어 다음 거래에 활용
    """

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002
    ):
        """
        Args:
            initial_capital: 초기 자본 (원)
            fee_rate: 수수료율 (0.05% = 0.0005)
            slippage: 슬리피지 (0.02% = 0.0002)
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.total_fee = fee_rate + slippage  # 0.07%

        # 상태 변수
        self.capital = initial_capital  # 현금
        self.btc_amount = 0.0  # 보유 BTC 수량
        self.weighted_entry_price = 0.0  # 가중평균 진입가
        self.total_invested = 0.0  # 누적 투자액

        # 거래 기록
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []

        # 포지션 추적
        self.positions: List[Dict] = []  # 개별 포지션 기록

    def reset(self):
        """엔진 초기화 (연도별 검증 시 사용)"""
        self.capital = self.initial_capital
        self.btc_amount = 0.0
        self.weighted_entry_price = 0.0
        self.total_invested = 0.0
        self.trades = []
        self.equity_curve = []
        self.positions = []

    def buy(self, timestamp: str, price: float, fraction: float = 1.0) -> bool:
        """
        매수 (포지션 누적 가능)

        Args:
            timestamp: 거래 시간
            price: 매수 가격
            fraction: 투자 비율 (0.0 ~ 1.0)

        Returns:
            True if 성공, False if 실패 (자본 부족 등)
        """
        # 투자 가능 금액
        invest_amount = self.capital * fraction

        if invest_amount <= 0:
            return False

        # 슬리피지 적용 (매수 시 불리하게)
        execution_price = price * (1 + self.slippage)

        # 실제 구매 BTC 수량 (수수료 차감 후)
        btc_bought = (invest_amount * (1 - self.fee_rate)) / execution_price

        # 실제 사용 금액 (수수료 + 슬리피지 포함)
        actual_cost = invest_amount  # 이미 fraction으로 제한됨

        # 자본 차감
        self.capital -= actual_cost

        # BTC 수량 증가
        prev_btc = self.btc_amount
        self.btc_amount += btc_bought

        # 가중평균 진입가 업데이트
        if prev_btc > 0:
            # 기존 포지션 + 신규 포지션의 가중평균
            total_value_before = prev_btc * self.weighted_entry_price
            new_value = btc_bought * execution_price
            self.weighted_entry_price = (total_value_before + new_value) / self.btc_amount
        else:
            self.weighted_entry_price = execution_price

        self.total_invested += actual_cost

        # 개별 포지션 기록
        position = {
            'type': 'buy',
            'timestamp': timestamp,
            'price': execution_price,
            'btc_amount': btc_bought,
            'invest_amount': actual_cost,
            'fraction': fraction,
            'total_btc_after': self.btc_amount,
            'capital_after': self.capital,
            'weighted_entry_price': self.weighted_entry_price
        }
        self.positions.append(position)

        # 거래 기록 (매수)
        trade = {
            'type': 'buy',
            'timestamp': timestamp,
            'price': execution_price,
            'btc_amount': btc_bought,
            'invest_amount': actual_cost,
            'fraction': fraction,
            'capital_after': self.capital,
            'btc_after': self.btc_amount,
            'weighted_entry': self.weighted_entry_price
        }
        self.trades.append(trade)

        return True

    def sell(self, timestamp: str, price: float, fraction: float = 1.0,
            reason: str = "Exit") -> bool:
        """
        매도 (부분 청산 가능)

        Args:
            timestamp: 거래 시간
            price: 매도 가격
            fraction: 청산 비율 (0.0 ~ 1.0, 보유 BTC 대비)
            reason: 청산 사유

        Returns:
            True if 성공, False if 실패 (포지션 없음 등)
        """
        if self.btc_amount <= 0:
            return False

        # 매도할 BTC 수량
        btc_to_sell = self.btc_amount * fraction

        # 슬리피지 적용 (매도 시 불리하게)
        execution_price = price * (1 - self.slippage)

        # 매도 대금 (수수료 차감 후)
        proceeds = btc_to_sell * execution_price * (1 - self.fee_rate)

        # 수익 계산 (가중평균 진입가 기준)
        cost_basis = btc_to_sell * self.weighted_entry_price
        profit = proceeds - cost_basis
        profit_pct = (profit / cost_basis) * 100 if cost_basis > 0 else 0.0

        # 자본 증가
        self.capital += proceeds

        # BTC 수량 감소
        self.btc_amount -= btc_to_sell
        self.total_invested -= cost_basis  # 투자액도 감소

        # 전체 청산 시 가중평균 진입가 리셋
        if self.btc_amount < 1e-10:  # 거의 0
            self.btc_amount = 0.0
            self.weighted_entry_price = 0.0
            self.total_invested = 0.0

        # 개별 포지션 기록
        position = {
            'type': 'sell',
            'timestamp': timestamp,
            'price': execution_price,
            'btc_amount': btc_to_sell,
            'proceeds': proceeds,
            'fraction': fraction,
            'profit': profit,
            'profit_pct': profit_pct,
            'reason': reason,
            'total_btc_after': self.btc_amount,
            'capital_after': self.capital,
            'weighted_entry_price': self.weighted_entry_price if self.btc_amount > 0 else 0.0
        }
        self.positions.append(position)

        # 거래 기록 (매도)
        trade = {
            'type': 'sell',
            'timestamp': timestamp,
            'price': execution_price,
            'btc_amount': btc_to_sell,
            'proceeds': proceeds,
            'profit': profit,
            'profit_pct': profit_pct,
            'fraction': fraction,
            'reason': reason,
            'capital_after': self.capital,
            'btc_after': self.btc_amount
        }
        self.trades.append(trade)

        return True

    def get_total_equity(self, current_price: float = 0.0) -> float:
        """
        현재 총 자산 (현금 + BTC 평가액)

        Args:
            current_price: 현재 BTC 가격 (0이면 cash만)

        Returns:
            총 자산
        """
        btc_value = self.btc_amount * current_price if current_price > 0 else 0.0
        return self.capital + btc_value

    def calculate_stats(self) -> Dict:
        """
        성과 통계 계산

        Returns:
            {
                'initial_capital': 10000000,
                'final_capital': 12000000,
                'total_return_pct': 20.0,
                'total_trades': 10,
                'buy_trades': 4,
                'sell_trades': 6,
                'wins': 4,
                'losses': 2,
                'win_rate': 66.7,
                'avg_profit_pct': 5.2,
                'avg_loss_pct': -2.1,
                'sharpe_ratio': 1.8,
                'max_drawdown': -8.5,
                'profit_factor': 2.5
            }
        """
        # 매도 거래만 추출
        sell_trades = [t for t in self.trades if t['type'] == 'sell']
        buy_trades = [t for t in self.trades if t['type'] == 'buy']

        # 총 수익률
        total_return_pct = ((self.capital - self.initial_capital) / self.initial_capital) * 100

        # 승/패 분리
        wins = [t for t in sell_trades if t['profit'] > 0]
        losses = [t for t in sell_trades if t['profit'] <= 0]

        win_rate = (len(wins) / len(sell_trades) * 100) if sell_trades else 0.0

        # 평균 수익/손실
        avg_profit_pct = np.mean([t['profit_pct'] for t in wins]) if wins else 0.0
        avg_loss_pct = np.mean([t['profit_pct'] for t in losses]) if losses else 0.0

        # Sharpe Ratio (간이 계산)
        if sell_trades:
            returns = [t['profit_pct'] for t in sell_trades]
            sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Max Drawdown (equity curve 기반)
        if self.equity_curve:
            equities = [e['total_equity'] for e in self.equity_curve]
            peak = equities[0]
            max_dd = 0.0
            for equity in equities:
                if equity > peak:
                    peak = equity
                dd = ((equity - peak) / peak) * 100
                if dd < max_dd:
                    max_dd = dd
        else:
            max_dd = 0.0

        # Profit Factor
        total_profit = sum(t['profit'] for t in wins)
        total_loss = abs(sum(t['profit'] for t in losses))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (float('inf') if total_profit > 0 else 0.0)

        return {
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_return_pct': total_return_pct,
            'total_trades': len(sell_trades),
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'avg_profit_pct': avg_profit_pct,
            'avg_loss_pct': avg_loss_pct,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_dd,
            'profit_factor': profit_factor if profit_factor != float('inf') else 999.99
        }

    def update_equity_curve(self, timestamp: str, current_price: float):
        """
        Equity curve 업데이트

        Args:
            timestamp: 현재 시간
            current_price: 현재 BTC 가격
        """
        btc_value = self.btc_amount * current_price
        total_equity = self.capital + btc_value

        self.equity_curve.append({
            'timestamp': timestamp,
            'cash': self.capital,
            'btc_amount': self.btc_amount,
            'btc_value': btc_value,
            'total_equity': total_equity,
            'total_return_pct': ((total_equity - self.initial_capital) / self.initial_capital) * 100
        })


if __name__ == '__main__':
    """테스트: v38 2020 시나리오 재현 (포지션 누적)"""

    print("="*70)
    print("  StandardCompoundEngine v2 테스트")
    print("  시나리오: v38 2020 (포지션 누적)")
    print("="*70)

    engine = StandardCompoundEngineV2(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002
    )

    print(f"\n초기 자본: {engine.capital:,.0f}원\n")

    # v38 2020 실제 거래 (정규화 전 400%)
    trades = [
        # 거래 1: 20% 투자
        {'action': 'buy', 'timestamp': '2020-03-12 09:00:00', 'price': 6364272.6, 'fraction': 0.20},
        {'action': 'sell', 'timestamp': '2020-03-13 09:00:00', 'price': 7265546.8, 'fraction': 1.0, 'reason': 'TP +14.16%'},

        # 거래 2: 20% 투자
        {'action': 'buy', 'timestamp': '2020-03-14 09:00:00', 'price': 6824364.6, 'fraction': 0.20},
        {'action': 'sell', 'timestamp': '2020-03-16 09:00:00', 'price': 6383722.6, 'fraction': 1.0, 'reason': 'SL -6.46%'},

        # 거래 3: 50% 투자
        {'action': 'buy', 'timestamp': '2020-07-27 09:00:00', 'price': 12918583.2, 'fraction': 0.50},
        {'action': 'sell', 'timestamp': '2020-07-31 09:00:00', 'price': 13413316.8, 'fraction': 0.40, 'reason': 'Partial TP +3.83%'},

        # 거래 4: 50% 투자
        {'action': 'buy', 'timestamp': '2020-10-21 09:00:00', 'price': 14425884.6, 'fraction': 0.50},
        {'action': 'sell', 'timestamp': '2020-12-23 09:00:00', 'price': 30330268.2, 'fraction': 1.0, 'reason': 'TP +110.11%'},
    ]

    # 거래 실행
    for i, trade in enumerate(trades, 1):
        action = trade['action']
        timestamp = trade['timestamp']
        price = trade['price']
        fraction = trade['fraction']

        if action == 'buy':
            success = engine.buy(timestamp, price, fraction)
            if success:
                print(f"[거래 {i}] 매수: {fraction:.1%} @ {price:,.0f}원")
                print(f"  → BTC: {engine.btc_amount:.8f}, 현금: {engine.capital:,.0f}원")
                print(f"  → 가중평균 진입가: {engine.weighted_entry_price:,.0f}원\n")

        elif action == 'sell':
            reason = trade.get('reason', 'Exit')
            success = engine.sell(timestamp, price, fraction, reason)
            if success:
                last_sell = engine.trades[-1]
                print(f"[거래 {i}] 매도: {fraction:.1%} @ {price:,.0f}원 ({reason})")
                print(f"  → 수익: {last_sell['profit']:+,.0f}원 ({last_sell['profit_pct']:+.2f}%)")
                print(f"  → BTC: {engine.btc_amount:.8f}, 현금: {engine.capital:,.0f}원\n")

    # 최종 통계
    stats = engine.calculate_stats()

    print("="*70)
    print("  최종 결과")
    print("="*70)
    print(f"초기 자본: {stats['initial_capital']:,.0f}원")
    print(f"최종 자본: {stats['final_capital']:,.0f}원")
    print(f"총 수익률: {stats['total_return_pct']:+.2f}%")
    print(f"\n총 거래: {stats['total_trades']}회")
    print(f"승률: {stats['win_rate']:.1f}% ({stats['wins']}승 {stats['losses']}패)")
    print(f"평균 수익: {stats['avg_profit_pct']:+.2f}%")
    print(f"평균 손실: {stats['avg_loss_pct']:+.2f}%")
    print(f"Profit Factor: {stats['profit_factor']:.2f}")
    print(f"Sharpe Ratio: {stats['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {stats['max_drawdown']:.2f}%")
    print("="*70)

    print(f"\n원본 v38 2020 수익률: 149.68%")
    print(f"v2 엔진 재현 수익률: {stats['total_return_pct']:.2f}%")
    print(f"차이: {stats['total_return_pct'] - 149.68:+.2f}%p")
