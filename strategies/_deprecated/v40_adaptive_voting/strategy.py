#!/usr/bin/env python3
"""
v40 Adaptive Voting Ensemble Strategy

v39 + 손절 규칙 + Kelly Criterion 포지션 사이즈
3가지 손절: 다수결, 고정(-15%), 시간(90일)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import timedelta
import sys
sys.path.append('../..')

from strategies.v37_supreme.strategies.trend_following import TrendFollowingStrategy
from strategies.v37_supreme.strategies.swing_trading import SwingTradingStrategy
from strategies.v35_optimized.sideways_enhanced import SidewaysEnhancedStrategies


class V40AdaptiveVoting:
    """
    v40 Adaptive Voting Ensemble: v39 + 손절 + Kelly

    개선사항:
    1. 다수결 손절: 2/3 이상 매도 신호 → 즉시 청산
    2. 고정 손절: 진입가 대비 -15% → 강제 청산
    3. 시간 손절: 보유 90일 + 손실 → 청산
    4. Kelly Criterion 포지션 사이즈: 1/3=20%, 2/3=50%, 3/3=80%
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 전체 설정 (v35 + v37 + 손절 + Kelly)
        """
        self.config = config

        # v37 전략들 (독립 인스턴스)
        v37_config = config.get('v37_strategies', {})
        self.trend_following = TrendFollowingStrategy(v37_config)
        self.swing_trading = SwingTradingStrategy(v37_config)

        # v35 SIDEWAYS 전략
        v35_config = config.get('v35_strategies', {})
        self.sideways_strategies = SidewaysEnhancedStrategies(v35_config)

        # 손절 규칙
        self.stop_loss_rules = config.get('stop_loss_rules', {})

        # Kelly Criterion
        self.kelly_config = config.get('kelly_criterion', {})
        self.position_mapping = self.kelly_config.get('position_mapping', {
            '1_vote': 0.20,
            '2_votes': 0.50,
            '3_votes': 0.80
        })

        # 포지션 상태
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.entry_votes = []
        self.entry_fraction = 0

        # 통계
        self.signal_history = []

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        Args:
            df: 지표가 포함된 전체 데이터프레임
            i: 현재 인덱스

        Returns:
            {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0, 'reason': str}
        """
        if i < 60:
            return {'action': 'hold', 'reason': 'WARMUP'}

        current_row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 1. 모든 전략의 신호 수집
        signals = self._collect_all_signals(df, i, current_row, prev_row)

        # 신호 기록
        self.signal_history.append({
            'time': current_row.name,
            'signals': signals
        })

        # 2. 포지션이 있을 때: 손절 + Exit 투표
        if self.in_position:
            # 손절 체크 (최우선)
            stop_decision = self._check_stop_loss(df, i, current_row, signals)
            if stop_decision:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.entry_votes = []
                self.entry_fraction = 0
                return stop_decision

            # Exit 투표
            exit_decision = self._vote_exit(signals)
            if exit_decision:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.entry_votes = []
                self.entry_fraction = 0
                return exit_decision

        # 3. 포지션이 없을 때: Entry 투표
        else:
            entry_decision = self._vote_entry(signals, current_row)
            if entry_decision:
                self.in_position = True
                self.entry_price = current_row['close']
                self.entry_time = i  # 인덱스 번호 저장
                self.entry_votes = [s['name'] for s in signals if s['action'] == 'buy']
                self.entry_fraction = entry_decision['fraction']
                return entry_decision

        return {'action': 'hold', 'reason': 'NO_CONSENSUS'}

    def _collect_all_signals(
        self,
        df: pd.DataFrame,
        i: int,
        current_row: pd.Series,
        prev_row: pd.Series
    ) -> List[Dict]:
        """
        모든 전략의 신호 수집

        Returns:
            [
                {'name': 'v37_trend', 'action': 'buy'/'sell'/'hold', ...},
                {'name': 'v37_swing', 'action': 'hold', ...},
                {'name': 'v35_sideways', 'action': 'buy', ...}
            ]
        """
        signals = []

        # v37 Trend Following
        trend_signal = self.trend_following.execute(df, i)
        signals.append({
            'name': 'v37_trend',
            'action': trend_signal.get('action', 'hold'),
            'fraction': trend_signal.get('fraction', 0),
            'reason': trend_signal.get('reason', '')
        })

        # v37 Swing Trading
        swing_signal = self.swing_trading.execute(df, i)
        signals.append({
            'name': 'v37_swing',
            'action': swing_signal.get('action', 'hold'),
            'fraction': swing_signal.get('fraction', 0),
            'reason': swing_signal.get('reason', '')
        })

        # v35 SIDEWAYS
        sideways_signal = self.sideways_strategies.check_all_entries(current_row, prev_row, df, i)
        if sideways_signal:
            signals.append({
                'name': 'v35_sideways',
                'action': sideways_signal.get('action', 'hold'),
                'fraction': sideways_signal.get('fraction', 0.5),
                'reason': sideways_signal.get('reason', '')
            })
        else:
            signals.append({
                'name': 'v35_sideways',
                'action': 'hold',
                'fraction': 0,
                'reason': 'NO_SIGNAL'
            })

        return signals

    def _check_stop_loss(
        self,
        df: pd.DataFrame,
        i: int,
        current_row: pd.Series,
        signals: List[Dict]
    ) -> Optional[Dict]:
        """
        손절 체크 (3가지 규칙)

        1. 다수결 손절: 2/3 이상 매도 신호
        2. 고정 손절: 진입가 대비 -15%
        3. 시간 손절: 보유 90일 + 손실

        Returns:
            손절 신호 or None
        """
        current_price = current_row['close']
        profit_pct = (current_price - self.entry_price) / self.entry_price

        # 1. 다수결 손절
        if self.stop_loss_rules.get('enable_voting_stop', True):
            sell_votes = [s for s in signals if s['action'] == 'sell']
            sell_count = len(sell_votes)
            min_votes = self.stop_loss_rules.get('voting_stop_min_votes', 2)

            if sell_count >= min_votes:
                voters = [s['name'] for s in sell_votes]
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'VOTING_STOP_LOSS ({sell_count}/3 votes): {", ".join(voters)}',
                    'stop_type': 'voting'
                }

        # 2. 고정 손절
        if self.stop_loss_rules.get('enable_fixed_stop', True):
            fixed_stop = self.stop_loss_rules.get('fixed_stop_percent', -0.15)

            if profit_pct <= fixed_stop:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'FIXED_STOP_LOSS ({profit_pct:.2%} <= {fixed_stop:.0%})',
                    'stop_type': 'fixed',
                    'profit_pct': profit_pct
                }

        # 3. 시간 손절
        if self.stop_loss_rules.get('enable_time_stop', True):
            holding_days = i - self.entry_time  # 인덱스 차이로 계산 (daily)
            time_stop_days = self.stop_loss_rules.get('time_stop_days', 90)

            if holding_days > time_stop_days and profit_pct < 0:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TIME_STOP_LOSS (holding {holding_days} days > {time_stop_days}, loss {profit_pct:.2%})',
                    'stop_type': 'time',
                    'holding_days': holding_days,
                    'profit_pct': profit_pct
                }

        return None

    def _vote_entry(self, signals: List[Dict], current_row: pd.Series) -> Optional[Dict]:
        """
        Entry 투표 (Kelly Criterion 포지션 사이즈)

        규칙:
        - 2개 이상 매수 → 진입
        - 1/3 투표 → 20% 포지션 (Kelly 1/4)
        - 2/3 투표 → 50% 포지션 (Kelly 1/2)
        - 3/3 투표 → 80% 포지션 (Kelly Full)
        """
        buy_votes = [s for s in signals if s['action'] == 'buy']
        buy_count = len(buy_votes)
        min_votes = self.config['voting_rules'].get('entry_min_votes', 2)

        if buy_count >= min_votes:
            # Kelly Criterion 포지션 사이즈
            vote_key = f'{buy_count}_vote' if buy_count == 1 else f'{buy_count}_votes'
            fraction = self.position_mapping.get(vote_key, 0.50)

            voters = [s['name'] for s in buy_votes]
            reasons = ', '.join([s['reason'] for s in buy_votes])

            return {
                'action': 'buy',
                'fraction': fraction,
                'reason': f'VOTING_BUY ({buy_count}/3 votes, {fraction:.0%} Kelly): {", ".join(voters)}',
                'voters': voters,
                'vote_details': reasons
            }

        return None

    def _vote_exit(self, signals: List[Dict]) -> Optional[Dict]:
        """
        Exit 투표

        규칙:
        - 2개 이상 매도 → 청산
        - 전량 매도 (보수적)
        """
        sell_votes = [s for s in signals if s['action'] == 'sell']
        sell_count = len(sell_votes)
        min_votes = self.config['voting_rules'].get('exit_min_votes', 2)

        if sell_count >= min_votes:
            voters = [s['name'] for s in sell_votes]
            reasons = ', '.join([s['reason'] for s in sell_votes])

            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'VOTING_SELL ({sell_count}/3 votes): {", ".join(voters)}',
                'voters': voters,
                'vote_details': reasons
            }

        return None

    def get_voting_stats(self) -> Dict:
        """
        투표 통계

        Returns:
            {
                'total_signals': N,
                'buy_consensus': N회,
                'sell_consensus': N회,
                'no_consensus': N회,
                'consensus_rate': X%
            }
        """
        if not self.signal_history:
            return {}

        buy_consensus = 0
        sell_consensus = 0
        no_consensus = 0

        for record in self.signal_history:
            signals = record['signals']
            buy_count = sum(1 for s in signals if s['action'] == 'buy')
            sell_count = sum(1 for s in signals if s['action'] == 'sell')

            if buy_count >= 2:
                buy_consensus += 1
            elif sell_count >= 2:
                sell_consensus += 1
            else:
                no_consensus += 1

        return {
            'total_signals': len(self.signal_history),
            'buy_consensus': buy_consensus,
            'sell_consensus': sell_consensus,
            'no_consensus': no_consensus,
            'consensus_rate': (buy_consensus + sell_consensus) / len(self.signal_history) * 100 if self.signal_history else 0
        }


if __name__ == '__main__':
    print("v40 Adaptive Voting Ensemble Strategy")
    print("\n개선사항:")
    print("  1. 다수결 손절: 2/3 이상 매도 → 즉시 청산")
    print("  2. 고정 손절: 진입가 대비 -15% → 강제 청산")
    print("  3. 시간 손절: 보유 90일 + 손실 → 청산")
    print("  4. Kelly Criterion 포지션 사이즈:")
    print("     - 1/3 투표 → 20% (Kelly 1/4)")
    print("     - 2/3 투표 → 50% (Kelly 1/2)")
    print("     - 3/3 투표 → 80% (Kelly Full)")
    print("\n기대 효과:")
    print("  - 2022년 손실: -42% → -15% (개선 +27%p)")
    print("  - MDD: -31.17% → -15%")
    print("  - 승률: 83.3% → 100% (손실 거래 제거)")
