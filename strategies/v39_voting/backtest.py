#!/usr/bin/env python3
"""
v39 Voting Ensemble - Backtest Script

2020-2025 전체 기간 백테스팅
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.backtester import Backtester
from core.evaluator import Evaluator

from strategies.v39_voting.strategy import V39VotingEnsemble


def run_yearly_backtest(year: int, config: dict, db_path='../../upbit_bitcoin.db'):
    """
    연도별 백테스팅

    Args:
        year: 백테스트 연도
        config: 전략 설정
        db_path: DB 경로

    Returns:
        결과 딕셔너리
    """
    print(f"\n{'='*70}")
    print(f"  {year}년 백테스팅")
    print(f"{'='*70}")

    # 데이터 로드
    with DataLoader(db_path) as loader:
        df = loader.load_timeframe('day', start_date=f"{year}-01-01", end_date=f"{year}-12-31")

    if df is None or len(df) == 0:
        print(f"  ❌ {year}년 데이터 없음")
        return None

    print(f"  기간: 0 ~ {len(df)-1}")
    print(f"  캔들: {len(df)}개")
    print(f"  시작가: {df.iloc[0]['close']:,.0f}원")
    print(f"  종료가: {df.iloc[-1]['close']:,.0f}원")

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'bb', 'adx', 'mfi', 'stoch', 'volume_sma'])

    # 전략 설정
    strategy = V39VotingEnsemble(config)

    # Backtester 래퍼 함수
    def strategy_wrapper(df, i, params):
        return strategy.execute(df, i)

    # 백테스팅 실행
    backtester = Backtester(
        initial_capital=config['backtesting']['initial_capital'],
        fee_rate=config['backtesting']['fee_rate'],
        slippage=config['backtesting']['slippage']
    )

    results = backtester.run(df, strategy_wrapper, {})

    # 평가
    metrics = Evaluator.calculate_all_metrics(results)

    # Buy&Hold 계산
    buy_hold_return = ((df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100
    metrics['buy_hold_return'] = buy_hold_return
    metrics['excess_return'] = metrics['total_return'] - buy_hold_return

    # 투표 통계
    voting_stats = strategy.get_voting_stats()

    # 결과 출력
    print(f"\n[전략 성과]")
    print(f"  초기 자본: {config['backtesting']['initial_capital']:,}원")
    print(f"  최종 자본: {results['final_capital']:,.0f}원")
    print(f"  총 수익률: {metrics['total_return']:.2f}%")

    print(f"\n[vs Buy&Hold]")
    print(f"  Buy&Hold: {buy_hold_return:.2f}%")
    print(f"  초과 수익: {metrics['excess_return']:+.2f}%p")

    print(f"\n[리스크 지표]")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {metrics['max_drawdown']:.2f}%")

    print(f"\n[거래 통계]")
    print(f"  총 거래: {metrics['total_trades']}회")
    print(f"  승률: {metrics['win_rate']:.1%}")
    print(f"  평균 수익: {metrics['avg_profit']:.2%}")
    print(f"  평균 손실: {metrics['avg_loss']:.2%}")
    print(f"  Profit Factor: {metrics['profit_factor']:.2f}")

    print(f"\n[투표 통계]")
    if voting_stats:
        print(f"  총 신호: {voting_stats['total_signals']}개")
        print(f"  매수 합의: {voting_stats['buy_consensus']}회")
        print(f"  매도 합의: {voting_stats['sell_consensus']}회")
        print(f"  합의 없음: {voting_stats['no_consensus']}회")
        print(f"  합의율: {voting_stats['consensus_rate']:.1f}%")

    return {
        'year': year,
        'metrics': metrics,
        'voting_stats': voting_stats,
        'df': df,
        'results': results
    }


def main():
    """메인 실행"""
    print("="*70)
    print("  v39 Voting Ensemble - 연도별 백테스팅")
    print("="*70)

    # Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    # 2020-2025 백테스팅
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    all_results = {}

    for year in years:
        result = run_yearly_backtest(year, config)
        if result:
            all_results[year] = result['metrics']

    # 전체 요약
    print("\n" + "="*70)
    print("  백테스팅 완료!")
    print("  결과: backtest_results.json")
    print("="*70)

    # 요약 테이블
    print("\n[연도별 요약]")
    print("    연도 |      수익률 | Buy&Hold |       초과 | Sharpe |     MDD |    거래")
    print("-" * 70)
    for year in years:
        if year in all_results:
            m = all_results[year]
            print(f"  {year} | {m['total_return']:>8.2f}% | "
                  f"{m['buy_hold_return']:>7.2f}% | "
                  f"{m['excess_return']:>+8.2f}%p | "
                  f"{m['sharpe_ratio']:>6.2f} | "
                  f"{m['max_drawdown']:>6.2f}% | "
                  f"{m['total_trades']:>5}회")

    # 결과 저장
    save_results = {
        'version': 'v39',
        'strategy_name': 'voting_ensemble',
        'backtest_date': datetime.now().isoformat(),
        'config': config,
        'results': {str(k): v for k, v in all_results.items()}
    }

    with open('backtest_results.json', 'w') as f:
        json.dump(save_results, f, indent=2, default=str)

    # 2024-2025 핵심 평가
    print("\n" + "="*70)
    print("  핵심 평가 (2024 BULL + 2025 SIDEWAYS)")
    print("="*70)

    if 2024 in all_results:
        m24 = all_results[2024]
        target_24 = config['target_performance']['2024_bull'] * 100
        status_24 = "✅" if m24['total_return'] >= target_24 else "❌"
        print(f"\n2024 BULL 시장:")
        print(f"  목표: {target_24:.0f}% | 실제: {m24['total_return']:.2f}% {status_24}")
        print(f"  Buy&Hold: {m24['buy_hold_return']:.2f}% | 초과: {m24['excess_return']:+.2f}%p")

    if 2025 in all_results:
        m25 = all_results[2025]
        target_25 = config['target_performance']['2025_sideways'] * 100
        status_25 = "✅" if m25['total_return'] >= target_25 else "❌"
        print(f"\n2025 SIDEWAYS 시장:")
        print(f"  목표: {target_25:.0f}% | 실제: {m25['total_return']:.2f}% {status_25}")
        print(f"  Buy&Hold: {m25['buy_hold_return']:.2f}% | 초과: {m25['excess_return']:+.2f}%p")

    # 연평균
    if len(all_results) > 0:
        avg_return = sum(m['total_return'] for m in all_results.values()) / len(all_results)
        avg_sharpe = sum(m['sharpe_ratio'] for m in all_results.values()) / len(all_results)
        target_avg = config['target_performance']['annual_avg'] * 100
        status_avg = "✅" if avg_return >= target_avg else "❌"

        print(f"\n연평균 ({len(all_results)}년):")
        print(f"  목표: {target_avg:.0f}% | 실제: {avg_return:.2f}% {status_avg}")
        print(f"  평균 Sharpe: {avg_sharpe:.2f}")


if __name__ == '__main__':
    main()
