#!/usr/bin/env python3
"""
v39 Voting Ensemble Strategy

Meta Classifier 없이 순수 투표 방식
v35 + v37 전략들이 독립적으로 신호 생성 → 다수결로 진입/청산
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import sys
sys.path.append('../..')

from strategies.v37_supreme.strategies.trend_following import TrendFollowingStrategy
from strategies.v37_supreme.strategies.swing_trading import SwingTradingStrategy
from strategies.v35_optimized.sideways_enhanced import SidewaysEnhancedStrategies


class V39VotingEnsemble:
    """
    v39 Voting Ensemble: 순수 투표 방식 앙상블

    원리:
    1. 모든 전략이 독립적으로 매수/매도 신호 생성
    2. 2개 이상 일치 시 진입/청산
    3. 투표 비율에 따라 포지션 사이즈 조절
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 전체 설정 (v35 + v37 파라미터)
        """
        self.config = config

        # v37 전략들 (독립 인스턴스)
        v37_config = config.get('v37_strategies', {})
        self.trend_following = TrendFollowingStrategy(v37_config)
        self.swing_trading = SwingTradingStrategy(v37_config)

        # v35 SIDEWAYS 전략
        v35_config = config.get('v35_strategies', {})
        self.sideways_strategies = SidewaysEnhancedStrategies(v35_config)

        # 포지션 상태
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.entry_votes = []  # 진입 시 어떤 전략들이 찬성했는지

        # 통계
        self.signal_history = []  # 매 캔들마다 각 전략의 신호 기록

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

        # 2. 포지션이 있을 때: Exit 투표
        if self.in_position:
            exit_decision = self._vote_exit(signals)
            if exit_decision:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.entry_votes = []
                return exit_decision

        # 3. 포지션이 없을 때: Entry 투표
        else:
            entry_decision = self._vote_entry(signals, current_row)
            if entry_decision:
                self.in_position = True
                self.entry_price = current_row['close']
                self.entry_time = current_row.name
                self.entry_votes = [s['name'] for s in signals if s['action'] == 'buy']
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
                {'name': 'v37_trend', 'action': 'buy'/'sell'/'hold', 'fraction': 0.8, ...},
                {'name': 'v37_swing', 'action': 'hold', ...},
                {'name': 'v35_sideways', 'action': 'buy', 'fraction': 0.5, ...}
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

    def _vote_entry(self, signals: List[Dict], current_row: pd.Series) -> Optional[Dict]:
        """
        Entry 투표

        규칙:
        - 2개 이상 매수 → 진입
        - 3개 만장일치 → 100% 포지션
        - 2개 일치 → 66% 포지션
        """
        buy_votes = [s for s in signals if s['action'] == 'buy']
        buy_count = len(buy_votes)

        if buy_count >= 2:
            # 포지션 사이즈 = 투표 비율
            fraction = buy_count / 3.0  # 2/3 = 0.66, 3/3 = 1.0

            voters = [s['name'] for s in buy_votes]
            reasons = ', '.join([s['reason'] for s in buy_votes])

            return {
                'action': 'buy',
                'fraction': fraction,
                'reason': f'VOTING_BUY ({buy_count}/3 votes): {", ".join(voters)}',
                'voters': voters,
                'vote_details': reasons
            }

        return None

    def _vote_exit(self, signals: List[Dict]) -> Optional[Dict]:
        """
        Exit 투표

        규칙:
        - 2개 이상 매도 → 청산
        - 3개 만장일치 → 전량 매도
        - 2개 일치 → 전량 매도 (보수적)
        """
        sell_votes = [s for s in signals if s['action'] == 'sell']
        sell_count = len(sell_votes)

        if sell_count >= 2:
            voters = [s['name'] for s in sell_votes]
            reasons = ', '.join([s['reason'] for s in sell_votes])

            return {
                'action': 'sell',
                'fraction': 1.0,  # 항상 전량 매도
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
                'strategy_agreement_rate': {...}
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
    print("v39 Voting Ensemble Strategy")
    print("\n투표 방식:")
    print("  Entry: 2/3 이상 매수 → 진입 (fraction = votes/3)")
    print("  Exit: 2/3 이상 매도 → 전량 청산")
    print("\n장점:")
    print("  - Meta Classifier 오류 회피")
    print("  - 전략 간 독립성 보장")
    print("  - 다수결로 안정성 확보")
