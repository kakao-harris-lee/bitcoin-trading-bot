#!/usr/bin/env python3
"""
v10 Backtest Script (Function-based)

v09에서 검증된 function-based 접근 사용
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.evaluator import Evaluator

from market_regime_detector import MarketRegimeDetector
from simple_backtester import SimpleBacktester
from adaptive_strategy import v10_strategy_function, reset_state


def run_backtest(start_date='2018-09-04', end_date='2023-12-31', config_path='config.json'):
    """
    v10 백테스트 실행

    Args:
        start_date: 시작일
        end_date: 종료일
        config_path: 설정 파일 경로

    Returns:
        dict: 백테스트 결과
    """
    # Config 로드
    with open(config_path) as f:
        config = json.load(f)

    print("="*80)
    print(f"v10 Market-Adaptive Strategy v2 Backtest")
    print("="*80)
    print(f"\n기간: {start_date} ~ {end_date}")

    # 데이터 로드
    print("\n[1/5] 데이터 로드...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(config['timeframe'], start_date=start_date, end_date=end_date)

    if len(df) == 0:
        print(f"  ❌ 데이터 없음")
        return None

    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buyhold_return = ((end_price - start_price) / start_price) * 100

    print(f"  ✅ {len(df)}개 캔들")
    print(f"  시작가: {start_price:,.0f}원")
    print(f"  종료가: {end_price:,.0f}원")
    print(f"  Buy&Hold: {buyhold_return:+.2f}%")

    # 지표 추가
    print("\n[2/5] 지표 추가...")
    df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'macd'])
    df = df.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

    # 시장 분류기
    detector = MarketRegimeDetector(config['market_detector'])
    df = detector.add_indicators(df)

    print(f"  ✅ EMA, MACD, ADX, Momentum 추가")

    # 백테스터 초기화
    print("\n[3/5] 백테스터 초기화...")
    backtester = SimpleBacktester(
        initial_capital=config['backtest']['initial_capital'],
        fee_rate=config['backtest']['fee_rate'],
        slippage=config['backtest']['slippage']
    )

    # 전략 실행
    print("\n[4/5] 전략 실행...")
    reset_state()  # 전역 상태 초기화

    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        day_price = row['close']

        # 전략 결정
        decision = v10_strategy_function(df, i, config, detector)

        # 주문 실행
        if decision['action'] == 'buy':
            backtester.execute_buy(
                timestamp=timestamp,
                price=day_price,
                fraction=decision['fraction']
            )
        elif decision['action'] == 'sell':
            backtester.execute_sell(
                timestamp=timestamp,
                price=day_price,
                fraction=decision['fraction']
            )

        # 자산 기록
        backtester.record_equity(timestamp, day_price)

    # 결과 계산
    print("\n[5/5] 결과 계산...")
    results = backtester.get_results()

    # Sharpe Ratio 계산
    equity_df = results['equity_curve']
    returns = equity_df['returns'].dropna()
    if len(returns) > 0 and returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
    else:
        sharpe = 0

    results['sharpe_ratio'] = sharpe
    results['buyhold_return'] = buyhold_return

    # 시장별 거래 분석
    regime_trades = {'bull': 0, 'sideways': 0, 'bear': 0}
    for trade in results['trades']:
        if trade.exit_time is None:
            continue
        reason = trade.reason if trade.reason else ''
        if 'BULL' in reason:
            regime_trades['bull'] += 1
        elif 'SIDEWAYS' in reason:
            regime_trades['sideways'] += 1
        elif 'BEAR' in reason:
            regime_trades['bear'] += 1

    results['regime_trades'] = regime_trades

    # 출력
    print("\n" + "="*80)
    print("백테스팅 결과")
    print("="*80)
    print(f"\n초기 자본: {results['initial_capital']:,.0f}원")
    print(f"최종 자본: {results['final_capital']:,.0f}원")
    print(f"총 수익률: {results['total_return']:+.2f}%")
    print(f"Buy&Hold:  {buyhold_return:+.2f}%")
    print(f"초과 수익: {results['total_return'] - buyhold_return:+.2f}%p")
    print(f"\nSharpe Ratio: {sharpe:.2f}")
    print(f"Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"\n총 거래: {results['total_trades']}회")
    print(f"승률: {results['win_rate']:.1%}")
    print(f"평균 수익: {results['avg_profit']:+.2f}%")
    print(f"평균 손실: {results['avg_loss']:+.2f}%")
    print(f"Profit Factor: {results['profit_factor']:.2f}")

    print(f"\n시장별 거래:")
    print(f"  Bull:     {regime_trades['bull']}회")
    print(f"  Sideways: {regime_trades['sideways']}회")
    print(f"  Bear:     {regime_trades['bear']}회")

    print("\n거래 내역:")
    for idx, trade in enumerate(results['trades'], 1):
        if trade.exit_time is None:
            continue
        print(f"{idx}. {trade.entry_time.date()} 진입 ({trade.entry_price:,.0f}원) "
              f"→ {trade.exit_time.date()} 청산 ({trade.exit_price:,.0f}원) "
              f"| {trade.profit_loss_pct:+.2f}% | {trade.reason}")

    print("="*80)

    return results


if __name__ == '__main__':
    # 2018-2023 학습
    print("\n" + "="*80)
    print("Train: 2018-09-04 ~ 2023-12-31")
    print("="*80)
    train_results = run_backtest('2018-09-04', '2023-12-31')

    # 2024 검증
    print("\n" + "="*80)
    print("Validation: 2024-01-01 ~ 2024-12-30")
    print("="*80)
    val_results = run_backtest('2024-01-01', '2024-12-30')

    # 2025 테스트
    print("\n" + "="*80)
    print("Test: 2025-01-01 ~ 2025-10-17")
    print("="*80)
    test_results = run_backtest('2025-01-01', '2025-10-17')

    # 오버피팅 분석
    if train_results and val_results and test_results:
        print("\n" + "="*80)
        print("오버피팅 분석")
        print("="*80)

        train_return = train_results['total_return']
        val_return = val_results['total_return']
        test_return = test_results['total_return']

        val_degradation = ((train_return - val_return) / train_return) * 100 if train_return != 0 else 0
        test_degradation = ((train_return - test_return) / train_return) * 100 if train_return != 0 else 0

        print(f"\nTrain (2018-2023): {train_return:+.2f}%")
        print(f"Val   (2024):      {val_return:+.2f}%")
        print(f"Test  (2025):      {test_return:+.2f}%")
        print(f"\n성능 저하 (Val):  {val_degradation:+.2f}%")
        print(f"성능 저하 (Test): {test_degradation:+.2f}%")

        if val_degradation < 60:
            print(f"\n✅ 오버피팅 통과 (<60%)")
        else:
            print(f"\n❌ 오버피팅 실패 (>= 60%)")

        # 목표 달성 여부
        print("\n" + "="*80)
        print("목표 달성 여부")
        print("="*80)

        print(f"\n2024년 수익률: {val_return:+.2f}% (목표: 130-150%)")
        if 130 <= val_return <= 150:
            print("  ✅ 달성")
        else:
            print("  ❌ 미달성")

        print(f"\n2025년 수익률: {test_return:+.2f}% (목표: 35-50%)")
        if 35 <= test_return <= 50:
            print("  ✅ 달성")
        else:
            print("  ❌ 미달성")

        print(f"\n오버피팅 지표: {val_degradation:.2f}% (목표: <60%)")
        if val_degradation < 60:
            print("  ✅ 달성")
        else:
            print("  ❌ 미달성")

        # 결과 저장
        output = {
            'train': {
                'period': '2018-09-04 ~ 2023-12-31',
                'return': train_return,
                'sharpe': train_results['sharpe_ratio'],
                'mdd': train_results['max_drawdown'],
                'trades': train_results['total_trades'],
                'win_rate': train_results['win_rate']
            },
            'validation_2024': {
                'period': '2024-01-01 ~ 2024-12-30',
                'return': val_return,
                'buyhold': val_results['buyhold_return'],
                'sharpe': val_results['sharpe_ratio'],
                'mdd': val_results['max_drawdown'],
                'trades': val_results['total_trades'],
                'win_rate': val_results['win_rate']
            },
            'test_2025': {
                'period': '2025-01-01 ~ 2025-10-17',
                'return': test_return,
                'buyhold': test_results['buyhold_return'],
                'sharpe': test_results['sharpe_ratio'],
                'mdd': test_results['max_drawdown'],
                'trades': test_results['total_trades'],
                'win_rate': test_results['win_rate']
            },
            'overfitting': {
                'val_degradation_pct': val_degradation,
                'test_degradation_pct': test_degradation,
                'passed': val_degradation < 60
            },
            'goals': {
                '2024_return': {'value': val_return, 'target': '130-150%', 'achieved': 130 <= val_return <= 150},
                '2025_return': {'value': test_return, 'target': '35-50%', 'achieved': 35 <= test_return <= 50},
                'overfitting': {'value': val_degradation, 'target': '<60%', 'achieved': val_degradation < 60}
            }
        }

        with open('backtest_results.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        print("\n결과 저장: backtest_results.json")
        print("="*80)
