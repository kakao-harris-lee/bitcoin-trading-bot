#!/usr/bin/env python3
"""
v43 Compound Engine (정확한 복제)
- position = capital / (capital × (1+fee)) = 1/(1+fee)
- sell_revenue = position × sell_price × (1-fee)
- 매수가는 사용하지 않음!
"""

from typing import Dict, Optional, List


class V43CompoundEngine:
    """
    v43 복리 엔진 (정확한 복제)

    핵심 메커니즘:
    - position = 1 / (1 + fee) (상수!)
    - sell_revenue = position × sell_price × (1 - fee)
    - 매수가는 무시, 매도가만 사용
    """

    def __init__(self, initial_capital: float, fee_rate: float, slippage: float):
        """
        Args:
            initial_capital: 초기 자본
            fee_rate: 수수료율 (0.0005 = 0.05%)
            slippage: 슬리피지 (0.0002 = 0.02%)
        """
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

        # v43 핵심: position은 상수!
        total_fee = fee_rate + slippage
        self.position_multiplier = 1.0 / (1.0 + total_fee)  # 0.9993

        # 활성 포지션
        self.active_position = None

        # 통계
        self.trade_history = []
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def enter_position(self, signal: Dict) -> Optional[Dict]:
        """
        포지션 진입 (v43 방식)

        Args:
            signal: 진입 시그널 (price, timestamp, score 등)

        Returns:
            포지션 정보 dict
        """
        if self.active_position is not None:
            return None  # 이미 포지션 있음

        # v43: position = 1 / (1 + fee) (상수!)
        position = self.position_multiplier

        # 포지션 생성
        self.active_position = {
            'entry_price': signal['price'],
            'entry_timestamp': signal['timestamp'],
            'position': position,  # v43의 position (0.9993)
            'score': signal.get('score', 0),
            'timeframe': signal.get('timeframe', 'unknown'),
            'signal': signal,
            'capital_at_entry': self.current_capital
        }

        # v43: capital = 0 (전액 투입)
        # 하지만 우리는 tracking을 위해 유지

        self.total_trades += 1

        return self.active_position

    def exit_position(self, exit_price: float, exit_timestamp: str, reason: str) -> Dict:
        """
        포지션 청산 (v43 방식)

        Args:
            exit_price: 청산 가격
            exit_timestamp: 청산 시간
            reason: 청산 사유

        Returns:
            거래 기록 dict
        """
        if self.active_position is None:
            raise ValueError("활성 포지션이 없습니다!")

        pos = self.active_position

        # v43 핵심: sell_revenue = position × sell_price × (1-fee)
        total_fee = self.fee_rate + self.slippage
        sell_revenue = pos['position'] * exit_price * (1 - total_fee)

        # 자본 업데이트
        capital_before = self.current_capital
        self.current_capital = sell_revenue

        # 수익률 계산
        return_pct = (exit_price - pos['entry_price']) / pos['entry_price']
        capital_return = (self.current_capital - capital_before) / capital_before

        # 거래 기록
        trade = {
            'entry_price': pos['entry_price'],
            'entry_timestamp': pos['entry_timestamp'],
            'exit_price': exit_price,
            'exit_timestamp': exit_timestamp,
            'position': pos['position'],
            'sell_revenue': sell_revenue,
            'return_pct': return_pct,  # 가격 변동률
            'capital_return': capital_return,  # 자본 변동률
            'score': pos['score'],
            'timeframe': pos['timeframe'],
            'reason': reason,
            'capital_before': capital_before,
            'capital_after': self.current_capital
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
        """현재 자본"""
        return self.current_capital

    def get_total_return_pct(self) -> float:
        """총 수익률 (백분율)"""
        return (self.current_capital - self.initial_capital) / self.initial_capital

    def get_stats(self) -> Dict:
        """통계"""
        total_return = self.get_total_return_pct()

        return {
            'initial_capital': self.initial_capital,
            'current_capital': self.current_capital,
            'total_return_pct': total_return,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': self.wins / self.total_trades if self.total_trades > 0 else 0
        }


# 테스트 코드
if __name__ == "__main__":
    print("=" * 80)
    print("v43 Compound Engine 테스트")
    print("=" * 80)

    # 엔진 초기화
    engine = V43CompoundEngine(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002
    )

    print(f"\n초기 자본: {engine.get_current_capital():,.0f}원")
    print(f"Position 승수: {engine.position_multiplier:.10f}")
    print()

    # 실제 v43 첫 거래 재현
    print("=== 실제 v43 첫 거래 재현 ===")

    # 진입
    signal = {
        'price': 71_755_000,
        'timestamp': '2024-02-19 09:00:00',
        'score': 40
    }

    pos = engine.enter_position(signal)
    print(f"진입: {signal['timestamp']}")
    print(f"  가격: {signal['price']:,}원")
    print(f"  position: {pos['position']:.10f}")
    print()

    # 청산
    trade = engine.exit_position(
        exit_price=78_619_000,
        exit_timestamp='2024-02-27 09:00:00',
        reason='take_profit'
    )

    print(f"청산: {trade['exit_timestamp']}")
    print(f"  가격: {trade['exit_price']:,}원")
    print(f"  자본: {trade['capital_after']:,.2f}원")
    print(f"  수익률: {trade['return_pct']*100:+.2f}%")
    print()

    print(f"v43 실제 결과: 78,509,010.39원")
    print(f"재현 결과:     {trade['capital_after']:,.2f}원")
    print(f"차이:          {78_509_010.39 - trade['capital_after']:,.2f}원")

    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)
