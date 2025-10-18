#!/usr/bin/env python3
"""
v08 Market-Adaptive Strategy Backtest

2024년 백테스팅 및 2025년 Out-of-Sample 검증
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.evaluator import Evaluator
from simple_backtester import SimpleBacktester

from strategy import V08Strategy, v08_strategy_wrapper
from market_regime_detector import MarketRegimeDetector


def run_backtest(
    start_date: str = '2024-01-01',
    end_date: str = '2024-12-31',
    config_path: str = 'config.json'
):
    """
    v08 전략 백테스팅

    Args:
        start_date: 시작일
        end_date: 종료일
        config_path: config 경로
    """
    print("="*80)
    print("v08 Market-Adaptive Strategy Backtest")
    print("="*80)

    # === 1. Config 로드 ===
    with open(config_path, 'r') as f:
        config = json.load(f)

    timeframe = config['timeframe']

    print(f"\n[1/7] Config 로드")
    print(f"  전략: {config['strategy_name']} ({config['version']})")
    print(f"  타임프레임: {timeframe}")
    print(f"  기간: {start_date} ~ {end_date}")
    print(f"\n  시장 분류 파라미터:")
    print(f"    ADX Threshold: {config['market_detector']['adx_threshold']}")
    print(f"    Transition Days: {config['market_detector']['transition_days']}")
    print(f"\n  Bull 파라미터:")
    print(f"    Position: {config['bull_params']['position_fraction']:.0%}")
    print(f"    Trailing Stop: {config['bull_params']['trailing_stop_pct']:.0%}")
    print(f"    Stop Loss: {config['bull_params']['stop_loss_pct']:.0%}")
    print(f"\n  Sideways 파라미터:")
    print(f"    Position: {config['sideways_params']['position_fraction']:.0%}")
    print(f"    Trailing Stop: {config['sideways_params']['trailing_stop_pct']:.0%}")
    print(f"    Stop Loss: {config['sideways_params']['stop_loss_pct']:.0%}")

    # === 2. 데이터 로드 ===
    print(f"\n[2/7] 데이터 로드")

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            timeframe,
            start_date=start_date,
            end_date=end_date
        )

    print(f"  캔들: {len(df):,}개")
    print(f"  시작: {df.iloc[0]['timestamp']} (종가 {df.iloc[0]['close']:,.0f}원)")
    print(f"  종료: {df.iloc[-1]['timestamp']} (종가 {df.iloc[-1]['close']:,.0f}원)")

    # === 3. 지표 추가 ===
    print(f"\n[3/7] 지표 추가")

    df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'macd', 'adx'])

    # EMA 12/26 추가 (시장 분류용)
    df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()

    print(f"  추가 완료: EMA(12,26), MACD, ADX")

    # === 4. 시장 분류 ===
    print(f"\n[4/7] 시장 상황 분류")

    detector = MarketRegimeDetector(config['market_detector'])
    df = detector.add_indicators(df)

    regimes = []
    for i in range(len(df)):
        regime = detector.detect(df, i)
        regimes.append(regime)

    df['regime'] = regimes

    bull_count = (df['regime'] == 'bull').sum()
    sideways_count = (df['regime'] == 'sideways').sum()
    bear_count = (df['regime'] == 'bear').sum()
    total = len(df)

    print(f"  Bull (상승장):    {bull_count:>4}일 ({bull_count/total*100:>5.1f}%)")
    print(f"  Sideways (횡보장): {sideways_count:>4}일 ({sideways_count/total*100:>5.1f}%)")
    print(f"  Bear (하락장):    {bear_count:>4}일 ({bear_count/total*100:>5.1f}%)")

    # === 5. 전략 인스턴스 생성 ===
    print(f"\n[5/7] 전략 초기화")
    strategy = V08Strategy(config)

    # === 6. 백테스팅 실행 ===
    print(f"\n[6/7] 백테스팅 실행")

    backtester = SimpleBacktester(
        initial_capital=config['trading']['initial_capital'],
        fee_rate=config['trading']['fee_rate'],
        slippage=config['trading']['slippage']
    )

    strategy_params = {
        'strategy_instance': strategy,
        'backtester': backtester
    }

    results = backtester.run(
        df,
        v08_strategy_wrapper,
        strategy_params
    )

    # === 7. 성과 평가 ===
    print(f"\n[7/7] 성과 평가")

    # Buy&Hold 기준선
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buyhold_return = ((end_price - start_price) / start_price) * 100

    # 전략 성과
    metrics = Evaluator.calculate_all_metrics(results)

    # 시장별 거래 분석
    trades = results.get('trades', [])
    regime_trades = {'bull': [], 'sideways': [], 'bear': []}

    for trade in trades:
        if trade.exit_time is None:
            continue
        # 진입 시점의 시장 상황 찾기
        entry_idx = df[df['timestamp'] == trade.entry_time].index
        if len(entry_idx) > 0:
            regime = df.iloc[entry_idx[0]]['regime']
            regime_trades[regime].append(trade)

    # === 결과 출력 ===
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)

    print(f"\n=== 백테스팅 기간 ===")
    print(f"타임프레임: {timeframe}")
    print(f"시작: {df.iloc[0]['timestamp'].date()} (시작가: {start_price:,.0f}원)")
    print(f"종료: {df.iloc[-1]['timestamp'].date()} (종료가: {end_price:,.0f}원)")
    print(f"기간: {(df.iloc[-1]['timestamp'] - df.iloc[0]['timestamp']).days}일 | 캔들: {len(df):,}개")

    print(f"\n=== Buy&Hold 기준선 ===")
    print(f"수익률: {buyhold_return:+.2f}%")

    # 타임프레임별 목표
    targets = {
        'day': 157.49
    }
    target_return = targets.get(timeframe, buyhold_return + 20)
    print(f"목표: {target_return:+.2f}% (Buy&Hold + 20%p)")

    print(f"\n=== 전략 성과 ===")
    print(f"초기 자본: {metrics['initial_capital']:,.0f}원")
    print(f"최종 자본: {metrics['final_capital']:,.0f}원")
    print(f"절대 수익: {metrics['final_capital'] - metrics['initial_capital']:+,.0f}원")
    print(f"수익률: {metrics['total_return']:+.2f}%")
    print(f"vs Buy&Hold: {metrics['total_return'] - buyhold_return:+.2f}%p")

    # 목표 달성 여부
    achieved_target = "✅" if metrics['total_return'] >= target_return else "❌"
    achieved_bh = "✅" if metrics['total_return'] >= buyhold_return else "❌"
    print(f"\n목표 달성: {achieved_target} ({metrics['total_return']:.2f}% vs {target_return:.2f}%)")
    print(f"Buy&Hold 초과: {achieved_bh} ({metrics['total_return']:.2f}% vs {buyhold_return:.2f}%)")

    print(f"\n=== 리스크 지표 ===")
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= 1.2 else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= 25.0 else "❌"
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f} (목표 >= 1.2) {sharpe_ok}")
    print(f"Max Drawdown: {metrics['max_drawdown']:.2f}% (목표 <= 25%) {mdd_ok}")
    print(f"Sortino Ratio: {metrics.get('sortino_ratio', 0):.2f}")

    print(f"\n=== 거래 통계 ===")
    print(f"총 거래: {metrics['total_trades']}회 | 승률: {metrics['win_rate']:.1%}")

    if metrics['total_trades'] > 0:
        print(f"승리 거래: {metrics.get('winning_trades', 0)}회")
        print(f"패배 거래: {metrics.get('losing_trades', 0)}회")
        print(f"평균 수익: {metrics.get('avg_profit', 0):,.0f}원")
        print(f"평균 손실: {metrics.get('avg_loss', 0):,.0f}원")
        print(f"Profit Factor: {metrics.get('profit_factor', 0):.2f}")

    # 시장별 거래 통계
    print(f"\n=== 시장별 거래 통계 ===")
    for regime_type in ['bull', 'sideways', 'bear']:
        regime_t = regime_trades[regime_type]
        if len(regime_t) == 0:
            print(f"{regime_type.upper()}: 거래 없음")
            continue

        regime_winning = [t for t in regime_t if t.profit_loss > 0]
        regime_losing = [t for t in regime_t if t.profit_loss <= 0]
        regime_win_rate = len(regime_winning) / len(regime_t) if regime_t else 0
        total_pnl = sum(t.profit_loss for t in regime_t)

        print(f"{regime_type.upper()}: {len(regime_t)}회 거래, 승률 {regime_win_rate:.1%}, 총 손익 {total_pnl:+,.0f}원")

    print(f"\n=== 종합 평가 ===")
    print(f"{achieved_target} 수익률 >= 목표 ({target_return:.2f}%)")
    print(f"{achieved_bh} 수익률 >= Buy&Hold")
    print(f"{sharpe_ok} Sharpe Ratio >= 1.2")
    print(f"{mdd_ok} Max Drawdown <= 25%")

    print("\n" + "="*80)

    # === 8. 거래 내역 출력 (최근 10개) ===
    if metrics['total_trades'] > 0:
        print("\n=== 거래 내역 (최근 10개) ===")
        for idx, trade in enumerate(trades[-10:], 1):
            print(f"{idx}. Entry: {trade.entry_time.date()} @ {trade.entry_price:,.0f}원")
            if trade.exit_time:
                print(f"   Exit:  {trade.exit_time.date()} @ {trade.exit_price:,.0f}원")
                print(f"   P&L:   {trade.profit_loss:+,.0f}원 ({trade.profit_loss_pct:+.2f}%)")
                print(f"   Reason: {trade.reason}")
            print()

    # === 9. 결과 저장 ===
    result_data = {
        'version': config['version'],
        'strategy_name': config['strategy_name'],
        'timeframe': timeframe,
        'period': {'start': start_date, 'end': end_date},
        'buyhold_return': buyhold_return,
        'target_return': target_return,
        'metrics': metrics,
        'config': config,
        'market_stats': {
            'bull_days': int(bull_count),
            'sideways_days': int(sideways_count),
            'bear_days': int(bear_count),
            'bull_pct': float(bull_count / total),
            'sideways_pct': float(sideways_count / total),
            'bear_pct': float(bear_count / total)
        },
        'regime_trades': {
            'bull': len(regime_trades['bull']),
            'sideways': len(regime_trades['sideways']),
            'bear': len(regime_trades['bear'])
        },
        'timestamp': datetime.now().isoformat()
    }

    result_filename = f'results_{timeframe}_{start_date[:4]}.json'
    with open(result_filename, 'w') as f:
        json.dump(result_data, f, indent=2, default=str)

    print(f"결과 저장: {result_filename}\n")

    return result_data


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2024-01-01', help='시작일')
    parser.add_argument('--end', default='2024-12-31', help='종료일')
    parser.add_argument('--config', default='config.json', help='config 파일')

    args = parser.parse_args()

    run_backtest(
        start_date=args.start,
        end_date=args.end,
        config_path=args.config
    )
