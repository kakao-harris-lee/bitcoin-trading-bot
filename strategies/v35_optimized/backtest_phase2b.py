#!/usr/bin/env python3
"""
v35 Phase 2-B Backtesting Script
AI 독립 필터 모드 검증

비교 모드:
1. Baseline (AI OFF)
2. AI Filter Mode - 완화 (권장)
3. AI Filter Mode - 엄격
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V35OptimizedStrategy
import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import Dict


class V35Backtester:
    """v35 백테스팅 엔진 (분할 익절 지원)"""

    def __init__(self, initial_capital: float, fee_rate: float = 0.0005, slippage: float = 0.0002):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.position = 0.0
        self.trades = []
        self.equity_curve = []

    def run(self, df: pd.DataFrame, strategy: V35OptimizedStrategy) -> Dict:
        """백테스팅 실행 (분할 익절 지원)"""
        self.capital = self.initial_capital
        self.position = 0.0
        self.trades = []
        self.equity_curve = []

        for i in range(30, len(df)):
            signal = strategy.execute(df, i)
            row = df.iloc[i]

            # Buy
            if signal['action'] == 'buy' and self.position == 0:
                fraction = signal.get('fraction', 0.5)
                buy_amount = self.capital * fraction
                buy_price = row['close'] * (1 + self.slippage)
                fee = buy_amount * self.fee_rate
                shares = (buy_amount - fee) / buy_price

                if shares > 0:
                    self.position = shares
                    self.capital -= buy_amount
                    self.trades.append({
                        'type': 'buy',
                        'time': row.name,
                        'price': buy_price,
                        'shares': shares,
                        'reason': signal.get('reason', 'UNKNOWN'),
                        'ai_info': {
                            'ai_filter_approved': signal.get('ai_filter_approved', False),
                            'ai_match_type': signal.get('ai_match_type', 'N/A'),
                            'ai_confidence': signal.get('ai_confidence', 0.0),
                            'ai_state': signal.get('ai_state', 'N/A')
                        }
                    })

            # Sell (분할 익절 지원)
            elif signal['action'] == 'sell' and self.position > 0:
                sell_fraction = signal.get('fraction', 1.0)
                sell_shares = self.position * sell_fraction
                sell_price = row['close'] * (1 - self.slippage)
                proceeds = sell_shares * sell_price * (1 - self.fee_rate)

                self.capital += proceeds
                self.position -= sell_shares

                self.trades.append({
                    'type': 'sell',
                    'time': row.name,
                    'price': sell_price,
                    'shares': sell_shares,
                    'fraction': sell_fraction,
                    'reason': signal.get('reason', 'UNKNOWN')
                })

            # Equity
            current_equity = self.capital + (self.position * row['close'] if self.position > 0 else 0)
            self.equity_curve.append(current_equity)

        # 마지막 포지션 정리
        if self.position > 0:
            self.capital += self.position * df.iloc[-1]['close'] * (1 - self.slippage - self.fee_rate)
            self.position = 0

        return self._calculate_metrics(df)

    def _calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """성과 지표 계산"""
        final_capital = self.capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        # 거래 분석
        buy_trades = [t for t in self.trades if t['type'] == 'buy']
        sell_trades = [t for t in self.trades if t['type'] == 'sell']

        # 승률 계산
        wins = 0
        losses = 0
        for i in range(min(len(buy_trades), len(sell_trades))):
            if sell_trades[i]['price'] > buy_trades[i]['price']:
                wins += 1
            else:
                losses += 1
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0

        # Sharpe Ratio
        if len(self.equity_curve) > 1:
            returns = pd.Series(self.equity_curve).pct_change().dropna()
            sharpe = returns.mean() / returns.std() * np.sqrt(365) if returns.std() > 0 else 0
        else:
            sharpe = 0

        # Max Drawdown
        equity = pd.Series(self.equity_curve)
        peak = equity.expanding().max()
        drawdown = (equity - peak) / peak * 100
        max_drawdown = drawdown.min()

        return {
            'total_return': total_return,
            'final_capital': final_capital,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'num_trades': len(buy_trades),
            'win_rate': win_rate,
            'wins': wins,
            'losses': losses,
            'buy_trades': buy_trades,
            'sell_trades': sell_trades
        }


def run_backtest_with_config(config_path: str, year: int = 2024):
    """설정 파일로 백테스트 실행"""
    print(f"\n{'='*70}")
    print(f"  Phase 2-B 백테스트: {config_path.split('/')[-1]}")
    print(f"{'='*70}")

    # Config 로드
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    print(f"\n[설정]")
    ai_config = config.get('ai_analyzer', {})
    print(f"  AI Enabled: {ai_config.get('enabled', False)}")
    print(f"  Test Mode: {ai_config.get('test_mode', False)}")
    print(f"  Filter Mode: {ai_config.get('filter_mode', False)}")
    print(f"  Filter Strict: {ai_config.get('filter_strict', False)}")
    print(f"  Confidence Threshold: {ai_config.get('confidence_threshold', 0.8)}")

    # 데이터 로드
    print(f"\n[데이터 로드]")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date=f'{year}-01-01', end_date=f'{year}-12-31')
    print(f"  기간: {year}")
    print(f"  캔들 수: {len(df)}")

    # 지표 추가
    print(f"\n[지표 계산]")
    df = MarketAnalyzer.add_indicators(
        df,
        indicators=['rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch']
    )
    print(f"  지표: RSI, MACD, MFI, ADX, ATR, BB, Stochastic")

    # 전략 및 백테스터 초기화
    strategy = V35OptimizedStrategy(config)
    backtester = V35Backtester(
        initial_capital=config['backtesting']['initial_capital'],
        fee_rate=config['backtesting']['fee_rate'],
        slippage=config['backtesting']['slippage']
    )

    # 백테스팅 실행
    print(f"\n[백테스팅 실행]")
    results = backtester.run(df, strategy)

    # 결과 출력
    print(f"\n[성과 지표]")
    print(f"  총 수익률: {results['total_return']:.2f}%")
    print(f"  최종 자본: {results['final_capital']:,.0f}원")
    print(f"  Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"  거래 횟수: {results['num_trades']}")
    print(f"  승률: {results['win_rate']:.1f}% ({results['wins']}승 {results['losses']}패)")

    # AI 분석 통계
    ai_summary = strategy.get_ai_analysis_summary()
    print(f"\n[AI 분석 통계]")
    print(f"  AI Enabled: {ai_summary['ai_enabled']}")
    print(f"  AI Filter Mode: {ai_summary.get('ai_filter_mode', False)}")

    if 'total_analyses' in ai_summary and ai_summary['total_analyses'] > 0:
        print(f"  총 분석: {ai_summary['total_analyses']}회")
        print(f"  평균 신뢰도: {ai_summary['avg_confidence']:.3f}")
        print(f"  고신뢰도(≥0.8) 비율: {ai_summary['high_confidence_rate']:.1%}")
        print(f"  V34-AI 일치율: {ai_summary['v34_ai_match_rate']:.1%}")

    # AI 필터 통계 (Phase 2-B)
    if 'ai_filter_stats' in ai_summary:
        filter_stats = ai_summary['ai_filter_stats']
        print(f"\n[AI 필터 통계] ⭐")
        print(f"  v35 총 BUY 신호: {filter_stats['total_v35_signals']}")
        print(f"  AI 승인: {filter_stats['ai_approved']} ({filter_stats['approval_rate']:.1%})")
        print(f"  AI 거부: {filter_stats['ai_rejected']} ({filter_stats['rejection_rate']:.1%})")

        if filter_stats['rejection_reasons']:
            print(f"\n  [거부 사유]")
            for reason, count in filter_stats['rejection_reasons'].items():
                print(f"    {reason}: {count}")

        if filter_stats['match_types']:
            print(f"\n  [매칭 타입]")
            for match_type, count in filter_stats['match_types'].items():
                print(f"    {match_type}: {count}")

    # 거래 내역 샘플
    if results['num_trades'] > 0:
        print(f"\n[거래 내역 샘플 (최근 5개)]")
        for trade in results['buy_trades'][-5:]:
            ai_info = trade.get('ai_info', {})
            print(f"  {trade['time']} | BUY | {trade['price']:,.0f}원 | {trade['reason']}")
            if ai_info.get('ai_filter_approved'):
                print(f"    └─ AI: {ai_info['ai_state']} ({ai_info['ai_confidence']:.2f}) | {ai_info['ai_match_type']}")

    return {
        'config': config_path.split('/')[-1],
        'performance': results,
        'ai_summary': ai_summary
    }


def main():
    """메인: 3가지 모드 비교"""
    print("="*70)
    print("  v35 Phase 2-B: AI Independent Filter 백테스트")
    print("="*70)
    print("\n비교 모드:")
    print("  1. Baseline (AI OFF)")
    print("  2. AI Filter - 완화 모드 (권장)")
    print("  3. AI Filter - 엄격 모드")
    print()

    year = 2024
    results_comparison = []

    # 1. Baseline (AI OFF)
    print("\n" + "="*70)
    print("  Mode 1: Baseline (AI OFF)")
    print("="*70)
    baseline_result = run_backtest_with_config(
        'config_optimized.json',
        year=year
    )
    results_comparison.append({
        'mode': 'Baseline (AI OFF)',
        **baseline_result['performance']
    })

    # 2. AI Filter - 완화 모드
    print("\n" + "="*70)
    print("  Mode 2: AI Filter - 완화 모드 (권장)")
    print("="*70)
    filter_result = run_backtest_with_config(
        'config_phase2b_filter.json',
        year=year
    )
    results_comparison.append({
        'mode': 'AI Filter - 완화',
        **filter_result['performance']
    })

    # 3. AI Filter - 엄격 모드
    print("\n" + "="*70)
    print("  Mode 3: AI Filter - 엄격 모드")
    print("="*70)
    strict_result = run_backtest_with_config(
        'config_phase2b_strict.json',
        year=year
    )
    results_comparison.append({
        'mode': 'AI Filter - 엄격',
        **strict_result['performance']
    })

    # 최종 비교표
    print("\n" + "="*70)
    print("  최종 비교 (2024)")
    print("="*70)
    print(f"\n{'모드':<25} {'수익률':>10} {'Sharpe':>8} {'MDD':>8} {'거래수':>6} {'승률':>8}")
    print("-"*70)

    baseline_return = results_comparison[0]['total_return']
    for result in results_comparison:
        mode = result['mode']
        ret = result['total_return']
        sharpe = result['sharpe_ratio']
        mdd = result['max_drawdown']
        trades = result['num_trades']
        win_rate = result['win_rate']

        # 색상 표시 (수익률 비교)
        status = ""
        if mode != 'Baseline (AI OFF)':
            if ret >= baseline_return:
                status = " ✅"
            else:
                status = f" ❌ ({ret - baseline_return:+.2f}%p)"

        print(f"{mode:<25} {ret:>9.2f}% {sharpe:>8.2f} {mdd:>7.2f}% {trades:>6} {win_rate:>7.1f}%{status}")

    # 결과 저장
    output = {
        'timestamp': datetime.now().isoformat(),
        'year': year,
        'baseline': results_comparison[0],
        'filter_relaxed': results_comparison[1],
        'filter_strict': results_comparison[2],
        'ai_summary_baseline': baseline_result['ai_summary'],
        'ai_summary_filter': filter_result['ai_summary'],
        'ai_summary_strict': strict_result['ai_summary']
    }

    output_file = f'phase2b_backtest_results_{year}.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n결과 저장: {output_file}")

    # 성공 기준 체크
    print(f"\n" + "="*70)
    print("  Phase 2-B 성공 기준 평가")
    print("="*70)

    filter_return = results_comparison[1]['total_return']
    filter_sharpe = results_comparison[1]['sharpe_ratio']
    filter_trades = results_comparison[1]['num_trades']
    filter_win_rate = results_comparison[1]['win_rate']

    criteria = [
        ('수익률 >= 28.73%', filter_return >= 28.73, f'{filter_return:.2f}%'),
        ('Sharpe >= 2.00', filter_sharpe >= 2.00, f'{filter_sharpe:.2f}'),
        ('거래 횟수 >= 10', filter_trades >= 10, f'{filter_trades}'),
        ('승률 >= 70%', filter_win_rate >= 70.0, f'{filter_win_rate:.1f}%')
    ]

    all_pass = True
    for criterion, passed, value in criteria:
        status = '✅ PASS' if passed else '❌ FAIL'
        print(f"  {criterion:<25} {status:>10} (실제: {value})")
        if not passed:
            all_pass = False

    print(f"\n{'='*70}")
    if all_pass:
        print("  🎉 Phase 2-B 성공! Active Mode 배포 가능")
    else:
        print("  ⚠️  Phase 2-B 일부 기준 미달성. 추가 튜닝 필요")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
