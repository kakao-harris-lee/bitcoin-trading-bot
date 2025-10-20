#!/usr/bin/env python3
"""
Position Manager
- Kelly Criterion Position Sizing
- Tier별 차등 포지션
- 최대 레버리지 관리
- 리스크 관리
"""

import numpy as np
import pandas as pd


class PositionManager:
    """포지션 관리자"""

    def __init__(self, config, initial_capital=10000000):
        self.config = config
        self.initial_capital = initial_capital
        self.current_capital = initial_capital

        # Kelly Criterion 설정
        self.kelly_enabled = config.get('kelly_criterion', {}).get('enabled', True)
        self.kelly_max = config.get('kelly_criterion', {}).get('max_fraction', 0.5)
        self.kelly_min = config.get('kelly_criterion', {}).get('min_fraction', 0.1)
        self.kelly_lookback = config.get('kelly_criterion', {}).get('lookback_trades', 50)

        # Tier별 기본 포지션 크기
        self.tier_position_sizes = {
            'S': config.get('tiers', {}).get('S', {}).get('position_size', 1.0),
            'A': config.get('tiers', {}).get('A', {}).get('position_size', 0.5),
            'B': config.get('tiers', {}).get('B', {}).get('position_size', 0.25),
            'C': config.get('tiers', {}).get('C', {}).get('position_size', 0.0)
        }

        # 최대 설정
        self.max_positions = config.get('trading', {}).get('max_positions', 3)
        self.max_daily_loss = config.get('trading', {}).get('max_daily_loss', 0.05)

        # 거래 기록
        self.trade_history = []
        self.open_positions = []

        # 일일 손실 추적
        self.daily_pnl = {}

    def calculate_kelly_fraction(self):
        """Kelly Criterion을 이용한 최적 포지션 크기 계산"""

        if not self.kelly_enabled or len(self.trade_history) < 10:
            return self.kelly_max

        # 최근 N개 거래
        recent_trades = self.trade_history[-self.kelly_lookback:]

        # 승률 계산
        wins = [t for t in recent_trades if t['pnl'] > 0]
        win_rate = len(wins) / len(recent_trades) if recent_trades else 0.5

        # 평균 승리/손실 비율
        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0.02
        avg_loss = abs(np.mean([t['pnl_pct'] for t in recent_trades if t['pnl'] < 0])) if len(recent_trades) > len(wins) else 0.01

        # Kelly Fraction = (Win_Rate * Avg_Win - (1 - Win_Rate) * Avg_Loss) / Avg_Win
        if avg_win > 0:
            kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        else:
            kelly = 0.25

        # 클램핑
        kelly = max(self.kelly_min, min(kelly, self.kelly_max))

        return kelly

    def calculate_position_size(self, tier, timeframe, kelly_fraction=None):
        """Tier와 Kelly Criterion을 결합한 포지션 크기 계산"""

        # Tier 기본 크기
        base_size = self.tier_position_sizes.get(tier, 0.0)

        if base_size == 0:
            return 0

        # Kelly Fraction
        if kelly_fraction is None:
            kelly_fraction = self.calculate_kelly_fraction()

        # 최종 포지션 크기
        position_size = base_size * kelly_fraction

        # 타임프레임별 조정 (단타는 작게, 스윙은 크게)
        tf_multiplier = {
            'minute5': 0.5,
            'minute15': 0.7,
            'minute60': 1.0,
            'minute240': 1.2,
            'day': 1.5
        }.get(timeframe, 1.0)

        position_size *= tf_multiplier

        # 최종 클램핑
        position_size = min(position_size, 1.0)

        return position_size

    def can_open_position(self, date=None):
        """새 포지션을 열 수 있는지 확인"""

        # 1. 최대 포지션 수 확인
        if len(self.open_positions) >= self.max_positions:
            return False, "MAX_POSITIONS_REACHED"

        # 2. 일일 손실 한도 확인
        if date:
            date_str = date.date() if hasattr(date, 'date') else date
            daily_loss = self.daily_pnl.get(date_str, 0)

            if daily_loss <= -self.max_daily_loss * self.current_capital:
                return False, "DAILY_LOSS_LIMIT"

        # 3. 자본금 확인
        if self.current_capital <= self.initial_capital * 0.5:
            return False, "LOW_CAPITAL"

        return True, "OK"

    def open_position(self, timestamp, price, tier, timeframe, score, signals):
        """포지션 진입"""

        can_open, reason = self.can_open_position(timestamp)

        if not can_open:
            return None, reason

        # 포지션 크기 계산
        position_size = self.calculate_position_size(tier, timeframe)

        if position_size == 0:
            return None, "ZERO_POSITION_SIZE"

        # 투입 자본 (available capital 기준)
        # 이미 열린 포지션에 묶인 자본 제외
        locked_capital = sum([p['capital_allocated'] for p in self.open_positions])
        available_capital = self.current_capital - locked_capital

        if available_capital <= 0:
            return None, "NO_AVAILABLE_CAPITAL"

        capital_allocated = available_capital * position_size

        # 최소 투입 금액 체크 (100만원 미만이면 진입 안 함)
        if capital_allocated < 1000000:
            return None, "INSUFFICIENT_CAPITAL"

        # 수수료
        fee_rate = self.config.get('trading', {}).get('fee_rate', 0.0005)
        fee = capital_allocated * fee_rate

        # 실제 매수 금액
        buy_amount = capital_allocated - fee

        # 매수 수량
        quantity = buy_amount / price

        # 포지션 생성
        position = {
            'entry_timestamp': timestamp,
            'entry_price': price,
            'quantity': quantity,
            'capital_allocated': capital_allocated,
            'entry_fee': fee,
            'tier': tier,
            'timeframe': timeframe,
            'score': score,
            'signals': signals,
            'peak_price': price,
            'status': 'OPEN'
        }

        self.open_positions.append(position)

        # 자본금은 차감하지 않음 (locked_capital로 관리)
        # self.current_capital -= capital_allocated

        return position, "OPENED"

    def close_position(self, position, timestamp, price, reason='MANUAL'):
        """포지션 청산"""

        # 수수료
        fee_rate = self.config.get('trading', {}).get('fee_rate', 0.0005)
        slippage = self.config.get('trading', {}).get('slippage', 0.0002)

        # 실제 매도 가격 (슬리피지 고려)
        actual_price = price * (1 - slippage)

        # 매도 금액
        sell_amount = position['quantity'] * actual_price
        sell_fee = sell_amount * fee_rate

        # 순 매도 금액
        net_sell = sell_amount - sell_fee

        # 손익 계산
        pnl = net_sell - position['capital_allocated']
        pnl_pct = pnl / position['capital_allocated']

        # 보유 시간
        hold_hours = (timestamp - position['entry_timestamp']).total_seconds() / 3600

        # 포지션 업데이트
        position['exit_timestamp'] = timestamp
        position['exit_price'] = price
        position['actual_exit_price'] = actual_price
        position['exit_fee'] = sell_fee
        position['pnl'] = pnl
        position['pnl_pct'] = pnl_pct
        position['hold_hours'] = hold_hours
        position['exit_reason'] = reason
        position['status'] = 'CLOSED'

        # 자본금 업데이트 (원금 반환 + 손익)
        self.current_capital += pnl

        # 거래 기록에 추가
        self.trade_history.append(position)

        # open_positions에서 제거
        if position in self.open_positions:
            self.open_positions.remove(position)

        # 일일 손익 업데이트
        date_str = timestamp.date() if hasattr(timestamp, 'date') else timestamp
        if date_str not in self.daily_pnl:
            self.daily_pnl[date_str] = 0
        self.daily_pnl[date_str] += pnl

        return position

    def update_peak_price(self, position, current_price):
        """포지션의 최고가 업데이트 (Trailing Stop용)"""
        if current_price > position['peak_price']:
            position['peak_price'] = current_price

    def get_statistics(self):
        """거래 통계"""

        if not self.trade_history:
            return {}

        trades = pd.DataFrame(self.trade_history)

        total_trades = len(trades)
        wins = trades[trades['pnl'] > 0]
        losses = trades[trades['pnl'] <= 0]

        win_rate = len(wins) / total_trades if total_trades > 0 else 0

        total_pnl = trades['pnl'].sum()
        total_return = (self.current_capital - self.initial_capital) / self.initial_capital

        avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl_pct'].mean() if len(losses) > 0 else 0

        profit_factor = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else 0

        avg_hold = trades['hold_hours'].mean()

        stats = {
            'initial_capital': self.initial_capital,
            'current_capital': self.current_capital,
            'total_return': total_return,
            'total_trades': total_trades,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'avg_hold_hours': avg_hold
        }

        return stats


def test_position_manager():
    """Position Manager 테스트"""
    import json
    from datetime import datetime, timedelta

    # Config 로드
    with open('../config/base_config.json') as f:
        config = json.load(f)

    # Position Manager 생성
    pm = PositionManager(config, initial_capital=10000000)

    print(f"{'='*70}")
    print(f"Position Manager 테스트")
    print(f"{'='*70}\n")

    # 테스트 거래 시뮬레이션
    base_time = datetime(2024, 1, 1, 9, 0)
    base_price = 60000000

    # 거래 1: S-Tier, 익절
    pos1, reason = pm.open_position(
        timestamp=base_time,
        price=base_price,
        tier='S',
        timeframe='minute15',
        score=45,
        signals=['MFI_BULLISH', 'LOCAL_MIN']
    )

    if pos1:
        print(f"✅ 포지션 1 진입: {pos1['capital_allocated']:,.0f}원 투입")

        # 5% 상승 후 익절
        exit_time = base_time + timedelta(hours=6)
        exit_price = base_price * 1.05

        closed1 = pm.close_position(pos1, exit_time, exit_price, 'TAKE_PROFIT')
        print(f"✅ 포지션 1 청산: {closed1['pnl_pct']*100:.2f}% (PnL: {closed1['pnl']:,.0f}원)\n")

    # 거래 2: A-Tier, 손절
    pos2, reason = pm.open_position(
        timestamp=base_time + timedelta(days=1),
        price=base_price * 1.05,
        tier='A',
        timeframe='minute60',
        score=30,
        signals=['LOW_VOL']
    )

    if pos2:
        print(f"✅ 포지션 2 진입: {pos2['capital_allocated']:,.0f}원 투입")

        # 2% 하락 후 손절
        exit_time = base_time + timedelta(days=1, hours=12)
        exit_price = base_price * 1.05 * 0.98

        closed2 = pm.close_position(pos2, exit_time, exit_price, 'STOP_LOSS')
        print(f"✅ 포지션 2 청산: {closed2['pnl_pct']*100:.2f}% (PnL: {closed2['pnl']:,.0f}원)\n")

    # 통계 출력
    stats = pm.get_statistics()

    print(f"\n{'='*70}")
    print(f"거래 통계")
    print(f"{'='*70}\n")

    print(f"초기 자본: {stats['initial_capital']:,.0f}원")
    print(f"현재 자본: {stats['current_capital']:,.0f}원")
    print(f"총 수익률: {stats['total_return']*100:.2f}%")
    print(f"총 거래: {stats['total_trades']}회")
    print(f"승률: {stats['win_rate']*100:.1f}%")
    print(f"평균 익절: {stats['avg_win']*100:.2f}%")
    print(f"평균 손절: {stats['avg_loss']*100:.2f}%")
    print(f"Profit Factor: {stats['profit_factor']:.2f}")
    print(f"평균 보유: {stats['avg_hold_hours']:.1f}시간")


if __name__ == '__main__':
    test_position_manager()
