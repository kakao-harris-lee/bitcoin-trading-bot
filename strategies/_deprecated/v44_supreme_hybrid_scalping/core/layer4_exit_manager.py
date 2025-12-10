#!/usr/bin/env python3
"""
Layer 4: Dynamic Exit Manager
- Multi-Stage Profit Taking (분할 익절)
- Time-Based Exit (기회비용 최소화)
- Layer 1에만 적용 (Layer 2는 자체 Trailing Stop 사용)
"""

import pandas as pd
from datetime import datetime, timedelta


class Layer4ExitManager:
    """Dynamic Exit 관리"""

    def __init__(self, config):
        self.config = config['layer4_dynamic_exit']

        # Multi-Stage Profit
        self.multi_stage_enabled = self.config['multi_stage_profit']['enabled']
        self.stages = self.config['multi_stage_profit']['stages']

        # Time-Based Exit
        self.time_based_enabled = self.config['time_based_exit']['enabled']
        self.time_rules = self.config['time_based_exit']['rules']

        # 포지션별 상태 추적
        self.position_states = {}

    def check_dynamic_exit(self, position, current_price, current_time):
        """
        Dynamic Exit 조건 체크

        Args:
            position: 현재 포지션 정보
            current_price: 현재 가격
            current_time: 현재 시간

        Returns:
            exit_action dict 또는 None
            {
                'action': 'partial_exit' 또는 'full_exit',
                'ratio': 청산 비율 (0.0-1.0),
                'reason': 이유,
                'stage': 단계 (multi-stage인 경우)
            }
        """
        # Layer 1만 적용
        if position.get('layer') != 1:
            return None

        pos_id = id(position)

        # 포지션 상태 초기화
        if pos_id not in self.position_states:
            self.position_states[pos_id] = {
                'stages_executed': [],
                'remaining_ratio': 1.0
            }

        state = self.position_states[pos_id]
        buy_price = position['buy_price']
        buy_time = position['buy_time']

        # 수익률 계산
        return_pct = (current_price - buy_price) / buy_price

        # 보유 시간 계산
        if isinstance(current_time, str):
            current_time = pd.to_datetime(current_time)
        if isinstance(buy_time, str):
            buy_time = pd.to_datetime(buy_time)

        hold_hours = (current_time - buy_time).total_seconds() / 3600

        # 1. Multi-Stage Profit Taking
        if self.multi_stage_enabled:
            for i, stage in enumerate(self.stages):
                stage_num = i + 1

                # 이미 실행된 단계는 건너뛰기
                if stage_num in state['stages_executed']:
                    continue

                profit_level = stage['profit_level']
                close_ratio = stage['close_ratio']

                # 이익 수준 도달
                if return_pct >= profit_level:
                    state['stages_executed'].append(stage_num)
                    actual_close_ratio = close_ratio * state['remaining_ratio']
                    state['remaining_ratio'] -= actual_close_ratio

                    return {
                        'action': 'partial_exit',
                        'ratio': actual_close_ratio,
                        'reason': f'stage{stage_num}_profit_{return_pct*100:.2f}%',
                        'stage': stage_num,
                        'remaining': state['remaining_ratio']
                    }

        # 2. Time-Based Exit
        if self.time_based_enabled:
            for rule in self.time_rules:
                min_hold = rule['min_hold_hours']
                profit_range = rule['profit_range']
                action = rule['action']

                # 시간 조건
                if hold_hours < min_hold:
                    continue

                # 수익률 범위 조건
                profit_min, profit_max = profit_range
                if not (profit_min <= return_pct <= profit_max):
                    continue

                # 조건 만족
                if action == 'close_all':
                    return {
                        'action': 'full_exit',
                        'ratio': state['remaining_ratio'],
                        'reason': f'time_based_opportunity_cost_{hold_hours:.1f}h_{return_pct*100:.2f}%',
                        'stage': None,
                        'remaining': 0.0
                    }

        return None

    def reset_position_state(self, position):
        """포지션 청산 시 상태 초기화"""
        pos_id = id(position)
        if pos_id in self.position_states:
            del self.position_states[pos_id]

    def get_position_state(self, position):
        """포지션 상태 조회 (디버깅용)"""
        pos_id = id(position)
        return self.position_states.get(pos_id, None)
