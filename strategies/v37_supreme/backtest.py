#!/usr/bin/env python3
"""
v37 Supreme Backtesting
연도별 백테스팅 (2020-2025)
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

from strategies.v37_supreme.strategy import V37SupremeStrategy


def load_config(config_path='config.json'):
    """Config 로드"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config


def run_yearly_backtest(year: int, config: dict, db_path='../../upbit_bitcoin.db'):
    """연도별 백테스팅"""

    print(f"\n{'='*70}")
    print(f"  {year}년 백테스팅")
    print(f"{'='*70}")

    # 데이터 로드
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    with DataLoader(db_path) as loader:
        df = loader.load_timeframe(
            config.get('timeframe', 'day'),
            start_date=start_date,
            end_date=end_date
        )

    if df is None or len(df) == 0:
        print(f"  ❌ {year}년 데이터 없음")
        return None

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'adx', 'atr', 'bb', 'stoch', 'mfi'])

    print(f"  기간: {df.index[0]} ~ {df.index[-1]}")
    print(f"  캔들: {len(df)}개")
    print(f"  시작가: {df.iloc[0]['close']:,.0f}원")
    print(f"  종료가: {df.iloc[-1]['close']:,.0f}원")

    # 전략 설정 (config에서 필요한 값만 추출)
    strategy_config = {
        # Dynamic Thresholds
        'threshold_lookback_period': config.get('dynamic_thresholds', {}).get('threshold_lookback_period', 60),
        'rsi_oversold_quantile': config.get('dynamic_thresholds', {}).get('rsi_oversold_quantile', 0.30),
        'rsi_overbought_quantile': config.get('dynamic_thresholds', {}).get('rsi_overbought_quantile', 0.70),
        'volume_high_quantile': config.get('dynamic_thresholds', {}).get('volume_high_quantile', 0.80),
        'volatility_high_quantile': config.get('dynamic_thresholds', {}).get('volatility_high_quantile', 0.70),

        # Trend Following
        'trend_adx_threshold': config.get('trend_following', {}).get('adx_threshold', 25),
        'trend_stop_loss': config.get('trend_following', {}).get('stop_loss', -0.10),
        'trend_trailing_stop': config.get('trend_following', {}).get('trailing_stop', -0.05),
        'trend_trailing_trigger': config.get('trend_following', {}).get('trailing_trigger', 0.20),
        'trend_max_hold_days': config.get('trend_following', {}).get('max_hold_days', 90),

        # Swing Trading
        'swing_rsi_oversold': config.get('swing_trading', {}).get('rsi_oversold', 40),
        'swing_tp_1': config.get('swing_trading', {}).get('take_profit_1', 0.10),
        'swing_tp_2': config.get('swing_trading', {}).get('take_profit_2', 0.15),
        'swing_stop_loss': config.get('swing_trading', {}).get('stop_loss', -0.03),
        'swing_max_hold_days': config.get('swing_trading', {}).get('max_hold_days', 40),

        # SIDEWAYS
        'use_rsi_bb': config.get('sideways', {}).get('use_rsi_bb', True),
        'use_stoch': config.get('sideways', {}).get('use_stoch', True),
        'use_volume_breakout': config.get('sideways', {}).get('use_volume_breakout', True),
        'rsi_bb_oversold': config.get('sideways', {}).get('rsi_bb_oversold', 30),
        'rsi_bb_overbought': config.get('sideways', {}).get('rsi_bb_overbought', 70),
        'stoch_oversold': config.get('sideways', {}).get('stoch_oversold', 20),
        'stoch_overbought': config.get('sideways', {}).get('stoch_overbought', 80),
        'volume_breakout_mult': config.get('sideways', {}).get('volume_breakout_mult', 2.0),
        'sideways_position_size': config.get('sideways', {}).get('position_size', 0.4),
        'sideways_tp_1': config.get('sideways', {}).get('take_profit_1', 0.02),
        'sideways_tp_2': config.get('sideways', {}).get('take_profit_2', 0.04),
        'sideways_tp_3': config.get('sideways', {}).get('take_profit_3', 0.06),
        'sideways_stop_loss': config.get('sideways', {}).get('stop_loss', -0.02),
        'sideways_max_hold_days': config.get('sideways', {}).get('max_hold_days', 20),

        # Defensive
        'defensive_rsi_oversold': config.get('defensive', {}).get('rsi_oversold', 25),
        'defensive_position_size': config.get('defensive', {}).get('position_size', 0.2),
        'defensive_bear_strong_size': config.get('defensive', {}).get('bear_strong_size', 0.1),
        'defensive_take_profit_1': config.get('defensive', {}).get('take_profit_1', 0.05),
        'defensive_take_profit_2': config.get('defensive', {}).get('take_profit_2', 0.10),
        'defensive_stop_loss': config.get('defensive', {}).get('stop_loss', -0.05),
        'defensive_tp_bear_strong': config.get('defensive', {}).get('tp_bear_strong', 0.03),
        'defensive_max_hold_days': config.get('defensive', {}).get('max_hold_days', 20)
    }

    # 백테스팅 실행
    backtesting_config = config.get('backtesting', {})
    backtester = Backtester(
        initial_capital=backtesting_config.get('initial_capital', 10000000),
        fee_rate=backtesting_config.get('fee_rate', 0.0005),
        slippage=backtesting_config.get('slippage', 0.0002)
    )

    strategy = V37SupremeStrategy(strategy_config)

    # Backtester와 호환되도록 래퍼 함수 생성
    def strategy_wrapper(df, i, params):
        return strategy.execute(df, i)

    results = backtester.run(df, strategy_wrapper, {})

    # 평가
    metrics = Evaluator.calculate_all_metrics(results)

    # Buy&Hold 계산
    buy_hold_return = ((df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100
    metrics['buy_hold_return'] = buy_hold_return
    metrics['excess_return'] = metrics['total_return'] - buy_hold_return

    # 결과 출력
    print(f"\n[전략 성과]")
    print(f"  초기 자본: {metrics['initial_capital']:,.0f}원")
    print(f"  최종 자본: {metrics['final_capital']:,.0f}원")
    print(f"  총 수익률: {metrics['total_return']:.2f}%")

    print(f"\n[vs Buy&Hold]")
    print(f"  Buy&Hold: {metrics['buy_hold_return']:.2f}%")
    print(f"  초과 수익: {metrics['excess_return']:+.2f}%p")

    print(f"\n[리스크 지표]")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {metrics['max_drawdown']:.2f}%")

    print(f"\n[거래 통계]")
    print(f"  총 거래: {metrics['total_trades']}회")
    print(f"  승률: {metrics['win_rate']:.1f}%")
    if metrics['total_trades'] > 0:
        print(f"  평균 수익: {metrics.get('avg_profit', 0):.2f}%")
        print(f"  평균 손실: {metrics.get('avg_loss', 0):.2f}%")
        print(f"  Profit Factor: {metrics.get('profit_factor', 0):.2f}")

    # 전략 통계
    stats = strategy.get_state_statistics()
    print(f"\n[시장 분류 통계]")
    print(f"  시장 상태 전환: {stats['total_state_transitions']}회")
    print(f"  전략 전환: {stats['total_strategy_switches']}회")

    return {
        'year': year,
        'metrics': metrics,
        'strategy_stats': stats
    }


def main():
    """메인 실행"""
    print("="*70)
    print("  v37 Supreme Strategy - 연도별 백테스팅")
    print("="*70)

    # Config 로드
    config = load_config()

    # 2020-2025 연도별 백테스팅
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    all_results = {}

    for year in years:
        result = run_yearly_backtest(year, config)
        if result:
            all_results[year] = result

    # 전체 결과 저장
    output = {
        'version': 'v37',
        'strategy_name': 'supreme',
        'backtest_date': datetime.now().isoformat(),
        'config': config,
        'results': {
            str(year): {
                'total_return': result['metrics']['total_return'],
                'buy_hold_return': result['metrics']['buy_hold_return'],
                'excess_return': result['metrics']['excess_return'],
                'sharpe_ratio': result['metrics']['sharpe_ratio'],
                'max_drawdown': result['metrics']['max_drawdown'],
                'total_trades': result['metrics']['total_trades'],
                'win_rate': result['metrics']['win_rate'],
                'avg_profit': result['metrics'].get('avg_profit', 0),
                'avg_loss': result['metrics'].get('avg_loss', 0),
                'profit_factor': result['metrics'].get('profit_factor', 0)
            }
            for year, result in all_results.items()
        }
    }

    with open('backtest_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*70}")
    print(f"  백테스팅 완료!")
    print(f"  결과: backtest_results.json")
    print(f"{'='*70}\n")

    # 요약
    print("\n[연도별 요약]")
    print(f"{'연도':>6s} | {'수익률':>8s} | {'Buy&Hold':>8s} | {'초과':>8s} | {'Sharpe':>6s} | {'MDD':>7s} | {'거래':>5s}")
    print("-"*70)
    for year, result in all_results.items():
        m = result['metrics']
        print(f"{year:>6d} | {m['total_return']:>7.2f}% | {m['buy_hold_return']:>7.2f}% | "
              f"{m['excess_return']:>+7.2f}%p | {m['sharpe_ratio']:>6.2f} | "
              f"{m['max_drawdown']:>6.2f}% | {m['total_trades']:>4d}회")


if __name__ == '__main__':
    main()
