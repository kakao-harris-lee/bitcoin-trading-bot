#!/usr/bin/env python3
"""
v-a-11 종합 성과 분석 스크립트

Phase 1-1: 전체 연도 성과 분석 (2020-2025)
"""

import json
from pathlib import Path
from typing import Dict, List
import pandas as pd

class VA11Analyzer:
    """v-a-11 종합 분석기"""

    def __init__(self, result_file: str):
        self.result_file = Path(result_file)
        with open(self.result_file, 'r') as f:
            self.data = json.load(f)
        self.results = self.data.get('results', {})

    def analyze_yearly_performance(self) -> pd.DataFrame:
        """연도별 성과 분석"""

        yearly_data = []

        for year in sorted([k for k in self.results.keys() if k != 'overall']):
            year_result = self.results[year]

            yearly_data.append({
                'year': year,
                'total_return': year_result.get('total_return', 0),
                'buy_hold': year_result.get('buy_hold', 0),
                'excess_return': year_result.get('excess_return', 0),
                'total_trades': year_result.get('total_trades', 0),
                'win_rate': year_result.get('win_rate', 0),
                'avg_profit': year_result.get('avg_profit', 0),
                'avg_loss': year_result.get('avg_loss', 0)
            })

        return pd.DataFrame(yearly_data)

    def analyze_strategy_contribution(self) -> Dict[str, Dict]:
        """전략별 기여도 분석"""

        strategy_stats = {
            'trend_following': {'trades': 0, 'wins': 0, 'total_profit': 0, 'total_loss': 0},
            'sideways': {'trades': 0, 'wins': 0, 'total_profit': 0, 'total_loss': 0},
            'defensive': {'trades': 0, 'wins': 0, 'total_profit': 0, 'total_loss': 0},
            'swing_trading': {'trades': 0, 'wins': 0, 'total_profit': 0, 'total_loss': 0}
        }

        for year in self.results.keys():
            if year == 'overall':
                continue

            trades = self.results[year].get('trades', [])

            for trade in trades:
                strategy = trade.get('strategy', 'unknown')
                profit_pct = trade.get('profit_pct', 0)

                if strategy not in strategy_stats:
                    continue

                strategy_stats[strategy]['trades'] += 1

                if profit_pct > 0:
                    strategy_stats[strategy]['wins'] += 1
                    strategy_stats[strategy]['total_profit'] += profit_pct
                else:
                    strategy_stats[strategy]['total_loss'] += profit_pct

        # 통계 계산
        for strategy in strategy_stats:
            stats = strategy_stats[strategy]
            if stats['trades'] > 0:
                stats['win_rate'] = stats['wins'] / stats['trades'] * 100
                stats['avg_profit'] = stats['total_profit'] / stats['wins'] if stats['wins'] > 0 else 0
                stats['avg_loss'] = stats['total_loss'] / (stats['trades'] - stats['wins']) if stats['trades'] > stats['wins'] else 0

        return strategy_stats

    def analyze_market_state_performance(self) -> Dict[str, Dict]:
        """시장 상태별 성과 분석"""

        market_stats = {}

        for year in self.results.keys():
            if year == 'overall':
                continue

            trades = self.results[year].get('trades', [])

            for trade in trades:
                market_state = trade.get('market_state', 'UNKNOWN')
                profit_pct = trade.get('profit_pct', 0)

                if market_state not in market_stats:
                    market_stats[market_state] = {
                        'trades': 0, 'wins': 0,
                        'total_profit': 0, 'total_loss': 0,
                        'profits': [], 'losses': []
                    }

                market_stats[market_state]['trades'] += 1

                if profit_pct > 0:
                    market_stats[market_state]['wins'] += 1
                    market_stats[market_state]['total_profit'] += profit_pct
                    market_stats[market_state]['profits'].append(profit_pct)
                else:
                    market_stats[market_state]['total_loss'] += profit_pct
                    market_stats[market_state]['losses'].append(profit_pct)

        # 통계 계산
        for market_state in market_stats:
            stats = market_stats[market_state]
            if stats['trades'] > 0:
                stats['win_rate'] = stats['wins'] / stats['trades'] * 100
                stats['avg_profit'] = stats['total_profit'] / stats['wins'] if stats['wins'] > 0 else 0
                stats['avg_loss'] = stats['total_loss'] / (stats['trades'] - stats['wins']) if stats['trades'] > stats['wins'] else 0

        return market_stats

    def analyze_2025_performance(self) -> Dict:
        """2025년 상세 분석"""

        if '2025' not in self.results:
            return {}

        year_2025 = self.results['2025']
        trades = year_2025.get('trades', [])

        analysis = {
            'basic_stats': {
                'total_return': year_2025.get('total_return', 0),
                'buy_hold': year_2025.get('buy_hold', 0),
                'excess_return': year_2025.get('excess_return', 0),
                'total_trades': year_2025.get('total_trades', 0),
                'win_rate': year_2025.get('win_rate', 0)
            },
            'monthly_distribution': {},
            'strategy_performance': {},
            'exit_reasons': {},
            'holding_periods': []
        }

        # 월별 분포
        for trade in trades:
            entry_time = trade.get('entry_time', '')
            if entry_time:
                month = entry_time[:7]  # YYYY-MM
                if month not in analysis['monthly_distribution']:
                    analysis['monthly_distribution'][month] = {'trades': 0, 'profit': 0}
                analysis['monthly_distribution'][month]['trades'] += 1
                analysis['monthly_distribution'][month]['profit'] += trade.get('profit_pct', 0)

        # 전략별 성과
        for trade in trades:
            strategy = trade.get('strategy', 'unknown')
            if strategy not in analysis['strategy_performance']:
                analysis['strategy_performance'][strategy] = {'trades': 0, 'wins': 0, 'profit': 0}
            analysis['strategy_performance'][strategy]['trades'] += 1
            if trade.get('profit_pct', 0) > 0:
                analysis['strategy_performance'][strategy]['wins'] += 1
            analysis['strategy_performance'][strategy]['profit'] += trade.get('profit_pct', 0)

        # 청산 사유
        for trade in trades:
            reason = trade.get('exit_reason', 'unknown')
            if reason not in analysis['exit_reasons']:
                analysis['exit_reasons'][reason] = 0
            analysis['exit_reasons'][reason] += 1

        # 보유 기간
        for trade in trades:
            analysis['holding_periods'].append(trade.get('hold_days', 0))

        return analysis

    def print_comprehensive_report(self):
        """종합 보고서 출력"""

        print("=" * 80)
        print("  v-a-11 종합 성과 분석 보고서")
        print("=" * 80)

        # 1. 연도별 성과
        print("\n[1] 연도별 성과")
        print("-" * 80)
        yearly_df = self.analyze_yearly_performance()
        print(yearly_df.to_string(index=False))

        print(f"\n6년 평균 수익률: {yearly_df['total_return'].mean():.2f}%")
        print(f"평균 거래 횟수: {yearly_df['total_trades'].mean():.1f}회/년")
        print(f"평균 승률: {yearly_df['win_rate'].mean():.2f}%")

        # 2. 전략별 기여도
        print("\n[2] 전략별 기여도")
        print("-" * 80)
        strategy_contrib = self.analyze_strategy_contribution()
        for strategy, stats in sorted(strategy_contrib.items(), key=lambda x: -x[1]['trades']):
            if stats['trades'] == 0:
                continue
            print(f"\n{strategy}:")
            print(f"  거래 횟수: {stats['trades']}회")
            print(f"  승률: {stats['win_rate']:.2f}%")
            print(f"  평균 익절: {stats['avg_profit']:.2f}%")
            print(f"  평균 손절: {stats['avg_loss']:.2f}%")
            print(f"  총 기여: {stats['total_profit'] + stats['total_loss']:.2f}%p")

        # 3. 시장 상태별 성과
        print("\n[3] 시장 상태별 성과")
        print("-" * 80)
        market_perf = self.analyze_market_state_performance()
        for market_state, stats in sorted(market_perf.items(), key=lambda x: -x[1]['trades']):
            print(f"\n{market_state}:")
            print(f"  거래 횟수: {stats['trades']}회")
            print(f"  승률: {stats['win_rate']:.2f}%")
            print(f"  평균 익절: {stats['avg_profit']:.2f}%")
            print(f"  평균 손절: {stats['avg_loss']:.2f}%")

        # 4. 2025년 상세 분석
        print("\n[4] 2025년 상세 분석")
        print("-" * 80)
        analysis_2025 = self.analyze_2025_performance()

        print("\n기본 통계:")
        print(f"  수익률: {analysis_2025['basic_stats']['total_return']:.2f}%")
        print(f"  Buy&Hold: {analysis_2025['basic_stats']['buy_hold']:.2f}%")
        print(f"  초과 수익: {analysis_2025['basic_stats']['excess_return']:.2f}%p")
        print(f"  총 거래: {analysis_2025['basic_stats']['total_trades']}회")
        print(f"  승률: {analysis_2025['basic_stats']['win_rate']:.2f}%")

        print("\n월별 분포:")
        for month, stats in sorted(analysis_2025['monthly_distribution'].items()):
            print(f"  {month}: {stats['trades']}회, 수익 {stats['profit']:.2f}%")

        print("\n전략별 성과:")
        for strategy, stats in sorted(analysis_2025['strategy_performance'].items(),
                                      key=lambda x: -x[1]['trades']):
            win_rate = stats['wins'] / stats['trades'] * 100 if stats['trades'] > 0 else 0
            print(f"  {strategy}: {stats['trades']}회, 승률 {win_rate:.1f}%, "
                  f"기여 {stats['profit']:.2f}%p")

        print("\n청산 사유:")
        for reason, count in sorted(analysis_2025['exit_reasons'].items(),
                                    key=lambda x: -x[1]):
            pct = count / analysis_2025['basic_stats']['total_trades'] * 100
            print(f"  {reason}: {count}회 ({pct:.1f}%)")

        if analysis_2025['holding_periods']:
            avg_hold = sum(analysis_2025['holding_periods']) / len(analysis_2025['holding_periods'])
            print(f"\n평균 보유 기간: {avg_hold:.1f}일")

        print("\n" + "=" * 80)


def main():
    result_file = Path(__file__).parent.parent / 'results' / 'backtest_v37_style.json'

    analyzer = VA11Analyzer(str(result_file))
    analyzer.print_comprehensive_report()


if __name__ == '__main__':
    main()
