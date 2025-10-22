#!/usr/bin/env python3
"""
Compound Returns Engine - v43 복리 재투자 방식 정확히 구현
⭐ 핵심: position = current_capital × kelly (절대 initial_capital 사용 금지!)
"""

import numpy as np
from typing import Dict, Optional, List


class CompoundReturnsEngine:
    """
    복리 재투자 엔진
    - v43 성공의 핵심: 매 거래마다 current_capital 사용
    - v44 실패 원인: initial_capital 고정 사용
    """

    def __init__(self, initial_capital: float = 10_000_000, fee_rate: float = 0.0005, slippage: float = 0.0002):
        """
        Args:
            initial_capital: 초기 자본 (기록용)
            fee_rate: 거래 수수료 (0.05%)
            slippage: 슬리피지 (0.02%)
        """
        self.initial_capital = initial_capital
        self.current_capital = initial_capital  # ⭐ 복리의 핵심!
        self.fee_rate = fee_rate
        self.slippage = slippage

        # 거래 이력
        self.trade_history: List[Dict] = []
        self.active_position: Optional[Dict] = None

        # 통계
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def calculate_position_size(self, kelly: float) -> float:
        """
        포지션 크기 계산
        ⭐ 핵심: current_capital 사용 (절대 initial_capital 사용 금지!)

        Args:
            kelly: Kelly Criterion 비율 (0.0-1.0)

        Returns:
            포지션 크기 (원)
        """
        # ⭐⭐⭐ 이것이 v43 성공의 비밀!
        position_size = self.current_capital * kelly

        return position_size

    def enter_position(self, signal: Dict, kelly: float) -> Optional[Dict]:
        """
        포지션 진입

        Args:
            signal: 진입 시그널
            kelly: Kelly Criterion 비율

        Returns:
            생성된 포지션 or None (진입 실패)
        """
        if self.active_position is not None:
            return None  # 이미 포지션 있음

        # 포지션 크기 계산
        position_size = self.calculate_position_size(kelly)

        # 진입 비용 (수수료 + 슬리피지)
        total_fee = self.fee_rate + self.slippage
        entry_cost = position_size * (1 + total_fee)

        # 자본 부족 체크
        if entry_cost > self.current_capital:
            print(f"⚠️ 진입 불가: 자본 부족 (필요: {entry_cost:,.0f}, 보유: {self.current_capital:,.0f})")
            return None

        # 자본 차감
        self.current_capital -= entry_cost

        # 포지션 생성
        self.active_position = {
            'entry_price': signal['price'],
            'entry_timestamp': signal['timestamp'],
            'position_size': position_size,
            'entry_cost': entry_cost,
            'kelly': kelly,
            'score': signal.get('score', 0),
            'timeframe': signal.get('timeframe', 'unknown'),
            'signal': signal
        }

        self.total_trades += 1

        return self.active_position

    def exit_position(self, exit_price: float, exit_timestamp: str, reason: str) -> Dict:
        """
        포지션 청산

        Args:
            exit_price: 청산 가격
            exit_timestamp: 청산 시각
            reason: 청산 이유

        Returns:
            거래 결과
        """
        if self.active_position is None:
            raise ValueError("청산할 포지션 없음")

        pos = self.active_position

        # 청산 금액 계산
        price_return = exit_price / pos['entry_price']
        exit_value = pos['position_size'] * price_return

        # 수수료 차감
        total_fee = self.fee_rate + self.slippage
        net_proceeds = exit_value * (1 - total_fee)

        # ⭐ 자본 회수 (복리 누적!)
        self.current_capital += net_proceeds

        # PnL 계산
        pnl = net_proceeds - pos['entry_cost']
        return_pct = pnl / pos['entry_cost']

        # 거래 기록
        trade = {
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'entry_timestamp': pos['entry_timestamp'],
            'exit_timestamp': exit_timestamp,
            'position_size': pos['position_size'],
            'entry_cost': pos['entry_cost'],
            'exit_value': exit_value,
            'net_proceeds': net_proceeds,
            'pnl': pnl,
            'return_pct': return_pct,
            'kelly': pos['kelly'],
            'score': pos['score'],
            'timeframe': pos['timeframe'],
            'reason': reason,
            'capital_before': self.current_capital - net_proceeds,  # 진입 전 자본
            'capital_after': self.current_capital  # 청산 후 자본
        }

        self.trade_history.append(trade)

        # 통계 업데이트
        if return_pct > 0:
            self.wins += 1
        else:
            self.losses += 1

        # 포지션 초기화
        self.active_position = None

        return trade

    def has_active_position(self) -> bool:
        """활성 포지션 여부"""
        return self.active_position is not None

    def get_current_capital(self) -> float:
        """현재 자본 반환"""
        return self.current_capital

    def get_total_return_pct(self) -> float:
        """총 수익률 반환"""
        return (self.current_capital - self.initial_capital) / self.initial_capital

    def get_statistics(self) -> Dict:
        """통계 반환"""
        if not self.trade_history:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'avg_return': 0.0,
                'total_return_pct': 0.0
            }

        returns = [t['return_pct'] for t in self.trade_history]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        return {
            'initial_capital': self.initial_capital,
            'current_capital': self.current_capital,
            'total_return': self.current_capital - self.initial_capital,
            'total_return_pct': self.get_total_return_pct() * 100,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': self.wins / self.total_trades if self.total_trades > 0 else 0.0,
            'avg_return': np.mean(returns) if returns else 0.0,
            'avg_win': np.mean(wins) if wins else 0.0,
            'avg_loss': np.mean(losses) if losses else 0.0,
            'sharpe_ratio': self._calculate_sharpe(returns) if len(returns) > 1 else 0.0,
            'profit_factor': self._calculate_profit_factor(wins, losses)
        }

    def _calculate_sharpe(self, returns: List[float]) -> float:
        """Sharpe Ratio 계산"""
        if len(returns) < 2:
            return 0.0

        mean_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        # 연환산 (거래 횟수 기준)
        sharpe = (mean_return / std_return) * np.sqrt(len(returns))
        return sharpe

    def _calculate_profit_factor(self, wins: List[float], losses: List[float]) -> float:
        """Profit Factor 계산 (총 수익 / 총 손실)"""
        if not losses:
            return float('inf') if wins else 0.0

        total_profit = sum(wins) if wins else 0.0
        total_loss = abs(sum(losses))

        if total_loss == 0:
            return float('inf')

        return total_profit / total_loss

    def reset(self):
        """엔진 리셋"""
        self.current_capital = self.initial_capital
        self.trade_history = []
        self.active_position = None
        self.total_trades = 0
        self.wins = 0
        self.losses = 0


# 테스트 코드
if __name__ == "__main__":
    # v43 방식 시뮬레이션
    print("=" * 80)
    print("v43 복리 재투자 시뮬레이션")
    print("=" * 80)

    engine = CompoundReturnsEngine(initial_capital=10_000_000)

    # 121회 거래 (평균 +1.8% 수익) 시뮬레이션
    np.random.seed(42)
    for i in range(121):
        # Kelly 0.98
        kelly = 0.98

        # 진입
        signal = {
            'price': 100_000,
            'timestamp': f'2024-01-{i+1:02d}',
            'score': 45
        }
        pos = engine.enter_position(signal, kelly)

        if pos is None:
            print(f"거래 {i+1}: 진입 실패 (자본 부족)")
            break

        # 수익률 (평균 1.8%, 표준편차 5%)
        return_pct = np.random.normal(0.018, 0.05)

        # 청산 가격
        exit_price = signal['price'] * (1 + return_pct)

        # 청산
        trade = engine.exit_position(exit_price, f'2024-01-{i+2:02d}', 'test')

        # 10거래마다 출력
        if (i + 1) % 10 == 0:
            stats = engine.get_statistics()
            print(f"\n거래 {i+1}회 완료:")
            print(f"  현재 자본: {stats['current_capital']:,.0f}원")
            print(f"  총 수익률: {stats['total_return_pct']:.2f}%")
            print(f"  승률: {stats['win_rate']*100:.1f}%")

    # 최종 결과
    print("\n" + "=" * 80)
    print("최종 결과")
    print("=" * 80)

    final_stats = engine.get_statistics()
    print(f"초기 자본:  {final_stats['initial_capital']:>15,}원")
    print(f"최종 자본:  {final_stats['current_capital']:>15,.0f}원")
    print(f"총 수익률:  {final_stats['total_return_pct']:>14.2f}%")
    print(f"총 거래:    {final_stats['total_trades']:>15}회")
    print(f"승률:       {final_stats['win_rate']*100:>14.1f}%")
    print(f"Sharpe:     {final_stats['sharpe_ratio']:>14.2f}")

    print(f"\n복리 효과: {final_stats['current_capital'] / final_stats['initial_capital']:.2f}배")
