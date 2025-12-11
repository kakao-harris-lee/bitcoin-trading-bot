#!/usr/bin/env python3
"""
v09 전략 하이퍼파라미터 최적화

학습 기간: 2018-09-04 ~ 2023-12-31 (5.3년)
검증 기간: 2024년 (Out-of-Sample)
테스트 기간: 2025년 (Final Test)
"""

import sys
sys.path.append('../..')

import json
import optuna
from optuna.samplers import TPESampler
from optuna.pruners import MedianPruner

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V07Strategy
from simple_backtester import SimpleBacktester


def run_backtest_with_params(params: dict, start_date: str, end_date: str) -> dict:
    """
    주어진 파라미터로 백테스팅 실행

    Args:
        params: 전략 파라미터
        start_date: 시작일
        end_date: 종료일

    Returns:
        백테스팅 결과
    """
    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date=start_date, end_date=end_date)

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'macd'])

    # v07 호환성을 위한 컬럼명 변경
    df = df.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

    # 백테스팅
    backtester = SimpleBacktester(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002
    )

    strategy = V07Strategy(params)

    # 수동 루프 (v07 패턴)
    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        price = row['close']

        # 전략 결정
        decision = strategy.decide(df, i)

        # 실행
        if decision['action'] == 'buy':
            fraction = decision.get('fraction', 0.95)
            if backtester.execute_buy(timestamp, price, fraction):
                strategy.on_buy(backtester.position, price)

        elif decision['action'] == 'sell':
            fraction = decision.get('fraction', 1.0)
            reason = decision.get('reason', '')
            if backtester.execute_sell(timestamp, price, fraction, reason):
                strategy.on_sell(backtester.position, price)

        # 자산 기록
        backtester.record_equity(timestamp, price)

    # 결과
    results = backtester.get_results()

    # Sharpe Ratio 계산
    import numpy as np
    returns = results['equity_curve']['returns'].dropna()
    if len(returns) > 0 and returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)  # Annualized
    else:
        sharpe = 0

    results['sharpe_ratio'] = sharpe

    return results


def objective(trial: optuna.Trial) -> float:
    """
    Optuna 목적 함수

    Args:
        trial: Optuna trial 객체

    Returns:
        최대화할 점수
    """
    # 파라미터 샘플링 (v07 config 구조에 맞춤)
    params = {
        'indicators': {
            'ema_fast': 12,
            'ema_slow': 26,
            'macd_fast': trial.suggest_int('macd_fast', 10, 15),
            'macd_slow': trial.suggest_int('macd_slow', 20, 30),
            'macd_signal': trial.suggest_int('macd_signal', 7, 11)
        },
        'entry': {
            'use_ema_golden_cross': True,
            'use_macd_golden_cross': True,
            'allow_multiple_positions': False
        },
        'exit': {
            'trailing_stop_pct': trial.suggest_float('trailing_stop_pct', 0.08, 0.25),
            'stop_loss_pct': trial.suggest_float('stop_loss_pct', 0.08, 0.20)
        },
        'position': {
            'position_fraction': 0.95
        }
    }

    # 백테스팅 (2018-09-04 ~ 2023-12-31)
    try:
        results = run_backtest_with_params(params, '2018-09-04', '2023-12-31')
    except Exception as e:
        print(f"Trial {trial.number} 실패: {e}")
        return -999

    # 제약 조건 체크
    if results['total_trades'] < 3:
        return -999  # 거래 너무 적음

    if results['sharpe_ratio'] < 0.5:
        return -999  # Sharpe 너무 낮음

    if results['max_drawdown'] > 40:
        return -999  # MDD 너무 높음

    # 다중 목표 최적화
    return_score = results['total_return'] / 150  # 목표 150% (5년 기준)
    sharpe_score = results['sharpe_ratio'] / 1.5  # 목표 1.5
    mdd_penalty = max(0, results['max_drawdown'] - 30) / 10  # MDD > 30% 패널티

    # 가중 합산
    score = (
        0.5 * return_score +     # 수익률 50%
        0.3 * sharpe_score -     # Sharpe 30%
        0.2 * mdd_penalty        # MDD 패널티 20%
    )

    # 진행 상황 출력
    print(f"\n--- Trial {trial.number} ---")
    print(f"  Params: trailing={params['trailing_stop_pct']:.2f}, "
          f"stop_loss={params['stop_loss_pct']:.2f}, "
          f"macd=({params['macd_fast']},{params['macd_slow']},{params['macd_signal']})")
    print(f"  Return: {results['total_return']:.2f}%, "
          f"Sharpe: {results['sharpe_ratio']:.2f}, "
          f"MDD: {results['max_drawdown']:.2f}%")
    print(f"  Trades: {results['total_trades']}, Win Rate: {results['win_rate']:.1%}")
    print(f"  Score: {score:.4f}")

    return score


def main():
    """최적화 실행"""
    print("="*80)
    print("v09 전략 하이퍼파라미터 최적화")
    print("="*80)
    print(f"\n학습 기간: 2018-09-04 ~ 2023-12-31 (5.3년)")
    print(f"Trials: 300회")
    print(f"최적화 목표: 수익률 최대화 + Sharpe 개선 + MDD 최소화\n")

    # Optuna Study
    study = optuna.create_study(
        direction='maximize',
        sampler=TPESampler(seed=42),
        pruner=MedianPruner(n_startup_trials=10, n_warmup_steps=5)
    )

    # 최적화 실행
    study.optimize(objective, n_trials=300, show_progress_bar=True)

    # 최적 파라미터
    print("\n" + "="*80)
    print("최적화 완료")
    print("="*80)

    best_params = study.best_params
    best_value = study.best_value

    print(f"\n최고 점수: {best_value:.4f}")
    print(f"\n최적 파라미터:")
    for key, value in best_params.items():
        print(f"  {key}: {value}")

    # 최적 파라미터로 재실행 (상세 결과)
    print(f"\n최적 파라미터로 재실행 중...")

    full_params = {
        **best_params,
        'position_fraction': 0.95,
        'ema_fast': 12,
        'ema_slow': 26
    }

    results_train = run_backtest_with_params(full_params, '2018-09-04', '2023-12-31')

    print(f"\n=== 학습 데이터 성과 (2018-09-04 ~ 2023-12-31) ===")
    print(f"수익률: {results_train['total_return']:.2f}%")
    print(f"Sharpe Ratio: {results_train['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results_train['max_drawdown']:.2f}%")
    print(f"총 거래: {results_train['total_trades']}회")
    print(f"승률: {results_train['win_rate']:.1%}")
    print(f"Profit Factor: {results_train.get('profit_factor', 0):.2f}")

    # 2024년 검증
    print(f"\n2024년 Out-of-Sample 검증 중...")
    results_2024 = run_backtest_with_params(full_params, '2024-01-01', '2024-12-31')

    print(f"\n=== 2024년 검증 성과 (Out-of-Sample) ===")
    print(f"수익률: {results_2024['total_return']:.2f}%")
    print(f"Sharpe Ratio: {results_2024['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results_2024['max_drawdown']:.2f}%")
    print(f"총 거래: {results_2024['total_trades']}회")
    print(f"승률: {results_2024['win_rate']:.1%}")

    # Buy&Hold 비교
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df_2024 = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    bh_return_2024 = ((df_2024.iloc[-1]['close'] - df_2024.iloc[0]['close']) / df_2024.iloc[0]['close']) * 100

    print(f"\nBuy&Hold (2024): {bh_return_2024:.2f}%")
    print(f"초과 수익: {results_2024['total_return'] - bh_return_2024:+.2f}%p")

    # 2025년 테스트
    print(f"\n2025년 Final Test 중...")
    results_2025 = run_backtest_with_params(full_params, '2025-01-01', '2025-10-17')

    print(f"\n=== 2025년 테스트 성과 (Final Test) ===")
    print(f"수익률: {results_2025['total_return']:.2f}%")
    print(f"Sharpe Ratio: {results_2025['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results_2025['max_drawdown']:.2f}%")
    print(f"총 거래: {results_2025['total_trades']}회")
    print(f"승률: {results_2025['win_rate']:.1%}")

    # Buy&Hold 비교
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df_2025 = loader.load_timeframe('day', start_date='2025-01-01', end_date='2025-10-17')

    bh_return_2025 = ((df_2025.iloc[-1]['close'] - df_2025.iloc[0]['close']) / df_2025.iloc[0]['close']) * 100

    print(f"\nBuy&Hold (2025): {bh_return_2025:.2f}%")
    print(f"초과 수익: {results_2025['total_return'] - bh_return_2025:+.2f}%p")

    # 오버피팅 분석
    degradation = ((results_2024['total_return'] - results_2025['total_return']) / results_2024['total_return']) * 100 if results_2024['total_return'] > 0 else 0

    print(f"\n=== 오버피팅 분석 ===")
    print(f"2024년: {results_2024['total_return']:.2f}%")
    print(f"2025년: {results_2025['total_return']:.2f}%")
    print(f"성능 저하: {degradation:.2f}%")

    if degradation < 70:
        print(f"✅ 목표 달성 (< 70%)")
    else:
        print(f"❌ 목표 미달 (>= 70%)")

    # 결과 저장
    output = {
        'best_params': full_params,
        'best_score': float(best_value),
        'train_results': {
            'period': '2018-09-04 ~ 2023-12-31',
            'total_return': float(results_train['total_return']),
            'sharpe_ratio': float(results_train['sharpe_ratio']),
            'max_drawdown': float(results_train['max_drawdown']),
            'total_trades': int(results_train['total_trades']),
            'win_rate': float(results_train['win_rate'])
        },
        '2024_validation': {
            'total_return': float(results_2024['total_return']),
            'sharpe_ratio': float(results_2024['sharpe_ratio']),
            'max_drawdown': float(results_2024['max_drawdown']),
            'buyhold_return': float(bh_return_2024),
            'excess_return': float(results_2024['total_return'] - bh_return_2024)
        },
        '2025_test': {
            'total_return': float(results_2025['total_return']),
            'sharpe_ratio': float(results_2025['sharpe_ratio']),
            'max_drawdown': float(results_2025['max_drawdown']),
            'buyhold_return': float(bh_return_2025),
            'excess_return': float(results_2025['total_return'] - bh_return_2025)
        },
        'overfitting': {
            'degradation_pct': float(degradation),
            'passed': degradation < 70
        }
    }

    with open('optuna_results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n결과 저장: optuna_results.json")

    # config.json 업데이트
    with open('config.json', 'r') as f:
        config = json.load(f)

    config.update(full_params)

    with open('config_optimized.json', 'w') as f:
        json.dump(config, f, indent=2)

    print(f"최적 파라미터 저장: config_optimized.json\n")


if __name__ == '__main__':
    main()
