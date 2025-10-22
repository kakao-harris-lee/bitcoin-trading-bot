#!/usr/bin/env python3
"""
표준 복리 계산 엔진
모든 전략의 재검증에 사용될 통일된 복리 계산 로직
"""

from typing import List, Dict, Optional
import pandas as pd
import numpy as np


class StandardCompoundEngine:
    """
    표준 복리 계산 엔진

    올바른 복리 계산 방식:
    - 매수: btc_amount = (capital * (1 - fee - slippage)) / price
    - 매도: capital = btc_amount * price * (1 - fee - slippage)
    - 다음 거래에서 업데이트된 capital 사용
    """

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,  # 0.05%
        slippage: float = 0.0002    # 0.02%
    ):
        """
        Args:
            initial_capital: 초기 자본 (원)
            fee_rate: 거래 수수료율
            slippage: 슬리피지율
        """
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.total_fee_rate = fee_rate + slippage

        # 거래 이력
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []

        # 현재 포지션
        self.position_btc = 0.0
        self.entry_price = 0.0
        self.entry_timestamp = None

    def reset(self):
        """상태 초기화"""
        self.capital = self.initial_capital
        self.trades = []
        self.equity_curve = []
        self.position_btc = 0.0
        self.entry_price = 0.0
        self.entry_timestamp = None

    def buy(self, timestamp: str, price: float, fraction: float = 1.0) -> Optional[Dict]:
        """
        매수 (복리 적용)

        Args:
            timestamp: 거래 시간
            price: 매수 가격
            fraction: 투자 비율 (0.0-1.0)

        Returns:
            거래 정보 or None (이미 포지션 보유 중)
        """
        if self.position_btc > 0:
            return None  # 이미 포지션 있음

        # 투자 금액
        invest_amount = self.capital * fraction

        if invest_amount <= 0:
            return None

        # ✅ 올바른 BTC 수량 계산
        btc_amount = (invest_amount * (1 - self.total_fee_rate)) / price

        # 실제 사용 금액 (수수료 포함)
        actual_cost = invest_amount

        # 자본 차감
        self.capital -= actual_cost
        self.position_btc = btc_amount
        self.entry_price = price
        self.entry_timestamp = timestamp

        trade = {
            'type': 'buy',
            'timestamp': timestamp,
            'price': price,
            'btc_amount': btc_amount,
            'capital_used': actual_cost,
            'remaining_capital': self.capital
        }

        self.trades.append(trade)

        return trade

    def sell(self, timestamp: str, price: float, reason: str = "") -> Optional[Dict]:
        """
        매도 (복리 적용)

        Args:
            timestamp: 거래 시간
            price: 매도 가격
            reason: 매도 사유

        Returns:
            거래 정보 or None (포지션 없음)
        """
        if self.position_btc <= 0:
            return None  # 포지션 없음

        # ✅ 올바른 매도 대금 계산
        proceeds = self.position_btc * price * (1 - self.total_fee_rate)

        # 수익률 계산
        profit_pct = ((price - self.entry_price) / self.entry_price) * 100

        # 보유 시간 계산
        hold_hours = 0
        if self.entry_timestamp:
            try:
                entry_dt = pd.to_datetime(self.entry_timestamp)
                exit_dt = pd.to_datetime(timestamp)
                hold_hours = (exit_dt - entry_dt).total_seconds() / 3600
            except:
                pass

        # 자본 회수
        self.capital += proceeds

        trade = {
            'type': 'sell',
            'timestamp': timestamp,
            'price': price,
            'btc_amount': self.position_btc,
            'proceeds': proceeds,
            'profit_pct': profit_pct,
            'hold_hours': hold_hours,
            'reason': reason,
            'total_capital': self.capital
        }

        self.trades.append(trade)

        # 포지션 초기화
        self.position_btc = 0.0
        self.entry_price = 0.0
        self.entry_timestamp = None

        return trade

    def get_current_equity(self, current_price: float) -> float:
        """현재 총 자산 가치"""
        position_value = self.position_btc * current_price
        return self.capital + position_value

    def calculate_stats(self) -> Dict:
        """통계 계산"""

        # 매도 거래만 추출
        sell_trades = [t for t in self.trades if t['type'] == 'sell']

        if not sell_trades:
            return {
                'total_return_pct': 0,
                'total_trades': 0,
                'win_rate': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0,
                'profit_factor': 0
            }

        # 기본 통계
        total_return_pct = ((self.capital - self.initial_capital) / self.initial_capital) * 100
        total_trades = len(sell_trades)

        # 승률
        wins = [t for t in sell_trades if t['profit_pct'] > 0]
        losses = [t for t in sell_trades if t['profit_pct'] <= 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0

        # Sharpe Ratio
        returns = [t['profit_pct'] for t in sell_trades]
        sharpe_ratio = 0
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252)

        # Max Drawdown
        equity_values = [t['total_capital'] for t in sell_trades]
        equity_values.insert(0, self.initial_capital)

        peak = equity_values[0]
        max_dd = 0
        for equity in equity_values:
            if equity > peak:
                peak = equity
            dd = ((equity - peak) / peak) * 100
            if dd < max_dd:
                max_dd = dd

        # Profit Factor
        total_profit = sum([t['profit_pct'] for t in wins]) if wins else 0
        total_loss = abs(sum([t['profit_pct'] for t in losses])) if losses else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        # 평균 통계
        avg_profit = np.mean(returns) if returns else 0
        avg_win = np.mean([t['profit_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['profit_pct'] for t in losses]) if losses else 0
        avg_hold_hours = np.mean([t['hold_hours'] for t in sell_trades]) if sell_trades else 0

        return {
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_return_pct': total_return_pct,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'wins': len(wins),
            'losses': len(losses),
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_dd,
            'profit_factor': profit_factor,
            'avg_profit_pct': avg_profit,
            'avg_win_pct': avg_win,
            'avg_loss_pct': avg_loss,
            'avg_hold_hours': avg_hold_hours
        }

    def print_trade_log(self, limit: int = 10):
        """거래 로그 출력"""
        print(f"\n{'='*80}")
        print(f"거래 로그 (최근 {limit}개)")
        print(f"{'='*80}\n")

        for i, trade in enumerate(self.trades[-limit:], 1):
            if trade['type'] == 'buy':
                print(f"{i}. [매수] {trade['timestamp']}")
                print(f"   가격: {trade['price']:,.0f}원")
                print(f"   BTC: {trade['btc_amount']:.8f}")
                print(f"   투자: {trade['capital_used']:,.0f}원")
            else:
                print(f"{i}. [매도] {trade['timestamp']}")
                print(f"   가격: {trade['price']:,.0f}원")
                print(f"   수익: {trade['profit_pct']:+.2f}%")
                print(f"   보유: {trade['hold_hours']:.1f}시간")
                print(f"   자본: {trade['total_capital']:,.0f}원")
                if trade['reason']:
                    print(f"   사유: {trade['reason']}")
            print()


def verify_buggy_v43_logic():
    """v43 버그 재현 (교육용)"""
    print("\n" + "="*80)
    print("v43 버그 재현 (고정 BTC 매수)")
    print("="*80)

    capital = 10_000_000
    fee_rate = 0.0005
    slippage = 0.0002

    # ❌ v43 잘못된 로직
    buy_cost = capital * (1 + fee_rate + slippage)
    position = capital / buy_cost

    print(f"\n초기 자본: {capital:,.0f}원")
    print(f"buy_cost = capital * (1 + fee + slippage) = {buy_cost:,.2f}원")
    print(f"position = capital / buy_cost = {position:.8f} BTC")
    print(f"\n⚠️ 문제: 자본이 1억원이 되어도 여전히 {position:.8f} BTC만 매수!")

    # ✅ 올바른 로직
    price = 50_000_000  # 비트코인 가격 5천만원
    correct_btc = (capital * (1 - fee_rate - slippage)) / price

    print(f"\n✅ 올바른 계산 (BTC 가격 {price:,.0f}원):")
    print(f"btc_amount = (capital * (1 - fee - slippage)) / price")
    print(f"btc_amount = ({capital:,.0f} * {1 - fee_rate - slippage:.6f}) / {price:,.0f}")
    print(f"btc_amount = {correct_btc:.8f} BTC")

    print(f"\n자본이 1억원으로 증가하면:")
    capital_100m = 100_000_000
    correct_btc_100m = (capital_100m * (1 - fee_rate - slippage)) / price
    print(f"btc_amount = {correct_btc_100m:.8f} BTC (10배 증가!)")


if __name__ == '__main__':
    # v43 버그 재현
    verify_buggy_v43_logic()

    # 표준 엔진 테스트
    print("\n" + "="*80)
    print("표준 복리 엔진 테스트")
    print("="*80)

    engine = StandardCompoundEngine(initial_capital=10_000_000)

    # 시나리오: 3번 거래
    trades_scenario = [
        ('2024-01-01', 50_000_000, 'buy'),   # 매수
        ('2024-01-02', 52_500_000, 'sell'),  # +5% 매도
        ('2024-01-03', 51_000_000, 'buy'),   # 재매수
        ('2024-01-04', 50_000_000, 'sell'),  # -2% 매도 (손절)
        ('2024-01-05', 49_000_000, 'buy'),   # 재매수
        ('2024-01-06', 53_900_000, 'sell'),  # +10% 매도
    ]

    for timestamp, price, action in trades_scenario:
        if action == 'buy':
            engine.buy(timestamp, price, fraction=1.0)
        else:
            engine.sell(timestamp, price, reason='시나리오 테스트')

    # 결과 출력
    engine.print_trade_log()

    stats = engine.calculate_stats()
    print(f"\n{'='*80}")
    print("통계")
    print(f"{'='*80}")
    print(f"초기 자본: {stats['initial_capital']:,.0f}원")
    print(f"최종 자본: {stats['final_capital']:,.0f}원")
    print(f"총 수익률: {stats['total_return_pct']:.2f}%")
    print(f"총 거래: {stats['total_trades']}회")
    print(f"승률: {stats['win_rate']:.1%}")
    print(f"Sharpe: {stats['sharpe_ratio']:.2f}")
    print(f"MDD: {stats['max_drawdown']:.2f}%")
