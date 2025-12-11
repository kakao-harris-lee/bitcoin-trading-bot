#!/usr/bin/env python3
"""
Dynamic Exit Manager
- 시장 상태별 동적 익절/손절
- Trailing Stop
- 분할 익절 (Multi-Stage)
- 타임아웃
"""

import pandas as pd


class DynamicExitManager:
    """동적 청산 관리자"""

    def __init__(self, config):
        self.config = config

        # 타임프레임별 기본 설정
        self.tf_settings = config.get('timeframes', {})

        # Trailing Stop 설정
        self.trailing_config = config.get('exit_strategy', {}).get('trailing_stop', {})
        self.trailing_enabled = self.trailing_config.get('enabled', True)
        self.trailing_activation = self.trailing_config.get('activation_profit', 0.03)
        self.trailing_percentage = self.trailing_config.get('trail_percentage', 0.97)

        # Multi-Stage Profit Taking
        self.multi_stage_config = config.get('exit_strategy', {}).get('multi_stage_profit', {})

    def should_exit(self, position, current_price, current_timestamp, market_state='BULL'):
        """포지션을 청산해야 하는지 판단"""

        timeframe = position['timeframe']
        entry_price = position['entry_price']
        entry_time = position['entry_timestamp']

        # 현재 수익률
        profit_pct = (current_price - entry_price) / entry_price

        # 타임프레임 설정
        tf_config = self.tf_settings.get(timeframe, {})

        # 1. Take Profit 체크
        take_profit = tf_config.get('take_profit', 0.05)

        if profit_pct >= take_profit:
            return True, 'TAKE_PROFIT', 1.0  # 전량 청산

        # 2. Stop Loss 체크
        stop_loss = tf_config.get('stop_loss', -0.02)

        if profit_pct <= stop_loss:
            return True, 'STOP_LOSS', 1.0

        # 3. Trailing Stop 체크 (수익 중일 때만)
        if self.trailing_enabled and profit_pct >= self.trailing_activation:
            peak_price = position.get('peak_price', entry_price)

            # 고점 대비 하락률
            drawdown_from_peak = (current_price - peak_price) / peak_price

            # Trailing Stop 발동 (고점 대비 3% 하락)
            if drawdown_from_peak <= -(1 - self.trailing_percentage):
                return True, 'TRAILING_STOP', 1.0

        # 4. Multi-Stage Profit Taking
        stages = self.multi_stage_config.get(timeframe, [])
        partial_exit_ratio = self._check_multi_stage(position, profit_pct, stages)

        if partial_exit_ratio > 0:
            return True, 'PARTIAL_PROFIT', partial_exit_ratio

        # 5. Timeout 체크
        max_hold_hours = tf_config.get('max_hold_hours', 72)
        hold_hours = (current_timestamp - entry_time).total_seconds() / 3600

        if hold_hours >= max_hold_hours:
            return True, 'TIMEOUT', 1.0

        # 6. 시장 상태 변화 (BEAR로 전환 시 즉시 청산)
        if market_state == 'BEAR' and profit_pct > -0.01:  # 손실이 -1% 이내면 바로 청산
            return True, 'MARKET_BEAR', 1.0

        # 청산 안 함
        return False, None, 0.0

    def _check_multi_stage(self, position, current_profit_pct, stages):
        """Multi-Stage Profit Taking 체크"""

        if not stages:
            return 0.0

        # 이미 청산된 비율 추적
        closed_ratio = position.get('closed_ratio', 0.0)

        for stage in stages:
            level = stage['level']
            close_ratio = stage['close_ratio']

            # 목표 도달 & 아직 청산 안 됨
            if current_profit_pct >= level and closed_ratio < close_ratio:
                # 이번에 청산할 비율
                exit_ratio = close_ratio - closed_ratio

                # 포지션에 기록
                position['closed_ratio'] = close_ratio

                return exit_ratio

        return 0.0

    def adjust_exit_by_tier(self, position, base_tp, base_sl):
        """Tier에 따라 익절/손절 조정"""

        tier = position.get('tier', 'B')

        # S-Tier: 익절 넓게, 손절 좁게 (큰 수익 노림)
        if tier == 'S':
            tp_multiplier = 2.0   # TP 2배
            sl_multiplier = 0.8   # SL 0.8배 (좁게)

        # A-Tier: 익절 넓게, 손절 보통
        elif tier == 'A':
            tp_multiplier = 1.5
            sl_multiplier = 1.0

        # B-Tier: 기본값
        elif tier == 'B':
            tp_multiplier = 1.0
            sl_multiplier = 1.0

        else:
            tp_multiplier = 1.0
            sl_multiplier = 1.2  # C-Tier는 빨리 손절

        adjusted_tp = base_tp * tp_multiplier
        adjusted_sl = base_sl * sl_multiplier

        return adjusted_tp, adjusted_sl

    def adjust_exit_by_market(self, market_state, base_tp, base_sl):
        """시장 상태에 따라 익절/손절 조정"""

        # BULL_STRONG: 익절 넓게, 큰 수익 노림
        if market_state == 'BULL_STRONG':
            return base_tp * 2.0, base_sl * 0.9

        # BULL_MODERATE: 익절 약간 넓게
        elif market_state == 'BULL_MODERATE':
            return base_tp * 1.5, base_sl * 1.0

        # SIDEWAYS: 기본값
        elif 'SIDEWAYS' in market_state:
            return base_tp * 1.0, base_sl * 1.0

        # BEAR: 익절 좁게, 빨리 청산
        elif 'BEAR' in market_state:
            return base_tp * 0.7, base_sl * 1.2

        else:
            return base_tp, base_sl

    def get_optimal_exit_params(self, position, market_state):
        """Tier + 시장 상태를 결합한 최적 익절/손절 계산"""

        timeframe = position['timeframe']
        tf_config = self.tf_settings.get(timeframe, {})

        # 기본값
        base_tp = tf_config.get('take_profit', 0.05)
        base_sl = tf_config.get('stop_loss', -0.02)

        # Tier 조정
        tp_tier, sl_tier = self.adjust_exit_by_tier(position, base_tp, base_sl)

        # 시장 상태 조정
        tp_final, sl_final = self.adjust_exit_by_market(market_state, tp_tier, sl_tier)

        return tp_final, sl_final


def test_exit_manager():
    """Exit Manager 테스트"""
    import json
    from datetime import datetime, timedelta

    # Config 로드
    with open('../config/base_config.json') as f:
        config = json.load(f)

    # Exit Manager 생성
    em = DynamicExitManager(config)

    print(f"{'='*70}")
    print(f"Dynamic Exit Manager 테스트")
    print(f"{'='*70}\n")

    # 테스트 포지션
    base_time = datetime(2024, 1, 1, 9, 0)
    base_price = 60000000

    position = {
        'entry_timestamp': base_time,
        'entry_price': base_price,
        'quantity': 0.1,
        'tier': 'S',
        'timeframe': 'minute15',
        'peak_price': base_price
    }

    # 시나리오 1: 익절
    print("시나리오 1: +5% 상승 (익절)")
    current_price = base_price * 1.05
    current_time = base_time + timedelta(hours=3)

    should_exit, reason, ratio = em.should_exit(
        position, current_price, current_time, 'BULL'
    )

    print(f"  - 청산 여부: {should_exit}")
    print(f"  - 사유: {reason}")
    print(f"  - 비율: {ratio * 100:.0f}%\n")

    # 시나리오 2: 손절
    print("시나리오 2: -2% 하락 (손절)")
    position2 = position.copy()
    position2['peak_price'] = base_price

    current_price = base_price * 0.98
    current_time = base_time + timedelta(hours=2)

    should_exit, reason, ratio = em.should_exit(
        position2, current_price, current_time, 'BULL'
    )

    print(f"  - 청산 여부: {should_exit}")
    print(f"  - 사유: {reason}")
    print(f"  - 비율: {ratio * 100:.0f}%\n")

    # 시나리오 3: Trailing Stop
    print("시나리오 3: +8% 상승 후 -3% 하락 (Trailing Stop)")
    position3 = position.copy()
    position3['peak_price'] = base_price * 1.08

    current_price = base_price * 1.08 * 0.97  # 고점 대비 -3%
    current_time = base_time + timedelta(hours=5)

    should_exit, reason, ratio = em.should_exit(
        position3, current_price, current_time, 'BULL'
    )

    print(f"  - 청산 여부: {should_exit}")
    print(f"  - 사유: {reason}")
    print(f"  - 비율: {ratio * 100:.0f}%\n")

    # Tier/시장 상태별 조정 테스트
    print("\n" + "="*70)
    print("Tier/시장 상태별 익절/손절 조정")
    print("="*70 + "\n")

    test_cases = [
        ('S', 'BULL_STRONG'),
        ('A', 'BULL_MODERATE'),
        ('B', 'SIDEWAYS_FLAT'),
        ('C', 'BEAR_MODERATE')
    ]

    for tier, market in test_cases:
        pos = {'tier': tier, 'timeframe': 'minute15'}
        tp, sl = em.get_optimal_exit_params(pos, market)

        print(f"Tier {tier} + {market}:")
        print(f"  - TP: {tp*100:>5.1f}%")
        print(f"  - SL: {sl*100:>5.1f}%\n")


if __name__ == '__main__':
    test_exit_manager()
