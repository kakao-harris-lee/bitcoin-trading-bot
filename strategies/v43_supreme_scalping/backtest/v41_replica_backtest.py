#!/usr/bin/env python3
"""
v43 - v41 Replica Backtest
v41 Day S-Tier 1,338% 결과를 정확히 재현
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../v42_ultimate_scalping/core'))

import pandas as pd
import numpy as np
from datetime import datetime
import json

from data_loader import MultiTimeframeDataLoader
from score_engine import UnifiedScoreEngine


class V41ReplicaBacktest:
    """v41 재현 백테스트 엔진"""

    def __init__(self, config_path='../config/v41_replica_config.json'):
        with open(config_path) as f:
            self.config = json.load(f)

        # v42 엔진 사용 (데이터 로드 & 점수 계산)
        self.data_loader = MultiTimeframeDataLoader()

        # v42 config 로드 (score_engine용)
        with open('../../v42_ultimate_scalping/config/base_config.json') as f:
            self.v42_config = json.load(f)

        self.score_engine = UnifiedScoreEngine(self.v42_config)

        # 백테스트 설정
        self.initial_capital = self.config['backtest']['initial_capital']
        self.fee_rate = self.config['backtest']['fee_rate']
        self.slippage = self.config['backtest']['slippage']

        # Exit 조건
        self.take_profit = self.config['exit_conditions']['take_profit']
        self.stop_loss = self.config['exit_conditions']['stop_loss']
        self.max_hold_hours = self.config['exit_conditions']['max_hold_hours']

    def run(self, timeframe, start_date, end_date, min_score=25):
        """단일 백테스트 실행"""

        print(f"\n{'='*80}")
        print(f"v41 Replica: {timeframe} (Score >= {min_score})")
        print(f"기간: {start_date} ~ {end_date}")
        print(f"{'='*80}\n")

        # 1. 데이터 로드
        data = self.data_loader.load_all_timeframes(start_date, end_date)

        # 2. 점수 계산
        scored_data = self.score_engine.score_all_timeframes(data)

        # 3. 타임프레임 데이터
        df = scored_data.get(timeframe)
        if df is None or len(df) == 0:
            print(f"[{timeframe}] 데이터 없음")
            return None

        # 4. S-Tier, Score >= min_score 필터링
        signals = df[(df['tier'] == 'S') & (df['score'] >= min_score)].copy()

        print(f"S-Tier 시그널: {len(signals)}개 (Score >= {min_score})\n")

        # 5. 백테스팅
        trades = []
        capital = self.initial_capital
        position = 0
        buy_price = 0
        buy_time = None
        buy_idx = -1

        for idx, signal_row in signals.iterrows():
            signal_time = signal_row['timestamp']

            # 매수
            if position == 0:
                buy_price = signal_row['close']
                buy_time = signal_time
                buy_idx = df[df['timestamp'] == signal_time].index[0]

                # 전액 매수
                buy_cost = capital * (1 + self.fee_rate + self.slippage)
                position = capital / buy_cost
                capital = 0

                trades.append({
                    'type': 'buy',
                    'timestamp': str(signal_time),
                    'price': buy_price,
                    'amount': position
                })

                # 청산 시점 찾기
                sell_idx = self._find_exit(df, buy_idx, buy_price)

                if sell_idx >= 0:
                    sell_row = df.iloc[sell_idx]
                    sell_price = sell_row['close']
                    sell_time = sell_row['timestamp']

                    # 매도
                    sell_revenue = position * sell_price * (1 - self.fee_rate - self.slippage)
                    capital = sell_revenue

                    profit = (sell_price - buy_price) / buy_price
                    hold_hours = (sell_time - buy_time).total_seconds() / 3600

                    trades.append({
                        'type': 'sell',
                        'timestamp': str(sell_time),
                        'price': sell_price,
                        'amount': position,
                        'profit': profit,
                        'hold_hours': hold_hours,
                        'capital': capital
                    })

                    position = 0
                    buy_price = 0
                    buy_time = None

        # 미청산 포지션 처리
        if position > 0:
            final_row = df.iloc[-1]
            final_price = final_row['close']
            final_time = final_row['timestamp']

            sell_revenue = position * final_price * (1 - self.fee_rate - self.slippage)
            capital = sell_revenue

            profit = (final_price - buy_price) / buy_price
            hold_hours = (final_time - buy_time).total_seconds() / 3600

            trades.append({
                'type': 'sell',
                'timestamp': str(final_time),
                'price': final_price,
                'amount': position,
                'profit': profit,
                'hold_hours': hold_hours,
                'capital': capital
            })

        # 통계 계산
        stats = self._calculate_stats(trades, capital)

        return stats, trades

    def _find_exit(self, df, buy_idx, buy_price):
        """청산 시점 찾기"""

        max_idx = min(buy_idx + self.max_hold_hours, len(df) - 1)

        for i in range(buy_idx + 1, max_idx + 1):
            current_price = df.iloc[i]['close']
            current_return = (current_price - buy_price) / buy_price

            # 익절
            if current_return >= self.take_profit:
                return i

            # 손절
            if current_return <= self.stop_loss:
                return i

        # 시간 초과
        return max_idx

    def _calculate_stats(self, trades, final_capital):
        """통계 계산"""

        sell_trades = [t for t in trades if t['type'] == 'sell']

        if not sell_trades:
            return None

        wins = [t for t in sell_trades if t['profit'] > 0]
        losses = [t for t in sell_trades if t['profit'] <= 0]

        total_return = (final_capital - self.initial_capital) / self.initial_capital
        win_rate = len(wins) / len(sell_trades) if sell_trades else 0

        avg_profit = np.mean([t['profit'] for t in sell_trades])
        avg_win = np.mean([t['profit'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['profit'] for t in losses]) if losses else 0

        profit_factor = abs(sum([t['profit'] for t in wins]) / sum([t['profit'] for t in losses])) if losses else 0
        avg_hold = np.mean([t['hold_hours'] for t in sell_trades])

        # Sharpe Ratio
        returns = [t['profit'] for t in sell_trades]
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_capital,
            'total_return': total_return,
            'total_trades': len(sell_trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'avg_hold_hours': avg_hold,
            'sharpe_ratio': sharpe
        }

    def print_results(self, stats, title="결과"):
        """결과 출력"""

        if not stats:
            print("결과 없음")
            return

        print(f"\n{'='*80}")
        print(f"{title}")
        print(f"{'='*80}\n")

        print(f"초기 자본:     {stats['initial_capital']:>15,}원")
        print(f"최종 자본:     {stats['final_capital']:>15,.0f}원")
        print(f"총 수익률:     {stats['total_return']*100:>14.2f}%")
        print(f"\n총 거래:       {stats['total_trades']:>15}회")
        print(f"승/패:         {stats['wins']:>7}/{stats['losses']:<7}회")
        print(f"승률:          {stats['win_rate']*100:>14.1f}%")
        print(f"\n평균 수익:     {stats['avg_profit']*100:>14.2f}%")
        print(f"평균 익절:     {stats['avg_win']*100:>14.2f}%")
        print(f"평균 손절:     {stats['avg_loss']*100:>14.2f}%")
        print(f"Profit Factor: {stats['profit_factor']:>14.2f}")
        print(f"\n평균 보유:     {stats['avg_hold_hours']:>14.1f}시간 ({stats['avg_hold_hours']/24:.1f}일)")
        print(f"Sharpe Ratio:  {stats['sharpe_ratio']:>14.2f}\n")


def main():
    """v41 재현 테스트"""

    engine = V41ReplicaBacktest()

    # 2024년 day S-Tier (v41 재현)
    stats, trades = engine.run(
        timeframe='day',
        start_date='2024-01-01',
        end_date='2025-01-01',
        min_score=25
    )

    engine.print_results(stats, "v41 Replica - Day S-Tier (2024)")

    # 결과 저장
    if stats:
        result = {
            'config': 'v41_replica',
            'timeframe': 'day',
            'year': 2024,
            'min_score': 25,
            **stats,
            'trades': trades[:10]  # 샘플만
        }

        output_file = '../results/v41_replica_day_2024.json'
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"결과 저장: {output_file}\n")


if __name__ == '__main__':
    main()
